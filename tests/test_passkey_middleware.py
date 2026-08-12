# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for the passkey MFA middleware fail-closed behaviour."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from crp_comply.api.app import create_app
from crp_comply.api.auth import AuthManager
from crp_comply.api.deps import init_dependencies
from crp_comply.api.usage import init_usage_tracker
from crp_comply.core import CRPComply


@pytest_asyncio.fixture
async def client(tmp_path):
    app = create_app()
    auth = AuthManager(data_dir=tmp_path, jwt_secret="test-secret")
    comply = CRPComply()
    init_dependencies(auth=auth, comply=comply)
    init_usage_tracker(data_dir=tmp_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_passkey_middleware_no_clerk_issuer_lets_route_auth_handle(client):
    """Without a Clerk issuer the middleware cannot prove a token is a Clerk JWT,
    so it falls through to route-level auth. An invalid token is rejected there."""
    env = {
        "CLERK_ISSUER": "",
        "PASSKEY_MFA_DISABLED": "false",
    }
    with patch.dict("os.environ", env, clear=False):
        resp = await client.get(
            "/api/v1/billing/status",
            headers={"Authorization": "Bearer fake-clerk-token"},
        )

    # Route-level auth rejects the invalid token.
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_passkey_middleware_allows_public_routes_when_clerk_unconfigured(client):
    """Public routes remain accessible regardless of Clerk configuration."""
    env = {
        "CLERK_ISSUER": "",
        "PASSKEY_MFA_DISABLED": "false",
    }
    with patch.dict("os.environ", env, clear=False):
        resp = await client.get("/api/v1/public/risk-classifier/stats")

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_passkey_middleware_allows_api_keys_when_clerk_unconfigured(client):
    """API-key auth bypasses the Clerk passkey check."""
    env = {
        "CLERK_ISSUER": "",
        "PASSKEY_MFA_DISABLED": "false",
    }
    with patch.dict("os.environ", env, clear=False):
        resp = await client.get(
            "/api/v1/billing/status",
            headers={"X-Api-Key": "crp_testkey"},
        )

    # Should pass the middleware; may 401 from the route if key invalid.
    assert resp.status_code in (200, 401)
