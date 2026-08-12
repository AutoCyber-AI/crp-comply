# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Draft session bridge — one record links recipe + agent + lifecycle.

§6 of ``COMPLIANCE_MODEL_ANALYSIS.md`` argues the recipe Workspace and
the open-ended AgentChat are the same drafting loop and need to share
state. This module is the minimum viable bridge: a tenant-scoped
``DraftSession`` record that holds

* the recipe id being drafted,
* the obligation id (Programme tracker key),
* the open-ended agent session id (so chat turns thread into the same
  conversation as the recipe-driven drafting),
* the latest report id produced (for "open the deliverable" links),
* the current :class:`LifecycleState` (mirrored from
  :class:`~crp_comply.programme.ObligationLifecycle` for cheap reads).

The store does **not** duplicate agent message history or recipe payloads
— callers fetch those from the existing stores by id. This keeps the
bridge a small, fast index that can be safely rebuilt if it gets corrupt.

Storage layout::

    {data_dir}/draft_sessions/{user_id}/{session_id}.json

API endpoints (mounted under ``/api/v1/drafts``):

``POST   /drafts``                          — create a session for a recipe
``GET    /drafts``                          — list the caller's sessions
``GET    /drafts/{session_id}``             — fetch one session
``POST   /drafts/{session_id}/agent``       — link an agent_session_id
``POST   /drafts/{session_id}/report``      — link a report_id
``DELETE /drafts/{session_id}``             — delete the bridge record
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from .deps import get_current_user

log = logging.getLogger("crp_comply.api.draft_sessions")

router = APIRouter(prefix="/drafts", tags=["drafts"])


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in s)[:128]


@dataclass
class DraftSession:
    """Bridge record linking recipe + agent + lifecycle + report."""

    session_id: str
    user_id: str
    recipe_id: str
    obligation_id: str
    system_name: str = ""
    agent_session_id: str = ""
    report_id: str = ""
    state: str = "not_started"
    created_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DraftSession":
        return cls(
            session_id=str(data.get("session_id") or ""),
            user_id=str(data.get("user_id") or ""),
            recipe_id=str(data.get("recipe_id") or ""),
            obligation_id=str(data.get("obligation_id") or ""),
            system_name=str(data.get("system_name") or ""),
            agent_session_id=str(data.get("agent_session_id") or ""),
            report_id=str(data.get("report_id") or ""),
            state=str(data.get("state") or "not_started"),
            created_at=str(data.get("created_at") or _utc_now_iso()),
            updated_at=str(data.get("updated_at") or _utc_now_iso()),
        )


