# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Per-tenant :class:`UserContactProfile` persistence.

The notification dispatcher consults a ``UserContactProfile`` before
every send to decide where to ring. Prior to this module the profile
had to be rebuilt from request bodies on every call — which meant the
recipe-run notification hook could only reach the user when the caller
remembered to attach an ``email`` / ``phone`` / ``webhook_url`` in the
request. That's fragile and leaks responsibility into every endpoint.

This store persists the profile once per tenant (``{data_dir}/contacts/
{sanitized_tenant_id}.json``) and lets every downstream surface (recipe
notifier, scheduler reminders, future agent-raised clarifications) look
it up by tenant id alone.

Multi-tenant invariant
----------------------

The filename is derived from the tenant handle, not the user id, so:

* A Clerk organisation with multiple seats shares a single contact
  profile (the org DPO, the org AI-officer, etc.).
* Solo-tenant deployments (tenant == user) still get a per-user file
  and are unaffected.

Every read / write is tenant-scoped; there is no cross-tenant lookup
surface on this module.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Any

from .notifications import UserContactProfile

log = logging.getLogger("crp_comply.contacts")


_TENANT_SAFE = re.compile(r"[^A-Za-z0-9._:@-]")


def _sanitize(tenant_id: str) -> str:
    """Map a tenant handle to a filesystem-safe filename.

    Reuses the same scheme as ``retention.py`` so ops who grep one
    directory layout recognise the other. Collisions are avoided by
    keeping the full sanitised string rather than truncating.
    """
    return _TENANT_SAFE.sub("_", tenant_id.strip()) or "anonymous"


class ContactProfileStore:
    """Tenant-scoped :class:`UserContactProfile` store.

    All operations take the tenant handle explicitly — there is no
    ``current user`` concept here. Endpoints that consume the store
    must obtain the tenant via :func:`crp_comply.api.deps.get_current_tenant`.
    """

    def __init__(self, data_dir: Path | str) -> None:
        self._dir = Path(data_dir) / "contacts"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    # ── path helpers ───────────────────────────────────────────

    def _path(self, tenant_id: str) -> Path:
        return self._dir / f"{_sanitize(tenant_id)}.json"

    # ── public API ─────────────────────────────────────────────

    def get(self, tenant_id: str) -> UserContactProfile | None:
        """Return the stored profile or ``None`` if the tenant has none."""
        p = self._path(tenant_id)
        if not p.exists():
            return None
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("contact profile unreadable for tenant=%s: %s", tenant_id, exc)
            return None
        if not isinstance(raw, dict):
            return None
        # Force the stored user_id to equal the tenant we loaded under —
        # the file is authoritative only for that tenant. This prevents
        # a corrupted / hand-edited file from leaking another tenant's
        # handle back into the notification envelope.
        raw["user_id"] = tenant_id
        return UserContactProfile(
            user_id=tenant_id,
            email=str(raw.get("email") or ""),
            full_name=str(raw.get("full_name") or ""),
            phone_e164=str(raw.get("phone_e164") or ""),
            preferred_channel=str(raw.get("preferred_channel") or "in_app"),
            timezone=str(raw.get("timezone") or "UTC"),
            language=str(raw.get("language") or "en-GB"),
            named_roles=dict(raw.get("named_roles") or {}),
            webhook_url=str(raw.get("webhook_url") or ""),
            quiet_hours=dict(raw.get("quiet_hours") or {}),
        )

    def get_or_default(self, tenant_id: str) -> UserContactProfile:
        """Return the stored profile or a blank stub for this tenant."""
        return self.get(tenant_id) or UserContactProfile(user_id=tenant_id, email="")

    def put(self, tenant_id: str, profile: UserContactProfile) -> UserContactProfile:
        """Persist ``profile`` under ``tenant_id``.

        The tenant handle overrides whatever ``profile.user_id`` carries
        — callers cannot smuggle a different tenant into the write.
        """
        with self._lock:
            safe = UserContactProfile(
                user_id=tenant_id,
                email=profile.email,
                full_name=profile.full_name,
                phone_e164=profile.phone_e164,
                preferred_channel=profile.preferred_channel,
                timezone=profile.timezone,
                language=profile.language,
                named_roles=dict(profile.named_roles),
                webhook_url=profile.webhook_url,
                quiet_hours=dict(profile.quiet_hours),
            )
            p = self._path(tenant_id)
            p.write_text(
                json.dumps(safe.to_dict(), indent=2, sort_keys=True),
                encoding="utf-8",
            )
            return safe

    def update(self, tenant_id: str, changes: dict[str, Any]) -> UserContactProfile:
        """Merge ``changes`` into the stored profile and persist.

        Unknown keys are dropped silently so API callers can't inject
        arbitrary attributes into the serialised file.
        """
        current = self.get_or_default(tenant_id)
        allowed = {
            "email",
            "full_name",
            "phone_e164",
            "preferred_channel",
            "timezone",
            "language",
            "webhook_url",
        }
        dict_allowed = {"named_roles", "quiet_hours"}
        for k, v in (changes or {}).items():
            if k in allowed and v is not None:
                setattr(current, k, str(v))
            elif k in dict_allowed and isinstance(v, dict):
                setattr(current, k, {str(kk): str(vv) for kk, vv in v.items()})
        return self.put(tenant_id, current)

    def delete(self, tenant_id: str) -> bool:
        """Remove the stored profile. Returns True iff a file existed."""
        with self._lock:
            p = self._path(tenant_id)
            if p.exists():
                p.unlink()
                return True
            return False


# ── Process-wide singleton (wired from app.py lifespan) ────────


_store: ContactProfileStore | None = None


def init_contact_store(data_dir: Path | str) -> ContactProfileStore:
    """Initialise the process-wide store (called from app startup)."""
    global _store
    _store = ContactProfileStore(data_dir=data_dir)
    return _store


def get_contact_store() -> ContactProfileStore:
    if _store is None:
        raise RuntimeError("ContactProfileStore not initialised — call init_contact_store() first")
    return _store


__all__ = [
    "ContactProfileStore",
    "get_contact_store",
    "init_contact_store",
]
