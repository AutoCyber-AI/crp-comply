# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""CRP Comply storage for Gateway audit streams (SPEC-011 / SPEC-042).

Provides the schema and persistence layer that receives signed audit events
from a CRP Gateway and stores them as tamper-evident compliance evidence.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

import asyncpg

logger = logging.getLogger("crp_comply.gateway_audit")

_GATEWAY_AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS gateway_audit_events (
    id BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    session_id TEXT NOT NULL,
    window_id TEXT NOT NULL DEFAULT '',
    tenant_id TEXT,
    event_index INTEGER,
    data JSONB NOT NULL DEFAULT '{}',
    hmac TEXT NOT NULL,
    gateway_received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_timestamp TIMESTAMPTZ,
    UNIQUE(event_id, session_id)
);

CREATE INDEX IF NOT EXISTS idx_gateway_audit_events_session
    ON gateway_audit_events(session_id, event_index);
CREATE INDEX IF NOT EXISTS idx_gateway_audit_events_tenant
    ON gateway_audit_events(tenant_id);
CREATE INDEX IF NOT EXISTS idx_gateway_audit_events_received
    ON gateway_audit_events(gateway_received_at);
"""


def verify_gateway_event_hmac(event: dict[str, Any], secret: bytes) -> bool:
    """Verify the HMAC-SHA256 signature on a Gateway audit event.

    The Gateway signs a canonical JSON representation of the event with
    the ``hmac`` field removed. This function recomputes the expected
    signature and compares it using a constant-time comparison. Events
    without an ``hmac`` field are rejected.
    """
    stored_hmac = event.get("hmac", "")
    if not stored_hmac:
        return False

    canonical_event = {k: v for k, v in event.items() if k != "hmac"}
    canonical = json.dumps(canonical_event, sort_keys=True, separators=(",", ":"))
    expected = hmac.new(secret, canonical.encode("utf-8"), hashlib.sha256).hexdigest()

    # Support both bare hex and ``sha256:<hex>`` prefixes.
    stored = stored_hmac.split(":", 1)[-1]
    return hmac.compare_digest(stored, expected)


async def init_gateway_audit_schema(pool: asyncpg.Pool) -> None:
    """Create the Gateway audit event table idempotently."""
    async with pool.acquire() as conn:
        await conn.execute(_GATEWAY_AUDIT_SCHEMA)


async def persist_audit_events(
    pool: asyncpg.Pool,
    events: list[dict[str, Any]],
    tenant_id: str | None,
    session_id: str | None = None,
    *,
    hmac_secret: bytes | None = None,
) -> int:
    """Persist a batch of Gateway audit events. Returns rows inserted.

    If *hmac_secret* is provided, each event is verified before insertion
    and events with invalid signatures are skipped.
    """
    inserted = 0
    async with pool.acquire() as conn:
        for event in events:
            if hmac_secret is not None:
                if not verify_gateway_event_hmac(event, hmac_secret):
                    logger.warning(
                        "Gateway audit event HMAC verification failed for session %s; skipping",
                        event.get("session_id", session_id or ""),
                    )
                    continue
            event_id = (
                f"{event.get('session_id', '')}-{event.get('index', event.get('event_index', ''))}"
            )
            await conn.execute(
                """
                INSERT INTO gateway_audit_events
                    (event_id, event_type, severity, session_id, window_id, tenant_id,
                     event_index, data, hmac, event_timestamp)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                ON CONFLICT (event_id, session_id) DO UPDATE SET
                    data = EXCLUDED.data,
                    hmac = EXCLUDED.hmac,
                    event_timestamp = EXCLUDED.event_timestamp
                """,
                event_id,
                event.get("event_type", "UNKNOWN"),
                event.get("severity", "INFO"),
                event.get("session_id", session_id or ""),
                event.get("window_id", ""),
                tenant_id,
                event.get("index") if event.get("index") is not None else event.get("event_index"),
                event.get("data", {}),
                event.get("hmac", ""),
                event.get("timestamp"),
            )
            inserted += 1
    return inserted


async def get_events(
    pool: asyncpg.Pool,
    session_id: str,
    limit: int = 1000,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return persisted Gateway audit events for a session."""
    rows = await pool.fetch(
        """
        SELECT event_id, event_type, severity, session_id, window_id, tenant_id,
               event_index, data, hmac, event_timestamp
        FROM gateway_audit_events
        WHERE session_id = $1
        ORDER BY event_index ASC NULLS LAST, gateway_received_at ASC
        LIMIT $2 OFFSET $3
        """,
        session_id,
        limit,
        offset,
    )
    return [dict(r) for r in rows]
