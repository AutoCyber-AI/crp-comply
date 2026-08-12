# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Working memory that accumulates facts across research steps (Round 10).

The ``EvidenceBoard`` is intentionally lightweight: it stores short,
citation-tagged fact strings produced by each step so that later phases
(ANALYSIS, SYNTHESIS, CITATION, REVIEW) can prime the LLM with the
evidence already gathered instead of asking it to re-derive everything
from the full observation text.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Fact:
    """One extracted fact with provenance."""

    text: str
    source_id: str = ""  # chunk_id, url, fact_id
    citation: str = ""  # rendered marker, e.g. [chunk_id]
    phase: str = ""
    confidence: float = 1.0


@dataclass
class EvidenceBoard:
    """Accumulates facts across research steps and renders a context block."""

    facts: list[Fact] = field(default_factory=list)

    def add(
        self,
        text: str,
        *,
        source_id: str = "",
        citation: str = "",
        phase: str = "",
        confidence: float = 1.0,
    ) -> None:
        """Add a fact if it is non-empty and not a near-duplicate."""
        text = (text or "").strip()
        if not text:
            return
        normalised = text.lower()
        for existing in self.facts:
            if existing.text.lower() == normalised:
                return
        self.facts.append(
            Fact(
                text=text,
                source_id=source_id,
                citation=citation,
                phase=phase,
                confidence=float(confidence),
            )
        )

    def add_from_citations(
        self,
        step_id: str,
        phase: str,
        observation: str,
        citations: list[dict[str, Any]],
    ) -> None:
        """Best-effort extraction of fact statements from an observation.

        We split on sentence boundaries and keep short assertion-like
        sentences, tagging them with the first available citation id.
        """
        if not observation:
            return
        default_source = ""
        default_citation = ""
        for c in citations or []:
            for key in ("chunk_id", "fact_id", "id", "citation_id", "source_id", "url"):
                value = c.get(key)
                if value:
                    default_source = str(value)
                    default_citation = f"[{default_source}]"
                    break
            if default_source:
                break
        for raw in observation.split("."):
            sentence = raw.strip()
            if not sentence:
                continue
            # Keep sentences that look factual (contain a verb hint).
            if not any(
                hint in sentence.lower()
                for hint in ("is", "are", "must", "shall", "requires", "prohibits", "defines")
            ):
                continue
            # Skip very short fragments and already-cited parentheticals.
            if len(sentence) < 20 or sentence.startswith("["):
                continue
            self.add(
                text=sentence,
                source_id=default_source,
                citation=default_citation,
                phase=phase,
            )

    def by_phase(self, phase: str) -> list[Fact]:
        return [f for f in self.facts if f.phase == phase]

    def render(self, max_facts: int = 20) -> str:
        """Render the board as Markdown context for the next LLM prompt."""
        if not self.facts:
            return ""
        lines = ["## Evidence gathered so far"]
        for fact in self.facts[:max_facts]:
            cite = f" {fact.citation}" if fact.citation else ""
            lines.append(f"- {fact.text}{cite}")
        if len(self.facts) > max_facts:
            lines.append(f"- ... and {len(self.facts) - max_facts} more facts")
        return "\n".join(lines)

    def to_dict(self) -> list[dict[str, Any]]:
        return [
            {
                "text": f.text,
                "source_id": f.source_id,
                "citation": f.citation,
                "phase": f.phase,
                "confidence": f.confidence,
            }
            for f in self.facts
        ]

    @classmethod
    def from_dict(cls, data: list[dict[str, Any]]) -> "EvidenceBoard":
        board = cls()
        for item in data:
            board.add(
                text=item.get("text", ""),
                source_id=item.get("source_id", ""),
                citation=item.get("citation", ""),
                phase=item.get("phase", ""),
                confidence=item.get("confidence", 1.0),
            )
        return board


__all__ = ["EvidenceBoard", "Fact"]
