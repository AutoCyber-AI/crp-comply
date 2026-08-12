# Copyright © 2025 Constantinos Vidiniotis. All rights reserved.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Runtime entitlement gate — reads Clerk org plan/quota, enforces limits.

Integrated into the Gateway proxy so every governed call is gated
before reaching the Gateway (SPEC-047 §5.2).
"""

from __future__ import annotations

import logging
from typing import Any

from crp_comply.billing.metering import InMemoryUsageStore, period_key

logger = logging.getLogger(__name__)


def _read_gateway_entitlement(org_id: str) -> dict[str, Any]:
    """Read the Gateway product entitlement from Clerk org metadata.

    Uses ``gateway_plan`` / ``gateway_quota`` per-product keys with a
    fallback to the legacy single ``plan`` / ``quota`` keys.
    """
    import os

    import requests

    secret = os.environ.get("CLERK_SECRET_KEY", "")
    if not secret:
        raise RuntimeError("CLERK_SECRET_KEY not set")

    url = f"https://api.clerk.com/v1/organizations/{org_id}"
    try:
        r = requests.get(
            url,
            headers={"Authorization": f"Bearer {secret}"},
            timeout=5.0,
        )
        r.raise_for_status()
        meta = r.json().get("public_metadata", {})
    except Exception as exc:
        raise RuntimeError(f"Failed to read Clerk metadata: {exc}") from exc

    plan = meta.get("gateway_plan", meta.get("plan", "free"))
    quota = meta.get("gateway_quota", meta.get("quota", 100))
    credits = meta.get("creditBalanceCents", 0)
    return {"plan": plan, "quota": quota, "credits": credits}


class QuotaGate:
    """Enforce per-org Gateway call quotas and credit balances.

    This gate protects the CRP Gateway proxy in Comply, so it reads the
    **gateway** product entitlement (``gateway_plan`` / ``gateway_quota``).

    Usage::

        gate = QuotaGate()
        result = gate.check("org_xxx")
        if result["status"] == "quota_exceeded":
            return HTTP 429
    """

    def __init__(self, store: InMemoryUsageStore | None = None) -> None:
        self._store = store or InMemoryUsageStore()

    def check(self, org_id: str) -> dict[str, Any]:
        """Check whether *org_id* is within the Gateway quota.

        Returns a dict with ``status`` (ok | ok_credit | quota_exceeded),
        ``used``, ``quota``, and optional ``action``.
        """
        try:
            ent = _read_gateway_entitlement(org_id)
        except Exception as exc:
            logger.warning("Cannot read Gateway entitlement for %s: %s", org_id, exc)
            # Fail open — allow if we can't verify
            return {"status": "ok", "used": -1, "quota": -1, "note": "entitlement_unavailable"}

        quota = ent.get("quota", 100)
        used = self._store.get(org_id, period_key())

        if used < quota:
            return {"status": "ok", "used": used, "quota": quota}

        # Over quota — check prepaid credits
        credit_bal = ent.get("credits", 0)
        if credit_bal > 0:
            return {
                "status": "ok_credit",
                "used": used,
                "quota": quota,
                "credits_remaining_cents": credit_bal,
            }

        return {
            "status": "quota_exceeded",
            "used": used,
            "quota": quota,
            "action": "prompt_topup_or_upgrade",
        }

    def record_usage(self, org_id: str, quantity: int = 1) -> dict[str, Any]:
        """Atomically increment usage for *org_id* and return new state."""
        used = self._store.increment(org_id, period_key())
        return {"status": "recorded", "used": used}
