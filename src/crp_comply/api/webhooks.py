# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Signed outbound webhooks — addresses PRODUCT_SECURITY.md §4 gap #2.

Any tenant-facing notification that leaves our system (Slack incident
webhook, customer SIEM, Stripe-style self-serve webhook) is signed with
HMAC-SHA256 using a per-webhook secret the user configured. Consumers
verify the signature using the same secret.

Header format (inspired by Stripe / GitHub, intentionally compatible):

    X-CRPComply-Signature: t=<unix_ts>,v1=<hex_hmac_sha256>
    X-CRPComply-Event: <event.name>
    X-CRPComply-Delivery: <uuid4 per send>

The signed payload is ``f"{t}.{raw_body}"`` so replayed bodies with a
stale timestamp are detectable (recipients should reject if
``abs(now-t) > 300``).

The sender retries 3 times with exponential backoff on non-2xx, then
persists a "failed" record which is surfaced via
``GET /webhooks/{id}/deliveries``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx


log = logging.getLogger("crp_comply.api.webhooks")


def sign_payload(secret: str, raw_body: bytes, *, ts: int | None = None) -> str:
    """Return the signature header value for ``raw_body``.

    Format: ``t=<unix_ts>,v1=<hex>``. Recipients verify by recomputing
    ``hmac_sha256(secret, f"{t}.{raw_body}")`` and constant-time comparing.
    """
    if ts is None:
        ts = int(time.time())
    signed = f"{ts}.".encode("utf-8") + raw_body
    mac = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


def verify_signature(
    secret: str,
    raw_body: bytes,
    header_value: str,
    *,
    tolerance_seconds: int = 300,
) -> bool:
    """Constant-time verify a webhook signature header.

    Returns False (never raises) on malformed header or stale timestamp.
    """
    try:
        parts = dict(p.split("=", 1) for p in header_value.split(","))
        ts = int(parts["t"])
        sig = parts["v1"]
    except Exception:
        return False
    if abs(time.time() - ts) > tolerance_seconds:
        return False
    expected = sign_payload(secret, raw_body, ts=ts).split(",")[1].split("=", 1)[1]
    return hmac.compare_digest(expected, sig)


# ─────────────────────────────────────────────────────────────
# Delivery
# ─────────────────────────────────────────────────────────────


@dataclass
class WebhookDelivery:
    id: str
    webhook_id: str
    event: str
    url: str
    status_code: int | None = None
    attempts: int = 0
    created_at: float = field(default_factory=time.time)
    last_error: str | None = None
    ok: bool = False


def _post_once(url: str, body: bytes, headers: dict[str, str], timeout: float) -> httpx.Response:
    with httpx.Client(timeout=timeout) as client:
        return client.post(url, content=body, headers=headers)


def deliver(
    *,
    webhook_id: str,
    url: str,
    secret: str,
    event: str,
    payload: dict[str, Any],
    max_attempts: int = 3,
    base_backoff: float = 0.5,
    timeout: float = 10.0,
) -> WebhookDelivery:
    """Deliver ``payload`` to ``url`` with signed headers.

    Retries on non-2xx up to ``max_attempts`` with exponential backoff.
    Returns a :class:`WebhookDelivery` record suitable for persistence.
    """
    raw = json.dumps(payload, default=str, ensure_ascii=False).encode("utf-8")
    delivery = WebhookDelivery(
        id=str(uuid.uuid4()),
        webhook_id=webhook_id,
        event=event,
        url=url,
    )
    for attempt in range(1, max_attempts + 1):
        delivery.attempts = attempt
        sig = sign_payload(secret, raw)
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "CRP-Comply-Webhook/1.0",
            "X-CRPComply-Signature": sig,
            "X-CRPComply-Event": event,
            "X-CRPComply-Delivery": delivery.id,
        }
        try:
            resp = _post_once(url, raw, headers, timeout)
            delivery.status_code = resp.status_code
            if 200 <= resp.status_code < 300:
                delivery.ok = True
                return delivery
            delivery.last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
        except Exception as exc:
            delivery.last_error = f"{type(exc).__name__}: {exc}"
            log.warning("webhook %s attempt %d failed: %s", webhook_id, attempt, exc)
        if attempt < max_attempts:
            time.sleep(base_backoff * (2 ** (attempt - 1)))
    return delivery
