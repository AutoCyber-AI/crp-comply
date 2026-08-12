# Copyright © 2025 Constantinos Vidiniotis. All rights reserved.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Bidirectional header mapping: X-CRP-Comply-* ↔ CRP-* (SPEC-042 §3.3).

Preserves the existing wire contract so current customer integrations
keep working while the backend routes through the CRP Gateway.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Request: Comply → Gateway
# ---------------------------------------------------------------------------

# Mapping from X-CRP-Comply-* request headers to standard CRP-* headers.
# Keys are lower-cased for case-insensitive matching.
COMPLY_TO_CRP_REQUEST: dict[str, str] = {
    "x-crp-comply-session": "CRP-Session-Token",
    "x-crp-comply-coverage": "CRP-Coverage-Set",
    "x-crp-comply-safety-policy": "CRP-Safety-Policy",
    "x-crp-comply-context-mode": "CRP-Context-Strategy",
    "x-crp-comply-accept-risk": "CRP-Accept-Risk",
    "x-crp-comply-protocol-version": "CRP-Context-Protocol-Version",
}

# ---------------------------------------------------------------------------
# Response: Gateway → Comply
# ---------------------------------------------------------------------------

# Mapping from standard CRP-* response headers back to X-CRP-Comply-*.
# This keeps existing client parsers working.
CRP_TO_COMPLY_RESPONSE: dict[str, str] = {
    "CRP-Safety-Hallucination-Risk": "X-CRP-Comply-Hallucination-Risk",
    "CRP-Safety-Hallucination-Score": "X-CRP-Comply-Hallucination-Score",
    "CRP-Safety-Grounding-Pct": "X-CRP-Comply-Grounding-Pct",
    "CRP-Safety-Fabrications": "X-CRP-Comply-Fabrications",
    "CRP-Safety-Contradictions": "X-CRP-Comply-Contradictions",
    "CRP-Safety-Distortions": "X-CRP-Comply-Distortions",
    "CRP-Safety-Attribution": "X-CRP-Comply-Attribution",
    "CRP-Compliance-Audit-Trail-URI": "X-CRP-Comply-Record-ID",
    "CRP-Context-Session-Id": "X-CRP-Comply-Session-Id",
    "CRP-Context-Quality-Tier": "X-CRP-Comply-Quality-Tier",
    "CRP-Context-Window": "X-CRP-Comply-Window",
    "CRP-Safety-Oversight-Mode": "X-CRP-Comply-Oversight-Mode",
}

# Hard allowlist of headers that may be forwarded to the LLM provider.
# Axiom 4: NO CRP-* header ever reaches the provider.
# This is the same allowlist used by the Gateway itself.
_PROVIDER_HEADER_ALLOWLIST: frozenset[str] = frozenset(
    {
        "authorization",
        "content-type",
        "accept",
        "user-agent",
        "x-request-id",
        "anthropic-version",
        "anthropic-beta",
    }
)


def map_request_headers(headers: dict[str, str]) -> dict[str, str]:
    """Translate incoming X-CRP-Comply-* headers to standard CRP-* headers.

    Unrecognised headers are passed through unchanged.
    """
    mapped: dict[str, str] = {}
    for key, value in headers.items():
        lower = key.lower()
        if lower in COMPLY_TO_CRP_REQUEST:
            mapped[COMPLY_TO_CRP_REQUEST[lower]] = value
        else:
            mapped[key] = value
    return mapped


def map_response_headers(headers: dict[str, str]) -> dict[str, str]:
    """Translate Gateway CRP-* response headers back to X-CRP-Comply-*.

    Also injects ``X-CRP-Comply: active`` to signal Comply governance.
    """
    mapped: dict[str, str] = {"X-CRP-Comply": "active"}
    for key, value in headers.items():
        if key in CRP_TO_COMPLY_RESPONSE:
            mapped[CRP_TO_COMPLY_RESPONSE[key]] = value
        else:
            mapped[key] = value
    return mapped


def strip_crp_headers_before_provider(headers: dict[str, str]) -> dict[str, str]:
    """Return a copy of *headers* with all CRP-* headers removed.

    Enforces Axiom 4 (Model Ignorance).  Only headers in the provider
    allowlist are retained.
    """
    return {k: v for k, v in headers.items() if k.lower() in _PROVIDER_HEADER_ALLOWLIST}
