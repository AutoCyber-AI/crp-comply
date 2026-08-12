"""Tests for the RAG layer — embedder contract + index round-trip + top-k.

These tests avoid downloading a real sentence-transformers model so they run
offline in CI. A tiny ``FakeEmbedder`` produces deterministic unit vectors;
the index should not care what embedder produced the data.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from crp_comply.agent.corpus import CorpusChunk, CorpusDocument  # noqa: E402
from crp_comply.agent.rag.index import CorpusIndex, _doc_from_json  # noqa: E402


DIM = 16


def _unit(vec: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(vec)
    return vec if n == 0 else vec / n


def _encode_fake(text: str) -> np.ndarray:
    """Cheap deterministic embedding: char-bucket bag-of-chars -> unit vec."""
    v = np.zeros(DIM, dtype=np.float32)
    for ch in text.lower():
        v[ord(ch) % DIM] += 1.0
    return _unit(v).astype(np.float32)


def _encode_many(texts):
    return np.vstack([_encode_fake(t) for t in texts]).astype(np.float32)


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
                section_path=("test", cid),
                tags={"kind": "unit-test"},
            )
        )
    doc.finalise()
    return doc


@pytest.fixture
def tmp_index(tmp_path) -> CorpusIndex:
    db = tmp_path / "corpus.sqlite"
    return CorpusIndex(db_path=db)


# ------------------------------------------------------------------ schema --


def test_index_starts_empty(tmp_index):
    stats = tmp_index.stats()
    assert stats["total_chunks"] == 0
    assert stats["sources"] == []


def test_upsert_document_roundtrip(tmp_index):
    doc = _make_doc("reg_a", [("art1", "foo bar baz"), ("art2", "hello world")])
    vecs = _encode_many([c.text for c in doc.chunks])
    n = tmp_index.upsert_document(doc, vecs, embedding_model="fake-dim16")
    assert n == 2

    stats = tmp_index.stats()
    assert stats["total_chunks"] == 2
    assert stats["sources"][0]["source_id"] == "reg_a"
    assert stats["sources"][0]["chunk_count"] == 2
    assert stats["embedding_profiles"] == [{"dim": DIM, "model": "fake-dim16"}]


def test_upsert_replaces_prior_chunks(tmp_index):
    doc1 = _make_doc("reg_a", [("x", "first version")])
    vecs1 = _encode_many([c.text for c in doc1.chunks])
    tmp_index.upsert_document(doc1, vecs1, embedding_model="fake")

    # Second doc with same source_id but different chunk ids should replace.
    doc2 = _make_doc("reg_a", [("y", "second"), ("z", "second again")])
    vecs2 = _encode_many([c.text for c in doc2.chunks])
    tmp_index.upsert_document(doc2, vecs2, embedding_model="fake")

    stats = tmp_index.stats()
    assert stats["total_chunks"] == 2
    assert stats["sources"][0]["chunk_count"] == 2


def test_dim_mismatch_raises(tmp_index):
    doc = _make_doc("reg_a", [("art1", "text")])
    bad = np.zeros((2, DIM), dtype=np.float32)  # 2 rows, 1 chunk
    with pytest.raises(ValueError):
        tmp_index.upsert_document(doc, bad, embedding_model="fake")


# ------------------------------------------------------------------- query --


def test_query_top_k_ordering(tmp_index):
    doc = _make_doc(
        "reg_a",
        [
            ("a", "human oversight of high-risk AI systems"),
            ("b", "data protection impact assessment"),
            ("c", "post-market monitoring plan"),
        ],
    )
    vecs = _encode_many([c.text for c in doc.chunks])
    tmp_index.upsert_document(doc, vecs, embedding_model="fake")

    q = _encode_fake("human oversight")
    hits = tmp_index.query(q, top_k=3)

    assert len(hits) == 3
    # The most similar chunk should be "a" (shares "human oversight" substring).
    assert hits[0].chunk_id == "reg_a/a"
    # Scores must be monotonically non-increasing.
    for i in range(len(hits) - 1):
        assert hits[i].score >= hits[i + 1].score


def test_query_dim_mismatch(tmp_index):
    doc = _make_doc("reg_a", [("a", "x")])
    vecs = _encode_many([c.text for c in doc.chunks])
    tmp_index.upsert_document(doc, vecs, embedding_model="fake")
    with pytest.raises(ValueError):
        tmp_index.query(np.zeros(DIM + 1, dtype=np.float32), top_k=1)


def test_query_source_filter(tmp_index):
    doc_a = _make_doc("reg_a", [("a", "alpha text")])
    doc_b = _make_doc("reg_b", [("b", "alpha text")])  # identical content
    tmp_index.upsert_document(
        doc_a, _encode_many([c.text for c in doc_a.chunks]), embedding_model="fake"
    )
    tmp_index.upsert_document(
        doc_b, _encode_many([c.text for c in doc_b.chunks]), embedding_model="fake"
    )
    hits = tmp_index.query(_encode_fake("alpha"), top_k=5, source_filter=["reg_b"])
    assert len(hits) == 1
    assert hits[0].source_id == "reg_b"


def test_query_returns_metadata(tmp_index):
    doc = _make_doc("reg_a", [("art1", "the text")])
    vecs = _encode_many([c.text for c in doc.chunks])
    tmp_index.upsert_document(doc, vecs, embedding_model="fake")
    hit = tmp_index.query(_encode_fake("text"), top_k=1)[0]
    assert hit.title == "art1"
    assert hit.article_id == "art1"
    assert hit.section_path == ["test", "art1"]
    assert hit.tags == {"kind": "unit-test"}


# --------------------------------------------------------------- json rehydrate


def test_doc_from_json_preserves_shape(tmp_path):
    doc = _make_doc("reg_a", [("art1", "first"), ("art2", "second")])
    out = tmp_path / "reg_a.json"
    doc.write_json(out)

    import json as _json

    raw = _json.loads(out.read_text(encoding="utf-8"))
    rehydrated = _doc_from_json(raw)

    assert rehydrated.source_id == doc.source_id
    assert len(rehydrated.chunks) == 2
    assert rehydrated.chunks[0].section_path == ("test", "art1")
    assert rehydrated.chunks[0].tags == {"kind": "unit-test"}


# ------------------------------------------------------------------- embedder


def test_embedder_resolves_env_var(monkeypatch):
    from crp_comply.agent.rag.embedder import _resolve_model_name, DEFAULT_MODEL

    monkeypatch.delenv("CRP_COMPLY_EMBED_MODEL", raising=False)
    assert _resolve_model_name(None) == DEFAULT_MODEL
    monkeypatch.setenv("CRP_COMPLY_EMBED_MODEL", "foo/bar")
    assert _resolve_model_name(None) == "foo/bar"
    assert _resolve_model_name("override/model") == "override/model"


def test_embedder_import_guard(monkeypatch):
    """If sentence-transformers isn't installed we should get a clear error."""
    from crp_comply.agent.rag.embedder import Embedder

    emb = Embedder(model_name="BAAI/irrelevant")

    # Simulate missing dependency by poisoning the import cache.
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    with pytest.raises(RuntimeError, match="sentence-transformers is not installed"):
        emb._ensure_loaded()


def test_cli_parser_smoke():
    from crp_comply.agent.rag.__main__ import build_parser

    parser = build_parser()
    args = parser.parse_args(["build", "--only", "nist_ai_rmf_core", "-v"])
    assert args.command == "build"
    assert args.only == ["nist_ai_rmf_core"]
    assert args.verbose is True

    args = parser.parse_args(["query", "human oversight", "-k", "3"])
    assert args.command == "query"
    assert args.text == "human oversight"
    assert args.top_k == 3
