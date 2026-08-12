"""Tests for the typed loop-event taxonomy (PHASE_7 \u00a721 7.0).

These tests are the gate for sub-phase 7.0:

* every event in PHASE_7 \u00a73.3 + \u00a719 is registered;
* every event has a schema and validates a known-good payload;
* unknown event names are rejected;
* ``make_event`` round-trips a sane payload;
* :func:`crp_comply.api.agent._sse_format` validates ``loop.*`` events
  but lets legacy event names through unchanged (additive contract).
"""

from __future__ import annotations

import pytest

from crp_comply.api.events import (
    ALL_EVENT_NAMES,
    PAYLOAD_SCHEMA,
    LoopEvent,
    LoopEventError,
    is_loop_event,
    make_event,
    validate_event,
)


# The 22 events specified in PHASE_7_LANGUAGE_AGENT_LOOP.md
EXPECTED_EVENTS: set[str] = {
    # \u00a73.3
    "loop.opened",
    "loop.plan",
    "loop.step.start",
    "loop.thought.delta",
    "loop.tool.call",
    "loop.tool.result",
    "loop.reflection",
    "loop.clarifier.ask",
    "loop.clarifier.answer",
    "loop.step.end",
    "loop.recipe.start",
    "loop.recipe.delta",
    "loop.recipe.done",
    "loop.final",
    "loop.error",
    "loop.heartbeat",
    # \u00a719 \u2014 fast-path / CKF / web
    "loop.triage",
    "loop.cache.hit",
    "loop.cache.miss",
    "loop.web.start",
    "loop.web.result",
    "loop.ckf.query",
    # §21 7.12 — budgets
    "loop.abort",
    # §21 7.15 — intelligent web search
    "loop.web.expand",
    "loop.web.rerank",
    "loop.web.cite",
    # CRP compliance — PII-in-pipeline warning
    "loop.pii_warning",
    # Round 8 — citation validation
    "loop.citation.invalid",
    # Round 10 — research phases
    "loop.phase.complete",
}


def test_registry_covers_phase7_spec() -> None:
    assert ALL_EVENT_NAMES == EXPECTED_EVENTS, (
        "LoopEvent must match PHASE_7 \u00a73.3 + \u00a719 + Round 8/10 exactly"
    )
    assert len(LoopEvent) == 29
    assert set(PAYLOAD_SCHEMA) == set(LoopEvent)


def test_is_loop_event() -> None:
    assert is_loop_event("loop.opened")
    assert is_loop_event("loop.ckf.query")
    assert not is_loop_event("tool_call")  # legacy
    assert not is_loop_event("loop.unknown")


def test_unknown_event_rejected() -> None:
    with pytest.raises(LoopEventError, match="unknown loop event"):
        validate_event("loop.does_not_exist", {})


def test_payload_validation_failure_message() -> None:
    # Wrong type for a required field.
    with pytest.raises(LoopEventError, match="failed schema"):
        validate_event("loop.step.end", {"step_id": "s1", "status": "INVALID"})


# ---------------------------------------------------------------------------
# Sample-payload round-trip per event
# ---------------------------------------------------------------------------


_SAMPLES: dict[str, dict] = {
    "loop.opened": {"session_id": "abc", "query": "what is gdpr?", "model": "gpt"},
    "loop.plan": {
        "steps": [
            {"id": "s1", "intent": "look up controller obligations"},
            {"id": "s2", "intent": "summarise"},
        ]
    },
    "loop.step.start": {"step_id": "s1", "intent": "x"},
    "loop.thought.delta": {"step_id": "s1", "text": "I should..."},
    "loop.tool.call": {"step_id": "s1", "tool": "pattern_query", "args": {"q": "x"}},
    "loop.tool.result": {"step_id": "s1", "tool": "pattern_query", "summary": "5 hits"},
    "loop.reflection": {"step_id": "s1", "verdict": "ok"},
    "loop.clarifier.ask": {"step_id": "s1", "question": "Are you a controller?", "slot_id": "role"},
    "loop.clarifier.answer": {"slot_id": "role", "answer": "controller"},
    "loop.step.end": {"step_id": "s1", "status": "ok"},
    "loop.recipe.start": {"recipe_id": "dpia_v1", "inputs": {}},
    "loop.recipe.delta": {"recipe_id": "dpia_v1", "kind": "section", "text": "Lawful basis..."},
    "loop.recipe.done": {"recipe_id": "dpia_v1", "artefact_id": "art-1"},
    "loop.final": {"artefacts": [], "summary": "done", "total_steps": 3},
    "loop.error": {"message": "boom"},
    "loop.heartbeat": {"state": "thinking"},
    "loop.triage": {
        "complexity": "simple",
        "intent": "define",
        "confidence": 0.9,
        "lane": "fast",
        "reasoning": "matched 'cite article N' pattern",
    },
    "loop.cache.hit": {"key_kind": "semantic", "similarity": 0.95, "age_seconds": 12.0},
    "loop.cache.miss": {"key_kind": "exact", "lookup_ms": 1.2},
    "loop.web.start": {"query": "edpb 2026 ruling", "backend": "local"},
    "loop.web.result": {
        "backend": "local",
        "hits": [{"domain": "edpb.europa.eu", "trust_tier": 1}],
        "blocked": 0,
        "latency_ms": 850.0,
    },
    "loop.ckf.query": {
        "mode": "pattern_query",
        "scope": "federated",
        "hits": 3,
        "top_confidence": 0.92,
    },
    "loop.abort": {
        "reason": "budget_exceeded",
        "dimension": "wall_clock",
        "limit": 300.0,
        "usage": 312.4,
        "budget": {
            "max_steps": 12.0,
            "max_tokens": 60000.0,
            "max_wall_clock_s": 300.0,
            "max_clarifiers": 6.0,
            "max_plan_revisions": 3.0,
        },
        "totals": {
            "steps": 9.0,
            "tokens": 41200.0,
            "wall_clock_s": 312.4,
            "clarifiers": 1.0,
            "plan_revisions": 0.0,
        },
    },
    "loop.web.expand": {
        "goal": "GDPR Article 6 lawful basis",
        "intent": "regulation_text",
        "sub_queries": [
            "GDPR Article 6",
            '"GDPR Article 6" site:eur-lex.europa.eu',
        ],
        "strategy": "templated",
    },
    "loop.web.rerank": {
        "model": "cross-encoder/ms-marco-MiniLM-L-6-v2",
        "candidates_in": 12,
        "candidates_out": 6,
        "latency_ms": 41.5,
    },
    "loop.web.cite": {
        "citation_id": "web:abc123:c0",
        "source_id": "web:abc123",
        "chunk_index": 0,
        "score": 0.84,
        "excerpt": "Processing shall be lawful only if and to the extent ...",
    },
    "loop.pii_warning": {
        "step_id": "s1",
        "categories": ["email", "phone"],
        "source": "intermediate_scan",
        "iter": 2,
    },
    "loop.citation.invalid": {
        "step_id": "final",
        "invalid_ids": ["bad_id"],
        "valid_ids": ["good_id"],
        "surrogate_ids": [],
        "stripped": True,
    },
    "loop.phase.complete": {
        "phase": "RESEARCH",
        "step_ids": ["s1"],
        "facts_gathered": 2,
        "citations_count": 1,
        "notes": "completed RESEARCH phase",
    },
}


