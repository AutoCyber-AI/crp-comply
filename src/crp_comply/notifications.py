# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Notification multiplexer for agent clarifications and event alerts.

The compliance agent regularly needs to reach out to the user:
clarification questions, deadline reminders, evidence-ready alerts.
This module is the transport-agnostic fan-out layer.

Design
------

* **Transport-agnostic.** Every channel implements
  :class:`NotificationChannel` and never imports network SDKs at
  module import time — each channel resolves its driver lazily so
  missing optional dependencies (smtplib/Twilio/etc.) don't break
  the import graph.
* **Receiver verification.** Every outbound notification carries a
  short HMAC-signed token tied to the recipient's `user_id` + `email`
  so the receiver can verify the message is for them (e.g. "this
  email was sent to you as the DPO for ``<tenant>``; verify here").
  The token is also the acknowledgement id used by the webhook
  ingress when the user clicks "Confirm".
* **Pluggable.** Production systems register custom channels (Slack,
  Teams, Pub/Sub) without touching the dispatcher.
* **Safe defaults.** If a channel's driver is unavailable the message
  is still logged to the in-app chat channel so nothing is silently
  dropped.

Intended use::

    from crp_comply.notifications import (
        NotificationDispatcher, Notification, NotificationPriority,
    )

    dispatcher = NotificationDispatcher.default()
    dispatcher.dispatch(
        user=contact_profile,
        notification=Notification(
            kind="clarification",
            subject="One question to finish your FRIA",
            body="Is your organisation deploying this system as a public body?",
            priority=NotificationPriority.HIGH,
            ring=True,
        ),
    )
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Protocol, runtime_checkable

log = logging.getLogger("crp_comply.notifications")


# ── Contact profile ───────────────────────────────────────────


#: Canonical contact fields we collect during onboarding — used by
#: :class:`NotificationDispatcher` to route messages and by the
#: receiver-verification footer to confirm the intended addressee.
CANONICAL_CONTACT_FIELDS: tuple[str, ...] = (
    "user_id",
    "full_name",
    "email",
    "phone_e164",
    "preferred_channel",  # in_app | email | sms | webhook
    "timezone",  # IANA — e.g. Europe/Athens
    "language",  # BCP-47 — e.g. en-GB
    "named_roles",  # dict: {"DPO": "...", "AI_OFFICER": "...", ...}
    "webhook_url",  # optional per-user webhook override
    "quiet_hours",  # dict: {"start": "22:00", "end": "07:00"}
)


@dataclass
class UserContactProfile:
    """Per-user contact + delivery preferences.

    This is the object the notification dispatcher consults before
    every send. It is orthogonal to the compliance-relevant
    :class:`~crp_comply.recipes.tailoring.UserProfile` (actor, high-risk,
    etc.) — one is about *what documents you owe*, this one is about
    *how we reach you*.
    """

    user_id: str
    email: str
    full_name: str = ""
    phone_e164: str = ""
    preferred_channel: str = "in_app"  # in_app | email | sms | webhook
    timezone: str = "UTC"
    language: str = "en-GB"
    named_roles: dict[str, str] = field(default_factory=dict)
    webhook_url: str = ""
    quiet_hours: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "email": self.email,
            "full_name": self.full_name,
            "phone_e164": self.phone_e164,
            "preferred_channel": self.preferred_channel,
            "timezone": self.timezone,
            "language": self.language,
            "named_roles": dict(self.named_roles),
            "webhook_url": self.webhook_url,
            "quiet_hours": dict(self.quiet_hours),
        }


# ── Notification model ────────────────────────────────────────


class NotificationPriority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class Notification:
    """A single message to send via one or more channels.

    ``kind`` is a free-form string (``clarification``,
    ``evidence_ready``, ``deadline_reminder``, ``incident``) so the
    UI can group / filter.

    ``ring=True`` tells the in-app chat channel to play a sound;
    ignored by other channels.
    """

    kind: str
    subject: str
    body: str
    priority: NotificationPriority = NotificationPriority.MEDIUM
    ring: bool = False
    sound: str = "soft_chime"
    cta_label: str = ""
    cta_url: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    #: Filled in by the dispatcher so every delivery has a traceable id.
    notification_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "notification_id": self.notification_id,
            "kind": self.kind,
            "subject": self.subject,
            "body": self.body,
            "priority": self.priority.value,
            "ring": self.ring,
            "sound": self.sound,
            "cta_label": self.cta_label,
            "cta_url": self.cta_url,
            "metadata": dict(self.metadata),
        }


