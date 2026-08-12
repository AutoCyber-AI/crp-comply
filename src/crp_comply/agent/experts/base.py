# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Base classes for regulation-specific expert subagents.

Each expert owns deep, sequential reasoning for one regulation or standard.
They are invoked by the main CRPv5 loop as fabric capabilities, but internally
run their own short positioned loops over a scoped tool set. All findings are
returned as structured :class:`ExpertReport` objects so the main loop can fold
 them into the shared CognitiveStateObject.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..user_need import UserNeed


class _RagBackend(Protocol):
    def query(
        self,
        query_text: str,
        *,
        top_k: int = 5,
        source_filter: list[str] | None = None,
    ) -> list[dict[str, Any]]: ...


class _WebBackend(Protocol):
    def research_intelligent(
        self,
        goal: str,
        *,
        intent: str = "general",
        freshness: str = "any",
        max_results_per_query: int = 8,
        **kwargs: Any,
    ) -> dict[str, Any]: ...


@dataclass
class ExpertContext:
    """Runtime dependencies handed to an expert."""

    rag: _RagBackend | None = None
    web: _WebBackend | None = None
    user_profile: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExpertFinding:
    """One structured finding from an expert investigation."""

    claim: str
    basis: str  # e.g. "Article 6(1) EU AI Act" or "ISO 42001 Annex A.5"
    source_id: str
    source_url: str | None = None
    confidence: float = 0.0
    excerpt: str = ""


@dataclass
class ExpertReport:
    """Structured output returned by a regulation expert."""

    regulation: str
    intent: str = "unknown"
    findings: list[ExpertFinding] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    open_questions: list[str] = field(default_factory=list)
    recommended_depth: str = "standard"
    raw_context: str = ""

    def to_tool_payload(self) -> dict[str, Any]:
        """Flatten to a JSON-safe dict for the LLM tool result."""
        return {
            "regulation": self.regulation,
            "intent": self.intent,
            "confidence": self.confidence,
            "findings": [
                {
                    "claim": f.claim,
                    "basis": f.basis,
                    "source_id": f.source_id,
                    "source_url": f.source_url,
                    "confidence": f.confidence,
                    "excerpt": f.excerpt[:400],
                }
                for f in self.findings
            ],
            "citations": list(self.citations),
            "open_questions": list(self.open_questions),
            "recommended_depth": self.recommended_depth,
        }


class RegulationExpert(ABC):
    """ABC for a regulation-specific expert subagent."""

    name: str = ""
    regulations: tuple[str, ...] = ()

    @abstractmethod
    def can_handle(self, user_need: UserNeed) -> bool:
        """True when this expert should take the user need."""

    @abstractmethod
    def investigate(self, user_need: UserNeed, context: ExpertContext) -> ExpertReport:
        """Run the expert's short loop and return findings."""
