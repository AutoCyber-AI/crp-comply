# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Per-tenant organisation profile endpoints.

Backs the frontend Onboarding wizard / ``useProfile()`` hook.

* ``GET    /me/org-profile``   → load (404 when never onboarded)
* ``PUT    /me/org-profile``   → replace (used on Onboarding finish)
* ``PATCH  /me/org-profile``   → partial update (Settings tweaks)
* ``DELETE /me/org-profile``   → reset (re-trigger onboarding)

All four require an authenticated caller; anonymous traffic gets a
401 because the OrgProfile is the structural input that drives every
recipe-tailoring call and must be tenant-scoped to be safe.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..org_profile import ALLOWED_FIELDS, get_org_profile_store
from .deps import get_current_tenant, get_current_user

log = logging.getLogger("crp_comply.api.org_profile")

router = APIRouter(prefix="/me/org-profile", tags=["self-service"])


def _require_authenticated(user_id: str) -> None:
    if user_id == "anonymous":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in to manage your organisation profile.",
        )


class OrgProfilePayload(BaseModel):
    """Free-form payload — the store enforces the actual schema.

    We intentionally don't enumerate every field here so adding a new
    onboarding question doesn't require an API redeploy. Validation
    + coercion lives in :mod:`crp_comply.org_profile`.
    """

    model_config = {"extra": "allow"}


class OrgProfileResponse(BaseModel):
    """Server-authoritative profile shape returned to the client.

    Mirrors :data:`crp_comply.org_profile.ALLOWED_FIELDS` plus the
    timestamps. The frontend treats ``onboarded_at`` as the canonical
    "is this user onboarded?" signal — non-null means yes, regardless
    of which structural fields are populated.
    """

    org_name: str | None = None
    actor: str | None = None
    jurisdictions: list[str] | None = None
    established_in_eu: bool | None = None
    system_category: str | None = None
    annex_iii_row: str | None = None
    is_high_risk: bool | None = None
    is_gpai: bool | None = None
    is_gpai_systemic: bool | None = None
    processes_personal_data: bool | None = None
    special_categories: bool | None = None
    biometric: bool | None = None
    is_chatbot: bool | None = None
    synthetic_content: bool | None = None
    emotion_recognition: bool | None = None
    deepfake: bool | None = None
    automated_decision_making: bool | None = None
    children_users: bool | None = None
    iso_42001_certified: bool | None = None
    iso_27001_certified: bool | None = None
    soc2_certified: bool | None = None
    onboarded_at: float | None = None
    updated_at: float | None = None
    is_onboarded: bool = Field(
        default=False,
        description="True once the tenant has completed onboarding at "
        "least once. Drives the frontend's `/app/onboard` redirect.",
    )


def _to_response(profile: dict[str, Any] | None) -> OrgProfileResponse:
    if profile is None:
        return OrgProfileResponse(is_onboarded=False)
    payload = {
        k: v
        for k, v in profile.items()
        if k in ALLOWED_FIELDS or k in {"onboarded_at", "updated_at"}
    }
    payload["is_onboarded"] = bool(profile.get("onboarded_at"))
    return OrgProfileResponse(**payload)


@router.get("", response_model=OrgProfileResponse)
def get_org_profile(
    user_id: Annotated[str, Depends(get_current_user)],
    tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> OrgProfileResponse:
    """Return the stored profile or an empty stub when never onboarded.

    The client uses ``is_onboarded`` to decide whether to push the
    user through ``/app/onboard``; an empty stub (``is_onboarded:
    false``) is the "you are signed in but haven't onboarded yet"
    state and is **not** an error.
    """
    _require_authenticated(user_id)
    profile = get_org_profile_store().get(tenant_id)
    return _to_response(profile)


@router.put("", response_model=OrgProfileResponse)
def put_org_profile(
    body: OrgProfilePayload,
    user_id: Annotated[str, Depends(get_current_user)],
    tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> OrgProfileResponse:
    """Replace the stored profile (Onboarding "Finish" calls this)."""
    _require_authenticated(user_id)
    raw = body.model_dump(exclude_unset=False)
    saved = get_org_profile_store().put(tenant_id, raw)
    log.info(
        "org profile saved tenant=%s actor=%s jurisdictions=%s",
        tenant_id,
        saved.get("actor"),
        saved.get("jurisdictions"),
    )
    return _to_response(saved)


@router.patch("", response_model=OrgProfileResponse)
def patch_org_profile(
    body: OrgProfilePayload,
    user_id: Annotated[str, Depends(get_current_user)],
    tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> OrgProfileResponse:
    """Partial update — used by Settings to flip a single flag."""
    _require_authenticated(user_id)
    raw = body.model_dump(exclude_unset=True)
    saved = get_org_profile_store().patch(tenant_id, raw)
    return _to_response(saved)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_org_profile(
    user_id: Annotated[str, Depends(get_current_user)],
    tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> None:
    """Reset onboarding state (e.g. "I changed roles, start over")."""
    _require_authenticated(user_id)
    get_org_profile_store().delete(tenant_id)
