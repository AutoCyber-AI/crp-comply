"""sqlite-backed corpus index with in-memory numpy cosine search.

Design:
- One sqlite database at ``index_dir()/corpus.sqlite``.
- ``chunks`` table stores chunk text + metadata + ``embedding BLOB`` (float32).
- ``sources`` table stores per-document metadata (version, license, content_hash,
  retrieved_at) so the agent can cite exactly what the LLM saw.
- Queries load all embeddings into one ``numpy`` matrix and do brute-force
  cosine similarity. For N < 50k chunks this is < 5 ms per query on a laptop
  and orders of magnitude simpler to deploy than sqlite-vec / faiss.

The index is *additive*: re-building from the same scraped JSON files upserts
by ``chunk.id`` so updated chunks replace their prior row without fragmenting.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence

import numpy as np

from ..corpus import CorpusChunk, CorpusDocument, index_dir, scraped_output_dir
from .embedder import Embedder

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    source_id        TEXT PRIMARY KEY,
    source_url       TEXT,
    jurisdiction     TEXT,
    version          TEXT,
    license          TEXT,
    retrieved_at     TEXT,
    content_hash     TEXT,
    notes            TEXT,
    chunk_count      INTEGER,
    indexed_at       TEXT
);

CREATE TABLE IF NOT EXISTS chunks (
    id              TEXT PRIMARY KEY,
    source_id       TEXT NOT NULL,
    text            TEXT NOT NULL,
    title           TEXT,
    article_id      TEXT,
    section_path    TEXT,
    tags            TEXT,
    effective_date  TEXT,
    superseded_by   TEXT,
    embedding       BLOB NOT NULL,
    embedding_model TEXT NOT NULL,
    embedding_dim   INTEGER NOT NULL,
    FOREIGN KEY (source_id) REFERENCES sources(source_id)
);

CREATE INDEX IF NOT EXISTS idx_chunks_source ON chunks(source_id);
CREATE INDEX IF NOT EXISTS idx_chunks_article ON chunks(article_id);
"""


@dataclass(frozen=True)
class QueryHit:
    chunk_id: str
    source_id: str
    score: float
    text: str
    title: str
    article_id: str
    section_path: List[str]
    tags: dict


def _blob(vec: np.ndarray) -> bytes:
    return np.ascontiguousarray(vec, dtype=np.float32).tobytes()


def _unblob(buf: bytes, dim: int) -> np.ndarray:
    return np.frombuffer(buf, dtype=np.float32).reshape(-1, dim)