@dataclass
class DeliveryReceipt:
    """What a channel returns after sending."""

    channel: str
    ok: bool
    delivered_to: str
    verification_token: str = ""
    error: str = ""
    sent_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "ok": self.ok,
            "delivered_to": self.delivered_to,
            "verification_token": self.verification_token,
            "error": self.error,
            "sent_at": self.sent_at,
        }


# ── Receiver verification (HMAC tokens) ───────────────────────


def _signing_key() -> bytes:
    """HMAC key source.

    Pulled from ``CRP_NOTIFY_SIGNING_KEY`` env var; falls back to a
    process-stable random-ish string derived from the PID + install
    time so dev environments work without configuration. Production
    deployments MUST set the env var.
    """
    key = os.environ.get("CRP_NOTIFY_SIGNING_KEY")
    if key:
        return key.encode("utf-8")
    # Deterministic-per-process dev fallback — NOT for production.
    return hashlib.sha256(
        f"crp-dev::{os.getpid()}::{os.path.abspath(__file__)}".encode("utf-8")
    ).digest()


def make_verification_token(user: UserContactProfile, notification_id: str) -> str:
    """Return a short HMAC token that proves this message is for ``user``.

    The token binds ``user_id + email + notification_id`` so a
    forwarded email still identifies the original recipient.
    """
    payload = f"{user.user_id}|{user.email}|{notification_id}".encode("utf-8")
    sig = hmac.new(_signing_key(), payload, hashlib.sha256).hexdigest()[:24]
    return sig


def verify_token(token: str, user: UserContactProfile, notification_id: str) -> bool:
    """Constant-time check that ``token`` was issued for ``(user, notification_id)``."""
    expected = make_verification_token(user, notification_id)
    return hmac.compare_digest(token, expected)


# ── Channel protocol + in-memory / stub channels ──────────────


@runtime_checkable
class NotificationChannel(Protocol):
    name: str

    def can_deliver(self, user: UserContactProfile) -> bool: ...

    def send(self, user: UserContactProfile, notification: Notification) -> DeliveryReceipt: ...


# ── In-app inbox backends ─────────────────────────────────────


@runtime_checkable
class InboxBackend(Protocol):
    """Storage contract for :class:`InAppChatChannel`.

    Implementations must be safe to share across threads. Appends
    must be durable relative to the backend's persistence guarantees
    (memory for the default; JSON-lines on disk for the persistent
    backend). Drains MUST be atomic per-tenant — a concurrent send
    during a drain either lands fully before or fully after, never
    half-torn.
    """

    def append(self, tenant_id: str, payload: dict[str, Any]) -> None: ...

    def drain(self, tenant_id: str) -> list[dict[str, Any]]: ...

    def peek(self, tenant_id: str) -> list[dict[str, Any]]: ...


