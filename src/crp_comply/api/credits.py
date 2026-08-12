# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Per-user prepaid credit balance — Stripe one-time top-ups.

When a user buys a credit pack (`payment_intent.succeeded` for one of
the `STRIPE_COMPLY_CREDITS_*_PRICE_ID` SKUs), the webhook calls
:func:`grant_usd` to bump the user's ``credit_balance_usd`` field.

Overage calls (above tier monthly quota) decrement the balance via
:func:`charge_usd`. When the balance hits 0, ``check_balance`` returns
``False`` and the API can offer the user a top-up modal or a switch
to local mode.

The store is a single JSON file under ``$DATA_DIR/credits.json`` so it
participates in the existing nightly backup and per-user restore.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("crp_comply.credits")


def _data_dir() -> Path:
    raw = os.environ.get("CRP_COMPLY_DATA_DIR", "data")
    p = Path(raw)
    p.mkdir(parents=True, exist_ok=True)
    return p


class CreditStore:
    """File-backed per-user credit balance.

    Storage layout (data/credits.json):
        {
            "<user_id>": {
                "balance_usd": float,
                "lifetime_usd": float,
                "history": [
                    {"ts": "...", "delta_usd": 5.0, "reason": "stripe:<YOUR_STRIPE_PRICE_ID>"},
                    {"ts": "...", "delta_usd": -0.04, "reason": "overage:draft"}
                ]
            }
        }
    """

    def __init__(self, data_dir: Path | str | None = None) -> None:
        self._dir = Path(data_dir) if data_dir is not None else _data_dir()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / "credits.json"
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, Any]] = {}
        self._load()

    # ── persistence ───────────────────────────────────────────
    def _load(self) -> None:
        if not self._file.exists():
            return
        try:
            self._data = json.loads(self._file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not load credits.json (%s); starting fresh", exc)
            self._data = {}

    def _save_unlocked(self) -> None:
        try:
            self._file.write_text(json.dumps(self._data, indent=2, default=str), encoding="utf-8")
        except OSError as exc:
            logger.error("Failed to persist credits: %s", exc)

    # ── public API ────────────────────────────────────────────
    def get_balance(self, user_id: str) -> dict[str, Any]:
        with self._lock:
            rec = self._data.get(user_id, {})
            return {
                "user_id": user_id,
                "balance_usd": float(rec.get("balance_usd", 0.0)),
                "lifetime_usd": float(rec.get("lifetime_usd", 0.0)),
            }

    def grant_usd(self, user_id: str, usd: float, reason: str) -> dict[str, Any]:
        """Add ``usd`` to the user's balance. Idempotency is the caller's job."""
        return self.grant_usd_idempotent(user_id, usd, reason, event_id=None)

    def grant_usd_idempotent(
        self, user_id: str, usd: float, reason: str, event_id: str | None = None
    ) -> dict[str, Any]:
        """Add ``usd`` to the user's balance, optionally deduplicating by event_id.

        When ``event_id`` is provided the grant is recorded against that id so
        replaying the same Stripe webhook event does not double-credit the user.
        """
        if usd <= 0:
            raise ValueError(f"grant_usd must be positive, got {usd}")
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            rec = self._data.setdefault(
                user_id,
                {"balance_usd": 0.0, "lifetime_usd": 0.0, "history": [], "processed_events": []},
            )
            processed = set(rec.get("processed_events", []))
            if event_id and event_id in processed:
                logger.info("credit grant idempotency skip: user=%s event=%s", user_id, event_id)
                return self.get_balance(user_id)
            rec["balance_usd"] = float(rec.get("balance_usd", 0.0)) + usd
            rec["lifetime_usd"] = float(rec.get("lifetime_usd", 0.0)) + usd
            rec.setdefault("history", []).append(
                {"ts": now, "delta_usd": float(usd), "reason": reason}
            )
            if event_id:
                processed.add(event_id)
                rec["processed_events"] = list(processed)
            self._save_unlocked()
            return self.get_balance(user_id)

    def charge_usd(self, user_id: str, usd: float, reason: str) -> tuple[bool, dict[str, Any]]:
        """Decrement balance. Returns (success, new_balance).

        Fails fast (returns False) if the balance would go negative — the
        caller is expected to react with a 402 or a switch-to-local prompt.
        """
        if usd <= 0:
            raise ValueError(f"charge_usd must be positive, got {usd}")
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            rec = self._data.setdefault(
                user_id,
                {"balance_usd": 0.0, "lifetime_usd": 0.0, "history": []},
            )
            current = float(rec.get("balance_usd", 0.0))
            if current < usd:
                return False, self.get_balance(user_id)
            rec["balance_usd"] = current - usd
            rec.setdefault("history", []).append(
                {"ts": now, "delta_usd": -float(usd), "reason": reason}
            )
            self._save_unlocked()
        return True, self.get_balance(user_id)

    def history(self, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rec = self._data.get(user_id, {})
            return list(rec.get("history", []))[-int(limit) :]

    def ensure_welcome_bonus(self, user_id: str, usd: float | None = None) -> bool:
        """Grant a one-time welcome credit to a brand-new user.

        Used to back the "100 free hosted-LLM calls, no key required"
        platform-trial offer. Returns True iff we actually granted (i.e.
        first time we have ever seen this user). Idempotent.

        ``CRP_COMPLY_WELCOME_BONUS_USD`` overrides the default ($5 == 100
        overage calls at the default $0.05/call).
        """
        if usd is None:
            try:
                usd = float(os.environ.get("CRP_COMPLY_WELCOME_BONUS_USD", "5.0"))
            except ValueError:
                usd = 5.0
        if usd <= 0:
            return False
        with self._lock:
            rec = self._data.get(user_id)
            if rec is not None and rec.get("welcome_bonus_granted"):
                return False
            now = datetime.now(timezone.utc).isoformat()
            rec = self._data.setdefault(
                user_id,
                {"balance_usd": 0.0, "lifetime_usd": 0.0, "history": []},
            )
            if rec.get("welcome_bonus_granted"):
                return False
            rec["balance_usd"] = float(rec.get("balance_usd", 0.0)) + usd
            rec["lifetime_usd"] = float(rec.get("lifetime_usd", 0.0)) + usd
            rec["welcome_bonus_granted"] = True
            rec.setdefault("history", []).append(
                {"ts": now, "delta_usd": float(usd), "reason": "welcome_bonus"}
            )
            self._save_unlocked()
        logger.info("welcome bonus granted to %s (+$%.2f)", user_id, usd)
        return True


# ── Singleton accessor ─────────────────────────────────────────
_store: CreditStore | None = None
_singleton_lock = threading.Lock()


def get_credit_store() -> CreditStore:
    global _store
    with _singleton_lock:
        if _store is None:
            _store = CreditStore()
        return _store


def reset_credit_store_for_tests() -> None:
    """Drop the in-memory singleton (test isolation)."""
    global _store
    with _singleton_lock:
        _store = None


__all__ = ["CreditStore", "get_credit_store", "reset_credit_store_for_tests"]
