# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""ISO/IEC 42001 regulation expert.

Retrieves clause pointers and control mappings from the ISO 42001 corpus and
surfaces copyright-safe surrogates. The main loop's LLM synthesises the final
answer and directs the user to the official ISO publication for verbatim text.
"""

from __future__ import annotations

from .base import ExpertContext, ExpertFinding, ExpertReport, RegulationExpert
from ..user_need import UserNeed


class Iso42001Expert(RegulationExpert):
    """Expert subagent for ISO/IEC 42001 AI management system standard."""

    name = "iso_42001_expert"
    regulations = ("iso 42001", "iso_42001", "iso 42001:2023")

    def can_handle(self, user_need: UserNeed) -> bool:
        regulation = (user_need.regulation or "").lower()
        return any(r in regulation for r in self.regulations)

    def investigate(self, user_need: UserNeed, context: ExpertContext) -> ExpertReport:
        report = ExpertReport(
            regulation="iso_42001",
            intent=user_need.intent,
            recommended_depth=user_need.depth,
        )

        query = self._build_query(user_need)
        if context.rag is not None:
            hits = context.rag.query(
                query,
                top_k=6,
                source_filter=["iso_42001", "iso_22989"],
            )
            for h in hits:
                report.findings.append(
                    ExpertFinding(
                        claim=h.get("text", "")[:240],
                        basis=h.get("article_id") or h.get("section_path", "ISO 42001"),
                        source_id=h.get("source_id", "iso_42001"),
                        source_url=h.get("source_url"),
                        confidence=float(h.get("score", 0.0)),
                        excerpt=h.get("text", "")[:400],
                    )
                )
            report.citations.extend(
                [
                    {
                        "source_id": h.get("source_id", "iso_42001"),
                        "clause": h.get("article_id"),
                        "url": h.get("source_url"),
                        "excerpt": (h.get("text") or "")[:240],
                    }
                    for h in hits
                ]
            )

        if not report.findings:
            report.open_questions.append(
                "Could you tell me which ISO 42001 clause or topic (e.g., risk assessment, policy, Annex A control) you need?"
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
        if user_need.task_type:
            parts.append(user_need.task_type)
        return " ".join(p for p in parts if p)
