# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for CRP Comply FastAPI API."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from crp_comply.api.app import create_app
from crp_comply.api.deps import init_dependencies
from crp_comply.api.auth import AuthManager
from crp_comply.api.usage import init_usage_tracker
from crp_comply.api.reports import init_report_store
from crp_comply.core import CRPComply


@pytest_asyncio.fixture
async def client(tmp_path):
    app = create_app()
    # Manually initialise dependencies (lifespan doesn't run with ASGITransport)
    auth = AuthManager(data_dir=tmp_path, jwt_secret="test-secret")
    comply = CRPComply()
    init_dependencies(auth=auth, comply=comply)
    init_usage_tracker(data_dir=tmp_path)
    init_report_store(data_dir=tmp_path)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ── Health ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert "version" in data
    assert "crp_version" in data
    assert "comply_version" in data


# ── Risk Assessment ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_risk_assessment(client):
    resp = await client.post(
        "/api/v1/risk-assessment",
        json={"system_name": "TestAI", "category": "GENERAL_PURPOSE"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["system_name"] == "TestAI"
    assert data["risk_level"] in ("MINIMAL", "LIMITED", "HIGH", "UNACCEPTABLE")


@pytest.mark.asyncio
async def test_risk_assessment_missing_name(client):
    resp = await client.post(
        "/api/v1/risk-assessment",
        json={"category": "GENERAL_PURPOSE"},
    )
    assert resp.status_code == 422


# ── Compliance Report ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_compliance_report(client):
    resp = await client.post(
        "/api/v1/compliance-report",
        json={"system_name": "TestAI"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "score" in data
    assert data["score"] > 0  # Should have a real score now
    assert "generated_at" in data
    assert data["overall_status"] in ("compliant", "partially_compliant", "non_compliant")
    assert len(data["controls"]) > 0  # Should contain actual controls


# ── Tier Gating ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dpia_requires_pro_tier(client):
    resp = await client.post(
        "/api/v1/dpia",
        json={"system_name": "TestAI"},
    )
    assert resp.status_code == 403
    assert "higher tier" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_transparency_requires_pro_tier(client):
    resp = await client.post(
        "/api/v1/transparency",
        json={"system_name": "TestAI"},
    )
    assert resp.status_code == 403


# ── API Key Management ────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_api_key(client):
    resp = await client.post(
        "/api/v1/keys",
        json={"name": "test-key", "tier": "pro"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "test-key"
    assert data["tier"] == "pro"
    assert "key" in data
    assert data["key"].startswith("crp_")


@pytest.mark.asyncio
async def test_list_api_keys(client):
    # Create a key first
    await client.post("/api/v1/keys", json={"name": "list-test", "tier": "free"})
    resp = await client.get("/api/v1/keys")
    assert resp.status_code == 200
    keys = resp.json()
    assert isinstance(keys, list)
    assert len(keys) >= 1


@pytest.mark.asyncio
async def test_pro_key_unlocks_dpia(client):
    # Create a PRO key
    key_resp = await client.post(
        "/api/v1/keys",
        json={"name": "pro-test", "tier": "pro"},
    )
    api_key = key_resp.json()["key"]

    # Use it to access DPIA
    resp = await client.post(
        "/api/v1/dpia",
        json={"system_name": "TestAI"},
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["dpia_required"] in (True, False)
    assert len(data["risk_categories"]) > 0  # Should have real risk data
    assert len(data["mitigations"]) > 0  # Should have real mitigations


@pytest.mark.asyncio
async def test_revoke_api_key(client):
    # Create then revoke
    key_resp = await client.post(
        "/api/v1/keys",
        json={"name": "revoke-test", "tier": "free"},
    )
    key_id = key_resp.json()["id"]

    resp = await client.delete(f"/api/v1/keys/{key_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "revoked"


@pytest.mark.asyncio
async def test_revoke_nonexistent_key(client):
    resp = await client.delete("/api/v1/keys/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_invalid_api_key_rejected(client):
    resp = await client.post(
        "/api/v1/dpia",
        json={"system_name": "TestAI"},
        headers={"X-Api-Key": "crc_invalid_key"},
    )
    assert resp.status_code == 401


# ── CLOUD Tier & Certificate ──────────────────────────────────


@pytest.mark.asyncio
async def test_certificate_requires_cloud_tier(client):
    """PRO key should be denied access to certificate endpoint."""
    key_resp = await client.post(
        "/api/v1/keys",
        json={"name": "pro-cert-test", "tier": "pro"},
    )
    api_key = key_resp.json()["key"]
    resp = await client.post(
        "/api/v1/certificate",
        json={"system_name": "TestAI", "organisation": "TestCorp"},
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 403
    assert "higher tier" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_cloud_key_unlocks_certificate(client):
    """CLOUD key should be able to issue a signed certificate."""
    key_resp = await client.post(
        "/api/v1/keys",
        json={"name": "cloud-test", "tier": "cloud"},
    )
    api_key = key_resp.json()["key"]
    resp = await client.post(
        "/api/v1/certificate",
        json={"system_name": "TestAI", "organisation": "TestCorp"},
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["certificate_id"].startswith("CRC-")
    assert data["system_name"] == "TestAI"
    assert data["organisation"] == "TestCorp"
    assert data["issuer"] == "AutoCyber AI Pty Ltd \u2014 CRP Comply Cloud"
    assert len(data["signature"]) == 64  # SHA-256 hex
    assert "crprotocol.io/verify/" in data["verification_url"]
    assert len(data["frameworks"]) >= 2


@pytest.mark.asyncio
async def test_cloud_key_has_all_features(client):
    """CLOUD key should unlock all endpoints including DPIA, transparency."""
    key_resp = await client.post(
        "/api/v1/keys",
        json={"name": "cloud-full", "tier": "cloud"},
    )
    api_key = key_resp.json()["key"]

    # DPIA should work
    resp = await client.post(
        "/api/v1/dpia",
        json={"system_name": "TestAI"},
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 200

    # Transparency should work
    resp = await client.post(
        "/api/v1/transparency",
        json={"system_name": "TestAI"},
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_create_cloud_api_key(client):
    resp = await client.post(
        "/api/v1/keys",
        json={"name": "cloud-key", "tier": "cloud"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["tier"] == "cloud"
    assert data["key"].startswith("crp_")


# ── P3 GAP-024: ContextualKnowledgeFabric ─────────────────────


@pytest.mark.asyncio
async def test_knowledge_health(client):
    resp = await client.get("/api/v1/knowledge/health")
    assert resp.status_code == 200
    data = resp.json()
    assert "health" in data
    assert "should_gc" in data


@pytest.mark.asyncio
async def test_knowledge_store_requires_facts(client):
    resp = await client.post("/api/v1/knowledge/store", json={})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_knowledge_store_and_health(client):
    # Store some facts
    resp = await client.post(
        "/api/v1/knowledge/store",
        json={"facts": [{"text": "Test fact"}], "window_id": "test-1"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["stored"] == 1


# ── P3 GAP-025: Observability / Telemetry ─────────────────────


@pytest.mark.asyncio
async def test_telemetry_endpoint(client):
    resp = await client.get("/api/v1/telemetry")
    assert resp.status_code == 200
    data = resp.json()
    assert "records" in data
    assert "total" in data


@pytest.mark.asyncio
async def test_quality_report(client):
    resp = await client.get("/api/v1/quality")
    assert resp.status_code == 200
    data = resp.json()
    assert "reporter_available" in data


@pytest.mark.asyncio
async def test_emit_event(client):
    resp = await client.post(
        "/api/v1/events/emit",
        json={"event_type": "SESSION_START", "data": {"test": True}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["emitted"] is True


@pytest.mark.asyncio
async def test_emit_requires_event_type(client):
    resp = await client.post("/api/v1/events/emit", json={"data": {}})
    assert resp.status_code == 400


# ── P3 GAP-029: RetentionManager + DataLineageTracker ─────────


@pytest.mark.asyncio
async def test_retention_register(client):
    key_resp = await client.post(
        "/api/v1/keys",
        json={"name": "ent-test", "tier": "enterprise"},
    )
    api_key = key_resp.json()["key"]
    resp = await client.post(
        "/api/v1/retention/register",
        json={"data_id": "test-data-1", "classification": "INTERNAL", "source_label": "test"},
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["registered"] is True


@pytest.mark.asyncio
async def test_retention_expired(client):
    key_resp = await client.post(
        "/api/v1/keys",
        json={"name": "ent-test2", "tier": "enterprise"},
    )
    api_key = key_resp.json()["key"]
    resp = await client.get(
        "/api/v1/retention/expired",
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "expired" in data
    assert "manager_available" in data


@pytest.mark.asyncio
async def test_retention_enforce(client):
    key_resp = await client.post(
        "/api/v1/keys",
        json={"name": "ent-test3", "tier": "enterprise"},
    )
    api_key = key_resp.json()["key"]
    resp = await client.post(
        "/api/v1/retention/enforce",
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "purged" in data


@pytest.mark.asyncio
async def test_lineage_record(client):
    key_resp = await client.post(
        "/api/v1/keys",
        json={"name": "ent-lineage", "tier": "enterprise"},
    )
    api_key = key_resp.json()["key"]
    resp = await client.post(
        "/api/v1/lineage/record",
        json={"data_id": "lineage-1", "origin": "user-upload", "source_label": "test"},
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["recorded"] is True


@pytest.mark.asyncio
async def test_lineage_get(client):
    key_resp = await client.post(
        "/api/v1/keys",
        json={"name": "ent-lineage2", "tier": "enterprise"},
    )
    api_key = key_resp.json()["key"]
    resp = await client.get(
        "/api/v1/lineage/some-data-id",
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "tracker_available" in data


@pytest.mark.asyncio
async def test_retention_free_tier_blocked(client):
    resp = await client.post(
        "/api/v1/retention/register",
        json={"data_id": "test", "classification": "PUBLIC"},
    )
    assert resp.status_code == 403


# ── P3 GAP-030: HumanOversightController ──────────────────────


@pytest.mark.asyncio
async def test_oversight_check(client):
    key_resp = await client.post(
        "/api/v1/keys",
        json={"name": "ent-oversight", "tier": "enterprise"},
    )
    api_key = key_resp.json()["key"]
    resp = await client.post(
        "/api/v1/oversight/check",
        json={"operation": "export"},
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "requires_approval" in data
    assert "level" in data
    assert "halt_on_injection" in data


@pytest.mark.asyncio
async def test_oversight_check_requires_operation(client):
    key_resp = await client.post(
        "/api/v1/keys",
        json={"name": "ent-oversight2", "tier": "enterprise"},
    )
    api_key = key_resp.json()["key"]
    resp = await client.post(
        "/api/v1/oversight/check",
        json={},
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_oversight_approve(client):
    key_resp = await client.post(
        "/api/v1/keys",
        json={"name": "ent-oversight3", "tier": "enterprise"},
    )
    api_key = key_resp.json()["key"]
    resp = await client.post(
        "/api/v1/oversight/approve",
        json={"operation": "export", "approved": True, "reason": "Authorized by admin"},
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["recorded"] is True
    assert data["approved"] is True


@pytest.mark.asyncio
async def test_oversight_config(client):
    key_resp = await client.post(
        "/api/v1/keys",
        json={"name": "ent-oversight4", "tier": "enterprise"},
    )
    api_key = key_resp.json()["key"]
    resp = await client.get(
        "/api/v1/oversight/config",
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "controller_available" in data


# ── P3 GAP-031: ScaleModeSelector ─────────────────────────────


@pytest.mark.asyncio
async def test_scale_configure(client):
    resp = await client.post(
        "/api/v1/scale/configure",
        json={"estimated_tokens": 100000, "model_capability": 1},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "quality_tier" in data
    assert "processing_mode" in data
    assert "cqs_enabled" in data


@pytest.mark.asyncio
async def test_scale_small_task(client):
    resp = await client.post(
        "/api/v1/scale/configure",
        json={"estimated_tokens": 1000},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "quality_tier" in data


# ── P3 GAP-033: EmbeddingDefense ──────────────────────────────


@pytest.mark.asyncio
async def test_protect_embeddings(client):
    key_resp = await client.post(
        "/api/v1/keys",
        json={"name": "ent-embed", "tier": "enterprise"},
    )
    api_key = key_resp.json()["key"]
    resp = await client.post(
        "/api/v1/embeddings/protect",
        json={"embedding": [0.1, 0.2, 0.3, 0.4, 0.5]},
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["protected"] is True
    assert data["dimensions"] == 5


@pytest.mark.asyncio
async def test_protect_requires_embedding(client):
    key_resp = await client.post(
        "/api/v1/keys",
        json={"name": "ent-embed2", "tier": "enterprise"},
    )
    api_key = key_resp.json()["key"]
    resp = await client.post(
        "/api/v1/embeddings/protect",
        json={},
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_protect_free_tier_blocked(client):
    resp = await client.post(
        "/api/v1/embeddings/protect",
        json={"embedding": [0.1, 0.2]},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_recover_requires_data(client):
    key_resp = await client.post(
        "/api/v1/keys",
        json={"name": "ent-embed3", "tier": "enterprise"},
    )
    api_key = key_resp.json()["key"]
    resp = await client.post(
        "/api/v1/embeddings/recover",
        json={},
        headers={"X-Api-Key": api_key},
    )
    assert resp.status_code == 400


# ── Storage Preference ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_storage_preference(client):
    resp = await client.get("/api/v1/storage/preference")
    assert resp.status_code == 200
    data = resp.json()
    assert data["storage_mode"] == "local"
    assert "local_data_dir" in data
    assert "cloud_available" in data


@pytest.mark.asyncio
async def test_set_storage_preference_local(client):
    resp = await client.post(
        "/api/v1/storage/preference",
        json={"mode": "local"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["storage_mode"] == "local"


@pytest.mark.asyncio
async def test_set_storage_preference_invalid(client):
    resp = await client.post(
        "/api/v1/storage/preference",
        json={"mode": "invalid"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_set_cloud_without_env(client):
    resp = await client.post(
        "/api/v1/storage/preference",
        json={"mode": "cloud"},
    )
    assert resp.status_code == 400
