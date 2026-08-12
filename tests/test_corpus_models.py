"""Tests for Phase 4 corpus models."""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from crp_comply.corpus.models import (
    IngestionJob,
    Obligation,
    ObligationEdge,
    Regulation,
    TenantAnnotation,
    content_hash,
)


def test_content_hash_stable() -> None:
    assert content_hash(["a", "b"]) == content_hash(["a", "b"])
    assert content_hash(["a", "b"]) != content_hash(["b", "a"])


def test_regulation_to_dict_roundtrip() -> None:
    reg = Regulation(
        source_id="eu_ai_act",
        title="EU AI Act",
        jurisdiction="EU",
        version="1.0",
        canonical_url="https://example.com",
        license="EU-free-reuse",
        chunk_count=42,
    )
    d = reg.to_dict()
    assert d["source_id"] == "eu_ai_act"
    assert d["chunk_count"] == 42


def test_ingestion_job_defaults() -> None:
    job = IngestionJob.new("eu_ai_act", trigger="manual")
    assert job.status == "pending"
    assert job.source_id == "eu_ai_act"
    assert job.trigger == "manual"
    assert len(job.id) == 16


def test_obligation_to_dict() -> None:
    ob = Obligation(
        id="obl:1234",
        source_id="eu_ai_act",
        chunk_id="eu_ai_act/art1",
        text="Providers shall ensure...",
        obligation_type="shall",
        actors=["provider"],
        topics=["risk"],
    )
    d = ob.to_dict()
    assert d["obligation_type"] == "shall"
    assert d["actors"] == ["provider"]


def test_edge_to_dict() -> None:
    edge = ObligationEdge(id="edge:1", source_id="obl:a", target_id="obl:b", edge_type="refines")
    assert edge.to_dict()["edge_type"] == "refines"


def test_annotation_to_dict() -> None:
    ann = TenantAnnotation(
        id="ann:1",
        tenant_id="tenant-a",
        target_type="chunk",
        target_id="chunk-1",
        annotation_type="mapping",
        payload={"framework": "iso27001"},
    )
    assert ann.to_dict()["payload"]["framework"] == "iso27001"
