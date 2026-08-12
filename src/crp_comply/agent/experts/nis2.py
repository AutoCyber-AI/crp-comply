# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""NIS2 regulation expert.

Retrieves provisions from the NIS2 corpus with deterministic entity
classification (essential / important) and intent-to-article routing for
cybersecurity risk management, incident reporting and supply-chain obligations.
"""

from __future__ import annotations

from .base import ExpertContext, ExpertFinding, ExpertReport, RegulationExpert
from ..user_need import UserNeed


class Nis2Expert(RegulationExpert):
    """Expert subagent for Directive (EU) 2022/2555 (NIS2)."""

    name = "nis2_expert"
    regulations = (
        "nis2",
        "network and information systems directive",
        "directive (eu) 2022/2555",
    )

    # Deterministic intent → article hints for the most common NIS2 questions.
    _INTENT_ARTICLES = {
        "entity classification": ["art2", "art3", "annex i", "annex ii"],
        "essential entity": ["art3", "annex i"],
        "important entity": ["art3", "annex ii"],
        "risk management": ["art21"],
        "cybersecurity risk management": ["art21"],
        "incident reporting": ["art23"],
        "supply chain": ["art22"],
        "supply chain security": ["art22"],
        "supervision": ["art32", "art33"],
        "penalties": ["art34"],
        "csirt": ["art8", "art9"],
        "information sharing": ["art24"],
    }

    # Sector keyword → likely NIS2 Annex I/II category (for scoping questions).
    _ESSENTIAL_SECTOR_SIGNALS = {
        "energy",
        "electricity",
        "transport",
        "banking",
        "financial market",
        "health",
        "drinking water",
        "waste water",
        "digital infrastructure",
        "ict",
        "public administration",
        "space",
    }
    _IMPORTANT_SECTOR_SIGNALS = {
        "postal",
        "waste",
        "manufacturing",
        "digital provider",
        "online marketplace",
        "online search engine",
        "social networking",
        "research",
        "chemical",
        "food",
        "medical device",
    }

    def can_handle(self, user_need: UserNeed) -> bool:
        regulation = (user_need.regulation or "").lower()
        return any(r in regulation for r in self.regulations)

    def investigate(self, user_need: UserNeed, context: ExpertContext) -> ExpertReport:
        report = ExpertReport(
            regulation="nis2",
            intent=user_need.intent,
            recommended_depth=user_need.depth,
        )

        query = self._build_query(user_need)
        article_filter = self._article_hints(user_need)
        entity_class = self._classify_entity(user_need)

        # Add a deterministic classification finding when the user describes a sector.
        if entity_class:
            report.findings.append(
                ExpertFinding(
                    claim=f"Based on the described sector, the entity appears to fall under the '{entity_class}' category in NIS2.",
                    basis="Article 3 / Annexes I–II NIS2",
                    source_id="nis2",
                    confidence=0.75,
                )
            )

        if context.rag is not None:
            hits = context.rag.query(
                query,
                top_k=8,
                source_filter=["nis2"],
            )
            # Boost article-hint matches when an article_id is present.
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
                        basis=h.get("article_id") or h.get("section_path", "NIS2"),
                        source_id=h.get("source_id", "nis2"),
                        source_url=h.get("source_url"),
                        confidence=float(h.get("score", 0.0)),
                        excerpt=h.get("text", "")[:400],
                    )
                )
            report.citations.extend(
                [
                    {
                        "source_id": h.get("source_id", "nis2"),
                        "clause": h.get("article_id"),
                        "url": h.get("source_url"),
                        "excerpt": (h.get("text") or "")[:240],
                    }
                    for h in hits
                ]
            )

        if not report.findings:
            report.open_questions.append(
                "Could you tell me which NIS2 topic you need (e.g. entity classification, risk management under Article 21, incident reporting under Article 23)?"
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

    def _classify_entity(self, user_need: UserNeed) -> str:
        """Return a lightweight entity-class signal based on sector keywords."""
        lowered = " ".join(
            p.lower() for p in (user_need.system_type, user_need.purpose, user_need.intent) if p
        )
        essential_hits = [s for s in self._ESSENTIAL_SECTOR_SIGNALS if s in lowered]
        important_hits = [s for s in self._IMPORTANT_SECTOR_SIGNALS if s in lowered]
        if essential_hits and not important_hits:
            return "essential entity"
        if important_hits and not essential_hits:
            return "important entity"
        if essential_hits and important_hits:
            return "essential or important entity (sector-specific sizing required)"
        return ""
