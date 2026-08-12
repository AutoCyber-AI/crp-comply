# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Generic key/value JSON persistence with file and Redis backends.

Used by OrgProfile, provider config, and agent-session stores so that
CRP Comply survives Railway/fly.io redeploys without an attached volume.
Set ``CRP_COMPLY_PERSISTENCE_STORE=redis`` and ``CRP_COMPLY_REDIS_URL``.
The default remains file-backed for local development.
"""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _safe_id(value: str) -> str:
    """Sanitise a key component for filesystem or Redis use."""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in value).rstrip("_") or "_"


class JsonStore(ABC):
    """Abstract JSON key/value store."""

    @abstractmethod
    def get(self, key: str) -> dict[str, Any] | None:
        """Return the stored dict for *key*, or ``None`` if absent."""

    @abstractmethod
    def set(self, key: str, value: dict[str, Any]) -> None:
        """Persist *value* under *key*."""

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Remove *key*. Returns ``True`` iff it existed."""

    def list_keys(self, prefix: str) -> list[str]:
        """Return keys starting with *prefix* (best-effort; default empty)."""
        return []


class FileJsonStore(JsonStore):
    """Filesystem-backed JSON store."""

    def __init__(self, base_dir: Path | str) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        safe = _safe_id(key)
        return self.base_dir / f"{safe}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read %s: %s", path, exc)
            return None
        return raw if isinstance(raw, dict) else None

    def set(self, key: str, value: dict[str, Any]) -> None:
        path = self._path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(value, indent=2, default=str), encoding="utf-8")
            tmp.replace(path)
        except OSError as exc:
            logger.warning("Failed to write %s: %s", path, exc)

    def delete(self, key: str) -> bool:
        path = self._path(key)
        if not path.exists():
            return False
        try:
            path.unlink()
            return True
        except OSError as exc:
            logger.warning("Failed to delete %s: %s", path, exc)
            return False

    def list_keys(self, prefix: str) -> list[str]:
        safe_prefix = _safe_id(prefix)
        keys: list[str] = []
        try:
            for p in self.base_dir.iterdir():
                if p.is_file() and p.suffix == ".json":
                    name = p.stem
                    if name.startswith(safe_prefix):
                        keys.append(name)
        except OSError:
            pass
        return keys


class RedisJsonStore(JsonStore):
    """Redis-backed JSON store with optional TTL.

    Falls back to no-op on connection errors so a transient Redis outage
    does not crash the API surface.
    """

    def __init__(
        self,
        *,
        url: str | None = None,
        key_prefix: str = "crp:comply:json",
        ttl_seconds: int | None = None,
    ) -> None:
        explicit = url or os.environ.get("CRP_COMPLY_REDIS_URL")
        if explicit:
            self.url = explicit
        else:
            # Fall back to Railway's shared REDIS_URL, namespaced by service so
            # gateway (db 0) and comply (db 1) don't collide.
            try:
                from crp_shared.redis_client import _make_url as _shared_redis_url

                shared = _shared_redis_url()
            except Exception:  # pragma: no cover - best-effort namespace
                shared = None
            self.url = shared or os.environ.get("REDIS_URL") or "redis://localhost:6379/1"
        self.key_prefix = key_prefix
        self.ttl = int(ttl_seconds or os.environ.get("CRP_COMPLY_PERSISTENCE_TTL_SECONDS") or 0)
        self._client: Any = None

    def _client_or_none(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import redis as _redis

            self._client = _redis.from_url(self.url, decode_responses=True)
        except Exception:  # noqa: BLE001
            logger.warning("Redis JSON store unavailable", exc_info=True)
            self._client = False
        return self._client

    def _key(self, key: str) -> str:
        return f"{self.key_prefix}:{_safe_id(key)}"

    def get(self, key: str) -> dict[str, Any] | None:
        client = self._client_or_none()
        if client is False:
            return None
        try:
            raw = client.get(self._key(key))
            if not raw:
                return None
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
        except Exception:  # noqa: BLE001
            logger.warning("Failed to load %s from Redis", key, exc_info=True)
            return None

    def set(self, key: str, value: dict[str, Any]) -> None:
        client = self._client_or_none()
        if client is False:
            return
        try:
            raw = json.dumps(value, default=str)
            k = self._key(key)
            if self.ttl and self.ttl > 0:
                client.setex(k, self.ttl, raw)
            else:
                client.set(k, raw)
        except Exception:  # noqa: BLE001
            logger.warning("Failed to save %s to Redis", key, exc_info=True)

    def delete(self, key: str) -> bool:
        client = self._client_or_none()
        if client is False:
            return False
        try:
            return bool(client.delete(self._key(key)))
        except Exception:  # noqa: BLE001
            logger.warning("Failed to delete %s from Redis", key, exc_info=True)
            return False

    def list_keys(self, prefix: str) -> list[str]:
        client = self._client_or_none()
        if client is False:
            return []
        try:
            pattern = f"{self.key_prefix}:{_safe_id(prefix)}*"
            keys = client.keys(pattern)
            strip = f"{self.key_prefix}:"
            return [k[len(strip) :] if k.startswith(strip) else k for k in keys]
        except Exception:  # noqa: BLE001
            logger.warning("Failed to list Redis keys for %s", prefix, exc_info=True)
            return []


def get_json_store(
    name: str,
    base_dir: Path | str | None = None,
    *,
    key_prefix: str | None = None,
    ttl_seconds: int | None = None,
) -> JsonStore:
    """Return a :class:`JsonStore` based on ``CRP_COMPLY_PERSISTENCE_STORE``.

    Parameters
    ----------
    name
        Logical store name (used as directory name for file, and as part of
        the Redis key prefix).
    base_dir
        Parent data directory for the file backend. Defaults to
        ``CRP_COMPLY_DATA_DIR`` or ``data``.
    key_prefix
        Optional Redis key prefix override. Defaults to ``crp:comply:{name}``.
    ttl_seconds
        Optional Redis TTL. 0 or None means no expiration.
    """
    store_kind = os.environ.get("CRP_COMPLY_PERSISTENCE_STORE", "file").lower().strip()
    if store_kind == "redis":
        prefix = key_prefix or f"crp:comply:{name}"
        return RedisJsonStore(key_prefix=prefix, ttl_seconds=ttl_seconds)
    data_dir = Path(base_dir or os.environ.get("CRP_COMPLY_DATA_DIR", "data"))
    return FileJsonStore(data_dir / name)


__all__ = [
    "JsonStore",
    "FileJsonStore",
    "RedisJsonStore",
    "get_json_store",
]
