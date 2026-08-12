# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for Round 10 research-phase planning and events."""

from __future__ import annotations

from crp_comply.agent.loop_runtime import _plan_for
from crp_comply.agent.loop_state import Phase, PlanStep
from crp_comply.agent.triage import TriageResult


def _triage(intent: str, lane: str, complexity: str = "moderate") -> TriageResult:
    return TriageResult(
        intent=intent,
        complexity=complexity,  # type: ignore[arg-type]
        confidence=0.9,
        lane=lane,  # type: ignore[arg-type]
        reasoning="test",
    )


def test_fast_path_has_research_phase() -> None:
    plan = _plan_for("What is GDPR?", _triage("define", "fast"))
    assert not plan.should_loop
    assert len(plan.steps) == 1
    assert plan.steps[0].phase == Phase.RESEARCH


def test_produce_artefact_plan_has_research_and_synthesis() -> None:
    plan = _plan_for("Draft a DPIA", _triage("produce_artefact", "slow"))
    assert plan.should_loop
    phases = [s.phase for s in plan.steps]
    assert phases == [Phase.RESEARCH, Phase.SYNTHESIS]


def test_compare_plan_has_research_and_analysis() -> None:
    plan = _plan_for("Compare EU and UK AI Act", _triage("compare", "slow"))
    phases = [s.phase for s in plan.steps]
    assert phases == [Phase.RESEARCH, Phase.RESEARCH, Phase.ANALYSIS]


def test_plan_payload_includes_phase() -> None:
    plan = _plan_for("What is GDPR?", _triage("define", "fast"))
    payload = plan.to_event_payload()
    assert payload["steps"][0]["phase"] == "RESEARCH"


def test_plan_step_accepts_phase() -> None:
    step = PlanStep(id="s1", intent="x", phase=Phase.CITATION)
    assert step.phase == Phase.CITATION
