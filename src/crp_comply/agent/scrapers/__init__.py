"""Regulation scrapers.

Each scraper is a module exposing a top-level ``scrape()`` function that
returns a :class:`CorpusDocument`. The shared pattern:

    from crp_comply.agent.scrapers import eurlex_ai_act
    doc = eurlex_ai_act.scrape()
    doc.write_json(scraped_output_dir() / f"{doc.source_id}.json")

Scrapers are network-bound and must be resilient: short retries, HTTP 304
caching when the server supports it, clear errors when the upstream page
layout changes (we fail loudly rather than silently ship stale data).
"""

from __future__ import annotations

from . import base  # noqa: F401

__all__ = ["base"]
