# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Dialogue manager for the compliance agent (Round 3).

Tracks conversational state, decides the next action, and coordinates
form-filling when required slots are missing.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from .memory import CompliantMemory
from .nlu import NluEngine, NluEntity, NluResult, SlotBoard

logger = logging.getLogger(__name__)


# ── User model helper ───────────────────────────────────────────────


@dataclass
class UserModel:
    """Thin wrapper around a tenant OrgProfile for dialogue slot seeding."""

    profile: dict[str, Any]

    def to_slots(self) -> dict[str, Any]:
        """Map OrgProfile fields to dialogue slot keys."""
        return _profile_to_slots(self.profile)


def _profile_to_slots(profile: dict[str, Any]) -> dict[str, Any]:
    """Convert an OrgProfile dict into dialogue slot keys.

    The mapping is deterministic and read-only: it never writes back to the
    profile store and never overwrites slots that are already populated.
    """
    if not profile:
        return {}

    slots: dict[str, Any] = {}

    if profile.get("org_name"):
        slots["org_name"] = profile["org_name"]

    # Actor / system type hierarchy: GPAI flag wins, then actor, then category.
    actor = profile.get("actor")
    system_category = profile.get("system_category")
    if profile.get("is_gpai"):
        slots["system_type"] = "GPAI provider"
    elif actor:
        slots["system_type"] = actor
    elif system_category:
        slots["system_type"] = system_category

    # Jurisdiction: single value or comma-joined list.
    jurisdictions = profile.get("jurisdictions")
    if isinstance(jurisdictions, list) and jurisdictions:
        cleaned = [str(j).strip() for j in jurisdictions if str(j).strip()]
        if cleaned:
            slots["jurisdiction"] = cleaned[0] if len(cleaned) == 1 else ", ".join(cleaned)
    elif isinstance(jurisdictions, str) and jurisdictions.strip():
        slots["jurisdiction"] = jurisdictions.strip()

    # Risk class: high-risk flag wins over annex III row.
    if profile.get("is_high_risk"):
        slots["risk_class"] = "high-risk"
    elif profile.get("annex_iii_row"):
        slots["risk_class"] = profile["annex_iii_row"]

    # Data type: biometric is more specific than generic personal data.
    if profile.get("biometric"):
        slots["data_type"] = "biometric data"
    elif profile.get("processes_personal_data"):
        slots["data_type"] = "personal data"

    # Children flag surfaces as a purpose / data-type hint.
    if profile.get("children") or profile.get("children_users"):
        slots["purpose"] = "children"
        if slots.get("data_type") == "personal data":
            slots["data_type"] = "children's personal data"

    return slots


# ── State / Turn model ──────────────────────────────────────────────


@dataclass
class DialogueTurn:
    role: str  # "user" | "agent" | "tool"
    text: str = ""
    structured: dict[str, Any] | None = None


@dataclass
class DialogueState:
    """Mutable conversation context."""

    turn_index: int = 0
    current_intent: str = "unknown"
    slots: SlotBoard = field(default_factory=SlotBoard)
    history: list[DialogueTurn] = field(default_factory=list)
    last_entities: list = field(default_factory=list)
    pending_clarification: str | None = None
    task_type: str | None = None
    finished: bool = False
    confirmed: bool = False
    # Round 7 — incremental confirmation and repair ledger.
    confirmed_slots: dict[str, Any] = field(default_factory=dict)
    repair_history: list[dict[str, Any]] = field(default_factory=list)
    pending_decision: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn_index": self.turn_index,
            "current_intent": self.current_intent,
            "slots": self.slots.to_dict(),
            "history": [
                {"role": t.role, "text": t.text, "structured": t.structured} for t in self.history
            ],
            "pending_clarification": self.pending_clarification,
            "task_type": self.task_type,
            "finished": self.finished,
            "confirmed": self.confirmed,
            "confirmed_slots": dict(self.confirmed_slots),
            "repair_history": list(self.repair_history),
            "pending_decision": self.pending_decision,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DialogueState":
        return cls(
            turn_index=data.get("turn_index", 0),
            current_intent=data.get("current_intent", "unknown"),
            slots=SlotBoard.from_dict(data.get("slots", {})),
            history=[
                DialogueTurn(
                    role=t.get("role", "user"),
                    text=t.get("text", ""),
                    structured=t.get("structured"),
                )
                for t in data.get("history", [])
            ],
            pending_clarification=data.get("pending_clarification"),
            task_type=data.get("task_type"),
            finished=data.get("finished", False),
            confirmed=data.get("confirmed", False),
            confirmed_slots=dict(data.get("confirmed_slots") or {}),
            repair_history=list(data.get("repair_history") or []),
            pending_decision=data.get("pending_decision"),
        )


