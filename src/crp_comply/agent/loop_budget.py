"""Loop budgets — PHASE_7 §13 + §21 7.12.

The reasoning loop is bounded along five orthogonal dimensions:

* ``max_steps``           — total step executions in one run.
* ``max_tokens``          — cumulative LLM I/O budget.
* ``max_wall_clock_s``    — real time elapsed since :class:`LoopBudgetMeter`
                            was constructed.
* ``max_clarifiers``      — ``ask_user`` invocations (also bounded by the
                            FSM in :class:`crp_comply.agent.loop_state.LoopState`).
* ``max_plan_revisions``  — planner re-invocations during ``REFLECT``
                            (also enforced in the FSM).

Exceeding **any** ceiling raises :class:`BudgetExceeded`. The
orchestrator catches this, transitions the FSM to ``ERROR``, and
emits ``loop.abort`` carrying a structured reason. Budgets are
**server-side configuration only** — clients cannot raise them via
request parameters (PHASE_7 §21 7.12 "no bypass").

The defaults match §13:

============  ==================
Ceiling       Default
------------  ------------------
steps         12
tokens        60 000
wall_clock    300 s (5 min)
clarifiers    6
plan_revs     3
============  ==================
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Literal


__all__ = [
    "BudgetDimension",
    "BudgetExceeded",
    "LoopBudget",
    "LoopBudgetMeter",
    "make_abort_payload",
]


# ── Dimension type ───────────────────────────────────────────────────


BudgetDimension = Literal[
    "steps",
    "tokens",
    "wall_clock",
    "clarifiers",
    "plan_revisions",
]


_ALL_DIMENSIONS: tuple[BudgetDimension, ...] = (
    "steps",
    "tokens",
    "wall_clock",
    "clarifiers",
    "plan_revisions",
)


# ── Errors ───────────────────────────────────────────────────────────


class BudgetExceeded(RuntimeError):
    """Raised when a budget ceiling is breached.

    The exception carries the offending *dimension*, the *limit*, and
    the *usage* that breached it. The orchestrator turns this into a
    ``loop.abort`` event via :func:`make_abort_payload`.
    """

    def __init__(
        self,
        dimension: BudgetDimension,
        *,
        limit: float,
        usage: float,
        message: str = "",
    ) -> None:
        self.dimension: BudgetDimension = dimension
        self.limit = limit
        self.usage = usage
        super().__init__(
            message or f"loop budget exceeded: {dimension} usage={usage} limit={limit}"
        )


# ── Config ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LoopBudget:
    """Static budget config. Frozen so it cannot be mutated mid-run.

    Constructed once per process via :meth:`from_env` (production)
    or by direct kwargs (tests). The dataclass is intentionally
    free of any "override from request" hook — the spec forbids
    client-side budget overrides.
    """

    max_steps: int = 12
    max_tokens: int = 60_000
    max_wall_clock_s: float = 300.0
    max_clarifiers: int = 6
    max_plan_revisions: int = 3

    def __post_init__(self) -> None:
        for name in (
            "max_steps",
            "max_tokens",
            "max_clarifiers",
            "max_plan_revisions",
        ):
            v = getattr(self, name)
            if not isinstance(v, int) or v <= 0:
                raise ValueError(f"{name} must be a positive int (got {v!r})")
        if not isinstance(self.max_wall_clock_s, (int, float)) or self.max_wall_clock_s <= 0:
            raise ValueError(
                f"max_wall_clock_s must be a positive number (got {self.max_wall_clock_s!r})"
            )

    @classmethod
    def from_env(cls, prefix: str = "CRP_COMPLY_LOOP_") -> "LoopBudget":
        """Read overrides from process env (admin / ops only).

        Recognised vars (all optional, integer/float):

        * ``CRP_COMPLY_LOOP_MAX_STEPS``
        * ``CRP_COMPLY_LOOP_MAX_TOKENS``
        * ``CRP_COMPLY_LOOP_MAX_WALL_CLOCK_S``
        * ``CRP_COMPLY_LOOP_MAX_CLARIFIERS``
        * ``CRP_COMPLY_LOOP_MAX_PLAN_REVISIONS``

        Anything missing or unparseable falls back to the §13
        default. Negative or zero values are rejected to prevent an
        operator from accidentally disabling a ceiling.
        """
        defaults = cls()
        kwargs: dict[str, Any] = {}
        for name, cast in (
            ("max_steps", int),
            ("max_tokens", int),
            ("max_wall_clock_s", float),
            ("max_clarifiers", int),
            ("max_plan_revisions", int),
        ):
            raw = os.environ.get(prefix + name.upper())
            if raw is None or raw == "":
                continue
            try:
                v = cast(raw)
            except (TypeError, ValueError):
                continue
            if v <= 0:
                continue
            kwargs[name] = v
        if not kwargs:
            return defaults
        return cls(**{**defaults.__dict__, **kwargs})

    def as_dict(self) -> dict[str, float]:
        return {
            "max_steps": self.max_steps,
            "max_tokens": self.max_tokens,
            "max_wall_clock_s": self.max_wall_clock_s,
            "max_clarifiers": self.max_clarifiers,
            "max_plan_revisions": self.max_plan_revisions,
        }


# ── Meter ────────────────────────────────────────────────────────────


@dataclass
class LoopBudgetMeter:
    """Mutable counters tied to a single loop run.

    Construct one per ``run_id``. All ``record_*`` methods raise
    :class:`BudgetExceeded` *after* incrementing if the new total
    crosses the ceiling — that means the breach is observable in
    :attr:`usage` and can be reported in the ``loop.abort`` event.

    The wall-clock dimension is checked on every ``record_*`` call
    via :meth:`_check_wall_clock` and additionally exposed as
    :meth:`check_wall_clock` for callers that want a passive probe
    between LLM turns (e.g. heartbeat ticks).
    """

    budget: LoopBudget = field(default_factory=LoopBudget)
    started_at: float = field(default_factory=time.monotonic)
    steps: int = 0
    tokens: int = 0
    clarifiers: int = 0
    plan_revisions: int = 0
    # Stamped when a breach occurs so callers can re-inspect after
    # catching the exception.
    breached: BudgetDimension | None = None

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_step(self, n: int = 1) -> None:
        self.steps += int(n)
        if self.steps > self.budget.max_steps:
            self._raise("steps", self.steps, self.budget.max_steps)
        self._check_wall_clock()

    def record_tokens(self, n: int) -> None:
        if n < 0:
            raise ValueError("token count must be non-negative")
        self.tokens += int(n)
        if self.tokens > self.budget.max_tokens:
            self._raise("tokens", self.tokens, self.budget.max_tokens)
        self._check_wall_clock()

    def record_clarifier(self, n: int = 1) -> None:
        self.clarifiers += int(n)
        if self.clarifiers > self.budget.max_clarifiers:
            self._raise("clarifiers", self.clarifiers, self.budget.max_clarifiers)
        self._check_wall_clock()

    def record_plan_revision(self, n: int = 1) -> None:
        self.plan_revisions += int(n)
        if self.plan_revisions > self.budget.max_plan_revisions:
            self._raise(
                "plan_revisions",
                self.plan_revisions,
                self.budget.max_plan_revisions,
            )
        self._check_wall_clock()

    # ------------------------------------------------------------------
    # Wall-clock
    # ------------------------------------------------------------------

    def elapsed_s(self) -> float:
        return max(0.0, time.monotonic() - self.started_at)

    def check_wall_clock(self) -> None:
        """Raise :class:`BudgetExceeded` if wall-clock has elapsed.

        Safe to call from a heartbeat ticker between active steps.
        """
        self._check_wall_clock()

    def _check_wall_clock(self) -> None:
        elapsed = self.elapsed_s()
        if elapsed > self.budget.max_wall_clock_s:
            self._raise("wall_clock", elapsed, self.budget.max_wall_clock_s)

    # ------------------------------------------------------------------
    # Telemetry
    # ------------------------------------------------------------------

    def usage(self) -> dict[str, float]:
        """Snapshot the current counter state. Read-only."""
        return {
            "steps": self.steps,
            "tokens": self.tokens,
            "wall_clock_s": self.elapsed_s(),
            "clarifiers": self.clarifiers,
            "plan_revisions": self.plan_revisions,
        }

    def remaining(self) -> dict[str, float]:
        """How much room is left along each dimension."""
        return {
            "steps": max(0, self.budget.max_steps - self.steps),
            "tokens": max(0, self.budget.max_tokens - self.tokens),
            "wall_clock_s": max(0.0, self.budget.max_wall_clock_s - self.elapsed_s()),
            "clarifiers": max(0, self.budget.max_clarifiers - self.clarifiers),
            "plan_revisions": max(
                0,
                self.budget.max_plan_revisions - self.plan_revisions,
            ),
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _raise(self, dimension: BudgetDimension, usage: float, limit: float) -> None:
        self.breached = dimension
        raise BudgetExceeded(dimension, limit=limit, usage=usage)


# ── Abort payload helper ─────────────────────────────────────────────


def make_abort_payload(
    meter: LoopBudgetMeter,
    exc: BudgetExceeded,
    *,
    run_id: str = "",
) -> dict[str, Any]:
    """Build the ``loop.abort`` payload from a meter + exception.

    The shape matches :class:`crp_comply.api.events.AbortPayload`.
    """
    return {
        "run_id": run_id,
        "reason": "budget_exceeded",
        "dimension": exc.dimension,
        "limit": float(exc.limit),
        "usage": float(exc.usage),
        "budget": meter.budget.as_dict(),
        "totals": meter.usage(),
    }
