# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Durable per-user preference profile for the compliance agent.

Phase 5a adds learned defaults so the agent remembers how the user likes
to receive answers (depth, format, audience, trusted sources) without
turning the profile into a black box. Profiles are per-user with an
optional org-level default fallback.

Persistence mirrors the file-based pattern used by OrgProfile and
contacts: ``data/user_preferences/{tenant_id}/{user_id}.json``. On
single-volume deployments this survives redeploys; the eventual Postgres
migration is purely a storage swap.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .user_need import UserNeed

log = logging.getLogger("crp_comply.agent.preferences")

_USER_SAFE = re.compile(r"[^A-Za-z0-9._-]")


def _sanitize(value: str) -> str:
    return _USER_SAFE.sub("_", value.strip()) or "anonymous"


@dataclass
class UserPreferenceProfile:
    """Learned user preferences and explicit overrides.

    All string fields use the same vocabulary as :class:`UserNeed`
    (``depth`` ∈ {brief, standard, thorough}, ``format`` ∈ prose etc.)
    so the planner can overlay them with a single mapping.
    """

    tenant_id: str
    user_id: str
    preferred_depth: str = "standard"
    preferred_format: str = "prose"
    preferred_audience: str = "unknown"
    preferred_regulations: list[str] = field(default_factory=list)
    trusted_source_domains: list[str] = field(default_factory=list)
    satisfaction_criteria: list[str] = field(default_factory=list)
    preferred_autonomy: str = "autonomous_with_checkpoints"
    feedback_summary: dict[str, Any] = field(default_factory=dict)
    explicit_feedback_count: int = 0
    implicit_signal_count: int = 0
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.updated_at:
            self.updated_at = _now_iso()
        self.preferred_depth = _valid_depth(self.preferred_depth)
        self.preferred_format = _valid_format(self.preferred_format)
        self.preferred_audience = _valid_audience(self.preferred_audience)
        self.preferred_autonomy = _valid_autonomy(self.preferred_autonomy)
        self.preferred_regulations = _unique_str_list(self.preferred_regulations)
        self.trusted_source_domains = _unique_str_list(self.trusted_source_domains)
        self.satisfaction_criteria = _unique_str_list(self.satisfaction_criteria)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "preferred_depth": self.preferred_depth,
            "preferred_format": self.preferred_format,
            "preferred_audience": self.preferred_audience,
            "preferred_regulations": list(self.preferred_regulations),
            "trusted_source_domains": list(self.trusted_source_domains),
            "satisfaction_criteria": list(self.satisfaction_criteria),
            "preferred_autonomy": self.preferred_autonomy,
            "feedback_summary": dict(self.feedback_summary),
            "explicit_feedback_count": self.explicit_feedback_count,
            "implicit_signal_count": self.implicit_signal_count,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "UserPreferenceProfile":
        return cls(
            tenant_id=str(raw.get("tenant_id") or ""),
            user_id=str(raw.get("user_id") or ""),
            preferred_depth=str(raw.get("preferred_depth") or "standard"),
            preferred_format=str(raw.get("preferred_format") or "prose"),
            preferred_audience=str(raw.get("preferred_audience") or "unknown"),
            preferred_regulations=_unique_str_list(raw.get("preferred_regulations")),
            trusted_source_domains=_unique_str_list(raw.get("trusted_source_domains")),
            satisfaction_criteria=_unique_str_list(raw.get("satisfaction_criteria")),
            preferred_autonomy=_valid_autonomy(raw.get("preferred_autonomy")),
            feedback_summary=dict(raw.get("feedback_summary") or {}),
            explicit_feedback_count=int(raw.get("explicit_feedback_count") or 0),
            implicit_signal_count=int(raw.get("implicit_signal_count") or 0),
            updated_at=str(raw.get("updated_at") or _now_iso()),
        )

    def apply_to_user_need(self, need: UserNeed, *, explicit_only: bool = False) -> UserNeed:
        """Fill in missing UserNeed slots from learned preferences.

        Only writes to a slot when the NLU did not produce an explicit value
        (i.e. the value is still at its default). This preserves user autonomy
        — an explicit “briefly” always beats a learned preference for thorough.
        """
        if need.depth in ("", "standard") and self.preferred_depth:
            need.depth = self.preferred_depth
        if need.format in ("", "prose") and self.preferred_format:
            need.format = self.preferred_format
        if need.audience in ("", "unknown") and self.preferred_audience:
            need.audience = self.preferred_audience
        if not need.regulation and self.preferred_regulations:
            need.regulation = self.preferred_regulations[0]
        if self.satisfaction_criteria and not need.satisfaction_criteria:
            need.satisfaction_criteria = list(self.satisfaction_criteria)
        if not explicit_only:
            need.raw_slots.setdefault("preferred_regulations", list(self.preferred_regulations))
            need.raw_slots.setdefault("trusted_source_domains", list(self.trusted_source_domains))
        return need

    def system_prompt_footnote(self) -> str:
        """One-line nudge that lets the user override a learned default."""
        prefs: list[str] = []
        if self.preferred_depth != "standard":
            prefs.append(f"{self.preferred_depth} answers")
        if self.preferred_format != "prose":
            prefs.append(f"{self.preferred_format} format")
        if self.preferred_audience != "unknown":
            prefs.append(f"for a {self.preferred_audience} audience")
        if not prefs:
            return ""
        return f"You usually prefer {', '.join(prefs)}. Say 'briefly' or 'in detail' to override."


