# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for the CRP Comply Gateway proxy (SPEC-042)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from crp_comply.gateway_proxy import ComplyGatewayProxy, GatewayProxyError


@pytest.fixture
def proxy():
    """Create a proxy instance with a fake URL and key."""
    return ComplyGatewayProxy(
        gateway_url="https://gateway.example.com",
        gateway_key="gk_test",
        timeout=5.0,
    )


@pytest.mark.asyncio
async def test_forward_strips_crp_headers(proxy):
    """CRP-* and X-CRP-Comply-* headers must not reach the provider (Axiom 4)."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "application/json"}
    mock_resp.content = b'{"ok": true}'

    captured_headers: dict[str, str] | None = None

    async def _capture_request(method, url, *, headers, content):
        nonlocal captured_headers
        captured_headers = headers
        return mock_resp

    proxy._client.request = _capture_request

    incoming_headers = {
        "Authorization": "Bearer sk-test",
        "Content-Type": "application/json",
        "X-CRP-Comply-Session": "sess-123",
        "CRP-Safety-Policy": "strict",
        "X-Request-ID": "req-1",
        "User-Agent": "test-client",
    }

    await proxy.forward(
        body=b'{"model": "gpt-4"}',
        headers=incoming_headers,
        path="/v1/chat/completions",
        method="POST",
    )

    assert captured_headers is not None
    lower_headers = {k.lower() for k in captured_headers}
    assert "x-crp-comply-session" not in lower_headers
    assert "crp-safety-policy" not in lower_headers
    # Allowlisted headers survive.
    assert "authorization" in lower_headers
    assert "content-type" in lower_headers
    assert "user-agent" in lower_headers
    assert "x-request-id" in lower_headers
    # Gateway key overwrites the Authorization header.
    assert captured_headers["Authorization"] == "Bearer gk_test"


@pytest.mark.asyncio
async def test_forward_maps_comply_headers(proxy):
    """X-CRP-Comply-* headers are mapped to CRP-* before stripping."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "application/json"}
    mock_resp.content = b'{"ok": true}'

    captured_headers: dict[str, str] | None = None

    async def _capture_request(method, url, *, headers, content):
        nonlocal captured_headers
        captured_headers = headers
        return mock_resp

    proxy._client.request = _capture_request

    await proxy.forward(
        body=b"{}",
        headers={"X-CRP-Comply-Session": "sess-123"},
        path="/v1/chat/completions",
        method="POST",
    )

    # After mapping to CRP-Session-Token and then stripping, it must not leak.
    assert captured_headers is not None
    lower_headers = {k.lower() for k in captured_headers}
    assert "crp-session-token" not in lower_headers
    assert "x-crp-comply-session" not in lower_headers


@pytest.mark.asyncio
async def test_forward_all_methods(proxy):
    """The proxy supports GET, POST, PUT, PATCH, DELETE, OPTIONS."""
    mock_resp = MagicMock()
    mock_resp.status_code = 204
    mock_resp.headers = {}
    mock_resp.content = b""

    proxy._client.request = AsyncMock(return_value=mock_resp)

    for method in ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
        result = await proxy.forward(
            body=b"",
            headers={"Authorization": "Bearer sk"},
            path="/v1/models",
            method=method,
        )
        assert result["status_code"] == 204
        proxy._client.request.assert_called()
        proxy._client.request.reset_mock()


@pytest.mark.asyncio
async def test_forward_raises_on_gateway_error(proxy):
    """Network errors surface as GatewayProxyError with 503."""
    proxy._client.request = AsyncMock(side_effect=httpx.RequestError("connection refused"))

    with pytest.raises(GatewayProxyError) as exc_info:
        await proxy.forward(b"{}", headers={}, path="/v1/chat/completions")

    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_forward_quota_exceeded(proxy):
    """Quota exceeded short-circuits before contacting the Gateway."""
    with patch.object(proxy._quota_gate, "check", return_value={"status": "quota_exceeded"}):
        result = await proxy.forward(
            b'{"model": "gpt-4"}',
            headers={},
            org_id="org_overquota",
            path="/v1/chat/completions",
        )

    assert result["status_code"] == 429
    assert result["headers"]["Content-Type"] == "application/json"


@pytest.mark.asyncio
async def test_stream_uses_stripped_headers(proxy):
    """Streaming path prepares headers the same way as non-streaming."""
    fake_cm = MagicMock()
    fake_cm.__aenter__ = AsyncMock()
    fake_cm.__aexit__ = AsyncMock(return_value=False)

    proxy._client.stream = MagicMock(return_value=fake_cm)

    async with proxy.stream(
        body=b'{"stream": true}',
        headers={
            "Authorization": "Bearer sk-test",
            "CRP-Safety-Policy": "strict",
        },
        path="/v1/chat/completions",
        method="POST",
    ) as _:
        pass

    call_kwargs = proxy._client.stream.call_args.kwargs
    forwarded = call_kwargs["headers"]
    lower_headers = {k.lower() for k in forwarded}
    assert "crp-safety-policy" not in lower_headers
    assert forwarded["Authorization"] == "Bearer gk_test"
