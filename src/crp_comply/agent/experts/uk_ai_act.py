# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""UK AI Act (proposed) regulation expert.

Deterministic guidance based on UK risk tiers and intent mapping. No corpus
file exists, so findings are not corpus-backed and confidence is held lower.
"""

from __future__ import annotations

from .base import ExpertContext, ExpertFinding, ExpertReport, RegulationExpert
from ..user_need import UserNeed


class UkAiActExpert(RegulationExpert):
    """Expert subagent for the proposed UK AI Act / UK AI regulation framework."""

    name = "uk_ai_act_expert"
    regulations = (
        "uk ai act",
        "uk_ai_act",
        "uk ai regulation",
        "uk ai bill",
        "uk artificial intelligence",
    )

    # UK risk-tier classification signals (as signalled in UK policy papers).
    _UNACCEPTABLE_SIGNALS = {
        "social scoring",
        "predictive policing",
        "emotion recognition in workplace",
        "emotion recognition in school",
        "biometric categorisation",
        "manipulative",
        "exploit vulnerability",
        "subliminal",
    }
    _HIGH_RISK_SIGNALS = {
        "healthcare",
        "medical",
        "recruitment",
        "hiring",
        "cv screening",
        "education",
        "justice",
        "law enforcement",
        "critical infrastructure",
        "finance",
        "insurance",
        "transport safety",
    }
    _LIMITED_RISK_SIGNALS = {
        "chatbot",
        "emotion recognition",
        "deepfake",
        "synthetic media",
        "ai generated content",
    }

    # Intent → representative UK AI Act provision or policy theme.
    _INTENT_GUIDANCE = {
        "risk tier": {
            "basis": "UK AI Act risk-tier framework",
            "claim": "The UK framework assigns AI systems to risk tiers; obligations escalate from low to limited, high and unacceptable risk.",
        },
        "high risk": {
            "basis": "UK high-risk AI obligations",
            "claim": "High-risk AI systems are likely to require risk assessments, transparency, human oversight, and registration before deployment.",
        },
        "transparency": {
            "basis": "UK AI transparency requirements",
            "claim": "Providers and deployers of AI systems must ensure appropriate transparency, including clear communication to users when they interact with AI.",
        },
        "human oversight": {
            "basis": "UK AI human oversight",
            "claim": "High-risk and certain limited-risk AI deployments are expected to maintain meaningful human oversight.",
        },
        "accountability": {
            "basis": "UK AI accountability",
            "claim": "The UK regime places accountability on both developers and deployers, with sector regulators taking the lead.",
        },
        "regulator": {
            "basis": "UK sector regulator approach",
            "claim": "The UK approach relies on existing sector regulators (e.g. ICO, FCA, MHRA, Ofcom) issuing AI guidance within their remits.",
        },
    }

    def can_handle(self, user_need: UserNeed) -> bool:
        regulation = (user_need.regulation or "").lower()
        return any(r in regulation for r in self.regulations)

    def investigate(self, user_need: UserNeed, context: ExpertContext) -> ExpertReport:
        report = ExpertReport(
            regulation="uk_ai_act",
            intent=user_need.intent,
            recommended_depth=user_need.depth,
        )

        # 1. Deterministic risk-tier classification if the user described a system.
        risk_tier = self._classify_risk_tier(user_need)
        if risk_tier:
            report.findings.append(
                ExpertFinding(
                    claim=f"Based on the description, the system appears to fall into the '{risk_tier}' risk tier under the UK AI framework.",
                    basis="UK AI Act risk-tier framework",
                    source_id="uk_ai_act",
                    confidence=0.6,
                )
            )

        # 2. Intent-based guidance.
        guidance = self._match_guidance(user_need)
        if guidance:
            report.findings.append(
                ExpertFinding(
                    claim=guidance["claim"],
                    basis=guidance["basis"],
                    source_id="uk_ai_act",
                    confidence=0.6,
                    excerpt=guidance["claim"],
                )
            )

        # 3. Scoped corpus retrieval is a no-op because no corpus exists, but we
        #    keep the call for API consistency.
        if context.rag is not None:
            hits = context.rag.query(
                self._build_query(user_need),
                top_k=4,
                source_filter=["uk_ai_act"],
            )
            for h in hits:
                report.findings.append(
                    ExpertFinding(
                        claim=h.get("text", "")[:240],
                        basis=h.get("article_id") or h.get("section_path", "UK AI Act"),
                        source_id="uk_ai_act",
                        source_url=h.get("source_url"),
                        confidence=float(h.get("score", 0.0)),
                        excerpt=h.get("text", "")[:400],
                    )
                )

        if not report.findings:
            report.open_questions.append(
                "Could you tell me the AI system's purpose or sector (e.g. healthcare recruitment, chatbot, finance), or which UK AI Act topic you need?"
            )
        else:
            report.confidence = sum(f.confidence for f in report.findings) / len(report.findings)
            report.open_questions.append(
                "Which sector or regulator applies to this AI system (e.g. ICO for data protection, FCA for finance, MHRA for medical devices)?"
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

    def _classify_risk_tier(self, user_need: UserNeed) -> str:
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
        if any(s in lowered for s in self._UNACCEPTABLE_SIGNALS):
            return "unacceptable"
        if any(s in lowered for s in self._HIGH_RISK_SIGNALS):
            return "high"
        if any(s in lowered for s in self._LIMITED_RISK_SIGNALS):
            return "limited"
        return ""