# ── Dialogue policy ─────────────────────────────────────────────────


@dataclass
class PolicyDecision:
    action: str
    args: dict[str, Any] = field(default_factory=dict)
    reply_text: str = ""
    requires_llm: bool = False
    options: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "args": dict(self.args),
            "reply_text": self.reply_text,
            "requires_llm": self.requires_llm,
            "options": list(self.options) if self.options is not None else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PolicyDecision":
        return cls(
            action=data.get("action", "unknown"),
            args=dict(data.get("args") or {}),
            reply_text=data.get("reply_text", ""),
            requires_llm=bool(data.get("requires_llm", False)),
            options=list(data["options"]) if data.get("options") is not None else None,
        )


class DialoguePolicy:
    """Decide the next action from NLU output and dialogue state."""

    TASK_INTENTS = {"produce_artefact", "audit_existing", "scope", "compare"}
    _CONFIRM_CONFIDENCE = 0.6

    def __init__(self) -> None:
        self._intent_handlers: dict[str, Callable[[NluResult, DialogueState], PolicyDecision]] = {
            "produce_artefact": self._handle_produce,
            "audit_existing": self._handle_audit,
            "scope": self._handle_scope,
            "compare": self._handle_compare,
            "cite": self._handle_cite,
            "define": self._handle_define,
            "unknown": self._handle_unknown,
        }

    def decide(
        self,
        nlu: NluResult,
        state: DialogueState,
        *,
        prior_slots: dict[str, Any] | None = None,
    ) -> PolicyDecision:
        effective_intent = self._effective_intent(nlu, state)
        required = self._form_required(effective_intent)

        # Infer task_type for produce_artefact before repair/confirm checks.
        if effective_intent == "produce_artefact":
            if not state.slots.get("task_type") and not nlu.slots.get("task_type"):
                task_text = nlu.text.lower()
                if "dpia" in task_text:
                    nlu.slots["task_type"] = "dpia"
                elif "risk" in task_text:
                    nlu.slots["task_type"] = "risk_assessment"
                elif "audit" in task_text:
                    nlu.slots["task_type"] = "audit_report"
            for k, v in nlu.slots.items():
                if v:
                    state.slots.set(k, v)

        prior_slots = prior_slots or {}
        merged = {**state.slots.to_dict(), **nlu.slots}

        # Round 7 — when the utterance is too vague to act on and carries no
        # useful slots, ask a clarifying question rather than guessing.
        if (
            effective_intent == "unknown"
            and nlu.intent_confidence < 0.55
            and not nlu.slots
            and not state.slots.to_dict()
        ):
            return PolicyDecision(
                action="clarify_intent",
                args={"intent": "unknown", "slots": merged},
                reply_text="I'm not sure what you'd like me to do. Could you rephrase? For example, ask me to define a term, compare frameworks, scope a system, or draft an artefact.",
                requires_llm=False,
            )

        # Round 7 — repair: the user's answer contradicts a known fact or is vague.
        repair = self._maybe_repair(nlu, prior_slots)
        if repair is not None:
            repair.args["intent"] = effective_intent
            repair.args["slots"] = merged
            repair.args["sentiment"] = nlu.sentiment
            return repair

        # Round 7 — probe: required slot still missing.
        missing = [k for k in required if not merged.get(k)]
        if missing:
            return PolicyDecision(
                action="probe",
                args={"missing": missing, "intent": effective_intent, "slots": merged},
                reply_text=_compose_probe(missing),
                requires_llm=False,
            )

        # Round 7 — confirm: all required slots present and confidence is high enough.
        if (
            effective_intent in self.TASK_INTENTS
            and not state.confirmed
            and nlu.intent_confidence >= self._CONFIRM_CONFIDENCE
        ):
            return PolicyDecision(
                action="confirm",
                args={"slots": merged, "intent": effective_intent},
                reply_text=_compose_confirmation(merged, effective_intent),
                options=["Yes, that's right", "No, let me correct it"],
                requires_llm=False,
            )

        # Enough information — delegate to the reasoning engine.
        handler = self._intent_handlers.get(effective_intent, self._handle_unknown)
        decision = handler(nlu, state)
        decision.args["intent"] = effective_intent
        decision.args["slots"] = merged
        decision.args["sentiment"] = nlu.sentiment
        return decision

    def _effective_intent(self, nlu: NluResult, state: DialogueState) -> str:
        effective_intent = nlu.intent
        if (
            effective_intent in ("unknown", "define", "cite")
            and state.current_intent in self.TASK_INTENTS
        ):
            effective_intent = state.current_intent
        if effective_intent == "unknown" and state.current_intent not in ("unknown", ""):
            effective_intent = state.current_intent
        return effective_intent

    @staticmethod
    def _form_required(intent: str) -> list[str]:
        mapping = {
            "produce_artefact": ["regulation", "task_type"],
            "audit_existing": ["system_type", "jurisdiction"],
            "scope": ["system_type", "jurisdiction"],
            "compare": ["regulation"],
            "cite": ["regulation"],
            "define": ["regulation"],
        }
        return mapping.get(intent, [])

    def _maybe_repair(self, nlu: NluResult, prior_slots: dict[str, Any]) -> PolicyDecision | None:
        for slot, value in nlu.slots.items():
            if not value:
                continue
            if _is_vague(value):
                return PolicyDecision(
                    action="repair",
                    args={"slot": slot, "value": value, "reason": "vague"},
                    reply_text=_compose_repair(slot, value, "vague"),
                    options=["Let me rephrase"],
                    requires_llm=False,
                )
            existing = prior_slots.get(slot)
            if existing and existing.strip().lower() != value.strip().lower():
                return PolicyDecision(
                    action="repair",
                    args={
                        "slot": slot,
                        "value": value,
                        "existing": existing,
                        "reason": "contradiction",
                    },
                    reply_text=_compose_repair(slot, value, "contradiction", existing),
                    options=["Use the new value", "Keep the original value"],
                    requires_llm=False,
                )
        return None

    def _handle_produce(self, nlu: NluResult, state: DialogueState) -> PolicyDecision:
        return PolicyDecision(
            action="produce_artefact",
            args={"task_type": state.slots.get("task_type")},
            requires_llm=True,
        )

    def _handle_audit(self, nlu: NluResult, state: DialogueState) -> PolicyDecision:
        return PolicyDecision(
            action="audit_existing",
            args={},
            requires_llm=True,
        )

    def _handle_scope(self, nlu: NluResult, state: DialogueState) -> PolicyDecision:
        return PolicyDecision(
            action="scope_assessment",
            args={},
            requires_llm=True,
        )

    def _handle_compare(self, nlu: NluResult, state: DialogueState) -> PolicyDecision:
        return PolicyDecision(
            action="compare",
            args={},
            requires_llm=True,
        )

    def _handle_cite(self, nlu: NluResult, state: DialogueState) -> PolicyDecision:
        return PolicyDecision(
            action="cite",
            args={},
            requires_llm=True,
        )

    def _handle_define(self, nlu: NluResult, state: DialogueState) -> PolicyDecision:
        return PolicyDecision(
            action="define",
            args={},
            requires_llm=True,
        )

    def _handle_unknown(self, nlu: NluResult, state: DialogueState) -> PolicyDecision:
        return PolicyDecision(
            action="delegate_reasoner",
            args={},
            reply_text="",
            requires_llm=True,
        )


