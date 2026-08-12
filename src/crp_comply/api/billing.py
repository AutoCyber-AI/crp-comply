# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Stripe billing — checkout sessions, webhooks, tier management."""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from typing import Any

import httpx
import stripe
from fastapi import APIRouter, HTTPException, Header, Request, status
from pydantic import BaseModel

from .auth import AuthManager, Tier
from .deps import get_auth

logger = logging.getLogger("crp_comply.billing")

router = APIRouter(prefix="/billing", tags=["billing"])

# ── Idempotency store (PostgreSQL first, file-based fallback) ──
_EVENT_ID_FILE = os.environ.get(
    "CRP_COMPLY_WEBHOOK_EVENTS",
    os.path.join(tempfile.gettempdir(), "crp_webhook_events.json"),
)
_EVENT_TTL_SECONDS = 86_400  # 24 hours


async def _is_event_processed(event_id: str) -> bool:
    """Check if a Stripe event has already been processed (PostgreSQL first)."""
    try:
        from crp_shared.db import get_db

        async with get_db() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM webhook_events WHERE event_id = $1 AND source = 'stripe'",
                event_id,
            )
            if row:
                return True
    except Exception:
        pass
    # Fallback to file-based
    try:
        with open(_EVENT_ID_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return event_id in data and (time.time() - data[event_id]) < _EVENT_TTL_SECONDS
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return False


async def _save_processed_event(event_id: str, event_type: str = "") -> None:
    """Mark a Stripe event as processed (PostgreSQL first)."""
    try:
        from crp_shared.db import get_db

        async with get_db() as conn:
            await conn.execute(
                """
                INSERT INTO webhook_events (event_id, source, event_type, processed_at)
                VALUES ($1, 'stripe', $2, NOW())
                ON CONFLICT (event_id) DO NOTHING
                """,
                event_id,
                event_type or "unknown",
            )
            return
    except Exception:
        pass
    # Fallback to file-based
    try:
        data: dict[str, float] = {}
        if os.path.exists(_EVENT_ID_FILE):
            with open(_EVENT_ID_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                data = {}
            # TTL prune
            now = time.time()
            data = {k: v for k, v in data.items() if now - v < _EVENT_TTL_SECONDS}
        data[event_id] = time.time()
        with open(_EVENT_ID_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except OSError as exc:
        logger.warning("Cannot persist webhook event idempotency: %s", exc)


# ── Clerk metadata updater (NEW — replaces local JSON writes) ──


def _clerk_secret() -> str:
    return os.environ.get("CLERK_SECRET_KEY", "")


def _clerk_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_clerk_secret()}",
        "Content-Type": "application/json",
    }


async def _update_clerk_metadata(org_id: str, metadata: dict[str, Any]) -> None:
    """Patch Clerk org public metadata (async, non-blocking)."""
    url = f"https://api.clerk.com/v1/organizations/{org_id}"
    try:
        async with httpx.AsyncClient() as client:
            r = await client.patch(
                url, headers=_clerk_headers(), json={"public_metadata": metadata}, timeout=10.0
            )
            r.raise_for_status()
        logger.info("Updated Clerk org %s metadata: %s", org_id, list(metadata.keys()))
    except httpx.HTTPStatusError as exc:
        logger.warning("Failed to update Clerk org %s: %s", org_id, exc)
    except Exception:
        logger.exception("Clerk metadata update failed for %s", org_id)


def _price_to_product_plan(price_id: str) -> tuple[str, str] | None:
    """Map a Stripe price ID to (product, plan_slug).

    Products: comply, gateway, scan.
    """
    env_to_product_plan: list[tuple[str, str, str]] = [
        # Comply
        ("STRIPE_COMPLY_STARTER_PRICE_ID", "comply", "starter"),
        ("STRIPE_COMPLY_SCALE_PRICE_ID", "comply", "scale"),
        ("STRIPE_COMPLY_PROFESSIONAL_PRICE_ID", "comply", "pro"),
        ("STRIPE_COMPLY_PRO_PRICE_ID", "comply", "pro"),
        ("STRIPE_COMPLY_ENTERPRISE_PRICE_ID", "comply", "enterprise"),
        ("STRIPE_COMPLY_CLOUD_PRICE_ID", "comply", "cloud"),
        # Gateway
        ("STRIPE_GATEWAY_DEVELOPER_PRICE_ID", "gateway", "developer"),
        ("STRIPE_GATEWAY_TEAM_PRICE_ID", "gateway", "team"),
        # Scan
        ("STRIPE_SCAN_PRO_PRICE_ID", "scan", "pro"),
        ("STRIPE_SCAN_BUSINESS_PRICE_ID", "scan", "business"),
    ]
    for env_var, product, plan in env_to_product_plan:
        if os.environ.get(env_var) == price_id:
            return product, plan
    return None


# ── Config ─────────────────────────────────────────────────────
# Price ID → Tier mapping (set in Stripe Dashboard, store IDs in env)
PRICE_TO_TIER: dict[str, Tier] = {}
# Credit-pack price ID → USD value (one-time top-ups, not subscriptions)
CREDITS_PRICE_TO_USD: dict[str, int] = {}
# Conversion: USD → token grant. Uses a blended Groq cost of $0.50 per
# 1M billed tokens (input+output mix) so $5 ≈ 10M tokens. Conservative
# vs the published Groq matrix — leaves margin for headroom traffic.
USD_TO_TOKENS_RATE = 2_000_000  # 1 USD = 2,000,000 tokens of grant


def _ts_to_iso(ts: int | None) -> str | None:
    """Convert a Stripe Unix timestamp to an ISO 8601 UTC string."""
    if not ts:
        return None
    from datetime import datetime, timezone

    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except (ValueError, TypeError, OverflowError):
        return None


def _init_stripe() -> None:
    """Initialise Stripe API key and price→tier mapping."""
    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not stripe.api_key:
        logger.warning("STRIPE_SECRET_KEY not set — billing endpoints will fail")

    # Map Stripe price IDs to internal tiers.
    #
    # The Professional tier is read from the **canonical** spelling
    # ``STRIPE_COMPLY_PROFESSIONAL_PRICE_ID`` first, then falls back to
    # the legacy aliases ``STRIPE_COMPLY_PRO_PRICE_ID`` and
    # ``STRIPE_COMPLY_PROFESISIONAL_PRICE_ID`` (the latter being a typo
    # we tolerated in early production deployments). All three resolve
    # to ``Tier.PRO`` so an operator can rename the env var safely.
    price_map: list[tuple[str, Tier]] = [
        ("STRIPE_COMPLY_STARTER_PRICE_ID", Tier.STARTER),
        ("STRIPE_COMPLY_SCALE_PRICE_ID", Tier.SCALE),
        ("STRIPE_COMPLY_PROFESSIONAL_PRICE_ID", Tier.PRO),
        ("STRIPE_COMPLY_PRO_PRICE_ID", Tier.PRO),
        ("STRIPE_COMPLY_PROFESISIONAL_PRICE_ID", Tier.PRO),  # legacy typo
        ("STRIPE_COMPLY_ENTERPRISE_PRICE_ID", Tier.ENTERPRISE),
        ("STRIPE_COMPLY_CLOUD_PRICE_ID", Tier.CLOUD),
    ]
    for env_var, tier in price_map:
        price_id = os.environ.get(env_var)
        if price_id:
            PRICE_TO_TIER[price_id] = tier

    # Credit-pack one-time SKUs → token grant. The grant is "tokens
    # added to this user's overflow allowance for the current period".
    # Operator sets the price ID env vars in Stripe Dashboard. The
    # mapping below is in *USD*; we convert to tokens using the same
    # blended Groq price assumed in BUDGET_LLM_GUIDANCE §4.
    global CREDITS_PRICE_TO_USD
    CREDITS_PRICE_TO_USD = {}
    credit_map: list[tuple[str, int]] = [
        ("STRIPE_COMPLY_CREDITS_5_PRICE_ID", 5),
        ("STRIPE_COMPLY_CREDITS_20_PRICE_ID", 20),
        ("STRIPE_COMPLY_CREDITS_50_PRICE_ID", 50),
    ]
    for env_var, usd in credit_map:
        price_id = os.environ.get(env_var)
        if price_id:
            CREDITS_PRICE_TO_USD[price_id] = usd


# ── Request/Response Models ────────────────────────────────────
class CreateCheckoutRequest(BaseModel):
    price_id: str
    success_url: str = ""
    cancel_url: str = ""


class CheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str


class BillingPortalResponse(BaseModel):
    portal_url: str


class SubscriptionStatus(BaseModel):
    tier: str
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None
    subscription_status: str | None = None
    cancel_at_period_end: bool = False
    current_period_end: str | None = None
    renewal_date: str | None = None
    quota_used: int = 0
    quota_limit: int = 0
    remaining: int = 0
    pct_used: float = 0.0
    overage_calls: int = 0
    overage_allowed: bool = False
    credit_balance_usd: float = 0.0
    action_required: bool = False
    action_reason: str | None = None


# ── Routes ─────────────────────────────────────────────────────
@router.post("/create-checkout-session", response_model=CheckoutResponse)
async def create_checkout_session(
    req: CreateCheckoutRequest,
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None, alias="X-Api-Key"),
) -> CheckoutResponse:
    """Create a Stripe Checkout Session for subscription upgrade."""
    auth = get_auth()

    # Extract user from auth header
    user_id = "anonymous"
    email = None
    org_id = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]

        clerk_claims = auth.verify_clerk_token(token)
        if clerk_claims:
            user_id = f"clerk:{clerk_claims.get('sub', '')}"
            email = clerk_claims.get("email")
            # Extract org_id from Clerk claims
            org_id = clerk_claims.get("org_id") or clerk_claims.get("organization_id")
            if not org_id and isinstance(clerk_claims.get("o"), dict):
                org_id = clerk_claims["o"].get("id")
        else:
            uid = auth.verify_token(token)
            if uid:
                user_id = uid
                user = auth.get_user(uid)
                if user:
                    email = user.email

    # Fallback: authenticate via API key
    if user_id == "anonymous" and x_api_key:
        result = auth.verify_api_key(x_api_key)
        if result:
            user_id, _tier = result
            user = auth.get_user(user_id)
            if user:
                email = user.email

    if user_id == "anonymous":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required to create a checkout session",
        )

    # Resolve env var name to actual Stripe price ID
    actual_price_id = os.environ.get(req.price_id, req.price_id)

    # Validate resolved price ID looks like a Stripe price
    if not actual_price_id.startswith("price_"):
        logger.error(
            "Invalid Stripe price ID resolved from %s: %s",
            req.price_id,
            actual_price_id,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Stripe price not configured for this tier. "
            f"Set the {req.price_id} environment variable.",
        )

    base_url = os.environ.get("CRP_COMPLY_BASE_URL", "http://localhost:5173")

    if not stripe.api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing is not configured. Set the STRIPE_SECRET_KEY environment variable.",
        )

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": actual_price_id, "quantity": 1}],
            success_url=req.success_url
            or f"{base_url}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=req.cancel_url or f"{base_url}/billing/cancel",
            customer_email=email,
            metadata={
                "crp_user_id": user_id,
                "crp_org_id": org_id or "",
                "product": "crp-comply",
            },
        )
    except stripe.StripeError as e:
        logger.error("Stripe checkout creation failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to create checkout session",
        )

    return CheckoutResponse(
        checkout_url=session.url or "",
        session_id=session.id,
    )


