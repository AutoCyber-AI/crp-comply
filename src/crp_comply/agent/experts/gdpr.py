# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""GDPR regulation expert.

Retrieves articles and recitals from the GDPR corpus, with a lightweight
intent-to-article mapping for the most common AI/data-protection questions.
"""

from __future__ import annotations

from .base import ExpertContext, ExpertFinding, ExpertReport, RegulationExpert
from ..user_need import UserNeed


class GdprExpert(RegulationExpert):
    """Expert subagent for the EU General Data Protection Regulation."""

    name = "gdpr_expert"
    regulations = ("gdpr", "general data protection regulation")

    # Fast deterministic pointers for common GDPR intents.
    _INTENT_ARTICLES = {
        "lawfulness": ["art6", "art7", "art9"],
        "consent": ["art7", "art8"],
        "data subject rights": [
            "art12",
            "art13",
            "art14",
            "art15",
            "art16",
            "art17",
            "art18",
            "art20",
            "art21",
            "art22",
        ],
        "automated decision": ["art22"],
        "profiling": ["art22", "art4"],
        "dpia": ["art35", "art36"],
        "data protection impact assessment": ["art35", "art36"],
        "controller": ["art4", "art24", "art25", "art28"],
        "processor": ["art4", "art28", "art29"],
        "security": ["art32"],
        "breach": ["art33", "art34"],
        "dpo": ["art37", "art38", "art39"],
        "international transfer": ["art44", "art45", "art46", "art47", "art49"],
        "privacy by design": ["art25"],
    }

    def can_handle(self, user_need: UserNeed) -> bool:
        regulation = (user_need.regulation or "").lower()
        return any(r in regulation for r in self.regulations)

    def investigate(self, user_need: UserNeed, context: ExpertContext) -> ExpertReport:
        report = ExpertReport(
            regulation="gdpr",
            intent=user_need.intent,
            recommended_depth=user_need.depth,
        )

        query = self._build_query(user_need)
        article_filter = self._article_hints(user_need)
        if context.rag is not None:
            hits = context.rag.query(
                query,
                top_k=8,
                source_filter=["gdpr"],
            )
            # Boost article-hint matches in the ranking we return.
            hits = sorted(
                hits,
                key=lambda h: (
                    1 if (h.get("article_id") or "").lower() in article_filter else 0,
                    float(h.get("score", 0.0)),
                ),
                reverse=True,
            )
            for h in hits:
                report.findings.append(
                    ExpertFinding(
                        claim=h.get("text", "")[:240],
                        basis=h.get("article_id") or h.get("section_path", "GDPR"),
                        source_id=h.get("source_id", "gdpr"),
                        source_url=h.get("source_url"),
                        confidence=float(h.get("score", 0.0)),
                        excerpt=h.get("text", "")[:400],
                    )
                )
            report.citations.extend(
                [
                    {
                        "source_id": h.get("source_id", "gdpr"),
                        "clause": h.get("article_id"),
                        "url": h.get("source_url"),
                        "excerpt": (h.get("text") or "")[:240],
                    }
                    for h in hits
                ]
            )

        if not report.findings:
            report.open_questions.append(
                "Could you tell me which GDPR topic or article (e.g. Article 22 automated decisions, Article 35 DPIA) you need?"
            )
        else:
            report.confidence = sum(f.confidence for f in report.findings) / len(report.findings)
        return report

    def _build_query(self, user_need: UserNeed) -> str:
        parts = [user_need.intent]
        if user_need.system_type:
            parts.append(user_need.system_type)
        if user_need.purpose:
            parts.append(user_need.purpose)
        return " ".join(p for p in parts if p)

    def _article_hints(self, user_need: UserNeed) -> set[str]:
        lowered = " ".join(
            p.lower() for p in (user_need.intent, user_need.task_type, user_need.purpose) if p
        )
        hits: set[str] = set()
        for keyword, articles in self._INTENT_ARTICLES.items():
            if keyword in lowered:
                hits.update(articles)
        return hits
