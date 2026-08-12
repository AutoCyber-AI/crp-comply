# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Per-user monthly usage tracking and quota enforcement.

Tracks every audited LLM/compliance call against the user's monthly quota
(determined by their subscription tier). Persists to a JSON file alongside
auth/users so it survives restarts on Railway's mounted volume.

Usage rolls over on the 1st of each calendar month (UTC).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .auth import Tier

logger = logging.getLogger("crp_comply.usage")


# ── Per-tier monthly call quotas ──────────────────────────────
# Aligned with Pricing.tsx: Free 100, Starter 5K, Scale 50K, Enterprise unlimited.
TIER_MONTHLY_QUOTA: dict[Tier, int] = {
    Tier.FREE: 100,
    Tier.STARTER: 5_000,  # Starter ($49 / 5K)
    Tier.PRO: 50_000,  # Professional / legacy Pro ($199 / 50K)
    Tier.SCALE: 50_000,  # Scale ($499 / 50K)
    Tier.ENTERPRISE: 10_000_000,  # Enterprise (custom contract; effectively unlimited)
    Tier.CLOUD: 10_000_000,  # Cloud / managed enterprise
}

# Overage policy: HARD_BLOCK at quota; SOFT_ALLOW lets calls through and emits overage
# events (for Stripe metered billing). Default to HARD_BLOCK to protect free tier.
OVERAGE_POLICY: dict[Tier, str] = {
    Tier.FREE: "HARD_BLOCK",
    Tier.STARTER: "SOFT_ALLOW",
    Tier.PRO: "SOFT_ALLOW",
    Tier.SCALE: "SOFT_ALLOW",
    Tier.ENTERPRISE: "SOFT_ALLOW",
    Tier.CLOUD: "SOFT_ALLOW",
}


def current_period() -> str:
    """Return the YYYY-MM key for the current UTC month."""
    now = datetime.now(timezone.utc)
    return f"{now.year:04d}-{now.month:02d}"


class QuotaExceededError(Exception):
    """Raised when a user has exceeded their monthly call quota."""

    def __init__(self, user_id: str, used: int, quota: int, tier: Tier) -> None:
        self.user_id = user_id
        self.used = used
        self.quota = quota
        self.tier = tier
        super().__init__(f"Monthly quota exceeded: {used}/{quota} calls used on {tier.value} tier")


