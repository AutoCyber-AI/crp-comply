# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Phase 4 structured corpus models.

These dataclasses are the persistence-agnostic shape for the perfect regulatory
corpus: per-regulation indices, obligation graphs, recency/contradiction edges,
tenant annotations, and continuous ingestion jobs.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class Regulation:
    """A tracked regulation / framework source."""

    source_id: str
    title: str
    jurisdiction: str
    version: str
    canonical_url: str
    license: str
    effective_date: str | None = None
    superseded_by: str | None = None
    chunk_count: int = 0
    indexed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "title": self.title,
            "jurisdiction": self.jurisdiction,
            "version": self.version,
            "canonical_url": self.canonical_url,
            "license": self.license,
            "effective_date": self.effective_date,
            "superseded_by": self.superseded_by,
            "chunk_count": self.chunk_count,
            "indexed_at": self.indexed_at,
        }


@dataclass
class Obligation:
    """A concrete requirement extracted from a regulation chunk."""

    id: str
    source_id: str
    chunk_id: str
    text: str
    article_id: str = ""
    section_path: list[str] = field(default_factory=list)
    obligation_type: str = "shall"  # shall | should | may | must_not | definition
    actors: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    effective_date: str | None = None
    superseded_by: str | None = None
    confidence: float = 0.8
    created_at: str = field(default_factory=lambda: _now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "chunk_id": self.chunk_id,
            "text": self.text,
            "article_id": self.article_id,
            "section_path": list(self.section_path),
            "obligation_type": self.obligation_type,
            "actors": list(self.actors),
            "topics": list(self.topics),
            "effective_date": self.effective_date,
            "superseded_by": self.superseded_by,
            "confidence": self.confidence,
            "created_at": self.created_at,
        }


@dataclass
class ObligationEdge:
    """A typed relationship between two obligations or a regulation."""

    id: str
    source_id: str
    target_id: str
    edge_type: str  # refines | supersedes | contradicts | derived_from | related_to
    weight: float = 1.0
    provenance: str = ""
    created_at: str = field(default_factory=lambda: _now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "edge_type": self.edge_type,
            "weight": self.weight,
            "provenance": self.provenance,
            "created_at": self.created_at,
        }


@dataclass
class TenantAnnotation:
    """Tenant-specific override or note attached to a chunk or obligation."""

    id: str
    tenant_id: str
    target_type: str  # chunk | obligation | regulation
    target_id: str
    annotation_type: str  # note | override | applicability | exemption | mapping
    payload: dict[str, Any] = field(default_factory=dict)
    created_by: str = ""
    created_at: str = field(default_factory=lambda: _now())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "annotation_type": self.annotation_type,
            "payload": dict(self.payload),
            "created_by": self.created_by,
            "created_at": self.created_at,
        }


@dataclass
class IngestionJob:
    """A single continuous-ingestion run."""

    id: str
    source_id: str
    status: str  # pending | running | success | failed | cancelled
    trigger: str  # scheduled | manual | startup
    started_at: str | None = None
    finished_at: str | None = None
    previous_hash: str | None = None
    new_hash: str | None = None
    chunks_added: int = 0
    chunks_removed: int = 0
    obligations_added: int = 0
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "status": self.status,
            "trigger": self.trigger,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "previous_hash": self.previous_hash,
            "new_hash": self.new_hash,
            "chunks_added": self.chunks_added,
            "chunks_removed": self.chunks_removed,
            "obligations_added": self.obligations_added,
            "error_message": self.error_message,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def new(
        cls, source_id: str, trigger: str = "manual", metadata: dict[str, Any] | None = None
    ) -> "IngestionJob":
        return cls(
            id=_uuid(),
            source_id=source_id,
            status="pending",
            trigger=trigger,
            metadata=metadata or {},
        )


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _uuid() -> str:
    return uuid.uuid4().hex[:16]


def content_hash(texts: list[str]) -> str:
    """Stable SHA-256 over ordered texts."""
    h = hashlib.sha256()
    for t in texts:
        h.update(t.encode("utf-8"))
        h.update(b"\x1e")
    return h.hexdigest()
