"""Ingest pipeline: parsers + CLI.

    python -m crp_comply.agent.ingest all                 # run every scraper
    python -m crp_comply.agent.ingest eu_ai_act gdpr      # named subset
    python -m crp_comply.agent.ingest iso                 # ingest ISO PDFs from corpus/iso/

Every ingest produces JSON documents under ``corpus/_scraped/`` and updates
``corpus/_scraped/manifest.json``. Embedding into the vector index is a
separate step (Phase 4.1b).
"""

from __future__ import annotations

__all__ = ["pdf_parser", "html_parser", "iso_loader"]
