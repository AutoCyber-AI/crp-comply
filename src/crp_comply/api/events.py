"""Typed event taxonomy for the language-agent reasoning loop.

This module is the **single source of truth** for the SSE event surface
the loop emits to the frontend reasoning tape. Every event the agent
publishes via ``event_sink`` MUST appear in :class:`LoopEvent` and MUST
validate against its corresponding :class:`pydantic.BaseModel` payload
schema.

The 22 events are sourced from PHASE_7_LANGUAGE_AGENT_LOOP.md sections
§3.3 (the original 16) and §19 (the 6 added during the fast-path /
CKF-integration / web-search expansion):

    Original 16 (§3.3)          Added in §19 (fast-path / web)
    ────────────────────        ──────────────────────────────
    loop.opened                  loop.triage
    loop.plan                    loop.cache.hit
    loop.step.start              loop.cache.miss
    loop.thought.delta           loop.web.start
    loop.tool.call               loop.web.result
    loop.tool.result             loop.ckf.query
    loop.reflection
    loop.clarifier.ask
    loop.clarifier.answer
    loop.step.end
    loop.recipe.start
    loop.recipe.delta
    loop.recipe.done
    loop.final
    loop.error
    loop.heartbeat

Why a typed registry?

* **Audit trail.** Every event written to ``data/telemetry/loop_runs/``
  is parsed back during a /replay. Free-form event names break replay.
* **No-bypass guarantee** (PHASE_7 §21 7.0). The reviewer rejects any
  PR that emits a ``loop.*`` event not present in :class:`LoopEvent`.
* **Frontend dispatch.** The React reasoning tape switches on the
  literal event name; an undeclared event is a UI dead-letter.

This module is dependency-light on purpose: it imports only ``enum``
and ``pydantic`` so it can be loaded everywhere (orchestrator, API,
sidecars) without dragging the ML stack along.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


# ---------------------------------------------------------------------------
# Event name registry
# ---------------------------------------------------------------------------


class LoopEvent(str, Enum):
    """Every typed event the language-agent loop may emit.

    Order is the order they appear in PHASE_7 §3.3 and §19.
    """

    # ── §3.3 — original 16 ───────────────────────────────────────────
    OPENED = "loop.opened"
    PLAN = "loop.plan"
    STEP_START = "loop.step.start"
    THOUGHT_DELTA = "loop.thought.delta"
    TOOL_CALL = "loop.tool.call"
    TOOL_RESULT = "loop.tool.result"
    REFLECTION = "loop.reflection"
    CLARIFIER_ASK = "loop.clarifier.ask"
    CLARIFIER_ANSWER = "loop.clarifier.answer"
    STEP_END = "loop.step.end"
    RECIPE_START = "loop.recipe.start"
    RECIPE_DELTA = "loop.recipe.delta"
    RECIPE_DONE = "loop.recipe.done"
    FINAL = "loop.final"
    ERROR = "loop.error"
    HEARTBEAT = "loop.heartbeat"

    # ── §19 — added for fast-path / CKF / web search ────────────────
    TRIAGE = "loop.triage"
    CACHE_HIT = "loop.cache.hit"
    CACHE_MISS = "loop.cache.miss"
    WEB_START = "loop.web.start"
    WEB_RESULT = "loop.web.result"
    CKF_QUERY = "loop.ckf.query"
    # ── 7.12 — budget abort ──────────────────────────────────────
    ABORT = "loop.abort"
    # ── 7.15 — intelligent web search (query expansion / rerank / cite) ──
    WEB_EXPAND = "loop.web.expand"
    WEB_RERANK = "loop.web.rerank"
    WEB_CITE = "loop.web.cite"
    # ── CRP compliance — PII in pipeline warning ─────────────────────
    PII_WARNING = "loop.pii_warning"
    # ── Round 8 — citation validation ────────────────────────────────
    CITATION_INVALID = "loop.citation.invalid"
    # ── Round 10 — research phases ───────────────────────────────────
    PHASE_COMPLETE = "loop.phase.complete"


# Convenience export: the literal type the validator expects.
LoopEventLiteral = Literal[
    "loop.opened",
    "loop.plan",
    "loop.step.start",
    "loop.thought.delta",
    "loop.tool.call",
    "loop.tool.result",
    "loop.reflection",
    "loop.clarifier.ask",
    "loop.clarifier.answer",
    "loop.step.end",
    "loop.recipe.start",
    "loop.recipe.delta",
    "loop.recipe.done",
    "loop.final",
    "loop.error",
    "loop.heartbeat",
    "loop.triage",
    "loop.cache.hit",
    "loop.cache.miss",
    "loop.web.start",
    "loop.web.result",
    "loop.ckf.query",
    "loop.abort",
    "loop.web.expand",
    "loop.web.rerank",
    "loop.web.cite",
    "loop.pii_warning",
    "loop.citation.invalid",
    "loop.phase.complete",
]


# ---------------------------------------------------------------------------
# Payload schemas
# ---------------------------------------------------------------------------


class _Base(BaseModel):
    """Base for every loop-event payload.

    ``ts`` is a server-generated UNIX timestamp. ``run_id`` ties the
    event to a single loop run (and to the on-disk replay log at
    ``data/telemetry/loop_runs/{run_id}.jsonl``).

    ``model_config`` is permissive on extras during the 7.0 → 7.12
    rollout: the reviewer wants to allow add-only fields per sub-phase
    without breaking existing emitters. The presence of *unknown*
    fields is logged but not rejected. The presence of an unknown
    *event name* is always rejected (see :func:`validate_event`).
    """

    model_config = ConfigDict(extra="allow")

    ts: float = Field(default_factory=lambda: time.time())
    run_id: str = Field(default="")


class OpenedPayload(_Base):
    session_id: str
    query: str
    model: str = ""


class PlanStep(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    intent: str
    tool_hint: str | None = None


class PlanPayload(_Base):
    steps: list[PlanStep]
    should_loop: bool = True


class StepStartPayload(_Base):
    step_id: str
    intent: str
    attempt: int = 1


class ThoughtDeltaPayload(_Base):
    step_id: str
    text: str


class ToolCallPayload(_Base):
    step_id: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)


class ToolResultPayload(_Base):
    step_id: str
    tool: str
    summary: str = ""
    citations: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class ReflectionPayload(_Base):
    step_id: str
    verdict: Literal["ok", "retry", "revise_plan", "clarify_first", "abort"]
    notes: str = ""
    plan_delta: dict[str, Any] | None = None


class ClarifierAskPayload(_Base):
    step_id: str
    question: str
    slot_id: str
    options: list[str] | None = None
    resume_token: str | None = None


class ClarifierAnswerPayload(_Base):
    slot_id: str
    answer: str


class StepEndPayload(_Base):
    step_id: str
    status: Literal["ok", "skipped", "failed"]


class RecipeStartPayload(_Base):
    recipe_id: str
    inputs: dict[str, Any] = Field(default_factory=dict)


class RecipeDeltaPayload(_Base):
    recipe_id: str
    kind: str
    text: str = ""


class RecipeDonePayload(_Base):
    recipe_id: str
    artefact_id: str


class FinalPayload(_Base):
    artefacts: list[dict[str, Any]] = Field(default_factory=list)
    summary: str = ""
    total_steps: int = 0


class ErrorPayload(_Base):
    message: str
    step_id: str | None = None


class HeartbeatPayload(_Base):
    state: str = "idle"


# Fast-path / CKF / web (§19) ------------------------------------------------


TriageLane = Literal["cache", "fast", "slow"]
TriageComplexity = Literal["trivial", "simple", "moderate", "complex", "comprehensive"]


class TriagePayload(_Base):
    complexity: TriageComplexity
    intent: str
    confidence: float = Field(ge=0.0, le=1.0)
    lane: TriageLane
    reasoning: str = ""


CacheKeyKind = Literal["exact", "semantic", "plan"]


class CacheHitPayload(_Base):
    key_kind: CacheKeyKind
    similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    age_seconds: float = 0.0
    citations: list[dict[str, Any]] = Field(default_factory=list)


class CacheMissPayload(_Base):
    key_kind: CacheKeyKind
    lookup_ms: float = 0.0


WebBackend = Literal["local", "brave", "tavily", "searxng"]
WebIntent = Literal[
    "regulation_text",
    "case_law",
    "guidance",
    "enforcement",
    "news",
    "vendor",
    "general",
]


class WebStartPayload(_Base):
    query: str
    backend: WebBackend
    profile: str | None = None  # trust-tier YAML profile (or Brave Goggle id)
    freshness: Literal["any", "day", "week", "month"] = "any"


class WebResultHit(BaseModel):
    model_config = ConfigDict(extra="allow")
    domain: str
    trust_tier: int = Field(ge=1, le=4)
    url: str = ""
    title: str = ""
    blocked: bool = False


class WebResultPayload(_Base):
    backend: WebBackend
    hits: list[WebResultHit] = Field(default_factory=list)
    blocked: int = 0
    latency_ms: float = 0.0
    quota_remaining: int | None = None


CKFMode = Literal[
    "pattern_query", "graph_walk", "community_summary", "temporal_query", "recall_facts", "semantic"
]
CKFScope = Literal["corpus", "tenant", "federated"]


class CKFQueryPayload(_Base):
    mode: CKFMode
    scope: CKFScope
    hits: int = 0
    top_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


# 7.12 — budget abort -------------------------------------------------------


AbortDimension = Literal[
    "steps",
    "tokens",
    "wall_clock",
    "clarifiers",
    "plan_revisions",
]


class AbortPayload(_Base):
    """Emitted exactly once when the loop hits a budget ceiling.

    Carries the breached dimension, the configured limit, and the
    actual usage so the UI can show a precise "stopped because…"
    banner. ``budget`` and ``totals`` are the full server-side
    config + usage snapshot for ops dashboards.
    """

    reason: Literal["budget_exceeded"] = "budget_exceeded"
    dimension: AbortDimension
    limit: float
    usage: float
    detail: str | None = None
    budget: dict[str, float] = Field(default_factory=dict)
    totals: dict[str, float] = Field(default_factory=dict)


# 7.15 — intelligent web search ----------------------------------------------


class WebExpandPayload(_Base):
    """LLM-driven sub-query fan-out."""

    goal: str
    intent: WebIntent = "general"
    sub_queries: list[str] = Field(default_factory=list)
    strategy: str = ""


class WebRerankPayload(_Base):
    """Cross-encoder rerank applied to candidate hits."""

    model: str
    candidates_in: int = 0
    candidates_out: int = 0
    latency_ms: float = 0.0


class WebCitePayload(_Base):
    """One chunk-and-cite binding (one chunk → one citation_id)."""

    citation_id: str
    source_id: str
    chunk_index: int = 0
    score: float = 0.0
    excerpt: str = ""


# CRP PII warning ---------------------------------------------------------


class PiiWarningPayload(_Base):
    """Emitted when PIIScanner detects personal-data categories in the pipeline.

    ``step_id`` ties the warning to the running agent step (may be empty
    if emitted outside a step context). ``categories`` is the list of PII
    labels detected (e.g. ``["email", "phone"]``). ``source`` identifies
    the pipeline stage: ``"intermediate_scan"`` (orchestrator), ``"ws_response"
    (WebSocket worker relay), etc.
    """

    step_id: str = ""
    categories: list[str] = Field(default_factory=list)
    source: str = ""
    iter: int | None = None


# Round 8 — citation validation ------------------------------------------------


class CitationInvalidPayload(_Base):
    """Emitted when the final answer contains citation markers that do not
    reference any tool-returned source in the current session.

    ``invalid_ids`` lists the rejected markers; ``valid_ids`` lists the
    markers that were resolved; ``surrogate_ids`` lists resolved markers
    that came from surrogate chunks. ``stripped`` is True when the runtime
    has already removed the invalid markers from the streamed answer.
    """

    step_id: str = "final"
    invalid_ids: list[str] = Field(default_factory=list)
    valid_ids: list[str] = Field(default_factory=list)
    surrogate_ids: list[str] = Field(default_factory=list)
    stripped: bool = False


class PhaseCompletePayload(_Base):
    """Emitted when all steps of a research phase have finished."""

    phase: str
    step_ids: list[str] = Field(default_factory=list)
    facts_gathered: int = 0
    citations_count: int = 0
    notes: str = ""


# ---------------------------------------------------------------------------
# Event → payload schema mapping
# ---------------------------------------------------------------------------


PAYLOAD_SCHEMA: dict[LoopEvent, type[_Base]] = {
    LoopEvent.OPENED: OpenedPayload,
    LoopEvent.PLAN: PlanPayload,
    LoopEvent.STEP_START: StepStartPayload,
    LoopEvent.THOUGHT_DELTA: ThoughtDeltaPayload,
    LoopEvent.TOOL_CALL: ToolCallPayload,
    LoopEvent.TOOL_RESULT: ToolResultPayload,
    LoopEvent.REFLECTION: ReflectionPayload,
    LoopEvent.CLARIFIER_ASK: ClarifierAskPayload,
    LoopEvent.CLARIFIER_ANSWER: ClarifierAnswerPayload,
    LoopEvent.STEP_END: StepEndPayload,
    LoopEvent.RECIPE_START: RecipeStartPayload,
    LoopEvent.RECIPE_DELTA: RecipeDeltaPayload,
    LoopEvent.RECIPE_DONE: RecipeDonePayload,
    LoopEvent.FINAL: FinalPayload,
    LoopEvent.ERROR: ErrorPayload,
    LoopEvent.HEARTBEAT: HeartbeatPayload,
    LoopEvent.TRIAGE: TriagePayload,
    LoopEvent.CACHE_HIT: CacheHitPayload,
    LoopEvent.CACHE_MISS: CacheMissPayload,
    LoopEvent.WEB_START: WebStartPayload,
    LoopEvent.WEB_RESULT: WebResultPayload,
    LoopEvent.CKF_QUERY: CKFQueryPayload,
    LoopEvent.ABORT: AbortPayload,
    LoopEvent.WEB_EXPAND: WebExpandPayload,
    LoopEvent.WEB_RERANK: WebRerankPayload,
    LoopEvent.WEB_CITE: WebCitePayload,
    LoopEvent.PII_WARNING: PiiWarningPayload,
    LoopEvent.CITATION_INVALID: CitationInvalidPayload,
    LoopEvent.PHASE_COMPLETE: PhaseCompletePayload,
}


assert set(PAYLOAD_SCHEMA.keys()) == set(LoopEvent), (
    "PAYLOAD_SCHEMA must cover every LoopEvent member"
)


ALL_EVENT_NAMES: frozenset[str] = frozenset(e.value for e in LoopEvent)


# ---------------------------------------------------------------------------
# Validation + emission helpers
# ---------------------------------------------------------------------------


class LoopEventError(ValueError):
    """Raised when an event fails the typed-registry contract."""


def is_loop_event(name: str) -> bool:
    """Return True if *name* is one of the 22 typed loop events.

    Useful for the SSE bridge so it only validates ``loop.*`` events
    and lets legacy event names (``tool_call``, ``llm_turn``, etc.)
    pass through unchanged during the 7.0 → 7.4 transition.
    """
    return name in ALL_EVENT_NAMES


def validate_event(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate a single event against :data:`PAYLOAD_SCHEMA`.

    Returns the *validated* payload as a plain dict (with defaults
    populated). Raises :class:`LoopEventError` on contract violation.

    The contract is:

    * ``name`` MUST be a member of :class:`LoopEvent`.
    * ``payload`` MUST validate against the schema in
      :data:`PAYLOAD_SCHEMA` for that event.
    * Extra keys are allowed (forward-compat).
    """
    try:
        evt = LoopEvent(name)
    except ValueError as exc:
        raise LoopEventError(
            f"unknown loop event {name!r} \u2014 add it to LoopEvent in "
            "src/crp_comply/api/events.py"
        ) from exc
    schema = PAYLOAD_SCHEMA[evt]
    try:
        model = schema.model_validate(payload)
    except ValidationError as exc:
        raise LoopEventError(
            f"event {name!r} payload failed schema {schema.__name__}: {exc}"
        ) from exc
    return model.model_dump(mode="json")


