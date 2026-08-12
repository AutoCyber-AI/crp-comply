# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Server-side session store with Redis, file, and in-memory backends.

Phase 5 introduces ``HttpOnly`` session cookies as the primary web
authentication carrier. The default production backend is the attached
volume (``CRP_COMPLY_DATA_DIR/sessions``) so sessions survive Redis
restarts and Railway redeploys. Redis remains available for deployments
that prefer a shared session cache.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any

logger = logging.getLogger(__name__)

SESSION_COOKIE_NAME = "crp_session"
SESSION_KEY_PREFIX = "cmp:session"
DEFAULT_SESSION_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days
STEP_UP_TTL_SECONDS = 10 * 60  # 10 minutes


@dataclass
class SessionRecord:
    """Server-side session payload."""

    session_id: str
    user_id: str
    tenant_id: str | None
    tier: str = "free"
    created_at: float = field(default_factory=time.time)
    last_seen_at: float = field(default_factory=time.time)
    ip_hash: str | None = None
    ua_hash: str | None = None
    elevated_until: float | None = None

    def is_elevated(self) -> bool:
        return self.elevated_until is not None and time.time() < self.elevated_until


class SessionStore:
    """Abstract session store."""

    async def create(
        self,
        user_id: str,
        tenant_id: str | None,
        tier: str = "free",
        ip_hash: str | None = None,
        ua_hash: str | None = None,
    ) -> SessionRecord:
        raise NotImplementedError

    async def get(self, session_id: str) -> SessionRecord | None:
        raise NotImplementedError

    async def touch(self, session_id: str) -> None:
        raise NotImplementedError

    async def list_for_user(self, user_id: str) -> list[SessionRecord]:
        raise NotImplementedError

    async def revoke(self, session_id: str, user_id: str) -> bool:
        raise NotImplementedError

    async def revoke_all_for_user(self, user_id: str, except_session_id: str | None = None) -> int:
        raise NotImplementedError

    async def set_elevated(self, session_id: str, until: float) -> None:
        raise NotImplementedError


