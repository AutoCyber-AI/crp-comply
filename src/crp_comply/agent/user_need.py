# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""User-need model for the Phase-7 compliance agent.

The goal is to represent *what the user wants* — not just *what they asked*.
Beyond intent and entities, we capture the desired response shape, audience,
urgency, and any explicit satisfaction criteria so the planner and final
formatter can tailor the answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class UserNeed:
    """Structured representation of the user's request."""

    intent: str = "unknown"
    intent_confidence: float = 0.0
    regulation: str | None = None
    jurisdiction: str | None = None
    system_type: str | None = None
    data_type: str | None = None
    purpose: str | None = None
    task_type: str | None = None
    depth: str = "standard"  # brief | standard | thorough
    format: str = "prose"  # summary | checklist | report | citation_list | decision_tree | prose
    audience: str = "unknown"  # executive | legal | engineer | auditor | unknown
    urgency: str = "normal"  # low | normal | high
    freshness_required: bool = False
    satisfaction_criteria: list[str] = field(default_factory=list)
    raw_slots: dict[str, Any] = field(default_factory=dict)

    def is_confident(self, threshold: float = 0.65) -> bool:
        """True when intent confidence is above the actionable threshold."""
        return self.intent_confidence >= threshold

    def needs_clarification(self) -> bool:
        """True when we are missing information critical to a tailored answer."""
        if not self.is_confident():
            return True
        # Unknown regulation for a regulation-specific intent usually needs a
        # targeted question.
        if self.intent in {"define", "cite", "compare", "scope"} and not self.regulation:
            return True
        return False

    def to_event_payload(self) -> dict[str, Any]:
        """Flatten to JSON-safe primitives for SSE."""
        return {
            "intent": self.intent,
            "intent_confidence": self.intent_confidence,
            "regulation": self.regulation,
            "depth": self.depth,
            "format": self.format,
            "audience": self.audience,
            "urgency": self.urgency,
            "freshness_required": self.freshness_required,
            "satisfaction_criteria": list(self.satisfaction_criteria),
        }
