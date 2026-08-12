# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Obligation-lifecycle store (Programme tracker).

§6 of ``COMPLIANCE_MODEL_ANALYSIS.md`` argues a real compliance
programme is a *living* record of where every obligation stands, not a
filesystem of static markdown reports. This module is that record.

States (the eight the audit called for, plus ``not_started``):

``not_started``           – nobody has touched this obligation yet
``interview_in_progress`` – agent is asking clarifications
``awaiting_answer``       – paused waiting for a user reply
``waiting_on_artefact``   – needs an upload (model card, DPIA template, …)
``waiting_on_runtime``    – needs ≥N days of proxy telemetry
``draft_ready``           – first draft generated, awaiting review
``signed``                – approver has signed off, evidence pack built
``stale``                 – underlying evidence changed, re-derive needed

Storage layout::

    {data_dir}/programme/{user_id}/{obligation_id}.json

Each ``obligation_id`` is the recipe-id (Bucket A) optionally suffixed
with ``::{system_slug}`` (Bucket B/C, where the same recipe applies to
multiple AI systems).
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

log = logging.getLogger("crp_comply.programme.lifecycle")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize(s: str) -> str:
    """Filesystem-safe id (alnum + ``-_.``)."""
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in s)[:128]


class LifecycleState(str, Enum):
    """Allowed lifecycle states. ``str``-derived so JSON dumps cleanly."""

    NOT_STARTED = "not_started"
    INTERVIEW_IN_PROGRESS = "interview_in_progress"
    AWAITING_ANSWER = "awaiting_answer"
    WAITING_ON_ARTEFACT = "waiting_on_artefact"
    WAITING_ON_RUNTIME = "waiting_on_runtime"
    DRAFT_READY = "draft_ready"
    SIGNED = "signed"
    STALE = "stale"


# State transitions that are valid. Anything not in this map is rejected
# so the UI can't accidentally jump from ``not_started`` → ``signed``.
_VALID_TRANSITIONS: dict[LifecycleState, set[LifecycleState]] = {
    LifecycleState.NOT_STARTED: {
        LifecycleState.INTERVIEW_IN_PROGRESS,
        LifecycleState.WAITING_ON_ARTEFACT,
        LifecycleState.WAITING_ON_RUNTIME,
        LifecycleState.DRAFT_READY,
    },
    LifecycleState.INTERVIEW_IN_PROGRESS: {
        LifecycleState.AWAITING_ANSWER,
        LifecycleState.WAITING_ON_ARTEFACT,
        LifecycleState.WAITING_ON_RUNTIME,
        LifecycleState.DRAFT_READY,
        LifecycleState.NOT_STARTED,
    },
    LifecycleState.AWAITING_ANSWER: {
        LifecycleState.INTERVIEW_IN_PROGRESS,
        LifecycleState.WAITING_ON_ARTEFACT,
        LifecycleState.WAITING_ON_RUNTIME,
        LifecycleState.DRAFT_READY,
    },
    LifecycleState.WAITING_ON_ARTEFACT: {
        LifecycleState.INTERVIEW_IN_PROGRESS,
        LifecycleState.WAITING_ON_RUNTIME,
        LifecycleState.DRAFT_READY,
    },
    LifecycleState.WAITING_ON_RUNTIME: {
        LifecycleState.INTERVIEW_IN_PROGRESS,
        LifecycleState.WAITING_ON_ARTEFACT,
        LifecycleState.DRAFT_READY,
    },
    LifecycleState.DRAFT_READY: {
        LifecycleState.SIGNED,
        LifecycleState.STALE,
        LifecycleState.WAITING_ON_ARTEFACT,
        LifecycleState.WAITING_ON_RUNTIME,
        LifecycleState.INTERVIEW_IN_PROGRESS,
    },
    LifecycleState.SIGNED: {
        LifecycleState.STALE,
    },
    LifecycleState.STALE: {
        LifecycleState.INTERVIEW_IN_PROGRESS,
        LifecycleState.WAITING_ON_ARTEFACT,
        LifecycleState.WAITING_ON_RUNTIME,
        LifecycleState.DRAFT_READY,
    },
}


