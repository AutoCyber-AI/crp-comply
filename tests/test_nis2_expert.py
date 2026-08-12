# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for the NIS2 regulation expert."""

from __future__ import annotations

from typing import Any

from crp_comply.agent.experts import ExpertContext, Nis2Expert
from crp_comply.agent.user_need import UserNeed


class _FakeRag:
    def __init__(self, hits: list[dict[str, Any]]) -> None:
        self._hits = hits

    def query(
        self,
        query: str,
        *,
        top_k: int,
        source_filter: list[str] | None,
    ) -> list[dict[str, Any]]:
        assert "nis2" in source_filter
        return list(self._hits)


def test_nis2_expert_handles_nis2() -> None:
    expert = Nis2Expert()
    need = UserNeed(intent="entity classification", regulation="NIS2")
    assert expert.can_handle(need)


def test_nis2_expert_declines_gdpr() -> None:
    expert = Nis2Expert()
    need = UserNeed(intent="data subject rights", regulation="GDPR")
    assert not expert.can_handle(need)


def test_nis2_expert_returns_findings() -> None:
    hits = [
        {
            "text": "Article 3 defines essential and important entities.",
            "article_id": "art3",
            "source_id": "nis2",
            "score": 0.92,
        },
        {
            "text": "Article 21 requires a cybersecurity risk-management measure.",
            "article_id": "art21",
            "source_id": "nis2",
            "score": 0.85,
        },
    ]
    expert = Nis2Expert()
    need = UserNeed(intent="risk management", regulation="NIS2", system_type="energy provider")
    report = expert.investigate(need, ExpertContext(rag=_FakeRag(hits)))
    assert report.regulation == "nis2"
    assert len(report.findings) >= 2
    assert any(f.basis == "art21" for f in report.findings)
    assert any(f.source_id == "nis2" for f in report.findings)
    assert report.citations
    assert report.confidence > 0


def test_nis2_expert_classifies_essential_entity() -> None:
    expert = Nis2Expert()
    need = UserNeed(
        intent="entity classification",
        regulation="NIS2",
        system_type="electricity transmission operator",
    )
    report = expert.investigate(need, ExpertContext(rag=None))
    assert any("essential entity" in f.claim.lower() for f in report.findings)


def test_nis2_expert_no_rag_asks_clarification() -> None:
    expert = Nis2Expert()
    need = UserNeed(intent="supply chain", regulation="NIS2")
    report = expert.investigate(need, ExpertContext(rag=None))
    assert not report.findings
    assert report.open_questions
