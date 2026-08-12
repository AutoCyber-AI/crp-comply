# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Lightweight NLU layer for the compliance agent (Round 3 + NLU v2).

Extracts intents, entities, and slots from user input using deterministic
regex gazetteers first, with an optional lightweight LLM fallback for
open-ended entities. Provides coreference/ellipsis repair and a sentiment
signal so the dialogue policy can adapt its tone.

NLU v2 improvements:
- Canonical entity normalisation (jurisdiction codes, regulation names,
  task-type short names) so downstream planners compare stable values.
- Richer entity types: risk level, deadlines, articles/sections, roles,
  question sub-type (fines, obligations, exemptions, deadlines, etc.).
- More robust intent classification with regex anchors and social intents.
- Depth/format/audience inference that respects explicit cues, the user's
  learned preference profile, and the intent/question type.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ── Known entity gazetteers ─────────────────────────────────────────

_REGULATIONS = {
    "eu ai act",
    "ai act",
    "eu_ai_act",
    "gdpr",
    "uk gdpr",
    "data protection act",
    "dpa 2018",
    "nis2",
    "dora",
    "iso 42001",
    "iso 22989",
    "nist ai rmf",
    "uk ai whitepaper",
    "uk ai act",
    "ccpa",
    "hipaa",
    "soc 2",
    "iso 27001",
}

# Map every known regulation string to a stable canonical name.
_REGULATION_CANONICAL: dict[str, str] = {
    "eu ai act": "eu ai act",
    "ai act": "eu ai act",
    "eu_ai_act": "eu ai act",
    "gdpr": "gdpr",
    "uk gdpr": "uk gdpr",
    "data protection act": "data protection act",
    "dpa 2018": "dpa 2018",
    "nis2": "nis2",
    "dora": "dora",
    "iso 42001": "iso 42001",
    "iso 22989": "iso 22989",
    "nist ai rmf": "nist ai rmf",
    "uk ai whitepaper": "uk ai whitepaper",
    "uk ai act": "uk ai act",
    "ccpa": "ccpa",
    "hipaa": "hipaa",
    "soc 2": "soc 2",
    "iso 27001": "iso 27001",
}

_JURISDICTIONS = {
    "eu",
    "europe",
    "european union",
    "uk",
    "united kingdom",
    "great britain",
    "us",
    "usa",
    "united states",
    "america",
    "australia",
    "australian",
    "au",
    "canada",
    "canadian",
    "ca",
    "singapore",
    "singaporean",
    "sg",
    "japan",
    "japanese",
    "jp",
    "brazil",
    "brazilian",
    "br",
    "india",
    "indian",
}

# Map every known jurisdiction string to a stable canonical code.
_JURISDICTION_CANONICAL: dict[str, str] = {
    "eu": "eu",
    "europe": "eu",
    "european union": "eu",
    "uk": "uk",
    "united kingdom": "uk",
    "great britain": "uk",
    "us": "us",
    "usa": "us",
    "united states": "us",
    "america": "us",
    "australia": "au",
    "australian": "au",
    "au": "au",
    "canada": "ca",
    "canadian": "ca",
    "ca": "ca",
    "singapore": "sg",
    "singaporean": "sg",
    "sg": "sg",
    "japan": "jp",
    "japanese": "jp",
    "jp": "jp",
    "brazil": "br",
    "brazilian": "br",
    "br": "br",
    "india": "in",
    "indian": "in",
}

_SYSTEM_TYPE_HINTS = {
    "hiring assistant",
    "recruitment tool",
    "recruitment assistant",
    "cv screening",
    "resume parser",
    "resume screening",
    "chatbot",
    "ai chatbot",
    "conversational ai",
    "recommendation system",
    "recommender system",
    "fraud detection",
    "fraud detection system",
    "credit scoring",
    "credit scoring system",
    "medical device",
    "clinical decision support",
    "diagnostic",
    "diagnostic system",
    "surveillance",
    "surveillance system",
    "biometric",
    "biometric system",
    "facial recognition",
    "generative ai",
    "gen ai",
    "gpai",
    "general purpose ai",
    "foundation model",
}

