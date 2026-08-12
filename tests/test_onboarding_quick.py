# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for the deterministic 3-question onboarding classifier."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def onboarding_client(monkeypatch, tmp_path):
    """API client with file-backed stores and no real LLM dependency."""
    monkeypatch.setenv("CRP_COMPLY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CRP_COMPLY_JWT_SECRET", "t" * 32)

    from crp_comply.api.app import create_app

    app = create_app()
    with TestClient(app) as client:
        yield client


def test_quick_onboarding_classifies_provider_in_eu_high_risk(onboarding_client):
    r = onboarding_client.post(
        "/api/v1/onboarding/quick",
        json={
            "actor": "provider",
            "jurisdictions": ["EU"],
            "system_types": ["high_risk", "personal_data"],
            "org_name": "Acme AI",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["profile"]["actor"] == "provider"
    assert data["profile"]["jurisdictions"] == ["EU"]
    assert data["profile"]["established_in_eu"] is True
    assert data["profile"]["is_high_risk"] is True
    assert data["profile"]["processes_personal_data"] is True
    assert "Provider" in data["classification"]
    assert "EU" in data["classification"]
    assert len(data["recommended_recipes"]) > 0
    assert len(data["checklist"]) >= 3


def test_quick_onboarding_rejects_invalid_actor(onboarding_client):
    r = onboarding_client.post(
        "/api/v1/onboarding/quick",
        json={"actor": "hacker", "jurisdictions": ["EU"], "system_types": []},
    )
    assert r.status_code == 422


def test_quick_onboarding_gpai_provider(onboarding_client):
    r = onboarding_client.post(
        "/api/v1/onboarding/quick",
        json={
            "actor": "gpai_provider",
            "jurisdictions": ["US"],
            "system_types": ["gpai"],
        },
    )
    data = r.json()
    assert data["profile"]["is_gpai"] is True
    assert "GPAI provider" in data["classification"]
    assert len(data["recommended_recipes"]) > 0
