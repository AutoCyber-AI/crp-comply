# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""HTTP client for the ``crp-comply-search`` web-research sidecar.

The web-search sidecar runs as a separate Railway service (see
``services/crp-comply-search/``). This module is the single seam the
main API uses to call it. Keeping it small and dependency-light means
unit tests can stub it with a couple of monkeypatches.

Environment contract
--------------------
``CRP_COMPLY_SEARCH_URL``       — base URL of the sidecar (no trailing /).
``CRP_COMPLY_SEARCH_API_KEY``   — bearer token; sidecar refuses requests
                                  without it in production.

Phase 5b hardening
------------------
* Exponential-backoff retries (max 3 attempts) for network/timeout/5xx.
* Per-path circuit breaker to fail fast when the sidecar is down.
* In-memory TTL cache for ``/research_intelligent`` results.
* Distinct :class:`SidecarTimeoutError` so callers can fall back to
  corpus-only without losing the turn.

The /search and /research endpoints are documented in
``services/crp-comply-search/README.md``.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx

DEFAULT_TIMEOUT = 10.0
_RETRYABLE_STATUSES = {408, 429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_CIRCUIT_FAILURE_THRESHOLD = 5
_CIRCUIT_RESET_SECONDS = 30.0
_CACHE_TTL_SECONDS = 300.0


class SidecarError(RuntimeError):
    """Raised when the sidecar responds with a non-2xx status or is unreachable."""


class SidecarTimeoutError(SidecarError):
    """Raised when the sidecar does not respond before the configured timeout.

    Callers (e.g. :class:`crp_comply.agent.WebClient`) should catch this and
    return a structured fallback payload so the agent can continue with
    corpus-only retrieval instead of surfacing a raw exception to the LLM.
    """


@dataclass(frozen=True)
class SidecarConfig:
    base_url: str
    api_key: str | None
    timeout: float = DEFAULT_TIMEOUT
    allow_feedback: bool = True

    @classmethod
    def from_env(cls) -> "SidecarConfig":
        base = (os.environ.get("CRP_COMPLY_SEARCH_URL") or "").rstrip("/")
        if not base:
            raise SidecarError(
                "CRP_COMPLY_SEARCH_URL is not set — point it at the sidecar "
                "(e.g. http://crp-comply-search.railway.internal:8081)"
            )
        key = os.environ.get("CRP_COMPLY_SEARCH_API_KEY") or None
        allow = os.environ.get("CRP_COMPLY_SEARCH_ALLOW_FEEDBACK", "true").lower() not in {
            "false",
            "0",
            "no",
            "off",
        }
        return cls(base_url=base, api_key=key, allow_feedback=allow)


def _headers(cfg: SidecarConfig) -> dict[str, str]:
    h = {"content-type": "application/json"}
    if cfg.api_key:
        h["authorization"] = f"Bearer {cfg.api_key}"
    return h


class _CircuitBreaker:
    """Simple per-path circuit breaker."""

    def __init__(self) -> None:
        self._state: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _record(self, path: str) -> dict[str, Any]:
        return self._state.setdefault(path, {"failures": 0, "last_failure": 0.0, "open": False})

    def check(self, path: str) -> None:
        with self._lock:
            rec = self._record(path)
            if rec["open"]:
                if time.monotonic() - rec["last_failure"] > _CIRCUIT_RESET_SECONDS:
                    rec["open"] = False
                    rec["failures"] = 0
                else:
                    raise SidecarError(f"circuit open for sidecar path {path}")

    def success(self, path: str) -> None:
        with self._lock:
            rec = self._record(path)
            rec["failures"] = 0
            rec["open"] = False

    def failure(self, path: str) -> None:
        with self._lock:
            rec = self._record(path)
            rec["failures"] += 1
            rec["last_failure"] = time.monotonic()
            if rec["failures"] >= _CIRCUIT_FAILURE_THRESHOLD:
                rec["open"] = True


_circuit = _CircuitBreaker()


class _Cache:
    """In-memory TTL cache keyed by (path, serialized body)."""

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def _key(self, path: str, body: dict[str, Any]) -> str:
        return f"{path}:{json.dumps(body, sort_keys=True, default=str)}"

    def get(self, path: str, body: dict[str, Any]) -> dict[str, Any] | None:
        with self._lock:
            key = self._key(path, body)
            entry = self._store.get(key)
            if entry is None:
                return None
            ts, value = entry
            if time.monotonic() - ts > self._ttl:
                self._store.pop(key, None)
                return None
            return value

    def set(self, path: str, body: dict[str, Any], value: dict[str, Any]) -> None:
        with self._lock:
            self._store[self._key(path, body)] = (time.monotonic(), value)
            # Best-effort size cap: evict oldest 20 % when store grows large.
            if len(self._store) > 512:
                sorted_keys = sorted(self._store, key=lambda k: self._store[k][0])
                for k in sorted_keys[:128]:
                    self._store.pop(k, None)


_cache = _Cache(_CACHE_TTL_SECONDS)


def health(cfg: SidecarConfig | None = None) -> dict[str, Any]:
    """GET /health — liveness probe.

    Returns the parsed JSON body. Raises :class:`SidecarError` on
    network or non-2xx errors.
    """
    cfg = cfg or SidecarConfig.from_env()
    try:
        r = httpx.get(
            f"{cfg.base_url}/health",
            headers=_headers(cfg),
            timeout=cfg.timeout,
        )
    except httpx.HTTPError as exc:
        raise SidecarError(f"network error: {exc}") from exc
    if r.status_code >= 400:
        raise SidecarError(f"/health returned {r.status_code}: {r.text[:200]}")
    return r.json()


def search(
    query: str,
    *,
    profile: str | None = None,
    freshness: str = "any",
    max_results: int = 10,
    fetch_full_text: bool = False,
    intent: str | None = None,
    cfg: SidecarConfig | None = None,
) -> dict[str, Any]:
    """POST /search — single web query.

    ``fetch_full_text`` defaults to ``False`` here (vs True on the
    sidecar) because the main API typically only needs the metadata
    bundle to feed into the orchestrator's CKF/citation layer; the
    full-text fetch is opt-in to keep latency predictable.
    """
    cfg = cfg or SidecarConfig.from_env()
    body: dict[str, Any] = {
        "query": query,
        "freshness": freshness,
        "max_results": int(max_results),
        "fetch_full_text": bool(fetch_full_text),
    }
    if profile:
        body["profile"] = profile
    if intent:
        body["intent"] = intent
    return _post(cfg, "/search", body)


def research(
    queries: list[str],
    *,
    profile: str | None = None,
    freshness: str = "any",
    max_results_per_query: int = 8,
    fetch_full_text: bool = False,
    intent: str | None = None,
    cfg: SidecarConfig | None = None,
) -> dict[str, Any]:
    """POST /research — multi-query expansion."""
    cfg = cfg or SidecarConfig.from_env()
    body: dict[str, Any] = {
        "queries": list(queries),
        "freshness": freshness,
        "max_results_per_query": int(max_results_per_query),
        "fetch_full_text": bool(fetch_full_text),
    }
    if profile:
        body["profile"] = profile
    if intent:
        body["intent"] = intent
    return _post(cfg, "/research", body)


def research_intelligent(
    goal: str,
    *,
    intent: str = "general",
    profile: str | None = None,
    freshness: str = "any",
    max_results_per_query: int = 8,
    expansion_strategy: str = "templated",
    rerank_top_k: int = 6,
    fetch_full_text: bool = True,
    chunk_cite: bool = True,
    cfg: SidecarConfig | None = None,
) -> dict[str, Any]:
    """POST /research_intelligent — expand → search → rerank → cite."""
    cfg = cfg or SidecarConfig.from_env()
    body: dict[str, Any] = {
        "goal": goal,
        "intent": intent,
        "freshness": freshness,
        "max_results_per_query": int(max_results_per_query),
        "expansion_strategy": expansion_strategy,
        "rerank_top_k": int(rerank_top_k),
        "fetch_full_text": bool(fetch_full_text),
        "chunk_cite": bool(chunk_cite),
    }
    if profile:
        body["profile"] = profile
    cached = _cache.get("/research_intelligent", body)
    if cached is not None:
        cached["_cached"] = True
        return cached
    result = _post(cfg, "/research_intelligent", body)
    _cache.set("/research_intelligent", body, result)
    return result


def research_agent(
    goal: str,
    *,
    intent: str = "general",
    profile: str | None = None,
    freshness: str = "any",
    max_results_per_query: int = 8,
    rerank_top_k: int = 6,
    fetch_full_text: bool = True,
    chunk_cite: bool = True,
    cfg: SidecarConfig | None = None,
) -> dict[str, Any]:
    """POST /research_agent — iterative search-reason-cite loop."""
    cfg = cfg or SidecarConfig.from_env()
    body: dict[str, Any] = {
        "goal": goal,
        "intent": intent,
        "freshness": freshness,
        "max_results_per_query": int(max_results_per_query),
        "rerank_top_k": int(rerank_top_k),
        "fetch_full_text": bool(fetch_full_text),
        "chunk_cite": bool(chunk_cite),
    }
    if profile:
        body["profile"] = profile
    return _post(cfg, "/research_agent", body)


def research_by_depth(
    depth: str,
    goal: str,
    *,
    intent: str = "general",
    profile: str | None = None,
    freshness: str = "any",
    cfg: SidecarConfig | None = None,
) -> dict[str, Any]:
    """Unified depth selector: maps ``brief|standard|thorough`` to the right endpoint.

    * ``brief``      → :func:`search` (<3 s target).
    * ``standard``   → :func:`research_intelligent` (<5 s target).
    * ``thorough``   → :func:`research_agent` (<10 s target).

    On timeout or circuit-open, returns a structured fallback payload so
    the agent can continue with corpus-only retrieval.
    """
    d = (depth or "standard").lower()
    if d == "brief":
        return search(goal, intent=intent, profile=profile, freshness=freshness, cfg=cfg)
    if d == "thorough":
        return research_agent(goal, intent=intent, profile=profile, freshness=freshness, cfg=cfg)
    return research_intelligent(goal, intent=intent, profile=profile, freshness=freshness, cfg=cfg)


def vendor_profile(
    vendor: str,
    *,
    profile: str | None = None,
    max_results: int = 8,
    cfg: SidecarConfig | None = None,
) -> dict[str, Any]:
    """POST /vendor_profile — vendor due-diligence sweep."""
    cfg = cfg or SidecarConfig.from_env()
    body: dict[str, Any] = {"vendor": vendor, "max_results": int(max_results)}
    if profile:
        body["profile"] = profile
    return _post(cfg, "/vendor_profile", body)


def compare_documents(
    documents: list[str],
    *,
    claims: list[str] | None = None,
    profile: str | None = None,
    cfg: SidecarConfig | None = None,
) -> dict[str, Any]:
    """POST /compare_documents — claim-matrix across N documents."""
    cfg = cfg or SidecarConfig.from_env()
    body: dict[str, Any] = {
        "documents": list(documents),
        "claims": list(claims or []),
    }
    if profile:
        body["profile"] = profile
    return _post(cfg, "/compare_documents", body)


def feedback(
    *,
    intent: str,
    engine: str,
    useful: bool = True,
    weight: float = 1.0,
    url: str | None = None,
    query: str | None = None,
    cfg: SidecarConfig | None = None,
) -> dict[str, Any]:
    """POST /feedback — forwarded by sidecar to SearXNG learning DB.

    Extra fields (``url``, ``query``) are passed through so the learning
    reranker can attribute the signal to a specific result.
    """
    cfg = cfg or SidecarConfig.from_env()
    if not cfg.allow_feedback:
        return {"ok": False, "feedback_disabled": True}
    body: dict[str, Any] = {
        "intent": intent,
        "engine": engine,
        "useful": bool(useful),
        "weight": float(weight),
    }
    if url:
        body["url"] = url
    if query:
        body["query"] = query
    return _post(cfg, "/feedback", body)


def _post(cfg: SidecarConfig, path: str, body: dict[str, Any]) -> dict[str, Any]:
    _circuit.check(path)

    last_error: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        try:
            r = httpx.post(
                f"{cfg.base_url}{path}",
                headers=_headers(cfg),
                json=body,
                timeout=cfg.timeout,
            )
        except httpx.TimeoutException as exc:
            last_error = exc
            _circuit.failure(path)
            # Only retry timeouts if we have attempts left.
            if attempt < _MAX_RETRIES - 1:
                time.sleep(0.5 * (2**attempt))
                continue
            raise SidecarTimeoutError(
                json.dumps(
                    {
                        "error": "timeout",
                        "path": path,
                        "timeout_seconds": cfg.timeout,
                        "fallback": True,
                    }
                )
            ) from exc
        except httpx.HTTPError as exc:
            last_error = exc
            _circuit.failure(path)
            if attempt < _MAX_RETRIES - 1:
                time.sleep(0.5 * (2**attempt))
                continue
            raise SidecarError(f"network error: {exc}") from exc

        if r.status_code >= 400:
            if r.status_code in _RETRYABLE_STATUSES and attempt < _MAX_RETRIES - 1:
                _circuit.failure(path)
                time.sleep(0.5 * (2**attempt))
                continue
            if r.status_code >= 500:
                _circuit.failure(path)
            raise SidecarError(f"{path} returned {r.status_code}: {r.text[:200]}")

        _circuit.success(path)
        try:
            return r.json()
        except Exception as exc:  # pragma: no cover - malformed JSON is a sidecar bug
            raise SidecarError(f"{path} returned invalid JSON: {exc}") from exc

    # Should never be reached, but keeps mypy happy.
    raise SidecarError(f"{path} failed after {_MAX_RETRIES} attempts: {last_error}")


def self_check(cfg: SidecarConfig | None = None) -> dict[str, Any]:
    """End-to-end smoke test: /health + a one-shot /search.

    Returns ``{"ok": bool, "health": dict, "search": dict|None,
    "errors": list[str], "elapsed_ms": float}``. Never raises — this
    is the primitive the ``check-sidecar`` CLI uses to render a clean
    pass/fail report.
    """
    cfg = cfg or SidecarConfig.from_env()
    out: dict[str, Any] = {
        "ok": False,
        "base_url": cfg.base_url,
        "auth": "bearer" if cfg.api_key else "none",
        "health": None,
        "search": None,
        "errors": [],
    }
    t0 = time.perf_counter()
    try:
        out["health"] = health(cfg)
    except SidecarError as exc:
        out["errors"].append(f"health: {exc}")
        out["elapsed_ms"] = (time.perf_counter() - t0) * 1000.0
        return out
    try:
        # Use a benign legal-domain query so trust-tier filtering
        # actually exercises the profile pipeline.
        out["search"] = search("GDPR Article 6 lawful basis", cfg=cfg)
    except SidecarError as exc:
        out["errors"].append(f"search: {exc}")
        out["elapsed_ms"] = (time.perf_counter() - t0) * 1000.0
        return out
    out["ok"] = True
    out["elapsed_ms"] = (time.perf_counter() - t0) * 1000.0
    return out


__all__ = [
    "DEFAULT_TIMEOUT",
    "SidecarConfig",
    "SidecarError",
    "SidecarTimeoutError",
    "compare_documents",
    "feedback",
    "health",
    "research",
    "research_agent",
    "research_by_depth",
    "research_intelligent",
    "search",
    "self_check",
    "vendor_profile",
]
