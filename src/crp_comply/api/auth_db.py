# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""PostgreSQL persistence layer for CRP Comply users and API keys.

This module is the migration target for AuthManager. It mirrors the JSON
file operations with async PostgreSQL equivalents, falling back to
in-memory/JSON when the database is unavailable.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from crp_shared.db import get_db

logger = logging.getLogger(__name__)

_USER_COLUMNS = [
    "user_id",
    "email",
    "name",
    "provider",
    "tier",
    "tenant_id",
    "github_installation_id",
    "disabled",
    "created_at",
    "updated_at",
]

_API_KEY_COLUMNS = [
    "key_hash",
    "key_id",
    "user_id",
    "name",
    "key_prefix",
    "tier",
    "revoked",
    "expires_at",
    "created_at",
]


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
    }


async def _db_available() -> bool:
    try:
        async with get_db() as conn:
            await conn.fetchval("SELECT 1")
        return True
    except Exception as exc:
        logger.debug("auth_db not available: %s", exc)
        return False


# ── Users ────────────────────────────────────────────────────────


async def upsert_user(user: dict[str, Any]) -> None:
    async with get_db() as conn:
        await conn.execute(
            """
            INSERT INTO comply_users
                (user_id, email, name, provider, tier, tenant_id, github_installation_id, disabled, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
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
        )


async def get_user(user_id: str) -> dict[str, Any] | None:
    async with get_db() as conn:
        row = await conn.fetchrow("SELECT * FROM comply_users WHERE user_id = $1", user_id)
    return _row_to_user(row) if row else None


async def get_user_by_tenant(tenant_id: str) -> dict[str, Any] | None:
    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM comply_users WHERE tenant_id = $1 LIMIT 1", tenant_id
        )
    return _row_to_user(row) if row else None


async def set_user_tier(user_id: str, tier: str) -> None:
    async with get_db() as conn:
        await conn.execute(
            "UPDATE comply_users SET tier = $1, updated_at = now() WHERE user_id = $2",
            tier,
            user_id,
        )


async def set_github_installation(user_id: str, installation_id: str) -> None:
    async with get_db() as conn:
        await conn.execute(
            """
            UPDATE comply_users
            SET github_installation_id = $1, updated_at = now()
            WHERE user_id = $2
            """,
            installation_id,
            user_id,
        )


async def get_github_installation(user_id: str) -> str | None:
    async with get_db() as conn:
        row = await conn.fetchrow(
            "SELECT github_installation_id FROM comply_users WHERE user_id = $1",
            user_id,
        )
    return row["github_installation_id"] if row else None


# ── API Keys ─────────────────────────────────────────────────────


async def create_api_key(data: dict[str, Any]) -> None:
    expires_at = data.get("expires_at")
    async with get_db() as conn:
        await conn.execute(
            """
            INSERT INTO comply_api_keys
                (key_hash, key_id, user_id, name, key_prefix, tier, revoked, expires_at, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            ON CONFLICT (key_hash) DO UPDATE SET
                name = EXCLUDED.name,
                tier = EXCLUDED.tier,
                revoked = FALSE,
                expires_at = EXCLUDED.expires_at
            """,
            data["key_hash"],
            data.get("key_id", ""),
            data["user_id"],
            data.get("name", "default"),
            data.get("key_prefix", ""),
            data.get("tier", "free"),
            data.get("revoked", False),
            datetime.fromisoformat(expires_at) if expires_at else None,
            data.get("created_at", _now_iso()),
        )


async def get_api_key(key_hash: str) -> dict[str, Any] | None:
    async with get_db() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM comply_api_keys
            WHERE key_hash = $1 AND revoked = FALSE
              AND (expires_at IS NULL OR expires_at > now())
            """,
            key_hash,
        )
    return _row_to_api_key(row) if row else None


async def list_api_keys(user_id: str) -> list[dict[str, Any]]:
    async with get_db() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM comply_api_keys
            WHERE user_id = $1 AND revoked = FALSE
            ORDER BY created_at DESC
            """,
            user_id,
        )
    return [_row_to_api_key(r) for r in rows]


async def revoke_api_key(user_id: str, key_id: str) -> bool:
    async with get_db() as conn:
        result = await conn.execute(
            """
            UPDATE comply_api_keys
            SET revoked = TRUE
            WHERE user_id = $1 AND key_id = $2
            """,
            user_id,
            key_id,
        )
    # asyncpg execute returns a status string like "UPDATE 1"
    return "UPDATE 1" in result


async def revoke_all_api_keys(user_id: str) -> None:
    async with get_db() as conn:
        await conn.execute(
            "UPDATE comply_api_keys SET revoked = TRUE WHERE user_id = $1",
            user_id,
        )
