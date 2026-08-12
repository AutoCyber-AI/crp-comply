# Copyright © 2025 Constantinos Vidiniotis. All rights reserved.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Nightly reconciliation — compare Stripe subscriptions to local entitlement.

Repairs drift from missed webhooks (SPEC-047 §3.2) and records every run in
a durable audit table so billing changes are traceable.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from typing import TYPE_CHECKING, Any

import requests
import stripe

from crp_comply.billing.constants import PLAN_FEATURES, PLAN_QUOTAS
from crp_comply.billing.entitlements import plan_from_price_id
from crp_comply.billing.webhook import _clerk_headers, _update_clerk_org

if TYPE_CHECKING:
    from crp_comply.api.auth import AuthManager

logger = logging.getLogger(__name__)

_RECONCILE_AUDIT_FILE = os.environ.get(
    "CRP_COMPLY_RECONCILE_AUDIT",
    os.path.join(tempfile.gettempdir(), "crp_billing_reconciliation.json"),
)


def reconcile_subscriptions(
    dry_run: bool = False,
    limit: int = 100,
) -> dict[str, Any]:
    """Walk active Stripe subscriptions and ensure Clerk org metadata matches.

    Args:
        dry_run: If True, log differences but do not write to Clerk.
        limit: Max subscriptions to check.

    Returns:
        Dict with ``checked``, ``repaired``, ``errors`` counts.
    """
    result = {"checked": 0, "repaired": 0, "errors": 0, "details": []}

    try:
        subs = stripe.Subscription.list(
            status="active",
            limit=limit,
            expand=["data.customer"],
        )
    except Exception as exc:
        logger.error("Failed to list Stripe subscriptions: %s", exc)
        result["errors"] += 1
        return result

    for sub in subs.auto_paging_iter():
        if result["checked"] >= limit:
            break
        result["checked"] += 1

        customer = sub.get("customer")
        if not customer:
            continue

        org_id = None
        if isinstance(customer, dict) and customer.get("metadata"):
            org_id = customer["metadata"].get("clerkOrgId")

        if not org_id:
            logger.debug("Skipping sub %s — no clerkOrgId linkage", sub["id"])
            continue

        # Determine expected plan from subscription
        try:
            price_id = sub["items"]["data"][0]["price"]["id"]
            expected_plan = plan_from_price_id(price_id)
        except (IndexError, KeyError):
            logger.warning("Sub %s has no price item", sub["id"])
            continue

        # Read current Clerk entitlement
        try:
            org_url = f"https://api.clerk.com/v1/organizations/{org_id}"
            r = requests.get(org_url, headers=_clerk_headers(), timeout=5.0)
            r.raise_for_status()
            current_meta = r.json().get("public_metadata", {})
            current_plan = current_meta.get("plan", "free")
        except Exception as exc:
            logger.warning("Cannot read Clerk org %s: %s", org_id, exc)
            result["errors"] += 1
            continue

        if current_plan != expected_plan:
            detail = {
                "org_id": org_id,
                "sub_id": sub["id"],
                "current_plan": current_plan,
                "expected_plan": expected_plan,
            }
            result["details"].append(detail)
            logger.info("Drift detected: %s", detail)

            if not dry_run:
                try:
                    _update_clerk_org(
                        org_id,
                        {
                            "plan": expected_plan,
                            "stripeSubscriptionId": sub["id"],
                            "quota": PLAN_QUOTAS.get(expected_plan, 100),
                            "features": PLAN_FEATURES.get(expected_plan, ["governance"]),
                            "currentPeriodEnd": sub.get("current_period_end"),
                        },
                    )
                    result["repaired"] += 1
                except Exception as exc:
                    logger.error("Failed to repair org %s: %s", org_id, exc)
                    result["errors"] += 1

    logger.info(
        "Reconciliation complete: checked=%d repaired=%d errors=%d",
        result["checked"],
        result["repaired"],
        result["errors"],
    )
    return result


def _record_reconciliation_run_local(run: dict[str, Any]) -> None:
    """Persist reconciliation run to a local JSON audit log (DB fallback)."""
    try:
        entries: list[dict[str, Any]] = []
        if os.path.exists(_RECONCILE_AUDIT_FILE):
            with open(_RECONCILE_AUDIT_FILE, "r", encoding="utf-8") as f:
                entries = json.load(f)
            if not isinstance(entries, list):
                entries = []
        run["recorded_at"] = time.time()
        entries.append(run)
        # Keep last 100 entries
        entries = entries[-100:]
        with open(_RECONCILE_AUDIT_FILE, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, default=str)
    except OSError as exc:
        logger.warning("Cannot persist reconciliation audit log: %s", exc)


