"""Pre-loop query triage \u2014 PHASE_7 \u00a714 + \u00a721 7.1.

Why this exists
---------------
Most compliance questions are dull and predictable: "cite Article 6
GDPR", "what does NIS2 mean by essential entity", "generate a DPIA
for our HR analytics tool". For those we should not pay the latency
cost of a multi-step ReAct loop. The triage layer answers, in CPU
time only:

    1. Is this a recognised pattern? (O(1) regex sweep)
    2. If not, how complex is it? (length / multi-clause heuristics)
    3. Which lane should it go in? (cache | fast | slow)

The decision is **deterministic** \u2014 same query in, same
:class:`TriageResult` out, every time. That is a hard requirement of
PHASE_7 \u00a721 7.1 ("Lane selection is deterministic: same query \u2192 same
lane every time") because the audit replay tooling (\u00a712) needs to
re-derive the lane from the original query alone.

No bypasses (PHASE_7 \u00a721 7.1):
* Unknown queries do *not* silently default to ``slow`` with high
  confidence. They emit ``confidence=low`` + ``reasoning='fallback'``
  so the UI can surface the explicit fallback.
* No LLM call is made inside :meth:`Triage.classify`. CPU only.
* User input is never concatenated into a regex: patterns are static
  YAML loaded at construction time, escape rules apply only to
  pattern *authors*.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal

import yaml

__all__ = [
    "Triage",
    "TriageResult",
    "TriageError",
    "load_default_triage",
]


# ── Type aliases (mirrored in api/events.py for the SSE schema) ───────


Complexity = Literal["trivial", "simple", "moderate", "complex", "comprehensive"]
Lane = Literal["cache", "fast", "slow"]
Intent = Literal["define", "cite", "scope", "compare", "produce_artefact", "audit_existing"]


_VALID_COMPLEXITIES: Final = {"trivial", "simple", "moderate", "complex", "comprehensive"}
_VALID_LANES: Final = {"cache", "fast", "slow"}
_VALID_INTENTS: Final = {
    "define",
    "cite",
    "scope",
    "compare",
    "produce_artefact",
    "audit_existing",
}


class TriageError(ValueError):
    """Raised when the pattern YAML fails validation at load time."""


@dataclass(frozen=True)
class TriageResult:
    """Outcome of one triage pass.

    Attributes
    ----------
    complexity : one of the five buckets from PHASE_7 \u00a73.2.
    intent     : six-way classifier from \u00a714.4 step 3.
    confidence : 0\u20131. Below 0.5 means we hit the safety fallback.
    lane       : ``cache`` is set by the orchestrator (after the cache
                 layer runs); the triage itself only ever returns
                 ``fast`` or ``slow``.
    reasoning  : human-readable trace string for the SSE event and
                 audit log; pattern id when a pattern matched, else
                 a short heuristic description (or ``"fallback"``).
    elapsed_ms : wall-clock cost of the classify() call \u2014 used by
                 the \u226450 ms p95 SLO test.
    pattern_id : id of the YAML pattern that fired, or ``None``.
    """

    complexity: Complexity
    intent: Intent
    confidence: float
    lane: Lane
    reasoning: str
    elapsed_ms: float = 0.0
    pattern_id: str | None = None

    def to_event_payload(self) -> dict[str, Any]:
        """Shape for ``loop.triage`` (see :class:`api.events.TriagePayload`)."""
        return {
            "complexity": self.complexity,
            "intent": self.intent,
            "confidence": round(float(self.confidence), 4),
            "lane": self.lane,
            "reasoning": self.reasoning,
        }


@dataclass(frozen=True)
class _Pattern:
    id: str
    regex: re.Pattern[str]
    intent: Intent
    complexity: Complexity
    lane: Lane
    confidence: float


_DEFAULT_PATTERNS_PATH: Final = Path(__file__).parent / "triage_patterns.yaml"


# ── Heuristic constants (PHASE_7 \u00a714.4 step 2) ────────────────────────


_REGULATION_TOKENS: Final = (
    "gdpr",
    "eu ai act",
    "ai act",
    "nis2",
    "dora",
    "iso 42001",
    "iso 22989",
    "nist ai rmf",
    "uk ai whitepaper",
    "uk ai act",
    "edpb",
    "oecd",
    "ccpa",
    "hipaa",
    "uk gdpr",
    "data protection act",
    "dpa 2018",
)
_COMPARISON_TOKENS: Final = (
    " vs ",
    " versus ",
    "difference between",
    "compared to",
    "compared with",
)
_CLAUSE_SEPARATORS: Final = (";", " and also ", " as well as ", " in addition ", " furthermore ")


# ── Pattern loader ────────────────────────────────────────────────────


def _validate_pattern_dict(idx: int, raw: dict[str, Any]) -> _Pattern:
    """Validate one YAML pattern entry and compile its regex.

    Why so strict: a malformed pattern would silently mis-route every
    query that hits it. Fail at module load instead.
    """
    required = {"id", "regex", "intent", "complexity", "lane", "confidence"}
    missing = required - set(raw)
    if missing:
        raise TriageError(f"pattern[{idx}] missing keys: {sorted(missing)}")
    pid = str(raw["id"])
    intent = str(raw["intent"])
    complexity = str(raw["complexity"])
    lane = str(raw["lane"])
    if intent not in _VALID_INTENTS:
        raise TriageError(f"pattern[{pid}] bad intent {intent!r}")
    if complexity not in _VALID_COMPLEXITIES:
        raise TriageError(f"pattern[{pid}] bad complexity {complexity!r}")
    if lane not in _VALID_LANES or lane == "cache":
        # YAML must never assign `cache` \u2014 cache is only set
        # programmatically by the orchestrator after a real hit.
        raise TriageError(f"pattern[{pid}] bad lane {lane!r} (must be 'fast' or 'slow')")
    confidence = float(raw["confidence"])
    if not 0.0 <= confidence <= 1.0:
        raise TriageError(f"pattern[{pid}] confidence out of [0,1]: {confidence}")
    try:
        compiled = re.compile(str(raw["regex"]), re.IGNORECASE)
    except re.error as exc:
        raise TriageError(f"pattern[{pid}] regex compile failed: {exc}") from exc
    return _Pattern(
        id=pid,
        regex=compiled,
        intent=intent,  # type: ignore[arg-type]
        complexity=complexity,  # type: ignore[arg-type]
        lane=lane,  # type: ignore[arg-type]
        confidence=confidence,
    )


def _load_patterns(path: Path) -> list[_Pattern]:
    if not path.exists():
        raise TriageError(f"triage pattern file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        doc = yaml.safe_load(fh) or {}
    raw_patterns = doc.get("patterns")
    if not isinstance(raw_patterns, list) or not raw_patterns:
        raise TriageError(f"{path}: 'patterns:' must be a non-empty list")
    out = [_validate_pattern_dict(i, p) for i, p in enumerate(raw_patterns)]
    seen: set[str] = set()
    for p in out:
        if p.id in seen:
            raise TriageError(f"duplicate pattern id: {p.id}")
        seen.add(p.id)
    return out


# ── Triage class ──────────────────────────────────────────────────────


@dataclass
class Triage:
    """Stateless deterministic classifier.

    A single :class:`Triage` instance can serve every request \u2014 it
    holds only the compiled pattern list. Construct via
    :func:`load_default_triage` to use the bundled YAML.
    """

    patterns: list[_Pattern] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: Path | str) -> "Triage":
        return cls(patterns=_load_patterns(Path(path)))

    # -- main entry --------------------------------------------------

    def classify(self, query: str) -> TriageResult:
        """Return a :class:`TriageResult` for *query*.

        Always returns a result; never raises on user input. The
        worst case is a fallback to ``slow`` lane with low
        confidence and ``reasoning='fallback'``.
        """
        t0 = time.perf_counter()
        normalised = (query or "").strip().lower()
        if not normalised:
            return TriageResult(
                complexity="simple",
                intent="define",
                confidence=0.1,
                lane="slow",
                reasoning="fallback:empty_query",
                elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                pattern_id=None,
            )

        # 1. Pattern pass (O(n) over a small static list, effectively O(1)).
        for p in self.patterns:
            if p.regex.search(normalised):
                return TriageResult(
                    complexity=p.complexity,
                    intent=p.intent,
                    confidence=p.confidence,
                    lane=p.lane,
                    reasoning=f"pattern:{p.id}",
                    elapsed_ms=(time.perf_counter() - t0) * 1000.0,
                    pattern_id=p.id,
                )

        # 2. Heuristics (PHASE_7 \u00a714.4 step 2).
        complexity, lane, intent, conf, reason = self._heuristics(normalised)
        return TriageResult(
            complexity=complexity,
            intent=intent,
            confidence=conf,
            lane=lane,
            reasoning=reason,
            elapsed_ms=(time.perf_counter() - t0) * 1000.0,
            pattern_id=None,
        )

    # -- heuristics --------------------------------------------------

    @staticmethod
    def _heuristics(
        q: str,
    ) -> tuple[Complexity, Lane, Intent, float, str]:
        word_count = len(q.split())
        reg_hits = sum(1 for tok in _REGULATION_TOKENS if tok in q)
        is_compare = any(tok in q for tok in _COMPARISON_TOKENS)
        clause_count = 1 + sum(q.count(sep) for sep in _CLAUSE_SEPARATORS)

        # Compare queries are always complex (slow lane).
        if is_compare or reg_hits >= 2:
            return (
                "complex",
                "slow",
                "compare" if is_compare else "scope",
                0.7,
                "heuristic:multi_regulation"
                if reg_hits >= 2 and not is_compare
                else "heuristic:comparison",
            )

        # Long multi-clause queries lean toward the slow lane too.
        if word_count >= 40 or clause_count >= 3:
            return (
                "complex",
                "slow",
                "scope",
                0.55,
                f"heuristic:long_query(words={word_count},clauses={clause_count})",
            )
        if word_count >= 18:
            return (
                "moderate",
                "slow",
                "scope",
                0.5,
                f"heuristic:medium_query(words={word_count})",
            )

        # Short, single-clause, single-regulation queries that didn't
        # match a pattern: we *guess* simple/define but with low
        # confidence and route to slow path \u2014 explicit fallback per
        # PHASE_7 \u00a721 7.1 ("Do not let triage default to slow_path
        # for unknown queries silently \u2014 emit confidence=low,
        # reasoning=fallback").
        return (
            "simple",
            "slow",
            "define",
            0.3,
            "fallback",
        )


def load_default_triage() -> Triage:
    """Return a :class:`Triage` instance loaded from the bundled YAML."""
    return Triage.from_yaml(_DEFAULT_PATTERNS_PATH)
