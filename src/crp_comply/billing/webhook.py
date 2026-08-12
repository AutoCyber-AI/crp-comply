# Copyright © 2025 Constantinos Vidiniotis. All rights reserved.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Stripe webhook handler — verify signature, update Clerk entitlement (SPEC-047 §4.3).

Non-negotiable rules:
  1. Entitlement granted ONLY by verified webhook — never client-side.
  2. Verify every webhook signature with stripe.webhooks.constructEvent.
  3. Idempotent — dedupe on Stripe event ID.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests
import stripe

from crp_comply.billing.constants import (
    CREDIT_CENTS_FROM_PRICE,
    PLAN_FEATURES,
    PLAN_QUOTAS,
)
from crp_comply.billing.entitlements import plan_from_price_id

logger = logging.getLogger(__name__)


def _split_product_plan(plan: str) -> tuple[str, str]:
    """Split a canonical plan slug into (product, plan_name).

    Examples::

        >>> _split_product_plan("comply_starter")
        ("comply", "starter")
        >>> _split_product_plan("gateway_team")
        ("gateway", "team")
    """
    parts = plan.split("_", 1)
    if len(parts) == 2 and parts[0] in {"comply", "gateway", "scan"}:
        return parts[0], parts[1]
    return "comply", plan


def _plan_metadata(plan: str, sub: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build Clerk public_metadata updates for a per-product plan.

    Writes both the canonical per-product key (``comply_plan``,
    ``gateway_plan``, ``scan_plan``) and a backward-compatible
    ``plan`` key so existing readers keep working.
    """
    product, plan_name = _split_product_plan(plan)
    metadata: dict[str, Any] = {
        f"{product}_plan": plan_name,
        "plan": plan,  # backward compatibility
        f"{product}_quota": PLAN_QUOTAS.get(plan, 100),
        "quota": PLAN_QUOTAS.get(plan, 100),  # backward compatibility
        f"{product}_features": PLAN_FEATURES.get(plan, ["governance"]),
        "features": PLAN_FEATURES.get(plan, ["governance"]),  # backward compatibility
    }
    if sub is not None:
        metadata["stripeSubscriptionId"] = sub.get("id")
        metadata["currentPeriodEnd"] = sub.get("current_period_end")
    return metadata

# In-memory dedupe set — production should use Redis / DB
_processed_event_ids: set[str] = set()

_STRIPE_WEBHOOK_SECRET: str | None = None


def _webhook_secret() -> str:
    """Return Stripe webhook signing secret from env (cached)."""
    global _STRIPE_WEBHOOK_SECRET  # noqa: PLW0603
    if _STRIPE_WEBHOOK_SECRET is None:
        _STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    if not _STRIPE_WEBHOOK_SECRET:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET environment variable is not set")
    return _STRIPE_WEBHOOK_SECRET


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


def _update_clerk_org(org_id: str, metadata: dict[str, Any]) -> None:
    """Patch Clerk org public metadata."""
    url = f"https://api.clerk.com/v1/organizations/{org_id}"
    try:
        r = requests.patch(
            url,
            headers=_clerk_headers(),
            json={"public_metadata": metadata},
            timeout=10.0,
        )
        r.raise_for_status()
        logger.info("Updated Clerk org %s metadata: %s", org_id, list(metadata))
    except requests.HTTPError as exc:
        logger.error("Failed to update Clerk org %s: %s", org_id, exc)
        raise


def _org_id_from_customer(customer_id: str) -> str | None:
    """Resolve Clerk org ID from Stripe customer metadata."""
    try:
        customer = stripe.Customer.retrieve(customer_id)
        return customer.metadata.get("clerkOrgId") if customer.metadata else None  # type: ignore[union-attr]
    except Exception:
        logger.warning("Could not retrieve Stripe customer %s", customer_id)
        return None


class StripeWebhookHandler:
    """Process Stripe webhooks and sync entitlement to Clerk org metadata.

    Usage::

        handler = StripeWebhookHandler()
        result = handler.process(payload_bytes, signature_header)
    """

    def __init__(self, webhook_secret: str | None = None) -> None:
        self._secret = webhook_secret or _webhook_secret()
        self._stripe_api_key = os.environ.get("STRIPE_SECRET_KEY", "")
        if self._stripe_api_key:
            stripe.api_key = self._stripe_api_key
            stripe.api_version = "2025-12-15.clover"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process(self, payload: bytes, sig_header: str) -> dict[str, Any]:
        """Verify signature and dispatch to the correct handler.

        Returns ``{"received": True}`` on success or a dict with
        ``error`` and HTTP-style ``status`` on failure.
        """
        try:
            event = stripe.Webhook.construct_event(payload, sig_header, self._secret)
        except stripe.error.SignatureVerificationError as exc:
            logger.warning("Stripe signature verification failed: %s", exc)
            return {"error": "Invalid signature", "status": 400}
        except ValueError as exc:
            logger.warning("Invalid Stripe payload: %s", exc)
            return {"error": "Invalid payload", "status": 400}

        event_id: str = event.get("id", "")
        if event_id in _processed_event_ids:
            logger.info("Deduplicating Stripe event %s", event_id)
            return {"received": True, "deduplicated": True}
        _processed_event_ids.add(event_id)

        handler_name = f"_on_{event['type'].replace('.', '_')}"
        handler = getattr(self, handler_name, self._on_unknown)
        handler(event)
        return {"received": True}

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_checkout_session_completed(self, event: dict[str, Any]) -> None:
        session = event["data"]["object"]
        org_id = session.get("metadata", {}).get("clerkOrgId")
        if not org_id:
            logger.warning("checkout.session.completed missing clerkOrgId")
            return

        mode = session.get("mode", "subscription")
        if mode == "subscription":
            sub_id = session.get("subscription")
            if not sub_id:
                logger.warning("checkout.session.completed missing subscription id")
                return
            try:
                sub = stripe.Subscription.retrieve(sub_id)
                price_id = sub["items"]["data"][0]["price"]["id"]
                plan = plan_from_price_id(price_id)
                metadata = _plan_metadata(plan, sub)
                _update_clerk_org(org_id, metadata)
                logger.info(
                    "Granted %s to org %s via checkout (sub=%s)",
                    plan,
                    org_id,
                    sub_id,
                )
            except Exception:
                logger.exception("Failed to process subscription checkout for %s", org_id)
        elif mode == "payment":
            # Credit top-up — increment prepaid balance
            price_id = session.get("metadata", {}).get("priceId")
            add_cents = CREDIT_CENTS_FROM_PRICE.get(price_id, 0)
            if add_cents:
                try:
                    org_url = f"https://api.clerk.com/v1/organizations/{org_id}"
                    r = requests.get(org_url, headers=_clerk_headers(), timeout=5.0)
                    r.raise_for_status()
                    current = r.json().get("public_metadata", {})
                    balance = current.get("creditBalanceCents", 0) + add_cents
                    _update_clerk_org(
                        org_id,
                        {
                            **current,
                            "creditBalanceCents": balance,
                        },
                    )
                    logger.info(
                        "Added %d cents credit to org %s",
                        add_cents,
                        org_id,
                    )
                except Exception:
                    logger.exception("Failed to credit org %s", org_id)

    def _on_customer_subscription_updated(self, event: dict[str, Any]) -> None:
        sub = event["data"]["object"]
        org_id = _org_id_from_customer(sub.get("customer"))
        if not org_id:
            return
        try:
            price_id = sub["items"]["data"][0]["price"]["id"]
            plan = plan_from_price_id(price_id)
            metadata = _plan_metadata(plan, sub)
            _update_clerk_org(org_id, metadata)
            logger.info("Updated subscription for org %s → %s", org_id, plan)
        except Exception:
            logger.exception("Failed to process subscription update for %s", org_id)

    def _on_customer_subscription_deleted(self, event: dict[str, Any]) -> None:
        sub = event["data"]["object"]
        org_id = _org_id_from_customer(sub.get("customer"))
        if not org_id:
            return
        try:
            price_id = sub["items"]["data"][0]["price"]["id"]
            plan = plan_from_price_id(price_id)
            product, plan_name = _split_product_plan(plan)
        except Exception:
            # If we cannot determine the product, reset the whole org to free
            # as a safe fallback and preserve backward compatibility.
            product = "comply"
        metadata = {
            f"{product}_plan": "free",
            "plan": "free",  # backward compatibility
            "stripeSubscriptionId": None,
            f"{product}_quota": PLAN_QUOTAS["free"],
            "quota": PLAN_QUOTAS["free"],  # backward compatibility
            f"{product}_features": PLAN_FEATURES["free"],
            "features": PLAN_FEATURES["free"],  # backward compatibility
        }
        _update_clerk_org(org_id, metadata)
        logger.info("Downgraded org %s %s plan to free (subscription deleted)", org_id, product)

    def _on_invoice_payment_failed(self, event: dict[str, Any]) -> None:
        inv = event["data"]["object"]
        org_id = _org_id_from_customer(inv.get("customer"))
        if not org_id:
            return
        try:
            org_url = f"https://api.clerk.com/v1/organizations/{org_id}"
            r = requests.get(org_url, headers=_clerk_headers(), timeout=5.0)
            r.raise_for_status()
            current = r.json().get("public_metadata", {})
            _update_clerk_org(org_id, {**current, "paymentIssue": True})
            logger.info("Flagged payment issue for org %s", org_id)
        except Exception:
            logger.exception("Failed to flag payment issue for %s", org_id)

    def _on_invoice_paid(self, event: dict[str, Any]) -> None:
        """Clear payment_issue flag when an invoice is paid."""
        inv = event["data"]["object"]
        org_id = _org_id_from_customer(inv.get("customer"))
        if not org_id:
            return
        try:
            org_url = f"https://api.clerk.com/v1/organizations/{org_id}"
            r = requests.get(org_url, headers=_clerk_headers(), timeout=5.0)
            r.raise_for_status()
            current = r.json().get("public_metadata", {})
            if current.get("paymentIssue"):
                current.pop("paymentIssue", None)
                _update_clerk_org(org_id, current)
                logger.info("Cleared payment issue for org %s", org_id)
        except Exception:
            logger.exception("Failed to clear payment issue for %s", org_id)

    def _on_payment_intent_succeeded(self, event: dict[str, Any]) -> None:
        """Payment intent succeeded — credits already handled by checkout.session.completed."""
        logger.debug("payment_intent.succeeded — no-op (handled by checkout)")

    def _on_unknown(self, event: dict[str, Any]) -> None:
        logger.debug("Unhandled Stripe event type: %s", event.get("type"))
