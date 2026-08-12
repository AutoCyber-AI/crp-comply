# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""One-click evidence sharing with tenant-scoped, expiring share links.

Shares are persisted via :func:`crp_comply.persistent_json_store.get_json_store`
under the logical store name ``shares``. A share record is keyed by ``share_id``;
the ``/shares`` list endpoint loads all share records and filters by the caller's
``tenant_id`` so cross-tenant leakage is impossible.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from ..persistent_json_store import JsonStore, get_json_store
from .deps import get_current_tenant, get_current_user
from .rbac import WorkspaceRole, require_role

logger = logging.getLogger("crp_comply.api.sharing")

router = APIRouter(tags=["shares"])

ResourceType = Literal["report", "pack"]
_DEFAULT_EXPIRES_DAYS = 7
_SHARE_KEY_PREFIX = "share:"

_store: JsonStore | None = None


def _get_store() -> JsonStore:
    """Lazy singleton for the shares JSON store."""
    global _store
    if _store is None:
        _store = get_json_store("shares")
    return _store


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _share_key(share_id: str) -> str:
    """Namespaced key for a single share record."""
    return f"{_SHARE_KEY_PREFIX}{share_id}"


def _new_share_id() -> str:
    return str(uuid.uuid4())


class CreateShareRequest(BaseModel):
    """Request body for creating a share link."""

    report_id: str | None = None
    pack_id: str | None = None
    recipient_email: str | None = None
    expires_in_days: int = Field(default=_DEFAULT_EXPIRES_DAYS, ge=1, le=365)

    @field_validator("report_id", "pack_id")
    @classmethod
    def _strip_optional(cls, v: str | None) -> str | None:
        return v.strip() if v else v

    @field_validator("recipient_email")
    @classmethod
    def _strip_email(cls, v: str | None) -> str | None:
        return v.strip() if v else v


class ShareRecord(BaseModel):
    """Stored share record."""

    share_id: str
    tenant_id: str
    created_by: str
    resource_type: ResourceType
    resource_id: str
    recipient_email: str | None
    created_at: str
    expires_at: str


def _now_iso() -> str:
    return _utc_now().isoformat()


def _resolve_resource_type_and_id(req: CreateShareRequest) -> tuple[ResourceType, str]:
    """Return (resource_type, resource_id) from the create request."""
    if req.report_id and req.pack_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide report_id or pack_id, not both",
        )
    if req.report_id:
        return "report", req.report_id
    if req.pack_id:
        return "pack", req.pack_id
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Provide report_id or pack_id",
    )


def _load_share(share_id: str) -> dict[str, Any] | None:
    return _get_store().get(_share_key(share_id))


def _save_share(record: dict[str, Any]) -> None:
    _get_store().set(_share_key(record["share_id"]), record)


def _list_tenant_shares(tenant_id: str) -> list[dict[str, Any]]:
    """Return all non-expired share records scoped to *tenant_id*."""
    store = _get_store()
    # FileJsonStore.list_keys matches the safe key stem; "share:" becomes "share_".
    keys = store.list_keys(_SHARE_KEY_PREFIX)
    shares: list[dict[str, Any]] = []
    for key in keys:
        raw = store.get(key)
        if not isinstance(raw, dict):
            continue
        if raw.get("tenant_id") != tenant_id:
            continue
        shares.append(raw)
    shares.sort(key=lambda s: s.get("created_at") or "", reverse=True)
    return shares


@router.post(
    "/shares",
    response_model=ShareRecord,
    status_code=status.HTTP_201_CREATED,
)
async def create_share(
    req: CreateShareRequest,
    user_id: str = Depends(get_current_user),
    tenant_id: str = Depends(get_current_tenant),
    _role: WorkspaceRole = Depends(require_role(WorkspaceRole.member)),
):
    """Create an expiring share link for a report or evidence pack."""
    resource_type, resource_id = _resolve_resource_type_and_id(req)
    now = _utc_now()
    record: dict[str, Any] = {
        "share_id": _new_share_id(),
        "tenant_id": tenant_id,
        "created_by": user_id,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "recipient_email": req.recipient_email,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(days=req.expires_in_days)).isoformat(),
    }
    _save_share(record)
    logger.info(
        "share created: share_id=%s tenant=%s user=%s type=%s resource=%s",
        record["share_id"],
        tenant_id,
        user_id,
        resource_type,
        resource_id,
    )
    return ShareRecord(**record)


@router.get("/shares")
async def list_shares(
    user_id: str = Depends(get_current_user),
    tenant_id: str = Depends(get_current_tenant),
):
    """List share links for the current tenant.

    Viewers and guests may list but cannot create or revoke shares.
    """
    if user_id == "anonymous":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sign in")
    return {"shares": _list_tenant_shares(tenant_id)}


@router.delete("/shares/{share_id}")
async def revoke_share(
    share_id: str,
    user_id: str = Depends(get_current_user),
    tenant_id: str = Depends(get_current_tenant),
    _role: WorkspaceRole = Depends(require_role(WorkspaceRole.member)),
):
    """Revoke a share link. Requires member, admin, or owner role."""
    raw = _load_share(share_id)
    if raw is None or raw.get("tenant_id") != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share not found")
    _get_store().delete(_share_key(share_id))
    logger.info("share revoked: share_id=%s tenant=%s user=%s", share_id, tenant_id, user_id)
    return {"revoked": True, "share_id": share_id}


@router.get("/shares/{share_id}/public")
async def get_shared_resource(share_id: str):
    """Public, unauthenticated fetch of a shared resource.

    Accessible to anyone with the link until ``expires_at``. Returns the
    report markdown or pack manifest as a JSON envelope.
    """
    raw = _load_share(share_id)
    if raw is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Share not found")

    try:
        expires = datetime.fromisoformat(raw["expires_at"])
    except Exception:
        expires = datetime.min.replace(tzinfo=timezone.utc)
    if _utc_now() > expires:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Share link has expired",
        )

    owner = raw["created_by"]
    resource_type = raw["resource_type"]
    resource_id = raw["resource_id"]

    try:
        if resource_type == "report":
            from .reports import get_report_store

            rec = get_report_store().get(owner, resource_id)
            if rec is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Report not found",
                )
            content = rec.get("markdown") or rec.get("payload") or {}
            system_name = rec.get("system_name") or "Report"
        else:
            from .reports import get_pack_builder

            manifest = get_pack_builder().get_manifest(owner, resource_id)
            if manifest is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Evidence pack not found",
                )
            content = manifest
            system_name = manifest.get("system_name") or "Evidence pack"
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Failed to load shared resource %s/%s: %s", resource_type, resource_id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to load shared resource",
        ) from exc

    return {
        "share_id": share_id,
        "resource_type": resource_type,
        "system_name": system_name,
        "expires_at": raw["expires_at"],
        "content": content,
    }
