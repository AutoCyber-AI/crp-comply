# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tenant-configurable retention windows — addresses PRODUCT_SECURITY.md §4 gap #5.

Replaces the hard-coded ``REPORT_RETENTION_DAYS=180`` /
``EVIDENCE_RETENTION_DAYS=365`` with a per-tenant configuration read from
``{data_dir}/retention/{user_id}.json``. Falls back to env-var defaults
when a tenant has no explicit policy.

Retention policies are bounded:

* ``reports_days``    30 ≤ days ≤ 3650 (10 years)
* ``evidence_days``   90 ≤ days ≤ 3650
* ``traces_days``     7  ≤ days ≤ 365

Users on Free tier cannot extend beyond the defaults. Enterprise tier may
request a custom bound (handled by support ticket, not this module).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .auth import Tier

log = logging.getLogger("crp_comply.api.retention")


DEFAULT_REPORTS_DAYS = int(os.getenv("CRP_COMPLY_REPORT_RETENTION_DAYS", "180"))
DEFAULT_EVIDENCE_DAYS = int(os.getenv("CRP_COMPLY_EVIDENCE_RETENTION_DAYS", "365"))
DEFAULT_TRACE_DAYS = int(os.getenv("CRP_COMPLY_TRACE_RETENTION_DAYS", "90"))


_BOUNDS = {
    "reports_days": (30, 3650),
    "evidence_days": (90, 3650),
    "traces_days": (7, 365),
}


# Free tier is capped at defaults — no upward adjustment.
_FREE_MAX = {
    "reports_days": DEFAULT_REPORTS_DAYS,
    "evidence_days": DEFAULT_EVIDENCE_DAYS,
    "traces_days": DEFAULT_TRACE_DAYS,
}


@dataclass
class RetentionPolicy:
    user_id: str
    reports_days: int = DEFAULT_REPORTS_DAYS
    evidence_days: int = DEFAULT_EVIDENCE_DAYS
    traces_days: int = DEFAULT_TRACE_DAYS
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RetentionStore:
    """File-backed per-user retention policies."""

    def __init__(self, data_dir: Path) -> None:
        self._dir = Path(data_dir) / "retention"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, user_id: str) -> Path:
        safe = "".join(c for c in user_id if c.isalnum() or c in "-_.")
        return self._dir / f"{safe}.json"

    def get(self, user_id: str) -> RetentionPolicy:
        p = self._path(user_id)
        if not p.exists():
            return RetentionPolicy(user_id=user_id)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return RetentionPolicy(**data)
        except Exception as exc:
            log.warning("bad retention file %s: %s; using defaults", p, exc)
            return RetentionPolicy(user_id=user_id)

    def set(
        self,
        user_id: str,
        tier: Tier,
        *,
        reports_days: int | None = None,
        evidence_days: int | None = None,
        traces_days: int | None = None,
    ) -> RetentionPolicy:
        """Update a user's policy. Raises ``ValueError`` on out-of-bound."""
        current = self.get(user_id)
        updates = {
            "reports_days": reports_days,
            "evidence_days": evidence_days,
            "traces_days": traces_days,
        }
        for field_name, value in updates.items():
            if value is None:
                continue
            lo, hi = _BOUNDS[field_name]
            if not (lo <= value <= hi):
                raise ValueError(f"{field_name}={value} out of bounds [{lo}, {hi}]")
            if tier == Tier.FREE and value > _FREE_MAX[field_name]:
                raise ValueError(
                    f"{field_name}={value} exceeds free-tier cap "
                    f"{_FREE_MAX[field_name]}; upgrade plan to extend"
                )
            setattr(current, field_name, value)
        current.updated_at = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._path(user_id).write_text(json.dumps(asdict(current), indent=2), encoding="utf-8")
        return current


# Module-level singleton
_store: RetentionStore | None = None


def init_retention_store(data_dir: Path) -> None:
    global _store
    _store = RetentionStore(data_dir)


def get_retention_store() -> RetentionStore:
    if _store is None:
        raise RuntimeError("RetentionStore not initialised")
    return _store
