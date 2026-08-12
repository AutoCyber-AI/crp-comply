# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Shared async PostgreSQL connection pool.

Used by BOTH CRP Gateway and CRP Comply.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from crp_shared.passkey import PASSKEY_SCHEMA

logger = logging.getLogger(__name__)

_pool: Any | None = None

# Schema for CRP Comply tables that use the shared pool.
_COMPLY_SCHEMA = """
CREATE TABLE IF NOT EXISTS webhook_events (
    event_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    event_type TEXT NOT NULL,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_webhook_events_source ON webhook_events(source);

CREATE TABLE IF NOT EXISTS billing_reconciliation_runs (
    id SERIAL PRIMARY KEY,
    ran_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    dry_run BOOLEAN NOT NULL DEFAULT false,
    checked INTEGER NOT NULL DEFAULT 0,
    repaired INTEGER NOT NULL DEFAULT 0,
    errors INTEGER NOT NULL DEFAULT 0,
    details JSONB NOT NULL DEFAULT '[]'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_billing_reconciliation_runs_ran_at ON billing_reconciliation_runs(ran_at DESC);

CREATE TABLE IF NOT EXISTS public_assessments (
    id SERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    risk_level TEXT NOT NULL,
    category TEXT NOT NULL,
    ip_hash TEXT,
    lead_email BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_public_assessments_ts ON public_assessments(ts);

-- User / API key persistence (migration path from JSON files)
CREATE TABLE IF NOT EXISTS comply_users (
    user_id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    name TEXT NOT NULL,
    provider TEXT NOT NULL,
    tier TEXT NOT NULL DEFAULT 'free',
    tenant_id TEXT NOT NULL,
    github_installation_id TEXT,
    disabled BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_comply_users_tenant ON comply_users(tenant_id);
CREATE INDEX IF NOT EXISTS idx_comply_users_github ON comply_users(github_installation_id);

CREATE TABLE IF NOT EXISTS comply_api_keys (
    key_hash TEXT PRIMARY KEY,
    key_id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES comply_users(user_id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    key_prefix TEXT NOT NULL,
    tier TEXT NOT NULL DEFAULT 'free',
    revoked BOOLEAN NOT NULL DEFAULT FALSE,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_comply_api_keys_user ON comply_api_keys(user_id);
CREATE INDEX IF NOT EXISTS idx_comply_api_keys_revoked ON comply_api_keys(revoked);
"""


async def _ensure_database(dsn: str) -> None:
    """Create the target database if it does not exist.

    Connects to the default 'postgres' database so we can issue CREATE DATABASE.
    """
    import asyncpg
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(dsn)
    admin_url = urlunparse(parsed._replace(path="/postgres"))
    target_db = parsed.path.lstrip("/") or "crp_comply"
    conn = await asyncpg.connect(admin_url)
    try:
        row = await conn.fetchrow(
            "SELECT 1 FROM pg_database WHERE datname = $1", target_db
        )
        if not row:
            await conn.execute(f'CREATE DATABASE "{target_db}"')
            logger.info("Created database: %s", target_db)
    finally:
        await conn.close()


async def init_db() -> None:
    """Initialize the asyncpg connection pool.

    Call once at application startup (e.g. in FastAPI lifespan).
    """
    global _pool
    import asyncpg

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise RuntimeError("DATABASE_URL environment variable is not set")

    await _ensure_database(dsn)
    _pool = await asyncpg.create_pool(
        dsn,
        min_size=2,
        max_size=10,
        command_timeout=30,
    )
    async with _pool.acquire() as conn:
        await conn.execute(_COMPLY_SCHEMA)
        await conn.execute(PASSKEY_SCHEMA)
    logger.info("PostgreSQL pool and schema ready: %s", dsn.split("@")[-1].split("/")[0])


async def init_comply_schema() -> None:
    """Idempotent schema setup for CRP Comply tables."""
    if _pool is None:
        return
    async with _pool.acquire() as conn:
        await conn.execute(_COMPLY_SCHEMA)
        await conn.execute(PASSKEY_SCHEMA)
    async with _pool.acquire() as conn:
        await conn.execute(_COMPLY_SCHEMA)


def get_db() -> Any:
    """Acquire a connection from the pool.

    Usage::
        async with get_db() as conn:
            row = await conn.fetchrow("SELECT ...")

    Note: this is a synchronous factory that returns an asyncpg
    ``AcquireContext``.  Callers must use ``async with`` to await it.
    """
    if _pool is None:
        raise RuntimeError("Database pool not initialized. Call init_db() first.")
    return _pool.acquire()


async def close_db() -> None:
    """Close the connection pool. Call on shutdown."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("PostgreSQL pool closed")
