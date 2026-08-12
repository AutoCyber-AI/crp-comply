# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Checkpoint resolution API routes.

Exposes pending checkpoints to the frontend Inbox and allows
reviewers to approve/reject/edit them.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from crp_comply.api.deps import get_current_user
from crp_comply.agent.mcp_permissions import PolicyEnforcer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/checkpoints", tags=["checkpoints"])

# In-memory store of enforcers per session (production: Redis)
_session_enforcers: dict[str, PolicyEnforcer] = {}


def register_enforcer(session_id: str, enforcer: PolicyEnforcer) -> None:
    """Called by the agent orchestrator when a session starts."""
    _session_enforcers[session_id] = enforcer


@router.get("/")
async def list_checkpoints(
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    """List all pending checkpoints across active sessions."""
    pending: list[dict[str, Any]] = []
    for session_id, enforcer in _session_enforcers.items():
        for cp in enforcer.list_pending_checkpoints():
            pending.append(
                {
                    "checkpoint_id": cp.checkpoint_id,
                    "session_id": cp.session_id,
                    "tool_name": cp.tool_name,
                    "tool_args": cp.tool_args,
                    "reason": cp.reason,
                    "created_at": cp.created_at,
                    "timeout_seconds": cp.timeout_seconds,
                    "tenant_id": cp.tenant_id,
                }
            )
    return {"checkpoints": pending, "count": len(pending)}


@router.post("/{checkpoint_id}/resolve")
async def resolve_checkpoint(
    checkpoint_id: str,
    request: Request,
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    """Resolve a checkpoint: approve or reject."""
    body = await request.json()
    action = str(body.get("action", "")).strip().lower()
    if action not in {"approve", "reject"}:
        raise HTTPException(status_code=400, detail="action must be 'approve' or 'reject'")
    note = body.get("note")
    note_str = str(note).strip() if note is not None else None

    # Find the enforcer that owns this checkpoint
    for session_id, enforcer in _session_enforcers.items():
        if enforcer.resolve_checkpoint(
            checkpoint_id,
            approved=(action == "approve"),
            resolved_by=user_id,
            note=note_str,
        ):
            logger.info(
                "Checkpoint %s resolved by %s: %s",
                checkpoint_id,
                user_id,
                action,
            )
            return {
                "status": "resolved",
                "checkpoint_id": checkpoint_id,
                "action": action,
                "resolved_by": user_id,
                "note": note_str,
            }

    raise HTTPException(status_code=404, detail="Checkpoint not found or expired")


@router.get("/{checkpoint_id}")
async def get_checkpoint(
    checkpoint_id: str,
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    """Get details of a single checkpoint."""
    for session_id, enforcer in _session_enforcers.items():
        for cp in enforcer.list_pending_checkpoints():
            if cp.checkpoint_id == checkpoint_id:
                return {
                    "checkpoint_id": cp.checkpoint_id,
                    "session_id": cp.session_id,
                    "tool_name": cp.tool_name,
                    "tool_args": cp.tool_args,
                    "reason": cp.reason,
                    "created_at": cp.created_at,
                    "timeout_seconds": cp.timeout_seconds,
                    "tenant_id": cp.tenant_id,
                }
    raise HTTPException(status_code=404, detail="Checkpoint not found or expired")
