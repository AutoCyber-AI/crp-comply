# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""SOC 2 regulation expert.

Deterministic guidance mapping SOC 2 Trust Services Categories and common
criteria to AI-relevant controls. No corpus file exists, so findings are not
corpus-backed and confidence is held lower.
"""

from __future__ import annotations

from .base import ExpertContext, ExpertFinding, ExpertReport, RegulationExpert
from ..user_need import UserNeed


class Soc2Expert(RegulationExpert):
    """Expert subagent for SOC 2 Trust Services Criteria (AICPA TSC)."""

    name = "soc2_expert"
    regulations = (
        "soc 2",
        "soc2",
        "soc ii",
        "trust services criteria",
        "aicpa tsc",
    )

    # Trust Services Category / common-criteria intent map.
    _INTENT_GUIDANCE = {
        "security": {
            "basis": "TSC CC6.1 / CC7.2 (Security)",
            "claim": "The Security category (common criteria) requires logical and physical protection of systems and data, including access control and system monitoring.",
        },
        "availability": {
            "basis": "TSC A1.2 (Availability)",
            "claim": "Availability criteria require systems to be available for operation and use as committed, with contingency planning and incident response.",
        },
        "processing integrity": {
            "basis": "TSC PI1.3 (Processing Integrity)",
            "claim": "Processing integrity requires system processing to be complete, valid, accurate, timely and authorized.",
        },
        "confidentiality": {
            "basis": "TSC C1.1 (Confidentiality)",
            "claim": "Confidentiality criteria require information designated as confidential to be protected to meet the entity's objectives.",
        },
        "privacy": {
            "basis": "TSC P1.1 (Privacy)",
            "claim": "Privacy criteria require personal information to be collected, used, retained, disclosed and disposed of in conformity with commitments and criteria.",
        },
        "access control": {
            "basis": "TSC CC6.1–CC6.3",
            "claim": "Access controls must logically restrict access to authorized users and enforce least privilege.",
        },
        "incident response": {
            "basis": "TSC CC7.3–CC7.5",
            "claim": "Security incidents must be detected, reported, assessed and responded to in a timely manner.",
        },
        "change management": {
            "basis": "TSC CC8.1",
            "claim": "Changes to systems must be managed through a controlled change-management process.",
        },
        "risk assessment": {
            "basis": "TSC CC3.1–CC3.4",
            "claim": "The entity specifies objectives with sufficient clarity to identify and assess risks to those objectives.",
        },
        "monitoring": {
            "basis": "TSC CC4.1–CC4.2",
            "claim": "The entity monitors internal control components and evaluates and communicates deficiencies.",
        },
        "ai governance": {
            "basis": "TSC CC1.3 / CC3.4 (AI-relevant)",
            "claim": "SOC 2 auditors increasingly expect documented AI governance, model risk assessment and data-quality controls for AI/ML systems in scope.",
        },
        "model risk": {
            "basis": "TSC CC3.4 / CC8.1 (AI-relevant)",
            "claim": "AI/ML model changes and risks should be documented, tested and approved through change-management and risk-assessment processes.",
        },
        "data quality": {
            "basis": "TSC PI1.3 / CC7.2 (AI-relevant)",
            "claim": "Training and inference data quality should be monitored to help ensure processing integrity and security of AI pipelines.",
        },
    }

    def can_handle(self, user_need: UserNeed) -> bool:
        regulation = (user_need.regulation or "").lower()
        return any(r in regulation for r in self.regulations)

    def investigate(self, user_need: UserNeed, context: ExpertContext) -> ExpertReport:
        report = ExpertReport(
            regulation="soc2",
            intent=user_need.intent,
            recommended_depth=user_need.depth,
        )

        # 1. Intent-based guidance.
        guidance = self._match_guidance(user_need)
        if guidance:
            report.findings.append(
                ExpertFinding(
                    claim=guidance["claim"],
                    basis=guidance["basis"],
                    source_id="soc2",
                    confidence=0.6,
                    excerpt=guidance["claim"],
                )
            )

        # 2. If AI/ML is mentioned, add an AI-relevant control finding.
        if self._mentions_ai(user_need):
            report.findings.append(
                ExpertFinding(
                    claim="AI/ML systems in a SOC 2 audit scope should demonstrate model risk assessment, data-quality controls, change management and governance documentation.",
                    basis="TSC CC1.3 / CC3.4 / CC8.1 (AI-relevant)",
                    source_id="soc2",
                    confidence=0.6,
                )
            )

        # 3. Scoped corpus retrieval (no corpus exists; kept for API consistency).
        if context.rag is not None:
            hits = context.rag.query(
                self._build_query(user_need),
                top_k=4,
                source_filter=["soc2"],
            )
            for h in hits:
                report.findings.append(
                    ExpertFinding(
                        claim=h.get("text", "")[:240],
                        basis=h.get("article_id") or h.get("section_path", "SOC 2"),
                        source_id="soc2",
                        source_url=h.get("source_url"),
                        confidence=float(h.get("score", 0.0)),
                        excerpt=h.get("text", "")[:400],
                    )
                )

        if not report.findings:
            report.open_questions.append(
                "Could you tell me which SOC 2 Trust Services Category or topic you need (e.g. Security, Availability, Processing Integrity, Confidentiality, Privacy, AI governance)?"
            )
        else:
            report.confidence = sum(f.confidence for f in report.findings) / len(report.findings)
            report.open_questions.append(
                "Which Trust Services Categories are in scope for your SOC 2 audit (e.g. Security plus Availability, Confidentiality, Processing Integrity and/or Privacy)?"
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
        for keyword in sorted(self._INTENT_GUIDANCE, key=len, reverse=True):
            if keyword in lowered:
                return self._INTENT_GUIDANCE[keyword]
        return None

    def _mentions_ai(self, user_need: UserNeed) -> bool:
        lowered = " ".join(
            p.lower()
            for p in (
                user_need.intent,
                user_need.system_type,
                user_need.purpose,
                user_need.data_type,
            )
            if p
        )
        return any(
            s in lowered
            for s in ("ai", "artificial intelligence", "ml", "machine learning", "model")
        )
