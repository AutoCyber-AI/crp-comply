"""Tests for the reflector (PHASE_7 \u00a721 7.6)."""

from __future__ import annotations

import pytest

from crp_comply.agent.loop_state import (
    LoopState,
    LoopStateName,
    Plan,
    PlanStep,
)
from crp_comply.agent.reflector import (
    Reflector,
    ReflectorResult,
    extract_claims,
    make_reflection_event,
)
from crp_comply.agent.step_runner import StepOutcome


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def fsm():
    s = LoopState(session_id="sess", run_id="run")
    plan = Plan(
        steps=(
            PlanStep(id="s1", intent="check Art. 6"),
            PlanStep(id="s2", intent="follow up"),
        ),
        should_loop=True,
    )
    s.set_plan(plan)
    s.transition(LoopStateName.STEP)
    s.transition(LoopStateName.ACTING)
    return s


def _ok_outcome(observation: str, citations=None) -> StepOutcome:
    return StepOutcome(
        step_id="s1",
        status="ok",
        observation=observation,
        citations=list(citations or []),
        tool_calls=[],
    )


def _failed_outcome() -> StepOutcome:
    return StepOutcome(
        step_id="s1",
        status="failed",
        observation="",
        citations=[],
        tool_calls=[],
        error="boom",
    )


# ── Claim extractor ─────────────────────────────────────────────────


def test_extract_claims_returns_assertions_only():
    text = "Hello there. Article 6 GDPR requires lawful basis. ok?"
    claims = extract_claims(text)
    assert any("Article 6" in c for c in claims)
    assert all("Hello there" not in c for c in claims)


def test_extract_claims_handles_empty():
    assert extract_claims("") == []
    assert extract_claims("    ") == []


def test_extract_claims_skips_non_verb_sentences():
    assert extract_claims("Lawful basis. Citation.") == []


# ── Verdicts: ok ────────────────────────────────────────────────────


def test_reflector_ok_when_all_claims_cited(fsm):
    out = _ok_outcome(
        "Article 6 GDPR requires lawful basis.",
        citations=[{"source": "GDPR", "article": "Art. 6"}],
    )
    res = Reflector().evaluate(
        state=fsm,
        step=fsm.plan.steps[0],
        outcome=out,
        confidence=0.95,
    )
    assert res.verdict == "ok"
    assert res.uncited_claims == ()


def test_reflector_ok_when_no_claims_at_all(fsm):
    # Pure narration with no verbs counts as zero claims \u2192 trivially
    # passes the citation check.
    out = _ok_outcome("Lawful basis. Citation.", citations=[])
    res = Reflector().evaluate(
        state=fsm,
        step=fsm.plan.steps[0],
        outcome=out,
    )
    assert res.verdict == "ok"


# ── Verdicts: retry on uncited claim ────────────────────────────────


def test_reflector_retry_on_uncited_claim(fsm):
    out = _ok_outcome(
        "Article 99 of the AI Act requires impact assessments.",
        citations=[],  # NO sources
    )
    res = Reflector().evaluate(
        state=fsm,
        step=fsm.plan.steps[0],
        outcome=out,
    )
    assert res.verdict == "retry"
    assert any("Article 99" in c for c in res.uncited_claims)


def test_reflector_retry_when_pinpoint_does_not_match_any_citation(fsm):
    out = _ok_outcome(
        "Article 22 GDPR requires human review.",
        citations=[{"source": "GDPR", "article": "Art. 6"}],
    )
    res = Reflector().evaluate(
        state=fsm,
        step=fsm.plan.steps[0],
        outcome=out,
    )
    assert res.verdict == "retry"


def test_reflector_does_not_emit_ok_when_any_claim_uncited(fsm):
    out = _ok_outcome(
        "Article 6 GDPR requires lawful basis. Article 35 GDPR requires DPIAs.",
        citations=[{"source": "GDPR", "article": "Art. 6"}],
    )
    res = Reflector().evaluate(
        state=fsm,
        step=fsm.plan.steps[0],
        outcome=out,
    )
    # One claim is uncited \u2192 the whole step is retry, structural rule.
    assert res.verdict == "retry"


