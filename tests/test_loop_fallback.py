"""Tests for mid-run local-LLM fallback (Phase 6, Round 6)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable

import pytest

from crp_comply.agent.cache import AgentCache
from crp_comply.agent.loop_budget import LoopBudget
from crp_comply.agent.loop_runtime import LoopRuntimeConfig, run_loop_stream


@dataclass
class _StubResult:
    final_text: str = ""
    citations: list[dict[str, Any]] = field(default_factory=list)
    state: str = "done"


@dataclass
class _QuotaStubAgent:
    """Fails with a hosted quota error unless running on the local LLM."""

    user_id: str
    max_iters: int
    event_sink: Callable[[dict[str, Any]], None] | None = None
    llm: Any | None = None

    def run(
        self,
        task: str,
        *,
        system_id: str = "",
        customer_id: str = "",
        session_id: str = "",
        extra_context: str = "",
        memory: Any | None = None,
    ) -> _StubResult:
        if self.llm == "local":
            return _StubResult(
                final_text="local-model answer with [chunk_alpha]",
                citations=[{"chunk_id": "alpha"}],
            )
        raise RuntimeError("insufficient_quota: hosted provider token budget exhausted")


def _quota_agent_builder(**kw: Any) -> _QuotaStubAgent:
    return _QuotaStubAgent(user_id=kw.get("user_id", ""), max_iters=int(kw.get("max_iters", 4)))


def _drain(coro_async_gen) -> list[dict[str, Any]]:
    async def _go() -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        async for ev in coro_async_gen:
            out.append(ev)
        return out

    return asyncio.run(_go())


def test_runtime_local_fallback_on_hosted_quota(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """When the agent step fails with a hosted quota error and a local worker
    is available, the runtime retries once with the local LLM and succeeds."""
    cache = AgentCache(db_path=tmp_path / "cache.sqlite")
    cfg = LoopRuntimeConfig(
        user_id="u1",
        tenant_id="t1",
        session_id="fallback-s1",
        task="What does GDPR Article 5 require for purpose limitation?",
        feedback_enabled=False,
    )

    monkeypatch.setattr(
        "crp_comply.agent.loop_runtime._local_llm_for_user",
        lambda user_id: "local",
    )

    events = _drain(
        run_loop_stream(
            cfg,
            agent_builder=_quota_agent_builder,
            cache=cache,
            budget=LoopBudget(max_steps=4, max_tokens=100_000),
        )
    )

    names = [e["event"] for e in events]
    assert "loop.fallback.local" in names
    final = events[-1]
    assert final["event"] == "loop.final"
    assert "local-model answer" in final["summary"]


def test_runtime_no_fallback_when_worker_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """If no local worker is connected, the hosted quota error is surfaced."""
    cache = AgentCache(db_path=tmp_path / "cache.sqlite")
    cfg = LoopRuntimeConfig(
        user_id="u1",
        tenant_id="t1",
        session_id="fallback-none-s1",
        task="What does GDPR Article 5 require for purpose limitation?",
        feedback_enabled=False,
    )

    monkeypatch.setattr(
        "crp_comply.agent.loop_runtime._local_llm_for_user",
        lambda user_id: None,
    )

    events = _drain(
        run_loop_stream(
            cfg,
            agent_builder=_quota_agent_builder,
            cache=cache,
            budget=LoopBudget(max_steps=4, max_tokens=100_000),
        )
    )

    names = [e["event"] for e in events]
    assert "loop.fallback.local" not in names
    step_end = next(e for e in events if e["event"] == "loop.step.end")
    assert step_end["status"] == "failed"
