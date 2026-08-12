# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for the NIST AI RMF regulation expert."""

from __future__ import annotations

from typing import Any

from crp_comply.agent.experts import ExpertContext, NistAiRmfExpert
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
        assert "nist_ai_rmf_core" in source_filter
        assert "nist_ai_rmf_genai" in source_filter
        return list(self._hits)


def test_nist_ai_rmf_expert_handles_nist() -> None:
    expert = NistAiRmfExpert()
    need = UserNeed(intent="governance", regulation="NIST AI RMF")
    assert expert.can_handle(need)


def test_nist_ai_rmf_expert_declines_gdpr() -> None:
    expert = NistAiRmfExpert()
    need = UserNeed(intent="data subject rights", regulation="GDPR")
    assert not expert.can_handle(need)


def test_nist_ai_rmf_expert_returns_findings() -> None:
    hits = [
        {
            "text": "GOV-1 establishes policies and processes for AI risk management.",
            "article_id": "GOV-1",
            "source_id": "nist_ai_rmf_core",
            "score": 0.91,
        },
        {
            "text": "GOV-5 requires transparent communication about AI risk.",
            "article_id": "GOV-5",
            "source_id": "nist_ai_rmf_core",
            "score": 0.84,
        },
    ]
    expert = NistAiRmfExpert()
    need = UserNeed(intent="governance", regulation="NIST AI RMF")
    report = expert.investigate(need, ExpertContext(rag=_FakeRag(hits)))
    assert report.regulation == "nist_ai_rmf"
    assert len(report.findings) >= 2
    assert any(f.basis == "GOV-1" for f in report.findings)
    assert any(f.source_id == "nist_ai_rmf_core" for f in report.findings)
    assert report.citations
    assert report.confidence > 0


def test_nist_ai_rmf_expert_maps_function() -> None:
    expert = NistAiRmfExpert()
    need = UserNeed(intent="measure model risk", regulation="NIST AI RMF")
    report = expert.investigate(need, ExpertContext(rag=None))
    assert any("MEASURE" in f.claim for f in report.findings)
    assert any(f.source_id == "nist_ai_rmf_core" for f in report.findings)


def test_nist_ai_rmf_expert_no_rag_asks_clarification() -> None:
    expert = NistAiRmfExpert()
    need = UserNeed(intent="unknown", regulation="NIST AI RMF")
    report = expert.investigate(need, ExpertContext(rag=None))
    assert not report.findings
    assert report.open_questions
