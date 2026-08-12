"""Tests for copyright-safe ingest (Phase 4.1c).

Verifies that:
  * Documents with ISO-style licenses get their chunk bodies redacted.
  * Documents with free-reuse licenses are left untouched.
  * The redaction surrogate preserves clause id + title for retrieval.
  * ``content_hash`` is recomputed over surrogates.
"""

from __future__ import annotations

from crp_comply.agent.corpus import CorpusChunk, CorpusDocument
from crp_comply.agent.copyright import (
    RESTRICTED_LICENSES,
    is_restricted,
    redact_chunk,
    redact_document,
)


def _make_chunk(
    *,
    chunk_id: str = "iso_42001/sec_0",
    text: str = "The organization shall establish, implement, maintain and continually improve an AI management system.",
    title: str = "4.4 AI management system",
    article_id: str = "4.4",
) -> CorpusChunk:
    return CorpusChunk(
        id=chunk_id,
        text=text,
        title=title,
        article_id=article_id,
        section_path=("section", article_id),
        tags={"kind": "pdf_section"},
    )


def _build_doc(license_: str, *, source_id: str = "iso_42001") -> CorpusDocument:
    doc = CorpusDocument.new(
        source_id=source_id,
        source_url="https://www.iso.org/standard/81230.html",
        jurisdiction="INTL",
        version="2023",
        license=license_,
        notes="ISO/IEC 42001:2023",
    )
    doc.add(
        _make_chunk(
            chunk_id=f"{source_id}/sec_0",
            text="The organization shall establish, implement, maintain and continually improve an AI management system.",
            title="4.4 AI management system",
            article_id="4.4",
        )
    )
    doc.add(
        _make_chunk(
            chunk_id=f"{source_id}/sec_1",
            text="Top management shall demonstrate leadership and commitment with respect to the AI management system.",
            title="5.1 Leadership and commitment",
            article_id="5.1",
        )
    )
    doc.finalise()
    return doc


# ---------------------------------------------------------------------------
# RESTRICTED_LICENSES registration
# ---------------------------------------------------------------------------


def test_iso_license_is_restricted():
    assert "ISO-copyright" in RESTRICTED_LICENSES
    assert is_restricted("ISO-copyright")
    assert is_restricted("third-party-commentary")


def test_eu_license_is_not_restricted():
    assert not is_restricted("EU-free-reuse")
    assert not is_restricted("US-public-domain")
    assert not is_restricted("OGL-v3")


# ---------------------------------------------------------------------------
# redact_chunk — body removed, structure kept
# ---------------------------------------------------------------------------


def test_redact_chunk_removes_body_keeps_metadata():
    original = _make_chunk()
    redacted = redact_chunk(original, source_id="iso_42001")

    assert "shall establish" not in redacted.text
    assert "continually improve" not in redacted.text

    assert "4.4 AI management system" in redacted.text
    assert "ISO 42001" in redacted.text or "iso_42001" in redacted.text.lower()

    assert "redacted" in redacted.text.lower()

    assert redacted.tags["copyright"] == "restricted"
    assert redacted.tags["verbatim_stored"] == "false"
    assert int(redacted.tags["word_count"]) > 0


# ---------------------------------------------------------------------------
# redact_document — end-to-end
# ---------------------------------------------------------------------------


def test_redact_document_iso_removes_all_bodies():
    doc = _build_doc("ISO-copyright")
    original_hash = doc.content_hash
    originals = [c.text for c in doc.chunks]

    redact_document(doc)

    for chunk, original_text in zip(doc.chunks, originals):
        assert original_text not in chunk.text
        assert chunk.tags["copyright"] == "restricted"

    assert doc.content_hash != original_hash
    assert doc.content_hash

    assert "copyright-restricted" in (doc.notes or "")


def test_redact_document_eu_is_noop():
    doc = _build_doc("EU-free-reuse", source_id="eu_ai_act")
    original_texts = [c.text for c in doc.chunks]
    original_hash = doc.content_hash

    redact_document(doc)

    for chunk, original_text in zip(doc.chunks, original_texts):
        assert chunk.text == original_text
        assert "copyright" not in (chunk.tags or {})

    assert doc.content_hash == original_hash
    assert "copyright-restricted" not in (doc.notes or "")


def test_redact_document_third_party_commentary_is_redacted():
    doc = _build_doc("third-party-commentary", source_id="iso_42001_explainer")
    redact_document(doc)
    for chunk in doc.chunks:
        assert chunk.tags["copyright"] == "restricted"
        assert "redacted" in chunk.text.lower()