# ── Response composers (Round 7) ─────────────────────────────────────


_SLOT_LABELS = {
    "regulation": "Regulation",
    "jurisdiction": "Jurisdiction",
    "system_type": "System type",
    "data_type": "Data processed",
    "purpose": "Purpose",
    "task_type": "Artefact/task type",
}


def _is_vague(value: str) -> bool:
    stripped = value.strip().lower()
    return len(stripped) < 2 or stripped in {"idk", "n/a", "unknown", "not sure", "unsure"}


def _is_affirmative(answer: str) -> bool:
    normalized = re.sub(r"[^\w\s]", "", answer.lower()).strip()
    return normalized in {
        "yes",
        "yeah",
        "yep",
        "yes thats right",
        "yes that is right",
        "yes thats correct",
        "yes that is correct",
        "thats right",
        "that is right",
        "correct",
        "right",
        "sure",
        "ok",
        "okay",
        "confirm",
        "confirmed",
    }


def _compose_confirmation(slots: dict[str, Any], intent: str) -> str:
    lines = ["Before I continue, let me confirm what I understood:"]
    for key, label in _SLOT_LABELS.items():
        value = slots.get(key)
        if value:
            lines.append(f"- {label}: {value}")
    lines.append("Does that look right?")
    return "\n".join(lines)


