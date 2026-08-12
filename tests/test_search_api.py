# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for the global search endpoint (Phase 2 deferred backend)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def search_client(monkeypatch, tmp_path):
    """API client with file-backed stores in a temp directory."""
    monkeypatch.setenv("CRP_COMPLY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CRP_COMPLY_JWT_SECRET", "t" * 32)

    from crp_comply.api.app import create_app

    app = create_app()
    with TestClient(app) as client:
        yield client


def test_search_recipes_default(search_client):
    r = search_client.get("/api/v1/search?scopes=recipe&limit=100")
    assert r.status_code == 200
    data = r.json()
    assert data["query"] == ""
    ids = {item["id"] for item in data["results"]}
    assert "iso_42001_statement_of_applicability" in ids


def test_search_recipes_filtered(search_client):
    r = search_client.get("/api/v1/search?q=eu&scopes=recipe")
    assert r.status_code == 200
    data = r.json()
    assert all("eu" in (item["title"] + " " + item["subtitle"]).lower() for item in data["results"])


def test_search_scopes_limit_to_type(search_client):
    r = search_client.get("/api/v1/search?scopes=recipe")
    assert r.status_code == 200
    assert all(item["type"] == "recipe" for item in r.json()["results"])


def test_search_reports(search_client, tmp_path):
    from crp_comply.api.reports import get_report_store

    store = get_report_store()
    store.save(
        user_id="anonymous",
        kind="risk_assessment",
        system_name="AcmeBot Risk Review",
        tier="FREE",
        payload={"summary": "test"},
    )

    r = search_client.get("/api/v1/search?q=acmebot&scopes=report")
    assert r.status_code == 200
    results = r.json()["results"]
    assert len(results) == 1
    assert results[0]["type"] == "report"
    assert results[0]["title"] == "AcmeBot Risk Review"
    assert results[0]["url"].startswith("/app/vault/")


def test_search_artefacts(search_client, tmp_path):
    from crp_comply.api.artefacts import get_artefact_store

    store = get_artefact_store()
    store.save(
        user_id="anonymous",
        kind="other",
        filename="PrivacyPolicy.pdf",
        content_type="application/pdf",
        data=b"fake pdf content",
        description="GDPR privacy policy",
    )

    r = search_client.get("/api/v1/search?q=privacy&scopes=artefact")
    assert r.status_code == 200
    results = r.json()["results"]
    assert len(results) == 1
    assert results[0]["type"] == "artefact"
    assert "Privacy" in results[0]["title"]


def test_search_obligations(search_client, tmp_path):
    from crp_comply.programme import get_programme_store
    from crp_comply.programme.lifecycle import ObligationLifecycle

    store = get_programme_store()
    store.upsert(
        ObligationLifecycle(
            obligation_id="iso_42001_soa::acme",
            user_id="anonymous",
            recipe_id="iso_42001_statement_of_applicability",
            system_name="Acme AI System",
            state="NOT_STARTED",
        )
    )

    r = search_client.get("/api/v1/search?q=acme&scopes=obligation")
    assert r.status_code == 200
    results = r.json()["results"]
    assert len(results) == 1
    assert results[0]["type"] == "obligation"
    assert results[0]["title"] == "Acme AI System"


def test_search_respects_limit(search_client):
    r = search_client.get("/api/v1/search?scopes=recipe&limit=5")
    assert r.status_code == 200
    assert len(r.json()["results"]) <= 5
