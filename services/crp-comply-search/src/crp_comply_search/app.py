"""FastAPI app for the crp-comply web-search sidecar.

Routes:

* ``POST /search``     \u2014 single query.
* ``POST /research``   \u2014 multi-query expansion.
* ``GET  /health``     \u2014 liveness.
* ``GET  /metrics``    \u2014 Prometheus exposition.

A bearer token is required when ``CRP_COMPLY_SEARCH_API_KEY`` is set
(production); when unset the sidecar runs open and logs a WARN at
startup so it's obvious in dev.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Literal

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    generate_latest,
)

from .backends import (
    BackendDisabledError,
    BraveBackend,
    LocalDDGBackend,
    SearXNGBackend,
    SearchResult,
    TavilyBackend,
    WebSearchBackend,
)
from .intelligence import ChunkCiter, CrossEncoderReranker, QueryExpander
from .profiles import ProfileRegistry, TrustTierProfile
from .reasoning import ReasoningClient, ReasoningConfig
from .research_agent import ResearchAgent


logger = logging.getLogger(__name__)


__all__ = ["create_app", "AppConfig"]


# ── Config ───────────────────────────────────────────────────────────


class AppConfig(BaseModel):
    """Resolved sidecar configuration. Built once at startup."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    backend: Literal["local", "brave", "tavily", "searxng"] = "local"
    profile_name: str = "crp_comply_official"
    profiles_dir: str | None = None
    api_key: str | None = None

    @classmethod
    def from_env(cls) -> "AppConfig":
        return cls(
            backend=os.environ.get(
                "CRP_COMPLY_SEARCH_BACKEND", "local"
            ).lower() or "local",  # type: ignore[arg-type]
            profile_name=os.environ.get(
                "CRP_COMPLY_SEARCH_PROFILE", "crp_comply_official"
            ),
            profiles_dir=os.environ.get("CRP_COMPLY_SEARCH_PROFILES_DIR")
            or None,
            api_key=os.environ.get("CRP_COMPLY_SEARCH_API_KEY") or None,
        )


# ── Request / response models ────────────────────────────────────────


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2000)
    profile: str | None = None  # accepted but server-side validated
    freshness: Literal["any", "day", "week", "month"] = "any"
    max_results: int = Field(default=10, ge=1, le=25)
    fetch_full_text: bool = True
    intent: Literal[
        "regulation_text", "case_law", "guidance", "enforcement",
        "news", "vendor", "general",
    ] | None = None


class ResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queries: list[str] = Field(min_length=1, max_length=8)
    profile: str | None = None
    freshness: Literal["any", "day", "week", "month"] = "any"
    max_results_per_query: int = Field(default=10, ge=1, le=25)
    fetch_full_text: bool = True
    intent: Literal[
        "regulation_text", "case_law", "guidance", "enforcement",
        "news", "vendor", "general",
    ] | None = None


class IntelligentResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: str = Field(min_length=1, max_length=2000)
    intent: Literal[
        "regulation_text", "case_law", "guidance", "enforcement",
        "news", "vendor", "general",
    ] = "general"
    profile: str | None = None
    freshness: Literal["any", "day", "week", "month"] = "any"
    max_results_per_query: int = Field(default=8, ge=1, le=25)
    expansion_strategy: Literal["templated", "llm"] = "templated"
    rerank_top_k: int = Field(default=6, ge=1, le=20)
    fetch_full_text: bool = True
    chunk_cite: bool = True


class VendorProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vendor: str = Field(min_length=1, max_length=200)
    profile: str | None = None
    max_results: int = Field(default=8, ge=1, le=20)


class CompareDocumentsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    documents: list[str] = Field(min_length=2, max_length=8)
    claims: list[str] = Field(default_factory=list, max_length=20)
    profile: str | None = None


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Literal[
        "regulation_text", "case_law", "guidance", "enforcement",
        "news", "vendor", "general",
    ]
    engine: str = Field(min_length=1, max_length=80)
    useful: bool = True
    weight: float = Field(default=1.0, ge=0.0, le=10.0)


# ── Metrics ──────────────────────────────────────────────────────────


