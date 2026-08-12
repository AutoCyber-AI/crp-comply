"""LoopState FSM + Planner \u2014 PHASE_7 \u00a73.2 + \u00a721 7.3.

The reasoning loop is a strict state machine. Every transition is
declared up-front; anything else raises :class:`LoopStateError`. The
machine is deterministic, single-threaded per session, and emits
events through a caller-supplied sink so the orchestrator stays in
charge of SSE serialisation.

States (PHASE_7 \u00a73.2)
---------------------

* ``PLANNING``     \u2014 first LLM call; emits a structured plan.
* ``STEP``         \u2014 choose next not-done step.
* ``ACTING``       \u2014 ReAct-style tool dispatch.
* ``REFLECT``      \u2014 critique LLM call; can revise the plan.
* ``AWAITING_USER`` \u2014 ``ask_user`` tool fired; suspend.
* ``FINALISE``     \u2014 run recipes, write artefacts, emit ``loop.final``.
* ``DONE``         \u2014 terminal.
* ``ERROR``        \u2014 terminal failure.

The legal transition table is the only thing the FSM enforces; the
*business* of choosing which step to run, what the planner returns,
and which reflector verdict applies all live in 7.4 / 7.6.

Bypass guards (PHASE_7 \u00a721 7.3)
-------------------------------

* Free-form state strings cannot be passed in: ``LoopStateName`` is
  an :class:`enum.Enum`, the FSM stores it as such, and the public
  API only accepts the enum.
* Lane B (fast path) does **not** skip the FSM. It runs a degenerate
  ``PLANNING(should_loop=False) \u2192 STEP \u2192 ACTING \u2192 REFLECT \u2192
  FINALISE \u2192 DONE`` so the same SSE event taxonomy fires.
* The planner may not emit zero steps. :func:`Planner.normalise_plan`
  raises if ``steps == []``.
* Plan revision is bounded by ``max_plan_revisions`` (default 3,
  PHASE_7 \u00a713) and tracked on the FSM instance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Literal

from .triage import TriageResult


# ── Research phase taxonomy (Round 10) ────────────────────────────────────


class Phase(str, Enum):
    """Explicit reasoning phases for complex compliance tasks."""

    RESEARCH = "RESEARCH"
    ANALYSIS = "ANALYSIS"
    SYNTHESIS = "SYNTHESIS"
    CITATION = "CITATION"
    REVIEW = "REVIEW"


__all__ = [
    "LoopStateName",
    "LoopState",
    "LoopStateError",
    "Plan",
    "PlanStep",
    "Planner",
    "default_should_loop_for",
    "VALID_TRANSITIONS",
]


# ── State enum + transition table ─────────────────────────────────────


class LoopStateName(str, Enum):
    PLANNING = "PLANNING"
    STEP = "STEP"
    ACTING = "ACTING"
    REFLECT = "REFLECT"
    AWAITING_USER = "AWAITING_USER"
    FINALISE = "FINALISE"
    DONE = "DONE"
    ERROR = "ERROR"


# Adjacency list of legal forward transitions. Anything not listed
# is rejected. ``ERROR`` is reachable from every non-terminal state
# (a tool blew up, an LLM call failed, etc.).
VALID_TRANSITIONS: dict[LoopStateName, frozenset[LoopStateName]] = {
    LoopStateName.PLANNING: frozenset(
        {
            LoopStateName.STEP,
            LoopStateName.FINALISE,  # degenerate Lane B may finalise straight away
            LoopStateName.ERROR,
        }
    ),
    LoopStateName.STEP: frozenset(
        {
            LoopStateName.ACTING,
            LoopStateName.FINALISE,  # all steps done
            LoopStateName.ERROR,
        }
    ),
    LoopStateName.ACTING: frozenset(
        {
            LoopStateName.REFLECT,
            LoopStateName.AWAITING_USER,
            LoopStateName.ERROR,
        }
    ),
    LoopStateName.REFLECT: frozenset(
        {
            LoopStateName.STEP,  # loop again
            LoopStateName.PLANNING,  # revise_plan
            LoopStateName.AWAITING_USER,  # clarify_first
            LoopStateName.FINALISE,  # done
            LoopStateName.ERROR,  # abort
        }
    ),
    LoopStateName.AWAITING_USER: frozenset(
        {
            LoopStateName.ACTING,  # resume the same step with the answer
            LoopStateName.ERROR,
        }
    ),
    LoopStateName.FINALISE: frozenset(
        {
            LoopStateName.DONE,
            LoopStateName.ERROR,
        }
    ),
    LoopStateName.DONE: frozenset(),
    LoopStateName.ERROR: frozenset(),
}


class LoopStateError(RuntimeError):
    """Raised on an illegal transition or a contract violation."""


# ── Plan + Plan step types ────────────────────────────────────────────


_VALID_TOOL_HINTS = {
    None,
    "pattern_query",
    "graph_walk",
    "community_summary",
    "temporal_query",
    "recall_facts",
    "semantic",
    "rag_search",
    "web_search",
    "run_recipe",
    "ask_user",
}


@dataclass(frozen=True)
class PlanStep:
    """One step of a plan.

    ``id`` is opaque but must be unique within a plan. ``tool_hint``
    is a *hint*, not a contract; the model may pick a different tool
    at ACTING time, but only one in the registered set (PHASE_7 \u00a721
    7.4 enforces that).

    ``phase`` (Round 10) tags the step with a research-phase so the
    runtime can emit ``loop.phase.complete`` and the Reflector can
    judge phase-level outcomes.
    """

    id: str
    intent: str
    tool_hint: str | None = None
    success_predicate: str | None = None
    phase: Phase | None = None


@dataclass(frozen=True)
class Plan:
    """The structured planner output.

    ``should_loop`` toggles between Lane B (single-shot, ``False``)
    and Lane C (multi-step, ``True``). Both lanes still run through
    the FSM \u2014 see PHASE_7 \u00a721 7.3 ("Do not skip the FSM in 'fast'
    code paths").
    """

    steps: tuple[PlanStep, ...]
    should_loop: bool = True

    def to_event_payload(self) -> dict[str, Any]:
        """Shape for ``loop.plan`` (see :class:`api.events.PlanPayload`)."""
        return {
            "steps": [
                {
                    "id": s.id,
                    "intent": s.intent,
                    "tool_hint": s.tool_hint,
                    "phase": s.phase.value if s.phase else None,
                }
                for s in self.steps
            ],
            "should_loop": self.should_loop,
        }


# ── Planner ───────────────────────────────────────────────────────────


def default_should_loop_for(triage: TriageResult) -> bool:
    """Lane decision per PHASE_7 \u00a714.3.

    Returns ``False`` (Lane B fast path) for trivial/simple intents
    where one tool call is enough; ``True`` for everything else.
    """
    if triage.lane == "fast":
        return False
    return True


# Type alias: a "plan generator" is anything callable that takes
# ``(query, triage)`` and returns a Plan. The orchestrator can wire
# in an LLM-backed planner in 7.4; tests use a stub.
PlanGenerator = Callable[[str, TriageResult], Plan]


@dataclass
class Planner:
    """Wraps a plan generator and enforces the planner contract.

    The contract:

    * Exactly one plan per call (no streaming partials).
    * Plans MUST have at least one step (PHASE_7 \u00a721 7.3).
    * ``tool_hint`` MUST be one of the known tools or ``None``.
    * ``should_loop`` is a real boolean.

    The default generator is a heuristic stub used by tests and as
    the fallback when no LLM is available; production wiring lives in
    7.4.
    """

    generate: PlanGenerator | None = None

    def plan(self, query: str, triage: TriageResult) -> Plan:
        gen = self.generate or _heuristic_plan
        plan = gen(query, triage)
        return self.normalise_plan(plan)

    @staticmethod
    def normalise_plan(plan: Plan) -> Plan:
        """Validate + canonicalise a plan; raise on violation."""
        if not isinstance(plan, Plan):
            raise LoopStateError(f"planner returned {type(plan).__name__}, expected Plan")
        if not plan.steps:
            raise LoopStateError(
                "planner emitted zero steps; minimum is one (PHASE_7 \u00a721 7.3)"
            )
        seen: set[str] = set()
        for s in plan.steps:
            if not s.id or not s.intent:
                raise LoopStateError(f"plan step missing id/intent: {s!r}")
            if s.id in seen:
                raise LoopStateError(f"duplicate step id: {s.id!r}")
            seen.add(s.id)
            if s.tool_hint not in _VALID_TOOL_HINTS:
                raise LoopStateError(f"step {s.id!r} has unknown tool_hint {s.tool_hint!r}")
        if not isinstance(plan.should_loop, bool):
            raise LoopStateError(f"should_loop must be bool, got {type(plan.should_loop).__name__}")
        return plan


def _heuristic_plan(query: str, triage: TriageResult) -> Plan:
    """Fallback plan generator (no LLM).

    Picks a tool hint from the triage intent and emits one step for
    Lane B, two for Lane C (recall + answer). Good enough for tests
    and for environments without an LLM configured.
    """
    intent = triage.intent
    should_loop = default_should_loop_for(triage)
    hint_for_intent = {
        "cite": "pattern_query",
        "define": "pattern_query",
        "scope": "graph_walk",
        "compare": "graph_walk",
        "produce_artefact": "run_recipe",
        "audit_existing": "graph_walk",
    }
    primary = hint_for_intent.get(intent, "pattern_query")
    if not should_loop:
        return Plan(
            steps=(
                PlanStep(
                    id="s1",
                    intent=f"{intent}: {query[:60]}",
                    tool_hint=primary,
                ),
            ),
            should_loop=False,
        )
    return Plan(
        steps=(
            PlanStep(
                id="s1",
                intent="recall relevant facts",
                tool_hint="recall_facts",
            ),
            PlanStep(
                id="s2",
                intent=f"{intent}: {query[:60]}",
                tool_hint=primary,
            ),
        ),
        should_loop=True,
    )


# ── LoopState FSM ─────────────────────────────────────────────────────


_ReflectVerdict = Literal["ok", "retry", "revise_plan", "clarify_first", "abort"]


@dataclass
class LoopState:
    """In-memory FSM for one reasoning loop run.

    Construct one per session; persist (sqlite) when entering
    ``AWAITING_USER`` (that's 7.5).

    All mutating methods go through :meth:`transition`; nothing else
    touches ``self.state`` directly.
    """

    session_id: str
    run_id: str
    state: LoopStateName = LoopStateName.PLANNING
    plan: Plan | None = None
    current_step_index: int = 0
    plan_revisions: int = 0
    max_plan_revisions: int = 3
    clarifier_count: int = 0
    max_clarifiers: int = 6
    history: list[tuple[LoopStateName, LoopStateName, str]] = field(default_factory=list)

    # -- FSM core -------------------------------------------------

    def transition(self, new_state: LoopStateName, *, reason: str = "") -> None:
        """Move to *new_state* or raise :class:`LoopStateError`."""
        if not isinstance(new_state, LoopStateName):
            raise LoopStateError(
                f"new_state must be a LoopStateName, got {type(new_state).__name__}"
            )
        allowed = VALID_TRANSITIONS.get(self.state, frozenset())
        if new_state not in allowed:
            raise LoopStateError(
                f"illegal transition {self.state.value} \u2192 {new_state.value}"
                f" (allowed: {sorted(s.value for s in allowed)})"
            )
        self.history.append((self.state, new_state, reason))
        self.state = new_state

    # -- Convenience wrappers used by the orchestrator -----------

    def set_plan(self, plan: Plan) -> None:
        """Attach a normalised plan (call after Planner.normalise_plan)."""
        if self.state is not LoopStateName.PLANNING:
            raise LoopStateError(f"cannot set plan from {self.state.value}; expected PLANNING")
        self.plan = plan
        self.current_step_index = 0

    def revise_plan(self, plan: Plan) -> None:
        """Replace the plan during REFLECT (counts toward the budget)."""
        if self.state is not LoopStateName.REFLECT:
            raise LoopStateError(f"cannot revise plan from {self.state.value}; expected REFLECT")
        self.plan_revisions += 1
        if self.plan_revisions > self.max_plan_revisions:
            raise LoopStateError(f"plan revision budget exhausted ({self.max_plan_revisions})")
        self.plan = plan
        # Resume execution at whatever the new plan calls "step 0".
        self.current_step_index = 0

    def advance_step(self) -> None:
        """Increment the cursor; raise if it overshoots the plan."""
        if self.plan is None:
            raise LoopStateError("cannot advance: no plan attached")
        self.current_step_index += 1

    def current_step(self) -> PlanStep | None:
        if self.plan is None:
            return None
        if 0 <= self.current_step_index < len(self.plan.steps):
            return self.plan.steps[self.current_step_index]
        return None

    def has_more_steps(self) -> bool:
        return self.current_step() is not None

    def record_clarifier(self) -> None:
        """Bump the clarifier counter (PHASE_7 \u00a713: budget = 6/loop)."""
        self.clarifier_count += 1
        if self.clarifier_count > self.max_clarifiers:
            raise LoopStateError(f"clarifier budget exhausted ({self.max_clarifiers})")

    # -- Reflector verdict \u2192 next state mapping --------------------

    def apply_reflector_verdict(self, verdict: _ReflectVerdict) -> LoopStateName:
        """Translate a reflector verdict into the FSM transition.

        This is a pure mapping; it does not itself transition. Callers
        are expected to:

            target = state.apply_reflector_verdict("ok")
            state.transition(target, reason="reflector:ok")
        """
        if verdict == "ok":
            # If there are more steps, loop; else finalise.
            return (
                LoopStateName.STEP
                if self._has_unfinished_after_current()
                else LoopStateName.FINALISE
            )
        if verdict == "retry":
            return LoopStateName.STEP  # same step, new attempt
        if verdict == "revise_plan":
            return LoopStateName.PLANNING
        if verdict == "clarify_first":
            return LoopStateName.AWAITING_USER
        if verdict == "abort":
            return LoopStateName.ERROR
        raise LoopStateError(f"unknown reflector verdict: {verdict!r}")

    def _has_unfinished_after_current(self) -> bool:
        if self.plan is None:
            return False
        return (self.current_step_index + 1) < len(self.plan.steps)

    # -- Telemetry --------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Serialise the FSM for AWAITING_USER persistence (7.5)."""
        return {
            "session_id": self.session_id,
            "run_id": self.run_id,
            "state": self.state.value,
            "current_step_index": self.current_step_index,
            "plan_revisions": self.plan_revisions,
            "clarifier_count": self.clarifier_count,
            "plan": (self.plan.to_event_payload() if self.plan is not None else None),
        }
