# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Unified audit-log endpoint.

Aggregates events from multiple backend sources into a single,
chronologically sorted timeline:

* Gateway audit events (if the PostgreSQL store is available)
* Report and evidence-pack creation events
* Obligation lifecycle transitions

All entries are derived from append-only stores; the endpoint itself does
not mutate any underlying data.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..programme import get_programme_store
from .deps import get_current_user
from .reports import get_pack_builder, get_report_store

logger = logging.getLogger("crp_comply.api.audit_log")

router = APIRouter(prefix="/audit-log", tags=["audit"])


class AuditLogEntry(BaseModel):
    id: str
    timestamp: str
    actor: str
    event_type: str
    description: str
    source: str
    signature: str | None = None
    verified: bool | None = None


def _to_iso(ts: Any) -> str:
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    if ts:
        return str(ts)
    return datetime.now(timezone.utc).isoformat()


def _report_entries(user_id: str, limit: int) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    try:
        store = get_report_store()
    except RuntimeError:
        return entries

    for rec in store.list(user_id, limit=limit):
        entries.append(
            {
                "id": f"report:{rec['id']}",
                "timestamp": rec.get("created_at") or _to_iso(None),
                "actor": user_id,
                "event_type": f"report:{rec.get('kind', 'unknown')}",
                "description": (
                    f"Generated {rec.get('kind', 'unknown')} "
                    f"for {rec.get('system_name', 'unspecified')}"
                ),
                "source": "ReportStore",
            }
        )
    return entries


def _pack_entries(user_id: str, limit: int) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    try:
        pb = get_pack_builder()
    except RuntimeError:
        return entries

    for pack in pb.list(user_id, limit=limit):
        pack_id = pack.get("pack_id") or "unknown"
        entries.append(
            {
                "id": f"pack:{pack_id}",
                "timestamp": pack.get("created_at") or _to_iso(None),
                "actor": user_id,
                "event_type": "evidence_pack:created",
                "description": (
                    f"Generated evidence pack for {pack.get('system_name', 'unspecified')}"
                ),
                "source": "EvidencePackBuilder",
            }
        )
    return entries


def _programme_entries(user_id: str, _limit: int) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    try:
        programme = get_programme_store()
    except RuntimeError:
        return entries

    for rec in programme.list(user_id):
        for h in rec.history or []:
            entries.append(
                {
                    "id": f"lifecycle:{rec.obligation_id}:{h.get('at', '')}",
                    "timestamp": h.get("at") or _to_iso(None),
                    "actor": user_id,
                    "event_type": f"lifecycle:{h.get('to', 'unknown')}",
                    "description": (
                        f"Obligation {rec.obligation_id} transitioned "
                        f"{h.get('from', '?')} → {h.get('to', '?')}"
                        + (f": {h.get('reason')}" if h.get("reason") else "")
                    ),
                    "source": "ProgrammeStore",
                }
            )
    return entries


async def _gateway_entries(user_id: str, limit: int) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    try:
        from crp_shared.db import _pool

        if _pool is None:
            return entries
        rows = await _pool.fetch(
            """
            SELECT event_id, event_type, severity, session_id, tenant_id,
                   event_index, data, hmac, event_timestamp, gateway_received_at
            FROM gateway_audit_events
            WHERE tenant_id = $1 OR tenant_id IS NULL
            ORDER BY gateway_received_at DESC
            LIMIT $2
            """,
            user_id,
            limit,
        )
        for row in rows:
            ts = row["event_timestamp"] or row["gateway_received_at"]
            entries.append(
                {
                    "id": f"gateway:{row['event_id']}",
                    "timestamp": ts.isoformat() if ts else _to_iso(None),
                    "actor": row.get("tenant_id") or user_id,
                    "event_type": f"gateway:{row['event_type']}",
                    "description": (
                        f"Gateway event {row['event_type']} ({row['severity']}) "
                        f"for session {row['session_id']}"
                    ),
                    "source": "GatewayAudit",
                    "signature": row.get("hmac"),
                    "verified": None,
                }
            )
    except Exception as exc:
        logger.debug("Gateway audit events skipped: %s", exc)
    return entries


async def build_audit_log(user_id: str, limit: int = 100) -> list[dict[str, Any]]:
    """Return a unified, sorted audit timeline for ``user_id``.

    Events are collected from ReportStore, EvidencePackBuilder,
    ProgrammeStore, and the Gateway audit table (best-effort). The result
    is sorted newest-first and capped at ``limit`` entries.
    """
    limit = max(1, min(limit, 500))
    entries: list[dict[str, Any]] = []
    entries.extend(_report_entries(user_id, limit))
    entries.extend(_pack_entries(user_id, limit))
    entries.extend(_programme_entries(user_id, limit))
    entries.extend(await _gateway_entries(user_id, limit))

    entries.sort(key=lambda e: e.get("timestamp") or "", reverse=True)
    return entries[:limit]


@router.get("", response_model=list[AuditLogEntry])
async def audit_log(
    user_id: str = Depends(get_current_user),
    limit: int = 100,
):
    """Return the caller's unified audit timeline.

    Anonymous callers are rejected. Events are read from append-only
    backend stores and sorted newest-first.
    """
    if user_id == "anonymous":
        raise HTTPException(status_code=401, detail="Sign in to view audit log.")
    return await build_audit_log(user_id, limit=limit)


__all__ = ["router", "build_audit_log"]
