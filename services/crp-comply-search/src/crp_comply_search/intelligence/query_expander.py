"""Sub-query fan-out for the intelligent web search.

Given a user goal + intent, emit 3-5 targeted sub-queries. Two
strategies:

* ``"templated"`` (default; deterministic, $0): a static template
  pack per intent, parameterised by the goal.
* ``"llm"`` (opt-in): delegates to a callable supplied by the caller
  so the sidecar stays LLM-agnostic. Falls back to "templated" if
  the callable fails or returns nothing.

PHASE_7 §7.15: only fires on lane C (multi-step planning). Lane A
(cache hit) skips expansion entirely.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Callable, Literal

logger = logging.getLogger(__name__)


Strategy = Literal["templated", "llm"]


@dataclass(frozen=True)
class ExpansionResult:
    goal: str
    intent: str
    strategy: Strategy
    sub_queries: list[str] = field(default_factory=list)


# Templates per intent. Each placeholder {goal} is the raw user goal.
# Order is meaningful — the first sub-query is also the most "literal".
_TEMPLATES: dict[str, list[str]] = {
    "regulation_text": [
        "{goal}",
        '"{goal}" regulation OR directive site:eur-lex.europa.eu',
        "{goal} CELEX number",
        "{goal} consolidated text",
    ],
    "case_law": [
        "{goal}",
        '"{goal}" judgment site:curia.europa.eu',
        "{goal} ECJ ruling",
        "{goal} case law analysis",
    ],
    "guidance": [
        "{goal}",
        "{goal} EDPB guidance",
        "{goal} ICO guidance",
        '"{goal}" supervisory authority',
    ],
    "enforcement": [
        "{goal}",
        "{goal} enforcement action fine",
        '"{goal}" decision site:edpb.europa.eu',
        "{goal} regulator decision 2025 OR 2026",
    ],
    "news": [
        "{goal}",
        "{goal} latest",
        '"{goal}" 2026',
        "{goal} announcement",
    ],
    "vendor": [
        "{goal} privacy policy",
        "{goal} subprocessors list",
        "{goal} data processing addendum",
        "{goal} security whitepaper",
        '"{goal}" GDPR DPA',
    ],
    "general": [
        "{goal}",
        "{goal} overview",
        "{goal} explained",
    ],
}


class QueryExpander:
    """Sub-query generator. Pure-Python; safe to construct cheaply."""

    DEFAULT_MAX = 4

    def __init__(
        self,
        *,
        llm_callable: Callable[[str, str, int], list[str]] | None = None,
        max_sub_queries: int = DEFAULT_MAX,
    ) -> None:
        self._llm = llm_callable
        self._max = max(1, int(max_sub_queries))

    def expand(
        self,
        goal: str,
        *,
        intent: str = "general",
        strategy: Strategy = "templated",
    ) -> ExpansionResult:
        goal_clean = (goal or "").strip()
        intent_clean = (intent or "general").strip().lower() or "general"
        if not goal_clean:
            return ExpansionResult(goal=goal_clean, intent=intent_clean,
                                   strategy=strategy, sub_queries=[])
        if strategy == "llm" and self._llm is not None:
            try:
                queries = list(self._llm(goal_clean, intent_clean, self._max))
                queries = [q.strip() for q in queries if q and q.strip()]
                if queries:
                    return ExpansionResult(
                        goal=goal_clean, intent=intent_clean,
                        strategy="llm",
                        sub_queries=self._dedupe(queries)[: self._max],
                    )
            except Exception:  # noqa: BLE001
                logger.warning("llm expansion failed; falling back to templated",
                               exc_info=True)
        return self._templated(goal_clean, intent_clean)

    # ----------------------------------------------------------------
    # Internals
    # ----------------------------------------------------------------
    def _templated(self, goal: str, intent: str) -> ExpansionResult:
        templates = _TEMPLATES.get(intent) or _TEMPLATES["general"]
        rendered = [t.format(goal=goal) for t in templates]
        return ExpansionResult(
            goal=goal, intent=intent, strategy="templated",
            sub_queries=self._dedupe(rendered)[: self._max],
        )

    @staticmethod
    def _dedupe(seq: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for raw in seq:
            key = re.sub(r"\s+", " ", raw.lower()).strip()
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(raw.strip())
        return out
