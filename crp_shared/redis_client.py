# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Redis client helpers for CRP services.

Reads ``REDIS_URL`` from the environment and exposes a namespaced Redis
connection.  If Redis is unavailable the helper logs a warning and returns
``None`` so callers can fall back to in-memory stores.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_ORDERS: dict[str, int] = {"gw": 0, "cmp": 1, "comply": 1}


def _service_prefix() -> str:
    """Return a short namespacing prefix for the current service."""
    name = os.environ.get("CRP_SERVICE_NAME", "").lower()
    if "gateway" in name:
        return "gw"
    if "comply" in name:
        return "cmp"
    import sys

    argv0 = sys.argv[0].lower()
    if "gateway" in argv0:
        return "gw"
    if "comply" in argv0:
        return "cmp"
    return "crp"


def _namespaced_url(raw_url: str, prefix: str) -> str:
    """Append a unique logical DB index per service to a redis:// URL.

    Railway typically provisions one shared Redis instance.  We split it
    logically by using a different numeric database per service (Redis
    supports 16 databases by default).  This avoids key collisions between
    gateway and comply while keeping configuration simple.
    """
    if not raw_url.startswith(("redis://", "rediss://")):
        return raw_url
    db_index = _ORDERS.get(prefix, 0)
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(raw_url)
    rebuilt = parsed._replace(path=f"/{db_index}")
    return urlunparse(rebuilt)


def _make_url() -> str | None:
    raw = os.environ.get("REDIS_URL")
    if not raw:
        return None
    return _namespaced_url(raw, _service_prefix())


def get_redis_client(**kwargs: Any) -> Any | None:
    """Create a synchronous Redis client from ``REDIS_URL`` if available."""
    url = _make_url()
    if not url:
        return None
    try:
        import redis as _redis
    except ImportError:
        logger.warning("REDIS_URL is set but redis-py is not installed")
        return None
    try:
        client = _redis.Redis.from_url(url, decode_responses=True, **kwargs)
        client.ping()
        logger.info("Redis connected (sync, namespace=%s)", _service_prefix())
        return client
    except Exception as exc:
        logger.warning("Redis connection failed: %s — falling back to in-memory", exc)
        return None


async def get_async_redis_client(**kwargs: Any) -> Any | None:
    """Create an async Redis client from ``REDIS_URL`` if available."""
    url = _make_url()
    if not url:
        return None
    try:
        from redis import asyncio as _aioredis
    except ImportError:
        logger.warning("REDIS_URL is set but redis-py is not installed")
        return None
    try:
        client = _aioredis.Redis.from_url(url, decode_responses=True, **kwargs)
        await client.ping()
        logger.info("Redis connected (async, namespace=%s)", _service_prefix())
        return client
    except Exception as exc:
        logger.warning("Redis connection failed: %s — falling back to in-memory", exc)
        return None


class RedisBackedDict:
    """Sync dict-like store backed by Redis strings with in-memory fallback."""

    def __init__(self, name: str, ttl_seconds: int = 3600) -> None:
        self.name = name
        self.ttl = ttl_seconds
        self._local: dict[str, Any] = {}
        self._redis = get_redis_client()

    def _key(self, key: str) -> str:
        return f"{self.name}:{key}"

    def get(self, key: str, default: Any = None) -> Any:
        if key in self._local:
            return self._local[key]
        if self._redis is None:
            return default
        try:
            raw = self._redis.get(self._key(key))
            if raw is None:
                return default
            return json.loads(raw)
        except Exception as exc:
            logger.warning("Redis read failed for %s: %s", key, exc)
            return default

    def set(self, key: str, value: Any) -> None:
        self._local[key] = value
        if self._redis is not None:
            try:
                self._redis.setex(self._key(key), self.ttl, json.dumps(value))
            except Exception as exc:
                logger.warning("Redis write failed for %s: %s", key, exc)

    def delete(self, key: str) -> None:
        self._local.pop(key, None)
        if self._redis is not None:
            try:
                self._redis.delete(self._key(key))
            except Exception as exc:
                logger.warning("Redis delete failed for %s: %s", key, exc)

    def values(self) -> list[Any]:
        return list(self._local.values())

    def items(self) -> list[tuple[str, Any]]:
        return list(self._local.items())


class AsyncRedisBackedDict:
    """Async dict-like store backed by Redis strings with in-memory fallback."""

    def __init__(self, name: str, ttl_seconds: int = 3600) -> None:
        self.name = name
        self.ttl = ttl_seconds
        self._local: dict[str, Any] = {}
        self._redis: Any | None = None

    async def _client(self) -> Any | None:
        if self._redis is None:
            self._redis = await get_async_redis_client()
        return self._redis

    def _key(self, key: str) -> str:
        return f"{self.name}:{key}"

    async def get(self, key: str, default: Any = None) -> Any:
        if key in self._local:
            return self._local[key]
        r = await self._client()
        if r is None:
            return default
        try:
            raw = await r.get(self._key(key))
            if raw is None:
                return default
            return json.loads(raw)
        except Exception as exc:
            logger.warning("Redis read failed for %s: %s", key, exc)
            return default

    async def set(self, key: str, value: Any) -> None:
        self._local[key] = value
        r = await self._client()
        if r is not None:
            try:
                await r.setex(self._key(key), self.ttl, json.dumps(value))
            except Exception as exc:
                logger.warning("Redis write failed for %s: %s", key, exc)

    async def delete(self, key: str) -> None:
        self._local.pop(key, None)
        r = await self._client()
        if r is not None:
            try:
                await r.delete(self._key(key))
            except Exception as exc:
                logger.warning("Redis delete failed for %s: %s", key, exc)

    def values(self) -> list[Any]:
        return list(self._local.values())

    def items(self) -> list[tuple[str, Any]]:
        return list(self._local.items())
