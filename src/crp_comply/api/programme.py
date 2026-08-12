# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Programme-tracker API.

Surfaces the obligation lifecycle store so the frontend can render a
real "where am I in this regulatory programme?" view rather than a flat
list of static markdown reports. See ``COMPLIANCE_MODEL_GAPS.md`` Gap #5.

Endpoints
---------

``GET  /api/v1/programme``
    List every obligation lifecycle record for the caller, newest first.
``GET  /api/v1/programme/{obligation_id}``
    Fetch a single record, including its append-only history.
``POST /api/v1/programme/{obligation_id}/transition``
    Advance the obligation's state. Rejects illegal transitions with
    ``409 Conflict`` rather than silently corrupting the lifecycle.
``DELETE /api/v1/programme/{obligation_id}``
    Remove the record entirely (e.g. obligation no longer applies).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from ..programme import (
    InvalidTransition,
    LifecycleState,
    ObligationLifecycle,
    get_programme_store,
)
from .deps import get_current_user

logger = logging.getLogger("crp_comply.api.programme")

router = APIRouter(prefix="/programme", tags=["programme"])


# ── DTOs ─────────────────────────────────────────────────────


class LifecycleDTO(BaseModel):
    obligation_id: str
    user_id: str
    recipe_id: str
    system_name: str = ""
    state: str
    blockers: list[str] = Field(default_factory=list)
    last_evidence_observed_at: str | None = None
    derived_from_report_id: str | None = None
    created_at: str
    updated_at: str
    history: list[dict[str, Any]] = Field(default_factory=list)


def _to_dto(rec: ObligationLifecycle) -> LifecycleDTO:
    return LifecycleDTO(**rec.to_dict())


class TransitionRequest(BaseModel):
    new_state: str
    recipe_id: str = ""
    system_name: str = ""
    reason: str = ""
    blockers: list[str] | None = None
    derived_from_report_id: str | None = None
    observed_evidence: bool = False


# ── Endpoints ────────────────────────────────────────────────


@router.get("", response_model=list[LifecycleDTO], summary="List programme obligations")
async def list_programme(
    user_id: Annotated[str, Depends(get_current_user)],
) -> list[LifecycleDTO]:
    store = get_programme_store()
    return [_to_dto(r) for r in store.list(user_id)]


@router.get(
    "/{obligation_id}",
    response_model=LifecycleDTO,
    summary="Fetch a single obligation lifecycle record",
)
async def get_obligation(
    obligation_id: str,
    user_id: Annotated[str, Depends(get_current_user)],
) -> LifecycleDTO:
    rec = get_programme_store().get(user_id, obligation_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="obligation not found")
    return _to_dto(rec)


@router.post(
    "/{obligation_id}/transition",
    response_model=LifecycleDTO,
    summary="Advance an obligation's lifecycle state",
)
async def transition_obligation(
    obligation_id: str,
    req: TransitionRequest,
    user_id: Annotated[str, Depends(get_current_user)],
) -> LifecycleDTO:
    try:
        new_state = LifecycleState(req.new_state)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"unknown state: {req.new_state}",
        ) from exc
    try:
        rec = get_programme_store().transition(
            user_id=user_id,
            obligation_id=obligation_id,
            recipe_id=req.recipe_id or obligation_id,
            new_state=new_state,
            reason=req.reason,
            blockers=req.blockers,
            derived_from_report_id=req.derived_from_report_id,
            system_name=req.system_name,
            observed_evidence=req.observed_evidence,
        )
    except InvalidTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_dto(rec)


@router.delete(
    "/{obligation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an obligation lifecycle record",
)
async def delete_obligation(
    obligation_id: str,
    user_id: Annotated[str, Depends(get_current_user)],
) -> None:
    if not get_programme_store().delete(user_id, obligation_id):
        raise HTTPException(status_code=404, detail="obligation not found")


__all__ = ["router"]
