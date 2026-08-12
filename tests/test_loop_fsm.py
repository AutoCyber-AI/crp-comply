"""LoopState FSM + Planner tests \u2014 PHASE_7 \u00a721 7.3.

Acceptance criteria:

* Every legal transition succeeds.
* Every illegal transition raises :class:`LoopStateError`.
* Free-form state strings are rejected.
* Lane B (degenerate) plan still flows PLANNING \u2192 STEP \u2192 ACTING \u2192
  REFLECT \u2192 FINALISE \u2192 DONE so the same SSE events fire.
* Planner.normalise_plan rejects zero-step plans, duplicate IDs,
  unknown ``tool_hint`` values, and non-bool ``should_loop``.
* Plan revision budget enforced.
* Reflector-verdict \u2192 FSM-transition mapping covers all five
  verdicts.
* ``Plan.to_event_payload()`` validates against the typed
  ``loop.plan`` schema.
"""

from __future__ import annotations

import itertools

import pytest

from crp_comply.agent.loop_state import (
    VALID_TRANSITIONS,
    LoopState,
    LoopStateError,
    LoopStateName,
    Plan,
    Planner,
    PlanStep,
    default_should_loop_for,
)
from crp_comply.agent.triage import TriageResult
from crp_comply.api.events import validate_event


def _trivial_triage(intent: str = "cite", lane: str = "fast") -> TriageResult:
    return TriageResult(
        complexity="trivial",
        intent=intent,  # type: ignore[arg-type]
        confidence=0.95,
        lane=lane,  # type: ignore[arg-type]
        reasoning="test",
    )


def _state(initial: LoopStateName = LoopStateName.PLANNING) -> LoopState:
    s = LoopState(session_id="sess", run_id="r1", state=initial)
    return s


# ── Transition table (fully enumerated) ─────────────────────────────


def test_legal_transitions_all_succeed() -> None:
    for src, dests in VALID_TRANSITIONS.items():
        for dst in dests:
            s = _state(src)
            s.transition(dst, reason="enum-test")
            assert s.state is dst


def test_every_illegal_transition_raises() -> None:
    all_states = list(LoopStateName)
    for src, dst in itertools.product(all_states, repeat=2):
        if dst in VALID_TRANSITIONS.get(src, frozenset()):
            continue
        s = _state(src)
        with pytest.raises(LoopStateError, match="illegal transition"):
            s.transition(dst)


def test_terminal_states_have_no_outgoing() -> None:
    assert VALID_TRANSITIONS[LoopStateName.DONE] == frozenset()
    assert VALID_TRANSITIONS[LoopStateName.ERROR] == frozenset()


def test_freeform_state_rejected() -> None:
    s = _state()
    with pytest.raises(LoopStateError, match="LoopStateName"):
        s.transition("STEP")  # type: ignore[arg-type]


# ── Lane B degenerate run ───────────────────────────────────────────


def test_lane_b_full_path() -> None:
    """Even fast-path runs must traverse the full FSM."""
    s = _state()
    plan = Plan(
        steps=(PlanStep(id="s1", intent="cite", tool_hint="pattern_query"),),
        should_loop=False,
    )
    s.set_plan(plan)
    s.transition(LoopStateName.STEP)
    s.transition(LoopStateName.ACTING)
    s.transition(LoopStateName.REFLECT)
    target = s.apply_reflector_verdict("ok")
    assert target is LoopStateName.FINALISE  # nothing after step 0
    s.transition(target)
    s.transition(LoopStateName.DONE)
    assert s.state is LoopStateName.DONE
    # Six recorded transitions \u2014 same length as Lane C minimal happy path.
    assert len(s.history) == 5


# ── Planner contract ────────────────────────────────────────────────


def test_planner_default_heuristic_lane_b() -> None:
    p = Planner()
    plan = p.plan("cite article 6 gdpr", _trivial_triage())
    assert plan.should_loop is False
    assert len(plan.steps) == 1


def test_planner_default_heuristic_lane_c() -> None:
    p = Planner()
    plan = p.plan(
        "audit our dpia for the new hr model",
        TriageResult(
            complexity="comprehensive",
            intent="audit_existing",
            confidence=0.9,
            lane="slow",
            reasoning="t",
        ),
    )
    assert plan.should_loop is True
    assert len(plan.steps) >= 2


def test_planner_rejects_zero_steps() -> None:
    with pytest.raises(LoopStateError, match="zero steps"):
        Planner.normalise_plan(Plan(steps=(), should_loop=False))


def test_planner_rejects_duplicate_step_ids() -> None:
    bad = Plan(
        steps=(
            PlanStep(id="s1", intent="a"),
            PlanStep(id="s1", intent="b"),
        ),
        should_loop=True,
    )
    with pytest.raises(LoopStateError, match="duplicate step id"):
        Planner.normalise_plan(bad)


def test_planner_rejects_unknown_tool_hint() -> None:
    bad = Plan(
        steps=(PlanStep(id="s1", intent="x", tool_hint="rogue_tool"),),
        should_loop=False,
    )
    with pytest.raises(LoopStateError, match="unknown tool_hint"):
        Planner.normalise_plan(bad)


def test_planner_rejects_non_bool_should_loop() -> None:
    bad = Plan(
        steps=(PlanStep(id="s1", intent="x"),),
        should_loop="yes",  # type: ignore[arg-type]
    )
    with pytest.raises(LoopStateError, match="should_loop must be bool"):
        Planner.normalise_plan(bad)


