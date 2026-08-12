"""PDF → :class:`CorpusDocument` parser.

Uses ``pdfplumber`` (optional dep). Generic heading detection falls back to
a simple heuristic: uppercase lines <= 80 chars start a new section. A
regulation-specific ``heading_pattern`` overrides that — for NIST AI RMF we
key on ``GOVERN / MAP / MEASURE / MANAGE``; for ISO 42001 we key on clause
numbering like ``^\\d+(\\.\\d+)*\\s``.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ..corpus import CorpusChunk, CorpusDocument
from ..scrapers.base import chunk_by_token_budget, normalize_ws, safe_id

logger = logging.getLogger(__name__)


def _require_pdfplumber():
    try:
        import pdfplumber  # type: ignore

        return pdfplumber
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "pdfplumber is required to parse PDFs. Install with: "
            "pip install 'crp-comply[agent]' or pip install pdfplumber"
        ) from exc


def _extract_text(path: Path) -> list[str]:
    """Return a list of page texts."""
    pdfplumber = _require_pdfplumber()
    pages: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages.append(text)
    return pages


def _split_sections(
    full_text: str,
    heading_pattern: str | None,
) -> list[tuple[str, str]]:
    """Split text into (heading, body) sections.

    If ``heading_pattern`` is provided, lines matching it become new
    sections. Otherwise we use a fallback: lines that are ALL CAPS or start
    with a clause number (1.2.3).
    """
    if heading_pattern:
        heading_re = re.compile(heading_pattern, re.MULTILINE)
    else:
        # ISO-style clause numbers or ALL CAPS short lines.
        heading_re = re.compile(
            r"^(?:\d+(?:\.\d+){0,3}\s+[A-Z][^\n]{0,100}|[A-Z][A-Z0-9 \-,]{4,80})$",
            re.MULTILINE,
        )

    sections: list[tuple[str, str]] = []
    last_end = 0
    last_heading = "Preamble"
    for m in heading_re.finditer(full_text):
        body = full_text[last_end : m.start()].strip()
        # Keep heading even if body is empty — preserves section chain for TOCs.
        sections.append((last_heading, body))
        last_heading = normalize_ws(m.group(0))[:150]
        last_end = m.end()
    tail = full_text[last_end:].strip()
    sections.append((last_heading, tail))
    return sections or [("Body", full_text.strip())]


def parse_pdf_to_document(
    path: Path,
    *,
    source_id: str,
    source_url: str,
    jurisdiction: str,
    version: str,
    license: str,
    notes: str = "",
    heading_pattern: str | None = None,
) -> CorpusDocument:
    """Parse a local PDF into a :class:`CorpusDocument`."""
    logger.info("parsing PDF %s (%s)", path.name, source_id)
    pages = _extract_text(path)
    full_text = "\n\n".join(p for p in pages if p)
    if not full_text.strip():
        raise RuntimeError(f"PDF {path} produced no text — is it scanned? OCR required.")

    doc = CorpusDocument.new(
        source_id=source_id,
        source_url=source_url or f"local:{path.as_posix()}",
        jurisdiction=jurisdiction,
        version=version,
        license=license,
        notes=notes,
    )

    sections = _split_sections(full_text, heading_pattern)
    for s_idx, (heading, body) in enumerate(sections):
        # Strip page-number-only lines and duplicate whitespace.
        body = re.sub(r"^\s*\d+\s*$", "", body, flags=re.MULTILINE)
        body = normalize_ws(body)
        if not body:
            continue
        for c_idx, piece in enumerate(chunk_by_token_budget(body, max_tokens=480, overlap=40)):
            doc.add(
                CorpusChunk(
                    id=safe_id(source_id, "sec", s_idx, c_idx),
                    text=piece,
                    title=heading,
                    section_path=("section", str(s_idx)),
                    tags={"kind": "pdf_section", "heading": heading[:80]},
                )
            )

    doc.finalise()
    logger.info(
        "%s: produced %d chunks from %d sections", source_id, len(doc.chunks), len(sections)
    )
    return doc