@dataclass
class ObligationLifecycle:
    """A single obligation's lifecycle record.

    Attributes
    ----------
    obligation_id:
        Stable key — typically ``{recipe_id}`` or
        ``{recipe_id}::{system_slug}``.
    user_id:
        Tenant scope. Never cross-tenant.
    recipe_id:
        Recipe that produces this obligation's deliverable.
    system_name:
        Optional AI-system identifier (Bucket B/C only).
    state:
        Current :class:`LifecycleState`.
    blockers:
        Plain-English reasons the obligation can't advance — e.g.
        ``["needs model_card upload", "proxy needs 14 days of data"]``.
        Empty when the user is unblocked.
    last_evidence_observed_at:
        ISO-8601 timestamp of the most recent evidence event (artefact
        upload, proxy stat snapshot, signed approval). Used for
        staleness detection.
    derived_from_report_id:
        ``Report.id`` (when ``state ∈ {draft_ready, signed, stale}``)
        whose derivation manifest binds this lifecycle to evidence.
    history:
        Append-only audit trail of state changes; capped to the last
        100 events per obligation.
    """

    obligation_id: str
    user_id: str
    recipe_id: str
    system_name: str = ""
    state: str = LifecycleState.NOT_STARTED.value
    blockers: list[str] = field(default_factory=list)
    last_evidence_observed_at: str | None = None
    derived_from_report_id: str | None = None
    created_at: str = field(default_factory=_utc_now_iso)
    updated_at: str = field(default_factory=_utc_now_iso)
    history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ObligationLifecycle":
        # Defensive: tolerate older records that don't have every field.
        return cls(
            obligation_id=str(data.get("obligation_id") or ""),
            user_id=str(data.get("user_id") or ""),
            recipe_id=str(data.get("recipe_id") or ""),
            system_name=str(data.get("system_name") or ""),
            state=str(data.get("state") or LifecycleState.NOT_STARTED.value),
            blockers=[str(b) for b in (data.get("blockers") or [])],
            last_evidence_observed_at=data.get("last_evidence_observed_at"),
            derived_from_report_id=data.get("derived_from_report_id"),
            created_at=str(data.get("created_at") or _utc_now_iso()),
            updated_at=str(data.get("updated_at") or _utc_now_iso()),
            history=list(data.get("history") or []),
        )


class InvalidTransition(ValueError):
    """Raised when a state transition is not in :data:`_VALID_TRANSITIONS`."""


