# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for the UK AI Act regulation expert."""

from __future__ import annotations

from crp_comply.agent.experts import ExpertContext, UkAiActExpert
from crp_comply.agent.user_need import UserNeed


def test_uk_ai_act_expert_handles_uk_ai_act() -> None:
    expert = UkAiActExpert()
    need = UserNeed(intent="risk tier", regulation="UK AI Act")
    assert expert.can_handle(need)


def test_uk_ai_act_expert_declines_gdpr() -> None:
    expert = UkAiActExpert()
    need = UserNeed(intent="data subject rights", regulation="GDPR")
    assert not expert.can_handle(need)


def test_uk_ai_act_expert_returns_findings_with_citations() -> None:
    expert = UkAiActExpert()
    need = UserNeed(
        intent="high risk obligations",
        regulation="UK AI Act",
        system_type="hiring assistant",
    )
    report = expert.investigate(need, ExpertContext(rag=None))
    assert report.regulation == "uk_ai_act"
    assert report.findings
    assert any("high" in f.claim.lower() for f in report.findings)
    assert all(f.source_id == "uk_ai_act" for f in report.findings)
    assert report.confidence > 0


def test_uk_ai_act_expert_classifies_high_risk() -> None:
    expert = UkAiActExpert()
    need = UserNeed(
        intent="risk classification",
        regulation="UK AI Act",
        system_type="medical diagnostic tool",
    )
    report = expert.investigate(need, ExpertContext(rag=None))
    assert any("high" in f.claim.lower() for f in report.findings)


def test_uk_ai_act_expert_no_rag_asks_clarification() -> None:
    expert = UkAiActExpert()
    need = UserNeed(intent="unknown", regulation="UK AI Act")
    report = expert.investigate(need, ExpertContext(rag=None))
    assert not report.findings
    assert report.open_questions
