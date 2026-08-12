# Copyright © 2025 Constantinos Vidiniotis. All rights reserved.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Session-scoped conversation ledger.

Converts aged conversational turns into structured facts so that raw history
can be dropped while meaning is preserved across full windows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from crp_comply.agent.crp_integration import extract_facts_from_text


@dataclass
class ConversationLedger:
    """Summarize and carry forward old conversational turns as facts."""

    session_id: str = ""
    keep_recent: int = 4
    max_facts: int = 200
    _turns: list[dict[str, str]] = field(default_factory=list)
    _facts: list[dict[str, Any]] = field(default_factory=list)

    def add_turn(self, role: str, content: str) -> None:
        """Record a raw conversational turn."""
        if content and content.strip():
            self._turns.append({"role": role, "content": content.strip()})

    def summarize_old_turns(self) -> list[dict[str, Any]]:
        """Extract facts from turns older than ``keep_recent`` and drop raw text."""
        if len(self._turns) <= self.keep_recent:
            return []

        old = self._turns[: -self.keep_recent]
        self._turns = self._turns[-self.keep_recent :]
        new_facts: list[dict[str, Any]] = []

        for turn in old:
            extracted = extract_facts_from_text(
                turn["content"],
                source_window_id=f"conversation-{self.session_id}",
                category=f"conversation.{turn['role']}_fact",
            )
            for fact in extracted.facts:
                text = getattr(fact, "text", "") or str(fact)
                if not text.strip():
                    continue
                new_facts.append(
                    {
                        "role": turn["role"],
                        "category": getattr(fact, "category", "")
                        or f"conversation.{turn['role']}_fact",
                        "text": text.strip(),
                        "confidence": float(getattr(fact, "confidence", 0.5) or 0.5),
                    }
                )

        self._facts.extend(new_facts)
        # Bound memory
        if len(self._facts) > self.max_facts:
            self._facts = self._facts[-self.max_facts :]
        return new_facts

    def pack_envelope(self, *, max_facts: int = 50) -> str:
        """Render stored facts as a system-message digest."""
        if not self._facts:
            return ""

        lines = ["[CONVERSATION FACTS — prior turns summarized]", ""]
        # Keep highest-confidence facts first
        sorted_facts = sorted(
            self._facts,
            key=lambda f: f.get("confidence", 0.5),
            reverse=True,
        )
        for fact in sorted_facts[:max_facts]:
            prefix = {"user": "User stated", "assistant": "Assistant established"}.get(
                fact.get("role"), "Established"
            )
            lines.append(f"- {prefix}: {fact['text']}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict."""
        return {
            "session_id": self.session_id,
            "keep_recent": self.keep_recent,
            "max_facts": self.max_facts,
            "turns": list(self._turns),
            "facts": list(self._facts),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConversationLedger":
        """Restore from a JSON-safe dict."""
        ledger = cls(
            session_id=data.get("session_id", ""),
            keep_recent=int(data.get("keep_recent", 4)),
            max_facts=int(data.get("max_facts", 200)),
        )
        ledger._turns = list(data.get("turns") or [])
        ledger._facts = list(data.get("facts") or [])
        return ledger
