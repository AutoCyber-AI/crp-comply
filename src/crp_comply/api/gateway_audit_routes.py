# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""CRP Comply endpoints for Gateway audit evidence."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from .deps import get_current_user

logger = logging.getLogger("crp_comply.api.gateway_audit")

router = APIRouter(prefix="/gateway-audit", tags=["gateway-audit"])


def _get_pool():
    from crp_shared.db import _pool

    if _pool is None:
        raise HTTPException(status_code=503, detail="PostgreSQL not available")
    return _pool


@router.get("/sessions/{session_id}/events")
async def list_gateway_audit_events(
    session_id: str,
    limit: int = Query(1000, ge=1, le=10000),
    offset: int = Query(0, ge=0),
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    """List audit events received from the Gateway for a session."""
    pool = _get_pool()
    from ..gateway_audit_store import get_events as _get_events

    events = await _get_events(pool, session_id, limit=limit, offset=offset)
    return {"session_id": session_id, "events": events, "count": len(events)}


@router.post("/sessions/{session_id}/verify")
async def verify_gateway_chain(
    session_id: str,
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    """Ask the upstream Gateway to verify the HMAC chain for a session."""
    gateway_url = os.environ.get("CRP_GATEWAY_URL", "https://gateway.crprotocol.io").rstrip("/")
    gateway_key = os.environ.get("CRP_GATEWAY_KEY", "")
    try:
        headers = {"Content-Type": "application/json"}
        if gateway_key:
            headers["Authorization"] = f"Bearer {gateway_key}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{gateway_url}/crp/v4/verify-chain",
                json={"session_id": session_id},
                headers=headers,
            )
        resp.raise_for_status()
        data = resp.json()
        return {
            "session_id": session_id,
            "gateway_integrity": data.get("integrity", "UNKNOWN"),
            "valid": data.get("valid", False),
            "broken_at": data.get("broken_at"),
        }
    except Exception as exc:
        logger.warning("Gateway chain verification failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"Gateway verification failed: {exc}") from exc
