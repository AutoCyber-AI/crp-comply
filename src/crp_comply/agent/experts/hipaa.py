# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""HIPAA regulation expert.

Deterministic guidance for the US Health Insurance Portability and
Accountability Act as it applies to AI/ML systems handling PHI. No corpus file
exists, so findings are not corpus-backed and confidence is held lower.
"""

from __future__ import annotations

from .base import ExpertContext, ExpertFinding, ExpertReport, RegulationExpert
from ..user_need import UserNeed


class HipaaExpert(RegulationExpert):
    """Expert subagent for HIPAA (Privacy Rule, Security Rule, Breach Notification)."""

    name = "hipaa_expert"
    regulations = (
        "hipaa",
        "health insurance portability and accountability act",
        "hipaa privacy rule",
        "hipaa security rule",
    )

    # Intent → HIPAA rule / concept.
    _INTENT_GUIDANCE = {
        "phi": {
            "basis": "45 CFR § 160.103 (PHI definition)",
            "claim": "Protected Health Information (PHI) is individually identifiable health information held or transmitted by a covered entity or business associate.",
        },
        "protected health information": {
            "basis": "45 CFR § 160.103",
            "claim": "PHI is individually identifiable health information held or transmitted by a covered entity or business associate in any form or medium.",
        },
        "privacy rule": {
            "basis": "45 CFR Part 164 Subpart E",
            "claim": "The HIPAA Privacy Rule governs the use and disclosure of PHI by covered entities and requires minimum necessary safeguards.",
        },
        "security rule": {
            "basis": "45 CFR Part 164 Subpart C",
            "claim": "The HIPAA Security Rule requires administrative, physical and technical safeguards to ensure the confidentiality, integrity and availability of electronic PHI.",
        },
        "minimum necessary": {
            "basis": "45 CFR § 164.502(b)",
            "claim": "Covered entities must make reasonable efforts to limit PHI to the minimum necessary to accomplish the intended purpose.",
        },
        "de-identification": {
            "basis": "45 CFR § 164.514(a)-(c)",
            "claim": "PHI is not individually identifiable if de-identified under the Safe Harbor or expert determination methods.",
        },
        "business associate agreement": {
            "basis": "45 CFR § 164.504(e)",
            "claim": "Covered entities must enter into a Business Associate Agreement (BAA) with business associates that create, receive, maintain or transmit PHI on their behalf.",
        },
        "baa": {
            "basis": "45 CFR § 164.504(e)",
            "claim": "A Business Associate Agreement (BAA) is required when a business associate handles PHI for a covered entity.",
        },
        "breach notification": {
            "basis": "45 CFR §§ 164.400–414",
            "claim": "Covered entities must notify affected individuals, HHS and, in large cases, the media of breaches of unsecured PHI.",
        },
        "authorization": {
            "basis": "45 CFR § 164.508",
            "claim": "Uses and disclosures of PHI for purposes other than treatment, payment or healthcare operations generally require a valid individual authorization.",
        },
        "ai": {
            "basis": "HIPAA + AI/ML guidance",
            "claim": "AI/ML systems that process PHI must comply with the Privacy Rule, Security Rule, breach-notification obligations and Business Associate Agreement requirements.",
        },
    }

    # Signals that the described organisation is likely a covered entity.
    _COVERED_ENTITY_SIGNALS = {
        "health plan",
        "healthcare provider",
        "hospital",
        "clinic",
        "doctor",
        "insurer",
        "clearinghouse",
        "covered entity",
    }

    def can_handle(self, user_need: UserNeed) -> bool:
        regulation = (user_need.regulation or "").lower()
        return any(r in regulation for r in self.regulations)

    def investigate(self, user_need: UserNeed, context: ExpertContext) -> ExpertReport:
        report = ExpertReport(
            regulation="hipaa",
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
                    source_id="hipaa",
                    confidence=0.6,
                    excerpt=guidance["claim"],
                )
            )

        # 2. If the system appears to handle PHI in AI/ML, add a targeted finding.
        if self._handles_phi(user_need):
            report.findings.append(
                ExpertFinding(
                    claim="The described AI/ML system appears to process PHI; HIPAA Privacy and Security Rule obligations apply, and a BAA is likely required for any vendor handling PHI.",
                    basis="45 CFR §§ 164.502, 164.504(e)",
                    source_id="hipaa",
                    confidence=0.6,
                )
            )

        # 3. Scoped corpus retrieval (no corpus exists; kept for API consistency).
        if context.rag is not None:
            hits = context.rag.query(
                self._build_query(user_need),
                top_k=4,
                source_filter=["hipaa"],
            )
            for h in hits:
                report.findings.append(
                    ExpertFinding(
                        claim=h.get("text", "")[:240],
                        basis=h.get("article_id") or h.get("section_path", "HIPAA"),
                        source_id="hipaa",
                        source_url=h.get("source_url"),
                        confidence=float(h.get("score", 0.0)),
                        excerpt=h.get("text", "")[:400],
                    )
                )

        if not report.findings:
            report.open_questions.append(
                "Could you tell me which HIPAA topic you need (e.g. Privacy Rule, Security Rule, BAAs, minimum necessary, de-identification, breach notification)?"
            )
        else:
            report.confidence = sum(f.confidence for f in report.findings) / len(report.findings)
            if not self._covered_entity_described(user_need):
                report.open_questions.append(
                    "Are you a covered entity (health plan, healthcare provider, clearinghouse) or a business associate handling PHI?"
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
        # Longer/more-specific keywords first to avoid short-string false matches.
        for keyword in sorted(self._INTENT_GUIDANCE, key=len, reverse=True):
            if keyword in lowered:
                return self._INTENT_GUIDANCE[keyword]
        return None

    def _handles_phi(self, user_need: UserNeed) -> bool:
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
        phi_signals = {
            "patient",
            "medical record",
            "health data",
            "clinical",
            "diagnosis",
            "ehr",
            "electronic health record",
            "phi",
        }
        return any(s in lowered for s in phi_signals)

    def _covered_entity_described(self, user_need: UserNeed) -> bool:
        lowered = " ".join(
            p.lower() for p in (user_need.intent, user_need.system_type, user_need.purpose) if p
        )
        return any(s in lowered for s in self._COVERED_ENTITY_SIGNALS)