_SYSTEM_TYPE_CANONICAL: dict[str, str] = {
    "hiring assistant": "hiring assistant",
    "recruitment tool": "hiring assistant",
    "recruitment assistant": "hiring assistant",
    "cv screening": "cv screening",
    "resume parser": "cv screening",
    "resume screening": "cv screening",
    "chatbot": "chatbot",
    "ai chatbot": "chatbot",
    "conversational ai": "chatbot",
    "recommendation system": "recommendation system",
    "recommender system": "recommendation system",
    "fraud detection": "fraud detection",
    "fraud detection system": "fraud detection",
    "credit scoring": "credit scoring",
    "credit scoring system": "credit scoring",
    "medical device": "medical device",
    "clinical decision support": "medical device",
    "diagnostic": "diagnostic",
    "diagnostic system": "diagnostic",
    "surveillance": "surveillance",
    "surveillance system": "surveillance",
    "biometric": "biometric",
    "biometric system": "biometric",
    "facial recognition": "biometric",
    "generative ai": "generative ai",
    "gen ai": "generative ai",
    "gpai": "gpai",
    "general purpose ai": "gpai",
    "foundation model": "foundation model",
}

_DATA_TYPE_HINTS = {
    "cv",
    "cvs",
    "resume",
    "resumes",
    "personal data",
    "pii",
    "personally identifiable information",
    "health data",
    "medical data",
    "biometric data",
    "biometrics",
    "financial data",
    "location data",
    "behavioural data",
    "behavioral data",
    "criminal record",
    "criminal records",
    "special category data",
    "special categories",
    "children's data",
    "minor data",
}

_DATA_TYPE_CANONICAL: dict[str, str] = {
    "cv": "cv",
    "cvs": "cv",
    "resume": "cv",
    "resumes": "cv",
    "personal data": "personal data",
    "pii": "personal data",
    "personally identifiable information": "personal data",
    "health data": "health data",
    "medical data": "health data",
    "biometric data": "biometric data",
    "biometrics": "biometric data",
    "financial data": "financial data",
    "location data": "location data",
    "behavioural data": "behavioural data",
    "behavioral data": "behavioural data",
    "criminal record": "criminal record",
    "criminal records": "criminal record",
    "special category data": "special category data",
    "special categories": "special category data",
    "children's data": "children's data",
    "minor data": "children's data",
}

_TASK_TYPE_HINTS = {
    "dpia",
    "data protection impact assessment",
    "risk assessment",
    "risk evaluation",
    "audit report",
    "compliance audit",
    "gap report",
    "gap analysis",
    "fria",
    "fundamental rights impact assessment",
    "conformity assessment",
    "records of processing",
    "record of processing activity",
    "ropa",
}

_TASK_TYPE_CANONICAL: dict[str, str] = {
    "dpia": "dpia",
    "data protection impact assessment": "dpia",
    "risk assessment": "risk assessment",
    "risk evaluation": "risk assessment",
    "audit report": "audit report",
    "compliance audit": "audit report",
    "gap report": "gap report",
    "gap analysis": "gap report",
    "fria": "fria",
    "fundamental rights impact assessment": "fria",
    "conformity assessment": "conformity assessment",
    "records of processing": "records of processing",
    "record of processing activity": "records of processing",
    "ropa": "records of processing",
}

_RISK_LEVEL_HINTS = {
    "high-risk",
    "high risk",
    "low-risk",
    "low risk",
    "minimal risk",
    "limited risk",
    "unacceptable risk",
    "prohibited",
}

_ROLE_HINTS = {
    "dpo",
    "data protection officer",
    "privacy officer",
    "ai officer",
    "responsible ai officer",
    "compliance officer",
    "data controller",
    "data processor",
    "operator",
    "deployer",
    "provider",
    "importer",
    "distributor",
    "authorised representative",
    "authorized representative",
}

_SENTIMENT_NEGATIVE = {
    "bad",
    "terrible",
    "awful",
    "frustrated",
    "annoying",
    "useless",
    "stupid",
    "broken",
    "wrong",
    "hate",
    "angry",
    "disappointed",
    "not helpful",
    "doesn't work",
    "waste of time",
}

_SENTIMENT_POSITIVE = {
    "good",
    "great",
    "excellent",
    "helpful",
    "useful",
    "amazing",
    "thanks",
    "thank you",
    "perfect",
    "love",
}