def _compose_repair(slot: str, value: str, reason: str, existing: str = "") -> str:
    label = _SLOT_LABELS.get(slot, slot)
    if reason == "contradiction" and existing:
        return (
            f"I understood '{value}' for {label}, but earlier I had '{existing}'. "
            "Could you clarify which is correct?"
        )
    return f"I'm not sure I understood '{value}' for {label}. Could you be more specific?"


def _compose_probe(missing: list[str]) -> str:
    mapping = {
        "regulation": "Which regulation should I use (e.g., EU AI Act, GDPR, ISO 42001)?",
        "jurisdiction": "Which jurisdiction are you operating in?",
        "system_type": "What kind of AI system are you asking about?",
        "data_type": "What personal or sensitive data does the system process?",
        "purpose": "What is the intended purpose of the system?",
        "task_type": "What artefact should I produce (e.g., DPIA, risk assessment, gap report)?",
    }
    questions = [mapping.get(m, f"Could you tell me the {m}?") for m in missing]
    return " ".join(questions)


# ── Form orchestrator ───────────────────────────────────────────────


class FormOrchestrator:
    """Runs a simple slot-filling form across turns."""

    def __init__(self, policy: DialoguePolicy) -> None:
        self.policy = policy

    def update_state(self, nlu: NluResult, state: DialogueState) -> None:
        """Merge newly extracted slots into the dialogue state."""
        for key, value in nlu.slots.items():
            if value:
                # Overwrite with the latest value so follow-up utterances can
                # refine or correct earlier slots.
                state.slots.set(key, value)
        # Preserve the current intent across vague/elliptical turns and when
        # the user is just answering a clarification question with a slot value.
        task_intents = {"produce_artefact", "audit_existing", "scope", "compare"}
        is_slot_answer = nlu.coreferred_text and nlu.coreferred_text != nlu.text
        if state.current_intent in task_intents and (
            nlu.intent in ("unknown", "define", "cite") or is_slot_answer
        ):
            pass  # keep current task intent
        elif (
            nlu.intent != "unknown" or not state.current_intent or state.current_intent == "unknown"
        ):
            state.current_intent = nlu.intent
        state.last_entities = [
            {"type": e.type, "value": e.value, "span": e.span} for e in nlu.entities
        ]
        state.history.append(
            DialogueTurn(
                role="user",
                text=nlu.text,
                structured={
                    "intent": nlu.intent,
                    "slots": nlu.slots,
                    "sentiment": nlu.sentiment,
                },
            )
        )

    def decide(
        self,
        nlu: NluResult,
        state: DialogueState,
    ) -> PolicyDecision:
        prior_slots = state.slots.to_dict()
        self.update_state(nlu, state)
        decision = self.policy.decide(nlu, state, prior_slots=prior_slots)
        if decision.action in ("probe", "repair", "confirm"):
            state.pending_clarification = (
                decision.args.get("slot") or (decision.args.get("missing") or [None])[0]
            )
        else:
            state.pending_clarification = None
        return decision


# ── Dialogue state tracker ──────────────────────────────────────────