class CorpusIndex:
    """sqlite + numpy vector store for ``CorpusDocument`` data."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else index_dir() / "corpus.sqlite"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # ``check_same_thread=False`` is required because the FastAPI
        # request runs on a worker thread (via ``asyncio.to_thread``)
        # while the index was built on the main thread at startup.
        # The internal ``_lock`` serialises writes — sqlite is fine
        # with multi-thread reads when the connection is shared.
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._lock = threading.RLock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # ---------------------------------------------------------------- schema

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "CorpusIndex":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------- ingestion

    def upsert_document(
        self,
        doc: CorpusDocument,
        embeddings: np.ndarray,
        *,
        embedding_model: str,
    ) -> int:
        """Insert/replace a document and all its chunks. Returns chunk count."""
        if embeddings.shape[0] != len(doc.chunks):
            raise ValueError(
                f"embedding count {embeddings.shape[0]} != chunk count {len(doc.chunks)}"
            )
        if embeddings.ndim != 2:
            raise ValueError("embeddings must be 2-D")
        dim = int(embeddings.shape[1])
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO sources (source_id, source_url, jurisdiction, version,
                                     license, retrieved_at, content_hash, notes,
                                     chunk_count, indexed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    source_url=excluded.source_url,
                    jurisdiction=excluded.jurisdiction,
                    version=excluded.version,
                    license=excluded.license,
                    retrieved_at=excluded.retrieved_at,
                    content_hash=excluded.content_hash,
                    notes=excluded.notes,
                    chunk_count=excluded.chunk_count,
                    indexed_at=excluded.indexed_at
                """,
                (
                    doc.source_id,
                    doc.source_url,
                    doc.jurisdiction,
                    doc.version,
                    doc.license,
                    doc.retrieved_at,
                    doc.content_hash,
                    doc.notes or "",
                    len(doc.chunks),
                    now,
                ),
            )
            # Wipe prior chunks for this source so upsert-by-content-hash semantics
            # don't leak stale rows when chunk ids change.
            self._conn.execute("DELETE FROM chunks WHERE source_id = ?", (doc.source_id,))
            rows = [
                (
                    chunk.id,
                    doc.source_id,
                    chunk.text,
                    chunk.title,
                    chunk.article_id,
                    json.dumps(list(chunk.section_path)),
                    json.dumps(dict(chunk.tags or {})),
                    chunk.effective_date,
                    chunk.superseded_by,
                    _blob(embeddings[i]),
                    embedding_model,
                    dim,
                )
                for i, chunk in enumerate(doc.chunks)
            ]
            self._conn.executemany(
                """
                INSERT OR REPLACE INTO chunks (id, source_id, text, title, article_id, section_path,
                                    tags, effective_date, superseded_by, embedding,
                                    embedding_model, embedding_dim)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return len(doc.chunks)

    # ------------------------------------------------------------------ read

    def stats(self) -> dict:
        with self._lock:
            cur = self._conn.execute(
                "SELECT source_id, version, chunk_count, indexed_at FROM sources ORDER BY source_id"
            )
            source_rows = cur.fetchall()
            total = self._conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            dims = self._conn.execute(
                "SELECT DISTINCT embedding_dim, embedding_model FROM chunks"
            ).fetchall()
        sources = [
            {"source_id": r[0], "version": r[1], "chunk_count": r[2], "indexed_at": r[3]}
            for r in source_rows
        ]
        return {
            "db_path": str(self.db_path),
            "total_chunks": total,
            "sources": sources,
            "embedding_profiles": [{"dim": d[0], "model": d[1]} for d in dims],
        }

    def load_matrix(
        self,
        *,
        source_filter: Sequence[str] | None = None,
    ) -> tuple[np.ndarray, List[tuple]]:
        """Load every chunk embedding into one (N, dim) float32 matrix.

        Returns ``(matrix, rows)`` where ``rows`` are aligned to matrix rows.
        Each row tuple: ``(id, source_id, text, title, article_id, section_path, tags_json)``.
        """
        query = (
            "SELECT id, source_id, text, title, article_id, section_path, tags, "
            "embedding, embedding_dim FROM chunks"
        )
        params: list = []
        if source_filter:
            placeholders = ",".join("?" * len(source_filter))
            query += f" WHERE source_id IN ({placeholders})"
            params.extend(source_filter)
        with self._lock:
            cur = self._conn.execute(query, params)
            rows = cur.fetchall()
        if not rows:
            return np.zeros((0, 0), dtype=np.float32), []
        dim = rows[0][8]
        matrix = np.empty((len(rows), dim), dtype=np.float32)
        out_rows: List[tuple] = []
        for i, r in enumerate(rows):
            matrix[i] = np.frombuffer(r[7], dtype=np.float32)
            out_rows.append(r[:7])
        return matrix, out_rows

    def query(
        self,
        query_vec: np.ndarray,
        *,
        top_k: int = 8,
        source_filter: Sequence[str] | None = None,
    ) -> List[QueryHit]:
        """Brute-force cosine top-k. Assumes ``query_vec`` is L2-normalised."""
        matrix, rows = self.load_matrix(source_filter=source_filter)
        if matrix.shape[0] == 0:
            return []
        q = np.asarray(query_vec, dtype=np.float32).reshape(-1)
        if q.shape[0] != matrix.shape[1]:
            raise ValueError(f"query dim {q.shape[0]} != index dim {matrix.shape[1]}")
        scores = matrix @ q  # cosine since both sides L2-normalised
        k = min(top_k, scores.shape[0])
        top_idx = np.argpartition(-scores, k - 1)[:k]
        top_idx = top_idx[np.argsort(-scores[top_idx])]
        hits: List[QueryHit] = []
        for idx in top_idx:
            r = rows[int(idx)]
            try:
                section_path = list(json.loads(r[5])) if r[5] else []
            except (json.JSONDecodeError, TypeError):
                section_path = []
            try:
                tags = dict(json.loads(r[6])) if r[6] else {}
            except (json.JSONDecodeError, TypeError):
                tags = {}
            hits.append(
                QueryHit(
                    chunk_id=r[0],
                    source_id=r[1],
                    text=r[2],
                    title=r[3] or "",
                    article_id=r[4] or "",
                    section_path=section_path,
                    tags=tags,
                    score=float(scores[int(idx)]),
                )
            )
        return hits


# ----------------------------------------------------------------- bulk build


def build_from_scraped(
    *,
    embedder: Embedder,
    source_ids: Iterable[str] | None = None,
    db_path: Path | None = None,
    verbose: bool = False,
) -> dict:
    """Rebuild the index from every JSON file in ``corpus/_scraped/``.

    Returns a summary dict ``{sources: [...], total_chunks: int}``.
    """
    scraped = scraped_output_dir()
    if not scraped.exists():
        raise FileNotFoundError(
            f"No scraped corpus found at {scraped}. "
            "Run `python -m crp_comply.agent.ingest <target>` first."
        )
    wanted = set(source_ids) if source_ids else None

    summary_sources: List[dict] = []
    total = 0
    with CorpusIndex(db_path=db_path) as index:
        for path in sorted(scraped.glob("*.json")):
            if path.name == "manifest.json":
                continue
            raw = json.loads(path.read_text(encoding="utf-8"))
            source_id = raw.get("source_id")
            if not source_id:
                continue
            if wanted and source_id not in wanted:
                continue
            doc = _doc_from_json(raw)
            if not doc.chunks:
                if verbose:
                    print(f"  skip {source_id}: 0 chunks")
                continue
            if verbose:
                print(f"  embed {source_id}: {len(doc.chunks)} chunks", flush=True)
            vectors = embedder.encode([c.text for c in doc.chunks])
            n = index.upsert_document(doc, vectors, embedding_model=embedder.model_name)
            total += n
            summary_sources.append({"source_id": source_id, "chunks": n, "version": doc.version})

    return {
        "sources": summary_sources,
        "total_chunks": total,
        "embedding_model": embedder.model_name,
        "embedding_dim": embedder.dim,
    }


def _doc_from_json(raw: dict) -> CorpusDocument:
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
