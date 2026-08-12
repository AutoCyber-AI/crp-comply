# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Web-search adapter exposed to the agent's tool registry.

The four ``build_*_tool`` factories in :mod:`crp_comply.agent.tools`
expect a single object that exposes:

* ``search(query, *, intent, freshness, max_results, fetch_full_text) -> dict``
* ``research_intelligent(goal, *, intent, freshness, max_results_per_query,
  expansion_strategy, rerank_top_k, fetch_full_text, chunk_cite) -> dict``
* ``vendor_profile(vendor, *, max_results) -> dict``
* ``compare_documents(documents, *, claims) -> dict``

The transport-level work already exists as module-level functions in
:mod:`crp_comply.sidecar_client`. This file is the thin object adapter
that wraps them so the agent can be handed a single ``web_client``
instance, with sensible failure semantics (return an empty result with
``"error"`` set instead of raising — the LLM would otherwise see a tool
exception and lose its turn).

Production env contract
-----------------------

* ``CRP_COMPLY_SEARCH_URL`` — base URL of the sidecar (e.g. the Railway
  internal hostname). When unset, :func:`build_default_web_client`
  returns ``None`` and the registry simply omits the web tools — the
  agent then falls back to corpus-only retrieval.
* ``CRP_COMPLY_SEARCH_API_KEY`` — bearer token. Optional in dev, but
  the sidecar refuses unauthenticated requests in production.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from .. import sidecar_client

logger = logging.getLogger(__name__)


__all__ = ["WebClient", "build_default_web_client"]


