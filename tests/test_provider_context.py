# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for the LLM provider context endpoint."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from crp_comply.api.app import create_app
from crp_comply.api.auth import AuthManager
from crp_comply.api.deps import init_dependencies
from crp_comply.api.provider import init_provider_store
from crp_comply.api.reports import init_report_store
from crp_comply.api.usage import init_usage_tracker
from crp_comply.core import CRPComply


@pytest_asyncio.fixture
async def client(tmp_path):
    app = create_app()
    auth = AuthManager(data_dir=tmp_path, jwt_secret="test-secret")
    comply = CRPComply()
    init_dependencies(auth=auth, comply=comply)
    init_usage_tracker(data_dir=tmp_path)
    init_report_store(data_dir=tmp_path)
    init_provider_store(data_dir=tmp_path, secret="test-secret")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, auth


def _token_for(auth: AuthManager, user_id: str) -> str:
    return auth.create_token(user_id)


def _ensure_user(auth: AuthManager, provider_id: str) -> str:
    user_id = f"local:{provider_id}"
    auth.upsert_oauth_user(
        provider="local",
        provider_id=provider_id,
        email=f"{provider_id}@example.com",
        name=provider_id,
    )
    return user_id


@pytest.mark.asyncio
async def test_provider_context_configured(client, monkeypatch):
    c, auth = client
    user_id = _ensure_user(auth, "ctx-user-a")
    token = _token_for(auth, user_id)

    # Configure an OpenAI-compatible provider for the user.
    configure_resp = await c.post(
        "/api/v1/llm/configure",
        json={
            "provider": "openai",
            "api_key": "sk-test",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert configure_resp.status_code == 200

    # Avoid real network calls; pretend the upstream reports a loaded window.
    monkeypatch.setattr(
        "crp_comply.agent.llm._probe_loaded_context_length",
        lambda _base_url, _api_key: 16384,
    )

    resp = await c.get(
        "/api/v1/llm/context",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "openai"
    assert data["base_url"] == "https://api.openai.com/v1"
    assert data["model"] == "gpt-4o-mini"
    assert data["context_window"] == 16384
    assert data["source"] == "user"


@pytest.mark.asyncio
async def test_provider_context_none(client):
    c, auth = client
    user_id = _ensure_user(auth, "ctx-user-none")
    token = _token_for(auth, user_id)

    resp = await c.get(
        "/api/v1/llm/context",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "none"
    assert data["base_url"] is None
    assert data["model"] is None
    assert data["context_window"] is None
    assert data["source"] == "none"


@pytest.mark.asyncio
async def test_provider_context_cross_user_isolation(client, monkeypatch):
    c, auth = client
    user_a = _ensure_user(auth, "ctx-user-a2")
    user_b = _ensure_user(auth, "ctx-user-b2")
    token_a = _token_for(auth, user_a)
    token_b = _token_for(auth, user_b)

    # Only user A configures a provider.
    configure_resp = await c.post(
        "/api/v1/llm/configure",
        json={
            "provider": "openai",
            "api_key": "sk-test",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini",
        },
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert configure_resp.status_code == 200

    monkeypatch.setattr(
        "crp_comply.agent.llm._probe_loaded_context_length",
        lambda _base_url, _api_key: 8192,
    )

    resp_a = await c.get(
        "/api/v1/llm/context",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp_a.status_code == 200
    data_a = resp_a.json()
    assert data_a["provider"] == "openai"
    assert data_a["source"] == "user"
    assert data_a["context_window"] == 8192

    resp_b = await c.get(
        "/api/v1/llm/context",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp_b.status_code == 200
    data_b = resp_b.json()
    assert data_b["provider"] == "none"
    assert data_b["source"] == "none"
    assert data_b["context_window"] is None
