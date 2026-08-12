# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Phase 4 corpus administration routes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field

from ..corpus import CorpusRepository, IngestionScheduler, RegulationIndex
from ..corpus.models import TenantAnnotation
from .deps import get_current_tenant, get_current_user

router = APIRouter(prefix="/corpus", tags=["corpus"])


# ---------------------------------------------------------------------------
# Request/response schemas
# ---------------------------------------------------------------------------


class CorpusStatusResponse(BaseModel):
    total_chunks: int
    sources: list[dict[str, Any]]
    embedding_profiles: list[dict[str, Any]]


class RegulationResponse(BaseModel):
    source_id: str
    title: str
    jurisdiction: str
    version: str
    canonical_url: str
    license: str
    effective_date: str | None
    superseded_by: str | None
    chunk_count: int
    indexed_at: str | None


class IngestTriggerResponse(BaseModel):
    job_id: str
    status: str
    source_id: str


class IngestJobResponse(BaseModel):
    id: str
    source_id: str
    status: str
    trigger: str
    started_at: str | None
    finished_at: str | None
    previous_hash: str | None
    new_hash: str | None
    chunks_added: int
    chunks_removed: int
    obligations_added: int
    error_message: str | None


class ObligationResponse(BaseModel):
    id: str
    source_id: str
    chunk_id: str
    text: str
    article_id: str
    section_path: list[str]
    obligation_type: str
    actors: list[str]
    topics: list[str]
    effective_date: str | None
    superseded_by: str | None
    confidence: float


class GraphResponse(BaseModel):
    node: ObligationResponse
    outgoing: list[dict[str, Any]]
    incoming: list[dict[str, Any]]


class AnnotationCreate(BaseModel):
    target_type: str = Field(..., pattern="^(chunk|obligation|regulation)$")
    target_id: str
    annotation_type: str = Field(..., pattern="^(note|override|applicability|exemption|mapping)$")
    payload: dict[str, Any] = Field(default_factory=dict)


class AnnotationResponse(BaseModel):
    id: str
    tenant_id: str
    target_type: str
    target_id: str
    annotation_type: str
    payload: dict[str, Any]
    created_by: str
    created_at: str


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def _get_repo() -> CorpusRepository:
    return CorpusRepository()


def _get_index() -> RegulationIndex:
    return RegulationIndex()


# ---------------------------------------------------------------------------
# Status & regulations
# ---------------------------------------------------------------------------


@router.get("/status", response_model=CorpusStatusResponse)
async def corpus_status(
    index: Annotated[RegulationIndex, Depends(_get_index)],
) -> dict[str, Any]:
    """High-level corpus status: chunk counts and source versions."""
    stats = index.index.stats()
    return {
        "total_chunks": stats.get("total_chunks", 0),
        "sources": stats.get("sources", []),
        "embedding_profiles": stats.get("embedding_profiles", []),
    }


@router.get("/regulations", response_model=list[RegulationResponse])
async def list_regulations(
    repo: Annotated[CorpusRepository, Depends(_get_repo)],
) -> list[dict[str, Any]]:
    with repo:
        return [r.to_dict() for r in repo.list_regulations()]


@router.get("/regulations/{source_id}", response_model=RegulationResponse)
async def get_regulation(
    source_id: str,
    repo: Annotated[CorpusRepository, Depends(_get_repo)],
) -> dict[str, Any]:
    with repo:
        reg = repo.get_regulation(source_id)
    if not reg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="regulation not found")
    return reg.to_dict()


# ---------------------------------------------------------------------------
# Ingestion jobs
# ---------------------------------------------------------------------------


@router.post("/ingest/{source_id}", response_model=IngestTriggerResponse)
async def trigger_ingestion(
    source_id: str = Path(..., description="Regulation source id, e.g. eu_ai_act"),
    force: bool = Query(False, description="Re-index even if the content hash is unchanged"),
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    """Trigger a manual ingestion job for a regulation source."""
    if user_id == "anonymous":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required"
        )
    scheduler = IngestionScheduler()
    # Heavy work runs in a thread pool; small scrapers finish in seconds.
    job = await scheduler.run_once_async(source_id, trigger="manual", force=force)
    return {"job_id": job.id, "status": job.status, "source_id": job.source_id}


@router.get("/ingest/jobs", response_model=list[IngestJobResponse])
async def list_ingest_jobs(
    repo: Annotated[CorpusRepository, Depends(_get_repo)],
    source_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> list[dict[str, Any]]:
    with repo:
        return [j.to_dict() for j in repo.list_jobs(source_id=source_id, limit=limit)]


@router.get("/ingest/jobs/{job_id}", response_model=IngestJobResponse)
async def get_ingest_job(
    job_id: str,
    repo: Annotated[CorpusRepository, Depends(_get_repo)],
) -> dict[str, Any]:
    with repo:
        job = repo.get_job(job_id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")
    return job.to_dict()


# ---------------------------------------------------------------------------
# Obligations & graph
# ---------------------------------------------------------------------------


@router.get("/obligations", response_model=list[ObligationResponse])
async def list_obligations(
    repo: Annotated[CorpusRepository, Depends(_get_repo)],
    source_id: str | None = Query(None),
    article_id: str | None = Query(None),
) -> list[dict[str, Any]]:
    source_filter = [source_id] if source_id else None
    with repo:
        return [
            o.to_dict()
            for o in repo.list_obligations(source_filter=source_filter, article_id=article_id)
        ]


@router.get("/obligations/{obligation_id}/graph", response_model=GraphResponse)
async def get_obligation_graph(
    obligation_id: str,
    repo: Annotated[CorpusRepository, Depends(_get_repo)],
) -> dict[str, Any]:
    with repo:
        node = repo.get_obligation(obligation_id)
        if not node:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="obligation not found"
            )
        neighbors = repo.graph_neighbors(obligation_id)
    return {
        "node": node.to_dict(),
        "outgoing": [e.to_dict() for e in neighbors["outgoing"]],
        "incoming": [e.to_dict() for e in neighbors["incoming"]],
    }


# ---------------------------------------------------------------------------
# Tenant annotations
# ---------------------------------------------------------------------------


@router.get("/annotations", response_model=list[AnnotationResponse])
async def list_annotations(
    tenant_id: Annotated[str, Depends(get_current_tenant)],
    repo: Annotated[CorpusRepository, Depends(_get_repo)],
    target_type: str | None = Query(None),
    target_id: str | None = Query(None),
) -> list[dict[str, Any]]:
    with repo:
        return [
            a.to_dict()
            for a in repo.list_annotations(tenant_id, target_type=target_type, target_id=target_id)
        ]


@router.post("/annotations", response_model=AnnotationResponse, status_code=status.HTTP_201_CREATED)
async def create_annotation(
    body: AnnotationCreate,
    tenant_id: Annotated[str, Depends(get_current_tenant)],
    user_id: Annotated[str, Depends(get_current_user)],
    repo: Annotated[CorpusRepository, Depends(_get_repo)],
) -> dict[str, Any]:
    if tenant_id == "anonymous":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required"
        )
    import uuid

    annotation = TenantAnnotation(
        id=uuid.uuid4().hex[:16],
        tenant_id=tenant_id,
        target_type=body.target_type,
        target_id=body.target_id,
        annotation_type=body.annotation_type,
        payload=body.payload,
        created_by=user_id,
    )
    with repo:
        repo.upsert_annotation(annotation)
    return annotation.to_dict()
