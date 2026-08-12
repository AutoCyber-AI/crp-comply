# Copyright © 2025 Constantinos Vidiniotis. All rights reserved.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Stripe Checkout + Customer Portal creation (SPEC-047 §4.2, §4.6).

Requires ``STRIPE_SECRET_KEY`` env var.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests
import stripe

logger = logging.getLogger(__name__)

_stripe_initialized: bool = False


def _ensure_stripe() -> None:
    """Set Stripe API key and version once."""
    global _stripe_initialized  # noqa: PLW0603
    if _stripe_initialized:
        return
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key:
        raise RuntimeError("STRIPE_SECRET_KEY environment variable is not set")
    stripe.api_key = key
    stripe.api_version = "2025-12-15.clover"
    _stripe_initialized = True


def _clerk_secret() -> str:
    secret = os.environ.get("CLERK_SECRET_KEY", "")
    if not secret:
        raise RuntimeError("CLERK_SECRET_KEY environment variable is not set")
    return secret


def _clerk_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_clerk_secret()}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Customer lifecycle
# ---------------------------------------------------------------------------


def get_or_create_stripe_customer(org_id: str, org_name: str = "", email: str = "") -> str:
    """Return the Stripe customer ID for a Clerk org, creating if absent.

    Writes the customer ID back to Clerk org publicMetadata.
    """
    _ensure_stripe()

    # Check Clerk org metadata for existing customer ID
    org_url = f"https://api.clerk.com/v1/organizations/{org_id}"
    r = requests.get(org_url, headers=_clerk_headers(), timeout=5.0)
    r.raise_for_status()
    meta = r.json().get("public_metadata", {})
    customer_id = meta.get("stripeCustomerId")
    if customer_id:
        return customer_id  # type: ignore[no-any-return]

    # Create new Stripe customer linked to this Clerk org
    customer = stripe.Customer.create(
        name=org_name or org_id,
        email=email or None,
        metadata={"clerkOrgId": org_id},
    )
    customer_id = customer["id"]  # type: ignore[index]

    # Write back to Clerk
    requests.patch(
        org_url,
        headers=_clerk_headers(),
        json={"public_metadata": {**meta, "stripeCustomerId": customer_id}},
        timeout=5.0,
    ).raise_for_status()

    logger.info("Created Stripe customer %s for org %s", customer_id, org_id)
    return customer_id  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Checkout & Portal
# ---------------------------------------------------------------------------


def create_checkout_session(
    org_id: str,
    price_id: str,
    mode: str = "subscription",
    return_url: str = "",
    org_name: str = "",
    email: str = "",
) -> dict[str, Any]:
    """Create a Stripe Checkout Session for *org_id*.

    Args:
        org_id: Clerk organization ID.
        price_id: Stripe Price ID (from constants).
        mode: ``'subscription'`` for tiers, ``'payment'`` for credit top-ups.
        return_url: Where to redirect after checkout (cancel/success).
        org_name: Organization name (for customer creation).
        email: Admin email (for customer creation).

    Returns:
        Stripe Checkout Session object (dict with ``url``, ``id``, etc.).
    """
    _ensure_stripe()
    customer_id = get_or_create_stripe_customer(org_id, org_name, email)

    base_url = return_url or os.environ.get("APP_BASE_URL", "https://comply.crprotocol.io")
    success = f"{base_url}/dashboard/billing?upgraded=1&cs={{CHECKOUT_SESSION_ID}}"
    cancel = f"{base_url}/dashboard/billing?canceled=1"

    session = stripe.checkout.Session.create(
        customer=customer_id,
        mode=mode,
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success,
        cancel_url=cancel,
        client_reference_id=org_id,
        metadata={"clerkOrgId": org_id, "priceId": price_id},
        allow_promotion_codes=True,
        automatic_tax={"enabled": True},
    )
    logger.info("Created checkout session %s for org %s (mode=%s)", session["id"], org_id, mode)  # type: ignore[index]
    return dict(session)  # type: ignore[no-any-return]


def create_portal_session(org_id: str, return_url: str = "") -> dict[str, Any]:
    """Create a Stripe Customer Portal session for self-serve management.

    Returns:
        Dict with ``url`` key pointing to the portal.
    """
    _ensure_stripe()
    org_url = f"https://api.clerk.com/v1/organizations/{org_id}"
    r = requests.get(org_url, headers=_clerk_headers(), timeout=5.0)
    r.raise_for_status()
    meta = r.json().get("public_metadata", {})
    customer_id = meta.get("stripeCustomerId")
    if not customer_id:
        raise ValueError(f"Org {org_id} has no Stripe customer")

    base = return_url or os.environ.get("APP_BASE_URL", "https://comply.crprotocol.io")
    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=f"{base}/dashboard/billing",
    )
    logger.info("Created portal session for org %s", org_id)
    return {"url": session["url"]}  # type: ignore[no-any-return]
