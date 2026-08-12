# Copyright © 2025 Constantinos Vidiniotis. All rights reserved.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Checkpoint inbox — human reviewer resolution endpoint (SPEC-034).

Provides HTTP-style handlers for the Comply Inbox surface.
Integrates with SafetyControlPlane and ComplianceAuditTrail.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any

from crp.security.checkpoint import CheckpointResolution, CheckpointResolutionAction
from crp.security.control_plane import get_default_control_plane

logger = logging.getLogger(__name__)


class CheckpointInboxError(Exception):
    """Raised when checkpoint resolution fails."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _audit_secret() -> bytes:
    """Return HMAC secret for audit events from env."""
    raw = os.environ.get("CRP_AUDIT_SECRET", "")
    return raw.encode() if raw else b"checkpoint-audit-default"


def _sign_audit_event(event: dict[str, Any]) -> dict[str, Any]:
    """HMAC-sign an audit event dict."""
    payload = json.dumps(event, sort_keys=True).encode()  # type: ignore[name-defined]
    sig = hmac.new(_audit_secret(), payload, hashlib.sha256).hexdigest()[:16]
    event["audit_sig"] = sig
    return event


def resolve_checkpoint(
    checkpoint_id: str,
    action: str,
    reviewer: str,
    edited_output: str = "",
    note: str = "",
) -> dict[str, Any]:
    """Resolve a checkpoint by ID (called by reviewer/webhook).

    Args:
        checkpoint_id: The UUID of the checkpoint to resolve.
        action: ``approve``, ``reject``, or ``edit``.
        reviewer: Identifier of the human reviewer (Clerk user ID).
        edited_output: If action is ``edit``, the modified output.
        note: Optional human note.

    Returns:
        Dict with ``status``, ``checkpoint_id``, ``audit_ref``.

    Raises:
        CheckpointInboxError: if checkpoint not found or action invalid.
    """
    scp = get_default_control_plane()
    cp = scp._checkpoints.get(checkpoint_id)
    if cp is None:
        raise CheckpointInboxError(f"Checkpoint {checkpoint_id} not found", status_code=404)

    try:
        resolution_action = CheckpointResolutionAction(action)
    except ValueError as exc:
        raise CheckpointInboxError(f"Invalid action: {action}") from exc

    resolution = CheckpointResolution(
        action=resolution_action,
        reviewer=reviewer,
        edited_output=edited_output,
        audit_event={
            "checkpoint_id": checkpoint_id,
            "note": note,
            "tenant_id": cp.context.get("session_id", "unknown"),
        },
    )

    cp.resolve(resolution)

    # HMAC-signed audit event
    audit_event = resolution.to_audit_dict()
    audit_event["checkpoint_id"] = checkpoint_id
    audit_event["note"] = note
    _sign_audit_event(audit_event)

    logger.info(
        "Checkpoint %s resolved by %s: action=%s",
        checkpoint_id,
        reviewer,
        action,
    )

    return {
        "status": "resolved",
        "checkpoint_id": checkpoint_id,
        "action": action,
        "audit_ref": audit_event["audit_sig"],
        "timestamp": resolution.timestamp,
    }


def list_active_checkpoints(tenant_id: str | None = None) -> list[dict[str, Any]]:
    """Return all unresolved checkpoints, optionally filtered by tenant."""
    scp = get_default_control_plane()
    results: list[dict[str, Any]] = []
    for cid, cp in scp._checkpoints.items():
        if cp._resolution is not None:
            continue  # already resolved
        if tenant_id and cp.context.get("tenant_id") != tenant_id:
            continue
        results.append(
            {
                "checkpoint_id": cid,
                "trigger": cp.trigger.value,
                "timeout": cp.timeout,
                "created_at": cp.context.get("created_at", time.time()),
                "context": cp.context,
            }
        )
    return results
