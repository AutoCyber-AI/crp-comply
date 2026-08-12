# Copyright © 2025 Constantinos Vidiniotis. All rights reserved.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Metering — quota enforcement and Stripe Meter Events (SPEC-047 §5.2, §5.3).

The Python runtime reads entitlement from Clerk org metadata and enforces
quotas.  Usage data belongs in CRP's own store, not Clerk metadata.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import stripe

from crp_comply.billing.constants import CREDIT_COST_PER_CALL_CENTS
from crp_comply.billing.entitlements import get_org_entitlement

logger = logging.getLogger(__name__)


class InMemoryUsageStore:
    """Simple in-memory usage counter for quota tracking.

    Production should swap this for Redis / DynamoDB / SQL.
    """

    def __init__(self) -> None:
        self._counts: dict[str, dict[str, int]] = {}
        self._credits: dict[str, int] = {}

    def increment(self, org_id: str, period_key: str) -> int:
        """Atomically increment usage for *org_id* in *period_key*."""
        if org_id not in self._counts:
            self._counts[org_id] = {}
        self._counts[org_id][period_key] = self._counts[org_id].get(period_key, 0) + 1
        return self._counts[org_id][period_key]

    def get(self, org_id: str, period_key: str) -> int:
        return self._counts.get(org_id, {}).get(period_key, 0)

    def draw_credit(self, org_id: str, cents: int) -> bool:
        """Draw *cents* from the org's prepaid credit balance."""
        bal = self._credits.get(org_id, 0)
        if bal < cents:
            return False
        self._credits[org_id] = bal - cents
        return True

    def add_credit(self, org_id: str, cents: int) -> None:
        self._credits[org_id] = self._credits.get(org_id, 0) + cents


def period_key() -> str:
    """Return the current billing period key (YYYY-MM)."""
    return time.strftime("%Y-%m")


class Metering:
    """Quota enforcement + Stripe Meter Events reporter."""

    def __init__(self, usage_store: InMemoryUsageStore | None = None) -> None:
        self._store = usage_store or InMemoryUsageStore()

    def record_call(self, org_id: str) -> dict[str, Any]:
        """Record one audited call and enforce quota.

        Returns a dict with ``status`` (ok | ok_credit | quota_exceeded),
        ``used``, ``quota``, and optionally ``action``.
        """
        try:
            ent = get_org_entitlement(org_id)
        except Exception as exc:
            logger.warning("Cannot read entitlement for %s: %s", org_id, exc)
            # Fail open — allow the call if we can't verify entitlement
            return {"status": "ok", "used": -1, "quota": -1, "note": "entitlement_unavailable"}

        quota = ent.get("quota", 100)
        used = self._store.increment(org_id, period_key())

        if used <= quota:
            return {"status": "ok", "used": used, "quota": quota}

        # Over quota — try prepaid credits
        credit_bal = ent.get("credit_balance_cents", 0)
        if credit_bal >= CREDIT_COST_PER_CALL_CENTS:
            # In a real system we'd decrement Clerk metadata atomically.
            # Here we just report that credits would cover it.
            return {
                "status": "ok_credit",
                "used": used,
                "quota": quota,
                "credits_used": CREDIT_COST_PER_CALL_CENTS,
            }

        return {
            "status": "quota_exceeded",
            "used": used,
            "quota": quota,
            "action": "prompt_topup_or_upgrade",
        }

    @staticmethod
    def report_metered_usage(subscription_item_id: str, quantity: int = 1) -> None:
        """Report usage to Stripe for metered billing (optional)."""
        try:
            stripe.SubscriptionItem.create_usage_record(
                subscription_item_id,
                quantity=quantity,
                timestamp=int(time.time()),
                action="increment",
            )
            logger.info("Reported %d units to Stripe meter %s", quantity, subscription_item_id)
        except Exception:
            logger.exception("Failed to report metered usage")
