"""Tests for real plan revision in the Phase 7 loop (Round 6)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable

import pytest

from crp_comply.agent.cache import AgentCache
from crp_comply.agent.loop_budget import LoopBudget
from crp_comply.agent.loop_runtime import LoopRuntimeConfig, run_loop_stream
from crp_comply.agent.loop_state import Plan, PlanStep
from crp_comply.agent.reflector import ReflectorResult
from crp_comply.agent.dialogue import DialoguePolicy, PolicyDecision


@dataclass
class _StubResult:
    final_text: str = "stubbed answer with [chunk_alpha]"
    citations: list[dict[str, Any]] = field(default_factory=list)
    state: str = "done"


@dataclass
class _StubAgent:
    user_id: str
    max_iters: int
    event_sink: Callable[[dict[str, Any]], None] | None = None

    def run(self, task: str, **kw) -> _StubResult:
        if self.event_sink is not None:
            self.event_sink({"event": "tool_call", "tool": "rag_search", "args": {"q": task}})
            self.event_sink(
                {"event": "tool_result", "tool": "rag_search", "result": {"summary": "found"}}
            )
            self.event_sink({"event": "llm_turn", "content": "synthesising"})
        return _StubResult(citations=[{"chunk_id": "alpha"}])


def _agent_builder(**kw: Any) -> _StubAgent:
    return _StubAgent(user_id=kw.get("user_id", ""), max_iters=int(kw.get("max_iters", 4)))


def _drain(coro_async_gen) -> list[dict[str, Any]]:
    async def _go() -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        async for ev in coro_async_gen:
            out.append(ev)
        return out

    return asyncio.run(_go())


def test_replan_reruns_planner_with_failure_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """On a ``revise_plan`` verdict the runtime re-invokes _plan_for with
    failure context and executes the revised plan."""
    cache = AgentCache(db_path=tmp_path / "cache.sqlite")
    cfg = LoopRuntimeConfig(
        user_id="u1",
        tenant_id="t1",
        session_id="replan-s1",
        task="What does GDPR Article 5 require for purpose limitation?",
        feedback_enabled=False,
    )

    calls: list[dict[str, Any]] = []

    def fake_plan_for(
        task: str,
        triage: Any,
        dialogue_intent: str = "unknown",
        *,
        depth: str = "standard",
        user_need: Any | None = None,
        failure_context: str | None = None,
    ) -> Plan:
        calls.append({"failure_context": failure_context, "task": task})
        if failure_context:
            return Plan(
                steps=(
                    PlanStep(id="recover", intent="recover missing citations"),
                    PlanStep(id="conclude", intent="conclude the comparison"),
                ),
                should_loop=True,
            )
        # First plan: a single step so the revise path is reached quickly.
        return Plan(
            steps=(PlanStep(id="s1", intent="initial comparison"),),
            should_loop=True,
        )

    monkeypatch.setattr(
        "crp_comply.agent.loop_runtime._plan_for",
        fake_plan_for,
    )
    monkeypatch.setattr(
        DialoguePolicy,
        "decide",
        lambda self, nlu, state, prior_slots=None: PolicyDecision(
            action="continue", requires_llm=True
        ),
    )

    verdict_count = {"n": 0}

    def fake_reflector_evaluate(*, state, step, outcome, confidence):
        verdict_count["n"] += 1
        if verdict_count["n"] == 1:
            return ReflectorResult(
                verdict="revise_plan",
                notes="missing citations",
                plan_delta="add citation recovery step",
            )
        return ReflectorResult(verdict="ok", notes="")

    monkeypatch.setattr(
        "crp_comply.agent.loop_runtime.Reflector.evaluate",
        staticmethod(fake_reflector_evaluate),
    )

    events = _drain(
        run_loop_stream(
            cfg,
            agent_builder=_agent_builder,
            cache=cache,
            budget=LoopBudget(max_steps=6, max_plan_revisions=2),
        )
    )

    names = [e["event"] for e in events]
    assert "loop.plan.revised" in names
    assert any(e["event"] == "loop.step.start" and e["step_id"] == "recover" for e in events)
    assert any(e["event"] == "loop.step.start" and e["step_id"] == "conclude" for e in events)

    # _plan_for was called twice: initial plan + replan with failure context.
    assert len(calls) == 2
    assert calls[0]["failure_context"] is None
    assert calls[1]["failure_context"] is not None
    assert "missing citations" in (calls[1]["failure_context"] or "")


def test_replan_budget_limits_revisions(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Once the plan-revision budget is exhausted, ``revise_plan`` aborts."""
    cache = AgentCache(db_path=tmp_path / "cache.sqlite")
    cfg = LoopRuntimeConfig(
        user_id="u1",
        tenant_id="t1",
        session_id="replan-budget-s1",
        task="What does GDPR Article 5 require?",
        feedback_enabled=False,
    )

    monkeypatch.setattr(
        "crp_comply.agent.loop_runtime._plan_for",
        lambda task, triage, dialogue_intent="unknown", *, depth="standard", user_need=None, failure_context=None: (
            Plan(
                steps=(PlanStep(id="s1", intent="initial"),),
                should_loop=True,
            )
        ),
    )
    monkeypatch.setattr(
        "crp_comply.agent.loop_runtime.Reflector.evaluate",
        staticmethod(lambda **kw: ReflectorResult(verdict="revise_plan", notes="always revise")),
    )
    monkeypatch.setattr(
        DialoguePolicy,
        "decide",
        lambda self, nlu, state, prior_slots=None: PolicyDecision(
            action="continue", requires_llm=True
        ),
    )

    events = _drain(
        run_loop_stream(
            cfg,
            agent_builder=_agent_builder,
            cache=cache,
            budget=LoopBudget(max_steps=6, max_plan_revisions=1),
        )
    )

    abort = next((e for e in events if e["event"] == "loop.abort"), None)
    assert abort is not None
    assert abort["dimension"] == "plan_revisions"
