# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Synchronous PostgreSQL persistence for CRP Comply AuthManager.

Uses psycopg2 so AuthManager can remain sync while migrating off JSON files.
 Falls back to in-memory/JSON when DATABASE_URL is unavailable.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_pool = None


def _dsn() -> str | None:
    return os.environ.get("DATABASE_URL")


def _connection() -> Any | None:
    global _pool
    dsn = _dsn()
    if not dsn:
        return None
    if _pool is None:
        try:
            import psycopg2
            import psycopg2.extras
            import psycopg2.pool

            _pool = psycopg2.pool.ThreadedConnectionPool(
                1,
                5,
                dsn,
                connect_timeout=10,
                cursor_factory=psycopg2.extras.RealDictCursor,
            )
            logger.info("AuthManager PostgreSQL pool created")
        except Exception as exc:
            logger.warning("AuthManager PostgreSQL pool failed: %s", exc)
            return None
    try:
        return _pool.getconn()
    except Exception as exc:
        logger.warning("AuthManager could not get connection: %s", exc)
        return None


def _release(conn: Any) -> None:
    global _pool
    if _pool and conn:
        try:
            _pool.putconn(conn)
        except Exception:
            pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_user(row: Any) -> dict[str, Any]:
    return {
        "id": row["user_id"],
        "email": row["email"],
        "name": row["name"],
        "provider": row["provider"],
        "tier": row["tier"],
        "tenant_id": row["tenant_id"],
        "github_installation_id": row["github_installation_id"],
        "disabled": row["disabled"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else _now_iso(),
    }


def _row_to_api_key(row: Any) -> dict[str, Any]:
    return {
        "id": row["key_id"],
        "name": row["name"],
        "key_prefix": row["key_prefix"],
        "user_id": row["user_id"],
        "tier": row["tier"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else _now_iso(),
        "revoked": row["revoked"],
        "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
        "key_hash": row["key_hash"],
    }


def db_available() -> bool:
    return _connection() is not None


# ── Users ────────────────────────────────────────────────────────


def upsert_user(user: dict[str, Any]) -> None:
    conn = _connection()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO comply_users
                    (user_id, email, name, provider, tier, tenant_id, github_installation_id, disabled, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    email = EXCLUDED.email,
                    name = EXCLUDED.name,
                    provider = EXCLUDED.provider,
                    tier = EXCLUDED.tier,
                    tenant_id = EXCLUDED.tenant_id,
                    github_installation_id = COALESCE(EXCLUDED.github_installation_id, comply_users.github_installation_id),
                    disabled = EXCLUDED.disabled,
                    updated_at = now()
                """,
                (
                    user["id"],
                    user.get("email", ""),
                    user.get("name", ""),
                    user.get("provider", ""),
                    user.get("tier", "free"),
                    user.get("tenant_id", user["id"]),
                    user.get("github_installation_id"),
                    user.get("disabled", False),
                    user.get("created_at", _now_iso()),
                    _now_iso(),
                ),
            )
        conn.commit()
    except Exception as exc:
        logger.warning("upsert_user DB failed: %s", exc)
    finally:
        _release(conn)


def get_user(user_id: str) -> dict[str, Any] | None:
    conn = _connection()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM comply_users WHERE user_id = %s", (user_id,))
            row = cur.fetchone()
        return _row_to_user(row) if row else None
    except Exception as exc:
        logger.warning("get_user DB failed: %s", exc)
        return None
    finally:
        _release(conn)


def set_user_tier(user_id: str, tier: str) -> bool:
    conn = _connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE comply_users SET tier = %s, updated_at = now() WHERE user_id = %s",
                (tier, user_id),
            )
            updated = cur.rowcount > 0
        conn.commit()
        return updated
    except Exception as exc:
        logger.warning("set_user_tier DB failed: %s", exc)
        return False
    finally:
        _release(conn)


def set_github_installation(user_id: str, installation_id: str) -> None:
    conn = _connection()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE comply_users
                SET github_installation_id = %s, updated_at = now()
                WHERE user_id = %s
                """,
                (installation_id, user_id),
            )
        conn.commit()
    except Exception as exc:
        logger.warning("set_github_installation DB failed: %s", exc)
    finally:
        _release(conn)


def get_github_installation(user_id: str) -> str | None:
    conn = _connection()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT github_installation_id FROM comply_users WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
        return row["github_installation_id"] if row else None
    except Exception as exc:
        logger.warning("get_github_installation DB failed: %s", exc)
        return None
    finally:
        _release(conn)


# ── API Keys ─────────────────────────────────────────────────────


def create_api_key(data: dict[str, Any]) -> None:
    conn = _connection()
    if not conn:
        return
    expires_at = data.get("expires_at")
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO comply_api_keys
                    (key_hash, key_id, user_id, name, key_prefix, tier, revoked, expires_at, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (key_hash) DO UPDATE SET
                    name = EXCLUDED.name,
                    tier = EXCLUDED.tier,
                    revoked = FALSE,
                    expires_at = EXCLUDED.expires_at
                """,
                (
                    data["key_hash"],
                    data.get("key_id", ""),
                    data["user_id"],
                    data.get("name", "default"),
                    data.get("key_prefix", ""),
                    data.get("tier", "free"),
                    data.get("revoked", False),
                    datetime.fromisoformat(expires_at) if expires_at else None,
                    data.get("created_at", _now_iso()),
                ),
            )
        conn.commit()
    except Exception as exc:
        logger.warning("create_api_key DB failed: %s", exc)
    finally:
        _release(conn)


def get_api_key(key_hash: str) -> dict[str, Any] | None:
    conn = _connection()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM comply_api_keys
                WHERE key_hash = %s AND revoked = FALSE
                  AND (expires_at IS NULL OR expires_at > now())
                """,
                (key_hash,),
            )
            row = cur.fetchone()
        return _row_to_api_key(row) if row else None
    except Exception as exc:
        logger.warning("get_api_key DB failed: %s", exc)
        return None
    finally:
        _release(conn)


def list_api_keys(user_id: str) -> list[dict[str, Any]]:
    conn = _connection()
    if not conn:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM comply_api_keys
                WHERE user_id = %s AND revoked = FALSE
                ORDER BY created_at DESC
                """,
                (user_id,),
            )
            rows = cur.fetchall()
        return [_row_to_api_key(r) for r in rows]
    except Exception as exc:
        logger.warning("list_api_keys DB failed: %s", exc)
        return []
    finally:
        _release(conn)


def revoke_api_key(user_id: str, key_id: str) -> bool:
    conn = _connection()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE comply_api_keys
                SET revoked = TRUE
                WHERE user_id = %s AND key_id = %s
                """,
                (user_id, key_id),
            )
            updated = cur.rowcount > 0
        conn.commit()
        return updated
    except Exception as exc:
        logger.warning("revoke_api_key DB failed: %s", exc)
        return False
    finally:
        _release(conn)
