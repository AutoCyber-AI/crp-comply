"""``ask_user`` tool + suspend/resume persistence \u2014 PHASE_7 \u00a721 7.5.

When the model decides it cannot proceed without user input, it
invokes the :func:`ask_user` tool. The runner emits
``loop.clarifier.ask`` with a ``resume_token`` and the orchestrator:

1. Persists the FSM snapshot + step cursor to sqlite at
   ``data/cache/awaiting_user.db`` (key: ``resume_token``).
2. Returns control to the SSE bridge \u2014 the stream stays open with
   heartbeats but no further work happens until the user replies.
3. On ``POST /agent/resume/{resume_token}`` the orchestrator loads
   the snapshot, transitions ``AWAITING_USER \u2192 ACTING``, and feeds
   the answer back into the runner as the next observation.

Bypass guards (PHASE_7 \u00a721 7.5):

* The snapshot lives on disk, not just in memory: a worker restart
  must be able to resume the loop. :class:`ClarifierStore` round-trips
  through sqlite.
* Clarifier budget = 6 per loop. Enforced by :class:`LoopState` (7.3)
  and double-checked here when persisting.
* The resume token is a 256-bit cryptographically random hex string
  bound to ``(session_id, run_id)`` so guessing or replay is
  infeasible.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .step_runner import ToolError, ToolResult, ToolSpec


__all__ = [
    "AskUserSuspended",
    "ClarifierRecord",
    "ClarifierStore",
    "build_ask_user_tool",
    "make_resume_token",
]


# ── Sentinels ────────────────────────────────────────────────────────


class AskUserSuspended(Exception):
    """Raised by :func:`ask_user` to signal the runner to suspend.

    Carries the question, slot id, options, and resume token. The
    orchestrator catches it, persists the FSM snapshot, and returns
    the resume token to the client.
    """

    def __init__(
        self,
        *,
        question: str,
        slot_id: str,
        options: list[str] | None = None,
        resume_token: str = "",
    ) -> None:
        super().__init__(question)
        self.question = question
        self.slot_id = slot_id
        self.options = options
        self.resume_token = resume_token


# ── Resume tokens ────────────────────────────────────────────────────


def make_resume_token() -> str:
    """Return a 256-bit hex resume token. Cryptographically random."""
    return secrets.token_hex(32)


# ── Persistence ──────────────────────────────────────────────────────


_SCHEMA = """
CREATE TABLE IF NOT EXISTS awaiting_user (
    resume_token   TEXT PRIMARY KEY,
    session_id     TEXT NOT NULL,
    run_id         TEXT NOT NULL,
    tenant_id      TEXT NOT NULL,
    slot_id        TEXT NOT NULL,
    question       TEXT NOT NULL,
    options_json   TEXT,
    snapshot_json  TEXT NOT NULL,
    created_at     REAL NOT NULL,
    answered_at    REAL,
    answer         TEXT
);
CREATE INDEX IF NOT EXISTS ix_awaiting_session
    ON awaiting_user(session_id);
