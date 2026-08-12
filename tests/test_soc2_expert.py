# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for the SOC 2 regulation expert."""

from __future__ import annotations

from crp_comply.agent.experts import ExpertContext, Soc2Expert
from crp_comply.agent.user_need import UserNeed


def test_soc2_expert_handles_soc2() -> None:
    expert = Soc2Expert()
    need = UserNeed(intent="security", regulation="SOC 2")
    assert expert.can_handle(need)


def test_soc2_expert_declines_gdpr() -> None:
    expert = Soc2Expert()
    need = UserNeed(intent="data subject rights", regulation="GDPR")
    assert not expert.can_handle(need)


def test_soc2_expert_returns_findings_with_citations() -> None:
    expert = Soc2Expert()
    need = UserNeed(
        intent="access control",
        regulation="SOC 2",
        system_type="AI platform",
    )
    report = expert.investigate(need, ExpertContext(rag=None))
    assert report.regulation == "soc2"
    assert report.findings
    assert any("TSC" in f.basis for f in report.findings)
    assert all(f.source_id == "soc2" for f in report.findings)
    assert report.confidence > 0


def test_soc2_expert_adds_ai_control() -> None:
    expert = Soc2Expert()
    need = UserNeed(
        intent="ai governance",
        regulation="SOC 2",
        system_type="machine learning pipeline",
    )
    report = expert.investigate(need, ExpertContext(rag=None))
    assert any("AI" in f.claim for f in report.findings)


def test_soc2_expert_no_rag_asks_clarification() -> None:
    expert = Soc2Expert()
    need = UserNeed(intent="unknown", regulation="SOC 2")
    report = expert.investigate(need, ExpertContext(rag=None))
    assert not report.findings
    assert report.open_questions
