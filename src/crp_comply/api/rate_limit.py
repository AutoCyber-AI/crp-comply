# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Per-minute rate limiting — addresses PRODUCT_SECURITY.md §4 gap #1.

A token bucket keyed by (user_id, endpoint_group). Free-tier callers share
the "anonymous" bucket when unauthenticated. Authenticated callers get one
bucket per-user-per-endpoint-group; refill happens on read, so there is no
background thread.

When ``REDIS_URL`` is set the bucket state is stored in Redis with a 90-second
TTL, making the limiter work correctly across multiple replicas.  Redis
unavailability falls back transparently to the in-memory bucket.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Annotated

from fastapi import Depends, HTTPException, status

from crp_shared.redis_client import get_redis_client

from .auth import Tier
from .deps import _extract_credentials

log = logging.getLogger("crp_comply.api.rate_limit")


_DEFAULTS: dict[str, int] = {
    "free": 20,
    "starter": 60,
    "scale": 300,
    "pro": 240,
    "enterprise": 1200,
    "cloud": 2400,
    "anonymous": 10,
}


def _load_limits() -> dict[str, int]:
    raw = os.getenv("CRP_COMPLY_RATE_LIMITS")
    limits = dict(_DEFAULTS)
    if not raw:
        return limits
    try:
        override = json.loads(raw)
        for k, v in override.items():
            if isinstance(v, int) and v > 0:
                limits[k] = v
    except Exception as exc:
        log.warning("ignoring bad CRP_COMPLY_RATE_LIMITS: %s", exc)
    return limits


_LIMITS = _load_limits()
_WINDOW_SECONDS = 60
_BUCKET_TTL_SECONDS = 90

# bucket key -> (tokens, last_refill_ts)
_buckets: dict[str, tuple[float, float]] = {}
_lock = threading.Lock()
_redis = get_redis_client()

# Atomic token-bucket script. Arguments: KEY, limit, window, now, cost(1), ttl
# Returns [allowed, tokens_after, limit]
# State is stored as "tokens:last_refill" so we avoid JSON in Lua.
_REDIS_BUCKET_LUA = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])

local raw = redis.call('get', key)
local tokens = limit
local last = now
if raw then
    local sep = raw:find(':')
    if sep then
        tokens = tonumber(raw:sub(1, sep - 1))
        last = tonumber(raw:sub(sep + 1))
    end
end

local elapsed = math.max(0, now - last)
tokens = math.min(limit, tokens + elapsed * (limit / window))
local allowed = 0
if tokens >= cost then
    tokens = tokens - cost
    allowed = 1
end

redis.call('setex', key, ttl, tokens .. ':' .. now)
return {allowed, math.floor(tokens), limit}
"""


def _bucket_key(user_id: str, group: str) -> str:
    return f"rate_limit:{user_id}:{group}"


def _allow_redis(user_id: str, tier: Tier | str, group: str) -> tuple[bool, int, int] | None:
    """Try to consume one token using Redis. Returns None if Redis unavailable."""
    if _redis is None:
        return None
    tier_key = tier.value if isinstance(tier, Tier) else str(tier)
    if user_id == "anonymous":
        tier_key = "anonymous"
    limit = _LIMITS.get(tier_key, _DEFAULTS["free"])
    key = _bucket_key(user_id, group)
    try:
        result = _redis.eval(
            _REDIS_BUCKET_LUA,
            1,
            key,
            limit,
            _WINDOW_SECONDS,
            time.monotonic(),
            1,
            _BUCKET_TTL_SECONDS,
        )
        allowed, remaining, limit = result
        return bool(allowed), int(remaining), int(limit)
    except Exception as exc:
        log.warning("Redis rate-limit failed for %s: %s — falling back to memory", key, exc)
        return None


def _allow_memory(user_id: str, tier: Tier | str, group: str) -> tuple[bool, int, int]:
    """Try to consume one token using the in-memory bucket."""
    tier_key = tier.value if isinstance(tier, Tier) else str(tier)
    if user_id == "anonymous":
        tier_key = "anonymous"
    limit = _LIMITS.get(tier_key, _DEFAULTS["free"])
    refill_rate = limit / _WINDOW_SECONDS  # tokens / second
    key = _bucket_key(user_id, group)
    now = time.monotonic()
    with _lock:
        tokens, last = _buckets.get(key, (float(limit), now))
        # refill
        elapsed = max(0.0, now - last)
        tokens = min(float(limit), tokens + elapsed * refill_rate)
        if tokens >= 1.0:
            tokens -= 1.0
            _buckets[key] = (tokens, now)
            return True, int(tokens), limit
        _buckets[key] = (tokens, now)
        return False, 0, limit


def _allow(user_id: str, tier: Tier | str, group: str) -> tuple[bool, int, int]:
    """Try to consume one token.

    Returns ``(allowed, remaining, limit)``.
    """
    redis_result = _allow_redis(user_id, tier, group)
    if redis_result is not None:
        return redis_result
    return _allow_memory(user_id, tier, group)


def rate_limit_dep(group: str = "default"):
    """FastAPI dependency: consume one token from the caller's bucket.

    Usage::

        @router.post("/foo", dependencies=[Depends(rate_limit_dep("foo"))])

    Group names cluster endpoints that should share a budget (e.g. all agent
    calls share ``"agent"`` so a user can't bypass limits by rotating
    endpoint paths).
    """

    async def _dep(
        creds: Annotated[tuple[str, Tier], Depends(_extract_credentials)],
    ) -> None:
        user_id, tier = creds
        allowed, remaining, limit = _allow(user_id, tier, group)
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "rate_limit_exceeded",
                    "group": group,
                    "limit_per_minute": limit,
                    "retry_after_seconds": 1,
                },
                headers={
                    "Retry-After": "1",
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

    return _dep


# ── Test hooks ────────────────────────────────────────────────


def _reset_for_tests() -> None:
    global _LIMITS, _redis
    with _lock:
        _buckets.clear()
        _LIMITS = _load_limits()


def _snapshot() -> dict[str, tuple[float, float]]:
    with _lock:
        return dict(_buckets)
