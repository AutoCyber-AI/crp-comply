# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for the DORA regulation expert."""

from __future__ import annotations

from crp_comply.agent.experts import DoraExpert, ExpertContext
from crp_comply.agent.user_need import UserNeed


def test_dora_expert_handles_dora() -> None:
    expert = DoraExpert()
    need = UserNeed(intent="ict risk management", regulation="DORA")
    assert expert.can_handle(need)


def test_dora_expert_declines_gdpr() -> None:
    expert = DoraExpert()
    need = UserNeed(intent="data subject rights", regulation="GDPR")
    assert not expert.can_handle(need)


def test_dora_expert_returns_findings_with_citations() -> None:
    expert = DoraExpert()
    need = UserNeed(
        intent="incident reporting",
        regulation="DORA",
        system_type="bank",
    )
    report = expert.investigate(need, ExpertContext(rag=None))
    assert report.regulation == "dora"
    assert report.findings
    assert any("Article 11" in f.basis for f in report.findings)
    assert all(f.source_id == "dora" for f in report.findings)
    assert report.confidence > 0
    assert all(f.confidence <= 0.7 for f in report.findings)


def test_dora_expert_no_rag_asks_clarification() -> None:
    expert = DoraExpert()
    need = UserNeed(intent="unknown", regulation="DORA")
    report = expert.investigate(need, ExpertContext(rag=None))
    assert not report.findings
    assert report.open_questions
