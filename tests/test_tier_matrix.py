# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Endpoint × tier fuzz tests — Round 17.

Verifies that each paid feature is blocked for the FREE tier and available
for the minimum tier that advertises it in ``TIER_FEATURES``.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from crp_comply.api.app import create_app
from crp_comply.api.auth import AuthManager, Tier, get_tier_features
from crp_comply.api.deps import init_dependencies
from crp_comply.api.usage import init_usage_tracker
from crp_comply.api.reports import init_report_store
from crp_comply.core import CRPComply


# endpoint -> (method, path, payload, required_feature)
ENDPOINTS: list[tuple[str, str, str, dict, str]] = [
    (
        "risk_assessment",
        "POST",
        "/api/v1/risk-assessment",
        {"system_name": "Test", "category": "GENERAL_PURPOSE"},
        "risk_assessment",
    ),
    # The base endpoint serves a basic report to FREE tiers and the full
    # report to paid tiers; the feature gate dynamically selects
    # ``basic_compliance_report`` for the FREE tier.
    (
        "compliance_report",
        "POST",
        "/api/v1/compliance-report",
        {"system_name": "Test", "category": "GENERAL_PURPOSE"},
        "basic_compliance_report",
    ),
    ("dpia", "POST", "/api/v1/dpia", {"system_name": "Test", "data_subjects": "users"}, "dpia"),
    (
        "transparency",
        "POST",
        "/api/v1/transparency",
        {"system_name": "Test"},
        "transparency_declaration",
    ),
    (
        "technical_documentation",
        "POST",
        "/api/v1/technical-docs",
        {"system_name": "Test", "category": "GENERAL_PURPOSE"},
        "technical_documentation",
    ),
    ("session_audit", "POST", "/api/v1/audit", {"session_file": "/tmp/fake.json"}, "session_audit"),
    (
        "evidence_pack",
        "POST",
        "/api/v1/evidence-pack",
        {"system_name": "Test", "category": "GENERAL_PURPOSE"},
        "evidence_pack",
    ),
    (
        "signed_certificate",
        "POST",
        "/api/v1/certificate",
        {"system_name": "Test", "category": "GENERAL_PURPOSE"},
        "signed_certificates",
    ),
]


def _token(auth: AuthManager, user_id: str) -> str:
    return auth.create_token(user_id)


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    # Force file-backed auth stores and internal JWT verification so the
    # test fixture fully controls users without needing PostgreSQL/Clerk.
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CLERK_ISSUER", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("PASSKEY_MFA_DISABLED", "true")
    app = create_app()
    auth = AuthManager(data_dir=tmp_path, jwt_secret="test-secret")
    comply = CRPComply()
    init_dependencies(auth=auth, comply=comply)
    init_usage_tracker(data_dir=tmp_path)
    init_report_store(data_dir=tmp_path)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, auth


def _make_user(auth: AuthManager, tier: Tier, index: int) -> str:
    provider_id = f"{tier.value}:{index}"
    user_id = f"test:{provider_id}"
    auth.upsert_oauth_user(
        provider="test",
        provider_id=provider_id,
        email=f"{tier.value}{index}@example.com",
        name="Test User",
        tenant_id=user_id,
    )
    auth.set_user_tier(user_id, tier)
    return user_id


@pytest.mark.asyncio
@pytest.mark.parametrize("name, method, path, payload, feature", ENDPOINTS)
async def test_free_tier_blocked_from_paid_features(client, name, method, path, payload, feature):
    c, auth = client
    user_id = _make_user(auth, Tier.FREE, hash(name) % 1000)
    resp = await c.request(
        method,
        path,
        json=payload,
        headers={"Authorization": f"Bearer {_token(auth, user_id)}"},
    )
    free_features = get_tier_features(Tier.FREE)
    if feature in free_features:
        # Free tier legitimately exposes this endpoint.
        assert resp.status_code not in (401, 403), (
            f"{name} should be allowed for FREE tier, got {resp.status_code}"
        )
    else:
        assert resp.status_code == 403, (
            f"{name} should be 403 for FREE tier, got {resp.status_code}"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("name, method, path, payload, feature", ENDPOINTS)
async def test_minimum_tier_allowed(client, name, method, path, payload, feature):
    c, auth = client
    # Find the minimum tier that advertises this feature.
    min_tier: Tier | None = None
    for tier in Tier:
        if feature in get_tier_features(tier):
            min_tier = tier
            break
    assert min_tier is not None, f"No tier exposes feature {feature}"

    user_id = _make_user(auth, min_tier, hash(name) % 1000)
    resp = await c.request(
        method,
        path,
        json=payload,
        headers={"Authorization": f"Bearer {_token(auth, user_id)}"},
    )
    # Allowed tiers may still return 422/500 for missing data, but never 403.
    assert resp.status_code != 403, f"{name} should not be 403 for {min_tier.value} tier"
    assert resp.status_code != 401, f"{name} should be authenticated for {min_tier.value} tier"