class InMemorySessionStore(SessionStore):
    """Fallback store used when Redis/file is unavailable."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionRecord] = {}

    async def create(
        self,
        user_id: str,
        tenant_id: str | None,
        tier: str = "free",
        ip_hash: str | None = None,
        ua_hash: str | None = None,
    ) -> SessionRecord:
        record = SessionRecord(
            session_id=_make_id(),
            user_id=user_id,
            tenant_id=tenant_id,
            tier=tier,
            ip_hash=ip_hash,
            ua_hash=ua_hash,
        )
        self._sessions[record.session_id] = record
        return record

    async def get(self, session_id: str) -> SessionRecord | None:
        rec = self._sessions.get(session_id)
        if rec:
            rec.last_seen_at = time.time()
        return rec

    async def touch(self, session_id: str) -> None:
        rec = self._sessions.get(session_id)
        if rec:
            rec.last_seen_at = time.time()

    async def list_for_user(self, user_id: str) -> list[SessionRecord]:
        return [r for r in self._sessions.values() if r.user_id == user_id]

    async def revoke(self, session_id: str, user_id: str) -> bool:
        rec = self._sessions.get(session_id)
        if rec and rec.user_id == user_id:
            del self._sessions[session_id]
            return True
        return False

    async def revoke_all_for_user(self, user_id: str, except_session_id: str | None = None) -> int:
        removed = 0
        for sid in list(self._sessions):
            rec = self._sessions[sid]
            if rec.user_id == user_id and sid != except_session_id:
                del self._sessions[sid]
                removed += 1
        return removed

    async def set_elevated(self, session_id: str, until: float) -> None:
        rec = self._sessions.get(session_id)
        if rec:
            rec.elevated_until = until


class FileSessionStore(SessionStore):
    """Filesystem-backed session store on the attached data volume.

    Each session is a JSON file under ``<data_dir>/sessions/<id>.json``.
    A per-user index file makes ``list_for_user`` fast without scanning
    the whole directory.
    """

    def __init__(self, data_dir: Path | str, ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS) -> None:
        self._base = Path(data_dir) / "sessions"
        self._base.mkdir(parents=True, exist_ok=True)
        self._ttl = ttl_seconds
        self._lock = RLock()

    def _record_path(self, session_id: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)
        return self._base / f"{safe or '_'}.json"

    def _user_index_path(self, user_id: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in user_id)
        return self._base / f"_user_{safe or '_'}.json"

    def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        tmp.replace(path)

    def _read_json(self, path: Path) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def _load_user_index(self, user_id: str) -> list[str]:
        raw = self._read_json(self._user_index_path(user_id))
        if isinstance(raw, list):
            return [str(x) for x in raw]
        return []

    def _save_user_index(self, user_id: str, session_ids: list[str]) -> None:
        self._write_json(self._user_index_path(user_id), list(dict.fromkeys(session_ids)))

    def _is_expired(self, record: SessionRecord) -> bool:
        return (time.time() - record.last_seen_at) > self._ttl

    async def create(
        self,
        user_id: str,
        tenant_id: str | None,
        tier: str = "free",
        ip_hash: str | None = None,
        ua_hash: str | None = None,
    ) -> SessionRecord:
        record = SessionRecord(
            session_id=_make_id(),
            user_id=user_id,
            tenant_id=tenant_id,
            tier=tier,
            ip_hash=ip_hash,
            ua_hash=ua_hash,
        )
        with self._lock:
            self._write_json(self._record_path(record.session_id), _record_to_dict(record))
            index = self._load_user_index(user_id)
            if record.session_id not in index:
                index.append(record.session_id)
            self._save_user_index(user_id, index)
        return record

    async def get(self, session_id: str) -> SessionRecord | None:
        with self._lock:
            path = self._record_path(session_id)
            data = self._read_json(path)
            if not isinstance(data, dict):
                return None
            record = _record_from_dict(data)
            if record.session_id != session_id:
                return None
            if self._is_expired(record):
                path.unlink(missing_ok=True)
                self._prune_from_index(record.user_id, session_id)
                return None
            record.last_seen_at = time.time()
            self._write_json(path, _record_to_dict(record))
            return record

    async def touch(self, session_id: str) -> None:
        record = await self.get(session_id)
        if record:
            record.last_seen_at = time.time()
            with self._lock:
                self._write_json(self._record_path(session_id), _record_to_dict(record))

    async def list_for_user(self, user_id: str) -> list[SessionRecord]:
        with self._lock:
            index = self._load_user_index(user_id)
            records: list[SessionRecord] = []
            new_index: list[str] = []
            for sid in index:
                data = self._read_json(self._record_path(sid))
                if not isinstance(data, dict):
                    continue
                record = _record_from_dict(data)
                if record.user_id != user_id or self._is_expired(record):
                    self._record_path(sid).unlink(missing_ok=True)
                    continue
                new_index.append(sid)
                records.append(record)
            self._save_user_index(user_id, new_index)
            return records

    async def revoke(self, session_id: str, user_id: str) -> bool:
        with self._lock:
            record = await self.get(session_id)
            if record is None or record.user_id != user_id:
                return False
            self._record_path(session_id).unlink(missing_ok=True)
            self._prune_from_index(user_id, session_id)
            return True

    async def revoke_all_for_user(self, user_id: str, except_session_id: str | None = None) -> int:
        records = await self.list_for_user(user_id)
        removed = 0
        for rec in records:
            if rec.session_id == except_session_id:
                continue
            if await self.revoke(rec.session_id, user_id):
                removed += 1
        return removed

    async def set_elevated(self, session_id: str, until: float) -> None:
        record = await self.get(session_id)
        if record:
            record.elevated_until = until
            with self._lock:
                self._write_json(self._record_path(session_id), _record_to_dict(record))

    def _prune_from_index(self, user_id: str, session_id: str) -> None:
        index = self._load_user_index(user_id)
        if session_id in index:
            index.remove(session_id)
            self._save_user_index(user_id, index)


class RedisSessionStore(SessionStore):
    """Redis-backed session store."""

    def __init__(self, ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS) -> None:
        self._redis: Any | None = None
        self._ttl = ttl_seconds

    async def _client(self) -> Any | None:
        if self._redis is None:
            from crp_shared.redis_client import get_async_redis_client

            self._redis = await get_async_redis_client()
        return self._redis

    def _key(self, session_id: str) -> str:
        return f"{SESSION_KEY_PREFIX}:{session_id}"

    def _user_index_key(self, user_id: str) -> str:
        return f"{SESSION_KEY_PREFIX}:user:{user_id}"

    async def create(
        self,
        user_id: str,
        tenant_id: str | None,
        tier: str = "free",
        ip_hash: str | None = None,
        ua_hash: str | None = None,
    ) -> SessionRecord:
        record = SessionRecord(
            session_id=_make_id(),
            user_id=user_id,
            tenant_id=tenant_id,
            tier=tier,
            ip_hash=ip_hash,
            ua_hash=ua_hash,
        )
        await self._save(record)
        return record

    async def _save(self, record: SessionRecord) -> None:
        client = await self._client()
        data = asdict(record)
        key = self._key(record.session_id)
        if client is not None:
            pipe = client.pipeline()
            pipe.hset(key, mapping={k: _encode(v) for k, v in data.items()})
            pipe.expire(key, self._ttl)
            pipe.sadd(self._user_index_key(record.user_id), record.session_id)
            await pipe.execute()
        else:
            # Fallback should never happen because InMemoryStore is used when Redis is absent,
            # but keep the branch safe.
            _memory_fallback()[record.session_id] = record

    async def get(self, session_id: str) -> SessionRecord | None:
        client = await self._client()
        if client is None:
            return None
        data = await client.hgetall(self._key(session_id))
        if not data:
            return None
        return _decode_record(data)

    async def touch(self, session_id: str) -> None:
        record = await self.get(session_id)
        if record:
            record.last_seen_at = time.time()
            await self._save(record)

    async def list_for_user(self, user_id: str) -> list[SessionRecord]:
        client = await self._client()
        if client is None:
            return []
        session_ids = await client.smembers(self._user_index_key(user_id))
        records: list[SessionRecord] = []
        for sid in session_ids:
            data = await client.hgetall(self._key(sid))
            if data:
                records.append(_decode_record(data))
        return records

    async def revoke(self, session_id: str, user_id: str) -> bool:
        client = await self._client()
        if client is None:
            return False
        record = await self.get(session_id)
        if record is None or record.user_id != user_id:
            return False
        pipe = client.pipeline()
        pipe.delete(self._key(session_id))
        pipe.srem(self._user_index_key(user_id), session_id)
        await pipe.execute()
        return True

    async def revoke_all_for_user(self, user_id: str, except_session_id: str | None = None) -> int:
        records = await self.list_for_user(user_id)
        removed = 0
        for rec in records:
            if rec.session_id == except_session_id:
                continue
            if await self.revoke(rec.session_id, user_id):
                removed += 1
        return removed

    async def set_elevated(self, session_id: str, until: float) -> None:
        record = await self.get(session_id)
        if record:
            record.elevated_until = until
            await self._save(record)


_memory_store: InMemorySessionStore | None = None


def _memory_fallback() -> dict[str, SessionRecord]:
    """Shared in-memory fallback for the Redis store if used accidentally."""
    global _memory_store
    if _memory_store is None:
        _memory_store = InMemorySessionStore()
    return _memory_store._sessions


def _make_id() -> str:
    return uuid.uuid4().hex


def _encode(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _decode_record(data: dict[str, str]) -> SessionRecord:
    def _float(key: str) -> float | None:
        v = data.get(key)
        return float(v) if v else None

    return SessionRecord(
        session_id=data["session_id"],
        user_id=data["user_id"],
        tenant_id=data.get("tenant_id") or None,
        tier=data.get("tier") or "free",
        created_at=_float("created_at") or time.time(),
        last_seen_at=_float("last_seen_at") or time.time(),
        ip_hash=data.get("ip_hash") or None,
        ua_hash=data.get("ua_hash") or None,
        elevated_until=_float("elevated_until"),
    )


def _record_to_dict(record: SessionRecord) -> dict[str, Any]:
    """Serialisable dict for the file backend."""
    return {
        "session_id": record.session_id,
        "user_id": record.user_id,
        "tenant_id": record.tenant_id,
        "tier": record.tier,
        "created_at": record.created_at,
        "last_seen_at": record.last_seen_at,
        "ip_hash": record.ip_hash,
        "ua_hash": record.ua_hash,
        "elevated_until": record.elevated_until,
    }


def _record_from_dict(data: dict[str, Any]) -> SessionRecord:
    """Load a SessionRecord from a parsed JSON dict."""

    def _float(value: Any) -> float | None:
        if value is None or value == "":
            return None
        return float(value)

    return SessionRecord(
        session_id=str(data.get("session_id", "")),
        user_id=str(data.get("user_id", "")),
        tenant_id=data.get("tenant_id") or None,
        tier=str(data.get("tier") or "free"),
        created_at=_float(data.get("created_at")) or time.time(),
        last_seen_at=_float(data.get("last_seen_at")) or time.time(),
        ip_hash=data.get("ip_hash") or None,
        ua_hash=data.get("ua_hash") or None,
        elevated_until=_float(data.get("elevated_until")),
    )


_session_store: SessionStore | None = None
_session_data_dir: Path | None = None


def _default_store() -> SessionStore:
    """Pick the default session store based on environment variables.

    Priority:
      1. ``CRP_COMPLY_SESSION_STORE`` explicit value.
      2. ``CRP_COMPLY_PERSISTENCE_STORE`` general setting.
      3. In-memory fallback for tests and local dev with no data dir.
    """
    session_store_env = os.environ.get("CRP_COMPLY_SESSION_STORE", "").lower().strip()
    persistence_env = os.environ.get("CRP_COMPLY_PERSISTENCE_STORE", "").lower().strip()

    wants_redis = session_store_env == "redis" or (
        not session_store_env and persistence_env == "redis"
    )
    wants_file = session_store_env == "file" or (
        not session_store_env and persistence_env == "file"
    )

    if wants_file and _session_data_dir is not None:
        return FileSessionStore(_session_data_dir)

    if wants_redis:
        from crp_shared.redis_client import get_redis_client

        client = get_redis_client()
        if client is not None:
            return RedisSessionStore()

    return InMemorySessionStore()


def init_session_store(data_dir: Path | str | None = None) -> SessionStore:
    """Initialise the process-wide session store from app startup."""
    global _session_store, _session_data_dir
    if data_dir is not None:
        _session_data_dir = Path(data_dir)
    _session_store = _default_store()
    logger.info("Session store initialised: %s", type(_session_store).__name__)
    return _session_store


def get_session_store() -> SessionStore:
    """Return the global session store (lazy initialised).

    Uses Redis when explicitly configured and reachable; otherwise prefers
    the file-backed store on the attached volume. Falls back to an
    in-memory store for single-process tests and local dev.
    """
    global _session_store
    if _session_store is None:
        _session_store = _default_store()
    return _session_store


def set_session_store(store: SessionStore) -> None:
    """Override the global store (used by tests)."""
    global _session_store
    _session_store = store


def _hash(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode()).hexdigest()[:16]
