# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Round 2 tests: local-LLM context detection and streaming lifecycle."""

from __future__ import annotations

import asyncio
import os
import threading
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from crp_comply.agent.llm import ComplianceLLM
from crp_comply.agent.worker_adapter import WorkerAdapter
from crp_comply.api.worker_registry import (
    WorkerOfflineError,
    WorkerStreamingError,
    WorkerTimeoutError,
    WorkerRegistry,
)


class _FakeOpenAIAdapter:
    """Minimal stand-in for crp.providers.OpenAIAdapter."""

    def __init__(self, base_url: str, context_window: int = 8192) -> None:
        self.base_url = base_url
        self._context_window = context_window

    def context_window_size(self) -> int:
        return self._context_window


def test_probe_loaded_context_length_caches_and_returns_min():
    from crp_comply.agent.llm import _probe_loaded_context_length

    base_url = "http://localhost:1234/v1"
    fake_response = {
        "data": [
            {"id": "model-a", "loaded_context_length": 4096},
            {"id": "model-b", "loaded_context_length": 8192},
        ]
    }
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = fake_response
        first = _probe_loaded_context_length(base_url, "local")
        second = _probe_loaded_context_length(base_url, "local")
        assert first == 4096
        assert second == 4096
        # Cache should prevent a second HTTP call.
        assert mock_get.call_count == 1


def test_compliance_llm_context_window_caps_to_loaded_length():
    adapter = _FakeOpenAIAdapter("http://localhost:1234/v1", context_window=131072)
    llm = ComplianceLLM(provider=adapter)
    # Simulate a successful probe of a smaller loaded window.
    llm._probed_context_window = 4096
    assert llm.context_window_size() == 4096


def test_compliance_llm_context_window_falls_back_to_provider():
    adapter = _FakeOpenAIAdapter("http://localhost:1234/v1", context_window=8192)
    with patch.object(ComplianceLLM, "_probe_context_window"):
        llm = ComplianceLLM(provider=adapter)
        # No probe set; should fall back to provider's declared window.
        assert llm.context_window_size() == 8192


def test_worker_adapter_streaming_raises_explicit_error():
    """WorkerAdapter must not silently fall back to blocking on streaming failure."""
    adapter = WorkerAdapter(user_id="u1")

    def _failing_dispatch_streaming(*args, **kwargs):
        raise WorkerOfflineError("worker gone")

    with patch.object(adapter, "_dispatch_streaming", side_effect=_failing_dispatch_streaming):
        with pytest.raises(WorkerStreamingError):
            adapter.generate_chat_with_tools_streaming(
                messages=[{"role": "user", "content": "hi"}],
                tools=[],
            )


def test_worker_registry_stream_watchdog_raises_on_stall():
    """If no stream frame arrives within the watchdog window, the caller gets a
    clear timeout error instead of hanging for the full 600s worker timeout."""
    reg = WorkerRegistry()
    reg._loop = MagicMock()

    fake_ws = MagicMock()
    fake_ws.send_json = MagicMock(return_value=None)

    def _fake_run_coroutine_threadsafe(coro, loop):
        # Execute the local send coroutine in a fresh loop so it is awaited.
        new_loop = asyncio.new_event_loop()
        try:
            new_loop.run_until_complete(coro)
        except Exception:  # noqa: BLE001
            pass
        finally:
            new_loop.close()
        # The real run_coroutine_threadsafe returns a concurrent.futures.Future,
        # but the caller only calls .result(timeout=...) on it.
        from concurrent.futures import Future as ConcurrentFuture

        fut: ConcurrentFuture[Any] = ConcurrentFuture()
        fut.set_result(None)
        return fut

    with patch.object(reg, "_slots", {"u1": MagicMock(ws=fake_ws, in_flight=0, total_calls=0)}):
        with patch("asyncio.run_coroutine_threadsafe", side_effect=_fake_run_coroutine_threadsafe):
            # The implementation floors the watchdog at 1s; set the env value
            # below that to verify the floor is applied and the test returns
            # quickly (~1s) rather than hanging for the full worker timeout.
            with patch.dict(os.environ, {"CRP_COMPLY_STREAM_WATCHDOG_S": "0.05"}):
                caught: list[Exception] = []

                def _call():
                    try:
                        reg.dispatch_streaming_from_sync(
                            "u1",
                            {"endpoint": "/v1/chat/completions", "stream": True},
                            timeout=600.0,
                            on_chunk=lambda x: None,
                        )
                    except Exception as exc:  # noqa: BLE001
                        caught.append(exc)

                t = threading.Thread(target=_call)
                t.start()
                t.join(timeout=5.0)
                assert not t.is_alive(), "dispatch_streaming_from_sync did not return"
                assert caught
                assert isinstance(caught[0], WorkerTimeoutError)
                assert "stalled" in str(caught[0])