"""


@dataclass(frozen=True)
class ClarifierRecord:
    resume_token: str
    session_id: str
    run_id: str
    tenant_id: str
    slot_id: str
    question: str
    options: list[str] | None
    snapshot: dict[str, Any]
    created_at: float
    answered_at: float | None = None
    answer: str | None = None


@dataclass
class ClarifierStore:
    """Sqlite-backed store for suspended clarifier sessions.

    A single instance is safe to share across threads.

    Resume tokens expire after :attr:`token_ttl_seconds` (default 24 h
    per PHASE_7 §21 7.12). Expired tokens behave as if they never
    existed: :meth:`load` returns ``None``, :meth:`answer` raises
    ``ToolError("unknown resume_token")`` so existence cannot be
    probed.
    """

    db_path: Path = field(default_factory=lambda: Path("data/cache/awaiting_user.db"))
    token_ttl_seconds: float = 24 * 60 * 60
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    # -- writes ----------------------------------------------------

    def suspend(
        self,
        *,
        resume_token: str,
        session_id: str,
        run_id: str,
        tenant_id: str,
        slot_id: str,
        question: str,
        options: list[str] | None,
        snapshot: dict[str, Any],
    ) -> ClarifierRecord:
        if not tenant_id:
            raise ToolError("tenant_id required to persist clarifier")
        if not session_id or not run_id:
            raise ToolError("session_id + run_id required")
        rec = ClarifierRecord(
            resume_token=resume_token,
            session_id=session_id,
            run_id=run_id,
            tenant_id=tenant_id,
            slot_id=slot_id,
            question=question,
            options=options,
            snapshot=snapshot,
            created_at=time.time(),
        )
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO awaiting_user ("
                "resume_token, session_id, run_id, tenant_id, slot_id, "
                "question, options_json, snapshot_json, created_at"
                ") VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    rec.resume_token,
                    rec.session_id,
                    rec.run_id,
                    rec.tenant_id,
                    rec.slot_id,
                    rec.question,
                    json.dumps(rec.options) if rec.options else None,
                    json.dumps(rec.snapshot),
                    rec.created_at,
                ),
            )
            conn.commit()
        return rec

    def answer(
        self,
        *,
        resume_token: str,
        tenant_id: str,
        answer: str,
    ) -> ClarifierRecord:
        """Record an answer and return the loaded record.

        Tenant ID must match: cross-tenant resume attempts return None
        as if the token did not exist.
        """
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM awaiting_user WHERE resume_token = ?",
                (resume_token,),
            ).fetchone()
            if row is None:
                raise ToolError("unknown resume_token")
            if row["tenant_id"] != tenant_id:
                # Don't leak existence across tenants.
                raise ToolError("unknown resume_token")
            if row["answered_at"] is not None:
                raise ToolError("resume_token already used")
            if self._is_expired(row["created_at"]):
                # Treat expired tokens as unknown: do not reveal that
                # the token *was* once valid (PHASE_7 §21 7.12).
                raise ToolError("unknown resume_token")
            now = time.time()
            conn.execute(
                "UPDATE awaiting_user SET answered_at = ?, answer = ? WHERE resume_token = ?",
                (now, answer, resume_token),
            )
            conn.commit()
            return _row_to_record(row, answered_at=now, answer=answer)

    # -- reads -----------------------------------------------------

    def load(self, *, resume_token: str, tenant_id: str) -> ClarifierRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM awaiting_user WHERE resume_token = ? AND tenant_id = ?",
                (resume_token, tenant_id),
            ).fetchone()
        if row is None:
            return None
        if self._is_expired(row["created_at"]):
            return None
        return _row_to_record(row)

    def _is_expired(self, created_at: float) -> bool:
        if self.token_ttl_seconds <= 0:
            return False
        return (time.time() - float(created_at)) > self.token_ttl_seconds

    def pending_for_session(self, *, session_id: str, tenant_id: str) -> list[ClarifierRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM awaiting_user "
                "WHERE session_id = ? AND tenant_id = ? AND answered_at IS NULL "
                "ORDER BY created_at",
                (session_id, tenant_id),
            ).fetchall()
        return [_row_to_record(r) for r in rows]

    def purge_older_than(self, max_age_seconds: float) -> int:
        """Drop unanswered clarifiers older than the cutoff.

        Used by a periodic janitor; not on the request path.
        """
        cutoff = time.time() - max_age_seconds
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM awaiting_user WHERE answered_at IS NULL AND created_at < ?",
                (cutoff,),
            )
            conn.commit()
            return cur.rowcount or 0


def _row_to_record(
    row: sqlite3.Row,
    *,
    answered_at: float | None = None,
    answer: str | None = None,
) -> ClarifierRecord:
    opts = json.loads(row["options_json"]) if row["options_json"] else None
    return ClarifierRecord(
        resume_token=row["resume_token"],
        session_id=row["session_id"],
        run_id=row["run_id"],
        tenant_id=row["tenant_id"],
        slot_id=row["slot_id"],
        question=row["question"],
        options=opts,
        snapshot=json.loads(row["snapshot_json"]),
        created_at=float(row["created_at"]),
        answered_at=(
            answered_at
            if answered_at is not None
            else (float(row["answered_at"]) if row["answered_at"] is not None else None)
        ),
        answer=(answer if answer is not None else row["answer"]),
    )


# ── Tool factory ─────────────────────────────────────────────────────


def build_ask_user_tool(*, resume_token: str) -> ToolSpec:
    """Build an ``ask_user`` :class:`ToolSpec` bound to a resume token.

    The orchestrator constructs one of these *per step* (each call
    needs a fresh token) and registers it on the runner's registry.
    The handler raises :class:`AskUserSuspended` rather than returning
    a :class:`ToolResult`; the runner's ``_dispatch`` would normally
    catch it as a ``ToolError`` but we raise it as a separate
    exception type so the orchestrator can distinguish suspend from
    failure.
    """

    def _handler(
        *,
        question: str,
        slot_id: str = "",
        options: list[str] | None = None,
        context: str | None = None,
    ) -> ToolResult:  # pragma: no cover - never reached
        # We always raise; this branch exists only to satisfy the
        # ToolHandler signature for IDEs.
        raise AskUserSuspended(
            question=question,
            slot_id=slot_id or "default",
            options=options,
            resume_token=resume_token,
        )

    return ToolSpec(
        name="ask_user",
        description=(
            "Ask the user a clarifying question. Use this when "
            "confidence on a user-facing claim is below 0.6 or when "
            "scoping cannot proceed without explicit input."
        ),
        handler=_handler,
        input_schema={
            "type": "object",
            "required": ["question"],
            "properties": {
                "question": {"type": "string"},
                "slot_id": {"type": "string"},
                "options": {"type": "array"},
                "context": {"type": "string"},
            },
        },
    )