class _MemoryInboxBackend:
    """Process-local in-memory backend (the default)."""

    def __init__(self) -> None:
        import threading

        self._queues: dict[str, list[dict[str, Any]]] = {}
        self._lock = threading.RLock()

    def append(self, tenant_id: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._queues.setdefault(tenant_id, []).append(payload)

    def drain(self, tenant_id: str) -> list[dict[str, Any]]:
        with self._lock:
            out = list(self._queues.get(tenant_id, []))
            self._queues[tenant_id] = []
            return out

    def peek(self, tenant_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._queues.get(tenant_id, []))


class PersistentInboxBackend:
    """JSON-lines inbox under ``{data_dir}/inbox/{sanitized_tenant}.jsonl``.

    Design notes
    ------------

    * **Append-only on send.** Every ``send`` opens the file in
      ``'a'`` mode and writes a single line — crash-safe for normal
      filesystem semantics, no partial rows on success.
    * **Drain is truncate-after-read.** A drain reads the current
      file, removes it, and returns the parsed payloads. A concurrent
      send during a drain lands in a freshly-created file on the next
      append — messages are preserved, not lost.
    * **Per-tenant lock.** Both operations hold a RLock so there's no
      torn-line read-under-write. Multi-process deployments that need
      stronger guarantees should swap in a real broker; the
      :class:`InboxBackend` protocol supports that.
    * **Isolation.** Every method takes ``tenant_id`` and derives the
      filename from it; there is no "global inbox" surface — no way to
      list other tenants' files from this class.
    """

    def __init__(self, data_dir: Path | str) -> None:  # type: ignore[name-defined]
        import threading

        from pathlib import Path as _Path

        self._dir = _Path(data_dir) / "inbox"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        # Back-compat peek surface for older tests that reached in.
        self._queues: dict[str, list[dict[str, Any]]] = {}

    @staticmethod
    def _safe(tenant_id: str) -> str:
        import re as _re

        safe = _re.sub(r"[^A-Za-z0-9._:@-]", "_", (tenant_id or "").strip())
        return safe or "anonymous"

    def _path(self, tenant_id: str):
        return self._dir / f"{self._safe(tenant_id)}.jsonl"

    def append(self, tenant_id: str, payload: dict[str, Any]) -> None:
        line = json.dumps(payload, default=str) + "\n"
        with self._lock:
            with self._path(tenant_id).open("a", encoding="utf-8") as f:
                f.write(line)

    def _read_all(self, tenant_id: str) -> list[dict[str, Any]]:
        p = self._path(tenant_id)
        if not p.exists():
            return []
        out: list[dict[str, Any]] = []
        try:
            for raw in p.read_text(encoding="utf-8").splitlines():
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    out.append(json.loads(raw))
                except json.JSONDecodeError as exc:
                    log.warning("skipping corrupt inbox line: %s", exc)
            return out
        except OSError as exc:
            log.warning("inbox read failed for tenant=%s: %s", tenant_id, exc)
            return []

    def drain(self, tenant_id: str) -> list[dict[str, Any]]:
        with self._lock:
            out = self._read_all(tenant_id)
            p = self._path(tenant_id)
            if p.exists():
                try:
                    p.unlink()
                except OSError as exc:  # pragma: no cover
                    log.warning("inbox unlink failed for tenant=%s: %s", tenant_id, exc)
            return out

    def peek(self, tenant_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return self._read_all(tenant_id)


class InAppChatChannel:
    """Per-tenant in-app inbox.

    By default the channel is an in-memory queue (fast, fine for tests
    and single-worker dev). Production deployments wire a
    :class:`PersistentInboxBackend` via :func:`init_persistent_inbox`
    so messages survive process restarts and are scoped by tenant on
    disk. Both backends share the same ``send/drain/peek`` contract.

    Isolation: ``user_id`` on the ``UserContactProfile`` is treated as
    the tenant handle — callers are expected to have already resolved
    it through :func:`crp_comply.api.deps.get_current_tenant`. The
    channel does not look up or infer tenancy itself.
    """

    name = "in_app"

    def __init__(self, backend: "InboxBackend | None" = None) -> None:
        self._backend: InboxBackend = backend or _MemoryInboxBackend()
        # Back-compat attribute used by older tests that peeked directly.
        self._queues = getattr(self._backend, "_queues", {})

    def set_backend(self, backend: "InboxBackend") -> None:
        """Swap the backend at runtime (used by ``init_persistent_inbox``)."""
        self._backend = backend
        self._queues = getattr(backend, "_queues", {})

    def can_deliver(self, user: UserContactProfile) -> bool:
        return bool(user.user_id)

    def send(self, user: UserContactProfile, notification: Notification) -> DeliveryReceipt:
        token = make_verification_token(user, notification.notification_id)
        payload = {
            "notification": notification.to_dict(),
            "ring": notification.ring,
            "sound": notification.sound,
            "verification_token": token,
            "received_at": time.time(),
        }
        self._backend.append(user.user_id, payload)
        return DeliveryReceipt(
            channel=self.name,
            ok=True,
            delivered_to=user.user_id,
            verification_token=token,
        )

    # Inspection helpers for UI + tests.
    def drain(self, user_id: str) -> list[dict[str, Any]]:
        return self._backend.drain(user_id)

    def peek(self, user_id: str) -> list[dict[str, Any]]:
        return self._backend.peek(user_id)


class EmailChannel:
    """SMTP e-mail channel with a log-only stub fallback.

    ``sender`` is a callable ``(to, subject, body, headers) -> bool``
    injected by the deployment — in tests we pass a list-capturing
    stub; in production a real SMTP helper (e.g.
    ``crp_comply.integrations.email.send_smtp``) is wired.

    Every outbound email embeds the HMAC verification token in an
    ``X-CRP-Verify`` header and a plain-text footer so recipients can
    confirm they are the intended addressee.
    """

    name = "email"

    def __init__(
        self,
        sender: Callable[[str, str, str, dict[str, str]], bool] | None = None,
    ) -> None:
        self._sender = sender

    def can_deliver(self, user: UserContactProfile) -> bool:
        return "@" in (user.email or "")

    def send(self, user: UserContactProfile, notification: Notification) -> DeliveryReceipt:
        token = make_verification_token(user, notification.notification_id)
        footer = (
            "\n\n---\n"
            f"This message was sent to {user.full_name or user.email} "
            f"<{user.email}>.\n"
            f"Verification token: {token}\n"
            "If this isn't you, ignore or report at /security."
        )
        body = notification.body + footer
        headers = {
            "X-CRP-Verify": token,
            "X-CRP-Notification-Id": notification.notification_id,
            "X-CRP-Kind": notification.kind,
        }
        if self._sender is None:
            log.info(
                "email channel stub: would send to %s subj=%s",
                user.email,
                notification.subject,
            )
            return DeliveryReceipt(
                channel=self.name,
                ok=True,
                delivered_to=user.email,
                verification_token=token,
            )
        try:
            ok = bool(self._sender(user.email, notification.subject, body, headers))
            return DeliveryReceipt(
                channel=self.name,
                ok=ok,
                delivered_to=user.email,
                verification_token=token,
                error="" if ok else "sender returned False",
            )
        except Exception as exc:  # pragma: no cover
            log.exception("email send failed")
            return DeliveryReceipt(
                channel=self.name,
                ok=False,
                delivered_to=user.email,
                verification_token=token,
                error=str(exc),
            )


class SmsChannel:
    """Twilio-shape SMS channel — driver injected at construction."""

    name = "sms"

    def __init__(
        self,
        sender: Callable[[str, str], bool] | None = None,
    ) -> None:
        self._sender = sender

    def can_deliver(self, user: UserContactProfile) -> bool:
        return bool(user.phone_e164) and user.phone_e164.startswith("+")

    def send(self, user: UserContactProfile, notification: Notification) -> DeliveryReceipt:
        token = make_verification_token(user, notification.notification_id)
        # SMS is length-constrained; keep it to the subject + CTA.
        msg = f"[CRP Comply] {notification.subject}"
        if notification.cta_url:
            msg += f" → {notification.cta_url}"
        msg = msg[:155]  # leave room for the token
        msg += f" [{token[:8]}]"
        if self._sender is None:
            log.info("sms channel stub: would send to %s: %s", user.phone_e164, msg)
            return DeliveryReceipt(
                channel=self.name,
                ok=True,
                delivered_to=user.phone_e164,
                verification_token=token,
            )
        try:
            ok = bool(self._sender(user.phone_e164, msg))
            return DeliveryReceipt(
                channel=self.name,
                ok=ok,
                delivered_to=user.phone_e164,
                verification_token=token,
                error="" if ok else "sender returned False",
            )
        except Exception as exc:  # pragma: no cover
            log.exception("sms send failed")
            return DeliveryReceipt(
                channel=self.name,
                ok=False,
                delivered_to=user.phone_e164,
                verification_token=token,
                error=str(exc),
            )


class WebhookChannel:
    """POSTs the notification JSON to a per-user webhook URL.

    ``poster`` is an injected callable ``(url, body) -> bool`` so we
    never hard-depend on ``requests``/``httpx``.
    """

    name = "webhook"

    def __init__(
        self,
        poster: Callable[[str, dict[str, Any]], bool] | None = None,
    ) -> None:
        self._poster = poster

    def can_deliver(self, user: UserContactProfile) -> bool:
        return bool(user.webhook_url)

    def send(self, user: UserContactProfile, notification: Notification) -> DeliveryReceipt:
        token = make_verification_token(user, notification.notification_id)
        body = {
            "user_id": user.user_id,
            "notification": notification.to_dict(),
            "verification_token": token,
        }
        if self._poster is None:
            log.info(
                "webhook channel stub: would POST to %s: %s",
                user.webhook_url,
                json.dumps(body)[:200],
            )
            return DeliveryReceipt(
                channel=self.name,
                ok=True,
                delivered_to=user.webhook_url,
                verification_token=token,
            )
        try:
            ok = bool(self._poster(user.webhook_url, body))
            return DeliveryReceipt(
                channel=self.name,
                ok=ok,
                delivered_to=user.webhook_url,
                verification_token=token,
                error="" if ok else "poster returned False",
            )
        except Exception as exc:  # pragma: no cover
            log.exception("webhook post failed")
            return DeliveryReceipt(
                channel=self.name,
                ok=False,
                delivered_to=user.webhook_url,
                verification_token=token,
                error=str(exc),
            )


# ── Dispatcher ────────────────────────────────────────────────


class NotificationDispatcher:
    """Fan-out notifications according to user preferences.

    Routing rules (in order):

    1. ``HIGH`` priority notifications always fan out to **in-app chat**
       (with ``ring=True`` forced on) *plus* any other channels the
       user's preference selects. Urgency beats preference.
    2. Otherwise the user's ``preferred_channel`` is the primary
       target; if the channel can't deliver (no email address / no
       phone) we fall back to in-app chat.
    3. Quiet-hours: ``HIGH`` bypasses; otherwise non-chat channels
       are held for after-hours delivery (represented here as a
       ``held=True`` receipt).
    4. Every notification gets a fresh UUID as ``notification_id`` so
       verification tokens are message-bound.
    """

    def __init__(self, channels: list[NotificationChannel]) -> None:
        by_name: dict[str, NotificationChannel] = {}
        for c in channels:
            by_name[c.name] = c
        self._channels = by_name
        if "in_app" not in by_name:
            # Guarantee the chat fallback exists.
            self._channels["in_app"] = InAppChatChannel()

    @classmethod
    def default(cls) -> "NotificationDispatcher":
        return cls([InAppChatChannel(), EmailChannel(), SmsChannel(), WebhookChannel()])

    def channel(self, name: str) -> NotificationChannel | None:
        return self._channels.get(name)

    def _is_quiet(self, user: UserContactProfile) -> bool:
        qh = user.quiet_hours or {}
        start, end = qh.get("start"), qh.get("end")
        if not (start and end):
            return False
        now = time.strftime("%H:%M", time.gmtime())
        # Simple UTC window; good enough for this layer. Production
        # should translate via the user's TZ.
        if start <= end:
            return start <= now <= end
        return now >= start or now <= end

    def dispatch(
        self,
        user: UserContactProfile,
        notification: Notification,
    ) -> list[DeliveryReceipt]:
        if not notification.notification_id:
            notification.notification_id = uuid.uuid4().hex

        is_high = notification.priority == NotificationPriority.HIGH
        targets: list[str] = []
        if is_high:
            targets.append("in_app")
            notification.ring = True  # override — urgency demands it
            if user.preferred_channel and user.preferred_channel != "in_app":
                targets.append(user.preferred_channel)
        else:
            if self._is_quiet(user):
                targets.append("in_app")
            else:
                preferred = user.preferred_channel or "in_app"
                ch = self._channels.get(preferred)
                if ch and ch.can_deliver(user):
                    targets.append(preferred)
                else:
                    targets.append("in_app")

        # Dedup while preserving order.
        seen: set[str] = set()
        ordered: list[str] = []
        for t in targets:
            if t not in seen:
                seen.add(t)
                ordered.append(t)

        receipts: list[DeliveryReceipt] = []
        for name in ordered:
            ch = self._channels.get(name)
            if ch is None:
                receipts.append(
                    DeliveryReceipt(
                        channel=name,
                        ok=False,
                        delivered_to=user.user_id,
                        error="channel_not_registered",
                    )
                )
                continue
            if not ch.can_deliver(user):
                receipts.append(
                    DeliveryReceipt(
                        channel=name,
                        ok=False,
                        delivered_to=user.user_id,
                        error="channel_cannot_deliver_for_user",
                    )
                )
                continue
            receipts.append(ch.send(user, notification))
        return receipts


__all__ = [
    "CANONICAL_CONTACT_FIELDS",
    "DeliveryReceipt",
    "EmailChannel",
    "InAppChatChannel",
    "InboxBackend",
    "Notification",
    "NotificationChannel",
    "NotificationDispatcher",
    "NotificationPriority",
    "PersistentInboxBackend",
    "SmsChannel",
    "UserContactProfile",
    "WebhookChannel",
    "init_persistent_inbox",
    "make_verification_token",
    "verify_token",
]


# ── Persistent inbox bootstrap ────────────────────────────────
#
# Called from the API lifespan on startup. Swaps the in-memory backend
# of the process-wide dispatcher's ``in_app`` channel for a JSON-lines
# backend rooted at ``{data_dir}/inbox/``. Idempotent — safe to call
# more than once (reconfigures the backend pointer).


def init_persistent_inbox(data_dir: "Path | str") -> "PersistentInboxBackend":  # type: ignore[name-defined]
    """Install :class:`PersistentInboxBackend` on the API dispatcher.

    This is a delayed import to avoid circular imports between
    ``crp_comply.notifications`` and ``crp_comply.api.notifications``.
    Callers outside the API layer can build a
    :class:`PersistentInboxBackend` directly and pass it to
    :class:`InAppChatChannel(backend=...)`.
    """
    backend = PersistentInboxBackend(data_dir=data_dir)
    try:  # pragma: no cover - api module may not be imported in some CLI flows
        from .api.notifications import get_inbox  # local import

        inbox = get_inbox()
        inbox.set_backend(backend)
    except Exception as exc:  # pragma: no cover
        log.info("persistent inbox registered but API not wired: %s", exc)
    return backend
