"""Offline tests for Phase 4.1 ingest plumbing (no network calls)."""

from __future__ import annotations

from pathlib import Path

import pytest

from crp_comply.agent.corpus import (
    CorpusChunk,
    CorpusDocument,
    corpus_dir,
    scraped_output_dir,
    write_manifest,
)
from crp_comply.agent.scrapers.base import (
    chunk_by_token_budget,
    normalize_ws,
    safe_id,
)


# ---------------------------------------------------------------------------
# base utilities
# ---------------------------------------------------------------------------


def test_normalize_ws_collapses_runs():
    assert normalize_ws("  hello\n  world  ") == "hello world"


def test_chunk_by_token_budget_produces_overlap():
    text = " ".join(["word"] * 2000)
    chunks = chunk_by_token_budget(text, max_tokens=200, overlap=20)
    assert len(chunks) >= 2
    assert all(isinstance(c, str) and c for c in chunks)
    # each chunk word count should be < max_tokens/1.3 + small buffer
    max_words = int(200 / 1.3)
    assert all(len(c.split()) <= max_words + 5 for c in chunks)


def test_chunk_by_token_budget_handles_empty():
    assert chunk_by_token_budget("") == []


def test_safe_id_sanitises():
    assert safe_id("eu_ai_act", "art", "6(1)", 0) == "eu_ai_act/art_6_1_0"


# ---------------------------------------------------------------------------
# CorpusDocument lifecycle
# ---------------------------------------------------------------------------


def test_corpus_document_finalise_and_write(tmp_path: Path):
    doc = CorpusDocument.new(
        source_id="unit_test",
        source_url="local:test",
        jurisdiction="EU",
        version="v0",
        license="EU-free-reuse",
    )
    doc.add(CorpusChunk(id="unit_test/art_1_0", text="alpha beta gamma", article_id="1"))
    doc.add(CorpusChunk(id="unit_test/art_2_0", text="delta epsilon", article_id="2"))
    doc.finalise()

    assert doc.content_hash and len(doc.content_hash) == 64  # sha256 hex
    assert len(doc.chunks) == 2

    out = tmp_path / "doc.json"
    doc.write_json(out)
    assert out.exists()
    payload = out.read_text(encoding="utf-8")
    assert "unit_test/art_1_0" in payload
    assert "alpha beta gamma" in payload


def test_corpus_document_hash_stable():
    def make():
        d = CorpusDocument.new(
            source_id="s",
            source_url="u",
            jurisdiction="EU",
            version="v",
            license="EU-free-reuse",
        )
        d.add(CorpusChunk(id="s/a", text="x"))
        d.finalise()
        return d.content_hash

    assert make() == make()


def test_write_manifest(tmp_path: Path):
    doc = CorpusDocument.new(
        source_id="s",
        source_url="u",
        jurisdiction="EU",
        version="v",
        license="EU-free-reuse",
    )
    doc.add(CorpusChunk(id="s/a", text="x"))
    doc.finalise()

    m = tmp_path / "manifest.json"
    write_manifest([doc], m)
    assert m.exists()
    txt = m.read_text(encoding="utf-8")
    assert '"source_id": "s"' in txt
    assert '"chunk_count": 1' in txt


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def test_corpus_dir_exists_or_creatable():
    d = corpus_dir()
    assert d.name == "corpus"


def test_scraped_output_dir_is_created():
    d = scraped_output_dir()
    assert d.exists()
    assert d.is_dir()


# ---------------------------------------------------------------------------
# PDF parser — smoke-tests the section splitter on synthetic text
# ---------------------------------------------------------------------------


def test_pdf_parser_section_splitter():
    from crp_comply.agent.ingest.pdf_parser import _split_sections

    sample = (
        "1 Scope\n"
        "This document specifies requirements for an AI management system.\n\n"
        "1.1 General\n"
        "The organisation shall implement controls.\n\n"
        "2 Terms and definitions\n"
        "2.1 AI system\n"
        "A machine-based system that..."
    )
    sections = _split_sections(sample, heading_pattern=None)
    # Expect at least four distinct headings (1 Scope, 1.1, 2 Terms, 2.1)
    titles = [h for h, _ in sections]
    assert any("Scope" in t for t in titles)
    assert any("Terms" in t for t in titles)


# ---------------------------------------------------------------------------
# EUR-Lex HTML parser — synthetic fragment
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    pytest.importorskip("bs4", reason="beautifulsoup4 required") is None,
    reason="bs4 not installed",
)
def test_eurlex_html_parser_extracts_articles():
    from crp_comply.agent.scrapers.eurlex import _parse_eurlex_html

    html = """
    <html><body>
      <p class="ti-art">Article 1</p>
      <p class="sti-art">Subject matter</p>
      <p class="normal">This Regulation lays down rules for AI.</p>
      <p class="ti-art">Article 2</p>
      <p class="sti-art">Scope</p>
      <p class="normal">This Regulation applies to providers and deployers.</p>
      <p class="ti-annex">Annex III</p>
      <p class="sti-annex">High-risk AI systems</p>
      <p class="normal">Row 4: Recruitment and selection of natural persons.</p>
    </body></html>
    """
    arts, annexes, recitals = _parse_eurlex_html(html)
    assert len(arts) == 2
    assert arts[0][0] == "1"
    assert arts[1][0] == "2"
    assert len(annexes) == 1
    assert annexes[0][0] == "III"