_DEPTH_HINTS: dict[str, tuple[str, ...]] = {
    "brief": (
        "brief",
        "short",
        "quick",
        "one sentence",
        "tl;dr",
        "in a nutshell",
        "concise",
        "just",
        "simply",
        "in simple terms",
    ),
    "standard": (),  # default when no explicit cue is present
    "thorough": (
        "detailed",
        "thorough",
        "in depth",
        "comprehensive",
        "long",
        "explain fully",
        "step by step",
        "deep dive",
        "exhaustive",
        "elaborate",
    ),
}

_FORMAT_HINTS: dict[str, tuple[str, ...]] = {
    "summary": ("summary", "summarise", "summarize", "overview", "high level"),
    "checklist": ("checklist", "list", "bullet points", "steps", "action items"),
    "report": ("report", "formal report", "audit-ready", "memorandum", "memo"),
    "citation_list": ("citations", "sources", "references", "articles", "cite"),
    "decision_tree": ("decision tree", "flowchart", "if then", "do i need"),
}

_AUDIENCE_HINTS: dict[str, tuple[str, ...]] = {
    "executive": ("executive", "ceo", "c-suite", "board", "leadership", "senior management"),
    "legal": ("legal", "lawyer", "counsel", "privacy officer", "dpo"),
    "engineer": ("engineer", "developer", "technical team", "ml team", "engineering"),
    "auditor": ("auditor", "audit", "compliance officer", "assessor"),
}

_URGENCY_HINTS: dict[str, tuple[str, ...]] = {
    "high": ("urgent", "asap", "immediately", "deadline", "today", "critical"),
    "low": ("whenever", "no rush", "not urgent", "curious"),
}

_SATISFACTION_CUES: tuple[str, ...] = (
    "must include",
    "needs to cover",
    "should mention",
    "i need to know",
    "make sure",
    "be sure to",
    "compare",
    "contrast",
    "difference between",
)

# Question sub-types that help the planner choose a simple vs. detailed answer.
_QUESTION_TYPE_HINTS: dict[str, tuple[str, ...]] = {
    "fines": ("fine", "fines", "penalty", "penalties", "sanction", "sanctions"),
    "deadline": ("deadline", "by when", "due date", "when do i need", "timeline"),
    "obligations": (
        "obligations",
        "requirements",
        "what do i need to do",
        "what are my obligations",
        "steps to comply",
        "how do i comply",
        "how to comply",
    ),
    "exemptions": ("exempt", "exemption", "exceptions", "exception", "does not apply"),
    "applicability": ("does it apply", "applicable", "apply to me", "scope", "in scope"),
    "risk": ("high-risk", "high risk", "risk classification", "risk level", "classify"),
    "examples": ("example", "examples", "sample", "samples", "template", "templates"),
    "summary": ("summarise", "summarize", "summary", "tl;dr", "in brief"),
}

# Social / meta intents that should not trigger reasoning.
_SOCIAL_INTENTS: dict[str, tuple[str, ...]] = {
    "greeting": ("hello", "hi", "hey", "good morning", "good afternoon", "good evening"),
    "goodbye": ("bye", "goodbye", "see you", "talk later"),
    "thanks": ("thanks", "thank you", "cheers", "appreciated"),
}


# ── Data classes ────────────────────────────────────────────────────


@dataclass
class NluEntity:
    """One extracted entity."""

    type: str
    value: str
    span: tuple[int, int]
    confidence: float = 1.0


@dataclass
class NluResult:
    """Structured output of the NLU pass."""

    text: str
    intent: str = "unknown"
    intent_confidence: float = 0.0
    entities: list[NluEntity] = field(default_factory=list)
    slots: dict[str, Any] = field(default_factory=dict)
    sentiment: str = "neutral"
    sentiment_score: float = 0.0
    coreferred_text: str = ""
    language: str = "en"


@dataclass
class SlotBoard:
    """Simple key/value slot store keyed by recipe/task."""

    _slots: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self._slots.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._slots[key] = value

    def missing(self, required: list[str]) -> list[str]:
        return [k for k in required if self.get(k) is None]

    def to_dict(self) -> dict[str, Any]:
        return dict(self._slots)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SlotBoard":
        return cls(_slots=dict(data))


def _jurisdiction_includes(jurisdictions: Any, target: str) -> bool:
    """True if ``jurisdictions`` contains ``target`` (case-insensitive)."""
    if not jurisdictions:
        return False
    if isinstance(jurisdictions, str):
        jurisdictions = [jurisdictions]
    target_lower = target.lower()
    return any(str(j).strip().lower() == target_lower for j in jurisdictions)


