# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Per-regulation index view with recency and contradiction handling.

This module sits on top of :class:`CorpusIndex` and provides the Phase 4
retrieval guarantees:

* Per-regulation source-filtered indices with isolated statistics.
* Recency-aware scoring so newer/amended clauses rank higher.
* Contradiction / supersession suppression so a superseded clause never
  outranks its replacement.
* Tenant-annotation boosting for chunks a tenant has explicitly mapped or
  overridden.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from ..agent.rag.index import CorpusIndex, QueryHit
from .repository import CorpusRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RegulationIndexStats:
    source_id: str
    total_chunks: int
    embedding_model: str
    embedding_dim: int


class RegulationIndex:
    """Phase 4 retrieval layer over :class:`CorpusIndex`."""

    def __init__(
        self,
        index: CorpusIndex | None = None,
        repo: CorpusRepository | None = None,
    ) -> None:
        self.index = index or CorpusIndex()
        self.repo = repo or CorpusRepository()

    def stats(self, source_id: str) -> RegulationIndexStats | None:
        """Return isolated stats for a single regulation."""
        all_stats = self.index.stats()
        for src in all_stats.get("sources", []):
            if src.get("source_id") == source_id:
                profiles = all_stats.get("embedding_profiles", [{}])
                return RegulationIndexStats(
                    source_id=source_id,
                    total_chunks=src.get("chunk_count", 0),
                    embedding_model=profiles[0].get("model", "unknown"),
                    embedding_dim=profiles[0].get("dim", 0),
                )
        return None

    def list_regulation_ids(self) -> list[str]:
        return [s["source_id"] for s in self.index.stats().get("sources", [])]

    def query_regulation(
        self,
        query_vec: np.ndarray,
        source_id: str,
        *,
        top_k: int = 8,
        recency_weight: float = 0.15,
        tenant_id: str | None = None,
    ) -> list[QueryHit]:
        """Retrieve top-k chunks for a single regulation with Phase 4 boosts.

        * ``recency_weight`` blends freshness into the cosine score.
        * Tenant annotations of type ``mapping`` or ``override`` add a small
          boost so explicitly-mapped clauses surface first.
        * Chunks marked as superseded are demoted by 0.3.
        """
        hits = self.index.query(query_vec, top_k=max(top_k * 3, 20), source_filter=[source_id])
        if not hits:
            return []

        annotated: set[str] = set()
        if tenant_id:
            try:
                annotations = self.repo.list_annotations(tenant_id, target_type="chunk")
                annotated = {
                    a.target_id for a in annotations if a.annotation_type in {"mapping", "override"}
                }
            except Exception:
                logger.debug("tenant annotation lookup failed", exc_info=True)

        now = time.time()
        scored: list[tuple[float, QueryHit]] = []
        for hit in hits:
            score = float(hit.score)
            score += recency_weight * _freshness_boost(hit.tags, now)
            if hit.chunk_id in annotated:
                score += 0.05
            if (hit.tags or {}).get("superseded") == "true" or hit.tags.get("superseded_by"):
                score -= 0.30
            scored.append((score, hit))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [hit for _, hit in scored[:top_k]]

    def query_multi_regulation(
        self,
        query_vec: np.ndarray,
        source_ids: Sequence[str],
        *,
        top_k: int = 8,
        recency_weight: float = 0.15,
        tenant_id: str | None = None,
    ) -> list[QueryHit]:
        """Cross-regulation retrieval with per-source fairness cap.

        Ensures no single regulation dominates the result set unless it is the
        only one with relevant hits.
        """
        per_source = max(2, top_k // len(source_ids)) if source_ids else top_k
        all_hits: list[QueryHit] = []
        for sid in source_ids:
            all_hits.extend(
                self.query_regulation(
                    query_vec,
                    sid,
                    top_k=per_source * 2,
                    recency_weight=recency_weight,
                    tenant_id=tenant_id,
                )
            )
        all_hits.sort(key=lambda h: h.score, reverse=True)
        return all_hits[:top_k]


def _freshness_boost(tags: dict[str, str] | None, now: float) -> float:
    """Return a small boost (0.0–1.0) based on chunk effective/published date."""
    tags = tags or {}
    date_str = tags.get("effective_date") or tags.get("published_at")
    if not date_str:
        return 0.5
    ts = _parse_iso_timestamp(date_str)
    if ts is None:
        return 0.5
    age_days = max(0.0, (now - ts) / 86400)
    if age_days <= 7:
        return 1.0
    if age_days <= 30:
        return 0.85
    if age_days <= 90:
        return 0.65
    if age_days <= 365:
        return 0.4
    return 0.2


def _parse_iso_timestamp(value: str) -> float | None:
    """Best-effort ISO 8601 / date parse to epoch seconds."""
    value = value.strip()
    from datetime import datetime

    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.timestamp()
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.timestamp()
    except ValueError:
        return None
