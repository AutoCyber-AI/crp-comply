# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""HMAC-signed state tokens for GitHub App OAuth flow.

Self-validating — no DB/Redis storage required. The signature proves authenticity
and the exp claim enforces TTL.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time

logger = logging.getLogger(__name__)

STATE_SECRET = os.environ.get("GITHUB_STATE_SECRET", "").encode() or secrets.token_bytes(32)


def _ensure_secret() -> bytes:
    if not STATE_SECRET:
        raise RuntimeError(
            "GITHUB_STATE_SECRET environment variable is not set. "
            "Generate one with: openssl rand -hex 32"
        )
    return STATE_SECRET


def sign_state(payload: dict) -> str:
    """Sign a payload into a state token.

    Returns: base64url(payload).hex_hmac_sha256
    """
    secret = _ensure_secret()
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
    sig = hmac.new(secret, raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"


def verify_state(state: str) -> dict:
    """Verify and decode a state token.

    Raises ValueError if signature is invalid or token is expired.
    """
    secret = _ensure_secret()
    try:
        raw, sig = state.rsplit(".", 1)
    except ValueError:
        raise ValueError("Malformed state token")

    expect = hmac.new(secret, raw.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expect, sig):
        raise ValueError("Invalid state signature")

    payload = json.loads(base64.urlsafe_b64decode(raw))

    exp = payload.get("exp", 0)
    if exp < time.time():
        raise ValueError("State token expired")

    return payload


def build_connect_state(clerk_user_id: str, clerk_org_id: str | None) -> str:
    """Build a state token for the GitHub App connect flow."""
    return sign_state(
        {
            "clerk_user_id": clerk_user_id,
            "clerk_org_id": clerk_org_id,
            "exp": time.time() + 600,  # 10 minutes
            "nonce": secrets.token_hex(8),
        }
    )
