"""ISO PDF loader — copyright-safe with output-boundary redaction.

ISO/IEC standards are copyrighted by ISO. Per ISO's licensing terms we
**must not redistribute** or serve verbatim ISO text through a SaaS, but
we *do* hold a single licensed copy locally for internal recipe authoring
and higher-quality semantic retrieval.

This loader:

1. Reads PDFs from ``corpus/iso/<standard>/*.pdf`` (the user drops them).
2. Parses them via :func:`parse_pdf_to_document` using an ISO clause regex.
3. **Calls** :func:`crp_comply.agent.copyright.tag_document_restricted` —
   chunks are *tagged* ``copyright='restricted'`` while the full prose is
   retained on disk for embedding and internal use.
4. Emits :class:`CorpusDocument` with ``license='ISO-copyright'`` and
   ``tags['copyright']='restricted'`` on every chunk, so every API/LLM
   boundary can substitute :func:`copyright.surrogate_chunk_for_response`
   structurally.

What the agent sees per ISO chunk *at the tool boundary* (after surrogate):
    "ISO 42001 6.1.3. Statement of Applicability. Section path: 6 / 6.1.
     [body redacted under iso_42001 copyright — ~312 words in source;
      see official publication]"

The full clause body remains in the RAG index for embedding match quality
and for our own engineering team's recipe authoring; it never reaches the
LLM context or HTTP responses.
Its narrative draws on the LLM's own training knowledge of the standard and
on the user-provided facts, with a citation back to the clause.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..copyright import tag_document_restricted
from ..corpus import CorpusDocument, corpus_dir
from .pdf_parser import parse_pdf_to_document

logger = logging.getLogger(__name__)


# ISO clause headings: 1, 1.2, 1.2.3 followed by whitespace + Title Case
ISO_HEADING = r"^\s*(?:\d+(?:\.\d+){0,3})\s+[A-Z][^\n]{0,120}$"


ISO_SPECS: list[dict] = [
    {
        "source_id": "iso_42001",
        "version": "2023",
        "title": "ISO/IEC 42001:2023 — AI Management System",
        "publisher_url": "https://www.iso.org/standard/81230.html",
        "dir": ("iso", "42001"),
        "primary": "official.pdf",
    },
    {
        "source_id": "iso_22989",
        "version": "2022",
        "title": "ISO/IEC 22989:2022 — AI Concepts and Terminology",
        "publisher_url": "https://www.iso.org/standard/74296.html",
        "dir": ("iso", "22989"),
        "primary": "official.pdf",
    },
    {
        "source_id": "iso_23894",
        "version": "2023",
        "title": "ISO/IEC 23894:2023 — AI Risk Management",
        "publisher_url": "https://www.iso.org/standard/77304.html",
        "dir": ("iso", "23894"),
        "primary": "official.pdf",
    },
    {
        "source_id": "iso_23053",
        "version": "2022",
        "title": "ISO/IEC 23053:2022 — Framework for AI systems using ML",
        "publisher_url": "https://www.iso.org/standard/74438.html",
        "dir": ("iso", "23053"),
        "primary": "official.pdf",
        "enterprise_only": True,
    },
    {
        "source_id": "iso_27001",
        "version": "2022",
        "title": "ISO/IEC 27001:2022 — Information Security Management",
        "publisher_url": "https://www.iso.org/standard/27001",
        "dir": ("iso", "27001"),
        "primary": "official.pdf",
        "enterprise_only": True,
    },
]


def _ingest_one_pdf(
    path: Path,
    *,
    source_id: str,
    version: str,
    license_tag: str,
    title_note: str,
    publisher_url: str,
) -> CorpusDocument:
    """Parse one ISO PDF and immediately redact its body text."""
    doc = parse_pdf_to_document(
        path,
        source_id=source_id,
        source_url=f"publisher:{publisher_url}",
        jurisdiction="ISO",
        version=version,
        license=license_tag,
        notes=f"{title_note}. Local file: {path.as_posix()}",
        heading_pattern=ISO_HEADING,
    )
    return tag_document_restricted(doc)


def load_iso_document(spec: dict) -> CorpusDocument | None:
    """Load a single ISO PDF spec. Returns None if the PDF isn't present yet."""
    base = corpus_dir().joinpath(*spec["dir"])
    primary = base / spec["primary"]
    if not primary.exists():
        logger.warning(
            "%s not found at %s — skip. Drop the official PDF there to ingest.",
            spec["source_id"],
            primary,
        )
        return None

    doc = _ingest_one_pdf(
        primary,
        source_id=spec["source_id"],
        version=spec["version"],
        license_tag="ISO-copyright",
        title_note=spec["title"],
        publisher_url=spec["publisher_url"],
    )

    # Also ingest any explainer PDFs in the same directory — tagged as
    # third-party-commentary, which is also treated as restricted by the
    # redactor until we have explicit redistribution permission from the
    # explainer's author.
    explainers: list[CorpusDocument] = []
    for extra in sorted(base.glob("*.pdf")):
        if extra.name == spec["primary"]:
            continue
        ex_doc = _ingest_one_pdf(
            extra,
            source_id=f"{spec['source_id']}_explainer_{extra.stem}",
            version=spec["version"],
            license_tag="third-party-commentary",
            title_note=f"Explainer/companion to {spec['title']}",
            publisher_url=spec["publisher_url"],
        )
        explainers.append(ex_doc)

    doc._explainers = explainers  # type: ignore[attr-defined]
    return doc


def load_all(include_enterprise: bool = False) -> list[CorpusDocument]:
    out: list[CorpusDocument] = []
    for spec in ISO_SPECS:
        if spec.get("enterprise_only") and not include_enterprise:
            continue
        doc = load_iso_document(spec)
        if doc is None:
            continue
        out.append(doc)
        for ex in getattr(doc, "_explainers", []):
            out.append(ex)
    return out
