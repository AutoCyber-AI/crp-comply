# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for the HIPAA regulation expert."""

from __future__ import annotations

from crp_comply.agent.experts import ExpertContext, HipaaExpert
from crp_comply.agent.user_need import UserNeed


def test_hipaa_expert_handles_hipaa() -> None:
    expert = HipaaExpert()
    need = UserNeed(intent="phi", regulation="HIPAA")
    assert expert.can_handle(need)


def test_hipaa_expert_declines_gdpr() -> None:
    expert = HipaaExpert()
    need = UserNeed(intent="data subject rights", regulation="GDPR")
    assert not expert.can_handle(need)


def test_hipaa_expert_returns_findings_with_citations() -> None:
    expert = HipaaExpert()
    need = UserNeed(
        intent="business associate agreement",
        regulation="HIPAA",
        system_type="AI triage tool",
    )
    report = expert.investigate(need, ExpertContext(rag=None))
    assert report.regulation == "hipaa"
    assert report.findings
    assert any("45 CFR" in f.basis for f in report.findings)
    assert all(f.source_id == "hipaa" for f in report.findings)
    assert report.confidence > 0


def test_hipaa_expert_detects_phi_handling() -> None:
    expert = HipaaExpert()
    need = UserNeed(
        intent="ai",
        regulation="HIPAA",
        system_type="clinical decision support",
        data_type="patient records",
    )
    report = expert.investigate(need, ExpertContext(rag=None))
    assert any("PHI" in f.claim for f in report.findings)


def test_hipaa_expert_no_rag_asks_clarification() -> None:
    expert = HipaaExpert()
    need = UserNeed(intent="unknown", regulation="HIPAA")
    report = expert.investigate(need, ExpertContext(rag=None))
    assert not report.findings
    assert report.open_questions
