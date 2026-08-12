"""Tests for the Phase 7.15 :mod:`crp_comply.agent.loop_runtime`.

These tests stub the underlying ``ComplianceAgent`` so the runtime
exercises every emit path (triage, cache miss, plan, step, reflect,
final) without requiring an LLM.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable

from crp_comply.agent.cache import AgentCache, CachedAnswer
from crp_comply.agent.loop_budget import LoopBudget
from crp_comply.agent.loop_runtime import LoopRuntimeConfig, run_loop_stream
from crp_comply.agent.memory import CompliantMemory


# ── Stubs ────────────────────────────────────────────────────────────


@dataclass
class _StubAgentResult:
    final_text: str = "stubbed answer with [chunk_alpha]"
    citations: list[dict[str, Any]] = field(default_factory=list)
    state: str = "done"
    iterations: int = 1
    tool_calls: int = 0
    facts_stored: int = 0


@dataclass
class _StubAgent:
    """Minimal stand-in for ComplianceAgent.

    Emits a tool_call + tool_result + llm_turn so the runtime's
    event-translation path is exercised, then returns a fixed result.
    """

    user_id: str
    max_iters: int
    event_sink: Callable[[dict[str, Any]], None] | None = None

    def run(
        self,
        task: str,
        *,
        system_id: str = "",
        customer_id: str = "",
        session_id: str = "",
        extra_context: str = "",
    ) -> _StubAgentResult:
        if self.event_sink is not None:
            self.event_sink({"event": "tool_call", "tool": "rag_search", "args": {"q": task}})
            self.event_sink(
                {
                    "event": "tool_result",
                    "tool": "rag_search",
                    "result": {"summary": "found 3 chunks"},
                }
            )
            self.event_sink({"event": "llm_turn", "content": "synthesising"})
        return _StubAgentResult(citations=[{"chunk_id": "alpha", "source": "GDPR Art. 5"}])


def _agent_builder(**kw: Any) -> _StubAgent:
    return _StubAgent(user_id=kw.get("user_id", ""), max_iters=int(kw.get("max_iters", 4)))


# ── Tests ────────────────────────────────────────────────────────────


def _drain(coro_async_gen) -> list[dict[str, Any]]:
    async def _go() -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        async for ev in coro_async_gen:
            out.append(ev)
        return out

    return asyncio.run(_go())


def test_runtime_lane_b_cache_miss_full_pipeline(tmp_path):
    """Lane B / cache miss: emits triage, cache.miss, plan, step×1, reflect, final."""
    cache = AgentCache(db_path=tmp_path / "cache.sqlite")
    cfg = LoopRuntimeConfig(
        user_id="u1",
        tenant_id="t1",
        session_id="s1",
        task="What does GDPR Article 5 require for purpose limitation?",
    )

    events = _drain(
        run_loop_stream(
            cfg,
            agent_builder=_agent_builder,
            cache=cache,
            budget=LoopBudget(max_steps=4, max_plan_revisions=2),
        )
    )

    names = [e["event"] for e in events]
    assert names[0] == "loop.opened"
    assert "loop.nlu" in names
    assert "loop.dialogue" in names
    assert "loop.triage" in names
    assert "loop.cache.miss" in names
    assert "loop.plan" in names
    assert "loop.step.start" in names
    assert "loop.tool.call" in names
    assert "loop.tool.result" in names
    assert "loop.thought.delta" in names
    assert "loop.step.end" in names
    assert "loop.reflection" in names
    assert names[-1] == "loop.final"

    final = events[-1]
    assert final["summary"]
    assert final["cached"] is False

    nlu = next(e for e in events if e["event"] == "loop.nlu")
    assert nlu["intent"] == "define"
    assert nlu["slots"]["regulation"] == "gdpr"


def test_runtime_cache_hit_short_circuits(tmp_path):
    """A pre-populated cache yields loop.cache.hit + immediate loop.final."""
    cache = AgentCache(db_path=tmp_path / "cache.sqlite")
    query = "What is the EU AI Act?"
    cache.put_answer(
        tenant_id="t1",
        corpus_version="v1",
        ckf_version="v1",
        query=query,
        cached=CachedAnswer(
            answer="Yes — Annex III §1 lists it as high-risk.",
            citations=[{"chunk_id": "annex_iii_1"}],
        ),
    )

    cfg = LoopRuntimeConfig(
        user_id="u1",
        tenant_id="t1",
        session_id="cache-hit-s1",
        task=query,
        feedback_enabled=False,
    )

    events = _drain(run_loop_stream(cfg, agent_builder=_agent_builder, cache=cache))

    names = [e["event"] for e in events]
    assert "loop.nlu" in names
    assert "loop.dialogue" in names
    assert "loop.cache.hit" in names
    assert names[-1] == "loop.final"
    assert events[-1]["cached"] is True
    # No step or plan events on a cache hit.
    assert "loop.plan" not in names
    assert "loop.step.start" not in names


def test_runtime_dialogue_clarify_short_circuits_before_agent(tmp_path):
    """Missing required slots trigger loop.clarifier.ask and no agent invocation."""
    cache = AgentCache(db_path=tmp_path / "cache.sqlite")
    cfg = LoopRuntimeConfig(
        user_id="u1",
        tenant_id="t1",
        session_id="s1",
        task="Draft a DPIA",
        feedback_enabled=False,
    )

    events = _drain(
        run_loop_stream(
            cfg,
            agent_builder=_agent_builder,
            cache=cache,
            budget=LoopBudget(max_steps=4, max_plan_revisions=2),
            memory=CompliantMemory(user_id="u1", session_id="s1", data_dir=tmp_path / "ctx"),
        )
    )

    names = [e["event"] for e in events]
    assert "loop.nlu" in names
    assert "loop.dialogue" in names
    assert "loop.clarifier.ask" in names
    # Should short-circuit before triage/plan/step.
    assert "loop.plan" not in names
    assert "loop.step.start" not in names
    assert names[-1] == "loop.clarifier.ask"

    ask = next(e for e in events if e["event"] == "loop.clarifier.ask")
    assert ask["question"]
    assert ask["resume_token"]


# ─────────────────────────────────────────────────────────────────────
# Phase 7.15.b — web translation, clarifier, freshness planner.
# ─────────────────────────────────────────────────────────────────────


@dataclass
class _WebStubAgent:
    """Agent that emits a `web_search` tool_call + result."""

    user_id: str
    max_iters: int
    event_sink: Callable[[dict[str, Any]], None] | None = None

    def run(self, task, **kw) -> _StubAgentResult:
        if self.event_sink is not None:
            self.event_sink(
                {
                    "event": "tool_call",
                    "tool": "web_search",
                    "args": {"query": "latest EDPB opinion 2025", "freshness": "month"},
                }
            )
            self.event_sink(
                {
                    "event": "tool_result",
                    "tool": "web_search",
                    "result": {
                        "results": [
                            {
                                "domain": "edpb.europa.eu",
                                "url": "https://edpb.europa.eu/x",
                                "title": "EDPB Opinion 2025/01",
                                "trust_tier": 1,
                            }
                        ],
                        "blocked": 0,
                        "latency_ms": 123.4,
                        "backend": "searxng",
                    },
                }
            )
        return _StubAgentResult(final_text="EDPB issued opinion 2025/01.")


def _web_agent_builder(**kw):
    return _WebStubAgent(user_id=kw.get("user_id", ""), max_iters=int(kw.get("max_iters", 4)))


def test_runtime_translates_web_tool_events(tmp_path):
    """Web tool_call/result pairs become loop.web.start/result events."""
    cache = AgentCache(db_path=tmp_path / "cache.sqlite")
    cfg = LoopRuntimeConfig(
        user_id="u1",
        tenant_id="t1",
        session_id="s1",
        task="latest EDPB opinion 2025",
        feedback_enabled=False,
    )

    events = _drain(
        run_loop_stream(
            cfg,
            agent_builder=_web_agent_builder,
            cache=cache,
            budget=LoopBudget(max_steps=4, max_plan_revisions=2),
        )
    )

    names = [e["event"] for e in events]
    assert "loop.web.start" in names
    assert "loop.web.result" in names
    web_result = next(e for e in events if e["event"] == "loop.web.result")
    assert web_result["backend"] == "searxng"
    assert len(web_result["hits"]) == 1
    assert web_result["hits"][0]["domain"] == "edpb.europa.eu"


# ─────────────────────────────────────────────────────────────────────
# Phase 7.15.c — agent throws / clarifier suspension.
# ─────────────────────────────────────────────────────────────────────


@dataclass
class _ClarifierStubAgent:
    """Agent that asks the user a question mid-run."""

    user_id: str
    max_iters: int
    event_sink: Callable[[dict[str, Any]], None] | None = None

    def run(self, task, **kw):
        from crp_comply.agent.clarifier import AskUserSuspended

        return AskUserSuspended(
            question="Which jurisdiction are you operating in?",
            slot_id="jurisdiction",
            options=["EU", "UK", "US"],
            resume_token="",
        )


def _clarifier_agent_builder(**kw):
    return _ClarifierStubAgent(user_id=kw.get("user_id", ""), max_iters=int(kw.get("max_iters", 4)))


def test_runtime_agent_clarifier_suspends_with_resume_token(tmp_path):
    """If the agent raises AskUserSuspended, the runtime emits loop.clarifier.ask."""
    cache = AgentCache(db_path=tmp_path / "cache.sqlite")
    cfg = LoopRuntimeConfig(
        user_id="u1",
        tenant_id="t1",
        session_id="s1",
        task="Is my AI system high-risk?",
        feedback_enabled=False,
    )

    events = _drain(run_loop_stream(cfg, agent_builder=_clarifier_agent_builder, cache=cache))
    names = [e["event"] for e in events]
    assert "loop.clarifier.ask" in names
    ask = next(e for e in events if e["event"] == "loop.clarifier.ask")
    assert ask["question"]
    assert ask["resume_token"]
    # Persisted record should be loadable via ClarifierStore.
    from crp_comply.agent.clarifier import ClarifierStore

    rec = ClarifierStore().load(resume_token=ask["resume_token"], tenant_id="t1")
    assert rec is not None
    assert rec.question == ask["question"]


def test_freshness_heuristic_picks_web_tool_hint():
    from crp_comply.agent.loop_runtime import _plan_for, needs_fresh_web
    from crp_comply.agent.triage import TriageResult

    assert needs_fresh_web("latest EDPB opinion 2025")
    assert not needs_fresh_web("what is purpose limitation")

    triage = TriageResult(
        complexity="simple",
        intent="define",
        confidence=0.9,
        lane="fast",
        reasoning="test",
    )
    plan_fresh = _plan_for("latest enforcement action against TikTok 2025", triage)
    assert plan_fresh.steps[0].tool_hint == "web_search"
    plan_static = _plan_for("define purpose limitation", triage)
    # CRPv5 fast path: static definitional questions skip the mandatory
    # retrieval round-trip and answer directly.
    assert plan_static.steps[0].tool_hint == "direct_answer"


def test_plan_uses_dialogue_intent_when_triage_unknown():
    """When deterministic triage is uncertain, the NLU intent guides planning."""
    from crp_comply.agent.loop_runtime import _plan_for
    from crp_comply.agent.triage import TriageResult

    triage = TriageResult(
        complexity="simple",
        intent="unknown",
        confidence=0.3,
        lane="standard",
        reasoning="test",
    )
    plan = _plan_for(
        "Draft a DPIA for my hiring assistant", triage, dialogue_intent="produce_artefact"
    )
    assert len(plan.steps) == 2
    assert plan.should_loop is True
