# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for the passkey adaptive risk engine's bootstrap behaviour."""

from __future__ import annotations

import time
from typing import Any

import pytest

from crp_shared.passkey import AuthContext, PasskeyManager


class _FakePool:
    def __init__(self, events: list[dict[str, Any]], cred_created_at: float | None = None) -> None:
        self.events = events
        self.cred_created_at = cred_created_at

    async def fetch(self, _query: str, *args: Any) -> list[dict[str, Any]]:
        return self.events

    async def fetchrow(self, _query: str, *args: Any) -> dict[str, Any] | None:
        if self.cred_created_at is None:
            return None
        return {"created_at": self.cred_created_at}


def _manager(events: list[dict[str, Any]], cred_created_at: float | None = None) -> PasskeyManager:
    return PasskeyManager(
        pool=_FakePool(events, cred_created_at),  # type: ignore[arg-type]
        rp_id="localhost",
        rp_name="CRP Comply",
        origin="http://localhost",
    )


@pytest.mark.asyncio
async def test_first_successful_verification_is_never_blocked():
    """A user with no prior successful authentications is allowed to bootstrap."""
    now = time.time()
    events = [
        {
            "ip_hash": "known-ip",
            "ua_hash": "known-ua",
            "geo_hash": "known-geo",
            "success": True,
            "created_at": now - 10,
            "risk_factors": ["registration"],
        }
    ]
    context = AuthContext(ip_address="new-ip", user_agent="new-ua", geo_hint="new-geo")
    manager = _manager(events)

    risk = await manager.assess_risk("user-1", context)

    assert risk.decision == "allow"
    assert risk.score <= 35.0
    assert "first_verification_bootstrap" in risk.factors


@pytest.mark.asyncio
async def test_new_credential_bypasses_unknown_context():
    """A credential registered within the bootstrap window can verify from a new context."""
    now = time.time()
    events = [
        {
            "ip_hash": "known-ip",
            "ua_hash": "known-ua",
            "geo_hash": "known-geo",
            "success": True,
            "created_at": now - 3600,
            "risk_factors": [],
        }
    ]
    context = AuthContext(ip_address="new-ip", user_agent="new-ua", geo_hint="new-geo")
    manager = _manager(events, cred_created_at=now - 60)

    risk = await manager.assess_risk("user-1", context, credential_id="cred-new")

    assert risk.decision == "allow"
    assert "first_verification_bootstrap" in risk.factors


@pytest.mark.asyncio
async def test_known_context_allows_verification():
    """Same IP, device and location as prior successes is a clean login."""
    now = time.time()
    context = AuthContext(ip_address="1.2.3.4", user_agent="test-ua", geo_hint="AU-Sydney")
    events = [
        {
            "ip_hash": context.ip_hash(),
            "ua_hash": context.ua_hash(),
            "geo_hash": context.geo_hash(),
            "success": True,
            "created_at": now - 3600,
            "risk_factors": [],
        }
    ]
    manager = _manager(events)

    risk = await manager.assess_risk("user-1", context)

    assert risk.decision == "allow"
    assert "first_verification_bootstrap" not in risk.factors


@pytest.mark.asyncio
async def test_unknown_context_with_history_can_block():
    """Without the bootstrap window, a new IP/device/location from a stale account blocks."""
    now = time.time()
    context = AuthContext(ip_address="5.6.7.8", user_agent="evil-ua", geo_hint="ZZ-Unknown")
    events = [
        {
            "ip_hash": "old-ip",
            "ua_hash": "old-ua",
            "geo_hash": "old-geo",
            "success": True,
            "created_at": now - 40 * 24 * 3600,
            "risk_factors": [],
        }
    ]
    manager = _manager(events, cred_created_at=now - 3600)

    risk = await manager.assess_risk("user-1", context, credential_id="cred-old")

    assert risk.decision == "block"
    assert "first_verification_bootstrap" not in risk.factors