async def _record_reconciliation_run(run: dict[str, Any]) -> None:
    """Persist reconciliation run to PostgreSQL (or local JSON fallback)."""
    try:
        from crp_shared.db import get_db

        async with get_db() as conn:
            await conn.execute(
                """
                INSERT INTO billing_reconciliation_runs
                    (dry_run, checked, repaired, errors, details)
                VALUES ($1, $2, $3, $4, $5)
                """,
                run.get("dry_run", False),
                run.get("checked", 0),
                run.get("repaired", 0),
                run.get("errors", 0),
                json.dumps(run.get("details", [])),
            )
            return
    except Exception:
        logger.debug("DB reconciliation audit unavailable; using local fallback")
    _record_reconciliation_run_local(run)


async def reconcile_billing(
    auth: AuthManager,
    *,
    dry_run: bool = False,
    limit: int = 100,
) -> dict[str, Any]:
    """Reconcile local user records against Stripe subscriptions.

    For every user with a ``stripe_customer_id`` we fetch the customer's
    subscriptions from Stripe, compare the expected tier/status/period-end,
    and repair drift in the local JSON + DB user record. A record of the run
    is written to ``billing_reconciliation_runs`` (PostgreSQL) or a local JSON
    fallback so billing changes remain auditable.
    """
    from crp_comply.api.billing import PRICE_TO_TIER, _init_stripe
    from crp_comply.api.models import Tier

    _init_stripe()

    result: dict[str, Any] = {
        "checked": 0,
        "repaired": 0,
        "errors": 0,
        "dry_run": dry_run,
        "details": [],
    }

    users = [(uid, data) for uid, data in auth._users.items() if data.get("stripe_customer_id")][
        :limit
    ]

    for uid, user_data in users:
        result["checked"] += 1
        customer_id = user_data.get("stripe_customer_id")
        local_tier = Tier(user_data.get("tier", "free"))
        local_status = user_data.get("subscription_status")
        local_cancel = bool(user_data.get("cancel_at_period_end", False))
        local_period_end = user_data.get("current_period_end")

        try:
            subs = stripe.Subscription.list(
                customer=customer_id,
                status="all",
                limit=1,
                expand=["data.items.data.price"],
            )
        except Exception as exc:
            logger.warning("Stripe list failed for customer %s: %s", customer_id, exc)
            result["errors"] += 1
            continue

        expected_tier = Tier.FREE
        expected_status = "canceled"
        expected_cancel = False
        expected_period_end: str | None = None

        if subs and subs.get("data"):
            sub = subs["data"][0]
            expected_status = sub.get("status", "active")
            expected_cancel = bool(sub.get("cancel_at_period_end", False))
            ts = sub.get("current_period_end")
            if ts:
                from datetime import datetime, timezone

                expected_period_end = datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
            items = sub.get("items", {}).get("data", [])
            if items:
                price_id = items[0].get("price", {}).get("id")
                expected_tier = PRICE_TO_TIER.get(price_id, Tier.FREE)

        drift = (
            local_tier != expected_tier
            or local_status != expected_status
            or local_cancel != expected_cancel
            or local_period_end != expected_period_end
        )

        if drift:
            detail = {
                "user_id": uid,
                "customer_id": customer_id,
                "tier": {"local": local_tier.value, "stripe": expected_tier.value},
                "status": {"local": local_status, "stripe": expected_status},
                "cancel_at_period_end": {"local": local_cancel, "stripe": expected_cancel},
                "current_period_end": {"local": local_period_end, "stripe": expected_period_end},
            }
            result["details"].append(detail)
            logger.info("Billing drift detected for %s: %s", uid, detail)

            if not dry_run:
                try:
                    auth.set_user_tier(uid, expected_tier)
                    auth.set_user_subscription(
                        uid,
                        stripe_subscription_id=sub["id"] if subs.get("data") else None,
                        subscription_status=expected_status,
                        cancel_at_period_end=expected_cancel,
                        current_period_end=expected_period_end,
                    )
                    result["repaired"] += 1
                except Exception as exc:
                    logger.error("Failed to repair user %s: %s", uid, exc)
                    result["errors"] += 1

    logger.info(
        "Billing reconciliation complete: checked=%d repaired=%d errors=%d",
        result["checked"],
        result["repaired"],
        result["errors"],
    )
    await _record_reconciliation_run(result)
    return result
