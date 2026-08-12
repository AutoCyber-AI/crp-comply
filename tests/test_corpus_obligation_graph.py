"""Tests for Phase 4 obligation graph extraction."""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from crp_comply.agent.corpus import CorpusChunk, CorpusDocument
from crp_comply.corpus.obligation_graph import (
    build_graph_for_document,
    derive_edges,
    extract_obligations,
)
from crp_comply.corpus.repository import CorpusRepository


def _make_doc() -> CorpusDocument:
    doc = CorpusDocument.new(
        source_id="test_reg",
        source_url="local://test",
        jurisdiction="TEST",
        version="1.0",
        license="CC-BY-4.0",
    )
    doc.add(
        CorpusChunk(
            id="test_reg/art1",
            text="Providers shall ensure risk management systems are established.",
            article_id="art1",
        )
    )
    doc.add(
        CorpusChunk(
            id="test_reg/art2",
            text="Deployers must monitor the AI system in operation. Providers should maintain technical documentation.",
            article_id="art2",
        )
    )
    doc.finalise()
    return doc


def test_extract_obligations_finds_shall_and_must() -> None:
    doc = _make_doc()
    obs = extract_obligations(doc)
    texts = " ".join(o.text.lower() for o in obs)
    assert "shall ensure" in texts
    assert "must monitor" in texts
    assert "should maintain" in texts


def test_extract_obligations_fallback_definition() -> None:
    doc = CorpusDocument.new(
        source_id="def_reg",
        source_url="local://def",
        jurisdiction="TEST",
        version="1.0",
        license="CC-BY-4.0",
    )
    doc.add(
        CorpusChunk(
            id="def_reg/scope",
            text="This regulation applies to providers of artificial intelligence systems placed on the market.",
            article_id="scope",
        )
    )
    doc.finalise()
    obs = extract_obligations(doc)
    assert len(obs) == 1
    assert obs[0].obligation_type == "definition"


def test_derive_edges_same_article_and_chunk() -> None:
    doc = _make_doc()
    obs = extract_obligations(doc)
    edges = derive_edges(obs)
    # Should have intra-chunk related_to edges for art2 (2 obligations).
    same_chunk_edges = [e for e in edges if e.provenance == "same_chunk"]
    assert len(same_chunk_edges) >= 1
    # All edge weights are positive.
    assert all(e.weight > 0 for e in edges)


def test_build_graph_for_document_is_idempotent(tmp_path) -> None:
    repo = CorpusRepository(db_path=tmp_path / "corpus.sqlite")
    doc = _make_doc()
    n1, e1 = build_graph_for_document(doc, repo)
    n2, e2 = build_graph_for_document(doc, repo)
    assert n1 == n2
    assert e1 == e2
    repo.close()