# ── Provider diagnostics for local_worker ─────────────────────────────


@pytest.mark.anyio
async def test_provider_test_handles_local_worker_not_connected(monkeypatch):
    from crp_comply.api.provider import test_provider

    class _FakeStore:
        def get(self, user_id):
            return {"provider": "local_worker", "model": "llama3.1:8b"}

    monkeypatch.setattr("crp_comply.api.provider.get_provider_store", lambda: _FakeStore())
    result = await test_provider(user_id="u1")
    assert result.provider == "local_worker"
    assert result.success is False
    assert "SDK worker" in (result.error or "")


@pytest.mark.anyio
async def test_provider_test_handles_local_worker_connected(monkeypatch):
    from crp_comply.api.provider import test_provider

    class _FakeStore:
        def get(self, user_id):
            return {"provider": "local_worker", "model": "llama3.1:8b"}

    class _FakeReg:
        def is_attached(self, user_id):
            return True

        def status(self, user_id):
            return {
                "attached": True,
                "llm_reachable": True,
                "llm_models": ["llama3.1:8b"],
                "llm_error": None,
            }

    monkeypatch.setattr("crp_comply.api.provider.get_provider_store", lambda: _FakeStore())
    monkeypatch.setattr("crp_comply.api.worker_registry.get_worker_registry", lambda: _FakeReg())
    result = await test_provider(user_id="u1")
    assert result.provider == "local_worker"
    assert result.success is True
    assert "llama3.1:8b" in result.models


@pytest.mark.anyio
async def test_provider_diagnose_handles_local_worker(monkeypatch):
    from crp_comply.api.provider import provider_diagnose

    class _FakeStore:
        def get(self, user_id):
            return {"provider": "local_worker", "model": "llama3.1:8b"}

    class _FakeReg:
        def is_attached(self, user_id):
            return True

        def status(self, user_id):
            return {
                "attached": True,
                "llm_reachable": True,
                "llm_models": ["llama3.1:8b"],
                "llm_model_context": {"llama3.1:8b": 4096},
                "llm_error": None,
            }

    monkeypatch.setattr("crp_comply.api.provider.get_provider_store", lambda: _FakeStore())
    monkeypatch.setattr("crp_comply.api.worker_registry.get_worker_registry", lambda: _FakeReg())
    result = await provider_diagnose(user_id="u1")
    assert result["provider"] == "local_worker"
    assert result["live_probe"]["ok"] is True
    assert result["worker_status"]["model_context"]["llama3.1:8b"] == 4096


# ── End-to-end worker-adapter/registry path (no real WebSocket) ───────


@pytest.mark.anyio
async def test_worker_adapter_uses_registry_context_window():
    """WorkerAdapter.context_window_size() returns the loaded context length
    reported by the worker's hello/health frames."""
    from crp_comply.api.worker_registry import _WorkerSlot, get_worker_registry

    reg = get_worker_registry()
    reg._loop = asyncio.get_event_loop()
    fake_ws = MagicMock()
    reg._slots["u1"] = _WorkerSlot(
        user_id="u1",
        ws=fake_ws,
        upstream_model_context={"llama3.1:8b": 4096},
    )
    adapter = WorkerAdapter(user_id="u1", model="llama3.1:8b")
    assert adapter.context_window_size() == 4096
    del reg._slots["u1"]


