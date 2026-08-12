"""Continuous compliance API.

Surfaces the continuous compliance engine to the frontend:
  * trigger an on-demand audit
  * read the latest audit result and gap report
  * create/list remediation tickets
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..continuous_compliance import ContinuousComplianceEngine, RemediationTicket
from .deps import get_current_user

logger = logging.getLogger("crp_comply.api.continuous")

router = APIRouter(prefix="/continuous", tags=["continuous compliance"])


# ── DTOs ─────────────────────────────────────────────────────


class ObligationVerdictDTO(BaseModel):
    obligation_id: str
    recipe_id: str
    system_name: str = ""
    state: str
    verdict: str
    reason: str
    last_evidence_at: str | None = None


class GapDTO(BaseModel):
    obligation_id: str
    recipe_id: str
    system_name: str = ""
    verdict: str
    reason: str
    blockers: list[str] = Field(default_factory=list)
    remediation_hint: str


class AuditResultDTO(BaseModel):
    user_id: str
    audited_at: str
    overall_score: float
    obligations: list[ObligationVerdictDTO]
    gap_report: list[GapDTO]


class RemediationRequest(BaseModel):
    obligation_id: str
    owner: str
    due_days: int = 14


class RemediationTicketDTO(BaseModel):
    ticket_id: str
    user_id: str
    obligation_id: str
    title: str
    description: str
    owner: str
    due_date: str
    evidence_checklist: list[str] = Field(default_factory=list)
    status: str
    created_at: str
    updated_at: str


def _remediation_to_dto(t: RemediationTicket) -> RemediationTicketDTO:
    return RemediationTicketDTO(**t.to_dict())


# ── Singleton access ─────────────────────────────────────────

_engine: ContinuousComplianceEngine | None = None


def init_continuous_engine(engine: ContinuousComplianceEngine) -> None:
    global _engine
    _engine = engine


def get_continuous_engine() -> ContinuousComplianceEngine:
    if _engine is None:
        raise RuntimeError("continuous compliance engine not initialised")
    return _engine


# ── Endpoints ────────────────────────────────────────────────


@router.post("/audit", response_model=AuditResultDTO, summary="Run a continuous compliance audit")
async def trigger_audit(
    user_id: Annotated[str, Depends(get_current_user)],
) -> AuditResultDTO:
    result = get_continuous_engine().audit(user_id)
    return AuditResultDTO(
        user_id=result.user_id,
        audited_at=result.audited_at,
        overall_score=result.overall_score,
        obligations=[ObligationVerdictDTO(**o.__dict__) for o in result.obligations],
        gap_report=[GapDTO(**g) for g in result.gap_report],
    )


@router.get("/audit", response_model=AuditResultDTO | None, summary="Read the latest audit result")
async def latest_audit(
    user_id: Annotated[str, Depends(get_current_user)],
) -> AuditResultDTO | None:
    result = get_continuous_engine().get_last_audit(user_id)
    if result is None:
        return None
    return AuditResultDTO(
        user_id=result.user_id,
        audited_at=result.audited_at,
        overall_score=result.overall_score,
        obligations=[ObligationVerdictDTO(**o.__dict__) for o in result.obligations],
        gap_report=[GapDTO(**g) for g in result.gap_report],
    )


@router.get("/gaps", response_model=list[GapDTO], summary="List compliance gaps from latest audit")
async def list_gaps(
    user_id: Annotated[str, Depends(get_current_user)],
) -> list[GapDTO]:
    result = get_continuous_engine().get_last_audit(user_id)
    if result is None:
        return []
    return [GapDTO(**g) for g in result.gap_report]


@router.post(
    "/remediate",
    response_model=RemediationTicketDTO,
    summary="Create a remediation ticket for an obligation",
)
async def create_remediation(
    req: RemediationRequest,
    user_id: Annotated[str, Depends(get_current_user)],
) -> RemediationTicketDTO:
    if not req.obligation_id or not req.owner:
        raise HTTPException(status_code=400, detail="obligation_id and owner are required")
    ticket = get_continuous_engine().create_remediation(
        user_id=user_id,
        obligation_id=req.obligation_id,
        owner=req.owner,
        due_days=req.due_days,
    )
    return _remediation_to_dto(ticket)


@router.get(
    "/remediate", response_model=list[RemediationTicketDTO], summary="List remediation tickets"
)
async def list_remediations(
    user_id: Annotated[str, Depends(get_current_user)],
) -> list[RemediationTicketDTO]:
    tickets = get_continuous_engine().list_remediations(user_id)
    return [_remediation_to_dto(t) for t in tickets]
