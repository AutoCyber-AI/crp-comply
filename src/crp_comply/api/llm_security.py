# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Secure local-LLM URL validation — prevents SSRF to internal cloud networks."""

from __future__ import annotations

import ipaddress
import logging
import os
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

LOCAL_LLM_HOSTS = {"localhost", "127.0.0.1", "::1"}


def is_self_hosted_deployment() -> bool:
    """Return True if this deployment is running on the user's own infrastructure."""
    cloud_markers = (
        "RAILWAY_PROJECT_ID",
        "RAILWAY_ENVIRONMENT",
        "FLY_APP_NAME",
        "RENDER",
        "VERCEL",
        "AWS_EXECUTION_ENV",
        "GOOGLE_CLOUD_PROJECT",
        "HEROKU",
        "DYNO",
    )
    for marker in cloud_markers:
        if os.environ.get(marker):
            return False
    return os.environ.get("CRP_COMPLY_SELF_HOSTED", "").lower() in ("1", "true", "yes")


def validate_local_llm_url(base_url: str, *, provider: str = "custom") -> None:
    """Ensure a local-LLM URL can only point to loopback in hosted deployments.

    In hosted (Railway / Fly / cloud) deployments the API server must never
    be able to reach a user's private LAN. This function blocks any base URL
    that is not localhost / 127.0.0.1 / ::1 for local providers (lmstudio,
    ollama, custom OpenAI-compatible). It is a no-op for self-hosted installs.

    Raises:
        ValueError: if the URL is not a permitted local-LLM target.
    """
    if is_self_hosted_deployment():
        return

    parsed = urlparse(base_url)
    host = (parsed.hostname or "").strip().lower()

    if not host:
        raise ValueError(f"{provider} base URL has no host: {base_url}")

    if host in LOCAL_LLM_HOSTS:
        return

    # Reject any private/LAN/Multicast/reserved address.
    try:
        addr = ipaddress.ip_address(host)
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            raise ValueError(
                f"Hosted CRP Comply cannot reach private-network LLM address {host!r}. "
                f"Use the SDK worker relay or a publicly-routable endpoint."
            )
    except ValueError as exc:
        if "Hosted CRP Comply" in str(exc):
            raise
        # Not an IP; hostname like 'lmstudio.local' is still private.
        if host.endswith(".local") or ".internal" in host:
            raise ValueError(
                f"Hosted CRP Comply cannot reach private-network LLM host {host!r}. "
                f"Use the SDK worker relay or a publicly-routable endpoint."
            ) from exc
        # Public DNS hostname — allowed.
        return


__all__ = ["is_self_hosted_deployment", "validate_local_llm_url"]