def make_event(
    name: str | LoopEvent,
    payload: dict[str, Any] | None = None,
    *,
    run_id: str = "",
) -> dict[str, Any]:
    """Build a *validated* event dict suitable for ``event_sink``.

    Returns a dict shaped like::

        {"event": "loop.tool.call", "ts": 1714849200.123,
         "run_id": "abc", "step_id": "s1", "tool": "...", ...}

    The orchestrator should always go through this constructor when
    emitting ``loop.*`` events so that the reviewer's no-bypass rule
    in PHASE_7 §21 7.0 holds.
    """
    if isinstance(name, LoopEvent):
        ename = name.value
    else:
        ename = name
    raw = dict(payload or {})
    if run_id and "run_id" not in raw:
        raw["run_id"] = run_id
    validated = validate_event(ename, raw)
    validated["event"] = ename
    return validated


__all__ = [
    "ALL_EVENT_NAMES",
    "CKFMode",
    "CKFQueryPayload",
    "CKFScope",
    "CacheHitPayload",
    "CacheKeyKind",
    "CacheMissPayload",
    "ClarifierAnswerPayload",
    "ClarifierAskPayload",
    "ErrorPayload",
    "FinalPayload",
    "HeartbeatPayload",
    "LoopEvent",
    "LoopEventError",
    "LoopEventLiteral",
    "OpenedPayload",
    "PAYLOAD_SCHEMA",
    "PiiWarningPayload",
    "PlanPayload",
    "PlanStep",
    "RecipeDeltaPayload",
    "RecipeDonePayload",
    "RecipeStartPayload",
    "ReflectionPayload",
    "StepEndPayload",
    "StepStartPayload",
    "ThoughtDeltaPayload",
    "ToolCallPayload",
    "ToolResultPayload",
    "TriageComplexity",
    "TriageLane",
    "TriagePayload",
    "WebBackend",
    "WebResultHit",
    "WebResultPayload",
    "WebStartPayload",
    "is_loop_event",
    "make_event",
    "validate_event",
]
