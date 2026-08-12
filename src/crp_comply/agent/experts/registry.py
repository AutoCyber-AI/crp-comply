# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Registry of regulation experts."""

from __future__ import annotations

from typing import Any

from ..user_need import UserNeed
from .base import ExpertContext, ExpertReport, RegulationExpert
from .dora import DoraExpert
from .eu_ai_act import EuAiActExpert
from .gdpr import GdprExpert
from .hipaa import HipaaExpert
from .iso42001 import Iso42001Expert
from .nis2 import Nis2Expert
from .nist_ai_rmf import NistAiRmfExpert
from .soc2 import Soc2Expert
from .uk_ai_act import UkAiActExpert


class ExpertRegistry:
    """Holds and dispatches to regulation-specific expert subagents."""

    def __init__(self, experts: list[RegulationExpert] | None = None) -> None:
        self._experts: list[RegulationExpert] = experts or [
            DoraExpert(),
            EuAiActExpert(),
            GdprExpert(),
            HipaaExpert(),
            Iso42001Expert(),
            Nis2Expert(),
            NistAiRmfExpert(),
            Soc2Expert(),
            UkAiActExpert(),
        ]

    def register(self, expert: RegulationExpert) -> None:
        self._experts.append(expert)

    def select(self, user_need: UserNeed) -> RegulationExpert | None:
        """Return the best expert for the need, or None if no match."""
        for expert in self._experts:
            if expert.can_handle(user_need):
                return expert
        return None

    def consult(
        self,
        user_need: UserNeed,
        context: ExpertContext | None = None,
    ) -> ExpertReport | None:
        """Run the selected expert and return its report."""
        expert = self.select(user_need)
        if expert is None:
            return None
        return expert.investigate(user_need, context or ExpertContext())

    def list_names(self) -> list[str]:
        return [e.name for e in self._experts]

    def to_tool_payload(self, report: ExpertReport | None) -> dict[str, Any]:
        """Convert a report to a dict suitable for a tool result."""
        if report is None:
            return {"handled": False, "reason": "no matching regulation expert"}
        return {"handled": True, **report.to_tool_payload()}
