# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""CRPv4 memory substrate adapter for the compliance agent (Round 4).

This module bridges the agent's session/dialogue state to CRPv4 tiered memory
primitives:

* ``MultiHorizonContext`` — ephemeral input + session context turns.
* ``CognitiveStateObject`` — the agent's current understanding (slots, intent,
  open questions, established facts, decisions).
* ``WindowDAG`` — compressed long-horizon recall across sessions.

The adapter persists to ``{data_dir}/context/{user_id}/{session_id}.json``.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from crp_comply.agent.cso_store import CSOStore, get_cso_store

logger = logging.getLogger(__name__)


@dataclass
class MemoryTiers:
    """Snapshot of the three memory tiers."""

    input_turn: dict[str, Any] | None = None
    context: dict[str, Any] = field(default_factory=dict)
    profile: dict[str, Any] = field(default_factory=dict)


class CompliantMemory:
    """Own one session's CRPv4 memory substrate.

    The adapter is intentionally defensive: if CRPv4 primitives raise during
    load/save/update, it falls back to a simple JSON dict so the agent can
    continue operating.
    """

    def __init__(
        self,
        user_id: str,
        session_id: str,
        *,
        data_dir: Path | str | None = None,
    ) -> None:
        self.user_id = user_id
        self.session_id = session_id
        self.data_dir = Path(data_dir or os.environ.get("CRP_COMPLY_DATA_DIR", "data"))
        self._store: CSOStore = get_cso_store(data_dir=self.data_dir)
        self._mhc: Any = None
        self._cso: Any = None
        self._window_dag: Any = None
        self._profile: dict[str, Any] = {}
        self._turn_counter: int = 0
        self._continuation_state: dict[str, Any] | None = None
        self._load()

    # ── Persistence ───────────────────────────────────────────────────

    def _load(self) -> None:
        raw = self._store.load(self.user_id, self.session_id)
        if raw is None:
            self._init_blank()
            return
        try:
            self._from_dict(raw)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to load memory for %s/%s; starting blank",
                self.user_id,
                self.session_id,
                exc_info=True,
            )
            self._init_blank()

    def save(self) -> None:
        """Persist the memory substrate."""
        try:
            self._store.save(self.user_id, self.session_id, self._to_dict())
        except Exception:  # noqa: BLE001
            logger.warning(
                "Failed to save memory for %s/%s", self.user_id, self.session_id, exc_info=True
            )

    # ── CRPv4 initialisation ──────────────────────────────────────────

    def _init_blank(self) -> None:
        try:
            from crp.state import MultiHorizonContext, CognitiveStateObject
            from crp.core.window import WindowDAG

            self._mhc = MultiHorizonContext()
            self._cso = CognitiveStateObject()
            self._window_dag = WindowDAG()
        except Exception:  # noqa: BLE001
            logger.warning(
                "CRPv4 memory primitives unavailable; using fallback dicts", exc_info=True
            )
            self._mhc = None
            self._cso = None
            self._window_dag = None
        self._profile = {}
        self._turn_counter = 0
        self._continuation_state = None

    # ── Serialisation ─────────────────────────────────────────────────

    def _to_dict(self) -> dict[str, Any]:
        mhc_dict: dict[str, Any] = {}
        cso_dict: dict[str, Any] = {}
        dag_dict: dict[str, Any] = {"nodes": [], "edges": []}
        if self._mhc is not None and hasattr(self._mhc, "turn_log"):
            try:
                mhc_dict = {"turn_log": [self._turn_entry_to_dict(t) for t in self._mhc.turn_log]}
            except Exception:  # noqa: BLE001
                pass
        if self._cso is not None and hasattr(self._cso, "to_dict"):
            try:
                cso_dict = self._cso.to_dict()
            except Exception:  # noqa: BLE001
                pass
        if self._window_dag is not None:
            try:
                dag_dict = {
                    "nodes": [getattr(n, "window_id", str(n)) for n in self._window_dag.nodes()],
                    "edges": [
                        [getattr(e, "source_id", ""), getattr(e, "target_id", "")]
                        for e in self._window_dag.edges()
                    ],
                }
            except Exception:  # noqa: BLE001
                pass
        return {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "version": 1,
            "updated_at": time.time(),
            "profile": self._profile,
            "mhc": mhc_dict,
            "cso": cso_dict,
            "window_dag": dag_dict,
            "turn_counter": self._turn_counter,
            "continuation_state": self._continuation_state,
        }

    def _from_dict(self, raw: dict[str, Any]) -> None:
        from crp.state import MultiHorizonContext, CognitiveStateObject, TurnEntry
        from crp.core.window import WindowDAG

        self._profile = dict(raw.get("profile") or {})
        self._turn_counter = int(raw.get("turn_counter", 0))
        self._continuation_state = raw.get("continuation_state")

        # MultiHorizonContext
        try:
            turns = []
            for t in raw.get("mhc", {}).get("turn_log", []):
                turns.append(
                    TurnEntry(
                        turn_id=int(t["turn_id"]),
                        role=str(t["role"]),
                        content=str(t["content"]),
                        topic_tags=list(t.get("topic_tags") or []),
                        referenced_turns=list(t.get("referenced_turns") or []),
                    )
                )
            self._mhc = MultiHorizonContext(turn_log=turns)
        except Exception:  # noqa: BLE001
            self._mhc = MultiHorizonContext()

        # CognitiveStateObject
        try:
            self._cso = CognitiveStateObject.from_dict(raw.get("cso", {}))
        except Exception:  # noqa: BLE001
            self._cso = CognitiveStateObject()

        # WindowDAG
        try:
            self._window_dag = WindowDAG()
            from crp.core.window import WindowNode, WindowEdge

            for node_id in raw.get("window_dag", {}).get("nodes", []):
                self._window_dag.add_node(WindowNode(window_id=str(node_id)))
            for edge in raw.get("window_dag", {}).get("edges", []):
                if isinstance(edge, (list, tuple)) and len(edge) == 2:
                    self._window_dag.add_edge(
                        WindowEdge(source_id=str(edge[0]), target_id=str(edge[1]))
                    )
        except Exception:  # noqa: BLE001
            self._window_dag = WindowDAG()

    @staticmethod
    def _turn_entry_to_dict(t: Any) -> dict[str, Any]:
        return {
            "turn_id": getattr(t, "turn_id", 0),
            "role": getattr(t, "role", ""),
            "content": getattr(t, "content", ""),
            "topic_tags": list(getattr(t, "topic_tags", []) or []),
            "referenced_turns": list(getattr(t, "referenced_turns", []) or []),
        }

    # ── Public accessors ──────────────────────────────────────────────

    @property
    def mhc(self) -> Any:
        return self._mhc

    @property
    def cso(self) -> Any:
        return self._cso

    @property
    def window_dag(self) -> Any:
        return self._window_dag

    @property
    def profile(self) -> dict[str, Any]:
        return dict(self._profile)

    def set_profile(self, profile: dict[str, Any] | None) -> None:
        self._profile = dict(profile or {})

    # ── Turn / context operations ─────────────────────────────────────

    def add_turn(
        self,
        role: str,
        content: str,
        *,
        topic_tags: list[str] | None = None,
        referenced_turns: list[int] | None = None,
    ) -> int:
        """Record a turn in the MultiHorizonContext. Returns the turn id."""
        self._turn_counter += 1
        turn_id = self._turn_counter
        tags = topic_tags or []
        if self._mhc is not None and hasattr(self._mhc, "add_turn"):
            try:
                entry = self._mhc.add_turn(role, content, topic_tags=tags)
                # Record cross-turn references if provided.
                if referenced_turns and hasattr(entry, "referenced_turns"):
                    entry.referenced_turns = list(referenced_turns)
            except Exception:  # noqa: BLE001
                logger.debug("add_turn failed", exc_info=True)
        # Also add a node to the WindowDAG for long-horizon recall.
        if self._window_dag is not None:
            try:
                from crp.core.window import WindowNode

                window_id = f"{self.session_id}:{turn_id}"
                self._window_dag.add_node(WindowNode(window_id=window_id))
                if turn_id > 1:
                    from crp.core.window import WindowEdge

                    self._window_dag.add_edge(
                        WindowEdge(
                            source_id=f"{self.session_id}:{turn_id - 1}",
                            target_id=window_id,
                        )
                    )
            except Exception:  # noqa: BLE001
                pass
        return turn_id

    def recent_turns(self, n: int = 10) -> list[dict[str, Any]]:
        """Return the last *n* turns as plain dicts."""
        if self._mhc is None or not hasattr(self._mhc, "get_recent_turns"):
            return []
        try:
            return [self._turn_entry_to_dict(t) for t in self._mhc.get_recent_turns(n)]
        except Exception:  # noqa: BLE001
            return []

    # ── Cognitive state operations ────────────────────────────────────

    def update_cognitive_state(
        self,
        *,
        slots: dict[str, Any] | None = None,
        intent: str | None = None,
        intent_confidence: float | None = None,
        open_questions: list[str] | None = None,
        established_facts: list[dict[str, Any]] | None = None,
    ) -> None:
        """Merge new understanding into the CognitiveStateObject."""
        if self._cso is None:
            return
        try:
            if intent:
                self._cso.goal_state.objective = f"{intent}: " + (
                    self._cso.goal_state.objective or ""
                )
            if open_questions:
                self._cso.open_questions = list(
                    dict.fromkeys(self._cso.open_questions + open_questions)
                )
            if established_facts:
                from crp.state import EstablishedFact, ProvenanceKind

                for f in established_facts:
                    self._cso.established_facts.append(
                        EstablishedFact(
                            fact_id=str(f.get("fact_id") or f.get("key") or ""),
                            statement=str(f.get("statement") or f.get("value") or ""),
                            provenance=ProvenanceKind.DERIVED,
                            provenance_ref=str(f.get("provenance_ref") or ""),
                            confidence=float(f.get("confidence", 1.0)),
                        )
                    )
            # Store slots as established facts so they are recalled across
            # sessions and do not have to be re-asked.
            if slots:
                from crp.state import EstablishedFact, ProvenanceKind

                for key, value in slots.items():
                    self._cso.established_facts.append(
                        EstablishedFact(
                            fact_id=str(key),
                            statement=str(value),
                            provenance=ProvenanceKind.DERIVED,
                            confidence=1.0,
                        )
                    )
        except Exception:  # noqa: BLE001
            logger.debug("update_cognitive_state failed", exc_info=True)

    def to_extra_context(self) -> str:
        """Render the context + profile tiers as extra context for the agent.

        CRPv5 source-tier tags keep tenant, session and corpus scopes
        distinguishable in the prompt so the LLM does not blend authoritative
        organisation facts with retrieved regulatory text.
        """
        parts: list[str] = []
        if self._profile:
            parts.append("## Organisation profile [source:tenant]")
            for key, value in self._profile.items():
                parts.append(f"- {key}: {value}")
        intent = ""
        if self._cso is not None:
            intent = str(getattr(self._cso.goal_state, "objective", "") or "").split(":")[0]
        if intent:
            parts.append(f"## Current intent [source:session]\n- {intent}")
        slots = self.current_slots()
        if slots:
            parts.append("## Known session context [source:session]")
            for key, value in slots.items():
                parts.append(f"- {key}: {value}")
        if self._cso is not None and getattr(self._cso, "open_questions", None):
            parts.append("## Open questions [source:session]")
            for q in self._cso.open_questions:
                parts.append(f"- {q}")
        return "\n".join(parts)

    def current_slots(self) -> dict[str, Any]:
        """Best-effort extraction of slots from the cognitive state."""
        slots: dict[str, Any] = {}
        if self._cso is None:
            return slots
        try:
            for fact in getattr(self._cso, "established_facts", []) or []:
                key = getattr(fact, "fact_id", "")
                val = getattr(fact, "statement", "")
                if key and val and key not in slots:
                    slots[key] = val
        except Exception:  # noqa: BLE001
            pass
        return slots

    # ── Continuation state ────────────────────────────────────────────

    def save_continuation_state(self, state: dict[str, Any]) -> None:
        """Persist in-flight continuation windows so /continue can resume.

        Phase 6 — the state includes the partial answer accumulated so far,
        the envelope that produced it, and the remaining window budget.
        """
        self._continuation_state = dict(state)
        self._continuation_state["updated_at"] = time.time()
        self.save()

    def load_continuation_state(self) -> dict[str, Any] | None:
        """Return the persisted continuation state, if any."""
        return self._continuation_state

    def clear_continuation_state(self) -> None:
        """Mark a continuation as complete/cancelled."""
        self._continuation_state = None
        self.save()

    # ── Migration ─────────────────────────────────────────────────────

    def migrate_from_flat_record(self, record: dict[str, Any]) -> None:
        """Import an old flat JSON session record into the memory substrate."""
        messages = list(record.get("messages") or [])
        for idx, msg in enumerate(messages):
            role = str(msg.get("role") or "user")
            content = str(msg.get("content") or "")
            self.add_turn(role, content)
        # Import profile if present.
        self._profile = dict(record.get("org_profile") or record.get("profile") or {})
        # Import slots/clarifications as cognitive state.
        slots = dict(record.get("slots") or {})
        open_qs = [str(q) for q in record.get("clarifications") or []]
        self.update_cognitive_state(slots=slots, open_questions=open_qs)
        self.save()
