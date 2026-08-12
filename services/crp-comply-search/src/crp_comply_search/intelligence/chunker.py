"""Chunk-and-cite: split a hit's full_text into citable passages.

For each input :class:`SearchHit` with ``full_text`` populated, we
emit one or more :class:`Citation` records:

    Citation(
      citation_id   = "web:<sha12>:c<index>",
      source_id     = hit.citation_id          # parent SearchHit id
      url, title, domain, trust_tier,
      chunk_index   = N,
      excerpt       = "..."                    # the actual passage
      score         = relevance to the query (cross-encoder or heuristic)
    )

The chunker uses a simple recursive splitter (no heavy deps): split
on paragraph breaks first, then on sentence-ish boundaries, then
hard-cap. Default chunk size is 700 chars with 80 char overlap.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


_PARA_RE = re.compile(r"\n\s*\n+")
_SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


@dataclass
class Citation:
    citation_id: str
    source_id: str
    url: str
    title: str
    domain: str
    trust_tier: int
    chunk_index: int
    excerpt: str
    score: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        return out


class ChunkCiter:
    """Splits full_text into chunks and assigns stable citation ids."""

    def __init__(
        self,
        *,
        chunk_size: int = 700,
        chunk_overlap: int = 80,
        max_chunks_per_hit: int = 3,
    ) -> None:
        self._size = max(120, int(chunk_size))
        self._overlap = max(0, min(int(chunk_overlap), self._size // 2))
        self._max = max(1, int(max_chunks_per_hit))

    def cite(
        self,
        query: str,
        hits: list[Any],
        *,
        scorer: Any | None = None,
        top_k_per_hit: int | None = None,
    ) -> list[Citation]:
        """Return a flat list of citations across all hits.

        ``scorer`` is any object exposing ``rerank(query, hits)`` (i.e.
        :class:`~.reranker.CrossEncoderReranker`). When supplied, each
        hit's chunks are scored and only the top ``top_k_per_hit``
        survive (defaults to ``max_chunks_per_hit``).
        """
        out: list[Citation] = []
        cap = top_k_per_hit or self._max
        for hit in hits:
            chunks = self._split(getattr(hit, "full_text", "") or "")
            if not chunks:
                # Fall back to snippet so every hit produces at least
                # one citation candidate (which may still rank low).
                snippet = (getattr(hit, "snippet", "") or "").strip()
                if not snippet:
                    continue
                chunks = [snippet]

            scored = self._score_chunks(query, chunks, scorer)
            scored.sort(key=lambda pair: -pair[1])
            survivors = scored[:cap]
            base_url = getattr(hit, "url", "") or ""
            base_id = getattr(hit, "citation_id", None) or (
                "web:" + uuid.uuid4().hex[:12]
            )
            for idx, (chunk, score) in enumerate(survivors):
                cid = f"{base_id}:c{idx}"
                out.append(Citation(
                    citation_id=cid,
                    source_id=base_id,
                    url=base_url,
                    title=getattr(hit, "title", ""),
                    domain=getattr(hit, "domain", ""),
                    trust_tier=int(getattr(hit, "trust_tier", 4)),
                    chunk_index=idx,
                    excerpt=chunk,
                    score=float(score),
                ))
        return out

    # ----------------------------------------------------------------
    # Internals.
    # ----------------------------------------------------------------
    def _split(self, text: str) -> list[str]:
        text = (text or "").strip()
        if not text:
            return []
        paras = [p.strip() for p in _PARA_RE.split(text) if p.strip()]
        chunks: list[str] = []
        buf = ""
        for p in paras:
            if not buf:
                buf = p
                continue
            if len(buf) + 2 + len(p) <= self._size:
                buf = buf + "\n\n" + p
            else:
                chunks.append(buf)
                buf = p
        if buf:
            chunks.append(buf)
        # Hard-split anything that's still > size, with overlap.
        out: list[str] = []
        for c in chunks:
            if len(c) <= self._size:
                out.append(c)
                continue
            i = 0
            while i < len(c):
                end = min(len(c), i + self._size)
                out.append(c[i:end])
                if end >= len(c):
                    break
                i = end - self._overlap
        return out

    @staticmethod
    def _score_chunks(
        query: str, chunks: list[str], scorer: Any | None,
    ) -> list[tuple[str, float]]:
        if scorer is None:
            return [(c, _heuristic(query, c)) for c in chunks]

        # Adapt scorer.rerank API: it expects objects with .title/.snippet.
        class _Pseudo:  # noqa: D401
            __slots__ = ("title", "snippet", "weight")

            def __init__(self, text: str) -> None:
                self.title = ""
                self.snippet = text[:512]
                self.weight = 0.0

        try:
            pseudo = [_Pseudo(c) for c in chunks]
            res = scorer.rerank(query, pseudo, top_k=len(pseudo))
            # Map back to (chunk, score) using object identity of pseudo.
            order = res.hits
            score_by_id = {id(p): float(rank) for rank, p in enumerate(order)}
            # Smaller rank == better, so invert.
            return [
                (chunks[i], float(len(pseudo) - score_by_id.get(id(p), len(pseudo))))
                for i, p in enumerate(pseudo)
            ]
        except Exception:  # noqa: BLE001
            logger.debug("chunk scorer failed; using heuristic", exc_info=True)
            return [(c, _heuristic(query, c)) for c in chunks]


def _heuristic(query: str, chunk: str) -> float:
    q_tokens = {t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 2}
    if not q_tokens:
        return 0.0
    c_tokens = set(re.findall(r"[a-z0-9]+", chunk.lower()))
    return len(q_tokens & c_tokens) / max(1, len(q_tokens))