def _has_word(text: str, word: str) -> bool:
    """Case-insensitive whole-word or phrase match."""
    pattern = r"\b" + re.escape(word) + r"\b"
    return bool(re.search(pattern, text, flags=re.IGNORECASE))


# ── NLU engine ─────────────────────────────────────────────────────-


class NluEngine:
    """Deterministic NLU with optional LLM fallback for open entities."""

    def __init__(
        self,
        *,
        llm_fallback: Callable[[str, list[str]], dict[str, Any]] | None = None,
    ) -> None:
        self._llm_fallback = llm_fallback

    def parse(
        self,
        text: str,
        *,
        context: dict[str, Any] | None = None,
        last_entities: list[NluEntity] | None = None,
        required_slots: list[str] | None = None,
        user_profile: dict[str, Any] | None = None,
        filled_slots: dict[str, Any] | None = None,
    ) -> NluResult:
        """Parse user input into intent, entities, slots, sentiment."""
        if not text:
            return NluResult(text=text)

        lowered = text.lower()
        profile = user_profile or {}

        # 1. Intent classification (deterministic fast path)
        intent, intent_confidence = self._classify_intent(lowered, profile=profile)

        # 2. Entity extraction
        entities = self._extract_entities(text, lowered)

        # 3. Coreference / ellipsis repair
        coreferred = self._repair_coreference(text, lowered, last_entities or [])

        # 4. Sentiment
        sentiment, sentiment_score = self._sentiment(lowered)

        # 5. Slot filling
        slots = self._entities_to_slots(entities)

        # 5a. Response shape slots so the planner/formatters can tailor output.
        depth = self._extract_depth(lowered)
        if depth:
            slots["depth"] = depth
        format_hint = self._extract_format(lowered)
        if format_hint:
            slots["format"] = format_hint
        audience = self._extract_audience(lowered)
        if audience:
            slots["audience"] = audience
        urgency = self._extract_urgency(lowered)
        if urgency:
            slots["urgency"] = urgency
        satisfaction = self._extract_satisfaction_criteria(text)
        if satisfaction:
            slots["satisfaction_criteria"] = satisfaction

        # 5b. Question sub-type for simple-vs-detailed tailoring.
        question_type = self._extract_question_type(lowered, intent)
        if question_type:
            slots["question_type"] = question_type

        # 5c. Intent-driven depth fallback when the user is explicit about the
        # shape of answer they want but didn't use a depth keyword.
        if not slots.get("depth"):
            inferred_depth = self._infer_depth_from_intent_question(
                intent, question_type, format_hint
            )
            if inferred_depth:
                slots["depth"] = inferred_depth

        # 5d. Merge slots already filled by the user profile / prior turns without
        # overwriting values freshly extracted from this utterance.
        for key, value in (filled_slots or {}).items():
            if value and not slots.get(key):
                slots[key] = value

        # 5e. Deterministic profile biases (only when the utterance itself is
        # ambiguous and the profile gives a clear default).
        jurisdictions = profile.get("jurisdictions") or []
        if not slots.get("regulation") and _jurisdiction_includes(jurisdictions, "eu"):
            if any(t in lowered for t in ("ai", "artificial intelligence", "ai act")):
                slots["regulation"] = "eu ai act"
                intent = intent or "define"
                intent_confidence = max(intent_confidence, 0.6)
        if not slots.get("system_type") and profile.get("is_gpai"):
            slots["system_type"] = "GPAI provider"
        if (
            not slots.get("jurisdiction")
            and isinstance(jurisdictions, list)
            and len(jurisdictions) == 1
        ):
            slots["jurisdiction"] = _JURISDICTION_CANONICAL.get(
                jurisdictions[0].lower().strip(), jurisdictions[0]
            )

        # 5f. Learned preference fallback for depth/format/audience.
        self._apply_preference_defaults(slots, profile)

        # Optional LLM fallback for open-ended slots not captured by gazetteers.
        if required_slots and self._llm_fallback:
            missing = [s for s in required_slots if slots.get(s) is None]
            if missing:
                try:
                    inferred = self._llm_fallback(coreferred or text, missing)
                    for k, v in inferred.items():
                        if v and slots.get(k) is None:
                            slots[k] = v
                except Exception:  # noqa: BLE001
                    logger.debug("LLM fallback failed", exc_info=True)

        return NluResult(
            text=text,
            intent=intent,
            intent_confidence=intent_confidence,
            entities=entities,
            slots=slots,
            sentiment=sentiment,
            sentiment_score=sentiment_score,
            coreferred_text=coreferred,
        )

    @staticmethod
    def _extract_depth(lowered: str) -> str:
        """Map explicit length/depth cues to a response-depth slot."""
        for depth, hints in _DEPTH_HINTS.items():
            if any(h in lowered for h in hints):
                return depth
        return ""

    @staticmethod
    def _extract_format(lowered: str) -> str:
        """Map explicit format cues to a response-format slot."""
        for fmt, hints in _FORMAT_HINTS.items():
            if any(h in lowered for h in hints):
                return fmt
        return ""

    @staticmethod
    def _extract_audience(lowered: str) -> str:
        """Map explicit audience cues to an audience slot."""
        for audience, hints in _AUDIENCE_HINTS.items():
            if any(h in lowered for h in hints):
                return audience
        return ""

    @staticmethod
    def _extract_urgency(lowered: str) -> str:
        """Map explicit urgency cues to an urgency slot."""
        for urgency, hints in _URGENCY_HINTS.items():
            if any(h in lowered for h in hints):
                return urgency
        return ""

    @staticmethod
    def _extract_satisfaction_criteria(text: str) -> list[str]:
        """Capture explicit 'must include' / comparison criteria from the user."""
        lowered = text.lower()
        criteria: list[str] = []
        for cue in _SATISFACTION_CUES:
            idx = lowered.find(cue)
            if idx == -1:
                continue
            # Capture from the cue to the next sentence boundary or 180 chars.
            start = idx
            end = min(len(text), idx + 180)
            for sep in (". ", "? ", "! ", "; ", "\n"):
                pos = text.find(sep, idx)
                if pos != -1 and pos < end:
                    end = pos + 1
            criteria.append(text[start:end].strip())
        return criteria

    @staticmethod
    def _extract_question_type(lowered: str, intent: str) -> str:
        """Detect specialised question sub-types for answer tailoring."""
        for qtype, hints in _QUESTION_TYPE_HINTS.items():
            if any(h in lowered for h in hints):
                return qtype
        return ""

    @staticmethod
    def _infer_depth_from_intent_question(
        intent: str, question_type: str, format_hint: str
    ) -> str:
        """Default depth when the user is clear about answer shape but has no depth keyword."""
        # Citation / summary / examples are usually short.
        if intent == "cite" or question_type in {"fines", "summary", "examples"}:
            return "brief"
        # Obligations, thorough formats, and formal reports are usually detailed.
        if question_type in {"obligations"} or format_hint in {"report"}:
            return "thorough"
        return ""

    @staticmethod
    def _apply_preference_defaults(slots: dict[str, Any], profile: dict[str, Any]) -> None:
        """Fill depth/format/audience from the user's learned preference profile."""
        preferred_depth = profile.get("preferred_depth")
        if preferred_depth and not slots.get("depth"):
            slots["depth"] = preferred_depth
        preferred_format = profile.get("preferred_format")
        if preferred_format and not slots.get("format"):
            slots["format"] = preferred_format
        preferred_audience = profile.get("preferred_audience")
        if preferred_audience and not slots.get("audience"):
            slots["audience"] = preferred_audience

    @staticmethod
    def _classify_intent(
        lowered: str,
        profile: dict[str, Any] | None = None,
    ) -> tuple[str, float]:
        # Social / meta intents first — they should not trigger reasoning.
        for intent, hints in _SOCIAL_INTENTS.items():
            if any(lowered.strip().startswith(h) for h in hints):
                return intent, 0.75

        # Artefact generation.
        if re.search(
            r"\b(draft|generate|create|write|produce|prepare)\b.*\b(dpia|risk assessment|audit report|gap report|fria|conformity assessment|records of processing)\b",
            lowered,
        ):
            return "produce_artefact", 0.9
        if re.search(
            r"\b(dpia|risk assessment|audit report|gap report|fria)\b.*\b(draft|generate|create|write|produce)\b",
            lowered,
        ):
            return "produce_artefact", 0.9

        # Comparisons.
        if re.search(r"\bcompare\b|\bversus\b|\bvs\b|\bdifference\b", lowered):
            return "compare", 0.85

        # Scope / applicability.
        if re.search(
            r"\b(does|do|is|are)\b.*\bapply\b|\bapplicable\b|\bscope\b|\bin scope\b",
            lowered,
        ):
            return "scope", 0.8

        # Risk classification / audit of an existing system.
        if re.search(
            r"\b(high.risk|low.risk|minimal risk|unacceptable risk|prohibited|risk classification|risk level|classify)\b",
            lowered,
        ) or re.search(r"\bassess\b.*\brisk\b", lowered):
            return "audit_existing", 0.8

        # Definition / explanation requests.
        if re.search(
            r"\b(what is|what does|what are|explain|how does|meaning of|definition of|tell me about)\b",
            lowered,
        ):
            return "define", 0.85

        # Citation requests (explicit, or just naming an article without a question word).
        if re.search(r"\b(article|section|annex)\b.*\b(\d+[a-z]?)\b|\bcite\b|\bcitation\b", lowered):
            return "cite", 0.85

        # Obligations / how-to-comply questions.
        if re.search(
            r"\b(how do i|how to|what do i need to do|what are my obligations|requirements|steps to comply)\b",
            lowered,
        ):
            return "scope", 0.75

        # Fallback: if it mentions a regulation, assume define/explain intent.
        if any(_has_word(lowered, reg) for reg in _REGULATIONS):
            return "define", 0.6

        # Profile-aware fallback: EU tenants asking about AI are likely asking
        # about the EU AI Act even if they don't name it explicitly.
        jurisdictions = (profile or {}).get("jurisdictions") or []
        if _jurisdiction_includes(jurisdictions, "eu") and any(
            t in lowered for t in ("ai", "artificial intelligence", "ai act")
        ):
            return "define", 0.55
        return "unknown", 0.4

    @staticmethod
    def _extract_entities(text: str, lowered: str) -> list[NluEntity]:
        entities: list[NluEntity] = []
        seen_spans: set[tuple[int, int]] = set()

        def _add(etype: str, value: str, start: int, end: int, confidence: float = 1.0) -> None:
            if (start, end) not in seen_spans:
                entities.append(NluEntity(etype, value, (start, end), confidence))
                seen_spans.add((start, end))

        # Regulations — longest first, with word boundaries.
        for reg in sorted(_REGULATIONS, key=len, reverse=True):
            for m in re.finditer(r"\b" + re.escape(reg) + r"\b", lowered):
                canonical = _REGULATION_CANONICAL.get(reg, reg)
                _add("regulation", canonical, m.start(), m.end())

        # Jurisdictions — longest first, with word boundaries.
        for jur in sorted(_JURISDICTIONS, key=len, reverse=True):
            for m in re.finditer(r"\b" + re.escape(jur) + r"\b", lowered):
                canonical = _JURISDICTION_CANONICAL.get(jur, jur)
                _add("jurisdiction", canonical, m.start(), m.end())

        # System types (whole-phrase matching)
        for hint in sorted(_SYSTEM_TYPE_HINTS, key=len, reverse=True):
            for m in re.finditer(r"\b" + re.escape(hint) + r"\b", lowered):
                canonical = _SYSTEM_TYPE_CANONICAL.get(hint, hint)
                _add("system_type", canonical, m.start(), m.end())

        # Data types (whole-phrase matching)
        for hint in sorted(_DATA_TYPE_HINTS, key=len, reverse=True):
            for m in re.finditer(r"\b" + re.escape(hint) + r"\b", lowered):
                canonical = _DATA_TYPE_CANONICAL.get(hint, hint)
                _add("data_type", canonical, m.start(), m.end())

        # Task / artefact types (whole-phrase matching)
        for hint in sorted(_TASK_TYPE_HINTS, key=len, reverse=True):
            for m in re.finditer(r"\b" + re.escape(hint) + r"\b", lowered):
                canonical = _TASK_TYPE_CANONICAL.get(hint, hint)
                _add("task_type", canonical, m.start(), m.end())

        # Risk level
        for hint in sorted(_RISK_LEVEL_HINTS, key=len, reverse=True):
            for m in re.finditer(re.escape(hint), lowered):
                _add("risk_level", hint, m.start(), m.end(), 0.8)

        # Roles
        for hint in sorted(_ROLE_HINTS, key=len, reverse=True):
            for m in re.finditer(r"\b" + re.escape(hint) + r"\b", lowered):
                _add("role", hint, m.start(), m.end(), 0.8)

        # Article / section / annex references (e.g., "Article 5", "Art. 6(1)(f)")
        for m in re.finditer(
            r"\b(article|art\.?|section|annex)\s*(\d+[a-z]?)(?:\s*\(([0-9a-z]+)\))?(?:\s*\(([0-9a-z]+)\))?",
            lowered,
            flags=re.IGNORECASE,
        ):
            ref = f"{m.group(1).lower()} {m.group(2)}"
            if m.group(3):
                ref += f"({m.group(3)})"
            if m.group(4):
                ref += f"({m.group(4)})"
            _add("article", ref, m.start(), m.end(), 0.9)

        # Deadlines: "by March 2025", "before 2026", "deadline is 31/12/2025"
        for m in re.finditer(
            r"\b(by|before|deadline|due)\s+((?:\d{1,2}[/.-])?\d{1,2}[/.-]?\d{2,4}|(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{4}|\d{4})\b",
            lowered,
        ):
            _add("deadline", m.group(2), m.start(2), m.end(2), 0.75)

        # Purpose: simple "for <purpose>", "to <verb>", or "<verb> candidates/users" capture
        purpose_patterns = [
            r"\bto\s+([a-z][a-z\s]*?(?:candidates|people|users|patients|customers))\b",
            r"\bfor\s+([a-z][a-z\s]*?(?:hiring|scoring|screening|recommendation|detection|processing))\b",
            r"\b((?:scores?|screen|screens|hire|hiring)\s+(?:candidates|people|users|patients|customers))\b",
        ]
        for pattern in purpose_patterns:
            for m in re.finditer(pattern, lowered):
                val = (m.group(1) or "").strip()
                if len(val) > 2:
                    # Normalise verbs to a gerund form for slot consistency.
                    val = val.replace("scores ", "scoring ").replace("score ", "scoring ")
                    val = val.replace("screens ", "screening ").replace("screen ", "screening ")
                    val = val.replace("hires ", "hiring ").replace("hire ", "hiring ")
                    _add("purpose", val, m.start(1), m.end(1), 0.7)

        return entities

    @staticmethod
    def _repair_coreference(
        text: str,
        lowered: str,
        last_entities: list[NluEntity],
    ) -> str:
        """Resolve simple ellipsis/coreference using the last-mentioned entity."""
        if not last_entities:
            return text

        # If the input is just a pronoun/fragment, prepend the last entity.
        fragments = {"it", "they", "them", "this", "that", "yes", "no", "maybe"}
        stripped = lowered.strip(".!? ")
        is_continuation = any(
            stripped.startswith(p) for p in ("it ", "they ", "them ", "this ", "that ")
        )
        if stripped in fragments or len(stripped.split()) <= 2 or is_continuation:
            last = last_entities[-1]
            # Only repair if the fragment doesn't already contain the entity.
            if last.value.lower() not in lowered:
                return f"{last.type} = {last.value}: {text}"
        return text

    @staticmethod
    def _sentiment(lowered: str) -> tuple[str, float]:
        neg = sum(1 for w in _SENTIMENT_NEGATIVE if w in lowered)
        pos = sum(1 for w in _SENTIMENT_POSITIVE if w in lowered)
        score = (pos - neg) * 0.25
        score = max(-1.0, min(1.0, score))
        if score <= -0.25:
            return "negative", score
        if score >= 0.25:
            return "positive", score
        return "neutral", score

    @staticmethod
    def _entities_to_slots(entities: list[NluEntity]) -> dict[str, Any]:
        slots: dict[str, Any] = {}
        for e in entities:
            key = {
                "regulation": "regulation",
                "jurisdiction": "jurisdiction",
                "system_type": "system_type",
                "data_type": "data_type",
                "purpose": "purpose",
                "task_type": "task_type",
                "risk_level": "risk_level",
                "article": "article",
                "deadline": "deadline",
                "role": "role",
            }.get(e.type)
            if key and not slots.get(key):
                slots[key] = e.value
        return slots
