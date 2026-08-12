# Copyright © 2025 Constantinos Vidiniotis. All rights reserved.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""CRP Comply billing module — Stripe + Clerk integration (SPEC-047).

Exports:
  - price_to_plan, plan_to_quota, plan_to_features
  - get_org_entitlement, require_feature
  - StripeWebhookHandler
  - create_checkout_session, create_portal_session
  - Metering
"""

from __future__ import annotations

from crp_comply.billing.constants import (
    CREDIT_CENTS_FROM_PRICE,
    PLAN_FEATURES,
    PLAN_QUOTAS,
    PRICE_TO_PLAN,
    PRODUCTS,
)
from crp_comply.billing.entitlements import (
    get_org_entitlement,
    plan_from_price_id,
    quota_for,
    require_feature,
)
from crp_comply.billing.webhook import StripeWebhookHandler

__all__ = [
    "CREDIT_CENTS_FROM_PRICE",
    "PLAN_FEATURES",
    "PLAN_QUOTAS",
    "PRICE_TO_PLAN",
    "PRODUCTS",
    "StripeWebhookHandler",
    "get_org_entitlement",
    "plan_from_price_id",
    "quota_for",
    "require_feature",
]
