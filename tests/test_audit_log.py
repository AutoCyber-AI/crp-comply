# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for the unified audit-log endpoint."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from crp_comply.api.app import create_app
from crp_comply.api.auth import AuthManager
from crp_comply.api.deps import init_dependencies
from crp_comply.api.reports import init_report_store
from crp_comply.api.usage import init_usage_tracker
from crp_comply.core import CRPComply
from crp_comply.programme import LifecycleState, get_programme_store, init_programme_store


@pytest_asyncio.fixture
async def client(tmp_path):
    app = create_app()
    auth = AuthManager(data_dir=tmp_path, jwt_secret="test-secret")
    comply = CRPComply()
    init_dependencies(auth=auth, comply=comply)
    init_usage_tracker(data_dir=tmp_path)
    init_report_store(data_dir=tmp_path)
    init_programme_store(data_dir=tmp_path)

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
async def test_audit_log_requires_auth(client):
    c, _ = client
    resp = await c.get("/api/v1/audit-log")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_audit_log_includes_programme_transitions(client):
    c, auth = client
    user_id = "clerk:audit-user"
    # Seed a programme transition so the audit log has something to show.
    get_programme_store().transition(
        user_id=user_id,
        obligation_id="iso_42001_statement_of_applicability",
        recipe_id="iso_42001_statement_of_applicability",
        new_state=LifecycleState.DRAFT_READY,
        reason="recipe drafted",
        observed_evidence=True,
    )

    resp = await c.get(
        "/api/v1/audit-log",
        headers={"Authorization": f"Bearer {_token(auth, 'audit-user')}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert any(e["event_type"] == "lifecycle:draft_ready" for e in data)
    # Newest-first ordering
    timestamps = [e["timestamp"] for e in data]
    assert timestamps == sorted(timestamps, reverse=True)


@pytest.mark.asyncio
async def test_audit_log_isolated_between_users(client):
    c, auth = client
    user_a = "clerk:audit-a"
    user_b = "clerk:audit-b"
    get_programme_store().transition(
        user_id=user_a,
        obligation_id="eu_ai_act_art_27_fria",
        recipe_id="eu_ai_act_art_27_fria",
        new_state=LifecycleState.DRAFT_READY,
        reason="recipe drafted",
        observed_evidence=True,
    )
    get_programme_store().transition(
        user_id=user_b,
        obligation_id="eu_ai_act_art_50_transparency",
        recipe_id="eu_ai_act_art_50_transparency",
        new_state=LifecycleState.DRAFT_READY,
        reason="recipe drafted for b",
        observed_evidence=True,
    )

    resp_b = await c.get(
        "/api/v1/audit-log",
        headers={"Authorization": f"Bearer {_token(auth, 'audit-b')}"},
    )
    assert resp_b.status_code == 200
    ids_b = {e["id"] for e in resp_b.json()}
    assert not any("eu_ai_act_art_27_fria" in eid for eid in ids_b)
    assert any("eu_ai_act_art_50_transparency" in eid for eid in ids_b)
