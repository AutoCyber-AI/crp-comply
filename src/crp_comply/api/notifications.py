# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Notifications API — test and inspect the multi-channel dispatcher."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..notifications import (
    EmailChannel,
    InAppChatChannel,
    Notification,
    NotificationDispatcher,
    NotificationPriority,
    SmsChannel,
    UserContactProfile,
    WebhookChannel,
    verify_token,
)
from ..contacts import get_contact_store
from .deps import get_current_tenant

logger = logging.getLogger("crp_comply.api.notifications")

router = APIRouter(prefix="/notifications", tags=["notifications"])


# ── Dispatcher singleton ────────────────────────────────────


_dispatcher: NotificationDispatcher | None = None
_inbox: InAppChatChannel | None = None


def _make_email_sender():
    """Build an email sender callable compatible with :class:`EmailChannel`."""
    try:
        from crp_comply.api.public import send_email
    except Exception as exc:  # pragma: no cover
        logger.warning("send_email not available: %s", exc)
        return None

    def _sender(to: str, subject: str, body: str, headers: dict[str, str]) -> bool:
        # headers are ignored for now — EmailChannel passes them but
        # send_email doesn't accept them. In future we can thread
        # X-CRP-Verify etc through a custom MIME structure.
        return send_email(to=to, subject=subject, body=body, html=None)

    return _sender


def get_dispatcher() -> NotificationDispatcher:
    global _dispatcher, _inbox
    if _dispatcher is None:
        _inbox = InAppChatChannel()
        email_sender = _make_email_sender()
        _dispatcher = NotificationDispatcher(
            [_inbox, EmailChannel(sender=email_sender), SmsChannel(), WebhookChannel()]
        )
    return _dispatcher


def get_inbox() -> InAppChatChannel:
    get_dispatcher()
    if not (_inbox is not None):
        raise RuntimeError("inbox dispatcher not initialised")
    return _inbox


def override_dispatcher(dispatcher: NotificationDispatcher, inbox: InAppChatChannel) -> None:
    """Test hook — inject a dispatcher + inbox."""
    global _dispatcher, _inbox
    _dispatcher = dispatcher
    _inbox = inbox


# ── Request / response models ───────────────────────────────


class TestNotificationRequest(BaseModel):
    email: str
    full_name: str = ""
    phone_e164: str = ""
    preferred_channel: str = "in_app"
    timezone: str = "UTC"
    language: str = "en-GB"
    webhook_url: str = ""
    subject: str = "CRP test notification"
    body: str = (
        "This is a test notification from CRP-Comply. "
        "If you received this, your notification channel is working."
    )
    priority: str = "medium"
    ring: bool = False


class DeliveryReceiptDTO(BaseModel):
    channel: str
    ok: bool
    delivered_to: str = ""
    verification_token: str = ""
    error: str = ""


class TestNotificationResponse(BaseModel):
    notification_id: str
    receipts: list[DeliveryReceiptDTO] = Field(default_factory=list)


class InboxEntryDTO(BaseModel):
    notification_id: str
    subject: str
    body: str
    priority: str
    ring: bool
    sound: str = ""
    kind: str = ""
    verification_token: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    received_at: str = ""
    cta_label: str = ""
    cta_url: str = ""


class VerifyTokenRequest(BaseModel):
    user_id: str
    email: str
    notification_id: str
    token: str


class VerifyTokenResponse(BaseModel):
    ok: bool


# ── Endpoints ───────────────────────────────────────────────