class PreferenceStore:
    """File-backed persistence for :class:`UserPreferenceProfile`."""

    def __init__(self, data_dir: Path | str | None = None) -> None:
        self._root = Path(data_dir or os.environ.get("CRP_COMPLY_DATA_DIR", "data"))
        self._lock = threading.RLock()

    def _path(self, tenant_id: str, user_id: str) -> Path:
        t = _sanitize(tenant_id or user_id or "anonymous")
        u = _sanitize(user_id or "anonymous")
        d = self._root / "user_preferences" / t
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{u}.json"

    def load(self, tenant_id: str, user_id: str) -> UserPreferenceProfile:
        with self._lock:
            p = self._path(tenant_id, user_id)
            if p.exists():
                try:
                    raw = json.loads(p.read_text(encoding="utf-8"))
                    raw["tenant_id"] = tenant_id
                    raw["user_id"] = user_id
                    return UserPreferenceProfile.from_dict(raw)
                except Exception:  # pragma: no cover — corrupt file, start fresh
                    log.warning("failed to read preference file %s", p, exc_info=True)
            return UserPreferenceProfile(tenant_id=tenant_id, user_id=user_id)

    def save(self, profile: UserPreferenceProfile) -> None:
        with self._lock:
            profile.updated_at = _now_iso()
            p = self._path(profile.tenant_id, profile.user_id)
            p.write_text(
                json.dumps(profile.to_dict(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

    def list_users(self, tenant_id: str) -> list[str]:
        with self._lock:
            d = self._root / "user_preferences" / _sanitize(tenant_id or "anonymous")
            if not d.exists():
                return []
            return sorted([p.stem for p in d.glob("*.json") if p.is_file()])

    def reset(self, tenant_id: str, user_id: str) -> UserPreferenceProfile:
        with self._lock:
            fresh = UserPreferenceProfile(tenant_id=tenant_id, user_id=user_id)
            self.save(fresh)
            return fresh


# Module-level singleton so API routes can call ``get_preference_store()``.
_store: PreferenceStore | None = None
_store_lock = threading.Lock()


def get_preference_store(data_dir: Path | str | None = None) -> PreferenceStore:
    global _store
    with _store_lock:
        if _store is None or data_dir is not None:
            _store = PreferenceStore(data_dir)
        return _store


def set_preference_store(store: PreferenceStore) -> None:
    global _store
    with _store_lock:
        _store = store


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _valid_depth(v: str) -> str:
    return v if v in {"brief", "standard", "thorough"} else "standard"


def _valid_format(v: str) -> str:
    return (
        v
        if v in {"summary", "checklist", "report", "citation_list", "decision_tree", "prose"}
        else "prose"
    )


def _valid_audience(v: str) -> str:
    return v if v in {"executive", "legal", "engineer", "auditor", "unknown"} else "unknown"


def _valid_autonomy(v: Any) -> str:
    return (
        v
        if v in {"suggest", "draft", "autonomous_with_checkpoints", "full"}
        else "autonomous_with_checkpoints"
    )


def _unique_str_list(v: Any) -> list[str]:
    if not v:
        return []
    if isinstance(v, str):
        v = [v]
    seen: set[str] = set()
    out: list[str] = []
    for x in v:
        s = str(x).strip().lower()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


__all__ = [
    "PreferenceStore",
    "UserPreferenceProfile",
    "get_preference_store",
    "set_preference_store",
]