@pytest.mark.anyio
async def test_worker_adapter_dispatches_through_registry():
    """A chat-with-tools call forwarded through the registry returns the
    worker's response payload in the ChatProvider tuple shape."""
    from crp_comply.api.worker_registry import _WorkerSlot, get_worker_registry

    reg = get_worker_registry()
    fake_ws = MagicMock()
    reg._slots["u1"] = _WorkerSlot(user_id="u1", ws=fake_ws)

    adapter = WorkerAdapter(user_id="u1", model="llama3.1:8b")

    def _fake_dispatch(payload, timeout=None):
        return {
            "choices": [
                {
                    "message": {"role": "assistant", "content": "hello from worker"},
                    "finish_reason": "stop",
                }
            ]
        }

    with patch.object(adapter, "_dispatch", side_effect=_fake_dispatch):
        text, reason, tool_calls, raw = adapter.generate_chat_with_tools(
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
        )
    assert text == "hello from worker"
    assert reason == "stop"
    del reg._slots["u1"]


# ── CRP per-slot context budget (n_parallel) ──────────────────────────


def test_worker_registry_parses_model_context_per_slot():
    """Hello/health frames can carry a per-slot context budget for LM Studio
    parallel slots; the registry must expose it in status()."""
    reg = WorkerRegistry()
    fake_ws = MagicMock()
    asyncio.run(reg.attach("u-slot", fake_ws))
    asyncio.run(
        reg.receive(
            "u-slot",
            {
                "type": "hello",
                "upstream_reachable": True,
                "models": ["m1", "m1:2"],
                "model_context": {"m1": 4096, "m1:2": 4096},
                "model_context_per_slot": {"m1": 2048, "m1:2": 2048},
                "n_parallel": 2,
                "upstream_kind": "lmstudio",
            },
        )
    )
    status = reg.status("u-slot")
    assert status["llm_model_context"]["m1"] == 4096
    assert status["llm_model_context_per_slot"]["m1"] == 2048
    assert status["llm_n_parallel"] == 2
    asyncio.run(reg.detach("u-slot"))


def test_worker_adapter_uses_per_slot_context():
    """When the registry reports a per-slot context, WorkerAdapter budgets
    against it rather than the raw loaded length."""
    reg = WorkerRegistry()
    fake_ws = MagicMock()
    asyncio.run(reg.attach("u-ctx", fake_ws))
    asyncio.run(
        reg.receive(
            "u-ctx",
            {
                "type": "hello",
                "upstream_reachable": True,
                "models": ["m1"],
                "model_context": {"m1": 4096},
                "model_context_per_slot": {"m1": 1024},
                "n_parallel": 4,
                "upstream_kind": "lmstudio",
            },
        )
    )
    adapter = WorkerAdapter(user_id="u-ctx")
    with patch("crp_comply.agent.worker_adapter.get_worker_registry", return_value=reg):
        assert adapter.context_window_size() == 1024
    asyncio.run(reg.detach("u-ctx"))


def test_worker_adapter_falls_back_to_env_parallel_division():
    """Without per-slot reporting, the adapter divides raw context by the
    operator-supplied CRP_COMPLY_WORKER_N_PARALLEL."""
    reg = WorkerRegistry()
    fake_ws = MagicMock()
    asyncio.run(reg.attach("u-env", fake_ws))
    asyncio.run(
        reg.receive(
            "u-env",
            {
                "type": "hello",
                "upstream_reachable": True,
                "models": ["m1"],
                "model_context": {"m1": 4096},
                "upstream_kind": "lmstudio",
            },
        )
    )
    adapter = WorkerAdapter(user_id="u-env")
    with patch("crp_comply.agent.worker_adapter.get_worker_registry", return_value=reg):
        with patch.dict(os.environ, {"CRP_COMPLY_WORKER_N_PARALLEL": "4"}):
            assert adapter.context_window_size() == 1024
    asyncio.run(reg.detach("u-env"))


def test_worker_adapter_env_parallel_defaults_to_one():
    """If no per-slot reporting and no env override, the adapter uses the raw
    context window unchanged (n_parallel defaults to 1)."""
    reg = WorkerRegistry()
    fake_ws = MagicMock()
    asyncio.run(reg.attach("u-def", fake_ws))
    asyncio.run(
        reg.receive(
            "u-def",
            {
                "type": "hello",
                "upstream_reachable": True,
                "models": ["m1"],
                "model_context": {"m1": 4096},
                "upstream_kind": "lmstudio",
            },
        )
    )
    adapter = WorkerAdapter(user_id="u-def")
    with patch("crp_comply.agent.worker_adapter.get_worker_registry", return_value=reg):
        assert adapter.context_window_size() == 4096
    asyncio.run(reg.detach("u-def"))
