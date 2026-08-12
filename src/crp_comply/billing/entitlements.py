# Copyright © 2025 Constantinos Vidiniotis. All rights reserved.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Entitlement read — Clerk org publicMetadata → plan/quota/features (SPEC-047 §5.1).

The Python runtime reads entitlement from Clerk org metadata to gate
usage.  Writes happen ONLY in the Stripe webhook handler (TypeScript
canonical, mirrored here for Python-layer runtime gating).
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

from crp_comply.billing.constants import PLAN_FEATURES, PLAN_QUOTAS, PRICE_TO_PLAN

logger = logging.getLogger(__name__)

_CLERK_SECRET: str | None = None
_CLERK_API_VERSION: str = "2025-11-10"


def _clerk_secret() -> str:
    """Return Clerk secret key from env (cached)."""
    global _CLERK_SECRET  # noqa: PLW0603
    if _CLERK_SECRET is None:
        _CLERK_SECRET = os.environ.get("CLERK_SECRET_KEY", "")
    if not _CLERK_SECRET:
        raise RuntimeError("CLERK_SECRET_KEY environment variable is not set")
    return _CLERK_SECRET


def _clerk_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_clerk_secret()}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Plan / entitlement mapping
# ---------------------------------------------------------------------------


def plan_from_price_id(price_id: str) -> str:
    """Map a Stripe Price ID to a plan slug.

    Unknown price IDs fall back to ``'free'``.
    """
    return PRICE_TO_PLAN.get(price_id, "free")


def quota_for(plan: str) -> int:
    """Return the monthly audited-call quota for *plan*."""
    return PLAN_QUOTAS.get(plan, 100)


def features_for(plan: str) -> list[str]:
    """Return the feature list for *plan*."""
    return list(PLAN_FEATURES.get(plan, ["governance"]))


# ---------------------------------------------------------------------------
# Clerk org metadata read
# ---------------------------------------------------------------------------


def get_org_entitlement(org_id: str, timeout: float = 5.0) -> dict[str, Any]:
    """Read entitlement from the Clerk org's public metadata.

    Returns a dict with keys: plan, quota, features, credit_balance_cents,
    stripe_customer_id, stripe_subscription_id, current_period_end.
    """
    url = f"https://api.clerk.com/v1/organizations/{org_id}"
    try:
        r = requests.get(
            url,
            headers=_clerk_headers(),
            timeout=timeout,
        )
        r.raise_for_status()
    except requests.HTTPError as exc:
        logger.warning("Clerk API error for org %s: %s", org_id, exc)
        raise

    data = r.json()
    meta = data.get("public_metadata", {})
    # Per-product entitlement keys are canonical (SPEC-047 §1).
    # Fall back to the legacy single "plan" key for backward compatibility.
    plan = meta.get("comply_plan", meta.get("plan", "free"))
    quota = meta.get("comply_quota", meta.get("quota", quota_for(plan)))
    features = meta.get("comply_features", meta.get("features", features_for(plan)))
    return {
        "plan": plan,
        "quota": quota,
        "features": features,
        "credit_balance_cents": meta.get("creditBalanceCents", 0),
        "stripe_customer_id": meta.get("stripeCustomerId"),
        "stripe_subscription_id": meta.get("stripeSubscriptionId"),
        "current_period_end": meta.get("currentPeriodEnd"),
    }


def require_feature(org_id: str, feature: str) -> dict[str, Any]:
    """Raise PermissionError if *feature* is not in the org's entitlement.

    Returns the full entitlement dict on success.
    """
    ent = get_org_entitlement(org_id)
    if feature not in ent["features"]:
        raise PermissionError(f"upgrade_required:{feature}")
    return ent
