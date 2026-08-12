# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for evidence sharing endpoints."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from crp_comply.api.app import create_app
from crp_comply.api.auth import AuthManager
from crp_comply.api.deps import init_dependencies
from crp_comply.api.reports import init_report_store
from crp_comply.core import CRPComply


@pytest_asyncio.fixture
async def client(tmp_path):
    app = create_app()
    auth = AuthManager(data_dir=tmp_path, jwt_secret="test-secret")
    comply = CRPComply()
    init_dependencies(auth=auth, comply=comply)
    init_report_store(data_dir=tmp_path)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c.headers["Authorization"] = ""
        yield c


@pytest_asyncio.fixture
async def api_key(client):
    resp = await client.post("/api/v1/keys", json={"name": "share-test", "tier": "pro"})
    assert resp.status_code == 200
    return resp.json()["key"]


@pytest_asyncio.fixture
async def report_record(tmp_path, api_key):
    """Seed a persisted report owned by the API key user."""
    from crp_comply.api.auth import AuthManager

    auth = AuthManager(data_dir=tmp_path, jwt_secret="test-secret")
    user_id, _tier = auth.verify_api_key(api_key)

    from crp_comply.api.reports import get_report_store

    rec = get_report_store().save(
        user_id=user_id,
        kind="compliance_report",
        system_name="Shareable System",
        tier="pro",
        payload={"score": 95},
        markdown="# Compliance Report\n\nEverything is fine.\n",
    )
    return rec


@pytest.mark.asyncio
async def test_create_share(client, api_key, report_record):
    resp = await client.post(
        "/api/v1/shares",
        json={
            "report_id": report_record["id"],
            "recipient_email": "auditor@example.com",
            "expires_in_days": 7,
        },
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["resource_type"] == "report"
    assert data["resource_id"] == report_record["id"]
    assert data["recipient_email"] == "auditor@example.com"
    assert "share_id" in data
    assert "expires_at" in data


@pytest.mark.asyncio
async def test_create_share_requires_report_or_pack(client, api_key):
    resp = await client.post(
        "/api/v1/shares",
        json={"expires_in_days": 7},
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_list_shares(client, api_key, report_record):
    create_resp = await client.post(
        "/api/v1/shares",
        json={"report_id": report_record["id"], "expires_in_days": 7},
        headers={"X-Api-Key": api_key},
    )
    share_id = create_resp.json()["share_id"]

    list_resp = await client.get("/api/v1/shares", headers={"X-Api-Key": api_key})
    assert list_resp.status_code == 200
    shares = list_resp.json()["shares"]
    assert any(s["share_id"] == share_id for s in shares)


@pytest.mark.asyncio
async def test_revoke_share(client, api_key, report_record):
    create_resp = await client.post(
        "/api/v1/shares",
        json={"report_id": report_record["id"], "expires_in_days": 7},
        headers={"X-Api-Key": api_key},
    )
    share_id = create_resp.json()["share_id"]

    revoke_resp = await client.delete(
        f"/api/v1/shares/{share_id}",
        headers={"X-Api-Key": api_key},
    )
    assert revoke_resp.status_code == 200
    assert revoke_resp.json()["revoked"] is True

    list_resp = await client.get("/api/v1/shares", headers={"X-Api-Key": api_key})
    assert not any(s["share_id"] == share_id for s in list_resp.json()["shares"])


@pytest.mark.asyncio
async def test_public_fetch_shared_report(client, api_key, report_record):
    create_resp = await client.post(
        "/api/v1/shares",
        json={"report_id": report_record["id"], "expires_in_days": 7},
        headers={"X-Api-Key": api_key},
    )
    share_id = create_resp.json()["share_id"]

    public_resp = await client.get(f"/api/v1/shares/{share_id}/public")
    assert public_resp.status_code == 200
    data = public_resp.json()
    assert data["share_id"] == share_id
    assert data["resource_type"] == "report"
    assert "# Compliance Report" in data["content"]


@pytest.mark.asyncio
async def test_public_fetch_expired_share_gone(client, api_key, report_record):
    create_resp = await client.post(
        "/api/v1/shares",
        json={"report_id": report_record["id"], "expires_in_days": 7},
        headers={"X-Api-Key": api_key},
    )
    share_id = create_resp.json()["share_id"]

    # Manually expire the stored share to bypass the valid minimum TTL.
    from datetime import datetime, timedelta, timezone
    from crp_comply.api.sharing import _get_store, _share_key

    store = _get_store()
    record = store.get(_share_key(share_id))
    record["expires_at"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    store.set(_share_key(share_id), record)

    public_resp = await client.get(f"/api/v1/shares/{share_id}/public")
    assert public_resp.status_code == 410


@pytest.mark.asyncio
async def test_public_fetch_unknown_share(client):
    resp = await client.get("/api/v1/shares/does-not-exist/public")
    assert resp.status_code == 404
