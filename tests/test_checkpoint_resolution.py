# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for checkpoint resolution API and policy enforcer note capture."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from crp_comply.agent.mcp_permissions import CheckpointRequest, PolicyEnforcer
from crp_comply.api.checkpoint_routes import register_enforcer


@pytest.fixture
def checkpoint_client(monkeypatch, tmp_path):
    """API client with file-backed stores."""
    monkeypatch.setenv("CRP_COMPLY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CRP_COMPLY_JWT_SECRET", "t" * 32)

    from crp_comply.api.app import create_app

    app = create_app()
    with TestClient(app) as client:
        yield client


@pytest.fixture
def enforcer_with_checkpoint() -> PolicyEnforcer:
    """Create an enforcer with one pending checkpoint."""
    enforcer = PolicyEnforcer(session_id="sess_123", tenant_id="t_123")
    request = CheckpointRequest(
        checkpoint_id="cp_123",
        tool_name="send_email",
        tool_args={"to": "auditor@example.com"},
        reason="External email",
        session_id="sess_123",
        tenant_id="t_123",
        created_at=0.0,
        timeout_seconds=300,
    )
    enforcer._checkpoint_queue.append(request)
    register_enforcer("sess_123", enforcer)
    return enforcer


def test_resolve_checkpoint_with_note(
    checkpoint_client: TestClient, enforcer_with_checkpoint: PolicyEnforcer
) -> None:
    """Approving a checkpoint with a note stores the note in the enforcer."""
    response = checkpoint_client.post(
        "/api/v1/checkpoints/cp_123/resolve",
        json={"action": "approve", "note": "Approved by compliance lead"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "approve"
    assert data["note"] == "Approved by compliance lead"
    assert len(enforcer_with_checkpoint.list_pending_checkpoints()) == 0


def test_resolve_checkpoint_reject(
    checkpoint_client: TestClient, enforcer_with_checkpoint: PolicyEnforcer
) -> None:
    """Rejecting a checkpoint clears it from the pending queue."""
    response = checkpoint_client.post(
        "/api/v1/checkpoints/cp_123/resolve",
        json={"action": "reject"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["action"] == "reject"
    assert len(enforcer_with_checkpoint.list_pending_checkpoints()) == 0


def test_resolve_checkpoint_invalid_action(
    checkpoint_client: TestClient, enforcer_with_checkpoint: PolicyEnforcer
) -> None:
    """An invalid action returns a 400 error."""
    response = checkpoint_client.post(
        "/api/v1/checkpoints/cp_123/resolve",
        json={"action": "nope"},
    )
    assert response.status_code == 400
