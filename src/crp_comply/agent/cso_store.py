# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Persistent store adapters for CRP Comply session memory.

Phase 5e.1 — Redis-backed CSO persistence. The default remains file-based so
local development and existing deployments are unaffected. Set
``CRP_COMPLY_CSO_STORE=redis`` and ``CRP_COMPLY_REDIS_URL`` to enable Redis.
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
    """Sanitise a user/session id for filesystem or key use."""
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in value).rstrip("_") or "_"


class CSOStore(ABC):
    """Abstract session-memory store."""

    @abstractmethod
    def load(self, user_id: str, session_id: str) -> dict[str, Any] | None:
        """Return the stored memory dict, or None if not found."""

    @abstractmethod
    def save(self, user_id: str, session_id: str, data: dict[str, Any]) -> None:
        """Persist the memory dict."""


class FileCSOStore(CSOStore):
    """File-system backed store (default, original behaviour)."""

    def __init__(self, data_dir: Path | str | None = None) -> None:
        self.data_dir = Path(data_dir or os.environ.get("CRP_COMPLY_DATA_DIR", "data"))

    def _resolve_path(self, user_id: str, session_id: str) -> Path:
        safe_user = _safe_id(user_id)
        safe_session = _safe_id(session_id)
        return self.data_dir / "context" / safe_user / f"{safe_session}.json"

    def load(self, user_id: str, session_id: str) -> dict[str, Any] | None:
        path = self._resolve_path(user_id, session_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            logger.warning("Failed to load memory from %s", path, exc_info=True)
            return None

    def save(self, user_id: str, session_id: str, data: dict[str, Any]) -> None:
        path = self._resolve_path(user_id, session_id)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
            tmp.replace(path)
        except Exception:  # noqa: BLE001
            logger.warning("Failed to save memory to %s", path, exc_info=True)


class RedisCSOStore(CSOStore):
    """Redis-backed store for cross-process session survival.

    Expects a ``redis`` package and a Redis URL. Falls back to no-op on errors.
    """

    def __init__(self, url: str | None = None, ttl_seconds: int | None = None) -> None:
        explicit = url or os.environ.get("CRP_COMPLY_REDIS_URL")
        if explicit:
            self.url = explicit
        else:
            # Namespaced fallback to Railway's shared REDIS_URL.
            try:
                from crp_shared.redis_client import _make_url as _shared_redis_url

                shared = _shared_redis_url()
            except Exception:  # pragma: no cover - best-effort namespace
                shared = None
            self.url = shared or os.environ.get("REDIS_URL") or "redis://localhost:6379/1"
        self.ttl = int(ttl_seconds or os.environ.get("CRP_COMPLY_CSO_TTL_SECONDS", "604800"))
        self._client: Any = None

    def _client_or_none(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            import redis as _redis

            self._client = _redis.from_url(self.url, decode_responses=True)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Redis CSO store unavailable; falling back to in-memory only", exc_info=True
            )
            self._client = False
        return self._client

    def _key(self, user_id: str, session_id: str) -> str:
        return f"crp:comply:memory:{_safe_id(user_id)}:{_safe_id(session_id)}"

    def load(self, user_id: str, session_id: str) -> dict[str, Any] | None:
        client = self._client_or_none()
        if client is False:
            return None
        try:
            raw = client.get(self._key(user_id, session_id))
            if not raw:
                return None
            return json.loads(raw)
        except Exception:  # noqa: BLE001
            logger.warning("Failed to load memory from Redis", exc_info=True)
            return None

    def save(self, user_id: str, session_id: str, data: dict[str, Any]) -> None:
        client = self._client_or_none()
        if client is False:
            return
        try:
            client.setex(
                self._key(user_id, session_id),
                self.ttl,
                json.dumps(data, default=str),
            )
        except Exception:  # noqa: BLE001
            logger.warning("Failed to save memory to Redis", exc_info=True)


def get_cso_store(data_dir: Path | str | None = None) -> CSOStore:
    """Return the active CSO store based on environment configuration."""
    store_kind = os.environ.get("CRP_COMPLY_CSO_STORE", "file").lower().strip()
    if store_kind == "redis":
        return RedisCSOStore()
    return FileCSOStore(data_dir=data_dir)
