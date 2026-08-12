"""Tests for the loop budget primitive (PHASE_7 §21 7.12)."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import pytest

from crp_comply.agent.cache import AgentCache
from crp_comply.agent.loop_budget import (
    BudgetExceeded,
    LoopBudget,
    LoopBudgetMeter,
    make_abort_payload,
)
from crp_comply.agent.loop_runtime import LoopRuntimeConfig, run_loop_stream


# ── Config ──────────────────────────────────────────────────────────


def test_default_budget_matches_spec() -> None:
    b = LoopBudget()
    assert b.max_steps == 12
    assert b.max_tokens == 60_000
    assert b.max_wall_clock_s == 300.0
    assert b.max_clarifiers == 6
    assert b.max_plan_revisions == 3


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_steps": 0},
        {"max_tokens": -1},
        {"max_clarifiers": 0},
        {"max_plan_revisions": -3},
        {"max_wall_clock_s": 0},
    ],
)
def test_budget_rejects_non_positive_ceilings(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        LoopBudget(**kwargs)


def test_budget_from_env_uses_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRP_COMPLY_LOOP_MAX_STEPS", "5")
    monkeypatch.setenv("CRP_COMPLY_LOOP_MAX_TOKENS", "100")
    monkeypatch.setenv("CRP_COMPLY_LOOP_MAX_WALL_CLOCK_S", "10.5")
    b = LoopBudget.from_env()
    assert b.max_steps == 5
    assert b.max_tokens == 100
    assert b.max_wall_clock_s == 10.5
    # Untouched dimensions keep the default.
    assert b.max_clarifiers == 6


def test_budget_from_env_ignores_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRP_COMPLY_LOOP_MAX_STEPS", "0")
    monkeypatch.setenv("CRP_COMPLY_LOOP_MAX_TOKENS", "junk")
    b = LoopBudget.from_env()
    assert b.max_steps == 12  # default
    assert b.max_tokens == 60_000  # default


# ── Meter ───────────────────────────────────────────────────────────


def test_meter_records_below_ceiling() -> None:
    m = LoopBudgetMeter()
    for _ in range(3):
        m.record_step()
    m.record_tokens(100)
    m.record_clarifier()
    m.record_plan_revision()
    usage = m.usage()
    assert usage["steps"] == 3
    assert usage["tokens"] == 100
    assert usage["clarifiers"] == 1
    assert usage["plan_revisions"] == 1
    assert m.breached is None


@pytest.mark.parametrize(
    "method,limit_field,limit_value",
    [
        ("record_step", "max_steps", 12),
        ("record_clarifier", "max_clarifiers", 6),
        ("record_plan_revision", "max_plan_revisions", 3),
    ],
)
def test_meter_raises_at_ceiling(method: str, limit_field: str, limit_value: int) -> None:
    m = LoopBudgetMeter()
    with pytest.raises(BudgetExceeded) as exc_info:
        for _ in range(limit_value + 1):
            getattr(m, method)()
    assert exc_info.value.dimension in {"steps", "clarifiers", "plan_revisions"}
    assert exc_info.value.limit == limit_value
    assert m.breached == exc_info.value.dimension


def test_meter_token_budget_exceeded() -> None:
    m = LoopBudgetMeter(budget=LoopBudget(max_tokens=100))
    m.record_tokens(60)
    with pytest.raises(BudgetExceeded) as exc_info:
        m.record_tokens(50)
    assert exc_info.value.dimension == "tokens"
    assert exc_info.value.limit == 100
    assert exc_info.value.usage == 110


def test_meter_wall_clock_exceeded() -> None:
    m = LoopBudgetMeter(budget=LoopBudget(max_wall_clock_s=0.05))
    time.sleep(0.06)
    with pytest.raises(BudgetExceeded) as exc_info:
        m.record_step()
    assert exc_info.value.dimension == "wall_clock"


def test_passive_wall_clock_check() -> None:
    m = LoopBudgetMeter(budget=LoopBudget(max_wall_clock_s=0.05))
    time.sleep(0.06)
    with pytest.raises(BudgetExceeded):
        m.check_wall_clock()


def test_meter_negative_tokens_rejected() -> None:
    m = LoopBudgetMeter()
    with pytest.raises(ValueError):
        m.record_tokens(-1)


def test_remaining_never_goes_negative() -> None:
    m = LoopBudgetMeter(budget=LoopBudget(max_steps=2))
    m.record_step()
    m.record_step()  # right at the ceiling — does not raise
    rem = m.remaining()
    assert rem["steps"] == 0


# ── Abort payload ───────────────────────────────────────────────────


def test_make_abort_payload_shape() -> None:
    m = LoopBudgetMeter(budget=LoopBudget(max_steps=1))
    m.record_step()
    try:
        m.record_step()
    except BudgetExceeded as exc:
        payload = make_abort_payload(m, exc, run_id="run-X")
    assert payload["run_id"] == "run-X"
    assert payload["reason"] == "budget_exceeded"
    assert payload["dimension"] == "steps"
    assert payload["limit"] == 1
    assert payload["usage"] == 2
    assert payload["budget"]["max_steps"] == 1
    assert payload["totals"]["steps"] == 2


def test_abort_payload_validates_against_event_schema() -> None:
    """The make_abort_payload output must round-trip through the
    AbortPayload pydantic model (PHASE_7 §21 7.0)."""
    from crp_comply.api.events import LoopEvent, PAYLOAD_SCHEMA

    m = LoopBudgetMeter(budget=LoopBudget(max_clarifiers=1))
    m.record_clarifier()
    try:
        m.record_clarifier()
    except BudgetExceeded as exc:
        payload = make_abort_payload(m, exc, run_id="run-Y")
    schema = PAYLOAD_SCHEMA[LoopEvent.ABORT]
    inst = schema.model_validate(payload)
    assert inst.dimension == "clarifiers"
    assert inst.usage == 2.0


# ── Phase 6 integration: token budget wiring ────────────────────────


@dataclass
class _TokenStubAgentResult:
    final_text: str = "stubbed answer with [chunk_alpha]"
    citations: list[dict[str, Any]] = field(default_factory=list)
    state: str = "done"


@dataclass
class _TokenSpendingStubAgent:
    """Reports token usage via the Phase 6 callback."""

    user_id: str
    max_iters: int
    event_sink: Callable[[dict[str, Any]], None] | None = None
    token_usage_callback: Callable[[int], None] | None = None

    def run(
        self,
        task: str,
        *,
        system_id: str = "",
        customer_id: str = "",
        session_id: str = "",
        extra_context: str = "",
        memory: Any | None = None,
    ) -> _TokenStubAgentResult:
        if self.token_usage_callback is not None:
            self.token_usage_callback(1000)
        if self.event_sink is not None:
            self.event_sink({"event": "tool_call", "tool": "rag_search", "args": {"q": task}})
            self.event_sink(
                {"event": "tool_result", "tool": "rag_search", "result": {"summary": "found"}}
            )
            self.event_sink({"event": "llm_turn", "content": "synthesising"})
        return _TokenStubAgentResult(citations=[{"chunk_id": "alpha"}])


def _token_agent_builder(**kw: Any) -> _TokenSpendingStubAgent:
    return _TokenSpendingStubAgent(
        user_id=kw.get("user_id", ""), max_iters=int(kw.get("max_iters", 4))
    )


def _drain(coro_async_gen) -> list[dict[str, Any]]:
    async def _go() -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        async for ev in coro_async_gen:
            out.append(ev)
        return out

    return asyncio.run(_go())


def test_runtime_records_tokens_and_emits_abort_on_budget(tmp_path) -> None:
    """When the agent's LLM calls push cumulative tokens over the ceiling,
    the runtime emits ``loop.abort`` with the correct dimension."""
    cache = AgentCache(db_path=tmp_path / "cache.sqlite")
    cfg = LoopRuntimeConfig(
        user_id="u1",
        tenant_id="t1",
        session_id="s1",
        task="What does GDPR Article 5 require?",
        feedback_enabled=False,
    )

    events = _drain(
        run_loop_stream(
            cfg,
            agent_builder=_token_agent_builder,
            cache=cache,
            budget=LoopBudget(max_steps=4, max_tokens=500, max_plan_revisions=2),
        )
    )

    abort = next((e for e in events if e["event"] == "loop.abort"), None)
    assert abort is not None, [e["event"] for e in events]
    assert abort["dimension"] == "tokens"
    assert abort["usage"] > abort["limit"]


def test_runtime_does_not_abort_when_tokens_within_budget(tmp_path) -> None:
    cache = AgentCache(db_path=tmp_path / "cache.sqlite")
    cfg = LoopRuntimeConfig(
        user_id="u1",
        tenant_id="t1",
        session_id="s1",
        task="What does GDPR Article 5 require?",
        feedback_enabled=False,
    )

    events = _drain(
        run_loop_stream(
            cfg,
            agent_builder=_token_agent_builder,
            cache=cache,
            budget=LoopBudget(max_steps=4, max_tokens=100_000, max_plan_revisions=2),
        )
    )

    assert not any(e["event"] == "loop.abort" for e in events)
    assert events[-1]["event"] == "loop.final"
