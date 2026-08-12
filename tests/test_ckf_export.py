# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for CKF GDPR Article 20 export endpoint."""

from __future__ import annotations

import tarfile

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from crp_comply.api.app import create_app
from crp_comply.api.auth import AuthManager
from crp_comply.api.deps import init_dependencies
from crp_comply.api.reports import init_report_store
from crp_comply.api.usage import init_usage_tracker
from crp_comply.core import CRPComply


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CRP_COMPLY_DATA_DIR", str(tmp_path))
    app = create_app()
    auth = AuthManager(data_dir=tmp_path, jwt_secret="test-secret")
    comply = CRPComply()
    init_dependencies(auth=auth, comply=comply)
    init_usage_tracker(data_dir=tmp_path)
    init_report_store(data_dir=tmp_path)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, auth


def _token(auth: AuthManager, user_id: str) -> str:
    auth.upsert_oauth_user(
        provider="clerk",
        provider_id=user_id,
        email=f"{user_id}@example.com",
        name=user_id,
    )
    return auth.create_token(f"clerk:{user_id}")


@pytest.mark.asyncio
async def test_ckf_export_requires_auth(client):
    c, _ = client
    resp = await c.get("/api/v1/ckf/export")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_ckf_export_returns_gzip_tarball(client):
    c, auth = client
    resp = await c.get(
        "/api/v1/ckf/export",
        headers={"Authorization": f"Bearer {_token(auth, 'user-ckf')}"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/gzip"
    assert "attachment" in resp.headers["content-disposition"]

    # Verify it is a valid tar.gz
    data = resp.content
    assert data[:2] == b"\x1f\x8b"
    with tarfile.open(fileobj=__import__("io").BytesIO(data), mode="r:gz") as tf:
        names = tf.getnames()
        assert any("facts.json" in n or "events.json" in n for n in names)
