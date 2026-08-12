# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""EU AI Act regulation expert.

Combines deterministic Article 6 risk classification with scoped corpus
retrieval and optional fresh-web guidance lookup. Returns structured findings
so the main loop never has to guess about EU AI Act obligations.
"""

from __future__ import annotations

from crp.security import RiskClassifier

from ..user_need import UserNeed
from .base import ExpertContext, ExpertFinding, ExpertReport, RegulationExpert


class EuAiActExpert(RegulationExpert):
    """Expert subagent for Regulation (EU) 2024/1689 (EU AI Act)."""

    name = "eu_ai_act_expert"
    regulations = ("eu ai act", "eu_ai_act", "ai act")

    # Simple keyword-based signal mapping for the deterministic classifier.
    _RIGHTS_SIGNALS = {
        "hiring",
        "recruitment",
        "scoring",
        "biometric",
        "emotion",
        "social",
        "policing",
        "justice",
        "asylum",
        "migration",
        "vulnerable",
        "children",
    }
    _SAFETY_SIGNALS = {
        "medical",
        "vehicle",
        "aviation",
        "critical infrastructure",
        "safety component",
    }
    _AUTOMATED_SIGNALS = {"automated", "auto", "scores", "ranking", "decision"}
    _PROFILE_SIGNALS = {"profile", "behavioural", "predict", "target"}

    def can_handle(self, user_need: UserNeed) -> bool:
        regulation = (user_need.regulation or "").lower()
        return any(r in regulation for r in self.regulations)

    def investigate(self, user_need: UserNeed, context: ExpertContext) -> ExpertReport:
        system_type = (user_need.system_type or "").lower()
        purpose = (user_need.purpose or "").lower()
        data_type = (user_need.data_type or "").lower()
        combined = f"{system_type} {purpose} {data_type}"

        report = ExpertReport(
            regulation="eu_ai_act",
            intent=user_need.intent,
            recommended_depth=user_need.depth,
        )

        # 1. Deterministic risk classification when the user_need describes a system.
        if system_type or purpose:
            classifier = RiskClassifier()
            assessment = classifier.assess(
                intended_purpose=user_need.purpose or user_need.system_type or "AI system",
                processes_personal_data=bool(
                    user_need.data_type or "personal" in combined or "cv" in combined
                ),
                makes_automated_decisions=any(s in combined for s in self._AUTOMATED_SIGNALS),
                affects_fundamental_rights=any(s in combined for s in self._RIGHTS_SIGNALS),
                safety_critical=any(s in combined for s in self._SAFETY_SIGNALS),
                profiles_individuals=any(s in combined for s in self._PROFILE_SIGNALS),
            )
            risk_level = getattr(assessment.risk_level, "value", str(assessment.risk_level))
            report.findings.append(
                ExpertFinding(
                    claim=f"The described system is classified as {risk_level} risk under Article 6.",
                    basis="Article 6 EU AI Act",
                    source_id="eu_ai_act",
                    confidence=0.9,
                )
            )
            report.confidence = 0.85

        # 2. Scoped corpus retrieval for the user's specific question.
        if context.rag is not None:
            query = self._build_query(user_need)
            hits = context.rag.query(query, top_k=6, source_filter=["eu_ai_act"])
            for h in hits:
                report.findings.append(
                    ExpertFinding(
                        claim=h.get("text", "")[:240],
                        basis=h.get("article_id") or h.get("source_id", "eu_ai_act"),
                        source_id="eu_ai_act",
                        source_url=h.get("source_url"),
                        confidence=float(h.get("score", 0.0)),
                        excerpt=h.get("text", "")[:400],
                    )
                )
            report.citations.extend(
                [
                    {
                        "source_id": "eu_ai_act",
                        "article_id": h.get("article_id"),
                        "url": h.get("source_url"),
                        "excerpt": (h.get("text") or "")[:240],
                    }
                    for h in hits
                ]
            )

        # 3. Optional fresh guidance lookup for high-urgency or recent-events queries.
        if user_need.freshness_required and context.web is not None:
            web = context.web.research_intelligent(
                goal=user_need.intent + " " + (user_need.regulation or "EU AI Act"),
                intent="guidance",
                freshness="month",
                max_results_per_query=4,
            )
            for r in web.get("results") or web.get("hits") or []:
                if not isinstance(r, dict):
                    continue
                report.findings.append(
                    ExpertFinding(
                        claim=r.get("title", "")[:200],
                        basis="recent guidance",
                        source_id="web",
                        source_url=r.get("url"),
                        confidence=0.6,
                        excerpt=(r.get("snippet") or "")[:400],
                    )
                )

        if not report.findings:
            report.open_questions.append(
                "Could you specify the AI system purpose or the EU AI Act article you are asking about?"
            )
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
