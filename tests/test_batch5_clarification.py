# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""BATCH 5 — clarification priority/skippable mechanics.

Unit-tests the ``ClarificationNeeded`` datastructure and the
``request_clarification`` tool handler's new fields.
"""

from __future__ import annotations

import pytest

from crp_comply.agent.tools import (
    ClarificationNeeded,
    build_request_clarification_tool,
)


def test_clarification_default_medium_not_skippable():
    c = ClarificationNeeded("Do you process biometric data?")
    assert c.priority == "medium"
    assert c.skippable is False
    assert c.fact_key == ""


def test_clarification_low_auto_skippable():
    c = ClarificationNeeded("Optional logo colour?", priority="low")
    assert c.priority == "low"
    assert c.skippable is True


def test_clarification_high_not_skippable_by_default():
    c = ClarificationNeeded(
        "Is the system used for recruitment?",
        priority="high",
        fact_key="used_for_recruitment",
    )
    assert c.priority == "high"
    assert c.skippable is False
    assert c.fact_key == "used_for_recruitment"


def test_clarification_explicit_skippable_overrides_default():
    c = ClarificationNeeded("...", priority="high", skippable=True)
    assert c.skippable is True


def test_clarification_invalid_priority_coerced_to_medium():
    c = ClarificationNeeded("...", priority="ULTRA")
    assert c.priority == "medium"


def test_request_clarification_tool_raises_with_priority():
    tool = build_request_clarification_tool()
    with pytest.raises(ClarificationNeeded) as exc_info:
        tool.handler(
            {
                "question": "Does the system process biometric data?",
                "priority": "high",
                "fact_key": "processes_biometric_data",
                "context": "Determines EU AI Act Annex III row 1 applicability.",
            }
        )
    clar = exc_info.value
    assert clar.priority == "high"
    assert clar.fact_key == "processes_biometric_data"
    assert clar.skippable is False
    assert "biometric" in clar.question.lower()


def test_request_clarification_tool_low_priority_auto_skippable():
    tool = build_request_clarification_tool()
    with pytest.raises(ClarificationNeeded) as exc_info:
        tool.handler({"question": "Preferred heading style?", "priority": "low"})
    assert exc_info.value.skippable is True


def test_request_clarification_tool_returns_error_on_empty_question():
    tool = build_request_clarification_tool()
    result = tool.handler({"question": ""})
    assert isinstance(result, dict)
    assert "error" in result


def test_agent_result_surfaces_pending_priority_fields():
    from crp_comply.agent.orchestrator import AgentResult

    r = AgentResult(
        state="awaiting_clarification",
        pending_question="Q",
        pending_priority="high",
        pending_skippable=False,
        pending_fact_key="used_for_recruitment",
    )
    d = r.to_dict()
    assert d["pending_priority"] == "high"
    assert d["pending_skippable"] is False
    assert d["pending_fact_key"] == "used_for_recruitment"


def test_agent_clarify_request_supports_skip():
    """AgentClarifyRequest validates skip semantics."""
    from crp_comply.api.models import AgentClarifyRequest

    req = AgentClarifyRequest(answer="", skip=True)
    assert req.skip is True
    assert req.answer == ""
    # normal answer path still works
    req2 = AgentClarifyRequest(answer="yes, we process faces")
    assert req2.skip is False
