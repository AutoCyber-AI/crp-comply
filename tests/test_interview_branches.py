# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for the branching interview DSL (Gap #1, DSL portion)."""

from __future__ import annotations

from crp_comply.recipes.loader import (
    ClarificationSpec,
    InterviewBranch,
    Recipe,
    RecipeSection,
    _parse_interview_branches,
)
from crp_comply.recipes.human_inputs import enumerate_human_inputs


def test_parse_interview_branches_from_yaml_dict():
    raw = [
        {
            "id": "data_subjects",
            "when": ["uses_personal_data"],
            "citation": "GDPR Art. 4(1)",
            "ask": {
                "automated_decisions": {
                    "question": "Does the system make automated decisions?",
                    "priority": "high",
                    "citation": "GDPR Art. 22",
                }
            },
        },
        {
            "id": "high_stakes",
            "when": ["uses_personal_data", "automated_decisions"],
            "ask": {
                "human_in_the_loop": {
                    "question": "Is there a human in the loop?",
                    "priority": "high",
                }
            },
        },
    ]
    branches = _parse_interview_branches(raw)
    assert len(branches) == 2
    assert branches[0].id == "data_subjects"
    assert branches[0].citation == "GDPR Art. 4(1)"
    assert "automated_decisions" in branches[0].ask
    assert branches[0].ask["automated_decisions"].priority == "high"


def test_recipe_loads_interview_branches_from_dict():
    r = Recipe.from_dict(
        {
            "id": "x",
            "title": "x",
            "regulation": "x",
            "sections": [{"id": "s1", "title": "S"}],
            "interview_branches": [
                {
                    "id": "branch1",
                    "when": ["uses_personal_data"],
                    "ask": {"q1": {"question": "Q1?"}},
                }
            ],
        }
    )
    assert len(r.interview_branches) == 1
    assert r.interview_branches[0].id == "branch1"


def test_enumerate_human_inputs_includes_active_branches():
    branch = InterviewBranch(
        id="b1",
        when=["uses_personal_data"],
        citation="GDPR Art. 4",
        ask={
            "automated_decisions": ClarificationSpec(
                question="Auto decisions?",
                priority="high",
            )
        },
    )
    r = Recipe(
        recipe_id="r",
        title="t",
        regulation="GDPR",
        sections=[RecipeSection(id="s1", title="S")],
        interview_branches=[branch],
    )
    profile = {"uses_personal_data": True}
    items = enumerate_human_inputs(r, profile=profile, inputs={})
    keys = {it.key for it in items}
    assert "automated_decisions" in keys
    matched = next(it for it in items if it.key == "automated_decisions")
    assert matched.source == "interview_branch"
    # Branch citation propagates when spec doesn't override
    assert matched.citation == "GDPR Art. 4"


def test_inactive_branch_is_skipped():
    branch = InterviewBranch(
        id="b1",
        when=["uses_personal_data"],
        ask={"automated_decisions": ClarificationSpec(question="Auto?")},
    )
    r = Recipe(
        recipe_id="r",
        title="t",
        regulation="GDPR",
        sections=[RecipeSection(id="s1", title="S")],
        interview_branches=[branch],
    )
    items = enumerate_human_inputs(r, profile={"uses_personal_data": False}, inputs={})
    assert "automated_decisions" not in {it.key for it in items}


def test_branch_skipped_when_fact_already_known():
    branch = InterviewBranch(
        id="b1",
        when=["uses_personal_data"],
        ask={"automated_decisions": ClarificationSpec(question="Auto?")},
    )
    r = Recipe(
        recipe_id="r",
        title="t",
        regulation="GDPR",
        sections=[RecipeSection(id="s1", title="S")],
        interview_branches=[branch],
    )
    profile = {"uses_personal_data": True, "automated_decisions": True}
    items = enumerate_human_inputs(r, profile=profile, inputs={})
    assert "automated_decisions" not in {it.key for it in items}