class DraftSessionStore:
    """JSON-backed, thread-safe per-tenant draft-session bridge."""

    def __init__(self, data_dir: Path | str) -> None:
        self._root = Path(data_dir) / "draft_sessions"
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _user_dir(self, user_id: str) -> Path:
        d = self._root / _sanitize(user_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _path(self, user_id: str, session_id: str) -> Path:
        return self._user_dir(user_id) / f"{_sanitize(session_id)}.json"

    def get(self, user_id: str, session_id: str) -> DraftSession | None:
        p = self._path(user_id, session_id)
        if not p.exists():
            return None
        try:
            return DraftSession.from_dict(json.loads(p.read_text(encoding="utf-8")))
        except Exception as exc:
            log.warning("failed to read draft session %s: %s", p, exc)
            return None

    def list(self, user_id: str) -> list[DraftSession]:
        out: list[DraftSession] = []
        for p in self._user_dir(user_id).glob("*.json"):
            try:
                out.append(DraftSession.from_dict(json.loads(p.read_text(encoding="utf-8"))))
            except Exception as _bandit_exc:
                log.debug("swallowed in draft_sessions.list: %s", _bandit_exc)
                continue
        out.sort(key=lambda r: r.updated_at, reverse=True)
        return out

    def save(self, rec: DraftSession) -> DraftSession:
        rec.updated_at = _utc_now_iso()
        p = self._path(rec.user_id, rec.session_id)
        with self._lock:
            p.write_text(
                json.dumps(rec.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        return rec

    def delete(self, user_id: str, session_id: str) -> bool:
        p = self._path(user_id, session_id)
        if not p.exists():
            return False
        with self._lock:
            p.unlink()
        return True


_store: DraftSessionStore | None = None


def init_draft_sessions(data_dir: Path | str) -> DraftSessionStore:
    global _store
    _store = DraftSessionStore(data_dir=data_dir)
    return _store


def get_draft_session_store() -> DraftSessionStore:
    if _store is None:
        raise RuntimeError(
            "draft session store not initialised — call init_draft_sessions(data_dir)"
        )
    return _store


# ── DTOs ─────────────────────────────────────────────────────


class DraftSessionDTO(BaseModel):
    session_id: str
    user_id: str
    recipe_id: str
    obligation_id: str
    system_name: str = ""
    agent_session_id: str = ""
    report_id: str = ""
    state: str
    created_at: str
    updated_at: str


def _to_dto(rec: DraftSession) -> DraftSessionDTO:
    return DraftSessionDTO(**rec.to_dict())


class CreateDraftRequest(BaseModel):
    recipe_id: str = Field(..., min_length=1)
    system_name: str = ""


class LinkAgentRequest(BaseModel):
    agent_session_id: str = Field(..., min_length=1)


class LinkReportRequest(BaseModel):
    report_id: str = Field(..., min_length=1)


# ── Endpoints ────────────────────────────────────────────────


def _refresh_state(rec: DraftSession) -> DraftSession:
    """Mirror the obligation lifecycle state into the bridge record.

    Programme transitions are written by the recipes pipeline; we don't
    re-do that work here, just expose the latest snapshot.
    """
    try:
        from ..programme import get_programme_store

        ob = get_programme_store().get(rec.user_id, rec.obligation_id)
        if ob is not None and ob.state != rec.state:
            rec.state = ob.state
            get_draft_session_store().save(rec)
    except Exception as exc:  # pragma: no cover — defensive
        log.debug("draft state refresh skipped: %s", exc)
    return rec


@router.post(
    "",
    response_model=DraftSessionDTO,
    status_code=status.HTTP_201_CREATED,
    summary="Create a draft session bridging recipe + agent + lifecycle",
)
async def create_draft(
    req: CreateDraftRequest,
    user_id: Annotated[str, Depends(get_current_user)],
) -> DraftSessionDTO:
    rec = DraftSession(
        session_id=str(uuid.uuid4()),
        user_id=user_id,
        recipe_id=req.recipe_id,
        obligation_id=req.recipe_id,
        system_name=req.system_name,
    )
    get_draft_session_store().save(rec)
    return _to_dto(_refresh_state(rec))


@router.get("", response_model=list[DraftSessionDTO], summary="List draft sessions")
async def list_drafts(
    user_id: Annotated[str, Depends(get_current_user)],
) -> list[DraftSessionDTO]:
    store = get_draft_session_store()
    return [_to_dto(_refresh_state(r)) for r in store.list(user_id)]


@router.get("/{session_id}", response_model=DraftSessionDTO, summary="Get a draft session")
async def get_draft(
    session_id: str,
    user_id: Annotated[str, Depends(get_current_user)],
) -> DraftSessionDTO:
    rec = get_draft_session_store().get(user_id, session_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="draft session not found")
    return _to_dto(_refresh_state(rec))


@router.post(
    "/{session_id}/agent",
    response_model=DraftSessionDTO,
    summary="Link an agent session to a draft",
)
async def link_agent(
    session_id: str,
    req: LinkAgentRequest,
    user_id: Annotated[str, Depends(get_current_user)],
) -> DraftSessionDTO:
    store = get_draft_session_store()
    rec = store.get(user_id, session_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="draft session not found")
    rec.agent_session_id = req.agent_session_id
    return _to_dto(store.save(rec))


@router.post(
    "/{session_id}/report",
    response_model=DraftSessionDTO,
    summary="Link a generated report to a draft",
)
async def link_report(
    session_id: str,
    req: LinkReportRequest,
    user_id: Annotated[str, Depends(get_current_user)],
) -> DraftSessionDTO:
    store = get_draft_session_store()
    rec = store.get(user_id, session_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="draft session not found")
    rec.report_id = req.report_id
    return _to_dto(store.save(rec))


@router.delete(
    "/{session_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a draft session"
)
async def delete_draft(
    session_id: str,
    user_id: Annotated[str, Depends(get_current_user)],
) -> None:
    if not get_draft_session_store().delete(user_id, session_id):
        raise HTTPException(status_code=404, detail="draft session not found")


__all__ = [
    "router",
    "DraftSession",
    "DraftSessionStore",
    "init_draft_sessions",
    "get_draft_session_store",
]