class WebClient:
    """Object adapter over :mod:`crp_comply.sidecar_client`.

    Failures are converted into structured error payloads rather than
    exceptions so the LLM can recover (call a different tool, retry
    with a different query, fall back to corpus). The error string
    surfaces in :class:`crp_comply.api.events.WebResultEvent` so the
    UI can show a "search failed" badge instead of dropping the run.
    """

    def __init__(self, *, cfg: sidecar_client.SidecarConfig | None = None) -> None:
        self._cfg = cfg

    # ── search ────────────────────────────────────────────────

    def search(
        self,
        query: str,
        *,
        intent: str = "general",
        freshness: str = "any",
        max_results: int = 8,
        fetch_full_text: bool = False,
        profile: str | None = None,
    ) -> dict[str, Any]:
        try:
            return sidecar_client.search(
                query,
                profile=profile,
                freshness=freshness,
                max_results=max_results,
                fetch_full_text=fetch_full_text,
                intent=intent,
                cfg=self._cfg,
            )
        except sidecar_client.SidecarError as exc:
            logger.warning("web search failed: %s", exc)
            return {
                "results": [],
                "backend": "sidecar",
                "blocked": 0,
                "latency_ms": 0,
                "error": str(exc),
            }

    # ── research ──────────────────────────────────────────────

    def research_intelligent(
        self,
        goal: str,
        *,
        intent: str = "general",
        freshness: str = "any",
        max_results_per_query: int = 8,
        expansion_strategy: str = "templated",
        rerank_top_k: int = 6,
        fetch_full_text: bool = True,
        chunk_cite: bool = True,
        profile: str | None = None,
    ) -> dict[str, Any]:
        try:
            return sidecar_client.research_intelligent(
                goal,
                intent=intent,
                profile=profile,
                freshness=freshness,
                max_results_per_query=max_results_per_query,
                expansion_strategy=expansion_strategy,
                rerank_top_k=rerank_top_k,
                fetch_full_text=fetch_full_text,
                chunk_cite=chunk_cite,
                cfg=self._cfg,
            )
        except sidecar_client.SidecarError as exc:
            logger.warning("web research failed: %s", exc)
            return {"results": [], "error": str(exc)}

    def research_agent(
        self,
        goal: str,
        *,
        intent: str = "general",
        freshness: str = "any",
        max_results_per_query: int = 8,
        rerank_top_k: int = 6,
        fetch_full_text: bool = True,
        chunk_cite: bool = True,
        profile: str | None = None,
    ) -> dict[str, Any]:
        """POST /research_agent — agentic search-reason-cite loop."""
        try:
            return sidecar_client.research_agent(
                goal,
                intent=intent,
                profile=profile,
                freshness=freshness,
                max_results_per_query=max_results_per_query,
                rerank_top_k=rerank_top_k,
                fetch_full_text=fetch_full_text,
                chunk_cite=chunk_cite,
                cfg=self._cfg,
            )
        except sidecar_client.SidecarError as exc:
            logger.warning("research_agent failed: %s", exc)
            return {"results": [], "citations": [], "error": str(exc)}

    def research_by_depth(
        self,
        goal: str,
        *,
        depth: str = "standard",
        intent: str = "general",
        freshness: str = "any",
        profile: str | None = None,
    ) -> dict[str, Any]:
        """Depth-aware research wrapper with timeout fallback."""
        try:
            return sidecar_client.research_by_depth(
                depth,
                goal,
                intent=intent,
                profile=profile,
                freshness=freshness,
                cfg=self._cfg,
            )
        except sidecar_client.SidecarTimeoutError:
            logger.warning(
                "research_by_depth timed out (depth=%s), returning corpus fallback", depth
            )
            return {
                "results": [],
                "citations": [],
                "error": "timeout",
                "fallback": True,
                "note": "Web research timed out. Falling back to the indexed corpus.",
            }
        except sidecar_client.SidecarError as exc:
            logger.warning("research_by_depth failed: %s", exc)
            return {"results": [], "citations": [], "error": str(exc)}

    # ── vendor profile ───────────────────────────────────────

    def vendor_profile(
        self,
        vendor: str,
        *,
        max_results: int = 8,
        profile: str | None = None,
    ) -> dict[str, Any]:
        try:
            return sidecar_client.vendor_profile(
                vendor,
                profile=profile,
                max_results=max_results,
                cfg=self._cfg,
            )
        except sidecar_client.SidecarError as exc:
            logger.warning("vendor_profile failed: %s", exc)
            return {"buckets": {}, "error": str(exc)}

    # ── compare documents ────────────────────────────────────

    def compare_documents(
        self,
        documents: list[str],
        *,
        claims: list[str] | None = None,
        profile: str | None = None,
    ) -> dict[str, Any]:
        try:
            return sidecar_client.compare_documents(
                list(documents),
                claims=list(claims or []),
                profile=profile,
                cfg=self._cfg,
            )
        except sidecar_client.SidecarError as exc:
            logger.warning("compare_documents failed: %s", exc)
            return {"matrix": {}, "error": str(exc)}

    # ── feedback (close the SearXNG learning loop) ───────────

    def feedback(
        self,
        *,
        intent: str,
        engine: str,
        useful: bool = True,
        weight: float = 1.0,
        url: str | None = None,
        query: str | None = None,
    ) -> dict[str, Any]:
        try:
            return sidecar_client.feedback(
                intent=intent,
                engine=engine,
                useful=useful,
                weight=weight,
                url=url,
                query=query,
                cfg=self._cfg,
            )
        except sidecar_client.SidecarError as exc:
            logger.debug("feedback failed (best-effort): %s", exc)
            return {"ok": False, "error": str(exc)}


def build_default_web_client() -> WebClient | None:
    """Construct a :class:`WebClient` from env, or ``None`` if disabled.

    Production wiring: ``_build_agent`` calls this once per request.
    A ``None`` return makes ``default_registry`` skip the web tools so
    the agent runs corpus-only — useful for local dev without the
    sidecar running, and for paranoid tenants that want to disable the
    open-web entirely (set ``CRP_COMPLY_SEARCH_URL=""``).
    """
    if not (os.environ.get("CRP_COMPLY_SEARCH_URL") or "").strip():
        return None
    try:
        cfg = sidecar_client.SidecarConfig.from_env()
    except sidecar_client.SidecarError as exc:
        logger.info("web client disabled: %s", exc)
        return None
    return WebClient(cfg=cfg)
