# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for the draft-session bridge endpoints."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from crp_comply.api.app import create_app
from crp_comply.api.auth import AuthManager
from crp_comply.core import CRPComply
from crp_comply.api.deps import init_dependencies
from crp_comply.api.draft_sessions import init_draft_sessions
from crp_comply.api.reports import init_report_store
from crp_comply.api.usage import init_usage_tracker


@pytest_asyncio.fixture
async def client(tmp_path):
    app = create_app()
    auth = AuthManager(data_dir=tmp_path, jwt_secret="test-secret")
    comply = CRPComply()
    init_dependencies(auth=auth, comply=comply)
    init_usage_tracker(data_dir=tmp_path)
    init_report_store(data_dir=tmp_path)
    init_draft_sessions(data_dir=tmp_path)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, auth


def _user_token(auth: AuthManager, user_id: str) -> str:
    auth.upsert_oauth_user(
        provider="clerk",
        provider_id=user_id,
        email=f"{user_id}@example.com",
        name=user_id,
    )
    return auth.create_token(f"clerk:{user_id}")


def _auth_header(user_id: str, auth: AuthManager) -> dict[str, str]:
    return {"Authorization": f"Bearer {_user_token(auth, user_id)}"}


@pytest.mark.asyncio
async def test_create_draft_session(client):
    c, auth = client
    resp = await c.post(
        "/api/v1/drafts",
        json={"recipe_id": "iso_42001_statement_of_applicability", "system_name": "TestAI"},
        headers=_auth_header("user-a", auth),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["recipe_id"] == "iso_42001_statement_of_applicability"
    assert data["system_name"] == "TestAI"
    assert data["session_id"]
    assert data["state"] == "not_started"
    assert data["report_id"] == ""


@pytest.mark.asyncio
async def test_list_and_get_draft_sessions(client):
    c, auth = client
    create_resp = await c.post(
        "/api/v1/drafts",
        json={"recipe_id": "eu_ai_act_art_27_fria"},
        headers=_auth_header("user-list", auth),
    )
    session_id = create_resp.json()["session_id"]

    list_resp = await c.get("/api/v1/drafts", headers=_auth_header("user-list", auth))
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert any(d["session_id"] == session_id for d in items)

    get_resp = await c.get(f"/api/v1/drafts/{session_id}", headers=_auth_header("user-list", auth))
    assert get_resp.status_code == 200
    assert get_resp.json()["session_id"] == session_id


@pytest.mark.asyncio
async def test_link_agent_and_report(client):
    c, auth = client
    create_resp = await c.post(
        "/api/v1/drafts",
        json={"recipe_id": "nist_ai_rmf_profile"},
        headers=_auth_header("user-link", auth),
    )
    session_id = create_resp.json()["session_id"]

    agent_resp = await c.post(
        f"/api/v1/drafts/{session_id}/agent",
        json={"agent_session_id": "agent-123"},
        headers=_auth_header("user-link", auth),
    )
    assert agent_resp.status_code == 200
    assert agent_resp.json()["agent_session_id"] == "agent-123"

    report_resp = await c.post(
        f"/api/v1/drafts/{session_id}/report",
        json={"report_id": "report-456"},
        headers=_auth_header("user-link", auth),
    )
    assert report_resp.status_code == 200
    assert report_resp.json()["report_id"] == "report-456"


@pytest.mark.asyncio
async def test_delete_draft_session(client):
    c, auth = client
    create_resp = await c.post(
        "/api/v1/drafts",
        json={"recipe_id": "eu_ai_act_art_27_fria"},
        headers=_auth_header("user-delete", auth),
    )
    session_id = create_resp.json()["session_id"]

    del_resp = await c.delete(
        f"/api/v1/drafts/{session_id}", headers=_auth_header("user-delete", auth)
    )
    assert del_resp.status_code == 204

    get_resp = await c.get(
        f"/api/v1/drafts/{session_id}", headers=_auth_header("user-delete", auth)
    )
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_draft_sessions_isolated_between_users(client):
    c, auth = client

    create_resp = await c.post(
        "/api/v1/drafts",
        json={"recipe_id": "iso_42001_statement_of_applicability"},
        headers=_auth_header("user-alpha", auth),
    )
    session_id = create_resp.json()["session_id"]

    get_a = await c.get(f"/api/v1/drafts/{session_id}", headers=_auth_header("user-alpha", auth))
    assert get_a.status_code == 200

    get_b = await c.get(f"/api/v1/drafts/{session_id}", headers=_auth_header("user-beta", auth))
    assert get_b.status_code == 404

    list_b = await c.get("/api/v1/drafts", headers=_auth_header("user-beta", auth))
    assert session_id not in {d["session_id"] for d in list_b.json()}
