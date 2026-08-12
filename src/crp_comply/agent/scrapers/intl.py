"""Scrapers for OECD, Council of Europe, UK gov, and EDPB publications.

All four use the same pattern:
  1. Download the canonical source PDF/HTML.
  2. Parse to text (PDF parser for PDFs, bs4 extractor for HTML).
  3. Emit :class:`CorpusDocument`.

Each source has a distinct licence — recorded on the document.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..corpus import CorpusDocument, corpus_dir
from .base import http_get

logger = logging.getLogger(__name__)


# Canonical sources — PDF where a PDF exists (stable), else HTML.
SOURCES = [
    {
        "source_id": "oecd_ai_principles",
        "url": "https://legalinstruments.oecd.org/public/doc/648/648.en.pdf",
        "jurisdiction": "INTL",
        "version": "2024-revision",
        "license": "OECD-free-w-attribution",
        "title": "OECD Recommendation of the Council on Artificial Intelligence",
        "subdir": ("intl", "oecd_ai"),
        "kind": "pdf",
    },
    {
        "source_id": "coe_framework_ai",
        "url": "https://rm.coe.int/1680afae3c",
        "jurisdiction": "INTL",
        "version": "2024",
        "license": "CoE-free",
        "title": "Council of Europe Framework Convention on AI, Human Rights, Democracy and the Rule of Law",
        "subdir": ("intl", "coe_framework"),
        "kind": "pdf",
    },
    {
        "source_id": "uk_ai_whitepaper",
        "url": "https://assets.publishing.service.gov.uk/media/64cb71a547915a00142a91c4/a-pro-innovation-approach-to-ai-regulation-amended-web-ready.pdf",
        "jurisdiction": "UK",
        "version": "2023-08",
        "license": "OGL-v3",
        "title": "A pro-innovation approach to AI regulation",
        "subdir": ("uk", "ai_white_paper"),
        "kind": "pdf",
    },
    {
        "source_id": "edpb_wp251",
        "url": "https://ec.europa.eu/newsroom/article29/redirection/document/49826",
        "jurisdiction": "EU",
        "version": "2018-02-06",
        "license": "EU-free-reuse",
        "title": "Guidelines on Automated individual decision-making and Profiling (WP251rev.01)",
        "subdir": ("eu", "edpb"),
        "kind": "pdf",
    },
]


def _download(spec: dict) -> Path:
    target = corpus_dir().joinpath(*spec["subdir"])
    target.mkdir(parents=True, exist_ok=True)
    ext = ".pdf" if spec["kind"] == "pdf" else ".html"
    dst = target / f"{spec['source_id']}{ext}"
    if dst.exists() and dst.stat().st_size > 20_000:
        logger.info("%s already present — skip", dst.name)
        return dst
    logger.info("downloading %s → %s", spec["url"], dst)
    resp = http_get(spec["url"])
    dst.write_bytes(resp.content)
    return dst


def _parse(spec: dict, path: Path) -> CorpusDocument:
    if spec["kind"] == "pdf":
        from ..ingest.pdf_parser import parse_pdf_to_document

        return parse_pdf_to_document(
            path,
            source_id=spec["source_id"],
            source_url=spec["url"],
            jurisdiction=spec["jurisdiction"],
            version=spec["version"],
            license=spec["license"],
            notes=spec["title"],
        )
    # HTML — use the generic html parser in ingest
    from ..ingest.html_parser import parse_html_to_document

    return parse_html_to_document(
        path,
        source_id=spec["source_id"],
        source_url=spec["url"],
        jurisdiction=spec["jurisdiction"],
        version=spec["version"],
        license=spec["license"],
        notes=spec["title"],
    )


def scrape() -> list[CorpusDocument]:
    docs: list[CorpusDocument] = []
    for spec in SOURCES:
        try:
            path = _download(spec)
            docs.append(_parse(spec, path))
        except Exception as exc:  # log and continue — one source failing shouldn't block others
            logger.error("source %s failed: %s", spec["source_id"], exc)
    return docs
