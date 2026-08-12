# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""CRP Comply — OpenAI-compatible compliance proxy.

Drop-in replacement for any OpenAI-compatible API.  Users change ONE
setting — their ``base_url`` — and every LLM call is automatically
PII-scanned, risk-classified, injection-checked, and written to a
tamper-evident HMAC-SHA256 audit trail.

Usage::

    from openai import OpenAI

    # Just change the base_url — everything else stays the same
    client = OpenAI(
        base_url="https://comply.crprotocol.io/v1",
        api_key="crc_...",           # CRP Comply API key
        default_headers={
            "X-Upstream-API-Key": "<YOUR_API_KEY>",  # Your real OpenAI key
        },
    )

    # Managed mode (server holds the upstream key):
    client = OpenAI(
        base_url="https://comply.crprotocol.io/v1",
        api_key="crc_...",
    )
"""

from .interceptor import ComplianceInterceptor
from .routes import init_proxy
from .routes import openai_router
from .routes import router

__all__ = ["ComplianceInterceptor", "init_proxy", "openai_router", "router"]