class ProgrammeStore:
    """JSON-backed, thread-safe per-tenant lifecycle store."""

    def __init__(self, data_dir: Path | str) -> None:
        self._root = Path(data_dir) / "programme"
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # ── paths ────────────────────────────────────────────────
    def _user_dir(self, user_id: str) -> Path:
        d = self._root / _sanitize(user_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _record_path(self, user_id: str, obligation_id: str) -> Path:
        return self._user_dir(user_id) / f"{_sanitize(obligation_id)}.json"

    # ── read ─────────────────────────────────────────────────
    def get(
        self,
        user_id: str,
        obligation_id: str,
    ) -> ObligationLifecycle | None:
        path = self._record_path(user_id, obligation_id)
        if not path.exists():
            return None
        try:
            return ObligationLifecycle.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception as exc:
            log.warning("failed to read lifecycle %s: %s", path, exc)
            return None

    def list(self, user_id: str) -> list[ObligationLifecycle]:
        d = self._user_dir(user_id)
        out: list[ObligationLifecycle] = []
        for path in d.glob("*.json"):
            try:
                out.append(
                    ObligationLifecycle.from_dict(json.loads(path.read_text(encoding="utf-8")))
                )
            except Exception as _bandit_exc:
                log.debug("swallowed in lifecycle.list: %s", _bandit_exc)
                continue
        out.sort(key=lambda r: r.updated_at, reverse=True)
        return out

    # ── write ────────────────────────────────────────────────
    def upsert(self, record: ObligationLifecycle) -> ObligationLifecycle:
        if not record.obligation_id or not record.user_id:
            raise ValueError("obligation_id and user_id are required")
        record.updated_at = _utc_now_iso()
        path = self._record_path(record.user_id, record.obligation_id)
        with self._lock:
            path.write_text(
                json.dumps(record.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        return record

    def transition(
        self,
        *,
        user_id: str,
        obligation_id: str,
        recipe_id: str,
        new_state: LifecycleState | str,
        reason: str = "",
        blockers: list[str] | None = None,
        derived_from_report_id: str | None = None,
        system_name: str = "",
        observed_evidence: bool = False,
    ) -> ObligationLifecycle:
        """Advance an obligation. Creates the record if missing."""
        if isinstance(new_state, str):
            try:
                new_state_enum = LifecycleState(new_state)
            except ValueError as exc:
                raise InvalidTransition(f"unknown state: {new_state}") from exc
        else:
            new_state_enum = new_state

        with self._lock:
            existing = self.get(user_id, obligation_id)
            if existing is None:
                rec = ObligationLifecycle(
                    obligation_id=obligation_id,
                    user_id=user_id,
                    recipe_id=recipe_id,
                    system_name=system_name,
                )
            else:
                rec = existing
                if recipe_id and not rec.recipe_id:
                    rec.recipe_id = recipe_id
                if system_name and not rec.system_name:
                    rec.system_name = system_name

            current = LifecycleState(rec.state)
            if new_state_enum != current:
                allowed = _VALID_TRANSITIONS.get(current, set())
                if new_state_enum not in allowed:
                    raise InvalidTransition(
                        f"cannot transition {current.value} → {new_state_enum.value}"
                    )

            rec.history.append(
                {
                    "at": _utc_now_iso(),
                    "from": rec.state,
                    "to": new_state_enum.value,
                    "reason": reason,
                }
            )
            # Cap history so a chatty obligation can't bloat the file.
            if len(rec.history) > 100:
                rec.history = rec.history[-100:]
            rec.state = new_state_enum.value
            if blockers is not None:
                rec.blockers = list(blockers)
            if derived_from_report_id is not None:
                rec.derived_from_report_id = derived_from_report_id
            if observed_evidence:
                rec.last_evidence_observed_at = _utc_now_iso()

        return self.upsert(rec)

    def mark_stale(
        self,
        *,
        user_id: str,
        obligation_id: str,
        reason: str,
    ) -> ObligationLifecycle | None:
        """Flag an obligation as stale when underlying evidence changed.

        No-op if the obligation is in a state from which staleness is
        meaningless (e.g. ``not_started``).
        """
        rec = self.get(user_id, obligation_id)
        if rec is None:
            return None
        if rec.state not in {
            LifecycleState.DRAFT_READY.value,
            LifecycleState.SIGNED.value,
        }:
            return rec
        return self.transition(
            user_id=user_id,
            obligation_id=obligation_id,
            recipe_id=rec.recipe_id,
            new_state=LifecycleState.STALE,
            reason=reason,
        )

    def delete(self, user_id: str, obligation_id: str) -> bool:
        path = self._record_path(user_id, obligation_id)
        if not path.exists():
            return False
        with self._lock:
            path.unlink()
        return True


# ── module singleton ────────────────────────────────────────
_store: ProgrammeStore | None = None


def init_programme_store(data_dir: Path | str) -> ProgrammeStore:
    """Initialise the module singleton (called from ``api/app.py`` lifespan)."""
    global _store
    _store = ProgrammeStore(data_dir=data_dir)
    return _store


def get_programme_store() -> ProgrammeStore:
    if _store is None:
        raise RuntimeError("programme store not initialised — call init_programme_store(data_dir)")
    return _store


__all__ = [
    "LifecycleState",
    "ObligationLifecycle",
    "ProgrammeStore",
    "InvalidTransition",
    "init_programme_store",
    "get_programme_store",
]
