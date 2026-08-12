# Copyright © 2025 Constantinos Vidiniotis. All rights reserved.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Stripe price IDs and entitlement maps for CRP Comply (SPEC-047 §1).

In production these values are loaded from environment variables so that no
real Stripe identifiers are committed to the public repository. Placeholders
below make it obvious where to inject your own price/product IDs.
"""

from __future__ import annotations

import os


# ---------------------------------------------------------------------------
# Price IDs — single source of truth
# ---------------------------------------------------------------------------

def _env_or(key: str, default: str) -> str:
    """Return the environment variable or a placeholder."""
    return os.environ.get(key, default)


# Map Stripe price IDs to CRP plan keys. Override via env vars; placeholders
# are used when no env var is set.
PRICE_TO_PLAN: dict[str, str] = {
    # CRP Comply
    _env_or("STRIPE_COMPLY_STARTER_MONTHLY_PRICE_ID", "price_<YOUR_COMPLY_STARTER_MONTHLY>"): "comply_starter",
    _env_or("STRIPE_COMPLY_STARTER_ANNUAL_PRICE_ID", "price_<YOUR_COMPLY_STARTER_ANNUAL>"): "comply_starter",
    _env_or("STRIPE_COMPLY_SCALE_MONTHLY_PRICE_ID", "price_<YOUR_COMPLY_SCALE_MONTHLY>"): "comply_scale",
    _env_or("STRIPE_COMPLY_SCALE_ANNUAL_PRICE_ID", "price_<YOUR_COMPLY_SCALE_ANNUAL>"): "comply_scale",
    _env_or("STRIPE_COMPLY_CREDITS_5_PRICE_ID", "price_<YOUR_COMPLY_CREDITS_5>"): "comply_credits",
    _env_or("STRIPE_COMPLY_CREDITS_20_PRICE_ID", "price_<YOUR_COMPLY_CREDITS_20>"): "comply_credits",
    _env_or("STRIPE_COMPLY_CREDITS_50_PRICE_ID", "price_<YOUR_COMPLY_CREDITS_50>"): "comply_credits",
    # CRP Scan
    _env_or("STRIPE_SCAN_PRO_PRICE_ID", "price_<YOUR_SCAN_PRO>"): "scan_pro",
    _env_or("STRIPE_SCAN_BUSINESS_PRICE_ID", "price_<YOUR_SCAN_BUSINESS>"): "scan_business",
    # CRP Gateway
    _env_or("STRIPE_GATEWAY_DEVELOPER_MONTHLY_PRICE_ID", "price_<YOUR_GATEWAY_DEVELOPER_MONTHLY>"): "gateway_developer",
    _env_or("STRIPE_GATEWAY_DEVELOPER_ANNUAL_PRICE_ID", "price_<YOUR_GATEWAY_DEVELOPER_ANNUAL>"): "gateway_developer",
    _env_or("STRIPE_GATEWAY_TEAM_MONTHLY_PRICE_ID", "price_<YOUR_GATEWAY_TEAM_MONTHLY>"): "gateway_team",
    _env_or("STRIPE_GATEWAY_TEAM_ANNUAL_PRICE_ID", "price_<YOUR_GATEWAY_TEAM_ANNUAL>"): "gateway_team",
}

# Stripe product IDs. Override via env vars; placeholders are used when no env
# var is set.
PRODUCTS: dict[str, str] = {
    "comply_starter": _env_or("STRIPE_COMPLY_STARTER_PRODUCT_ID", "prod_<YOUR_COMPLY_STARTER_PRODUCT>"),
    "comply_scale": _env_or("STRIPE_COMPLY_SCALE_PRODUCT_ID", "prod_<YOUR_COMPLY_SCALE_PRODUCT>"),
    "comply_credits": _env_or("STRIPE_COMPLY_CREDITS_PRODUCT_ID", "prod_<YOUR_COMPLY_CREDITS_PRODUCT>"),
    "scan_pro": _env_or("STRIPE_SCAN_PRO_PRODUCT_ID", "prod_<YOUR_SCAN_PRO_PRODUCT>"),
    "scan_business": _env_or("STRIPE_SCAN_BUSINESS_PRODUCT_ID", "prod_<YOUR_SCAN_BUSINESS_PRODUCT>"),
    "gateway_developer": _env_or("STRIPE_GATEWAY_DEVELOPER_PRODUCT_ID", "prod_<YOUR_GATEWAY_DEVELOPER_PRODUCT>"),
    "gateway_team": _env_or("STRIPE_GATEWAY_TEAM_PRODUCT_ID", "prod_<YOUR_GATEWAY_TEAM_PRODUCT>"),
}


# ---------------------------------------------------------------------------
# Quotas — audited calls per month
# ---------------------------------------------------------------------------

PLAN_QUOTAS: dict[str, int] = {
    "free": 100,
    "comply_starter": 5_000,
    "comply_scale": 50_000,
    "gateway_developer": 50_000,
    "gateway_team": 500_000,
    "scan_pro": 0,  # scan_pro is per-repo, not call-quota
    "scan_business": 0,  # scan_business is unlimited repos
}

# ---------------------------------------------------------------------------
# Features per plan
# ---------------------------------------------------------------------------

PLAN_FEATURES: dict[str, list[str]] = {
    "free": ["governance"],
    "comply_starter": [
        "governance",
        "checkpoint_inbox",
        "evidence_pack",
        "hosted_vault",
        "scan_remediations",
    ],
    "comply_scale": [
        "governance",
        "checkpoint_inbox",
        "evidence_pack",
        "hosted_vault",
        "scan_remediations",
        "sso",
        "data_residency",
        "custom_rules",
        "hosted_llm",
    ],
    "gateway_developer": [
        "governance",
        "context_suite",
        "console",
        "deploy_endpoint",
    ],
    "gateway_team": [
        "governance",
        "context_suite",
        "console",
        "deploy_endpoint",
        "shared_pipelines",
        "sso",
    ],
    "scan_pro": ["scan_remediation_pr"],
    "scan_business": [
        "scan_remediation_pr",
        "unlimited_repos",
        "campaigns",
    ],
}

# ---------------------------------------------------------------------------
# Credit top-ups — cents added per price ID
# ---------------------------------------------------------------------------

CREDIT_CENTS_FROM_PRICE: dict[str, int] = {
    _env_or("STRIPE_COMPLY_CREDITS_5_PRICE_ID", "price_<YOUR_COMPLY_CREDITS_5>"): 500,  # $5
    _env_or("STRIPE_COMPLY_CREDITS_20_PRICE_ID", "price_<YOUR_COMPLY_CREDITS_20>"): 2_000,  # $20
    _env_or("STRIPE_COMPLY_CREDITS_50_PRICE_ID", "price_<YOUR_COMPLY_CREDITS_50>"): 5_000,  # $50
}

# Metering event name for Stripe Meter Events API
METER_EVENT_NAME: str = "comply_proxy_requests"

# Credit cost per audited call (in cents) — drawn after quota exceeded
CREDIT_COST_PER_CALL_CENTS: int = 1  # 1 cent per 100 calls over quota
