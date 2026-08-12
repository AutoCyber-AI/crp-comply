"""EUR-Lex scraper — EU AI Act (Regulation 2024/1689) and GDPR (2016/679).

Strategy: fetch the consolidated HTML via the CELEX identifier, parse the
standard EUR-Lex document structure (ti-art, sti-art, normal paragraphs),
and emit one chunk per Article + one per Annex.

Why HTML and not XML: EUR-Lex's Formex XML is brittle and version-gated.
The English HTML view is stable and publicly cached.

License: © European Union. Reuse is authorised with source attribution
(Decision 2011/833/EU). We store article ids + our own commentary in the
shipped RAG index; verbatim regulation text is included per fair-quotation
and our DPA.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterator

try:
    from bs4 import BeautifulSoup  # type: ignore
except ImportError:  # pragma: no cover
    BeautifulSoup = None  # type: ignore

from ..corpus import CorpusChunk, CorpusDocument
from .base import BROWSER_UA, chunk_by_token_budget, http_get, normalize_ws, safe_id

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Registry of EUR-Lex documents we ingest
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EurLexSpec:
    source_id: str
    celex: str
    title: str
    version: str
    url: str


AI_ACT = EurLexSpec(
    source_id="eu_ai_act",
    celex="32024R1689",
    title="Regulation (EU) 2024/1689 — Artificial Intelligence Act",
    version="consolidated-2024-08-01",
    url="https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1689",
)

GDPR = EurLexSpec(
    source_id="gdpr",
    celex="32016R0679",
    title="Regulation (EU) 2016/679 — General Data Protection Regulation",
    version="consolidated-2018-05-04",
    url="https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32016R0679",
)

NIS2 = EurLexSpec(
    source_id="nis2",
    celex="32022L2555",
    title="Directive (EU) 2022/2555 — NIS2",
    version="consolidated-2023-01-16",
    url="https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32022L2555",
)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


_ARTICLE_HEADING = re.compile(r"^Article\s+(\d+[a-z]?)\b", re.IGNORECASE)
_ANNEX_HEADING = re.compile(r"^Annex\s+([IVXLCDM]+)\b", re.IGNORECASE)
_RECITAL_LEAD = re.compile(r"^\(\s*(\d+)\s*\)")


def _require_bs4() -> None:
    if BeautifulSoup is None:
        raise RuntimeError(
            "beautifulsoup4 is required to run EUR-Lex scrapers. "
            "Install with: pip install beautifulsoup4 lxml"
        )


def _iter_blocks(html: str) -> Iterator[tuple[str, str]]:
    """Yield (block_class, text) tuples from EUR-Lex HTML.

    We look at the body paragraphs and preserve the block type encoded in
    the ``class`` attribute (``ti-art``, ``sti-art``, ``normal``, etc.).
    """
    _require_bs4()
    soup = BeautifulSoup(html, "lxml" if _has_lxml() else "html.parser")
    # EUR-Lex wraps the body in <div class="eli-main-title"> ... <p class="...">
    for p in soup.find_all(["p", "div", "span"]):
        classes = " ".join(p.get("class") or [])
        text = p.get_text(separator=" ", strip=True)
        if text:
            yield classes, normalize_ws(text)


def _has_lxml() -> bool:
    try:
        import lxml  # noqa: F401

        return True
    except ImportError:
        return False


def _parse_eurlex_html(
    html: str,
) -> tuple[
    list[tuple[str, str, list[str]]], list[tuple[str, str, list[str]]], list[tuple[str, str]]
]:
    """Split an EUR-Lex HTML body into (articles, annexes, recitals).

    Returns
    -------
    articles : list of (article_id, title, paragraphs)
    annexes  : list of (annex_roman, title, paragraphs)
    recitals : list of (recital_number, text)
    """
    articles: list[tuple[str, str, list[str]]] = []
    annexes: list[tuple[str, str, list[str]]] = []
    recitals: list[tuple[str, str]] = []

    cur_article: tuple[str, str, list[str]] | None = None
    cur_annex: tuple[str, str, list[str]] | None = None

    for cls, text in _iter_blocks(html):
        # Annex heading
        m_annex = _ANNEX_HEADING.match(text)
        if m_annex and "ti-annex" in cls or (m_annex and len(text) < 80):
            if cur_article is not None:
                articles.append(cur_article)
                cur_article = None
            if cur_annex is not None:
                annexes.append(cur_annex)
            cur_annex = (m_annex.group(1).upper(), text, [])
            continue

        # Article heading
        m_art = _ARTICLE_HEADING.match(text)
        if m_art and ("ti-art" in cls or len(text) < 80):
            if cur_article is not None:
                articles.append(cur_article)
            if cur_annex is not None:
                annexes.append(cur_annex)
                cur_annex = None
            cur_article = (m_art.group(1), text, [])
            continue

        # Sub-title for article / annex — prepend to the current title
        if "sti-art" in cls or "sti-annex" in cls:
            if cur_article is not None:
                cur_article = (cur_article[0], cur_article[1] + " — " + text, cur_article[2])
            elif cur_annex is not None:
                cur_annex = (cur_annex[0], cur_annex[1] + " — " + text, cur_annex[2])
            continue

        # Recital
        if not cur_article and not cur_annex:
            m_rec = _RECITAL_LEAD.match(text)
            if m_rec:
                recitals.append((m_rec.group(1), text))
                continue

        # Body paragraph attached to current section
        if cur_article is not None:
            cur_article[2].append(text)
        elif cur_annex is not None:
            cur_annex[2].append(text)

    if cur_article is not None:
        articles.append(cur_article)
    if cur_annex is not None:
        annexes.append(cur_annex)

    return articles, annexes, recitals


# ---------------------------------------------------------------------------
# Public: scrape one spec
# ---------------------------------------------------------------------------


def scrape_spec(spec: EurLexSpec) -> CorpusDocument:
    """Fetch and chunk a EUR-Lex regulation.

    Strategy, in priority order:
      1. If ``corpus/eu/{source_id}/{source_id}.pdf`` exists locally, parse it
         (fastest, reliable, and avoids EUR-Lex's async-render gate).
      2. Try HTML with browser-like headers — works occasionally.
      3. Fall back to the PDF URL.
      4. If all fail, raise with an actionable error telling the user which
         PDF to download and where to put it.
    """
    from ..corpus import corpus_dir
    from ..ingest.pdf_parser import parse_pdf_to_document

    pdf_dir = corpus_dir() / "eu" / spec.source_id
    pdf_dir.mkdir(parents=True, exist_ok=True)
    local_pdf = pdf_dir / f"{spec.source_id}.pdf"

    # --- 1. Local PDF (preferred) -----------------------------------------
    if local_pdf.exists() and local_pdf.stat().st_size > 10_000:
        logger.info("using local PDF for %s: %s", spec.source_id, local_pdf)
        return parse_pdf_to_document(
            local_pdf,
            source_id=spec.source_id,
            source_url=f"local:{local_pdf.as_posix()}",
            jurisdiction="EU",
            version=spec.version,
            license="EU-free-reuse",
            notes=f"CELEX {spec.celex} — {spec.title} (local PDF)",
            heading_pattern=r"^(?:Article\s+\d+[a-z]?|ANNEX\s+[IVXLCDM]+)\b",
        )

    articles: list[tuple[str, str, list[str]]] = []
    annexes: list[tuple[str, str, list[str]]] = []
    recitals: list[tuple[str, str]] = []

    # --- 2. HTML attempt --------------------------------------------------
    html_headers = {
        "User-Agent": BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
        "Accept-Language": "en-GB,en;q=0.9",
    }
    try:
        logger.info("scraping %s via HTML %s", spec.source_id, spec.url)
        resp = http_get(spec.url, headers=html_headers)
        articles, annexes, recitals = _parse_eurlex_html(resp.text)
    except Exception as exc:
        logger.warning("HTML path failed for %s: %s — trying PDF URL", spec.source_id, exc)

    # --- 3. PDF URL fallback ---------------------------------------------
    if not articles:
        pdf_url = f"https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX:{spec.celex}"
        try:
            logger.info("scraping %s via PDF %s", spec.source_id, pdf_url)
            pdf_headers = dict(html_headers)
            pdf_headers["Accept"] = "application/pdf,*/*"
            resp = http_get(pdf_url, headers=pdf_headers)
            local_pdf.write_bytes(resp.content)
            return parse_pdf_to_document(
                local_pdf,
                source_id=spec.source_id,
                source_url=pdf_url,
                jurisdiction="EU",
                version=spec.version,
                license="EU-free-reuse",
                notes=f"CELEX {spec.celex} — {spec.title} (PDF)",
                heading_pattern=r"^(?:Article\s+\d+[a-z]?|ANNEX\s+[IVXLCDM]+)\b",
            )
        except Exception as exc:
            raise RuntimeError(
                f"Could not fetch {spec.source_id} from EUR-Lex (HTML & PDF both 202). "
                f"Manual fix: download the PDF from "
                f"https://eur-lex.europa.eu/legal-content/EN/TXT/PDF/?uri=CELEX:{spec.celex} "
                f"in a browser and save it to {local_pdf}"
            ) from exc

    logger.info(
        "%s: %d articles, %d annexes, %d recitals parsed",
        spec.source_id,
        len(articles),
        len(annexes),
        len(recitals),
    )

    doc = CorpusDocument.new(
        source_id=spec.source_id,
        source_url=spec.url,
        jurisdiction="EU",
        version=spec.version,
        license="EU-free-reuse",
        notes=f"CELEX {spec.celex} — {spec.title}",
    )

    for art_id, title, paragraphs in articles:
        body = "\n\n".join(paragraphs)
        for i, piece in enumerate(chunk_by_token_budget(body, max_tokens=480, overlap=40)):
            doc.add(
                CorpusChunk(
                    id=safe_id(spec.source_id, "art", art_id, i),
                    text=piece,
                    title=title,
                    article_id=art_id,
                    section_path=("article", art_id),
                    tags={"kind": "article", "celex": spec.celex},
                )
            )

    for annex_id, title, paragraphs in annexes:
        body = "\n\n".join(paragraphs)
        for i, piece in enumerate(chunk_by_token_budget(body, max_tokens=480, overlap=40)):
            doc.add(
                CorpusChunk(
                    id=safe_id(spec.source_id, "annex", annex_id, i),
                    text=piece,
                    title=title,
                    article_id=f"Annex {annex_id}",
                    section_path=("annex", annex_id),
                    tags={"kind": "annex", "celex": spec.celex},
                )
            )

    for rec_id, rec_text in recitals:
        doc.add(
            CorpusChunk(
                id=safe_id(spec.source_id, "recital", rec_id),
                text=rec_text,
                title=f"Recital {rec_id}",
                article_id=f"Recital {rec_id}",
                section_path=("recital", rec_id),
                tags={"kind": "recital", "celex": spec.celex},
            )
        )

    doc.finalise()
    return doc


def scrape_eu_ai_act() -> CorpusDocument:
    return scrape_spec(AI_ACT)


def scrape_gdpr() -> CorpusDocument:
    return scrape_spec(GDPR)


def scrape_nis2() -> CorpusDocument:
    return scrape_spec(NIS2)
