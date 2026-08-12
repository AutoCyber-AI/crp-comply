# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""SQLite repository for Phase 4 structured corpus metadata.

Shares the same SQLite file as :class:`CorpusIndex` so the corpus and its
metadata stay transactionally aligned and backup together.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Sequence

from ..agent.rag.index import index_dir
from .models import (
    IngestionJob,
    Obligation,
    ObligationEdge,
    Regulation,
    TenantAnnotation,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS regulations (
    source_id       TEXT PRIMARY KEY,
    title           TEXT,
    jurisdiction    TEXT,
    version         TEXT,
    canonical_url   TEXT,
    license         TEXT,
    effective_date  TEXT,
    superseded_by   TEXT,
    chunk_count     INTEGER DEFAULT 0,
    indexed_at      TEXT,
    meta            TEXT
);

CREATE TABLE IF NOT EXISTS obligations (
    id              TEXT PRIMARY KEY,
    source_id       TEXT NOT NULL,
    chunk_id        TEXT NOT NULL,
    text            TEXT NOT NULL,
    article_id      TEXT,
    section_path    TEXT,
    obligation_type TEXT,
    actors          TEXT,
    topics          TEXT,
    effective_date  TEXT,
    superseded_by   TEXT,
    confidence      REAL,
    created_at      TEXT,
    meta            TEXT
);

CREATE INDEX IF NOT EXISTS idx_obligations_source ON obligations(source_id);
CREATE INDEX IF NOT EXISTS idx_obligations_chunk ON obligations(chunk_id);
CREATE INDEX IF NOT EXISTS idx_obligations_article ON obligations(article_id);

CREATE TABLE IF NOT EXISTS obligation_edges (
    id          TEXT PRIMARY KEY,
    source_id   TEXT NOT NULL,
    target_id   TEXT NOT NULL,
    edge_type   TEXT NOT NULL,
    weight      REAL DEFAULT 1.0,
    provenance  TEXT,
    created_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_edges_source ON obligation_edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON obligation_edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_type ON obligation_edges(edge_type);

CREATE TABLE IF NOT EXISTS tenant_annotations (
    id                TEXT PRIMARY KEY,
    tenant_id         TEXT NOT NULL,
    target_type       TEXT NOT NULL,
    target_id         TEXT NOT NULL,
    annotation_type   TEXT NOT NULL,
    payload           TEXT,
    created_by        TEXT,
    created_at        TEXT
);

CREATE INDEX IF NOT EXISTS idx_annotations_tenant ON tenant_annotations(tenant_id);
CREATE INDEX IF NOT EXISTS idx_annotations_target ON tenant_annotations(target_type, target_id);

CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id               TEXT PRIMARY KEY,
    source_id        TEXT NOT NULL,
    status           TEXT,
    trigger          TEXT,
    started_at       TEXT,
    finished_at      TEXT,
    previous_hash    TEXT,
    new_hash         TEXT,
    chunks_added     INTEGER DEFAULT 0,
    chunks_removed   INTEGER DEFAULT 0,
    obligations_added INTEGER DEFAULT 0,
    error_message    TEXT,
    metadata         TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_source ON ingestion_jobs(source_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON ingestion_jobs(status);
"""


class CorpusRepository:
    """Persistence layer for the Phase 4 corpus knowledge graph."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else index_dir() / "corpus.sqlite"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "CorpusRepository":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---------------------------------------------------------------- regulations

    def upsert_regulation(self, regulation: Regulation) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO regulations (source_id, title, jurisdiction, version,
                                         canonical_url, license, effective_date,
                                         superseded_by, chunk_count, indexed_at, meta)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    title=excluded.title,
                    jurisdiction=excluded.jurisdiction,
                    version=excluded.version,
                    canonical_url=excluded.canonical_url,
                    license=excluded.license,
                    effective_date=excluded.effective_date,
                    superseded_by=excluded.superseded_by,
                    chunk_count=excluded.chunk_count,
                    indexed_at=excluded.indexed_at,
                    meta=excluded.meta
                """,
                (
                    regulation.source_id,
                    regulation.title,
                    regulation.jurisdiction,
                    regulation.version,
                    regulation.canonical_url,
                    regulation.license,
                    regulation.effective_date,
                    regulation.superseded_by,
                    regulation.chunk_count,
                    regulation.indexed_at,
                    json.dumps({}),
                ),
            )

    def get_regulation(self, source_id: str) -> Regulation | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM regulations WHERE source_id = ?", (source_id,)
            ).fetchone()
        if not row:
            return None
        return self._regulation_from_row(row)

    def list_regulations(self) -> list[Regulation]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM regulations ORDER BY source_id").fetchall()
        return [self._regulation_from_row(r) for r in rows]

    def _regulation_from_row(self, row: sqlite3.Row) -> Regulation:
        return Regulation(
            source_id=row["source_id"],
            title=row["title"] or "",
            jurisdiction=row["jurisdiction"] or "",
            version=row["version"] or "",
            canonical_url=row["canonical_url"] or "",
            license=row["license"] or "",
            effective_date=row["effective_date"],
            superseded_by=row["superseded_by"],
            chunk_count=row["chunk_count"] or 0,
            indexed_at=row["indexed_at"],
        )

    # ---------------------------------------------------------------- obligations

    def upsert_obligation(self, obligation: Obligation) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO obligations (id, source_id, chunk_id, text, article_id,
                                         section_path, obligation_type, actors, topics,
                                         effective_date, superseded_by, confidence,
                                         created_at, meta)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    text=excluded.text,
                    article_id=excluded.article_id,
                    section_path=excluded.section_path,
                    obligation_type=excluded.obligation_type,
                    actors=excluded.actors,
                    topics=excluded.topics,
                    effective_date=excluded.effective_date,
                    superseded_by=excluded.superseded_by,
                    confidence=excluded.confidence,
                    meta=excluded.meta
                """,
                (
                    obligation.id,
                    obligation.source_id,
                    obligation.chunk_id,
                    obligation.text,
                    obligation.article_id,
                    json.dumps(list(obligation.section_path)),
                    obligation.obligation_type,
                    json.dumps(list(obligation.actors)),
                    json.dumps(list(obligation.topics)),
                    obligation.effective_date,
                    obligation.superseded_by,
                    obligation.confidence,
                    obligation.created_at,
                    json.dumps({}),
                ),
            )

    def get_obligation(self, obligation_id: str) -> Obligation | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM obligations WHERE id = ?", (obligation_id,)
            ).fetchone()
        if not row:
            return None
        return self._obligation_from_row(row)

    def list_obligations(
        self,
        *,
        source_filter: Sequence[str] | None = None,
        article_id: str | None = None,
        chunk_id: str | None = None,
    ) -> list[Obligation]:
        query = "SELECT * FROM obligations WHERE 1=1"
        params: list[Any] = []
        if source_filter:
            placeholders = ",".join("?" * len(source_filter))
            query += f" AND source_id IN ({placeholders})"
            params.extend(source_filter)
        if article_id:
            query += " AND article_id = ?"
            params.append(article_id)
        if chunk_id:
            query += " AND chunk_id = ?"
            params.append(chunk_id)
        query += " ORDER BY source_id, article_id, created_at"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [self._obligation_from_row(r) for r in rows]

    def delete_obligations_for_source(self, source_id: str) -> int:
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM obligations WHERE source_id = ?", (source_id,))
            return cur.rowcount

    def _obligation_from_row(self, row: sqlite3.Row) -> Obligation:
        return Obligation(
            id=row["id"],
            source_id=row["source_id"],
            chunk_id=row["chunk_id"],
            text=row["text"],
            article_id=row["article_id"] or "",
            section_path=_json_list(row["section_path"]),
            obligation_type=row["obligation_type"] or "shall",
            actors=_json_list(row["actors"]),
            topics=_json_list(row["topics"]),
            effective_date=row["effective_date"],
            superseded_by=row["superseded_by"],
            confidence=row["confidence"] or 0.0,
            created_at=row["created_at"] or "",
        )

    # ---------------------------------------------------------------- edges

    def upsert_edge(self, edge: ObligationEdge) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO obligation_edges (id, source_id, target_id, edge_type,
                                               weight, provenance, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    edge_type=excluded.edge_type,
                    weight=excluded.weight,
                    provenance=excluded.provenance
                """,
                (
                    edge.id,
                    edge.source_id,
                    edge.target_id,
                    edge.edge_type,
                    edge.weight,
                    edge.provenance,
                    edge.created_at,
                ),
            )

    def get_edges(
        self,
        *,
        source_id: str | None = None,
        target_id: str | None = None,
        edge_type: str | None = None,
    ) -> list[ObligationEdge]:
        query = "SELECT * FROM obligation_edges WHERE 1=1"
        params: list[Any] = []
        if source_id:
            query += " AND source_id = ?"
            params.append(source_id)
        if target_id:
            query += " AND target_id = ?"
            params.append(target_id)
        if edge_type:
            query += " AND edge_type = ?"
            params.append(edge_type)
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [self._edge_from_row(r) for r in rows]

    def graph_neighbors(self, node_id: str) -> dict[str, list[ObligationEdge]]:
        """Return outgoing and incoming edges for a node."""
        return {
            "outgoing": self.get_edges(source_id=node_id),
            "incoming": self.get_edges(target_id=node_id),
        }

    def delete_edges_for_source(self, source_id: str) -> int:
        with self._lock, self._conn:
            cur = self._conn.execute(
                "DELETE FROM obligation_edges WHERE source_id = ? OR target_id LIKE ?",
                (source_id, f"{source_id}:%"),
            )
            return cur.rowcount

    def _edge_from_row(self, row: sqlite3.Row) -> ObligationEdge:
        return ObligationEdge(
            id=row["id"],
            source_id=row["source_id"],
            target_id=row["target_id"],
            edge_type=row["edge_type"],
            weight=row["weight"] or 1.0,
            provenance=row["provenance"] or "",
            created_at=row["created_at"] or "",
        )

    # ---------------------------------------------------------------- annotations

    def upsert_annotation(self, annotation: TenantAnnotation) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO tenant_annotations (id, tenant_id, target_type, target_id,
                                                 annotation_type, payload, created_by,
                                                 created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    annotation_type=excluded.annotation_type,
                    payload=excluded.payload,
                    created_by=excluded.created_by
                """,
                (
                    annotation.id,
                    annotation.tenant_id,
                    annotation.target_type,
                    annotation.target_id,
                    annotation.annotation_type,
                    json.dumps(dict(annotation.payload)),
                    annotation.created_by,
                    annotation.created_at,
                ),
            )

    def list_annotations(
        self,
        tenant_id: str,
        *,
        target_type: str | None = None,
        target_id: str | None = None,
    ) -> list[TenantAnnotation]:
        query = "SELECT * FROM tenant_annotations WHERE tenant_id = ?"
        params: list[Any] = [tenant_id]
        if target_type:
            query += " AND target_type = ?"
            params.append(target_type)
        if target_id:
            query += " AND target_id = ?"
            params.append(target_id)
        query += " ORDER BY created_at DESC"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [self._annotation_from_row(r) for r in rows]

    def _annotation_from_row(self, row: sqlite3.Row) -> TenantAnnotation:
        return TenantAnnotation(
            id=row["id"],
            tenant_id=row["tenant_id"],
            target_type=row["target_type"],
            target_id=row["target_id"],
            annotation_type=row["annotation_type"],
            payload=_json_dict(row["payload"]),
            created_by=row["created_by"] or "",
            created_at=row["created_at"] or "",
        )

    # ---------------------------------------------------------------- jobs

    def create_job(self, job: IngestionJob) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO ingestion_jobs (id, source_id, status, trigger,
                                            started_at, finished_at, previous_hash,
                                            new_hash, chunks_added, chunks_removed,
                                            obligations_added, error_message, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.id,
                    job.source_id,
                    job.status,
                    job.trigger,
                    job.started_at,
                    job.finished_at,
                    job.previous_hash,
                    job.new_hash,
                    job.chunks_added,
                    job.chunks_removed,
                    job.obligations_added,
                    job.error_message,
                    json.dumps(dict(job.metadata)),
                ),
            )

    def update_job(self, job: IngestionJob) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE ingestion_jobs SET
                    status = ?,
                    finished_at = ?,
                    previous_hash = ?,
                    new_hash = ?,
                    chunks_added = ?,
                    chunks_removed = ?,
                    obligations_added = ?,
                    error_message = ?,
                    metadata = ?
                WHERE id = ?
                """,
                (
                    job.status,
                    job.finished_at,
                    job.previous_hash,
                    job.new_hash,
                    job.chunks_added,
                    job.chunks_removed,
                    job.obligations_added,
                    job.error_message,
                    json.dumps(dict(job.metadata)),
                    job.id,
                ),
            )

    def get_job(self, job_id: str) -> IngestionJob | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM ingestion_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        if not row:
            return None
        return self._job_from_row(row)

    def list_jobs(self, source_id: str | None = None, limit: int = 50) -> list[IngestionJob]:
        query = "SELECT * FROM ingestion_jobs"
        params: list[Any] = []
        if source_id:
            query += " WHERE source_id = ?"
            params.append(source_id)
        query += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [self._job_from_row(r) for r in rows]

    def _job_from_row(self, row: sqlite3.Row) -> IngestionJob:
        return IngestionJob(
            id=row["id"],
            source_id=row["source_id"],
            status=row["status"],
            trigger=row["trigger"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            previous_hash=row["previous_hash"],
            new_hash=row["new_hash"],
            chunks_added=row["chunks_added"],
            chunks_removed=row["chunks_removed"],
            obligations_added=row["obligations_added"],
            error_message=row["error_message"],
            metadata=_json_dict(row["metadata"]),
        )


def _json_list(raw: Any) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
        return [str(v) for v in value] if isinstance(value, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _json_dict(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return dict(value) if isinstance(value, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}
