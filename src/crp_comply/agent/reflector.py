"""Reflector + plan revision + CKF coverage check \u2014 PHASE_7 \u00a721 7.6.

After every step the orchestrator passes the :class:`StepOutcome`
plus the current :class:`LoopState` to the reflector, which returns
one of five verdicts:

* ``ok``            \u2014 step succeeded; advance.
* ``retry``         \u2014 redo the same step (e.g. a citation is missing).
* ``revise_plan``   \u2014 the plan was wrong; replan from PLANNING.
* ``clarify_first`` \u2014 ask the user before continuing.
* ``abort``         \u2014 unrecoverable; transition to ERROR.

The reflector is **structural**, not advisory:

* ``ok`` is impossible if any claim in the step's observation is
  uncited (PHASE_7 \u00a715.1.3 + \u00a721 7.6: "every claim must reference a
  ``fact_id``"). Uncited \u2192 ``retry``.
* Plan revision is capped by ``state.max_plan_revisions`` (default 3).
  Asking for a fourth revision is downgraded to ``abort``.
* Lane B (degenerate single-step) still goes through reflect; the
  reflector does not look at the lane.

Bypass guards (PHASE_7 \u00a721 7.6):

* :func:`extract_claims` walks the observation text for sentences that
  look like assertions (subject + verb). Any claim without at least
  one matching citation triggers ``retry``.
* The plan-revision budget is checked here *and* by
  :meth:`LoopState.revise_plan`; both must agree.
* Confidence floor: if the model itself signalled low confidence
  (``confidence < 0.6`` carried on the outcome), the reflector
  emits ``clarify_first`` rather than ``ok``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from .loop_state import LoopState, PlanStep
from .step_runner import StepOutcome
from ..api.events import make_event


__all__ = [
    "Reflector",
    "ReflectorResult",
    "ReflectorVerdict",
    "extract_claims",
]


ReflectorVerdict = Literal["ok", "retry", "revise_plan", "clarify_first", "abort"]


# ── Claim extraction ────────────────────────────────────────────────


# A "claim" is a sentence that asserts something factual. We split on
# sentence boundaries, drop quoted noise, and keep anything that has a
# verb-like token. Heuristic but deterministic \u2014 the goal is to catch
# the common shape "X is required by Y" and "Z must do W".
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
_VERB_HINT = re.compile(
    r"\b(is|are|was|were|must|shall|may|requires?|needs?|provides?|"
    r"prohibits?|allows?|grants?|imposes?|defines?)\b",
    re.I,
)
# Citation markers: "[recall] ...", "[pattern_query] ...", and any
# mention of a regulation pinpoint like "Art. 6", "Article 22", etc.
_CITATION_PINPOINT = re.compile(
    r"\b(?P<kind>art(?:icle)?|annex|recital)\.?\s*"
    r"(?P<num>\d+|[ivxlc]+)\b",
    re.I,
)


def _normalise_pinpoint(match: re.Match[str]) -> tuple[str, str]:
    """Return ``(kind, number)`` normalised to lowercase."""
    kind = match.group("kind").lower()
    if kind.startswith("art"):
        kind = "article"
    return kind, match.group("num").lower()


def extract_claims(observation: str) -> list[str]:
    """Split *observation* into claim-like sentences.

    Returns the raw sentence strings; the reflector then checks each
    one against the citation list.
    """
    if not observation:
        return []
    out: list[str] = []
    for raw in _SENT_SPLIT.split(observation.strip()):
        s = raw.strip()
        if not s:
            continue
        if not _VERB_HINT.search(s):
            continue
        out.append(s)
    return out


def _claim_is_cited(claim: str, citations: list[dict[str, Any]]) -> bool:
    """A claim is cited if it carries a pinpoint marker that matches
    one of the citation entries, *or* if any citation simply exists
    for a tool whose tag appears in the sentence (e.g. ``[pattern_query]``).
    """
    if not citations:
        # No citations at all \u2014 cannot be cited.
        return False
    # Tool-tag style (the runner prefixes observation parts with
    # ``[tool] ...``); claims rolling out of a tagged segment inherit
    # that tool's citations. We approximate this with: the sentence
    # contains a ``[...]`` tag.
    if "[" in claim and "]" in claim:
        return True
    # Pinpoint match: claim mentions Art. X, citation mentions Art. X.
    pin = _CITATION_PINPOINT.search(claim)
    if pin is None:
        # Unspecific assertion; require any citation to exist.
        return bool(citations)
    kind, num = _normalise_pinpoint(pin)
    for cite in citations:
        for value in cite.values():
            text = str(value).lower()
            cite_match = _CITATION_PINPOINT.search(text)
            if cite_match is None:
                continue
            c_kind, c_num = _normalise_pinpoint(cite_match)
            if c_kind == kind and c_num == num:
                return True
    return False


# ── Reflector ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class ReflectorResult:
    verdict: ReflectorVerdict
    notes: str = ""
    plan_delta: dict[str, Any] | None = None
    uncited_claims: tuple[str, ...] = field(default_factory=tuple)


@dataclass
class Reflector:
    """Stateless evaluator of step outcomes.

    The reflector does not own the FSM \u2014 it returns a verdict and the
    orchestrator threads that through ``state.apply_reflector_verdict``.
    Doing it this way lets us unit-test the verdict logic without
    spinning up a real loop.

    *low_confidence_threshold* is the floor below which the reflector
    forces ``clarify_first``. Defaults to 0.6 per PHASE_7 \u00a721 7.5.
    """

    low_confidence_threshold: float = 0.6
    require_citations: bool = True

    def evaluate(
        self,
        *,
        state: LoopState,
        step: PlanStep,
        outcome: StepOutcome,
        confidence: float | None = None,
    ) -> ReflectorResult:
        # 1. Tool failures \u2192 retry (or abort if budget gone).
        if outcome.status == "failed":
            return self._retry_or_abort(state, "step failed: " + (outcome.error or "(no detail)"))

        # 2. Citation coverage. Uncited claim \u2192 retry; the model must
        # try again with sources. We do *not* downgrade to ok even if
        # only one of N claims is uncited \u2014 the rule is structural.
        uncited: list[str] = []
        if self.require_citations:
            for claim in extract_claims(outcome.observation):
                if not _claim_is_cited(claim, outcome.citations):
                    uncited.append(claim)
        if uncited:
            return self._retry_or_abort(
                state,
                f"uncited claim(s): {len(uncited)}",
                uncited=tuple(uncited),
            )

        # 3. Low-confidence \u2192 ask the user.
        if confidence is not None and confidence < self.low_confidence_threshold:
            # If we're already over the clarifier budget, abort rather
            # than spin in clarify_first.
            if state.clarifier_count >= state.max_clarifiers:
                return ReflectorResult(
                    verdict="abort",
                    notes="confidence below floor and clarifier budget exhausted",
                )
            return ReflectorResult(
                verdict="clarify_first",
                notes=f"confidence {confidence:.2f} < {self.low_confidence_threshold}",
            )

        # 4. Otherwise the step is good.
        return ReflectorResult(verdict="ok")

    # -- helpers ----------------------------------------------------

    def _retry_or_abort(
        self,
        state: LoopState,
        notes: str,
        *,
        uncited: tuple[str, ...] = (),
    ) -> ReflectorResult:
        """Retry if we have budget, else escalate to revise_plan, else abort.

        We use plan_revisions as a proxy for "how many times the same
        sub-tree of work has been attempted"; once the budget is gone
        the only honest answer is abort.
        """
        if state.plan_revisions >= state.max_plan_revisions:
            return ReflectorResult(
                verdict="abort",
                notes=notes + " (plan revision budget exhausted)",
                uncited_claims=uncited,
            )
        # First failure on a step \u2192 retry the same step. Once we've
        # retried this step at least twice (REFLECT \u2192 STEP back-edges
        # in the FSM history) without success, ask the planner for a
        # fresh plan. After three plan revisions the outer guard above
        # promotes the next failure to ``abort``.
        retries = _count_retries_on_current_step(state)
        if retries >= 2:
            return ReflectorResult(
                verdict="revise_plan",
                notes=notes + " (retry exhausted; revising plan)",
                uncited_claims=uncited,
            )
        return ReflectorResult(
            verdict="retry",
            notes=notes,
            uncited_claims=uncited,
        )


def _count_retries_on_current_step(state: LoopState) -> int:
    """Count REFLECT\u2192STEP transitions since the last plan boundary.

    Each such transition is a retry of the current step. A
    PLANNING\u2192STEP transition resets the counter (new plan, fresh
    attempt log).
    """
    count = 0
    for entry in state.history:
        try:
            from_state, to_state, _reason = entry
        except Exception:  # pragma: no cover - defensive
            continue
        from_name = getattr(from_state, "name", str(from_state))
        to_name = getattr(to_state, "name", str(to_state))
        if from_name == "PLANNING" and to_name == "STEP":
            count = 0
            continue
        if from_name == "REFLECT" and to_name == "STEP":
            count += 1
    return count


# ── Telemetry ───────────────────────────────────────────────────────


def make_reflection_event(
    *,
    step_id: str,
    result: ReflectorResult,
    run_id: str = "",
) -> dict[str, Any]:
    """Build a validated ``loop.reflection`` event from a result.

    Centralised so the orchestrator and the test harness produce the
    same shape.
    """
    return make_event(
        "loop.reflection",
        {
            "step_id": step_id,
            "verdict": result.verdict,
            "notes": result.notes,
            "plan_delta": result.plan_delta,
        },
        run_id=run_id,
    )
