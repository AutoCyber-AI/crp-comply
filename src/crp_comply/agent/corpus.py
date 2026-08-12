"""Shared corpus data model.

Every scraper and the ISO PDF ingestor produce :class:`CorpusDocument` objects
with the same schema. The ingest pipeline (parser -> chunker -> embedder) only
operates on this shape — so adding a new regulation source means writing one
scraper that emits :class:`CorpusDocument`, nothing else.

Schema rationale is in ``LLM_INTELLIGENCE_DESIGN.md`` §14 and §15.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CorpusChunk:
    """One retrievable unit — an Article, Annex row, ISO clause, etc.

    ``id`` is globally unique across the corpus. Reports cite chunks by this id
    + ``corpus_version``, so a regulator can replay the exact text the agent
    reasoned against (see §15.4 of the design doc).
    """

    id: str
    text: str
    title: str = ""
    article_id: str = ""
    section_path: tuple[str, ...] = field(default_factory=tuple)
    tags: dict[str, str] = field(default_factory=dict)
    effective_date: str | None = None
    superseded_by: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["section_path"] = list(self.section_path)
        return d


@dataclass
class CorpusDocument:
    """One regulation document — source manifest + chunks."""

    source_id: str  # e.g. "eu_ai_act", "gdpr", "iso_42001"
    source_url: str  # canonical URL or "local:iso/42001/official.pdf"
    jurisdiction: str  # "EU" | "UK" | "US" | "INTL" | "ISO"
    version: str  # e.g. "consolidated-2024-08-01"
    license: str  # "EU-free-reuse" | "US-public-domain" | "ISO-copyright" | "OGL-v3" | "CC-BY-4.0"
    retrieved_at: str  # ISO 8601 UTC
    content_hash: str = ""  # sha256 of the normalised source text
    chunks: list[CorpusChunk] = field(default_factory=list)
    notes: str = ""

    # -- factories -----------------------------------------------------------

    @classmethod
    def new(
        cls,
        *,
        source_id: str,
        source_url: str,
        jurisdiction: str,
        version: str,
        license: str,
        notes: str = "",
    ) -> "CorpusDocument":
        return cls(
            source_id=source_id,
            source_url=source_url,
            jurisdiction=jurisdiction,
            version=version,
            license=license,
            retrieved_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            notes=notes,
        )

    # -- helpers -------------------------------------------------------------

    def add(self, chunk: CorpusChunk) -> None:
        self.chunks.append(chunk)

    def finalise(self) -> None:
        """Compute ``content_hash`` over chunk text in stable order."""
        h = hashlib.sha256()
        for c in self.chunks:
            h.update(c.id.encode())
            h.update(b"\x00")
            h.update(c.text.encode())
            h.update(b"\x1e")
        self.content_hash = h.hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_url": self.source_url,
            "jurisdiction": self.jurisdiction,
            "version": self.version,
            "license": self.license,
            "retrieved_at": self.retrieved_at,
            "content_hash": self.content_hash,
            "notes": self.notes,
            "chunks": [c.to_dict() for c in self.chunks],
        }

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Corpus root resolution
# ---------------------------------------------------------------------------


def repo_root() -> Path:
    """Return the repo root assuming the conventional layout.

    ``src/crp_comply/agent/corpus.py`` → go up 4 levels.

    Note: when this package is *pip-installed* (as it is on Railway),
    ``parents[3]`` resolves to a system path like
    ``/usr/local/lib/python3.13`` which is **read-only**. Callers
    that need a writable scratch dir must go through :func:`corpus_dir`
    (which honours ``CRP_COMPLY_DATA_DIR``) and not assume this path
    is writable.
    """
    return Path(__file__).resolve().parents[3]


def _is_writable(p: Path) -> bool:
    try:
        p.mkdir(parents=True, exist_ok=True)
        probe = p / ".crp_writable_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def corpus_dir() -> Path:
    """Where regulation source documents live.

    Resolution order (first writable wins):

    1. ``$CRP_COMPLY_CORPUS_DIR`` (explicit override).
    2. ``$CRP_COMPLY_DATA_DIR/corpus`` (Railway volume).
    3. ``<repo>/corpus`` when running from a checkout AND that path
       is writable.
    4. A per-process temp directory under ``$CRP_COMPLY_DATA_DIR``
       or the system tempdir as a last-resort fallback.
    """
    import os as _os
    import tempfile as _tempfile

    explicit = _os.getenv("CRP_COMPLY_CORPUS_DIR")
    if explicit:
        d = Path(explicit)
        d.mkdir(parents=True, exist_ok=True)
        return d

    data_root = _os.getenv("CRP_COMPLY_DATA_DIR")
    if data_root:
        d = Path(data_root) / "corpus"
        if _is_writable(d):
            return d

    repo_corpus = repo_root() / "corpus"
    if _is_writable(repo_corpus):
        return repo_corpus

    fallback = (
        Path(data_root) / "corpus"
        if data_root
        else Path(_tempfile.gettempdir()) / "crp_comply_corpus"
    )
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def scraped_output_dir() -> Path:
    """Where scraped regulation JSONs land.

    On Railway / production the operator typically mounts a persistent
    volume at ``/app/data``. Set ``CRP_COMPLY_SCRAPED_DIR`` (or
    implicitly via ``CRP_COMPLY_DATA_DIR``) to redirect scraped output
    onto the volume so the corpus survives container restarts \u2014
    otherwise every cold boot re-runs the scrapers from scratch.

    Resolution order:

    1. ``$CRP_COMPLY_SCRAPED_DIR`` (explicit override).
    2. ``<repo>/corpus/_scraped`` if it already contains JSON files
       (preserves local dev workflow where the scraped corpus lives
       in the repo tree).
    3. ``$CRP_COMPLY_DATA_DIR/corpus_scraped`` (volume-mounted in
       production).
    4. ``<repo>/corpus/_scraped`` (final fallback for fresh dev).
    """
    import os as _os

    explicit = _os.getenv("CRP_COMPLY_SCRAPED_DIR")
    if explicit:
        d = Path(explicit)
        d.mkdir(parents=True, exist_ok=True)
        return d

    legacy = corpus_dir() / "_scraped"
    if legacy.exists() and any(
        p.suffix == ".json" and p.name != "manifest.json" for p in legacy.iterdir()
    ):
        return legacy

    data_root = _os.getenv("CRP_COMPLY_DATA_DIR")
    if data_root:
        d = Path(data_root) / "corpus_scraped"
        d.mkdir(parents=True, exist_ok=True)
        return d

    legacy.mkdir(parents=True, exist_ok=True)
    return legacy


def index_dir() -> Path:
    """Where the embedded sqlite-vss index lives.

    Production: Railway volume at ``/app/data/rag_index``.
    Local dev: ``<repo>/data/rag_index``.
    """
    import os

    explicit = os.getenv("CRP_RAG_INDEX_DIR")
    if explicit:
        return Path(explicit)
    # /app/data on Railway, ./data locally
    if Path("/app/data").is_dir():
        return Path("/app/data/rag_index")
    d = repo_root() / "data" / "rag_index"
    return d


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def write_manifest(docs: Iterable[CorpusDocument], manifest_path: Path) -> None:
    """Write a single manifest capturing versions + hashes of all sources."""
    manifest = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": [
            {
                "source_id": d.source_id,
                "source_url": d.source_url,
                "jurisdiction": d.jurisdiction,
                "version": d.version,
                "license": d.license,
                "content_hash": d.content_hash,
                "chunk_count": len(d.chunks),
            }
            for d in docs
        ],
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