@pytest.mark.parametrize("event", sorted(EXPECTED_EVENTS))
def test_sample_payload_validates(event: str) -> None:
    sample = _SAMPLES[event]
    out = validate_event(event, sample)
    # Defaults populated.
    assert "ts" in out and out["ts"] > 0
    assert "run_id" in out


def test_make_event_attaches_event_name_and_run_id() -> None:
    evt = make_event(
        LoopEvent.STEP_START,
        {"step_id": "s1", "intent": "lookup"},
        run_id="run-42",
    )
    assert evt["event"] == "loop.step.start"
    assert evt["run_id"] == "run-42"
    assert evt["step_id"] == "s1"


def test_every_event_appears_in_samples() -> None:
    # Guards against forgetting to add a sample payload when adding
    # a new event in the future.
    assert set(_SAMPLES.keys()) == EXPECTED_EVENTS


# ---------------------------------------------------------------------------
# SSE bridge: loop.* events validated, legacy events untouched
# ---------------------------------------------------------------------------


def test_sse_format_validates_loop_event() -> None:
    from crp_comply.api.agent import _sse_format

    frame = _sse_format("loop.step.start", {"step_id": "s1", "intent": "lookup"})
    assert "event: loop.step.start" in frame
    assert '"step_id": "s1"' in frame


def test_sse_format_demotes_malformed_loop_event_to_error() -> None:
    from crp_comply.api.agent import _sse_format

    # Missing required field 'step_id' on loop.step.start.
    frame = _sse_format("loop.step.start", {"intent": "lookup"})
    # Bad payload should be replaced with a loop.error frame so the
    # browser still gets something parseable.
    assert "event: loop.error" in frame


def test_sse_format_lets_legacy_event_pass_through() -> None:
    from crp_comply.api.agent import _sse_format

    # Legacy orchestrator events (tool_call, llm_turn, crp_*) must not
    # be schema-validated against the typed registry \u2014 7.0 is purely
    # additive.
    frame = _sse_format("tool_call", {"tool": "rag.search", "args": {}})
    assert "event: tool_call" in frame
    assert '"tool": "rag.search"' in frame


# ---------------------------------------------------------------------------
# Audit 6 §1 regression — loop.abort emitters must validate
# ---------------------------------------------------------------------------
#
# Previously the loop emitted free-form strings for ``reason`` (e.g.
# "plan revision budget exhausted"), which fail the ``Literal`` schema and
# caused the whole event to be dropped as malformed ("undefined used
# undefined of undefined" in the UI). The fix keeps ``reason`` a stable
# machine enum and carries the human text in ``detail``. These tests pin
# the exact payload shapes both emitters in loop_runtime.py produce.


def test_step_budget_abort_payload_validates() -> None:
    # Mirrors loop_runtime.py step-budget abort emitter.
    emitted = {
        "dimension": "steps",
        "limit": 12.0,
        "usage": 13.0,
        "detail": "step budget exceeded: steps 13 of 12",
    }
    out = validate_event("loop.abort", emitted)
    assert out["reason"] == "budget_exceeded"
    assert out["dimension"] == "steps"
    assert out["detail"].startswith("step budget")


def test_plan_revision_abort_payload_validates() -> None:
    # Mirrors loop_runtime.py plan-revision abort emitter.
    emitted = {
        "dimension": "plan_revisions",
        "limit": 3.0,
        "usage": 4.0,
        "detail": "plan revision budget exhausted",
    }
    out = validate_event("loop.abort", emitted)
    assert out["reason"] == "budget_exceeded"
    assert out["dimension"] == "plan_revisions"
    assert out["detail"] == "plan revision budget exhausted"


def test_free_form_abort_reason_is_rejected() -> None:
    # Guard against the original regression: a free-form ``reason`` string
    # must NOT validate — the machine reason is a fixed enum.
    with pytest.raises(LoopEventError):
        validate_event(
            "loop.abort",
            {
                "reason": "plan revision budget exhausted",
                "dimension": "plan_revisions",
                "limit": 3.0,
                "usage": 4.0,
            },
        )
