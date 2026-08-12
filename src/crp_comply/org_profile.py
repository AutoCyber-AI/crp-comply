# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Per-tenant :class:`OrgProfile` persistence.

Counterpart to :mod:`crp_comply.contacts`. The :class:`ContactProfileStore`
holds notification *delivery* preferences (email / phone / webhook). This
module holds the structural compliance facts that every recipe-tailoring
call depends on:

* actor (provider / deployer / importer / distributor / authorised rep / GPAI)
* jurisdictions, EU establishment
* system category, Annex III row, GPAI flags
* data-modality flags (personal data, special categories, biometric, etc.)
* certification claims (ISO 42001 / 27001 / SOC 2)

Prior to this module the OrgProfile lived **only in the browser's
``localStorage``**, namespaced globally — so a fresh device / a new
seat / a privacy-mode window all rendered an empty profile and forced
the user back through Onboarding. That is the "onboarding resets every
sign-in" bug. With a tenant-scoped server file the profile is durable,
shared across devices, and survives a ``railway up`` redeploy thanks
to the attached ``/app/data`` volume (see ``railway.toml``).

Multi-tenant invariant
----------------------

The filename is derived from the tenant handle (Clerk ``org_id`` when
present, otherwise the user's own id — see
:func:`crp_comply.api.deps.get_current_tenant`). One Clerk organisation
shares one OrgProfile across every seat, which is the right model for
compliance: the *organisation* is the regulated entity, not any given
employee logging in.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from pathlib import Path
from typing import Any

from .persistent_json_store import JsonStore, get_json_store

log = logging.getLogger("crp_comply.org_profile")

# Same scheme as contacts.py / retention.py so ops recognise the
# layout. Anything that isn't word-safe collapses to underscore.
_TENANT_SAFE = re.compile(r"[^A-Za-z0-9._:@-]")


def _sanitize(tenant_id: str) -> str:
    return _TENANT_SAFE.sub("_", tenant_id.strip()) or "anonymous"


# ── Allowed fields ────────────────────────────────────────────
#
# Mirrors the OrgProfile interface in
# ``frontend/src/lib/profile.tsx``. Anything not in this set is
# dropped silently on write — callers cannot use the profile blob
# as a free-form k/v store, which would let a compromised browser
# inject keys that influence other endpoints.

_STR_FIELDS: frozenset[str] = frozenset(
    {
        "org_name",
        "actor",
        "system_category",
        "annex_iii_row",
    }
)

_BOOL_FIELDS: frozenset[str] = frozenset(
    {
        "established_in_eu",
        "is_high_risk",
        "is_gpai",
        "is_gpai_systemic",
        "processes_personal_data",
        "special_categories",
        "biometric",
        "is_chatbot",
        "synthetic_content",
        "emotion_recognition",
        "deepfake",
        "automated_decision_making",
        "children_users",
        "iso_42001_certified",
        "iso_27001_certified",
        "soc2_certified",
    }
)

_LIST_STR_FIELDS: frozenset[str] = frozenset({"jurisdictions"})

ALLOWED_FIELDS: frozenset[str] = _STR_FIELDS | _BOOL_FIELDS | _LIST_STR_FIELDS


def _coerce(profile: dict[str, Any]) -> dict[str, Any]:
    """Validate + coerce a raw payload to the canonical shape.

    Unknown keys are stripped, types are normalised, and empty
    values fall through to ``None`` so the JSON file stays compact.
    """
    out: dict[str, Any] = {}
    for k, v in (profile or {}).items():
        if k not in ALLOWED_FIELDS:
            continue
        if v is None:
            continue
        if k in _STR_FIELDS:
            s = str(v).strip()
            if s:
                out[k] = s
        elif k in _BOOL_FIELDS:
            out[k] = bool(v)
        elif k in _LIST_STR_FIELDS:
            if isinstance(v, list):
                cleaned = [str(x).strip() for x in v if str(x).strip()]
                if cleaned:
                    out[k] = cleaned
    return out


class OrgProfileStore:
    """Tenant-scoped OrgProfile store.

    All operations take the tenant handle explicitly. The store keeps
    a per-tenant lock-free model — concurrent writes within a single
    tenant are serialised through the global RLock; writes across
    tenants are independent on the backend (file or Redis).
    """

    def __init__(self, data_dir: Path | str | None = None, store: JsonStore | None = None) -> None:
        if store is not None:
            self._store = store
        else:
            self._store = get_json_store("org_profiles", data_dir)
        self._lock = threading.RLock()

    # ── public API ────────────────────────────────────────────

    def get(self, tenant_id: str) -> dict[str, Any] | None:
        """Return the stored profile dict or ``None`` if absent.

        Includes the ``onboarded_at`` / ``updated_at`` metadata so the
        client can tell "never onboarded" (``None``) from "onboarded
        with empty profile" (returned dict with ``onboarded_at`` set).
        """
        raw = self._store.get(_sanitize(tenant_id))
        if raw is None:
            return None
        # Strip the tenant metadata back out of the returned shape so
        # the client sees exactly what it sent on PUT, plus the
        # on-server timestamps. The tenant_id is *never* trusted from
        # the file — it's always the caller's authenticated tenant.
        raw.pop("tenant_id", None)
        return raw

    def put(self, tenant_id: str, profile: dict[str, Any]) -> dict[str, Any]:
        """Replace the stored profile with ``profile``.

        Unknown keys are dropped (see :data:`ALLOWED_FIELDS`).
        ``onboarded_at`` is set on first write and preserved on
        subsequent writes; ``updated_at`` is bumped every call.
        """
        cleaned = _coerce(profile)
        with self._lock:
            existing = self.get(tenant_id) or {}
            now = time.time()
            cleaned["onboarded_at"] = existing.get("onboarded_at") or now
            cleaned["updated_at"] = now
            payload = dict(cleaned)
            # Persist tenant_id alongside to make ad-hoc grep'ing the
            # data dir possible. Never trusted on read.
            payload["tenant_id"] = tenant_id
            self._store.set(_sanitize(tenant_id), payload)
            return cleaned

    def patch(self, tenant_id: str, changes: dict[str, Any]) -> dict[str, Any]:
        """Merge ``changes`` into the stored profile and persist."""
        with self._lock:
            current = self.get(tenant_id) or {}
            # Drop server-managed fields from the merge surface so a
            # client cannot fabricate ``onboarded_at`` to pretend it
            # finished onboarding earlier than it did.
            current.pop("onboarded_at", None)
            current.pop("updated_at", None)
            merged = {**current, **(changes or {})}
            return self.put(tenant_id, merged)

    def delete(self, tenant_id: str) -> bool:
        """Remove the stored profile. Returns True iff a file existed."""
        with self._lock:
            return self._store.delete(_sanitize(tenant_id))


# ── Process-wide singleton (wired from app.py lifespan) ────────

_store: OrgProfileStore | None = None


def init_org_profile_store(data_dir: Path | str | None = None) -> OrgProfileStore:
    """Initialise the process-wide store (called from app startup)."""
    global _store
    _store = OrgProfileStore(data_dir=data_dir)
    return _store


def get_org_profile_store() -> OrgProfileStore:
    if _store is None:
        raise RuntimeError("OrgProfileStore not initialised — call init_org_profile_store() first")
    return _store


__all__ = [
    "ALLOWED_FIELDS",
    "OrgProfileStore",
    "get_org_profile_store",
    "init_org_profile_store",
]