# ── Verdicts: failed step retries (then revises, then aborts) ───────


def test_reflector_retry_on_first_failure(fsm):
    res = Reflector().evaluate(
        state=fsm,
        step=fsm.plan.steps[0],
        outcome=_failed_outcome(),
    )
    assert res.verdict == "retry"
    assert "boom" in res.notes


def test_reflector_revise_plan_after_two_retries(fsm):
    # Simulate two REFLECT\u2192STEP retries having happened.
    fsm.transition(LoopStateName.REFLECT)
    fsm.transition(LoopStateName.STEP, reason="retry-1")
    fsm.transition(LoopStateName.ACTING)
    fsm.transition(LoopStateName.REFLECT)
    fsm.transition(LoopStateName.STEP, reason="retry-2")
    fsm.transition(LoopStateName.ACTING)
    res = Reflector().evaluate(
        state=fsm,
        step=fsm.plan.steps[0],
        outcome=_failed_outcome(),
    )
    assert res.verdict == "revise_plan"


def test_reflector_aborts_when_revision_budget_exhausted(fsm):
    # Manually exhaust the revision budget without raising on the 4th
    # increment by setting it directly.
    fsm.plan_revisions = fsm.max_plan_revisions
    res = Reflector().evaluate(
        state=fsm,
        step=fsm.plan.steps[0],
        outcome=_failed_outcome(),
    )
    assert res.verdict == "abort"
    assert "budget" in res.notes


# ── Verdicts: clarify_first ─────────────────────────────────────────


def test_reflector_clarify_first_on_low_confidence(fsm):
    out = _ok_outcome("[recall] facts found.", citations=[])
    res = Reflector().evaluate(
        state=fsm,
        step=fsm.plan.steps[0],
        outcome=out,
        confidence=0.4,
    )
    assert res.verdict == "clarify_first"


def test_reflector_aborts_when_clarifier_budget_gone(fsm):
    fsm.clarifier_count = fsm.max_clarifiers
    out = _ok_outcome("[recall] facts found.", citations=[])
    res = Reflector().evaluate(
        state=fsm,
        step=fsm.plan.steps[0],
        outcome=out,
        confidence=0.4,
    )
    assert res.verdict == "abort"


def test_reflector_high_confidence_does_not_trigger_clarify(fsm):
    out = _ok_outcome("[recall] facts found.", citations=[])
    res = Reflector().evaluate(
        state=fsm,
        step=fsm.plan.steps[0],
        outcome=out,
        confidence=0.99,
    )
    assert res.verdict == "ok"


# ── Lane B (degenerate single-step) still reflects ──────────────────


def test_reflector_runs_on_lane_b_single_step():
    s = LoopState(session_id="x", run_id="y")
    plan = Plan(
        steps=(PlanStep(id="only", intent="quick lookup"),),
        should_loop=False,
    )
    s.set_plan(plan)
    s.transition(LoopStateName.STEP)
    s.transition(LoopStateName.ACTING)
    out = StepOutcome(
        step_id="only",
        status="ok",
        observation="No claims here. Just facts.",
        citations=[],
        tool_calls=[],
    )
    res = Reflector().evaluate(state=s, step=plan.steps[0], outcome=out)
    # The reflector does not look at should_loop; it just evaluates.
    assert res.verdict == "ok"


# ── Plan-revision budget honoured by FSM ────────────────────────────


def test_reflector_verdict_routes_through_fsm_mapping(fsm):
    res = ReflectorResult(verdict="ok")
    target = fsm.apply_reflector_verdict(res.verdict)
    assert target == LoopStateName.STEP  # has more steps after s1


# ── Telemetry helper ────────────────────────────────────────────────


def test_make_reflection_event_validates_through_typed_schema():
    res = ReflectorResult(verdict="retry", notes="uncited claim")
    evt = make_reflection_event(step_id="s1", result=res, run_id="r")
    assert evt["event"] == "loop.reflection"
    assert evt["verdict"] == "retry"
    assert evt["notes"] == "uncited claim"
    assert evt["run_id"] == "r"
