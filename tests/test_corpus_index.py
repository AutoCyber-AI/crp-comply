"""Tests for Phase 4 RegulationIndex retrieval layer."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from crp_comply.agent.corpus import CorpusChunk, CorpusDocument
from crp_comply.agent.rag.index import CorpusIndex
from crp_comply.corpus.index import RegulationIndex


DIM = 16


def _unit(vec: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(vec)
    return vec if n == 0 else vec / n


def _encode(text: str) -> np.ndarray:
    v = np.zeros(DIM, dtype=np.float32)
    for ch in text.lower():
        v[ord(ch) % DIM] += 1.0
    return _unit(v).astype(np.float32)


def _make_doc(source_id: str, chunks: list[tuple[str, str]]) -> CorpusDocument:
    doc = CorpusDocument.new(
        source_id=source_id,
        source_url=f"local://{source_id}",
        jurisdiction="TEST",
        version="1.0",
        license="CC-BY-4.0",
    )
    for cid, text in chunks:
        doc.add(
            CorpusChunk(
                id=f"{source_id}/{cid}",
                text=text,
                title=cid,
                article_id=cid,
            )
        )
    doc.finalise()
    return doc


@pytest.fixture
def tmp_index(tmp_path):
    db = tmp_path / "corpus.sqlite"
    index = CorpusIndex(db_path=db)
    doc_a = _make_doc("reg_a", [("art1", "foo bar baz"), ("art2", "hello world")])
    doc_b = _make_doc("reg_b", [("art1", "alpha beta gamma"), ("art2", "delta epsilon")])
    vecs_a = np.vstack([_encode(c.text) for c in doc_a.chunks])
    vecs_b = np.vstack([_encode(c.text) for c in doc_b.chunks])
    index.upsert_document(doc_a, vecs_a, embedding_model="fake")
    index.upsert_document(doc_b, vecs_b, embedding_model="fake")
    yield index
    index.close()


def test_regulation_index_stats(tmp_index) -> None:
    reg_index = RegulationIndex(index=tmp_index)
    stats = reg_index.stats("reg_a")
    assert stats is not None
    assert stats.total_chunks == 2


def test_query_regulation_is_isolated(tmp_index) -> None:
    reg_index = RegulationIndex(index=tmp_index)
    q = _encode("foo bar")
    hits = reg_index.query_regulation(q, "reg_a", top_k=2)
    assert len(hits) == 2
    assert all(h.source_id == "reg_a" for h in hits)


def test_query_multi_regulation_fairness(tmp_index) -> None:
    reg_index = RegulationIndex(index=tmp_index)
    q = _encode("alpha beta")
    hits = reg_index.query_multi_regulation(q, ["reg_a", "reg_b"], top_k=2)
    assert len(hits) <= 2
    source_ids = {h.source_id for h in hits}
    assert "reg_b" in source_ids