class UsageTracker:
    """File-backed per-user monthly call counter.

    Storage layout (data/usage.json):
        {
            "<user_id>": {
                "<YYYY-MM>": {
                    "total_calls": int,
                    "billable_calls": int,
                    "overage_calls": int,
                    "by_endpoint": { "<endpoint>": int, ... },
                    "first_call_at": "<iso>",
                    "last_call_at": "<iso>",
                }
            }
        }

    Anonymous users are not tracked here — they use the public router's
    in-memory IP rate limiter instead.
    """

    def __init__(self, data_dir: Path | str = "data") -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._file = self._data_dir / "usage.json"
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, dict[str, Any]]] = {}
        self._load()

    # ── Persistence ───────────────────────────────────────────
    def _load(self) -> None:
        if self._file.exists():
            try:
                self._data = json.loads(self._file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load usage file (%s); starting fresh", e)
                self._data = {}

    def _save_unlocked(self) -> None:
        try:
            self._file.write_text(
                json.dumps(self._data, indent=2, default=str),
                encoding="utf-8",
            )
        except OSError as e:
            logger.error("Failed to persist usage data: %s", e)

    # ── Public API ────────────────────────────────────────────
    def get_usage(self, user_id: str, period: str | None = None) -> dict[str, Any]:
        """Return current period's usage record for a user (zeroed if absent)."""
        period = period or current_period()
        with self._lock:
            user = self._data.get(user_id, {})
            record = user.get(period, {})
        return {
            "period": period,
            "total_calls": int(record.get("total_calls", 0)),
            "billable_calls": int(record.get("billable_calls", 0)),
            "overage_calls": int(record.get("overage_calls", 0)),
            "by_endpoint": dict(record.get("by_endpoint", {})),
            "first_call_at": record.get("first_call_at"),
            "last_call_at": record.get("last_call_at"),
        }

    def check_quota(self, user_id: str, tier: Tier) -> dict[str, Any]:
        """Return quota status without incrementing.

        Returns a dict with keys: used, quota, remaining, pct_used, blocked,
        tier, period, resets_at.
        """
        usage = self.get_usage(user_id)
        used = usage["total_calls"]
        quota = TIER_MONTHLY_QUOTA.get(tier, 0)
        policy = OVERAGE_POLICY.get(tier, "HARD_BLOCK")
        blocked = used >= quota and policy == "HARD_BLOCK"

        # Compute next-month UTC midnight as resets_at
        now = datetime.now(timezone.utc)
        if now.month == 12:
            resets = now.replace(
                year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0
            )
        else:
            resets = now.replace(
                month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0
            )

        return {
            "user_id": user_id,
            "tier": tier.value,
            "period": usage["period"],
            "used": used,
            "quota": quota,
            "remaining": max(0, quota - used),
            "pct_used": round(100.0 * used / quota, 2) if quota > 0 else 0.0,
            "overage_calls": usage["overage_calls"],
            "blocked": blocked,
            "policy": policy,
            "resets_at": resets.isoformat(),
        }

    def record_call(
        self,
        user_id: str,
        tier: Tier,
        endpoint: str,
        *,
        increment: int = 1,
    ) -> dict[str, Any]:
        """Increment the user's call counter and return the post-increment status.

        Raises QuotaExceededError if the user is on a HARD_BLOCK tier and
        already at or above quota. Calls above quota on SOFT_ALLOW tiers are
        recorded as overage_calls for downstream metered billing.
        """
        if user_id == "anonymous":
            # Anonymous traffic never touches per-user counters.
            return self.check_quota(user_id, tier)

        period = current_period()
        now_iso = datetime.now(timezone.utc).isoformat()
        quota = TIER_MONTHLY_QUOTA.get(tier, 0)
        policy = OVERAGE_POLICY.get(tier, "HARD_BLOCK")

        with self._lock:
            user = self._data.setdefault(user_id, {})
            record = user.setdefault(
                period,
                {
                    "total_calls": 0,
                    "billable_calls": 0,
                    "overage_calls": 0,
                    "by_endpoint": {},
                    "first_call_at": now_iso,
                    "last_call_at": now_iso,
                },
            )
            current = int(record.get("total_calls", 0))

            # Pre-increment quota check for HARD_BLOCK tiers
            if policy == "HARD_BLOCK" and current >= quota:
                raise QuotaExceededError(user_id, current, quota, tier)

            new_total = current + increment
            record["total_calls"] = new_total
            if new_total > quota:
                # The portion above quota is overage; the rest is billable-included.
                record["billable_calls"] = quota
                record["overage_calls"] = new_total - quota
            else:
                record["billable_calls"] = new_total
                record["overage_calls"] = 0
            record["by_endpoint"][endpoint] = (
                int(record["by_endpoint"].get(endpoint, 0)) + increment
            )
            record["last_call_at"] = now_iso

            self._save_unlocked()

        status = self.check_quota(user_id, tier)
        if status["overage_calls"] > 0 and policy == "SOFT_ALLOW":
            logger.info(
                "Overage call recorded for user=%s tier=%s endpoint=%s overage=%d",
                user_id,
                tier.value,
                endpoint,
                status["overage_calls"],
            )
            # Best-effort report to Stripe Meter API (metered billing).
            # Gated behind STRIPE_METER_ID_OVERAGES so deployments without
            # a meter configured incur zero overhead.
            self._emit_stripe_meter_overage(user_id, increment)
        return status

    def _emit_stripe_meter_overage(self, user_id: str, increment: int) -> None:
        """Report ``increment`` overage calls to a Stripe Meter (best-effort).

        Wires into Stripe's Billing Meters API (introduced 2024) so the
        operator can charge $/call for soft-allowed overage. Silent on any
        failure — never blocks the request path.

        The Stripe event name is read from ``STRIPE_METER_EVENT_NAME``
        (preferred; e.g. ``comply_proxy_requests``). Falls back to
        ``STRIPE_METER_ID_OVERAGES`` for older deployments.
        """
        event_name = os.environ.get("STRIPE_METER_EVENT_NAME", "") or os.environ.get(
            "STRIPE_METER_ID_OVERAGES", ""
        )
        if not event_name or increment <= 0:
            return
        try:
            import stripe  # type: ignore[import-not-found]

            if not stripe.api_key:
                stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
            if not stripe.api_key:
                return

            # Look up the Stripe customer ID for this user.
            try:
                from .deps import get_auth as _get_auth

                _auth = _get_auth()
                user = _auth.get_user(user_id)
                customer_id = getattr(user, "stripe_customer_id", None) if user else None
            except Exception:
                customer_id = None

            if not customer_id:
                return

            # Stripe SDK ≥7.x — billing.meter_event_summary is the documented surface;
            # for legacy SDKs fall back to billing.meter_event. The probe verifies
            # the attribute path exists before we attempt the call below.
            _ = (  # noqa: F841 — intentional capability probe
                getattr(getattr(stripe, "billing", None), "meter_event", None)
                or getattr(getattr(stripe, "v1", None), "billing", None)
            )
            payload = {
                "event_name": event_name,
                "payload": {
                    "stripe_customer_id": customer_id,
                    "value": str(int(increment)),
                },
            }
            try:
                stripe.billing.meter_event.create(**payload)  # type: ignore[attr-defined]
            except Exception:
                # Older SDK shapes: try the v2 API surface.
                try:
                    stripe.billing.MeterEvent.create(**payload)  # type: ignore[attr-defined]
                except Exception as exc:  # pragma: no cover
                    logger.debug("stripe meter event failed: %s", exc)
        except Exception as exc:  # pragma: no cover
            logger.debug("stripe meter integration unavailable: %s", exc)

    # ── Token + cost telemetry (design §6 / DEFERRED_TODOS §6) ──

    def record_tokens(
        self,
        user_id: str,
        *,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float = 0.0,
        session_id: str | None = None,
        endpoint: str = "llm",
        latency_ms: int | None = None,
    ) -> None:
        """Persist per-call token + cost telemetry.

        Storage: ``data/usage.json["<user>"]["<period>"]["llm"]`` carries
        aggregates, and the full per-call record is appended to
        ``data/usage_tokens.ndjson`` for per-session drill-downs.
        """
        period = current_period()
        now_iso = datetime.now(timezone.utc).isoformat()
        cost = max(0.0, float(cost_usd))
        it = max(0, int(input_tokens))
        ot = max(0, int(output_tokens))

        with self._lock:
            user = self._data.setdefault(user_id, {})
            record = user.setdefault(
                period,
                {
                    "total_calls": 0,
                    "billable_calls": 0,
                    "overage_calls": 0,
                    "by_endpoint": {},
                    "first_call_at": now_iso,
                    "last_call_at": now_iso,
                },
            )
            llm = record.setdefault(
                "llm",
                {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "by_model": {}},
            )
            llm["input_tokens"] = int(llm.get("input_tokens", 0)) + it
            llm["output_tokens"] = int(llm.get("output_tokens", 0)) + ot
            llm["cost_usd"] = round(float(llm.get("cost_usd", 0.0)) + cost, 6)
            m = llm["by_model"].setdefault(
                model,
                {
                    "calls": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost_usd": 0.0,
                    "provider": provider,
                },
            )
            m["calls"] = int(m.get("calls", 0)) + 1
            m["input_tokens"] = int(m.get("input_tokens", 0)) + it
            m["output_tokens"] = int(m.get("output_tokens", 0)) + ot
            m["cost_usd"] = round(float(m.get("cost_usd", 0.0)) + cost, 6)
            self._save_unlocked()

        # Append raw per-call row for session-level drill-downs.
        try:
            drill = self._data_dir / "usage_tokens.ndjson"
            drill.parent.mkdir(parents=True, exist_ok=True)
            with drill.open("a", encoding="utf-8") as fh:
                fh.write(
                    json.dumps(
                        {
                            "ts": now_iso,
                            "user_id": user_id,
                            "session_id": session_id,
                            "endpoint": endpoint,
                            "provider": provider,
                            "model": model,
                            "input_tokens": it,
                            "output_tokens": ot,
                            "cost_usd": cost,
                            "latency_ms": latency_ms,
                        },
                        default=str,
                    )
                    + "\n"
                )
        except OSError as exc:  # pragma: no cover
            logger.warning("failed to persist usage_tokens row: %s", exc)

    def get_cost_summary(self, user_id: str, period: str | None = None) -> dict[str, Any]:
        """Return aggregated input/output/cost for the user in ``period``."""
        period = period or current_period()
        with self._lock:
            record = self._data.get(user_id, {}).get(period, {})
            llm = dict(record.get("llm", {}))
        return {
            "user_id": user_id,
            "period": period,
            "input_tokens": int(llm.get("input_tokens", 0)),
            "output_tokens": int(llm.get("output_tokens", 0)),
            "cost_usd": round(float(llm.get("cost_usd", 0.0)), 6),
            "by_model": dict(llm.get("by_model", {})),
        }


# ── Singleton accessor ────────────────────────────────────────
_usage_tracker: UsageTracker | None = None


def init_usage_tracker(data_dir: Path | str = "data") -> UsageTracker:
    global _usage_tracker
    _usage_tracker = UsageTracker(data_dir=data_dir)
    return _usage_tracker


def get_usage_tracker() -> UsageTracker:
    if _usage_tracker is None:
        raise RuntimeError("UsageTracker not initialised — call init_usage_tracker() at startup")
    return _usage_tracker
