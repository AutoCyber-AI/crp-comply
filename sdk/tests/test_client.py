"""Tests for crp_comply_sdk.CRPComply — fully mocked, no network."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from crp_comply_sdk import (
    CRPComply,
    CRPComplyAuthError,
    CRPComplyError,
    CRPComplyQuotaError,
    CRPComplyServerError,
    CRPComplyTierError,
)


# ── fixtures ────────────────────────────────────────────────────


def _make_client(handler) -> CRPComply:
    """Build a CRPComply bound to a MockTransport with the given handler."""
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    return CRPComply(
        api_key="crp_test_key",
        base_url="https://api.example.com/api/v1",
        http_client=http,
    )


def _json_response(payload: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        content=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


# ── configuration ──────────────────────────────────────────────


def test_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CRP_COMPLY_API_KEY", raising=False)
    with pytest.raises(CRPComplyAuthError):
        CRPComply()


def test_reads_api_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRP_COMPLY_API_KEY", "crp_env_key")
    client = CRPComply()
    assert client._api_key == "crp_env_key"
    client.close()


def test_reads_base_url_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRP_COMPLY_API_KEY", "crp_x")
    monkeypatch.setenv("CRP_COMPLY_BASE_URL", "https://custom.example.com/v2/")
    client = CRPComply()
    assert client._base_url == "https://custom.example.com/v2"
    client.close()


def test_context_manager_closes() -> None:
    client = _make_client(lambda req: _json_response({}))
    with client as c:
        assert c is client
    # Second close should be safe
    client.close()


# ── auth header + transport ────────────────────────────────────


def test_sets_bearer_header() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["ua"] = request.headers.get("user-agent")
        return _json_response({"status": "ok"})

    client = _make_client(handler)
    client.me()
    assert seen["auth"] == "Bearer crp_test_key"
    assert "crp-comply-sdk-python" in (seen["ua"] or "")


def test_health_is_unauthenticated() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return _json_response({"status": "ok"})

    client = _make_client(handler)
    client.health()
    assert seen["auth"] is None


# ── error mapping ──────────────────────────────────────────────


def test_401_raises_auth_error() -> None:
    client = _make_client(lambda r: _json_response({"detail": "bad key"}, 401))
    with pytest.raises(CRPComplyAuthError) as exc:
        client.me()
    assert exc.value.status_code == 401


def test_402_raises_tier_error_with_upgrade_url() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        return _json_response(
            {
                "detail": {
                    "message": "feature not in tier",
                    "feature": "evidence_pack",
                    "current_tier": "FREE",
                    "required_tier": "PRO",
                    "upgrade_url": "https://crp-comply.com/pricing",
                }
            },
            402,
        )

    client = _make_client(handler)
    with pytest.raises(CRPComplyTierError) as exc:
        client.evidence_pack(system_name="X", category="y")
    assert exc.value.feature == "evidence_pack"
    assert exc.value.current_tier == "FREE"
    assert exc.value.required_tier == "PRO"
    assert exc.value.upgrade_url == "https://crp-comply.com/pricing"


def test_429_raises_quota_error() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        return _json_response(
            {
                "detail": {
                    "message": "quota exhausted",
                    "upgrade_url": "https://crp-comply.com/pricing",
                }
            },
            429,
        )

    client = _make_client(handler)
    with pytest.raises(CRPComplyQuotaError) as exc:
        client.audit(prompt="p", response="r")
    assert exc.value.upgrade_url == "https://crp-comply.com/pricing"


def test_500_raises_server_error() -> None:
    client = _make_client(lambda r: _json_response({"detail": "boom"}, 500))
    with pytest.raises(CRPComplyServerError):
        client.me()


# ── team & sharing (Phase 7) ─────────────────────────────────────


def test_team_role() -> None:
    client = _make_client(lambda r: _json_response({"role": "admin", "tenant_id": "t_1"}))
    assert client.team_role() == {"role": "admin", "tenant_id": "t_1"}


def test_create_share_report() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return _json_response({"share_id": "s_1", "url": "https://x/s_1"})

    client = _make_client(handler)
    result = client.create_share(report_id="r_1", recipient_email="a@example.com", expires_in_days=3)
    assert result["share_id"] == "s_1"
    assert seen["method"] == "POST"
    assert seen["body"]["report_id"] == "r_1"
    assert seen["body"]["recipient_email"] == "a@example.com"
    assert seen["body"]["expires_in_days"] == 3


def test_create_share_requires_resource() -> None:
    client = _make_client(lambda r: _json_response({}))
    with pytest.raises(ValueError):
        client.create_share()


def test_list_shares() -> None:
    client = _make_client(lambda r: _json_response({"shares": [{"share_id": "s_1"}]}))
    assert client.list_shares()["shares"][0]["share_id"] == "s_1"


def test_revoke_share() -> None:
    client = _make_client(lambda r: _json_response({"status": "revoked", "share_id": "s_1"}))
    assert client.revoke_share("s_1")["status"] == "revoked"


def test_get_shared_report_is_unauthenticated() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return _json_response({"markdown": "# report"})

    client = _make_client(handler)
    result = client.get_shared_report("s_1")
    assert result["markdown"] == "# report"
    assert seen["auth"] is None


def test_network_error_wraps() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    client = _make_client(handler)
    with pytest.raises(CRPComplyError):
        client.me()


def test_invalid_json_raises() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"not-json", headers={"content-type": "application/json"}
        )

    client = _make_client(handler)
    with pytest.raises(CRPComplyError):
        client.me()


# ── endpoint routing ───────────────────────────────────────────


def test_risk_assessment_posts_correct_body() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["method"] = request.method
        seen["body"] = json.loads(request.content)
        return _json_response({"risk_level": "HIGH"})

    client = _make_client(handler)
    client.risk_assessment(
        system_name="Hiring",
        category="employment",
        affects_fundamental_rights=True,
    )
    assert seen["method"] == "POST"
    assert seen["url"].endswith("/risk-assessment")
    assert seen["body"]["system_name"] == "Hiring"
    assert seen["body"]["category"] == "employment"
    assert seen["body"]["affects_fundamental_rights"] is True


def test_compliance_report_markdown_flag_routes_to_markdown_endpoint() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return _json_response({"markdown": "# Report"})

    client = _make_client(handler)
    client.compliance_report(system_name="X", category="y", markdown=True)
    assert seen["url"].endswith("/compliance-report/markdown")

    client.compliance_report(system_name="X", category="y", markdown=False)
    assert seen["url"].endswith("/compliance-report")


def test_list_reports_with_kind_filter() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return _json_response({"reports": [], "total": 0})

    client = _make_client(handler)
    client.list_reports(kind="dpia")
    assert "kind=dpia" in seen["url"]


def test_download_evidence_pack_returns_bytes() -> None:
    zip_bytes = b"PK\x03\x04fake zip content"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=zip_bytes)

    client = _make_client(handler)
    got = client.download_evidence_pack("pack-123")
    assert got == zip_bytes


def test_get_report_markdown_returns_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content="# hi".encode("utf-8"))

    client = _make_client(handler)
    assert client.get_report_markdown("r1") == "# hi"


def test_delete_returns_empty_on_204() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    client = _make_client(handler)
    assert client.delete_report("r1") == {}


def test_audit_builds_body_with_optional_fields() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _json_response({"risk_level": "LOW", "pii_detected": False})

    client = _make_client(handler)
    client.audit(
        prompt="hello",
        response="hi",
        system_name="Bot",
        metadata={"trace_id": "t1"},
    )
    assert seen["body"] == {
        "prompt": "hello",
        "response": "hi",
        "system_name": "Bot",
        "metadata": {"trace_id": "t1"},
    }


def test_classify_risk_accepts_iterable_use_cases() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _json_response({"risk_level": "high"})

    client = _make_client(handler)
    client.classify_risk(
        system_name="Hiring",
        description="CV screener",
        use_cases=iter(["cv_screening", "ranking"]),
    )
    assert seen["body"]["use_cases"] == ["cv_screening", "ranking"]
