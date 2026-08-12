# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""NIST AI RMF regulation expert.

Retrieves clauses from the NIST AI RMF Core and Generative AI Profile corpora,
with deterministic function-to-control mapping (Govern, Map, Measure, Manage).
"""

from __future__ import annotations

from .base import ExpertContext, ExpertFinding, ExpertReport, RegulationExpert
from ..user_need import UserNeed


class NistAiRmfExpert(RegulationExpert):
    """Expert subagent for NIST AI Risk Management Framework (AI RMF 1.0)."""

    name = "nist_ai_rmf_expert"
    regulations = (
        "nist ai rmf",
        "nist_ai_rmf",
        "nist ai risk management framework",
        "ai rmf",
    )

    # Intent → AI RMF function and representative controls / sections.
    _INTENT_FUNCTIONS = {
        "govern": (
            "GOVERN",
            [
                "GOV-1",
                "GOV-2",
                "GOV-3",
                "GOV-4",
                "GOV-5",
                "GOV-6",
                "GOV-7",
                "GOV-8",
                "GOV-9",
                "GOV-10",
            ],
        ),
        "governance": (
            "GOVERN",
            [
                "GOV-1",
                "GOV-2",
                "GOV-3",
                "GOV-4",
                "GOV-5",
                "GOV-6",
                "GOV-7",
                "GOV-8",
                "GOV-9",
                "GOV-10",
            ],
        ),
        "map": ("MAP", ["MAP-1", "MAP-2", "MAP-3", "MAP-4", "MAP-5"]),
        "identify": ("MAP", ["MAP-1", "MAP-2", "MAP-3", "MAP-4", "MAP-5"]),
        "context": ("MAP", ["MAP-1", "MAP-2", "MAP-3"]),
        "measure": ("MEASURE", ["MEAS-1", "MEAS-2", "MEAS-3", "MEAS-4", "MEAS-5"]),
        "evaluate": ("MEASURE", ["MEAS-1", "MEAS-2", "MEAS-3", "MEAS-4", "MEAS-5"]),
        "manage": ("MANAGE", ["MGMT-1", "MGMT-2", "MGMT-3", "MGMT-4"]),
        "mitigate": ("MANAGE", ["MGMT-1", "MGMT-2", "MGMT-3", "MGMT-4"]),
        "risk tolerance": ("GOVERN", ["GOV-1", "GOV-2"]),
        "transparency": ("GOVERN", ["GOV-5", "GOV-6"]),
        "third party": ("GOVERN", ["GOV-4"]),
        "supply chain": ("GOVERN", ["GOV-4"]),
        "incident": ("MANAGE", ["MGMT-4"]),
        "genai": ("Generative AI Profile", ["GOV-GENAI", "MAP-GENAI", "MEAS-GENAI", "MGMT-GENAI"]),
        "generative ai": (
            "Generative AI Profile",
            ["GOV-GENAI", "MAP-GENAI", "MEAS-GENAI", "MGMT-GENAI"],
        ),
    }

    def can_handle(self, user_need: UserNeed) -> bool:
        regulation = (user_need.regulation or "").lower()
        return any(r in regulation for r in self.regulations)

    def investigate(self, user_need: UserNeed, context: ExpertContext) -> ExpertReport:
        report = ExpertReport(
            regulation="nist_ai_rmf",
            intent=user_need.intent,
            recommended_depth=user_need.depth,
        )

        query = self._build_query(user_need)
        function_name, controls = self._function_hints(user_need)

        # Add a deterministic finding that names the relevant AI RMF function.
        if function_name:
            report.findings.append(
                ExpertFinding(
                    claim=f"The question maps to the NIST AI RMF '{function_name}' function; relevant controls include {', '.join(controls[:5])}.",
                    basis=controls[0] if controls else "NIST AI RMF Core",
                    source_id="nist_ai_rmf_core",
                    confidence=0.8,
                )
            )

        if context.rag is not None:
            hits = context.rag.query(
                query,
                top_k=8,
                source_filter=["nist_ai_rmf_core", "nist_ai_rmf_genai"],
            )
            # Boost control-hint matches in the ranking we return.
            control_set = set(c.lower() for c in controls)
            hits = sorted(
                hits,
                key=lambda h: (
                    1 if any(c in (h.get("article_id") or "").lower() for c in control_set) else 0,
                    float(h.get("score", 0.0)),
                ),
                reverse=True,
            )
            for h in hits:
                report.findings.append(
                    ExpertFinding(
                        claim=h.get("text", "")[:240],
                        basis=h.get("article_id") or h.get("section_path", "NIST AI RMF"),
                        source_id=h.get("source_id", "nist_ai_rmf_core"),
                        source_url=h.get("source_url"),
                        confidence=float(h.get("score", 0.0)),
                        excerpt=h.get("text", "")[:400],
                    )
                )
            report.citations.extend(
                [
                    {
                        "source_id": h.get("source_id", "nist_ai_rmf_core"),
                        "clause": h.get("article_id"),
                        "url": h.get("source_url"),
                        "excerpt": (h.get("text") or "")[:240],
                    }
                    for h in hits
                ]
            )

        if not report.findings:
            report.open_questions.append(
                "Could you tell me which NIST AI RMF function you are asking about (Govern, Map, Measure, Manage) or whether the system is a generative AI system?"
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

    def _function_hints(self, user_need: UserNeed) -> tuple[str, list[str]]:
        lowered = " ".join(
            p.lower() for p in (user_need.intent, user_need.task_type, user_need.purpose) if p
        )
        for keyword, (function, controls) in self._INTENT_FUNCTIONS.items():
            if keyword in lowered:
                return function, controls
        return "", []
