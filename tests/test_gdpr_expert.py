"""Tests for the GDPR regulation expert."""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from crp_comply.agent.experts import ExpertContext, GdprExpert
from crp_comply.agent.user_need import UserNeed


class _FakeRag:
    def __init__(self, hits):
        self._hits = hits

    def query(self, query, *, top_k, source_filter):
        assert "gdpr" in source_filter
        return list(self._hits)


def test_gdpr_expert_handles_gdpr() -> None:
    expert = GdprExpert()
    need = UserNeed(intent="What are data subject rights?", regulation="GDPR")
    assert expert.can_handle(need)


def test_gdpr_expert_declines_ai_act() -> None:
    expert = GdprExpert()
    need = UserNeed(intent="risk classification", regulation="EU AI Act")
    assert not expert.can_handle(need)


def test_gdpr_expert_returns_findings() -> None:
    hits = [
        {
            "text": "Article 15 gives the data subject the right of access.",
            "article_id": "art15",
            "source_id": "gdpr",
            "score": 0.95,
        },
        {
            "text": "Article 22 covers automated individual decision-making.",
            "article_id": "art22",
            "source_id": "gdpr",
            "score": 0.88,
        },
    ]
    expert = GdprExpert()
    need = UserNeed(intent="data subject rights", regulation="GDPR")
    report = expert.investigate(need, ExpertContext(rag=_FakeRag(hits)))
    assert report.regulation == "gdpr"
    assert len(report.findings) == 2
    assert any(f.basis == "art15" for f in report.findings)
    assert report.confidence > 0


def test_gdpr_expert_no_rag_asks_clarification() -> None:
    expert = GdprExpert()
    need = UserNeed(intent="consent", regulation="GDPR")
    report = expert.investigate(need, ExpertContext(rag=None))
    assert not report.findings
    assert len(report.open_questions) == 1
