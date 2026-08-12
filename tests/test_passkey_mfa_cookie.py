# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for HttpOnly cookie handling of the passkey MFA token."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from crp_comply.api.app import create_app
from crp_comply.api.auth import AuthManager
from crp_comply.api.deps import init_dependencies
from crp_comply.api.usage import init_usage_tracker
from crp_comply.core import CRPComply


class _FakePasskeyManager:
    """In-memory stand-in for the real passkey manager."""

    def __init__(self) -> None:
        self.session_ttl_seconds = 3600
        self.pool = None  # get_passkey_manager_for_request reads this.
        self._tokens: dict[str, str] = {}
        self._counter = 0

    async def verify_authentication(
        self,
        credential_dict: dict[str, Any],
        context: Any,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "user_id": "clerk:user_123",
            "credential_id": "cred-1",
            "decision": "allow",
            "risk_score": 10.0,
            "risk_factors": [],
        }

    async def create_mfa_session(
        self,
        user_id: str,
        credential_id: str,
        context: Any,
        risk_score: float,
    ) -> str:
        self._counter += 1
        token = f"mfa-token-{self._counter}"
        self._tokens[token] = user_id
        return token

    async def verify_mfa_session(self, token: str | None, user_id: str, context: Any) -> Any:
        from crp_shared.passkey import RiskAssessment

        if not token:
            return None
        if self._tokens.get(token) == user_id:
            return RiskAssessment(score=10.0, factors=[], decision="allow")
        return None

    async def revoke_mfa_session(self, token: str) -> None:
        self._tokens.pop(token, None)

    async def has_credentials(self, user_id: str) -> bool:
        return True


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    """Yield an AsyncClient against a test app with a fake passkey manager."""
    monkeypatch.setenv("PASSKEY_MFA_DISABLED", "false")
    monkeypatch.setenv("CLERK_ISSUER", "https://test.clerk.accounts.dev")

    app = create_app()
    auth = AuthManager(data_dir=tmp_path, jwt_secret="test-secret")
    comply = CRPComply()
    init_dependencies(auth=auth, comply=comply)
    init_usage_tracker(data_dir=tmp_path)

    fake_manager = _FakePasskeyManager()

    # Patch both passkey manager accessors so every route sees the fake.
    with (
        patch("crp_comply.api.deps._passkey_manager", fake_manager),
        patch("crp_comply.api.deps.get_passkey_manager", return_value=fake_manager),
        patch("crp_comply.api.routes.get_passkey_manager_for_request", return_value=fake_manager),
        patch(
            "crp_comply.api.session_routes.get_passkey_manager_for_request",
            return_value=fake_manager,
        ),
        patch(
            "crp_comply.api.routes._comply_passkey_user_id",
            return_value=("clerk:user_123", None),
        ),
        patch.object(
            auth,
            "verify_clerk_token",
            return_value={"sub": "user_123"},
        ),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as c:
            c._fake_passkey_manager = fake_manager  # type: ignore[attr-defined]
            yield c


@pytest.mark.asyncio
async def test_passkeys_verify_sets_http_only_cookie(client):
    """/passkeys/verify sets the MFA token as an HttpOnly cookie."""
    resp = await client.post(
        "/api/v1/passkeys/verify",
        headers={"Authorization": "Bearer fake-clerk-token"},
        json={"credential": {"id": "cred-1", "rawId": "x", "response": {}}},
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["mfa_token"]

    set_cookie = resp.headers.get("set-cookie")
    assert set_cookie is not None
    assert "crp_passkey_mfa_token=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "samesite=strict" in set_cookie.lower()


@pytest.mark.asyncio
async def test_step_up_sets_http_only_cookie(client):
    """/auth/step-up also sets the MFA token as an HttpOnly cookie."""
    # step-up requires a server-side session cookie first.
    session_resp = await client.post(
        "/api/v1/auth/session",
        headers={"Authorization": "Bearer fake-clerk-token"},
    )
    # Session creation is allowed before MFA because it is the session
    # bootstrap endpoint.
    assert session_resp.status_code == 200

    resp = await client.post(
        "/api/v1/auth/step-up",
        headers={"Authorization": "Bearer fake-clerk-token"},
        json={"credential": {"id": "cred-1", "rawId": "x", "response": {}}},
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "elevated"
    assert data["mfa_token"]

    set_cookie = resp.headers.get("set-cookie")
    assert set_cookie is not None
    assert "crp_passkey_mfa_token=" in set_cookie
    assert "HttpOnly" in set_cookie


@pytest.mark.asyncio
async def test_protected_route_accepts_passkey_cookie(client):
    """A protected route passes MFA when the token is supplied only as a cookie."""
    # First obtain an MFA cookie.
    resp = await client.post(
        "/api/v1/passkeys/verify",
        headers={"Authorization": "Bearer fake-clerk-token"},
        json={"credential": {"id": "cred-1", "rawId": "x", "response": {}}},
    )
    assert resp.status_code == 200
    mfa_cookie = resp.cookies.get("crp_passkey_mfa_token")
    assert mfa_cookie is not None

    # Then hit a protected route using only the cookie (no MFA header).
    client.cookies.set("crp_passkey_mfa_token", mfa_cookie)
    resp2 = await client.get(
        "/api/v1/billing/status",
        headers={"Authorization": "Bearer fake-clerk-token"},
    )

    # 200/402/404 are all acceptable — the middleware allowed the request.
    assert resp2.status_code in (200, 402, 404)


@pytest.mark.asyncio
async def test_revoked_mfa_cookie_is_rejected(client):
    """After the server revokes the MFA session the cookie no longer works."""
    resp = await client.post(
        "/api/v1/passkeys/verify",
        headers={"Authorization": "Bearer fake-clerk-token"},
        json={"credential": {"id": "cred-1", "rawId": "x", "response": {}}},
    )
    assert resp.status_code == 200
    mfa_cookie = resp.cookies.get("crp_passkey_mfa_token")
    assert mfa_cookie is not None

    # Simulate server-side revocation.
    await client._fake_passkey_manager.revoke_mfa_session(mfa_cookie)

    client.cookies.set("crp_passkey_mfa_token", mfa_cookie)
    resp2 = await client.get(
        "/api/v1/billing/status",
        headers={"Authorization": "Bearer fake-clerk-token"},
    )

    assert resp2.status_code == 403
    assert resp2.json().get("code") == "passkey_mfa_required"
