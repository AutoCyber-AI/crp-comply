"""Shared scraper utilities."""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from typing import Iterable
from urllib.parse import urlparse

import httpx


logger = logging.getLogger("crp_comply.agent.scrapers")


class AsyncRenderRefused(RuntimeError):
    """Raised when an endpoint persistently returns HTTP 202 (JS-rendered)."""


USER_AGENT = "CRP-Comply-RegulationBot/0.1 (+https://crprotocol.io/products/comply)"
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


# ── Per-host min-delay registry (polite scraping) ─────────────
#
# PRODUCT_SECURITY.md §5 gap #2: enforce a minimum inter-request delay
# per origin so we never DoS a regulator's site. Defaults are conservative
# (2s for general hosts, 5s for EU eur-lex which rate-limits aggressively).
# Override with JSON in CRP_COMPLY_SCRAPER_DELAYS, e.g.:
#   {"eur-lex.europa.eu": 5.0, "nist.gov": 2.0, "default": 1.5}

_DEFAULT_DELAYS: dict[str, float] = {
    "default": 1.5,
    "eur-lex.europa.eu": 5.0,
    "ec.europa.eu": 3.0,
    "nist.gov": 2.0,
    "pages.nist.gov": 2.0,
    "edpb.europa.eu": 3.0,
    "oecd.org": 2.0,
    "coe.int": 2.0,
    "gov.uk": 2.0,
}


def _load_delays() -> dict[str, float]:
    import json as _json

    raw = os.getenv("CRP_COMPLY_SCRAPER_DELAYS")
    delays = dict(_DEFAULT_DELAYS)
    if raw:
        try:
            for k, v in _json.loads(raw).items():
                delays[k] = float(v)
        except Exception as exc:
            logger.warning("ignoring bad CRP_COMPLY_SCRAPER_DELAYS: %s", exc)
    return delays


_DELAYS: dict[str, float] = _load_delays()
_LAST_FETCH: dict[str, float] = {}
_DELAY_LOCK = threading.Lock()


def _delay_for(host: str) -> float:
    return _DELAYS.get(host, _DELAYS.get("default", 1.5))


def _wait_for_host(url: str) -> None:
    """Block until the per-host min delay since the last fetch has elapsed."""
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return
    if not host:
        return
    delay = _delay_for(host)
    with _DELAY_LOCK:
        last = _LAST_FETCH.get(host, 0.0)
        now = time.monotonic()
        wait = (last + delay) - now
        if wait > 0:
            time.sleep(wait)
        _LAST_FETCH[host] = time.monotonic()


def _reset_scraper_delays_for_tests() -> None:
    """Test helper: clear the per-host last-fetch registry."""
    global _DELAYS
    with _DELAY_LOCK:
        _LAST_FETCH.clear()
        _DELAYS = _load_delays()


def http_get(
    url: str,
    *,
    retries: int = 5,
    backoff: float = 2.0,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """GET with retries + exponential backoff + per-host politeness delay.

    Handles HTTP 202 (EUR-Lex async render) by re-fetching after a delay.
    """
    _wait_for_host(url)

    hdrs = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if headers:
        hdrs.update(headers)

    last_exc: Exception | None = None
    consecutive_202 = 0
    for attempt in range(retries):
        try:
            with httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=True) as client:
                resp = client.get(url, headers=hdrs)
                if resp.status_code == 202:
                    consecutive_202 += 1
                    if consecutive_202 >= 2:
                        # Non-retriable — caller should try an alternate URL.
                        raise AsyncRenderRefused(f"{url} kept returning 202 — likely JS-rendered")
                    wait = backoff**attempt
                    logger.info("fetch %s returned 202 — retry in %.1fs", url, wait)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp
        except AsyncRenderRefused:
            raise
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            last_exc = exc
            wait = backoff**attempt
            logger.warning(
                "fetch %s failed (attempt %d/%d): %s — retry in %.1fs",
                url,
                attempt + 1,
                retries,
                exc,
                wait,
            )
            time.sleep(wait)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"fetch {url} exhausted retries")


_WS_RE = re.compile(r"\s+")


def normalize_ws(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def split_paragraphs(text: str) -> list[str]:
    parts = re.split(r"\n\s*\n", text)
    return [normalize_ws(p) for p in parts if p.strip()]


def chunk_by_token_budget(
    text: str,
    *,
    max_tokens: int = 512,
    overlap: int = 50,
) -> list[str]:
    """Approximate token budgeting by word count (1 word ≈ 1.3 tokens)."""
    words = text.split()
    if not words:
        return []
    max_words = max(1, int(max_tokens / 1.3))
    step = max(1, max_words - int(overlap / 1.3))
    out: list[str] = []
    for start in range(0, len(words), step):
        piece = words[start : start + max_words]
        if not piece:
            break
        out.append(" ".join(piece))
        if start + max_words >= len(words):
            break
    return out


def safe_id(prefix: str, *parts: object) -> str:
    """Build a stable chunk id from source + section parts."""
    body = "_".join(str(p) for p in parts if p is not None)
    body = re.sub(r"[^A-Za-z0-9._-]+", "_", body)
    body = re.sub(r"_+", "_", body).strip("_")
    return f"{prefix}/{body}" if body else prefix


def iter_nonempty(lines: Iterable[str]) -> Iterable[str]:
    for line in lines:
        s = line.strip()
        if s:
            yield s
