# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""DORA regulation expert.

Deterministic guidance for Regulation (EU) 2022/2554 (DORA) based on a
structured intent-to-article/control map. No corpus file exists, so findings
are not corpus-backed and confidence is held lower.
"""

from __future__ import annotations

from .base import ExpertContext, ExpertFinding, ExpertReport, RegulationExpert
from ..user_need import UserNeed


class DoraExpert(RegulationExpert):
    """Expert subagent for the Digital Operational Resilience Act (DORA)."""

    name = "dora_expert"
    regulations = (
        "dora",
        "digital operational resilience act",
        "regulation (eu) 2022/2554",
    )

    # Deterministic intent → DORA article/control map.
    _INTENT_GUIDANCE = {
        "ict risk management": {
            "basis": "Article 6 DORA",
            "claim": "Financial entities must establish, maintain and review an ICT risk-management framework as part of their overall risk-management system.",
        },
        "ict incident management": {
            "basis": "Article 11 DORA",
            "claim": "Financial entities must implement a cyber incident management process and report major ICT-related incidents to the lead overseer/competent authority.",
        },
        "incident reporting": {
            "basis": "Article 11 DORA",
            "claim": "Major ICT-related incidents must be reported without undue delay, and initial notifications followed by intermediate and final reports.",
        },
        "digital operational resilience testing": {
            "basis": "Article 24 DORA",
            "claim": "Financial entities must periodically test their ICT systems and processes, including threat-led penetration testing for significant entities.",
        },
        "penetration testing": {
            "basis": "Article 24 DORA",
            "claim": "Significant financial entities must carry out threat-led penetration testing at least every three years.",
        },
        "third party risk": {
            "basis": "Article 28 DORA",
            "claim": "Financial entities must manage ICT third-party risk, including concentration risk and key contractual provisions for critical ICT service providers.",
        },
        "critical ict service provider": {
            "basis": "Article 31 DORA",
            "claim": "Critical ICT third-party service providers are subject to an oversight framework led by the Lead Overseer.",
        },
        "information sharing": {
            "basis": "Article 27 DORA",
            "claim": "Financial entities may exchange cyber threat information and intelligence among themselves subject to confidentiality and competition-law safeguards.",
        },
        "governance": {
            "basis": "Article 5 DORA",
            "claim": "The management body of a financial entity is ultimately responsible for ICT risk management and digital operational resilience.",
        },
    }

    # Signals that help scope whether DORA likely applies.
    _FINANCIAL_SECTOR_SIGNALS = {
        "bank",
        "insurer",
        "insurance",
        "investment firm",
        "payment institution",
        "crypto-asset",
        "credit institution",
        "asset manager",
        "pension fund",
        "financial entity",
    }

    def can_handle(self, user_need: UserNeed) -> bool:
        regulation = (user_need.regulation or "").lower()
        return any(r in regulation for r in self.regulations)

    def investigate(self, user_need: UserNeed, context: ExpertContext) -> ExpertReport:
        report = ExpertReport(
            regulation="dora",
            intent=user_need.intent,
            recommended_depth=user_need.depth,
        )

        guidance = self._match_guidance(user_need)
        if guidance:
            report.findings.append(
                ExpertFinding(
                    claim=guidance["claim"],
                    basis=guidance["basis"],
                    source_id="dora",
                    confidence=0.6,
                    excerpt=guidance["claim"],
                )
            )

        # If the user has a corpus backend, still try a scoped query; but DORA
        # is not expected to be present.  The deterministic map remains primary.
        if context.rag is not None:
            hits = context.rag.query(
                self._build_query(user_need),
                top_k=4,
                source_filter=["dora"],
            )
            for h in hits:
                report.findings.append(
                    ExpertFinding(
                        claim=h.get("text", "")[:240],
                        basis=h.get("article_id") or h.get("section_path", "DORA"),
                        source_id="dora",
                        source_url=h.get("source_url"),
                        confidence=float(h.get("score", 0.0)),
                        excerpt=h.get("text", "")[:400],
                    )
                )

        if not report.findings:
            report.open_questions.append(
                "Could you tell me which DORA topic you need (e.g. ICT risk management, incident reporting, digital operational resilience testing, or third-party risk)?"
            )
        else:
            report.confidence = sum(f.confidence for f in report.findings) / len(report.findings)
            # Always ask a clarifying scope question because DORA has a strong
            # financial-sector scope and no corpus backing.
            if not self._in_financial_sector(user_need):
                report.open_questions.append(
                    "What type of financial entity are you (e.g. bank, insurer, payment institution, investment firm), or are you a critical ICT third-party service provider?"
                )
        return report

    def _build_query(self, user_need: UserNeed) -> str:
        parts = [user_need.intent]
        if user_need.system_type:
            parts.append(user_need.system_type)
        if user_need.purpose:
            parts.append(user_need.purpose)
        return " ".join(p for p in parts if p)

    def _match_guidance(self, user_need: UserNeed) -> dict[str, str] | None:
        lowered = " ".join(
            p.lower() for p in (user_need.intent, user_need.task_type, user_need.purpose) if p
        )
        for keyword, guidance in self._INTENT_GUIDANCE.items():
            if keyword in lowered:
                return guidance
        return None

    def _in_financial_sector(self, user_need: UserNeed) -> bool:
        lowered = " ".join(
            p.lower() for p in (user_need.system_type, user_need.purpose, user_need.intent) if p
        )
        return any(signal in lowered for signal in self._FINANCIAL_SECTOR_SIGNALS)
