# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Phase 4 perfect regulatory corpus: indices, obligation graph, tenant annotations, continuous ingestion."""

from __future__ import annotations

from .models import (
    IngestionJob,
    Obligation,
    ObligationEdge,
    Regulation,
    TenantAnnotation,
)
from .index import RegulationIndex
from .obligation_graph import build_graph_for_document, derive_edges, extract_obligations
from .repository import CorpusRepository
from .scheduler import IngestionScheduler

__all__ = [
    "CorpusRepository",
    "IngestionJob",
    "IngestionScheduler",
    "Obligation",
    "ObligationEdge",
    "Regulation",
    "RegulationIndex",
    "TenantAnnotation",
    "build_graph_for_document",
    "derive_edges",
    "extract_obligations",
]
