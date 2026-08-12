# Copyright © 2025 Constantinos Vidiniotis. All rights reserved.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""CRP Comply Gateway Proxy — thin reverse-proxy adapter (SPEC-042 §3).

Receives OpenAI-compatible requests on ``comply.crprotocol.io/v1``,
maps ``X-CRP-Comply-*`` headers to standard ``CRP-*`` headers, forwards
to the CRP Gateway, and maps the response back — preserving the existing
wire contract without breaking customer integrations.

If the Gateway is unavailable, returns HTTP 503.  No fallback to the
bespoke proxy.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

from crp_comply.header_mapping import (
    map_request_headers,
    map_response_headers,
    strip_crp_headers_before_provider,
)
from crp_comply.quota_gate import QuotaGate

logger = logging.getLogger(__name__)

_DEFAULT_GATEWAY_URL = "https://gateway.crprotocol.io"
_DEFAULT_TIMEOUT = 60.0


class GatewayProxyError(Exception):
    """Raised when the Gateway proxy cannot complete a request."""

    def __init__(self, message: str, status_code: int = 503) -> None:
        super().__init__(message)
        self.status_code = status_code


class ComplyGatewayProxy:
    """Thin proxy between Comply's public endpoint and the CRP Gateway.

    Usage::

        proxy = ComplyGatewayProxy()
        response = await proxy.forward(request_body, request_headers)

    The proxy is async (uses ``httpx.AsyncClient``) so it does not block
    the FastAPI event loop. Streaming responses are supported via
    :meth:`stream`.
    """

    def __init__(
        self,
        gateway_url: str | None = None,
        gateway_key: str | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self._gateway_url = (
            gateway_url or os.environ.get("CRP_GATEWAY_URL", _DEFAULT_GATEWAY_URL)
        ).rstrip("/")
        self._gateway_key = gateway_key or os.environ.get("CRP_GATEWAY_KEY", "")
        self._timeout = timeout
        self._quota_gate = QuotaGate()
        self._client = httpx.AsyncClient(timeout=timeout)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _prepare_headers(self, headers: dict[str, str]) -> dict[str, str]:
        """Map Comply headers → CRP headers and enforce Axiom 4 stripping."""
        crp_headers = map_request_headers(headers)
        # Axiom 4: NO CRP-* header ever reaches the provider.
        provider_headers = strip_crp_headers_before_provider(crp_headers)
        if self._gateway_key:
            provider_headers["Authorization"] = f"Bearer {self._gateway_key}"
        # Remove hop-by-hop headers that httpx will set correctly.
        provider_headers.pop("content-length", None)
        provider_headers.pop("host", None)
        return provider_headers

    async def forward(
        self,
        body: bytes,
        headers: dict[str, str],
        *,
        org_id: str | None = None,
        path: str = "/v1/chat/completions",
        method: str = "POST",
    ) -> dict[str, Any]:
        """Forward a request to the CRP Gateway (non-streaming).

        Args:
            body: Raw request body (JSON bytes).
            headers: Incoming HTTP headers (including X-CRP-Comply-*).
            org_id: Clerk organization ID (for quota gating).
            path: Gateway path to forward to.
            method: HTTP method to use.

        Returns:
            Dict with ``status_code``, ``headers``, and ``body`` keys.

        Raises:
            GatewayProxyError: if the Gateway is unreachable or the org
            is over quota.
        """
        # 1. Quota gate
        if org_id:
            gate_result = self._quota_gate.check(org_id)
            if gate_result["status"] == "quota_exceeded":
                logger.warning("Quota exceeded for org %s", org_id)
                return {
                    "status_code": 429,
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps(
                        {
                            "error": {
                                "code": "quota_exceeded",
                                "message": "Monthly quota exceeded. Please upgrade.",
                                "type": "crp_quota_exceeded",
                            },
                        }
                    ).encode(),
                }

        # 2. Map + strip headers
        provider_headers = self._prepare_headers(headers)

        # 3. Forward to Gateway
        url = f"{self._gateway_url}{path}"
        try:
            resp = await self._client.request(
                method,
                url,
                headers=provider_headers,
                content=body,
            )
        except httpx.RequestError as exc:
            logger.error("Gateway unreachable (%s): %s", url, exc)
            raise GatewayProxyError("Gateway unavailable", status_code=503) from exc

        # 4. Map response headers back to Comply contract
        response_headers = map_response_headers(dict(resp.headers))

        # 5. Record usage if successful
        if org_id and resp.status_code < 300:
            self._quota_gate.record_usage(org_id)

        return {
            "status_code": resp.status_code,
            "headers": response_headers,
            "body": resp.content,
        }

    def stream(
        self,
        body: bytes,
        headers: dict[str, str],
        *,
        org_id: str | None = None,
        path: str = "/v1/chat/completions",
        method: str = "POST",
    ) -> httpx.AsyncClient.stream:
        """Return an httpx streaming context manager for the Gateway request.

        The caller is responsible for entering the async context and
        iterating over response chunks.
        """
        # 1. Quota gate
        if org_id:
            gate_result = self._quota_gate.check(org_id)
            if gate_result["status"] == "quota_exceeded":
                logger.warning("Quota exceeded for org %s", org_id)
                raise GatewayProxyError("Quota exceeded", status_code=429)

        # 2. Map + strip headers
        provider_headers = self._prepare_headers(headers)

        # 3. Return streaming context manager
        url = f"{self._gateway_url}{path}"
        return self._client.stream(method, url, headers=provider_headers, content=body)

    def health(self) -> dict[str, Any]:
        """Quick health check — probes the Gateway root endpoint."""
        try:
            # Use a sync call for the sync health helper; tests can mock this.
            import requests

            r = requests.get(
                f"{self._gateway_url}/health",
                timeout=5.0,
                headers={"Authorization": f"Bearer {self._gateway_key}"}
                if self._gateway_key
                else {},
            )
            return {
                "ok": r.status_code < 300,
                "gateway_status": r.status_code,
                "gateway_url": self._gateway_url,
            }
        except Exception as exc:
            logger.warning("Gateway health check failed: %s", exc)
            return {"ok": False, "gateway_url": self._gateway_url, "error": str(exc)}
