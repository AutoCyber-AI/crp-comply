# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for Gateway audit stream ingestion in CRP Comply."""

from __future__ import annotations

import hashlib
import hmac
import json
import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from crp_comply.api.app import create_app
from crp_comply.api.auth import AuthManager
from crp_comply.api.deps import init_dependencies
from crp_comply.api.reports import init_report_store
from crp_comply.api.usage import init_usage_tracker
from crp_comply.api.webhooks import sign_payload
from crp_comply.core import CRPComply
from crp_comply.gateway_audit_store import verify_gateway_event_hmac


def _sign_event(event: dict, secret: bytes) -> dict:
    """Return an event with a valid HMAC-SHA256 signature."""
    canonical = json.dumps(event, sort_keys=True, separators=(",", ":"))
    sig = hmac.new(secret, canonical.encode("utf-8"), hashlib.sha256).hexdigest()
    return {**event, "hmac": f"sha256:{sig}"}


@pytest_asyncio.fixture
async def client(tmp_path):
    app = create_app()
    auth = AuthManager(data_dir=tmp_path, jwt_secret="test-secret")
    comply = CRPComply()
    init_dependencies(auth=auth, comply=comply)
    init_usage_tracker(data_dir=tmp_path)
    init_report_store(data_dir=tmp_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_gateway_audit_webhook_missing_secret(client):
    """Webhook endpoint returns 503 when no secret is configured."""
    # Ensure no secret is configured for this test.
    for key in ("CRP_COMPLY_WEBHOOK_SECRET_GATEWAY-AUDIT", "CRP_COMPLY_WEBHOOK_SECRET"):
        os.environ.pop(key, None)
    resp = await client.post("/api/v1/webhooks/gateway-audit", json={"events": []})
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_gateway_audit_webhook_signature_format(client):
    """The signature format round-trips through the generic webhook verifier."""
    secret = "test-secret"
    body = b'{"events": [], "session_id": "s1"}'
    sig = sign_payload(secret, body)
    # The generic webhook source would need CRP_COMPLY_WEBHOOK_SECRET set.
    os.environ["CRP_COMPLY_WEBHOOK_SECRET"] = secret
    resp = await client.post(
        "/api/v1/webhooks/gateway-audit",
        content=body,
        headers={"X-CRPComply-Signature": sig, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "gateway-audit"
    assert data["status"] == "ok"


def test_verify_gateway_event_hmac():
    """HMAC verification accepts valid signatures and rejects tampered events."""
    secret = b"audit-secret"
    event = {"event_type": "SESSION_CREATED", "session_id": "s1", "index": 0}
    signed = _sign_event(event, secret)

    assert verify_gateway_event_hmac(signed, secret) is True
    assert verify_gateway_event_hmac(event, secret) is False  # missing hmac

    tampered = dict(signed)
    tampered["session_id"] = "s2"
    assert verify_gateway_event_hmac(tampered, secret) is False

    assert verify_gateway_event_hmac(signed, b"wrong-secret") is False


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")
@pytest.mark.asyncio
async def test_persist_audit_events():
    """Integration test: persist and retrieve Gateway audit events."""
    import asyncpg

    from crp_comply.gateway_audit_store import (
        get_events,
        init_gateway_audit_schema,
        persist_audit_events,
    )

    dsn = os.environ["DATABASE_URL"]
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    await init_gateway_audit_schema(pool)
    session_id = "test-comply-session"
    await pool.execute("DELETE FROM gateway_audit_events WHERE session_id = $1", session_id)

    secret = b"audit-secret"
    events = [
        _sign_event(
            {
                "event_type": "SESSION_CREATED",
                "severity": "INFO",
                "session_id": session_id,
                "window_id": "w0",
                "index": 0,
                "data": {"msg": "start"},
            },
            secret,
        )
    ]
    count = await persist_audit_events(
        pool, events, tenant_id="tenant-1", session_id=session_id, hmac_secret=secret
    )
    assert count == 1

    stored = await get_events(pool, session_id)
    assert len(stored) == 1
    assert stored[0]["event_type"] == "SESSION_CREATED"

    await pool.execute("DELETE FROM gateway_audit_events WHERE session_id = $1", session_id)
    await pool.close()


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")
@pytest.mark.asyncio
async def test_persist_audit_events_skips_unverified():
    """Events with invalid HMAC are skipped when a secret is supplied."""
    import asyncpg

    from crp_comply.gateway_audit_store import (
        get_events,
        init_gateway_audit_schema,
        persist_audit_events,
    )

    dsn = os.environ["DATABASE_URL"]
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    await init_gateway_audit_schema(pool)
    session_id = "test-comply-session-unverified"
    await pool.execute("DELETE FROM gateway_audit_events WHERE session_id = $1", session_id)

    secret = b"audit-secret"
    valid_event = _sign_event(
        {
            "event_type": "SESSION_CREATED",
            "severity": "INFO",
            "session_id": session_id,
            "window_id": "w0",
            "index": 0,
            "data": {"msg": "start"},
        },
        secret,
    )
    invalid_event = dict(valid_event)
    invalid_event["index"] = 1
    invalid_event["data"] = {"msg": "tampered"}

    count = await persist_audit_events(
        pool,
        [valid_event, invalid_event],
        tenant_id="tenant-1",
        session_id=session_id,
        hmac_secret=secret,
    )
    assert count == 1

    stored = await get_events(pool, session_id)
    assert len(stored) == 1
    assert stored[0]["event_index"] == 0

    await pool.execute("DELETE FROM gateway_audit_events WHERE session_id = $1", session_id)
    await pool.close()
