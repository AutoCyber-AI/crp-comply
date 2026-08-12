# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for Phase 5a preference profile + learner."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from crp_comply.agent.preference_learner import PreferenceLearner
from crp_comply.agent.preferences import (
    PreferenceStore,
    UserPreferenceProfile,
    set_preference_store,
)
from crp_comply.agent.user_need import UserNeed
from crp_comply.api.app import create_app
from crp_comply.api.auth import AuthManager, Tier
from crp_comply.api.deps import init_dependencies
from crp_comply.api.usage import init_usage_tracker


# ── Unit tests: preference store ───────────────────────────────────────────


def test_store_creates_default(tmp_path):
    store = PreferenceStore(tmp_path)
    p = store.load("tenant-1", "user-a")
    assert p.user_id == "user-a"
    assert p.tenant_id == "tenant-1"
    assert p.preferred_depth == "standard"


def test_store_round_trip(tmp_path):
    store = PreferenceStore(tmp_path)
    p = store.load("t1", "u1")
    p.preferred_depth = "thorough"
    p.preferred_format = "checklist"
    p.preferred_regulations = ["gdpr", "eu_ai_act"]
    store.save(p)

    p2 = store.load("t1", "u1")
    assert p2.preferred_depth == "thorough"
    assert p2.preferred_format == "checklist"
    assert p2.preferred_regulations == ["gdpr", "eu_ai_act"]


def test_store_sanitizes_paths(tmp_path):
    store = PreferenceStore(tmp_path)
    p = store.load("t/t", "u@u")
    p.preferred_depth = "brief"
    store.save(p)
    assert (tmp_path / "user_preferences" / "t_t" / "u_u.json").exists()


def test_profile_applies_defaults():
    p = UserPreferenceProfile(
        tenant_id="t", user_id="u", preferred_depth="thorough", preferred_format="checklist"
    )
    need = UserNeed()
    p.apply_to_user_need(need)
    assert need.depth == "thorough"
    assert need.format == "checklist"


def test_profile_does_not_override_explicit():
    p = UserPreferenceProfile(tenant_id="t", user_id="u", preferred_depth="thorough")
    need = UserNeed(depth="brief")
    p.apply_to_user_need(need)
    assert need.depth == "brief"


def test_profile_footnote():
    p = UserPreferenceProfile(
        tenant_id="t", user_id="u", preferred_depth="brief", preferred_format="checklist"
    )
    assert "usually prefer" in p.system_prompt_footnote()


# ── Unit tests: preference learner ─────────────────────────────────────────


def test_learner_updates_depth_from_comment():
    p = UserPreferenceProfile(tenant_id="t", user_id="u")
    learner = PreferenceLearner()
    for _ in range(3):
        learner.update_from_feedback(
            p,
            {"signal": "boost", "comment": "I like short answers", "rating": 5},
        )
    assert p.preferred_depth == "brief"
    assert p.explicit_feedback_count == 3


def test_reject_stronger_than_boost():
    p = UserPreferenceProfile(tenant_id="t", user_id="u")
    learner = PreferenceLearner()
    learner.update_from_feedback(p, {"signal": "boost", "sources": ["https://example.com/good"]})
    learner.update_from_feedback(p, {"signal": "reject", "sources": ["https://example.com/good"]})
    score = p.feedback_summary.get("domain_score:example.com", 0)
    assert score < 0


def test_learner_updates_regulation_focus():
    p = UserPreferenceProfile(tenant_id="t", user_id="u")
    learner = PreferenceLearner()
    learner.update_from_feedback(p, {"signal": "boost", "regulation": "gdpr"})
    assert "gdpr" in p.preferred_regulations


def test_update_from_session():
    p = UserPreferenceProfile(tenant_id="t", user_id="u")
    learner = PreferenceLearner()
    learner.update_from_session(
        p,
        {
            "depth": "thorough",
            "regulation": "eu_ai_act",
            "citations": [{"url": "https://edpb.europa.eu/note"}],
        },
    )
    assert p.implicit_signal_count == 1
    assert "eu_ai_act" in p.preferred_regulations
    assert "edpb.europa.eu" in p.trusted_source_domains


# ── API tests: /me/preferences ─────────────────────────────────────────────


@pytest_asyncio.fixture
async def pref_client(tmp_path):
    app = create_app()
    auth = AuthManager(data_dir=tmp_path, jwt_secret="test-secret-prefs")
    comply = object()  # type: ignore[assignment]
    init_dependencies(auth=auth, comply=comply)  # type: ignore[arg-type]
    init_usage_tracker(data_dir=tmp_path)
    set_preference_store(PreferenceStore(tmp_path))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        c._test_auth = auth  # type: ignore[attr-defined]
        yield c


def _auth_headers(auth: AuthManager, *, tier: Tier = Tier.PRO) -> dict:
    user = auth.upsert_oauth_user(
        provider="test",
        provider_id="pref-user",
        email="pref@example.com",
        name="Pref User",
    )
    auth.set_user_tier(user.id, tier)
    return {"Authorization": f"Bearer {auth.create_token(user.id)}"}


@pytest.mark.asyncio
async def test_get_preferences_default(pref_client):
    headers = _auth_headers(pref_client._test_auth)
    resp = await pref_client.get("/api/v1/me/preferences", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["preferred_depth"] == "standard"
    assert body["user_id"]


@pytest.mark.asyncio
async def test_update_preferences(pref_client):
    headers = _auth_headers(pref_client._test_auth)
    resp = await pref_client.post(
        "/api/v1/me/preferences",
        json={"preferred_depth": "thorough", "preferred_format": "checklist"},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["preferred_depth"] == "thorough"
    assert body["preferred_format"] == "checklist"

    get_resp = await pref_client.get("/api/v1/me/preferences", headers=headers)
    assert get_resp.json()["preferred_depth"] == "thorough"


@pytest.mark.asyncio
async def test_reset_preferences(pref_client):
    headers = _auth_headers(pref_client._test_auth)
    await pref_client.post(
        "/api/v1/me/preferences",
        json={"preferred_depth": "thorough"},
        headers=headers,
    )
    resp = await pref_client.post(
        "/api/v1/me/preferences",
        json={"reset": True},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["preferred_depth"] == "standard"


@pytest.mark.asyncio
async def test_preferences_requires_auth(pref_client):
    resp = await pref_client.get("/api/v1/me/preferences")
    assert resp.status_code == 401