_SEARCH_COUNTER = Counter(
    "crp_comply_search_requests_total",
    "Search requests served.",
    ["endpoint", "backend", "profile", "outcome"],
)
_LATENCY = Histogram(
    "crp_comply_search_latency_seconds",
    "Search request wall-clock latency.",
    ["endpoint", "backend"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)
_BLOCKED = Counter(
    "crp_comply_search_blocked_total",
    "Hits dropped by trust-tier blocklist.",
    ["profile"],
)


# ── Backend factory ──────────────────────────────────────────────────


def _build_backend(name: str) -> WebSearchBackend:
    if name == "local":
        return LocalDDGBackend()
    if name == "brave":
        # __post_init__ raises BackendDisabledError unless enabled.
        return BraveBackend(api_key=os.environ.get("BRAVE_API_KEY"))
    if name == "tavily":
        return TavilyBackend(api_key=os.environ.get("TAVILY_API_KEY"))
    if name == "searxng":
        # Free meta-search via a SearXNG instance.
        # Reads CRP_COMPLY_SEARXNG_URL at construction time.
        return SearXNGBackend()
    raise ValueError(f"unknown backend {name!r}")


# ── App factory ──────────────────────────────────────────────────────


def create_app(
    config: AppConfig | None = None,
    *,
    backend: WebSearchBackend | None = None,
    registry: ProfileRegistry | None = None,
) -> FastAPI:
    cfg = config or AppConfig.from_env()
    reg = registry or ProfileRegistry.load_dir(
        cfg.profiles_dir or None
    )
    if cfg.profile_name not in reg:
        available = reg.names()
        fallback = "crp_comply_official" if "crp_comply_official" in available else available[0]
        logger.warning(
            "configured profile %r not found (available: %s); falling back to %r",
            cfg.profile_name, available, fallback,
        )
        cfg = AppConfig(
            backend=cfg.backend,
            profile_name=fallback,
            profiles_dir=cfg.profiles_dir,
            api_key=cfg.api_key,
        )
    if backend is None:
        try:
            backend = _build_backend(cfg.backend)
        except BackendDisabledError:
            # Fail loudly per PHASE_7 \u00a721 7.8.
            raise

    if cfg.api_key is None:
        logger.warning(
            "crp-comply-search starting WITHOUT API key; "
            "set CRP_COMPLY_SEARCH_API_KEY in production."
        )

    app = FastAPI(
        title="crp-comply-search",
        version="0.1.0",
        description=(
            "Web search sidecar for the crp-comply language-agent loop "
            "(PHASE_7 \u00a77.8)."
        ),
    )
    app.state.config = cfg
    app.state.backend = backend
    app.state.registry = reg
    # 7.15 — intelligence layer (lazy ML deps; see intelligence/*).
    app.state.expander = QueryExpander()
    app.state.reranker = CrossEncoderReranker()
    app.state.chunker = ChunkCiter()

    # Optional reasoning model client for agentic gap detection.
    reasoning_cfg = ReasoningConfig.from_env()
    app.state.reasoning_client = (
        ReasoningClient(reasoning_cfg) if reasoning_cfg else None
    )

    # ---- auth dependency -----------------------------------------

    def require_api_key(request: Request) -> None:
        expected = cfg.api_key
        if expected is None:
            return  # dev mode
        header = request.headers.get("authorization") or ""
        if not header.lower().startswith("bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing bearer token",
            )
        if header.split(None, 1)[1].strip() != expected:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid api key",
            )

    # ---- helpers -------------------------------------------------

    def _resolve_profile(name: str | None) -> TrustTierProfile:
        target = name or cfg.profile_name
        if target not in reg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"unknown profile {target!r}",
            )
        return reg.get(target)

    # ---- routes --------------------------------------------------

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "backend": cfg.backend,
            "profile": cfg.profile_name,
            "profiles": reg.names(),
            "version": app.version,
        }

    @app.get("/metrics")
    def metrics() -> PlainTextResponse:
        return PlainTextResponse(
            generate_latest(),
            media_type=CONTENT_TYPE_LATEST,
        )

    @app.post("/search")
    def search(
        body: SearchRequest, _auth: None = Depends(require_api_key)
    ) -> dict[str, Any]:
        profile = _resolve_profile(body.profile)
        t0 = time.perf_counter()
        try:
            res: SearchResult = backend.search(
                body.query,
                profile=profile,
                freshness=body.freshness,
                max_results=body.max_results,
                fetch_full_text=body.fetch_full_text,
                intent=body.intent,
            )
            outcome = "ok"
        except Exception:
            outcome = "error"
            _SEARCH_COUNTER.labels(
                "search", cfg.backend, profile.name, outcome
            ).inc()
            raise
        finally:
            _LATENCY.labels("search", cfg.backend).observe(
                time.perf_counter() - t0
            )
        _SEARCH_COUNTER.labels(
            "search", cfg.backend, profile.name, outcome
        ).inc()
        if res.blocked:
            _BLOCKED.labels(profile.name).inc(res.blocked)
        return res.to_dict()

    @app.post("/research")
    def research(
        body: ResearchRequest, _auth: None = Depends(require_api_key)
    ) -> dict[str, Any]:
        profile = _resolve_profile(body.profile)
        t0 = time.perf_counter()
        try:
            res = backend.research(
                body.queries,
                profile=profile,
                freshness=body.freshness,
                max_results=body.max_results_per_query,
                fetch_full_text=body.fetch_full_text,
                intent=body.intent,
            )
            outcome = "ok"
        except Exception:
            outcome = "error"
            _SEARCH_COUNTER.labels(
                "research", cfg.backend, profile.name, outcome
            ).inc()
            raise
        finally:
            _LATENCY.labels("research", cfg.backend).observe(
                time.perf_counter() - t0
            )
        _SEARCH_COUNTER.labels(
            "research", cfg.backend, profile.name, outcome
        ).inc()
        if res.blocked:
            _BLOCKED.labels(profile.name).inc(res.blocked)
        return res.to_dict()

    @app.post("/research_intelligent")
    def research_intelligent(
        body: IntelligentResearchRequest,
        _auth: None = Depends(require_api_key),
    ) -> dict[str, Any]:
        profile = _resolve_profile(body.profile)
        t0 = time.perf_counter()
        # 1) Sub-query fan-out.
        expansion = app.state.expander.expand(
            body.goal, intent=body.intent, strategy=body.expansion_strategy,
        )
        sub_queries = expansion.sub_queries or [body.goal]
        # 2) Multi-query research, with host-side intent routing.
        try:
            res = backend.research(
                sub_queries,
                profile=profile,
                freshness=body.freshness,
                max_results=body.max_results_per_query,
                fetch_full_text=body.fetch_full_text,
                intent=body.intent,
            )
        except Exception:
            _SEARCH_COUNTER.labels(
                "research_intelligent", cfg.backend, profile.name, "error"
            ).inc()
            raise
        finally:
            _LATENCY.labels("research_intelligent", cfg.backend).observe(
                time.perf_counter() - t0
            )
        # 3) Cross-encoder rerank.
        rerank = app.state.reranker.rerank(
            body.goal, list(res.results), top_k=body.rerank_top_k,
        )
        # 4) Chunk-and-cite.
        citations: list[dict[str, Any]] = []
        if body.chunk_cite:
            citations = [
                c.to_dict()
                for c in app.state.chunker.cite(
                    body.goal, rerank.hits, scorer=app.state.reranker,
                )
            ]
        _SEARCH_COUNTER.labels(
            "research_intelligent", cfg.backend, profile.name, "ok"
        ).inc()
        if res.blocked:
            _BLOCKED.labels(profile.name).inc(res.blocked)
        return {
            "goal": body.goal,
            "intent": body.intent,
            "backend": res.backend,
            "profile": res.profile,
            "expansion": {
                "strategy": expansion.strategy,
                "sub_queries": expansion.sub_queries,
            },
            "rerank": {
                "model": rerank.model,
                "candidates_in": rerank.candidates_in,
                "candidates_out": rerank.candidates_out,
                "latency_ms": rerank.latency_ms,
            },
            "results": [h.to_dict() for h in rerank.hits],
            "blocked": res.blocked,
            "latency_ms": (time.perf_counter() - t0) * 1000.0,
            "citations": citations,
        }

    @app.post("/vendor_profile")
    def vendor_profile(
        body: VendorProfileRequest,
        _auth: None = Depends(require_api_key),
    ) -> dict[str, Any]:
        profile = _resolve_profile(body.profile)
        # Vendor intent gives the host-side router the "vendor" engine
        # ordering (privacy policies, DPAs, subprocessor lists).
        sub_queries = [
            f"{body.vendor} privacy policy",
            f"{body.vendor} subprocessors list",
            f"{body.vendor} data processing addendum",
            f"{body.vendor} security whitepaper certifications",
        ]
        res = backend.research(
            sub_queries,
            profile=profile,
            freshness="any",
            max_results=body.max_results,
            fetch_full_text=True,
            intent="vendor",
        )
        # Bucket hits by signal.
        buckets: dict[str, list[dict[str, Any]]] = {
            "privacy_policy": [],
            "subprocessors": [],
            "dpa": [],
            "security": [],
            "other": [],
        }
        for h in res.results:
            label = (h.title + " " + h.snippet + " " + h.url).lower()
            if "subprocess" in label:
                buckets["subprocessors"].append(h.to_dict())
            elif "data processing" in label or "/dpa" in label or "dpa.pdf" in label:
                buckets["dpa"].append(h.to_dict())
            elif "privacy" in label and "policy" in label:
                buckets["privacy_policy"].append(h.to_dict())
            elif (
                "security" in label or "iso 27001" in label or "soc 2" in label
            ):
                buckets["security"].append(h.to_dict())
            else:
                buckets["other"].append(h.to_dict())
        return {
            "vendor": body.vendor,
            "profile": res.profile,
            "backend": res.backend,
            "buckets": buckets,
            "blocked": res.blocked,
            "latency_ms": res.latency_ms,
        }

    @app.post("/research_agent")
    def research_agent(
        body: IntelligentResearchRequest,
        _auth: None = Depends(require_api_key),
    ) -> dict[str, Any]:
        """Agentic web-research loop with reasoning-driven coverage expansion."""
        profile = _resolve_profile(body.profile)
        t0 = time.perf_counter()
        agent = ResearchAgent(
            backend=backend,
            profile=profile,
            expander=app.state.expander,
            reranker=app.state.reranker,
            chunker=app.state.chunker,
            reasoning_client=app.state.reasoning_client,
        )
        state = agent.run(
            goal=body.goal,
            intent=body.intent,
            freshness=body.freshness,
            max_results_per_query=body.max_results_per_query,
            rerank_top_k=body.rerank_top_k,
            fetch_full_text=body.fetch_full_text,
            chunk_cite=body.chunk_cite,
        )
        _SEARCH_COUNTER.labels(
            "research_agent", cfg.backend, profile.name, "ok"
        ).inc()
        if state.hits:
            _LATENCY.labels("research_agent", cfg.backend).observe(
                time.perf_counter() - t0
            )
        return {
            "goal": body.goal,
            "intent": body.intent,
            "backend": cfg.backend,
            "profile": profile.name,
            "coverage_score": state.coverage_score,
            "iterations": state.iterations,
            "gaps": state.gaps,
            "events": state.events,
            "expansion": {
                "sub_queries": list(state.sub_queries),
            },
            "results": [h.to_dict() for h in state.hits],
            "citations": state.citations,
            "latency_ms": (time.perf_counter() - t0) * 1000.0,
        }

    @app.post("/compare_documents")
    def compare_documents(
        body: CompareDocumentsRequest,
        _auth: None = Depends(require_api_key),
    ) -> dict[str, Any]:
        profile = _resolve_profile(body.profile)
        # Per-document fetch via the local backend's full-text helper
        # to keep the seam thin. Every backend exposes _fill_full_text.
        from .backends import SearchHit  # noqa: WPS433 (intentional inline)

        hits: list[SearchHit] = []
        for url in body.documents:
            hits.append(
                SearchHit(
                    title=url,
                    url=url,
                    snippet="",
                    domain=url,
                    trust_tier=2,
                    weight=1.0,
                    blocked=False,
                )
            )
        try:
            backend._fill_full_text(hits)  # noqa: SLF001
        except Exception:  # noqa: BLE001
            logger.exception("compare_documents: full-text fetch failed")
        # Build claim matrix: claim → doc_url → best chunk score.
        chunker = app.state.chunker
        scorer = app.state.reranker
        matrix: dict[str, dict[str, dict[str, Any]]] = {}
        for claim in body.claims or [""]:
            row: dict[str, dict[str, Any]] = {}
            cites = chunker.cite(claim or "summary", hits, scorer=scorer,
                                 top_k_per_hit=1)
            for c in cites:
                row[c.url] = {
                    "score": c.score,
                    "excerpt": c.excerpt[:600],
                    "chunk_index": c.chunk_index,
                    "citation_id": c.citation_id,
                }
            matrix[claim or "summary"] = row
        return {
            "documents": body.documents,
            "claims": body.claims,
            "matrix": matrix,
            "profile": profile.name,
        }

    @app.post("/feedback")
    def feedback(
        body: FeedbackRequest,
        _auth: None = Depends(require_api_key),
    ) -> dict[str, Any]:
        """Forward feedback to the SearXNG host's learning reranker.

        The main agent calls this at end-of-run for each cited web hit
        so the host-side learning loop closes (PHASE_7 §7.15).
        """
        target = os.environ.get("CRP_COMPLY_SEARXNG_URL", "").rstrip("/")
        if not target:
            return {"ok": False, "reason": "searxng_url_unset"}
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(
                    f"{target}/crp/feedback",
                    json=body.model_dump(),
                )
            return {"ok": resp.status_code == 200, "status": resp.status_code}
        except Exception as exc:  # noqa: BLE001
            logger.warning("feedback forward failed: %s", exc)
            return {"ok": False, "reason": "forward_error"}

    return app