@router.post(
    "/test",
    response_model=TestNotificationResponse,
    summary="Send a test notification through the user's preferred channel",
)
async def test_notification(
    req: TestNotificationRequest,
    tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> TestNotificationResponse:
    try:
        priority = NotificationPriority(req.priority.lower())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid priority: {req.priority}") from exc

    # Route to the caller's tenant — never a user-supplied id. The
    # request body still carries ``email`` / ``phone`` for the actual
    # delivery channels, but the inbox key is pinned to the tenant.
    profile = UserContactProfile(
        user_id=tenant_id,
        email=req.email,
        full_name=req.full_name,
        phone_e164=req.phone_e164,
        preferred_channel=req.preferred_channel,
        timezone=req.timezone,
        language=req.language,
        webhook_url=req.webhook_url,
    )
    notification = Notification(
        kind="test",
        subject=req.subject,
        body=req.body,
        priority=priority,
        ring=req.ring,
    )
    dispatcher = get_dispatcher()
    receipts = dispatcher.dispatch(user=profile, notification=notification)
    return TestNotificationResponse(
        notification_id=notification.notification_id,
        receipts=[
            DeliveryReceiptDTO(
                channel=r.channel,
                ok=r.ok,
                delivered_to=r.delivered_to,
                verification_token=r.verification_token,
                error=r.error,
            )
            for r in receipts
        ],
    )


def _entry_to_dto(e: dict[str, Any]) -> InboxEntryDTO:
    n = e.get("notification", {}) or {}
    received_at_raw = e.get("received_at")
    received_at = ""
    if isinstance(received_at_raw, (int, float)):
        try:
            from datetime import datetime as _dt, timezone as _tz

            received_at = _dt.fromtimestamp(float(received_at_raw), tz=_tz.utc).isoformat()
        except (OSError, ValueError, OverflowError):
            received_at = ""
    elif isinstance(received_at_raw, str):
        received_at = received_at_raw
    return InboxEntryDTO(
        notification_id=n.get("notification_id", ""),
        subject=n.get("subject", ""),
        body=n.get("body", ""),
        priority=n.get("priority", "medium"),
        ring=bool(e.get("ring", n.get("ring", False))),
        sound=e.get("sound", n.get("sound", "")),
        kind=n.get("kind", ""),
        verification_token=e.get("verification_token", ""),
        metadata=n.get("metadata", {}) or {},
        received_at=received_at,
        cta_label=n.get("cta_label", ""),
        cta_url=n.get("cta_url", ""),
    )


@router.get(
    "/inbox",
    response_model=list[InboxEntryDTO],
    summary="Read pending in-app notifications for the caller (drains by default)",
)
async def drain_inbox(
    tenant_id: Annotated[str, Depends(get_current_tenant)],
    peek: bool = False,
) -> list[InboxEntryDTO]:
    # Inbox is tenant-scoped, not user-scoped: every seat of a Clerk
    # org reads the same queue. This is deliberate — a DPO and an
    # AI-officer on the same tenant see the same "action required"
    # messages so neither misses a high-priority item. Cross-tenant
    # leaks are prevented upstream by ``get_current_tenant`` resolving
    # against the caller's Clerk org claim.
    #
    # ``peek=true`` returns the queue without consuming it — used by
    # the dashboard / sidebar badge poll so periodic UI refreshes
    # don't silently drop messages before the user has a chance to
    # see them. Default behaviour stays drain-on-read for backward
    # compatibility with existing tests and the Inbox "mark all read"
    # action.
    inbox = get_inbox()
    entries = inbox.peek(tenant_id) if peek else inbox.drain(tenant_id)
    return [_entry_to_dto(e) for e in entries]


@router.post(
    "/verify",
    response_model=VerifyTokenResponse,
    summary="Verify a notification's HMAC token (receiver attestation)",
)
async def verify_notification_token(req: VerifyTokenRequest) -> VerifyTokenResponse:
    stub = UserContactProfile(user_id=req.user_id, email=req.email)
    ok = verify_token(req.token, stub, req.notification_id)
    return VerifyTokenResponse(ok=ok)


# ── Contact profile (per-tenant persistence) ───────────────


class ContactProfileDTO(BaseModel):
    """Per-tenant delivery preferences.

    Mirrors :class:`crp_comply.notifications.UserContactProfile` but
    the ``user_id`` field is always overridden by the caller's tenant
    on write so a compromised body can't smuggle in another tenant's
    handle.
    """

    email: str = ""
    full_name: str = ""
    phone_e164: str = ""
    preferred_channel: str = "in_app"
    timezone: str = "UTC"
    language: str = "en-GB"
    webhook_url: str = ""
    named_roles: dict[str, str] = Field(default_factory=dict)
    quiet_hours: dict[str, str] = Field(default_factory=dict)


class StoredContactProfileDTO(ContactProfileDTO):
    tenant_id: str


@router.get(
    "/contact-profile",
    response_model=StoredContactProfileDTO,
    summary="Read the caller's tenant contact profile",
)
async def get_contact_profile(
    tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> StoredContactProfileDTO:
    if tenant_id == "anonymous":
        raise HTTPException(
            status_code=401,
            detail="Anonymous callers have no contact profile.",
        )
    p = get_contact_store().get_or_default(tenant_id)
    return StoredContactProfileDTO(
        tenant_id=tenant_id,
        email=p.email,
        full_name=p.full_name,
        phone_e164=p.phone_e164,
        preferred_channel=p.preferred_channel,
        timezone=p.timezone,
        language=p.language,
        webhook_url=p.webhook_url,
        named_roles=dict(p.named_roles),
        quiet_hours=dict(p.quiet_hours),
    )


@router.put(
    "/contact-profile",
    response_model=StoredContactProfileDTO,
    summary="Upsert the caller's tenant contact profile",
)
async def put_contact_profile(
    body: ContactProfileDTO,
    tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> StoredContactProfileDTO:
    if tenant_id == "anonymous":
        raise HTTPException(
            status_code=401,
            detail="Anonymous callers cannot persist a contact profile.",
        )
    stored = get_contact_store().put(
        tenant_id,
        UserContactProfile(
            user_id=tenant_id,
            email=body.email,
            full_name=body.full_name,
            phone_e164=body.phone_e164,
            preferred_channel=body.preferred_channel,
            timezone=body.timezone,
            language=body.language,
            webhook_url=body.webhook_url,
            named_roles=dict(body.named_roles),
            quiet_hours=dict(body.quiet_hours),
        ),
    )
    return StoredContactProfileDTO(
        tenant_id=tenant_id,
        email=stored.email,
        full_name=stored.full_name,
        phone_e164=stored.phone_e164,
        preferred_channel=stored.preferred_channel,
        timezone=stored.timezone,
        language=stored.language,
        webhook_url=stored.webhook_url,
        named_roles=dict(stored.named_roles),
        quiet_hours=dict(stored.quiet_hours),
    )


def emit_notification(user_id: str, kind: str, payload: dict[str, Any]) -> None:
    """Fire-and-forget notification dispatch."""
    try:
        store = get_contact_store()
        profile = store.get_or_default(user_id)
        notification = Notification(
            kind=kind,
            subject=payload.get("subject", ""),
            body=payload.get("body", ""),
            priority=NotificationPriority(payload.get("priority", "medium")),
        )
        get_dispatcher().dispatch(user=profile, notification=notification)
    except Exception:
        logger.exception("Failed to emit notification for user %s", user_id)


__all__ = [
    "router",
    "override_dispatcher",
    "get_dispatcher",
    "get_inbox",
    "emit_notification",
]