def test_planner_custom_generator_used() -> None:
    sentinel = Plan(steps=(PlanStep(id="x1", intent="custom"),), should_loop=False)
    p = Planner(generate=lambda q, t: sentinel)
    out = p.plan("anything", _trivial_triage())
    assert out is sentinel


def test_default_should_loop_lanes() -> None:
    assert default_should_loop_for(_trivial_triage(lane="fast")) is False
    slow = TriageResult(
        complexity="moderate",
        intent="scope",
        confidence=0.7,
        lane="slow",
        reasoning="t",
    )
    assert default_should_loop_for(slow) is True


# ── Plan attachment + step cursor ───────────────────────────────────


def test_set_plan_only_in_planning() -> None:
    s = _state(LoopStateName.STEP)
    plan = Plan(steps=(PlanStep(id="s1", intent="x"),), should_loop=False)
    with pytest.raises(LoopStateError, match="cannot set plan"):
        s.set_plan(plan)


def test_advance_step_overshoot() -> None:
    s = _state()
    s.set_plan(Plan(steps=(PlanStep(id="s1", intent="x"),), should_loop=False))
    assert s.current_step() is not None
    s.advance_step()
    assert s.current_step() is None
    assert not s.has_more_steps()


# ── Plan revision budget ────────────────────────────────────────────


def test_plan_revision_budget_enforced() -> None:
    s = _state(LoopStateName.PLANNING)
    plan = Plan(steps=(PlanStep(id="s1", intent="x"),), should_loop=True)
    s.set_plan(plan)
    s.transition(LoopStateName.STEP)
    s.transition(LoopStateName.ACTING)
    s.transition(LoopStateName.REFLECT)
    new_plan = Plan(steps=(PlanStep(id="s2", intent="y"),), should_loop=True)
    # 3 revisions allowed by default.
    s.revise_plan(new_plan)
    s.revise_plan(new_plan)
    s.revise_plan(new_plan)
    with pytest.raises(LoopStateError, match="revision budget"):
        s.revise_plan(new_plan)


def test_revise_plan_only_in_reflect() -> None:
    s = _state(LoopStateName.STEP)
    plan = Plan(steps=(PlanStep(id="s1", intent="x"),), should_loop=False)
    with pytest.raises(LoopStateError, match="cannot revise plan"):
        s.revise_plan(plan)


# ── Reflector verdict mapping ───────────────────────────────────────


@pytest.mark.parametrize(
    "verdict,expected",
    [
        ("retry", LoopStateName.STEP),
        ("revise_plan", LoopStateName.PLANNING),
        ("clarify_first", LoopStateName.AWAITING_USER),
        ("abort", LoopStateName.ERROR),
    ],
)
def test_verdict_mapping(verdict, expected) -> None:
    _state(LoopStateName.REFLECT)
    plan = Plan(
        steps=(
            PlanStep(id="s1", intent="x"),
            PlanStep(id="s2", intent="y"),
        ),
        should_loop=True,
    )
    # Inject plan via a clean PLANNING state so the cursor is sane.
    s2 = _state(LoopStateName.PLANNING)
    s2.set_plan(plan)
    s2.state = LoopStateName.REFLECT  # type: ignore[assignment]
    target = s2.apply_reflector_verdict(verdict)
    assert target is expected


def test_verdict_ok_finalises_when_last_step() -> None:
    s = _state(LoopStateName.PLANNING)
    s.set_plan(Plan(steps=(PlanStep(id="s1", intent="x"),), should_loop=False))
    s.state = LoopStateName.REFLECT
    assert s.apply_reflector_verdict("ok") is LoopStateName.FINALISE


def test_verdict_ok_loops_when_more_steps() -> None:
    s = _state(LoopStateName.PLANNING)
    s.set_plan(
        Plan(
            steps=(
                PlanStep(id="s1", intent="x"),
                PlanStep(id="s2", intent="y"),
            ),
            should_loop=True,
        )
    )
    s.state = LoopStateName.REFLECT
    assert s.apply_reflector_verdict("ok") is LoopStateName.STEP


def test_unknown_verdict_raises() -> None:
    s = _state(LoopStateName.REFLECT)
    with pytest.raises(LoopStateError, match="unknown reflector verdict"):
        s.apply_reflector_verdict("magical")  # type: ignore[arg-type]


# ── Clarifier budget ────────────────────────────────────────────────


def test_clarifier_budget_enforced() -> None:
    s = _state()
    for _ in range(s.max_clarifiers):
        s.record_clarifier()
    with pytest.raises(LoopStateError, match="clarifier budget"):
        s.record_clarifier()


# ── Plan event payload validates ────────────────────────────────────


def test_plan_event_payload_validates() -> None:
    plan = Plan(
        steps=(
            PlanStep(id="s1", intent="recall", tool_hint="recall_facts"),
            PlanStep(id="s2", intent="answer", tool_hint="pattern_query"),
        ),
        should_loop=True,
    )
    out = validate_event("loop.plan", plan.to_event_payload())
    assert out["should_loop"] is True
    assert out["steps"][0]["id"] == "s1"


# ── Snapshot for AWAITING_USER persistence ──────────────────────────


def test_snapshot_round_trip_keys() -> None:
    s = _state()
    s.set_plan(Plan(steps=(PlanStep(id="s1", intent="x"),), should_loop=False))
    snap = s.snapshot()
    assert snap["session_id"] == "sess"
    assert snap["state"] == "PLANNING"
    assert snap["plan"]["steps"][0]["id"] == "s1"
