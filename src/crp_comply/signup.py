# Copyright © 2025 Constantinos Vidiniotis. All rights reserved.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Anonymous scan + result-preserving signup (SPEC-048 Part C).

Anonymous scans are limited to public repos or uploaded SARIF.
Private-repo scanning requires authenticated GitHub App connection.
"""

from __future__ import annotations

import logging
import secrets
import time
from typing import Any

import requests

from crp_comply.billing.entitlements import _clerk_headers

logger = logging.getLogger(__name__)

# In-memory store — production should use Redis / DB with TTL
_anonymous_store: dict[str, dict[str, Any]] = {}
_DEFAULT_TTL_DAYS = 30


def store_anonymous_results(
    findings: list[dict[str, Any]], ttl_days: int = _DEFAULT_TTL_DAYS
) -> str:
    """Store scan findings against a random token for later claim.

    Returns the claim token.
    """
    token = secrets.token_urlsafe(32)
    _anonymous_store[token] = {
        "findings": findings,
        "created_at": time.time(),
        "ttl_seconds": ttl_days * 86400,
        "claimed": False,
        "claimed_by": None,
    }
    logger.info("Stored anonymous findings under token %s...", token[:8])
    return token


def claim_results(token: str, org_id: str) -> dict[str, Any]:
    """Migrate anonymous findings to a Clerk org.

    Idempotent — claiming twice for the same org returns success.
    Claiming for a different org returns error.
    """
    record = _anonymous_store.get(token)
    if record is None:
        return {"status": "not_found", "error": "Token not found or expired"}

    if record["claimed"]:
        if record["claimed_by"] == org_id:
            return {"status": "already_claimed", "findings": record["findings"]}
        return {"status": "error", "error": "Token already claimed by another org"}

    # Check TTL
    age = time.time() - record["created_at"]
    if age > record["ttl_seconds"]:
        del _anonymous_store[token]
        return {"status": "expired", "error": "Token expired"}

    # Write to Clerk org metadata (append to scanResults)
    try:
        org_url = f"https://api.clerk.com/v1/organizations/{org_id}"
        r = requests.get(org_url, headers=_clerk_headers(), timeout=5.0)
        r.raise_for_status()
        current_meta = r.json().get("public_metadata", {})
        existing = current_meta.get("scanResults", [])
        existing.extend(record["findings"])
        requests.patch(
            org_url,
            headers=_clerk_headers(),
            json={"public_metadata": {**current_meta, "scanResults": existing}},
            timeout=5.0,
        ).raise_for_status()
    except Exception as exc:
        logger.error("Failed to write claimed results to Clerk: %s", exc)
        return {"status": "error", "error": str(exc)}

    record["claimed"] = True
    record["claimed_by"] = org_id
    logger.info("Token %s claimed by org %s", token[:8], org_id)
    return {"status": "claimed", "findings_count": len(record["findings"])}


def is_public_repo(repo_url: str) -> bool:
    """Best-effort check whether a GitHub repo is public.

    Returns True if the repo is accessible without auth.
    """
    # Normalize URL to API endpoint
    clean = (
        repo_url.rstrip("/").replace("https://github.com/", "").replace("http://github.com/", "")
    )
    if "/" not in clean:
        return False
    api_url = f"https://api.github.com/repos/{clean}"
    try:
        resp = requests.get(api_url, timeout=5.0)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("private", True) is False
        return False
    except Exception:
        return False
