# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for the Stripe billing webhook endpoint."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from crp_comply.api.app import create_app
from crp_comply.api.auth import AuthManager
from crp_comply.api.deps import init_dependencies
from crp_comply.api.usage import init_usage_tracker
from crp_comply.core import CRPComply


@pytest_asyncio.fixture
async def client(tmp_path):
    app = create_app()
    auth = AuthManager(data_dir=tmp_path, jwt_secret="test-secret")
    comply = CRPComply()
    init_dependencies(auth=auth, comply=comply)
    init_usage_tracker(data_dir=tmp_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class FakeStripeEvent:
    """Lightweight stand-in for a Stripe event object."""

    def __init__(self, event_id: str, event_type: str = "invoice.paid") -> None:
        self.id = event_id
        self.type = event_type
        self.data = {"object": {"id": "evt_obj", "customer": "cus_test"}}

    def __getitem__(self, key: str):
        if key == "data":
            return self.data
        raise KeyError(key)


def _make_stripe_event(event_id: str, event_type: str = "invoice.paid") -> FakeStripeEvent:
    return FakeStripeEvent(event_id, event_type)


@pytest.mark.asyncio
async def test_stripe_webhook_503_when_unconfigured(client):
    """Webhook returns 503 (not 500) when STRIPE_WEBHOOK_SECRET is missing."""
    with patch.dict("os.environ", {"STRIPE_WEBHOOK_SECRET": ""}, clear=False):
        resp = await client.post(
            "/api/v1/billing/webhook",
            content=b"{}",
            headers={"Stripe-Signature": "v0,sig"},
        )
    assert resp.status_code == 503
    assert "not configured" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_stripe_webhook_rejects_invalid_signature(client):
    """Invalid signatures return 400 and are not acknowledged."""
    with patch.dict("os.environ", {"STRIPE_WEBHOOK_SECRET": "whsec_test"}, clear=False):
        resp = await client.post(
            "/api/v1/billing/webhook",
            content=b"{}",
            headers={"Stripe-Signature": "v0,invalid"},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_stripe_webhook_idempotency_and_replay(client):
    """Duplicate event IDs return 200 without re-running the handler."""
    event_id = f"evt_replay_{int(time.time() * 1000)}"
    event = _make_stripe_event(event_id)
    processed_ids: set[str] = set()

    def _fake_handle_invoice_paid(_auth, _data):
        processed_ids.add(event.id)

    env = {"STRIPE_WEBHOOK_SECRET": "whsec_test"}
    with (
        patch.dict("os.environ", env, clear=False),
        patch("crp_comply.api.billing.stripe.Webhook.construct_event", return_value=event),
        patch("crp_comply.api.billing._handle_invoice_paid", new=_fake_handle_invoice_paid),
    ):
        # First delivery succeeds.
        resp1 = await client.post(
            "/api/v1/billing/webhook",
            content=b"{}",
            headers={"Stripe-Signature": "t=1,v1=sig"},
        )
        assert resp1.status_code == 200
        assert processed_ids == {event_id}

        # Replay with the same event ID returns 200 but does not re-run handler.
        processed_ids.clear()
        resp2 = await client.post(
            "/api/v1/billing/webhook",
            content=b"{}",
            headers={"Stripe-Signature": "t=1,v1=sig"},
        )
        assert resp2.status_code == 200
        assert processed_ids == set()


@pytest.mark.asyncio
async def test_stripe_webhook_handler_failure_returns_400(client):
    """Handler failures return 400 and the event is not acknowledged."""
    event = _make_stripe_event("evt_fail_1", event_type="checkout.session.completed")

    env = {"STRIPE_WEBHOOK_SECRET": "whsec_test"}
    with (
        patch.dict("os.environ", env, clear=False),
        patch("crp_comply.api.billing.stripe.Webhook.construct_event", return_value=event),
        patch(
            "crp_comply.api.billing._handle_checkout_completed",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ),
    ):
        resp = await client.post(
            "/api/v1/billing/webhook",
            content=b"{}",
            headers={"Stripe-Signature": "t=1,v1=sig"},
        )

    assert resp.status_code == 400
    assert "handler failed" in resp.json()["detail"].lower()