class DialogueStateTracker:
    """Owns the in-memory and persisted dialogue state for one user."""

    def __init__(
        self,
        user_id: str,
        nlu: NluEngine | None = None,
        policy: DialoguePolicy | None = None,
        form: FormOrchestrator | None = None,
        persist_fn: Callable[[str, dict[str, Any]], None] | None = None,
        load_fn: Callable[[str], dict[str, Any] | None] | None = None,
        memory: CompliantMemory | None = None,
        user_profile: dict[str, Any] | None = None,
    ) -> None:
        self.user_id = user_id
        self.nlu = nlu or NluEngine()
        self.policy = policy or DialoguePolicy()
        self.form = form or FormOrchestrator(self.policy)
        self._memory = memory
        self._persist_fn = persist_fn
        self._load_fn = load_fn
        self._state = self._load()
        self._user_profile: dict[str, Any] | None = None
        if user_profile:
            self.load_user_model(user_profile)

    def load_user_model(self, profile: dict[str, Any] | None) -> None:
        """Seed dialogue slots from an OrgProfile without overwriting existing values."""
        self._user_profile = dict(profile or {})
        for key, value in _profile_to_slots(self._user_profile).items():
            if value and not self._state.slots.get(key):
                self._state.slots.set(key, value)
        if self._memory is not None:
            try:
                self._memory.set_profile(self._user_profile)
            except Exception:  # noqa: BLE001
                logger.debug("Failed to set profile on memory substrate", exc_info=True)

    def _load(self) -> DialogueState:
        if self._load_fn:
            try:
                data = self._load_fn(self.user_id)
                if data:
                    return DialogueState.from_dict(data)
            except Exception:  # noqa: BLE001
                logger.debug("Failed to load dialogue state", exc_info=True)
        return DialogueState()

    def save(self) -> None:
        if self._memory is not None:
            try:
                self._memory.update_cognitive_state(
                    slots=self._state.slots.to_dict(),
                    intent=self._state.current_intent,
                    open_questions=[self._state.pending_clarification]
                    if self._state.pending_clarification
                    else [],
                )
                self._memory.save()
            except Exception:  # noqa: BLE001
                logger.debug("Failed to persist dialogue state via memory", exc_info=True)
        if self._persist_fn:
            try:
                self._persist_fn(self.user_id, self._state.to_dict())
            except Exception:  # noqa: BLE001
                logger.debug("Failed to persist dialogue state", exc_info=True)

    @property
    def state(self) -> DialogueState:
        return self._state

    def process_utterance(
        self,
        text: str,
        *,
        required_slots: list[str] | None = None,
    ) -> tuple[NluResult, PolicyDecision]:
        last_entities = [
            NluEntity(type=e["type"], value=e["value"], span=tuple(e["span"]), confidence=1.0)
            for e in self._state.last_entities
            if isinstance(e, dict)
        ]
        filled_slots = self._state.slots.to_dict()
        nlu = self.nlu.parse(
            text,
            context={"history": [t.text for t in self._state.history[-5:]]},
            last_entities=last_entities,
            required_slots=required_slots,
            user_profile=self._user_profile,
            filled_slots=filled_slots,
        )
        decision = self.form.decide(nlu, self._state)
        self._set_pending_if_clarify(decision)
        self._state.turn_index += 1
        self.save()
        return nlu, decision

    def set_pending_decision(self, decision: PolicyDecision) -> None:
        """Store a policy decision so it can be resumed after user input."""
        self._state.pending_decision = decision.to_dict()
        self.save()

    def resume(self, answer: str) -> PolicyDecision | None:
        """Resume from a suspended clarification decision.

        Interprets *answer* in the context of the pending decision and
        returns the next clarification decision, or ``None`` when enough
        information is available and reasoning can proceed.
        """
        answer = (answer or "").strip()
        if not answer:
            raise ValueError("answer must not be empty")

        pending = self._state.pending_decision
        if pending is None:
            _, decision = self.process_utterance(answer)
            return decision

        decision = PolicyDecision.from_dict(pending)
        self._record_answer_turn(answer, decision.action)

        if decision.action == "confirm":
            return self._resume_confirm(answer, decision)
        if decision.action == "repair":
            return self._resume_repair(answer, decision)
        if decision.action == "probe":
            return self._resume_probe(answer, decision)
        if decision.action == "clarify_intent":
            self._state.pending_decision = None
            _, next_decision = self.process_utterance(answer)
            return next_decision

        self._state.pending_decision = None
        _, next_decision = self.process_utterance(answer)
        return next_decision

    def _record_answer_turn(self, answer: str, action: str) -> None:
        self._state.history.append(
            DialogueTurn(
                role="user",
                text=answer,
                structured={"action": action, "pending": True},
            )
        )

    def _resume_confirm(self, answer: str, decision: PolicyDecision) -> PolicyDecision | None:
        if _is_affirmative(answer):
            for key, value in (decision.args.get("slots") or {}).items():
                if value:
                    self._state.confirmed_slots[key] = value
            self._state.confirmed = True
            self._state.pending_decision = None
            self.save()
            return None

        # User disagreed — ask which slot to correct.
        slot_map = {
            label: key
            for key, label in _SLOT_LABELS.items()
            if (decision.args.get("slots") or {}).get(key)
        }
        options = [f"Correct {label}" for label in slot_map.keys()]
        repair = PolicyDecision(
            action="repair",
            args={
                "intent": decision.args.get("intent"),
                "slots": decision.args.get("slots"),
                "reason": "user_disagreed",
                "slot_options": slot_map,
            },
            reply_text="Which detail would you like to correct?",
            options=options or None,
            requires_llm=False,
        )
        self._state.pending_decision = repair.to_dict()
        self.save()
        return repair

    def _resume_repair(self, answer: str, decision: PolicyDecision) -> PolicyDecision | None:
        reason = decision.args.get("reason")
        slot_options = decision.args.get("slot_options") or {}
        target_slot = decision.args.get("slot")

        # Branch from confirm-no: user picked a slot label to correct.
        if reason == "user_disagreed" and slot_options:
            for label, key in slot_options.items():
                if answer.lower() in label.lower() or label.lower() in answer.lower():
                    return self._probe_for_slot(key)
            return decision

        if not target_slot:
            self._state.pending_decision = None
            return None

        existing = decision.args.get("existing") or self._state.slots.get(target_slot)
        new_value = decision.args.get("value")
        options = decision.options or []

        if answer in options:
            lowered = answer.lower()
            if "new" in lowered:
                if new_value:
                    self._state.slots.set(target_slot, new_value)
            elif "original" in lowered:
                if existing:
                    self._state.slots.set(target_slot, existing)
            elif "rephrase" in lowered:
                return self._probe_for_slot(target_slot)
        else:
            # Free-text correction.
            self._state.slots.set(target_slot, answer)

        self._state.repair_history.append(
            {
                "slot": target_slot,
                "prior": existing,
                "final": self._state.slots.get(target_slot),
                "reason": reason,
            }
        )
        self._state.pending_decision = None
        return self._decide_next_after_update()

    def _resume_probe(self, answer: str, decision: PolicyDecision) -> PolicyDecision | None:
        target_slot = decision.args.get("slot")
        missing = list(decision.args.get("missing") or [])
        if target_slot:
            self._state.slots.set(target_slot, answer)
        elif missing:
            self._state.slots.set(missing[0], answer)

        required = missing or ([target_slot] if target_slot else [])
        last_entities = [
            NluEntity(type=e["type"], value=e["value"], span=tuple(e["span"]), confidence=1.0)
            for e in self._state.last_entities
            if isinstance(e, dict)
        ]
        nlu = self.nlu.parse(
            answer,
            context={"history": [t.text for t in self._state.history[-5:]]},
            last_entities=last_entities,
            required_slots=required,
            user_profile=self._user_profile,
            filled_slots=self._state.slots.to_dict(),
        )
        prior_slots = dict(self._state.slots.to_dict())
        self.form.update_state(nlu, self._state)
        self._state.pending_decision = None
        next_decision = self.policy.decide(nlu, self._state, prior_slots=prior_slots)
        self._set_pending_if_clarify(next_decision)
        self._state.turn_index += 1
        self.save()
        return next_decision

    def _probe_for_slot(self, slot: str) -> PolicyDecision:
        question = _compose_probe([slot])
        decision = PolicyDecision(
            action="probe",
            args={"missing": [slot], "slot": slot, "intent": self._state.current_intent},
            reply_text=question,
            requires_llm=False,
        )
        self._state.pending_decision = decision.to_dict()
        self.save()
        return decision

    def _decide_next_after_update(self) -> PolicyDecision | None:
        slots = self._state.slots.to_dict()
        nlu = self.nlu.parse(
            "",
            context={},
            last_entities=[],
            required_slots=[],
            user_profile=self._user_profile,
            filled_slots=slots,
        )
        for key, value in slots.items():
            if value:
                nlu.slots[key] = value
        next_decision = self.policy.decide(nlu, self._state, prior_slots=slots)
        self._set_pending_if_clarify(next_decision)
        self.save()
        return next_decision

    def _set_pending_if_clarify(self, decision: PolicyDecision) -> None:
        if decision.action in {"probe", "repair", "confirm", "clarify_intent"}:
            self._state.pending_decision = decision.to_dict()
        else:
            self._state.pending_decision = None

    def add_agent_turn(self, text: str, structured: dict[str, Any] | None = None) -> None:
        self._state.history.append(DialogueTurn(role="agent", text=text, structured=structured))
        self.save()

    def finish(self) -> None:
        self._state.finished = True
        self.save()
