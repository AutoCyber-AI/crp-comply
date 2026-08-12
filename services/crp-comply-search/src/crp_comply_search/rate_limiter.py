"""Per-process DDG rate limiter \u2014 PHASE_7 \u00a716.

DuckDuckGo throttles aggressively when more than ~1 query/sec is
issued from a single egress IP. We enforce a per-process minimum
delay between calls (default 1.2 s, tunable via
``CRP_COMPLY_SEARCH_DDG_DELAY``).

The limiter is sync-friendly (used inside FastAPI route handlers
that run on the threadpool) and async-friendly (the async fetch
path uses :meth:`acquire_async`).
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from dataclasses import dataclass, field


__all__ = ["DDGRateLimiter", "default_min_delay"]


def default_min_delay() -> float:
    raw = os.environ.get("CRP_COMPLY_SEARCH_DDG_DELAY")
    if not raw:
        return 1.2
    try:
        v = float(raw)
    except ValueError:
        return 1.2
    return max(0.0, v)


@dataclass
class DDGRateLimiter:
    """Single-token leaky-bucket: at most one call per ``min_delay``.

    Multiple threads/coroutines block until the previous call's
    timestamp + ``min_delay`` has passed. Non-reentrant; one
    instance is shared across the process.
    """

    min_delay: float = field(default_factory=default_min_delay)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _last_at: float = 0.0

    def acquire(self) -> float:
        """Block until the limiter allows a call. Returns the
        wait time in seconds (0 if no wait was needed)."""
        with self._lock:
            now = time.monotonic()
            wait = self._last_at + self.min_delay - now
            if wait > 0:
                time.sleep(wait)
                self._last_at = time.monotonic()
                return wait
            self._last_at = now
            return 0.0

    async def acquire_async(self) -> float:
        """Async version. Cooperatively waits without holding a thread."""
        # Compute the wait under the lock, then sleep outside it so
        # other coroutines can queue up.
        with self._lock:
            now = time.monotonic()
            wait = self._last_at + self.min_delay - now
            self._last_at = max(now + max(wait, 0.0), self._last_at + self.min_delay)
        if wait > 0:
            await asyncio.sleep(wait)
            return wait
        return 0.0
