"""Generic HTML → :class:`CorpusDocument` parser."""

from __future__ import annotations

import logging
from pathlib import Path

from ..corpus import CorpusChunk, CorpusDocument
from ..scrapers.base import chunk_by_token_budget, normalize_ws, safe_id

logger = logging.getLogger(__name__)


def _extract_text(path: Path) -> list[tuple[str, str]]:
    """Return [(heading, body)] pairs from an HTML file."""
    try:
        from bs4 import BeautifulSoup  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("beautifulsoup4 is required for HTML parsing") from exc

    html = path.read_text(encoding="utf-8", errors="replace")
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")

    # Strip scripts + styles.
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    sections: list[tuple[str, list[str]]] = []
    current = ("Preamble", [])
    for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "li"]):
        txt = el.get_text(separator=" ", strip=True)
        if not txt:
            continue
        if el.name in {"h1", "h2", "h3", "h4"}:
            if current[1]:
                sections.append((current[0], current[1]))
            current = (normalize_ws(txt)[:150], [])
        else:
            current[1].append(normalize_ws(txt))
    if current[1]:
        sections.append((current[0], current[1]))

    return [(h, "\n".join(body)) for h, body in sections if body]


def parse_html_to_document(
    path: Path,
    *,
    source_id: str,
    source_url: str,
    jurisdiction: str,
    version: str,
    license: str,
    notes: str = "",
) -> CorpusDocument:
    logger.info("parsing HTML %s (%s)", path.name, source_id)
    sections = _extract_text(path)

    doc = CorpusDocument.new(
        source_id=source_id,
        source_url=source_url,
        jurisdiction=jurisdiction,
        version=version,
        license=license,
        notes=notes,
    )
    for s_idx, (heading, body) in enumerate(sections):
        for c_idx, piece in enumerate(chunk_by_token_budget(body, max_tokens=480, overlap=40)):
            doc.add(
                CorpusChunk(
                    id=safe_id(source_id, "sec", s_idx, c_idx),
                    text=piece,
                    title=heading,
                    section_path=("section", str(s_idx)),
                    tags={"kind": "html_section", "heading": heading[:80]},
                )
            )
    doc.finalise()
    return doc
