# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Continuous ingestion scheduler for the Phase 4 corpus.

Keeps the regulation corpus, RAG index, and obligation graph in sync with
upstream sources. The scheduler is intentionally lightweight: it re-runs the
existing scrapers for a single source, compares the content hash, and only
re-embeds when something changed. All heavy work runs in a thread pool so the
async loop stays responsive.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Callable

from ..agent.corpus import CorpusDocument, scraped_output_dir, write_manifest
from ..agent.rag import CorpusIndex, Embedder
from .models import IngestionJob, Regulation, _now
from .obligation_graph import build_graph_for_document
from .repository import CorpusRepository

logger = logging.getLogger(__name__)

SourceScraper = Callable[[], CorpusDocument]


# Built-in scraper registry — imported lazily so importing this module does not
# pull network or heavy PDF parsers at startup.
def _scraper_registry() -> dict[str, SourceScraper]:
    from ..agent.scrapers import eurlex, intl, nist

    registry: dict[str, SourceScraper] = {
        "eu_ai_act": eurlex.scrape_eu_ai_act,
        "gdpr": eurlex.scrape_gdpr,
        "nis2": eurlex.scrape_nis2,
    }

    def _nist() -> CorpusDocument:
        docs = nist.scrape()
        if not docs:
            raise RuntimeError("nist scraper returned no documents")
        return docs[0]

    registry["nist_ai_rmf"] = _nist

    def _intl_first() -> CorpusDocument:
        docs = intl.scrape()
        if not docs:
            raise RuntimeError("intl scraper returned no documents")
        return docs[0]

    registry["oecd_ai_principles"] = _intl_first
    return registry


class IngestionScheduler:
    """Polls upstream regulation sources and rebuilds the corpus when changed."""

    def __init__(
        self,
        repo: CorpusRepository | None = None,
        embedder: Embedder | None = None,
        scrapers: dict[str, SourceScraper] | None = None,
    ) -> None:
        self.repo = repo or CorpusRepository()
        self.embedder = embedder
        self.scrapers = scrapers or _scraper_registry()

    def ingest_source(
        self,
        source_id: str,
        *,
        trigger: str = "manual",
        force: bool = False,
    ) -> IngestionJob:
        """Run a single ingestion job synchronously.

        This is the entry point used by the manual API trigger and by the
        continuous loop. It does not assume an event loop.
        """
        job = IngestionJob.new(source_id=source_id, trigger=trigger)
        job.started_at = _now()
        job.status = "running"
        self.repo.create_job(job)

        try:
            previous = self.repo.get_regulation(source_id)
            scraper = self.scrapers.get(source_id)
            if scraper is None:
                raise RuntimeError(f"no scraper registered for {source_id}")

            doc = scraper()
            doc.finalise()
            new_hash = doc.content_hash

            job.previous_hash = previous and previous.version or None
            job.new_hash = new_hash

            if not force and previous and previous.version == new_hash:
                job.status = "success"
                job.finished_at = _now()
                self.repo.update_job(job)
                return job

            # Persist scraped JSON and update manifest.
            out_dir = scraped_output_dir()
            doc.write_json(out_dir / f"{source_id}.json")
            _rewrite_manifest(out_dir)

            # Embed and index.
            embedder = self.embedder or Embedder()
            index = CorpusIndex()
            vectors = embedder.encode([c.text for c in doc.chunks])
            index.upsert_document(doc, vectors, embedding_model=embedder.model_name)

            # Build and persist obligation graph.
            ob_count, edge_count = build_graph_for_document(doc, self.repo)

            # Update regulation metadata.
            self.repo.upsert_regulation(
                Regulation(
                    source_id=source_id,
                    title=doc.source_id,
                    jurisdiction=doc.jurisdiction,
                    version=new_hash,
                    canonical_url=doc.source_url,
                    license=doc.license,
                    chunk_count=len(doc.chunks),
                    indexed_at=_now(),
                )
            )

            job.chunks_added = len(doc.chunks)
            job.obligations_added = ob_count
            job.status = "success"
            job.finished_at = _now()
            job.metadata["edge_count"] = edge_count
            self.repo.update_job(job)
            logger.info(
                "ingestion complete for %s: %d chunks, %d obligations, %d edges",
                source_id,
                len(doc.chunks),
                ob_count,
                edge_count,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("ingestion failed for %s", source_id)
            job.status = "failed"
            job.error_message = str(exc)[:500]
            job.finished_at = _now()
            self.repo.update_job(job)

        return job

    async def run_once_async(
        self, source_id: str, *, trigger: str = "scheduled", force: bool = False
    ) -> IngestionJob:
        """Thread-pool wrapper around :meth:`ingest_source`."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.ingest_source, source_id, trigger, force)

    async def run_continuous(
        self,
        interval_hours: float | None = None,
        source_ids: list[str] | None = None,
    ) -> None:
        """Background loop. Runs forever until cancelled."""
        interval = interval_hours or float(
            os.environ.get("CRP_COMPLY_CONTINUOUS_INGEST_INTERVAL_HOURS", "168")
        )
        sources = source_ids or list(self.scrapers.keys())
        logger.info(
            "starting continuous ingestion: sources=%s interval=%.1fh",
            sources,
            interval,
        )
        while True:
            try:
                await asyncio.sleep(interval * 3600)
            except asyncio.CancelledError:
                raise
            for source_id in sources:
                try:
                    await self.run_once_async(source_id, trigger="scheduled")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("scheduled ingestion failed for %s: %s", source_id, exc)


def _rewrite_manifest(out_dir: Path) -> None:
    """Rewrite the scraped manifest from all JSON files present."""
    docs: list[CorpusDocument] = []
    for path in sorted(out_dir.glob("*.json")):
        if path.name == "manifest.json":
            continue
        try:
            import json

            raw = json.loads(path.read_text(encoding="utf-8"))
            docs.append(_doc_from_json(raw))
        except Exception:
            continue
    try:
        write_manifest(docs, out_dir / "manifest.json")
    except Exception:
        logger.debug("manifest rewrite failed", exc_info=True)


def _doc_from_json(raw: dict[str, Any]) -> CorpusDocument:
    from ..agent.corpus import CorpusChunk

    chunks = [
        CorpusChunk(
            id=c["id"],
            text=c["text"],
            title=c.get("title") or "",
            article_id=c.get("article_id") or "",
            section_path=tuple(c.get("section_path") or ()),
            tags=dict(c.get("tags") or {}),
            effective_date=c.get("effective_date"),
            superseded_by=c.get("superseded_by"),
        )
        for c in raw.get("chunks", [])
    ]
    return CorpusDocument(
        source_id=raw["source_id"],
        source_url=raw.get("source_url", ""),
        jurisdiction=raw.get("jurisdiction", ""),
        version=raw.get("version", ""),
        license=raw.get("license", ""),
        retrieved_at=raw.get("retrieved_at", ""),
        content_hash=raw.get("content_hash", ""),
        chunks=chunks,
        notes=raw.get("notes") or "",
    )
