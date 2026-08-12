"""Web search backends for the sidecar (PHASE_7 \u00a77.8 / \u00a716.2).

Three backends ship:

* :class:`LocalDDGBackend` (default) \u2014 ``ddgs`` library + ``httpx``
  full-page fetch + BeautifulSoup text extraction. Free, on-prem,
  rate-limited via :class:`DDGRateLimiter`.
* :class:`BraveBackend` \u2014 stub. Raises :class:`BackendDisabledError`
  unless ``CRP_COMPLY_ENABLE_BRAVE=1`` *and* an API key is set.
* :class:`TavilyBackend` \u2014 stub. Raises :class:`BackendDisabledError`
  unless ``CRP_COMPLY_ENABLE_TAVILY=1`` *and* an API key is set.

All three return a :class:`SearchResult` envelope. Trust-tier
filtering is applied uniformly here so the FastAPI layer doesn't
have to care which backend was used.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Protocol, runtime_checkable
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from .profiles import TrustTierProfile
from .rate_limiter import DDGRateLimiter


logger = logging.getLogger(__name__)


__all__ = [
    "BackendDisabledError",
    "BraveBackend",
    "LocalDDGBackend",
    "SearchHit",
    "SearchResult",
    "SearXNGBackend",
    "TavilyBackend",
    "WebSearchBackend",
    "apply_trust_tier",
]


Freshness = Literal["any", "day", "week", "month"]
BackendName = Literal["local", "brave", "tavily", "searxng"]


# ── Errors ───────────────────────────────────────────────────────────


class BackendDisabledError(RuntimeError):
    """Raised when a backend is requested but not enabled.

    Per PHASE_7 \u00a721 7.8: "do not silently fall back to local". The
    sidecar must surface this to the caller, who should fail loudly.
    """


# ── Result types ─────────────────────────────────────────────────────


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str
    domain: str
    trust_tier: int
    weight: float
    blocked: bool
    full_text: str = ""
    content_hash: str = ""
    raw_text_blob_id: str = ""
    fetched_at: float = 0.0
    published_at: float | None = None
    citation_id: str = ""

    def to_event_hit(self) -> dict[str, Any]:
        """Compact form for ``loop.web.result`` events."""
        return {
            "domain": self.domain,
            "trust_tier": self.trust_tier,
            "url": self.url,
            "title": self.title,
            "blocked": self.blocked,
        }


@dataclass
class SearchResult:
    query: str
    backend: BackendName
    profile: str
    results: list[SearchHit] = field(default_factory=list)
    blocked: int = 0
    latency_ms: float = 0.0
    quota_remaining: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "backend": self.backend,
            "profile": self.profile,
            "results": [h.__dict__ for h in self.results],
            "blocked": self.blocked,
            "latency_ms": self.latency_ms,
            "quota_remaining": self.quota_remaining,
        }


# ── Protocol ─────────────────────────────────────────────────────────


@runtime_checkable
class WebSearchBackend(Protocol):
    name: BackendName

    def search(
        self,
        query: str,
        *,
        profile: TrustTierProfile,
        freshness: Freshness = "any",
        max_results: int = 10,
        fetch_full_text: bool = True,
        intent: str | None = None,
    ) -> SearchResult: ...

    def research(
        self,
        queries: Iterable[str],
        *,
        profile: TrustTierProfile,
        freshness: Freshness = "any",
        max_results: int = 10,
        fetch_full_text: bool = True,
        intent: str | None = None,
    ) -> SearchResult: ...


# ── Trust-tier filter ────────────────────────────────────────────────


def apply_trust_tier(
    raw_hits: list[SearchHit], profile: TrustTierProfile
) -> tuple[list[SearchHit], int]:
    """Tag each hit with tier/weight/blocked, drop blocked, sort by
    (-weight, original-order). Returns (kept_hits, blocked_count).

    Per PHASE_7 \u00a721 7.8 we *never* return blocked hits to the caller;
    we only count them for telemetry.
    """
    kept: list[tuple[float, int, SearchHit]] = []
    blocked = 0
    for idx, hit in enumerate(raw_hits):
        host = _hostname_of(hit.url) or hit.domain
        tier, weight, is_blocked = profile.classify(host)
        hit.domain = host or hit.domain
        hit.trust_tier = tier
        hit.weight = weight
        hit.blocked = is_blocked
        if is_blocked:
            blocked += 1
            continue
        kept.append((weight, idx, hit))
    kept.sort(key=lambda t: (-t[0], t[1]))
    return [h for _, _, h in kept], blocked


def _hostname_of(url: str) -> str:
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host.lower()


# ── Local DDG backend ────────────────────────────────────────────────


@dataclass
class LocalDDGBackend:
    """Free / on-prem backend using ``ddgs`` + httpx.

    *limiter* is shared across the process so all routes see the
    same 1.2 s minimum delay.
    """

    name: BackendName = "local"
    limiter: DDGRateLimiter = field(default_factory=DDGRateLimiter)
    fetch_timeout: float = 15.0
    user_agent: str = "crp-comply-search/0.1 (+https://crp-comply.local)"
    max_full_text_bytes: int = 200_000

    # ---- public API ------------------------------------------------

    def search(
        self,
        query: str,
        *,
        profile: TrustTierProfile,
        freshness: Freshness = "any",
        max_results: int = 10,
        fetch_full_text: bool = True,
        intent: str | None = None,  # ignored \u2014 only SearXNG host routes by intent
    ) -> SearchResult:
        t0 = time.perf_counter()
        raw = self._ddg_search(query, freshness, max_results)
        if fetch_full_text:
            self._fill_full_text(raw)
        kept, blocked = apply_trust_tier(raw, profile)
        for h in kept:
            h.citation_id = f"web:{uuid.uuid4().hex[:12]}"
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return SearchResult(
            query=query,
            backend=self.name,
            profile=profile.name,
            results=kept,
            blocked=blocked,
            latency_ms=elapsed_ms,
        )

    def research(
        self,
        queries: Iterable[str],
        *,
        profile: TrustTierProfile,
        freshness: Freshness = "any",
        max_results: int = 10,
        fetch_full_text: bool = True,
        intent: str | None = None,
    ) -> SearchResult:
        merged: dict[str, SearchHit] = {}
        first_query = ""
        blocked_total = 0
        t0 = time.perf_counter()
        for q in queries:
            if not first_query:
                first_query = q
            sub = self.search(
                q, profile=profile, freshness=freshness,
                max_results=max_results, fetch_full_text=fetch_full_text,
            )
            blocked_total += sub.blocked
            for h in sub.results:
                key = h.content_hash or h.url
                if not key or key in merged:
                    continue
                merged[key] = h
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        ranked = sorted(merged.values(), key=lambda h: -h.weight)
        return SearchResult(
            query=first_query,
            backend=self.name,
            profile=profile.name,
            results=ranked,
            blocked=blocked_total,
            latency_ms=elapsed_ms,
        )

    # ---- internals ------------------------------------------------

    def _ddg_search(
        self, query: str, freshness: Freshness, max_results: int
    ) -> list[SearchHit]:
        self.limiter.acquire()
        try:
            from ddgs import DDGS  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "ddgs not installed; run pip install ddgs"
            ) from exc
        timelimit_map = {"any": None, "day": "d", "week": "w", "month": "m"}
        out: list[SearchHit] = []
        with DDGS() as ddgs:
            for r in ddgs.text(
                query,
                max_results=max_results,
                timelimit=timelimit_map.get(freshness),
                safesearch="moderate",
            ):
                url = r.get("href") or r.get("url") or ""
                title = r.get("title") or ""
                snippet = r.get("body") or r.get("snippet") or ""
                if not url:
                    continue
                out.append(SearchHit(
                    title=title,
                    url=url,
                    snippet=snippet,
                    domain=_hostname_of(url),
                    trust_tier=4,
                    weight=0.0,
                    blocked=False,
                ))
        return out

    def _fill_full_text(self, hits: list[SearchHit]) -> None:
        if not hits:
            return
        with httpx.Client(
            timeout=self.fetch_timeout,
            headers={"User-Agent": self.user_agent},
            follow_redirects=True,
            limits=httpx.Limits(max_connections=4),
        ) as client:
            for hit in hits:
                self._fetch_one(client, hit)

    def _fetch_one(self, client: httpx.Client, hit: SearchHit) -> None:
        try:
            resp = client.get(hit.url)
            if resp.status_code >= 400:
                return
            body = resp.text or ""
            if len(body) > self.max_full_text_bytes:
                body = body[: self.max_full_text_bytes]
            text = _extract_text(body)
            hit.full_text = text
            digest = hashlib.sha256(body.encode("utf-8", "ignore")).hexdigest()
            hit.content_hash = digest
            hit.raw_text_blob_id = f"sha256:{digest}"
            hit.fetched_at = time.time()
        except Exception:
            logger.debug("fetch failed for %s", hit.url, exc_info=True)


def _extract_text(html: str) -> str:
    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(" ", strip=True)
    except Exception:
        return ""
    return " ".join(text.split())


# ── SearXNG backend ──────────────────────────────────────────────────


@dataclass
class SearXNGBackend:
    """Free meta-search backend powered by a SearXNG instance.

    SearXNG (`<https://github.com/searxng/searxng>`__, AGPL-3.0)
    aggregates Bing, Google, DuckDuckGo, Mojeek, Wikipedia and ~80 other
    engines into a single privacy-preserving JSON API.  Operators can
    self-host (``docker run searxng/searxng``) or point at any of the 60+
    public instances listed at https://searx.space.

    Configuration (all read at construction time):

    * ``CRP_COMPLY_SEARXNG_URL`` — base URL, e.g.
      ``https://baresearch.org`` or ``http://localhost:8080``. **Required**.
    * ``CRP_COMPLY_SEARXNG_ENGINES`` — comma-separated upstream engine
      list (default: ``bing,duckduckgo,mojeek,wikipedia``).  Restricting
      the engine list both speeds up and stabilises results.
    * ``CRP_COMPLY_SEARXNG_TIMEOUT`` — float seconds (default 15).

    Output is normalised into :class:`SearchHit` records and run through
    :func:`apply_trust_tier`, so it slots in interchangeably with the
    DDG backend.  ``research()`` deduplicates across sub-queries by
    ``content_hash`` (mirroring :class:`LocalDDGBackend`).

    This backend never sends API keys, never funds a paid provider, and
    leaks no tenant identifier to the upstream — the perfect
    "completely free" replacement for Tavily / Brave for compliance
    research.
    """

    name: BackendName = "searxng"
    base_url: str = ""
    engines: str = ""
    timeout: float = 15.0
    user_agent: str = "crp-comply-search/0.1 (+https://crp-comply.local)"
    fetch_full_text: bool = False  # JSON snippets often suffice
    max_full_text_bytes: int = 200_000

    def __post_init__(self) -> None:
        if not self.base_url:
            self.base_url = os.environ.get("CRP_COMPLY_SEARXNG_URL", "").strip()
        if not self.base_url:
            raise BackendDisabledError(
                "SearXNG backend enabled but CRP_COMPLY_SEARXNG_URL is not set."
            )
        self.base_url = self.base_url.rstrip("/")
        if not self.engines:
            self.engines = os.environ.get(
                "CRP_COMPLY_SEARXNG_ENGINES",
                "bing,duckduckgo,mojeek,wikipedia",
            )
        env_timeout = os.environ.get("CRP_COMPLY_SEARXNG_TIMEOUT")
        if env_timeout:
            try:
                self.timeout = float(env_timeout)
            except ValueError:
                pass

    # ---- public API -----------------------------------------------

    def search(
        self,
        query: str,
        *,
        profile: TrustTierProfile,
        freshness: Freshness = "any",
        max_results: int = 10,
        fetch_full_text: bool | None = None,
        intent: str | None = None,
    ) -> SearchResult:
        t0 = time.perf_counter()
        raw = self._searxng_query(query, freshness, max_results, intent)
        do_fetch = self.fetch_full_text if fetch_full_text is None else fetch_full_text
        if do_fetch:
            self._fill_full_text(raw)
        kept, blocked = apply_trust_tier(raw, profile)
        for h in kept:
            h.citation_id = f"web:{uuid.uuid4().hex[:12]}"
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return SearchResult(
            query=query,
            backend=self.name,
            profile=profile.name,
            results=kept,
            blocked=blocked,
            latency_ms=elapsed_ms,
        )

    def research(
        self,
        queries: Iterable[str],
        *,
        profile: TrustTierProfile,
        freshness: Freshness = "any",
        max_results: int = 10,
        fetch_full_text: bool | None = None,
        intent: str | None = None,
    ) -> SearchResult:
        merged: dict[str, SearchHit] = {}
        first_query = ""
        blocked_total = 0
        t0 = time.perf_counter()
        for q in queries:
            if not first_query:
                first_query = q
            sub = self.search(
                q, profile=profile, freshness=freshness,
                max_results=max_results, fetch_full_text=fetch_full_text,
                intent=intent,
            )
            blocked_total += sub.blocked
            for h in sub.results:
                key = h.content_hash or h.url
                if not key or key in merged:
                    continue
                merged[key] = h
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        ranked = sorted(merged.values(), key=lambda h: -h.weight)
        return SearchResult(
            query=first_query,
            backend=self.name,
            profile=profile.name,
            results=ranked,
            blocked=blocked_total,
            latency_ms=elapsed_ms,
        )

    # ---- internals ------------------------------------------------

    def _searxng_query(
        self, query: str, freshness: Freshness, max_results: int,
        intent: str | None = None,
    ) -> list[SearchHit]:
        time_range_map = {"any": "", "day": "day", "week": "week", "month": "month"}
        params: dict[str, str] = {
            "q": query,
            "format": "json",
            "safesearch": "1",
            "language": "en",
        }
        # When an intent is supplied, hand engine selection over to the
        # SearXNG host-side router plugin (see crp-comply-searxng). When
        # not, fall back to the static engine list (legacy / public
        # SearXNG instances without our plugin installed).
        if intent:
            params["crp_intent"] = intent
        elif self.engines:
            params["engines"] = self.engines
        tr = time_range_map.get(freshness, "")
        if tr:
            params["time_range"] = tr
        try:
            with httpx.Client(
                timeout=self.timeout,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "application/json",
                },
                follow_redirects=True,
            ) as client:
                resp = client.get(f"{self.base_url}/search", params=params)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("SearXNG request failed: %s", exc)
            return []
        except ValueError as exc:
            logger.warning("SearXNG returned non-JSON: %s", exc)
            return []

        rows = data.get("results") or []
        out: list[SearchHit] = []
        for r in rows[:max_results]:
            url = r.get("url") or ""
            if not url:
                continue
            title = r.get("title") or ""
            snippet = r.get("content") or r.get("snippet") or ""
            out.append(SearchHit(
                title=title,
                url=url,
                snippet=snippet,
                domain=_hostname_of(url),
                trust_tier=4,
                weight=0.0,
                blocked=False,
            ))
        return out

    def _fill_full_text(self, hits: list[SearchHit]) -> None:
        if not hits:
            return
        with httpx.Client(
            timeout=self.timeout,
            headers={"User-Agent": self.user_agent},
            follow_redirects=True,
            limits=httpx.Limits(max_connections=4),
        ) as client:
            for hit in hits:
                try:
                    resp = client.get(hit.url)
                    if resp.status_code >= 400:
                        continue
                    body = resp.text or ""
                    if len(body) > self.max_full_text_bytes:
                        body = body[: self.max_full_text_bytes]
                    text = _extract_text(body)
                    hit.full_text = text
                    digest = hashlib.sha256(
                        body.encode("utf-8", "ignore")
                    ).hexdigest()
                    hit.content_hash = digest
                    hit.raw_text_blob_id = f"sha256:{digest}"
                    hit.fetched_at = time.time()
                except Exception:
                    logger.debug("fetch failed for %s", hit.url, exc_info=True)


# ── Stub backends ────────────────────────────────────────────────────


@dataclass
class BraveBackend:
    """Brave Search API backend.

    Per PHASE_7 \u00a721 7.8 / \u00a716.2: instantiating this without
    ``CRP_COMPLY_ENABLE_BRAVE=1`` raises :class:`BackendDisabledError`
    so the operator gets a *loud* failure at startup if a tenant
    requested Brave but didn't enable it.
    """

    name: BackendName = "brave"
    api_key: str | None = None
    timeout: float = 15.0
    user_agent: str = "crp-comply-search/0.1"
    max_full_text_bytes: int = 200_000

    def __post_init__(self) -> None:
        enabled = os.environ.get("CRP_COMPLY_ENABLE_BRAVE", "").lower() in (
            "1", "true", "yes", "on"
        )
        if not enabled:
            raise BackendDisabledError(
                "Brave backend disabled. Set CRP_COMPLY_ENABLE_BRAVE=1 "
                "and supply BRAVE_API_KEY to enable. (PHASE_7 \u00a716.2)"
            )
        if not self.api_key:
            raise BackendDisabledError(
                "Brave backend enabled but BRAVE_API_KEY missing."
            )

    def search(
        self,
        query: str,
        *,
        profile: TrustTierProfile,
        freshness: Freshness = "any",
        max_results: int = 10,
        fetch_full_text: bool = True,
        intent: str | None = None,  # noqa: ARG002
    ) -> SearchResult:
        t0 = time.perf_counter()
        raw = self._brave_search(query, freshness, max_results)
        if fetch_full_text:
            self._fill_full_text(raw)
        kept, blocked = apply_trust_tier(raw, profile)
        for h in kept:
            h.citation_id = f"web:{uuid.uuid4().hex[:12]}"
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return SearchResult(
            query=query,
            backend=self.name,
            profile=profile.name,
            results=kept,
            blocked=blocked,
            latency_ms=elapsed_ms,
        )

    def research(
        self,
        queries: Iterable[str],
        *,
        profile: TrustTierProfile,
        freshness: Freshness = "any",
        max_results: int = 10,
        fetch_full_text: bool = True,
        intent: str | None = None,  # noqa: ARG002
    ) -> SearchResult:
        all_hits: list[SearchHit] = []
        for q in queries:
            res = self.search(
                q,
                profile=profile,
                freshness=freshness,
                max_results=max_results,
                fetch_full_text=fetch_full_text,
            )
            all_hits.extend(res.results)
        # Deduplicate by URL, keeping the first (highest-weight) occurrence.
        seen: set[str] = set()
        deduped: list[SearchHit] = []
        for h in all_hits:
            if h.url in seen:
                continue
            seen.add(h.url)
            deduped.append(h)
        return SearchResult(
            query="; ".join(queries),
            backend=self.name,
            profile=profile.name,
            results=deduped,
            blocked=0,
            latency_ms=0.0,
        )

    def _brave_search(
        self, query: str, freshness: Freshness, max_results: int
    ) -> list[SearchHit]:
        time_range_map: dict[Freshness, str] = {
            "day": "d",
            "week": "w",
            "month": "m",
        }
        params: dict[str, Any] = {
            "q": query,
            "count": min(max_results, 20),
            "offset": 0,
        }
        tr = time_range_map.get(freshness, "")
        if tr:
            params["freshness"] = tr
        try:
            with httpx.Client(
                timeout=self.timeout,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "application/json",
                    "X-Subscription-Token": self.api_key or "",
                },
            ) as client:
                resp = client.get(
                    "https://api.search.brave.com/res/v1/web/search", params=params
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("Brave request failed: %s", exc)
            return []
        except ValueError as exc:
            logger.warning("Brave returned non-JSON: %s", exc)
            return []

        rows = (data.get("web") or {}).get("results") or []
        out: list[SearchHit] = []
        for r in rows[:max_results]:
            url = r.get("url") or ""
            if not url:
                continue
            out.append(SearchHit(
                title=r.get("title") or "",
                url=url,
                snippet=r.get("description") or "",
                domain=_hostname_of(url),
                trust_tier=4,
                weight=0.0,
                blocked=False,
            ))
        return out

    def _fill_full_text(self, hits: list[SearchHit]) -> None:
        if not hits:
            return
        with httpx.Client(
            timeout=self.timeout,
            headers={"User-Agent": self.user_agent},
            follow_redirects=True,
            limits=httpx.Limits(max_connections=4),
        ) as client:
            for hit in hits:
                try:
                    resp = client.get(hit.url)
                    if resp.status_code >= 400:
                        continue
                    body = resp.text or ""
                    if len(body) > self.max_full_text_bytes:
                        body = body[: self.max_full_text_bytes]
                    hit.full_text = _extract_text(body)
                    digest = hashlib.sha256(body.encode("utf-8", "ignore")).hexdigest()
                    hit.content_hash = digest
                    hit.raw_text_blob_id = f"sha256:{digest}"
                    hit.fetched_at = time.time()
                except Exception:
                    logger.debug("fetch failed for %s", hit.url, exc_info=True)


@dataclass
class TavilyBackend:
    """Tavily search API backend (research-grade aggregator)."""

    name: BackendName = "tavily"
    api_key: str | None = None
    timeout: float = 20.0
    user_agent: str = "crp-comply-search/0.1"

    def __post_init__(self) -> None:
        enabled = os.environ.get("CRP_COMPLY_ENABLE_TAVILY", "").lower() in (
            "1", "true", "yes", "on"
        )
        if not enabled:
            raise BackendDisabledError(
                "Tavily backend disabled. Set CRP_COMPLY_ENABLE_TAVILY=1 "
                "and supply TAVILY_API_KEY to enable. (PHASE_7 \u00a716.2)"
            )
        if not self.api_key:
            raise BackendDisabledError(
                "Tavily backend enabled but TAVILY_API_KEY missing."
            )

    def search(
        self,
        query: str,
        *,
        profile: TrustTierProfile,
        freshness: Freshness = "any",
        max_results: int = 10,
        fetch_full_text: bool = True,  # noqa: ARG002
        intent: str | None = None,  # noqa: ARG002
    ) -> SearchResult:
        t0 = time.perf_counter()
        raw = self._tavily_search(query, freshness, max_results)
        kept, blocked = apply_trust_tier(raw, profile)
        for h in kept:
            h.citation_id = f"web:{uuid.uuid4().hex[:12]}"
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return SearchResult(
            query=query,
            backend=self.name,
            profile=profile.name,
            results=kept,
            blocked=blocked,
            latency_ms=elapsed_ms,
        )

    def research(
        self,
        queries: Iterable[str],
        *,
        profile: TrustTierProfile,
        freshness: Freshness = "any",
        max_results: int = 10,
        fetch_full_text: bool = True,  # noqa: ARG002
        intent: str | None = None,  # noqa: ARG002
    ) -> SearchResult:
        all_hits: list[SearchHit] = []
        for q in queries:
            res = self.search(
                q,
                profile=profile,
                freshness=freshness,
                max_results=max_results,
            )
            all_hits.extend(res.results)
        seen: set[str] = set()
        deduped: list[SearchHit] = []
        for h in all_hits:
            if h.url in seen:
                continue
            seen.add(h.url)
            deduped.append(h)
        return SearchResult(
            query="; ".join(queries),
            backend=self.name,
            profile=profile.name,
            results=deduped,
            blocked=0,
            latency_ms=0.0,
        )

    def _tavily_search(
        self, query: str, freshness: Freshness, max_results: int
    ) -> list[SearchHit]:
        time_range_map: dict[Freshness, str] = {
            "day": "day",
            "week": "week",
            "month": "month",
        }
        payload: dict[str, Any] = {
            "query": query,
            "search_depth": "advanced",
            "max_results": min(max_results, 20),
            "include_answer": False,
            "include_raw_content": False,
        }
        tr = time_range_map.get(freshness, "")
        if tr:
            payload["time_range"] = tr
        try:
            with httpx.Client(
                timeout=self.timeout,
                headers={
                    "User-Agent": self.user_agent,
                    "Content-Type": "application/json",
                },
            ) as client:
                resp = client.post(
                    "https://api.tavily.com/search",
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("Tavily request failed: %s", exc)
            return []
        except ValueError as exc:
            logger.warning("Tavily returned non-JSON: %s", exc)
            return []

        rows = data.get("results") or []
        out: list[SearchHit] = []
        for r in rows[:max_results]:
            url = r.get("url") or ""
            if not url:
                continue
            out.append(SearchHit(
                title=r.get("title") or "",
                url=url,
                snippet=r.get("content") or "",
                domain=_hostname_of(url),
                trust_tier=4,
                weight=0.0,
                blocked=False,
                full_text=r.get("raw_content") or "",
            ))
        return out
