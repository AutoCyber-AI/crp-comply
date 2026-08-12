# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Public well-known + tenant retention endpoints.

Includes:

* ``GET  /.well-known/crp-comply-evidence-key.pub`` — published ed25519
  public key used to sign evidence-pack manifests. Anyone in the supply
  chain (customers, regulators, auditors) can fetch this and verify
  packs without a shared secret. Addresses PRODUCT_SECURITY.md §4 gap #4.

* ``GET  /settings/retention``   — read the caller's retention policy.
* ``PUT  /settings/retention``   — update it (tenant-configurable windows
  per PRODUCT_SECURITY.md §4 gap #5).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from .auth import Tier
from .deps import get_current_tier, get_current_user
from .retention import get_retention_store

logger = logging.getLogger("crp_comply.api.well_known")

well_known_router = APIRouter(tags=["well-known"])
settings_router = APIRouter(prefix="/settings", tags=["settings"])


# ─────────────────────────────────────────────────────────────
# /.well-known
# ─────────────────────────────────────────────────────────────


@well_known_router.get("/.well-known/crp-comply-evidence-key.pub")
async def get_evidence_public_key(request: Request) -> dict:
    """Return the published evidence-pack signing public key.

    The value is stable across restarts (persisted at
    ``{data_dir}/reports/.keys/``) and rotates only via a deliberate
    operator action.
    """
    from . import evidence_signing as _es

    data_dir = Path(os.environ.get("CRP_COMPLY_DATA_DIR", "data")) / "reports"
    return _es.export_public_key(data_dir)


# ─────────────────────────────────────────────────────────────
# Retention policy
# ─────────────────────────────────────────────────────────────


class RetentionResponse(BaseModel):
    user_id: str
    reports_days: int
    evidence_days: int
    traces_days: int
    updated_at: str
    bounds: dict[str, tuple[int, int]] = Field(
        default_factory=lambda: {
            "reports_days": (30, 3650),
            "evidence_days": (90, 3650),
            "traces_days": (7, 365),
        }
    )


class RetentionUpdateRequest(BaseModel):
    reports_days: int | None = Field(None, ge=30, le=3650)
    evidence_days: int | None = Field(None, ge=90, le=3650)
    traces_days: int | None = Field(None, ge=7, le=365)


def _as_response(policy) -> RetentionResponse:
    return RetentionResponse(
        user_id=policy.user_id,
        reports_days=policy.reports_days,
        evidence_days=policy.evidence_days,
        traces_days=policy.traces_days,
        updated_at=policy.updated_at,
    )


@settings_router.get("/retention", response_model=RetentionResponse)
async def get_retention(user_id: str = Depends(get_current_user)):
    return _as_response(get_retention_store().get(user_id))


@settings_router.put("/retention", response_model=RetentionResponse)
async def set_retention(
    req: RetentionUpdateRequest,
    user_id: str = Depends(get_current_user),
    tier: Tier = Depends(get_current_tier),
):
    try:
        policy = get_retention_store().set(
            user_id,
            tier,
            reports_days=req.reports_days,
            evidence_days=req.evidence_days,
            traces_days=req.traces_days,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return _as_response(policy)