@router.post("/create-portal-session", response_model=BillingPortalResponse)
async def create_portal_session(
    authorization: str | None = Header(None),
) -> BillingPortalResponse:
    """Create a Stripe Customer Portal session for self-service billing."""
    auth = get_auth()

    user_id = _get_user_id(auth, authorization)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    user = auth.get_user(user_id)
    if not user or not getattr(user, "stripe_customer_id", None):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No billing account found — subscribe first",
        )

    try:
        base_url = os.environ.get("CRP_COMPLY_BASE_URL", "http://localhost:5173")
        session = stripe.billing_portal.Session.create(
            customer=user.stripe_customer_id,
            return_url=f"{base_url}/settings",
        )
    except stripe.StripeError as e:
        logger.error("Stripe portal session failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to create portal session",
        )

    return BillingPortalResponse(portal_url=session.url)


@router.post("/webhook")
async def stripe_webhook(request: Request) -> dict[str, str]:
    """Handle Stripe webhook events.

    Returns HTTP 503 when Stripe is not configured. Events are only
    acknowledged with HTTP 200 after the handler succeeds; handler
    failures return HTTP 400 so Stripe retries. Signature timestamps
    are checked with a configurable tolerance and events are deduplicated
    by Stripe event ID.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

    if not webhook_secret:
        logger.error("STRIPE_WEBHOOK_SECRET not configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe webhook not configured",
        )

    tolerance_seconds = int(os.environ.get("STRIPE_WEBHOOK_TOLERANCE_SECONDS", "300"))
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret, tolerance=tolerance_seconds
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid payload",
        )
    except stripe.SignatureVerificationError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid signature",
        )

    event_id = getattr(event, "id", "")
    if not event_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing Stripe event id",
        )

    event_type = getattr(event, "type", "")
    if await _is_event_processed(event_id):
        logger.info("Stripe webhook: %s — already processed (idempotency)", event_type)
        return {"status": "ok"}

    auth = get_auth()
    data = event["data"]["object"]

    logger.info("Stripe webhook: %s", event_type)

    try:
        if event_type == "checkout.session.completed":
            await _handle_checkout_completed(auth, data)
        elif event_type == "customer.subscription.created":
            await _handle_subscription_created(auth, data)
        elif event_type == "customer.subscription.updated":
            await _handle_subscription_updated(auth, data)
        elif event_type == "customer.subscription.deleted":
            await _handle_subscription_deleted(auth, data)
        elif event_type == "invoice.paid":
            _handle_invoice_paid(auth, data)
        elif event_type == "invoice.payment_failed":
            _handle_payment_failed(auth, data)
        elif event_type == "invoice.payment_action_required":
            _handle_payment_action_required(auth, data)
        elif event_type == "payment_intent.succeeded":
            await _handle_payment_intent_succeeded(auth, data, event_id)
        else:
            logger.debug("Unhandled Stripe event: %s", event_type)
    except Exception as exc:
        logger.exception("Stripe webhook handler failed for %s: %s", event_type, exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Handler failed: {exc}",
        ) from exc

    # Only acknowledge after successful handler execution.
    await _save_processed_event(event_id, event_type)
    return {"status": "ok"}


# ── Webhook Handlers ───────────────────────────────────────────
async def _handle_checkout_completed(auth: AuthManager, data: dict[str, Any]) -> None:
    """Activate subscription after successful checkout — writes Clerk metadata."""
    metadata = data.get("metadata") or {}
    user_id = metadata.get("crp_user_id")
    org_id = metadata.get("crp_org_id")
    customer_id = data.get("customer")
    subscription_id = data.get("subscription")

    if not user_id:
        logger.warning("checkout.session.completed missing crp_user_id metadata")
        return

    # Determine product/plan from the subscription's price
    tier = Tier.FREE  # safest default — only upgrade when price is confirmed
    product_plan = None
    if subscription_id:
        try:
            sub = stripe.Subscription.retrieve(subscription_id)
            price_id = sub["items"]["data"][0]["price"]["id"]
            tier = PRICE_TO_TIER.get(price_id, Tier.PRO)
            product_plan = _price_to_product_plan(price_id)
        except stripe.StripeError:
            pass

    # NEW: Write to Clerk org metadata ONLY for subscription checkouts.
    # Credit packs (mode=payment, subscription_id=None) must NOT overwrite plan.
    target_org = org_id
    if not target_org and user_id.startswith("org_"):
        target_org = user_id
    if target_org and subscription_id and product_plan:
        product, plan = product_plan
        await _update_clerk_metadata(
            target_org, {f"{product}_plan": plan, "stripeCustomerId": customer_id}
        )
    elif target_org and subscription_id:
        # Fallback: write tier directly (backward compat for comply-specific tiers)
        await _update_clerk_metadata(
            target_org, {"comply_plan": tier.value, "stripeCustomerId": customer_id}
        )

    # LEGACY: Keep local JSON for backward compat during cutover
    auth.set_user_tier(user_id, tier)
    auth.set_user_subscription(
        user_id,
        stripe_customer_id=customer_id,
        stripe_subscription_id=subscription_id,
        subscription_status="active",
        cancel_at_period_end=False,
    )

    logger.info(
        "Checkout completed: user=%s org=%s tier=%s product_plan=%s",
        user_id,
        target_org,
        tier.value,
        product_plan,
    )


async def _handle_subscription_created(auth: AuthManager, data: dict[str, Any]) -> None:
    """Subscription created — activate tier immediately."""
    customer_id = data.get("customer")
    price_id = data.get("items", {}).get("data", [{}])[0].get("price", {}).get("id")
    subscription_id = data.get("id")
    sub_status = data.get("status", "active")
    cancel_at_period_end = bool(data.get("cancel_at_period_end", False))
    current_period_end_ts = data.get("current_period_end")

    if not price_id:
        return

    new_tier = PRICE_TO_TIER.get(price_id, Tier.FREE)
    product_plan = _price_to_product_plan(price_id)
    period_end = _ts_to_iso(current_period_end_ts)

    for uid, user_data in auth._users.items():
        if user_data.get("stripe_customer_id") == customer_id:
            # NEW: Write to Clerk metadata if org
            if uid.startswith("org_") and product_plan:
                product, plan = product_plan
                await _update_clerk_metadata(uid, {f"{product}_plan": plan})
            elif uid.startswith("org_"):
                await _update_clerk_metadata(uid, {"comply_plan": new_tier.value})

            # LEGACY: local JSON
            auth.set_user_tier(uid, new_tier)
            auth.set_user_subscription(
                uid,
                stripe_subscription_id=subscription_id,
                subscription_status=sub_status,
                cancel_at_period_end=cancel_at_period_end,
                current_period_end=period_end,
            )
            logger.info("User %s subscription created -> tier %s", uid, new_tier.value)
            break


def _handle_invoice_paid(auth: AuthManager, data: dict[str, Any]) -> None:
    """Confirm renewal — subscription stays active."""
    customer_id = data.get("customer")
    subscription_id = data.get("subscription")
    period_end_ts = data.get("period_end") or data.get("lines", {}).get("data", [{}])[0].get(
        "period", {}
    ).get("end")
    logger.info("Invoice paid for customer %s", customer_id)
    for uid, user_data in auth._users.items():
        if user_data.get("stripe_customer_id") == customer_id:
            auth.set_user_subscription(
                uid,
                stripe_subscription_id=subscription_id,
                subscription_status="active",
                cancel_at_period_end=False,
                current_period_end=_ts_to_iso(period_end_ts),
            )
            break


def _handle_payment_failed(auth: AuthManager, data: dict[str, Any]) -> None:
    """Payment failed — mark subscription past_due and notify the user."""
    customer_id = data.get("customer")
    subscription_id = data.get("subscription")
    invoice_url = data.get("hosted_invoice_url")
    logger.warning("Payment failed for customer %s — Stripe will retry", customer_id)
    for uid, user_data in auth._users.items():
        if user_data.get("stripe_customer_id") == customer_id:
            auth.set_user_subscription(
                uid,
                stripe_subscription_id=subscription_id,
                subscription_status="past_due",
            )
            try:
                from crp_comply.api.notifications import emit_notification

                emit_notification(
                    user_id=uid,
                    kind="billing_action_required",
                    payload={
                        "reason": "payment_failed",
                        "invoice_url": invoice_url,
                        "message": "Your latest invoice payment failed. Please update your payment method to keep your subscription active.",
                    },
                )
            except Exception:
                logger.exception("Failed to send billing notification")
            break


async def _handle_subscription_updated(auth: AuthManager, data: dict[str, Any]) -> None:
    """Handle plan changes (upgrade/downgrade) and cancellation flags."""
    customer_id = data.get("customer")
    subscription_id = data.get("id")
    price_id = data.get("items", {}).get("data", [{}])[0].get("price", {}).get("id")
    sub_status = data.get("status")
    cancel_at_period_end = data.get("cancel_at_period_end")
    current_period_end_ts = data.get("current_period_end")

    if not price_id:
        return

    new_tier = PRICE_TO_TIER.get(price_id, Tier.FREE)
    product_plan = _price_to_product_plan(price_id)
    period_end = _ts_to_iso(current_period_end_ts)

    # Find user by stripe customer ID
    for uid, user_data in auth._users.items():
        if user_data.get("stripe_customer_id") == customer_id:
            # NEW: Write to Clerk metadata if org
            if uid.startswith("org_") and product_plan:
                product, plan = product_plan
                await _update_clerk_metadata(uid, {f"{product}_plan": plan})
            elif uid.startswith("org_"):
                await _update_clerk_metadata(uid, {"comply_plan": new_tier.value})

            # LEGACY: local JSON
            auth.set_user_tier(uid, new_tier)
            auth.set_user_subscription(
                uid,
                stripe_subscription_id=subscription_id,
                subscription_status=sub_status,
                cancel_at_period_end=cancel_at_period_end,
                current_period_end=period_end,
            )
            logger.info(
                "User %s subscription updated -> tier=%s status=%s cancel_at_period_end=%s",
                uid,
                new_tier.value,
                sub_status,
                cancel_at_period_end,
            )
            break


async def _handle_subscription_deleted(auth: AuthManager, data: dict[str, Any]) -> None:
    """Subscription cancelled — downgrade to FREE."""
    customer_id = data.get("customer")

    for uid, user_data in auth._users.items():
        if user_data.get("stripe_customer_id") == customer_id:
            # NEW: Write to Clerk metadata if org — clear all product plans to free
            if uid.startswith("org_"):
                await _update_clerk_metadata(
                    uid,
                    {
                        "comply_plan": "free",
                        "gateway_plan": "free",
                        "scan_plan": "free",
                    },
                )

            # LEGACY: local JSON
            auth.set_user_tier(uid, Tier.FREE)
            auth.set_user_subscription(
                uid,
                stripe_subscription_id=None,
                subscription_status="canceled",
                cancel_at_period_end=False,
                current_period_end=None,
            )
            logger.info("User %s downgraded to FREE (subscription cancelled)", uid)
            break


def _handle_payment_action_required(auth: AuthManager, data: dict[str, Any]) -> None:
    """3D-Secure / SCA challenge — surface to the user via notification."""
    customer_id = data.get("customer")
    invoice_url = data.get("hosted_invoice_url")
    logger.warning(
        "Payment requires customer action: customer=%s invoice=%s",
        customer_id,
        invoice_url,
    )
    try:
        from crp_comply.api.notifications import emit_notification

        for uid, user_data in auth._users.items():
            if user_data.get("stripe_customer_id") == customer_id:
                emit_notification(
                    user_id=uid,
                    kind="billing_action_required",
                    payload={"invoice_url": invoice_url},
                )
                break
    except Exception:
        logger.exception("Failed to send billing notification")


async def _handle_payment_intent_succeeded(
    auth: AuthManager, data: dict[str, Any], event_id: str
) -> None:
    """Credit-pack one-time purchase succeeded → grant USD credits.

    Distinguishes credit packs from subscription invoicing by checking
    the price ID against ``CREDITS_PRICE_TO_USD`` populated at startup.
    A subscription's `payment_intent.succeeded` is ignored here because
    `checkout.session.completed` already activated the tier.
    """
    customer_id = data.get("customer")
    pi_id = data.get("id")
    metadata = data.get("metadata") or {}
    user_id = metadata.get("crp_user_id")
    price_id = metadata.get("crp_price_id")

    # Fall back to expanding the PaymentIntent if metadata is missing.
    if (not user_id or not price_id) and pi_id:
        try:
            pi = stripe.PaymentIntent.retrieve(pi_id, expand=["invoice.lines.data.price"])
            metadata = pi.get("metadata") or {}
            user_id = user_id or metadata.get("crp_user_id")
            price_id = price_id or metadata.get("crp_price_id")
        except stripe.StripeError:
            pass

    if not price_id or price_id not in CREDITS_PRICE_TO_USD:
        # Not a credit-pack purchase. Subscription PIs flow through
        # checkout.session.completed instead.
        logger.debug("payment_intent.succeeded ignored (not a credit pack): %s", pi_id)
        return

    if not user_id:
        # Try resolving by stripe_customer_id.
        for uid, user_data in auth._users.items():
            if user_data.get("stripe_customer_id") == customer_id:
                user_id = uid
                break
    if not user_id:
        logger.warning("payment_intent.succeeded without crp_user_id (pi=%s)", pi_id)
        return

    usd = CREDITS_PRICE_TO_USD[price_id]
    org_id = metadata.get("crp_org_id") or ""
    try:
        from .credits import get_credit_store

        balance = get_credit_store().grant_usd_idempotent(
            user_id=user_id,
            usd=float(usd),
            reason=f"stripe:{price_id}:{pi_id}",
            event_id=event_id,
        )
        logger.info(
            "Credit pack granted: user=%s usd=%s balance=%.2f",
            user_id,
            usd,
            balance["balance_usd"],
        )
        # Sync credit balance to Clerk metadata so quota_gate sees it
        if org_id and org_id.startswith("org_"):
            try:
                import httpx

                clerk_url = f"https://api.clerk.com/v1/organizations/{org_id}"
                async with httpx.AsyncClient() as client:
                    r = await client.get(clerk_url, headers=_clerk_headers(), timeout=5.0)
                    r.raise_for_status()
                    current_meta = r.json().get("public_metadata", {})
                    current_cents = current_meta.get("creditBalanceCents", 0)
                    add_cents = int(float(usd) * 100)
                    new_balance = current_cents + add_cents
                    await client.patch(
                        clerk_url,
                        headers=_clerk_headers(),
                        json={
                            "public_metadata": {**current_meta, "creditBalanceCents": new_balance}
                        },
                        timeout=10.0,
                    )
                    logger.info(
                        "Synced creditBalanceCents to Clerk org %s: %d → %d",
                        org_id,
                        current_cents,
                        new_balance,
                    )
            except Exception as clerk_exc:
                logger.warning(
                    "Failed to sync credit balance to Clerk org %s: %s", org_id, clerk_exc
                )
        try:
            from crp_comply.api.notifications import emit_notification

            emit_notification(
                user_id=user_id,
                kind="credits_granted",
                payload={"usd_added": usd, "balance_usd": balance["balance_usd"]},
            )
        except Exception:
            logger.exception("Failed to send billing notification")
    except Exception as exc:  # noqa: BLE001 — webhook must never raise
        logger.error("Failed to grant credits for pi=%s: %s", pi_id, exc)


# ── Credit-pack endpoints ─────────────────────────────────────


class CreditCheckoutRequest(BaseModel):
    """Pick a credit-pack SKU. ``price_id`` is either a literal Stripe
    price (``<YOUR_STRIPE_PRICE_ID>``) or one of the env-var names below, which we
    resolve to the actual ID server-side.

    Accepted env-var aliases:
      * ``STRIPE_COMPLY_CREDITS_5_PRICE_ID``
      * ``STRIPE_COMPLY_CREDITS_20_PRICE_ID``
      * ``STRIPE_COMPLY_CREDITS_50_PRICE_ID``
    """

    price_id: str
    success_url: str = ""
    cancel_url: str = ""


@router.post("/credits/checkout", response_model=CheckoutResponse)
async def create_credits_checkout(
    req: CreditCheckoutRequest,
    authorization: str | None = Header(None),
    x_api_key: str | None = Header(None, alias="X-Api-Key"),
) -> CheckoutResponse:
    """Create a one-time-payment Stripe Checkout session for a credit pack."""
    auth = get_auth()

    user_id = "anonymous"
    email = None
    org_id = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        clerk_claims = auth.verify_clerk_token(token)
        if clerk_claims:
            user_id = f"clerk:{clerk_claims.get('sub', '')}"
            email = clerk_claims.get("email")
            org_id = clerk_claims.get("org_id") or clerk_claims.get("organization_id")
            if not org_id and isinstance(clerk_claims.get("o"), dict):
                org_id = clerk_claims["o"].get("id")
        else:
            uid = auth.verify_token(token)
            if uid:
                user_id = uid
                user = auth.get_user(uid)
                if user:
                    email = user.email
    if user_id == "anonymous" and x_api_key:
        result = auth.verify_api_key(x_api_key)
        if result:
            user_id, _ = result
            user = auth.get_user(user_id)
            if user:
                email = user.email
    if user_id == "anonymous":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required to buy credits",
        )

    # Resolve env var alias if given, then validate it's a credit-pack SKU.
    actual_price_id = os.environ.get(req.price_id, req.price_id)
    if not actual_price_id.startswith("price_"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Credit pack not configured. Set {req.price_id} in the deployment.",
        )
    if actual_price_id not in CREDITS_PRICE_TO_USD:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unknown credit-pack price ID. Allowed: $5 / $20 / $50 packs only.",
        )
    if not stripe.api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing not configured (STRIPE_SECRET_KEY missing).",
        )

    base_url = os.environ.get("CRP_COMPLY_BASE_URL", "http://localhost:5173")
    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[{"price": actual_price_id, "quantity": 1}],
            success_url=req.success_url
            or f"{base_url}/app/settings?session_id={{CHECKOUT_SESSION_ID}}#credits",
            cancel_url=req.cancel_url or f"{base_url}/app/settings#credits",
            customer_email=email,
            metadata={
                "crp_user_id": user_id,
                "crp_org_id": org_id or "",
                "crp_price_id": actual_price_id,
                "product": "crp-comply-credits",
            },
            payment_intent_data={
                "metadata": {
                    "crp_user_id": user_id,
                    "crp_org_id": org_id or "",
                    "crp_price_id": actual_price_id,
                }
            },
        )
    except stripe.StripeError as exc:
        logger.error("Stripe credit-pack checkout failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to create credits checkout session",
        )

    return CheckoutResponse(checkout_url=session.url or "", session_id=session.id)


class CreditBalanceResponse(BaseModel):
    user_id: str
    balance_usd: float
    lifetime_usd: float


@router.get("/credits/balance", response_model=CreditBalanceResponse)
async def get_credits_balance(
    authorization: str | None = Header(None),
) -> CreditBalanceResponse:
    """Return current prepaid credit balance for the authenticated user."""
    auth = get_auth()
    user_id = _get_user_id(auth, authorization)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required"
        )
    from .credits import get_credit_store

    bal = get_credit_store().get_balance(user_id)
    return CreditBalanceResponse(**bal)


@router.get("/status", response_model=SubscriptionStatus)
async def billing_status(
    authorization: str | None = Header(None),
) -> SubscriptionStatus:
    """Return the authenticated user's current subscription state.

    Used by the frontend to render the current-plan badge, quota progress
    bar, renewal date, and any billing action-required banner.
    """
    from datetime import datetime, timezone

    auth = get_auth()
    user_id = _get_user_id(auth, authorization)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    user = auth.get_user(user_id)
    tier = user.tier if user and getattr(user, "tier", None) else Tier.FREE
    tier_str = tier.value
    customer_id = getattr(user, "stripe_customer_id", None) if user else None
    subscription_id = getattr(user, "stripe_subscription_id", None) if user else None
    subscription_status = getattr(user, "subscription_status", None) if user else None
    cancel_at_period_end = getattr(user, "cancel_at_period_end", False) if user else False
    period_end = getattr(user, "current_period_end", None) if user else None

    # Refresh from Stripe when we have a subscription on file.
    if subscription_id and stripe.api_key:
        try:
            sub = stripe.Subscription.retrieve(subscription_id)
            ts = sub.get("current_period_end")
            if ts:
                period_end = datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
            subscription_status = sub.get("status", subscription_status)
            cancel_at_period_end = bool(sub.get("cancel_at_period_end", cancel_at_period_end))
            auth.set_user_subscription(
                user_id,
                subscription_status=subscription_status,
                cancel_at_period_end=cancel_at_period_end,
                current_period_end=period_end,
            )
        except stripe.StripeError as e:  # pragma: no cover - network
            logger.debug("retrieving subscription failed: %s", e)

    # Quota status
    quota_status: dict[str, Any] = {
        "used": 0,
        "quota": 0,
        "remaining": 0,
        "pct_used": 0.0,
        "overage_calls": 0,
        "blocked": False,
        "policy": "HARD_BLOCK",
    }
    try:
        from .usage import get_usage_tracker

        quota_status = get_usage_tracker().check_quota(user_id, tier)
    except RuntimeError:
        pass

    # Credit balance
    credit_balance = 0.0
    try:
        from .credits import get_credit_store

        credit_balance = get_credit_store().get_balance(user_id)["balance_usd"]
    except Exception:
        pass

    action_required = False
    action_reason: str | None = None
    if subscription_status == "past_due":
        action_required = True
        action_reason = "payment_failed"
    elif cancel_at_period_end:
        action_required = True
        action_reason = "cancel_at_period_end"
    elif quota_status.get("blocked"):
        action_required = True
        action_reason = "quota_exceeded"

    return SubscriptionStatus(
        tier=tier_str,
        stripe_customer_id=customer_id,
        stripe_subscription_id=subscription_id,
        subscription_status=subscription_status,
        cancel_at_period_end=cancel_at_period_end,
        current_period_end=period_end,
        renewal_date=period_end,
        quota_used=int(quota_status.get("used", 0)),
        quota_limit=int(quota_status.get("quota", 0)),
        remaining=int(quota_status.get("remaining", 0)),
        pct_used=float(quota_status.get("pct_used", 0.0)),
        overage_calls=int(quota_status.get("overage_calls", 0)),
        overage_allowed=quota_status.get("policy") == "SOFT_ALLOW",
        credit_balance_usd=credit_balance,
        action_required=action_required,
        action_reason=action_reason,
    )


# ── Helpers ────────────────────────────────────────────────────
def _get_user_id(auth: AuthManager, authorization: str | None) -> str | None:
    """Extract authenticated user ID from auth header."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[7:]

    clerk_claims = auth.verify_clerk_token(token)
    if clerk_claims:
        return f"clerk:{clerk_claims.get('sub', '')}"
    uid = auth.verify_token(token)
    return uid
