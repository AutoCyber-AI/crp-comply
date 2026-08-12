"""CRP Query Router — server-side intelligent engine selection.

This is the **first half** of the SearXNG-host-side agent. Where the
default SearXNG fans out to every enabled engine for the requested
category, the router rewrites the engine list per request based on:

  1. The detected ``intent`` query parameter (``regulation_text``,
     ``case_law``, ``guidance``, ``enforcement``, ``news``, ``vendor``,
     ``general``) — supplied by crp-comply-search.
  2. The static intent → engine ordering in
     ``settings.yml::crp_agent.router.intents``.
  3. The runtime feedback signal from the learning reranker, which
     boosts/dampens engines based on past citation utility.
  4. A heuristic query fingerprint (presence of CELEX numbers, EU regs,
     vendor proper nouns) that adds an authority engine even if the
     caller asked for a generic search.

The plugin honours SearXNG's plugin contract (``pre_search``) so it
runs before any HTTP request goes out to the engines.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from searx import settings
from searx.plugins import Plugin, PluginInfo

if TYPE_CHECKING:  # pragma: no cover
    from searx.search import SearchQuery
    from searx.plugins import PluginCfg

logger = logging.getLogger("searx.plugins.crp_query_router")

# Authority hints that force inclusion of an authority engine even if
# the request didn't ask for it.
_CELEX_RE = re.compile(r"\b(?:\d{4}/\d+|\d{5}[A-Z]\d{4})\b")
_REGULATION_RE = re.compile(
    r"\b(?:GDPR|EU AI Act|DSA|DMA|NIS2|DORA|eIDAS|ePrivacy|MiCA|CSRD)\b",
    re.IGNORECASE,
)
_CASE_RE = re.compile(r"\bC[-\u2013]\d+/\d{2}\b|\bCase\s+C[-\u2013]?\d+", re.IGNORECASE)


class CrpQueryRouter(Plugin):
    """Server-side router that picks the most useful engine subset."""

    id = "CRP Query Router"

    def __init__(self, plg_cfg: "PluginCfg | None" = None):
        super().__init__(plg_cfg)
        cfg = (settings.get("crp_agent") or {}).get("router") or {}
        self._intents: dict[str, list[str]] = cfg.get("intents") or {}
        self._budget: int = int(cfg.get("max_engines_per_query") or 4)
        self.info = PluginInfo(
            id=self.id,
            name="CRP Query Router",
            description=(
                "Routes queries to the most relevant engine subset based on "
                "declared intent + query authority fingerprint."
            ),
            preference_section="general",
        )

    # ------------------------------------------------------------------
    # SearXNG hook.
    # ------------------------------------------------------------------
    def pre_search(self, request, search) -> bool:  # type: ignore[override]
        try:
            self._route(request, search)
        except Exception:  # noqa: BLE001 — never block search on routing failure.
            logger.exception("crp_query_router: routing failed; falling back to default")
        return True

    # ------------------------------------------------------------------
    # Internals.
    # ------------------------------------------------------------------
    def _route(self, request, search) -> None:
        sq: "SearchQuery" = search.search_query
        intent = self._extract_intent(request)
        query = (sq.query or "").strip()
        ordering = list(self._intents.get(intent) or self._intents.get("general") or [])
        ordering = self._apply_authority_fingerprint(query, ordering)
        ordering = self._apply_feedback(intent, ordering)

        # Trim to budget.
        chosen = ordering[: self._budget]
        if not chosen:
            return

        # Replace the engineref list — keep only refs whose engine name
        # is in the chosen set, in the chosen order.
        original = list(sq.engineref_list)
        chosen_set = set(chosen)
        rewritten = [er for er in original if er.name in chosen_set]
        # Preserve declared intent ordering.
        rewritten.sort(key=lambda er: chosen.index(er.name))
        if rewritten:
            sq.engineref_list = rewritten
            logger.info(
                "crp_query_router: intent=%s engines=%s",
                intent,
                [er.name for er in rewritten],
            )

    @staticmethod
    def _extract_intent(request) -> str:
        # crp-comply-search passes the intent as a query string param.
        intent = (
            (request.form.get("crp_intent") if hasattr(request, "form") else None)
            or (request.args.get("crp_intent") if hasattr(request, "args") else None)
            or "general"
        )
        intent = str(intent).lower().strip()
        return intent if intent else "general"

    @staticmethod
    def _apply_authority_fingerprint(query: str, ordering: list[str]) -> list[str]:
        out = list(ordering)

        def _ensure(engine: str, position: int = 0) -> None:
            if engine in out:
                out.remove(engine)
            out.insert(position, engine)

        if _CELEX_RE.search(query) or _REGULATION_RE.search(query):
            _ensure("eur-lex", 0)
        if _CASE_RE.search(query):
            _ensure("curia", 0)
            _ensure("bailii", 1)
        return out

    def _apply_feedback(self, intent: str, ordering: list[str]) -> list[str]:
        # Stable sort by the learning reranker's score (if loaded).
        from searx.plugins._crp.learning_reranker import (  # local import — avoid cycle
            engine_scores,
        )

        scores: dict[str, float] = engine_scores(intent)
        if not scores:
            return ordering
        return sorted(ordering, key=lambda e: -scores.get(e, 0.0))


# SearXNG looks for either a callable named ``init`` or an instance.
def init(app: Any, plg_settings: Any) -> bool:  # noqa: D401
    """SearXNG plugin init hook."""
    return True


# Module-level instance picked up by SearXNG when listed in enabled_plugins.
plugin = CrpQueryRouter()
