"""Tests for Phase 4 corpus repository."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from crp_comply.corpus.models import (
    IngestionJob,
    Obligation,
    ObligationEdge,
    Regulation,
    TenantAnnotation,
)
from crp_comply.corpus.repository import CorpusRepository


@pytest.fixture
def tmp_repo(tmp_path):
    db = tmp_path / "corpus.sqlite"
    repo = CorpusRepository(db_path=db)
    yield repo
    repo.close()


def test_regulation_crud(tmp_repo) -> None:
    reg = Regulation(
        source_id="eu_ai_act",
        title="EU AI Act",
        jurisdiction="EU",
        version="abc123",
        canonical_url="https://eur-lex.europa.eu/ai-act",
        license="EU-free-reuse",
        chunk_count=10,
    )
    tmp_repo.upsert_regulation(reg)
    got = tmp_repo.get_regulation("eu_ai_act")
    assert got is not None
    assert got.version == "abc123"
    assert tmp_repo.list_regulations()[0].source_id == "eu_ai_act"


def test_obligation_and_edge_crud(tmp_repo) -> None:
    ob = Obligation(
        id="obl:1",
        source_id="eu_ai_act",
        chunk_id="c1",
        text="Providers shall do X",
        article_id="art9",
        obligation_type="shall",
    )
    tmp_repo.upsert_obligation(ob)
    got = tmp_repo.get_obligation("obl:1")
    assert got is not None
    assert got.article_id == "art9"

    edge = ObligationEdge(id="edge:1", source_id="obl:1", target_id="obl:2", edge_type="refines")
    tmp_repo.upsert_edge(edge)
    neighbors = tmp_repo.graph_neighbors("obl:1")
    assert len(neighbors["outgoing"]) == 1
    assert neighbors["outgoing"][0].target_id == "obl:2"


def test_delete_obligations_for_source(tmp_repo) -> None:
    tmp_repo.upsert_obligation(Obligation(id="o1", source_id="s1", chunk_id="c1", text="t1"))
    tmp_repo.upsert_obligation(Obligation(id="o2", source_id="s2", chunk_id="c2", text="t2"))
    assert tmp_repo.delete_obligations_for_source("s1") == 1
    assert tmp_repo.get_obligation("o1") is None
    assert tmp_repo.get_obligation("o2") is not None


def test_tenant_annotation_crud(tmp_repo) -> None:
    ann = TenantAnnotation(
        id="a1",
        tenant_id="tenant-1",
        target_type="chunk",
        target_id="c1",
        annotation_type="mapping",
        payload={"note": "maps to ISO 5.1"},
    )
    tmp_repo.upsert_annotation(ann)
    results = tmp_repo.list_annotations("tenant-1")
    assert len(results) == 1
    assert results[0].payload["note"] == "maps to ISO 5.1"


def test_ingestion_job_crud(tmp_repo) -> None:
    job = IngestionJob.new("eu_ai_act", trigger="scheduled")
    job.started_at = "2026-01-01T00:00:00Z"
    job.status = "running"
    tmp_repo.create_job(job)
    got = tmp_repo.get_job(job.id)
    assert got is not None
    assert got.trigger == "scheduled"

    job.status = "success"
    job.finished_at = "2026-01-01T00:01:00Z"
    job.chunks_added = 5
    tmp_repo.update_job(job)
    got2 = tmp_repo.get_job(job.id)
    assert got2.status == "success"
    assert got2.chunks_added == 5
    assert len(tmp_repo.list_jobs(source_id="eu_ai_act")) == 1
