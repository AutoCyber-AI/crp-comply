"""NIST AI Risk Management Framework scraper.

Sources:
  * AI RMF 1.0 (core) — https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf
  * Generative AI Profile (NIST AI 600-1) — https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf
  * AI RMF Playbook (HTML) — https://airc.nist.gov/AI_RMF_Knowledge_Base/Playbook

License: US Government works — public domain (17 U.S.C. §105).

For the PDFs we delegate to ``crp_comply.agent.ingest.pdf_parser``. This
scraper exists to (a) list the source URLs, (b) download them into the
corpus directory, and (c) hand off to the PDF parser which produces the
same :class:`CorpusDocument` shape as the EUR-Lex scrapers.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..corpus import CorpusDocument, corpus_dir
from .base import http_get

logger = logging.getLogger(__name__)


NIST_SOURCES = [
    {
        "source_id": "nist_ai_rmf_core",
        "url": "https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf",
        "version": "1.0",
        "title": "NIST AI Risk Management Framework 1.0",
    },
    {
        "source_id": "nist_ai_rmf_genai",
        "url": "https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf",
        "version": "1.0",
        "title": "NIST AI 600-1: Generative AI Profile",
    },
]


def download_all(dest_dir: Path | None = None) -> list[Path]:
    """Download every NIST PDF into ``corpus/us/nist_ai_rmf/``.

    Returns the list of local file paths that were written. PDFs that
    already exist with matching size are skipped.
    """
    target = dest_dir or (corpus_dir() / "us" / "nist_ai_rmf")
    target.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for spec in NIST_SOURCES:
        name = spec["url"].rsplit("/", 1)[-1]
        dst = target / name
        if dst.exists() and dst.stat().st_size > 100_000:
            logger.info("%s already present (%d bytes) — skip", dst.name, dst.stat().st_size)
        else:
            logger.info("downloading %s → %s", spec["url"], dst)
            resp = http_get(spec["url"])
            dst.write_bytes(resp.content)
        paths.append(dst)
    return paths


def scrape() -> list[CorpusDocument]:
    """Download the NIST PDFs and parse them into CorpusDocuments.

    Each returned document corresponds to one PDF (core + GenAI profile).
    """
    from ..ingest.pdf_parser import parse_pdf_to_document

    docs: list[CorpusDocument] = []
    for spec, path in zip(NIST_SOURCES, download_all()):
        doc = parse_pdf_to_document(
            path,
            source_id=spec["source_id"],
            source_url=spec["url"],
            jurisdiction="US",
            version=spec["version"],
            license="US-public-domain",
            notes=spec["title"],
            heading_pattern=r"^(?:GOVERN|MAP|MEASURE|MANAGE)[\s\-:]",
        )
        docs.append(doc)
    return docs
