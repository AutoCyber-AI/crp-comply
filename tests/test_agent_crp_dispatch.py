"""Tests for :class:`crp_comply.agent.crp_dispatch.CrpDispatcher`.

These tests verify that Round 1's CRP dispatcher facade correctly delegates
to CRP primitives and falls back gracefully when CRP is thin/unavailable.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from crp_comply.agent.crp_dispatch import CrpDispatcher


class _FakeProvider:
    """Minimal provider stand-in for dispatcher tests."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def generate_chat_with_tools(self, messages, tools, **kwargs):
        self.calls.append({"messages": messages, "tools": tools, "kwargs": kwargs})
        return "final", "stop", [], {}

    def context_window_size(self) -> int:
        return 8192


class _FakeContinuationManager:
    """Stand-in that records stitched windows."""

    def __init__(self) -> None:
        self.windows: list[list[str]] | None = None

    def stitch(self, windows: list[str]) -> Any:
        self.windows = windows
        return type("R", (), {"text": "\n".join(windows)})()


def test_compute_envelope_budget_returns_non_negative():
    provider = _FakeProvider()
    disp = CrpDispatcher(provider, system_prompt="sys")
    budget = disp.compute_envelope_budget(
        context_window=4096,
        system_tokens=1300,
        task_tokens=200,
        max_output_tokens=384,
    )
    assert isinstance(budget, int)
    assert budget >= 0


def test_continue_truncated_stops_on_stop_reason():
    provider = _FakeProvider()
    disp = CrpDispatcher(provider, system_prompt="sys")
    # Patch the continuation manager so we don't need a real CRP install.
    fake_cm = _FakeContinuationManager()
    disp._continuation_manager = fake_cm

    calls: list[str] = []

    def continue_fn(last: str) -> tuple[str, str | None]:
        calls.append(last)
        return ("second window", "stop")

    outcome = disp.continue_truncated(
        "first window",
        continue_fn=continue_fn,
        max_windows=4,
    )

    assert outcome["final_text"] == "first window\nsecond window"
    assert outcome["windows"] == 2
    assert outcome["termination_reason"] == "stop"
    assert outcome["stitched"] is True
    assert fake_cm.windows == ["first window", "second window"]


def test_continue_truncated_respects_max_windows():
    provider = _FakeProvider()
    disp = CrpDispatcher(provider, system_prompt="sys")
    fake_cm = _FakeContinuationManager()
    disp._continuation_manager = fake_cm

    def continue_fn(last: str) -> tuple[str, str | None]:
        return ("more", "length")

    outcome = disp.continue_truncated(
        "first",
        continue_fn=continue_fn,
        max_windows=2,
    )

    assert outcome["windows"] == 2
    assert outcome["termination_reason"] == "max_windows"


def test_continue_truncated_empty_first_window():
    provider = _FakeProvider()
    disp = CrpDispatcher(provider, system_prompt="sys")
    outcome = disp.continue_truncated(
        "",
        continue_fn=lambda last: ("x", "stop"),
        max_windows=4,
    )
    assert outcome["windows"] == 0
    assert outcome["termination_reason"] == "empty"


def test_dispatch_turn_delegates_to_provider():
    provider = _FakeProvider()
    disp = CrpDispatcher(provider, system_prompt="sys")
    messages = [{"role": "user", "content": "hi"}]
    tools = [{"type": "function", "function": {"name": "echo"}}]
    result = disp.dispatch_turn(messages, tools, max_tokens=100)
    assert result == ("final", "stop", [], {})
    assert len(provider.calls) == 1
    assert provider.calls[0]["messages"] == messages
    assert provider.calls[0]["tools"] == tools
    assert provider.calls[0]["kwargs"]["max_tokens"] == 100


def test_preview_envelope_graceful_on_failure():
    provider = _FakeProvider()
    disp = CrpDispatcher(provider, system_prompt="sys")
    # Force client creation then break it so preview fails deterministically.
    disp._client = object()
    result = disp.preview_envelope("task")
    assert "error" in result


def test_crp_retrieve_context_coerces_string_max_results():
    """Regression: crp_retrieve_context must accept string max_results from LLM.

    CRP's built-in handler does ``min(args.get("max_results", 5), 20)`` which
    raises a type error when the LLM passes a JSON string. Our import-time
    patch coerces the argument.
    """
    try:
        from crp.core.context_tools import ContextToolExecutor
    except ImportError:
        pytest.skip("CRP not installed")

    class _FakeStore:
        fact_count = 0

        def get_ranked_facts(self, **kwargs):
            return []

        @property
        def structural_state(self):
            return {}

        @property
        def critical_state(self):
            return {}

    executor = ContextToolExecutor(
        warm_store=_FakeStore(),
        ckf=None,  # type: ignore[arg-type]
        count_tokens=lambda text: len(text.split()),
    )
    # This must not raise "'<' not supported between instances of 'int' and 'str'".
    result = executor.execute(
        type(
            "TC",
            (),
            {
                "id": "1",
                "name": "crp_retrieve_context",
                "arguments": {"query": "EU AI Act", "max_results": "10"},
            },
        )()
    )
    payload = json.loads(result.content)
    assert "error" not in payload
    assert "facts" in payload
