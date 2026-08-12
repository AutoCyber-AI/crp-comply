"""Tiny adapter between the string-query tool contract and :class:`CorpusIndex`.

The tool in :mod:`crp_comply.agent.tools` expects a backend with
``query(query_text, top_k, source_filter)`` returning ``list[dict]``. The
underlying :class:`CorpusIndex` operates on numpy vectors; this module
embeds the query and reshapes the :class:`QueryHit` dataclasses into dicts.

In addition to the plain ``query()`` used by the LLM tool protocol, this
service exposes :meth:`query_packed` which runs the retrieved hits through
the CRP envelope stack (contradiction detection → packer) so callers that
need a budget-aware regulation envelope — e.g. the Mode C SDK worker —
get the same intelligence the rest of CRP uses.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, List, Sequence

from .crp_integration import detect_hit_contradictions, pack_hits_to_envelope
from .rag import CorpusIndex, Embedder


class RagService:
    """Query-string facade over :class:`CorpusIndex`."""

    def __init__(
        self,
        index: CorpusIndex | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self.index = index or CorpusIndex()
        self.embedder = embedder or Embedder()

    def query(
        self,
        query_text: str,
        *,
        top_k: int = 5,
        source_filter: Sequence[str] | None = None,
    ) -> List[dict[str, Any]]:
        text = (query_text or "").strip()
        if not text:
            return []
        vec = self.embedder.encode([text])[0]
        hits = self.index.query(
            vec,
            top_k=int(top_k),
            source_filter=list(source_filter) if source_filter else None,
        )
        return [asdict(h) for h in hits]

    def query_packed(
        self,
        query_text: str,
        *,
        top_k: int = 20,
        source_filter: Sequence[str] | None = None,
        budget_tokens: int = 1800,
        diversity_lambda: float | None = 0.7,
        rerank_top_k: int | None = None,
    ) -> dict[str, Any]:
        """Retrieve, dedupe-on-contradiction, and pack into a token budget.

        ``diversity_lambda`` (default 0.7) enables MMR rerank before
        packing — so we don't burn the budget on near-duplicate clauses.
        Set to ``None`` to disable.

        Returns a dict with keys:

        * ``packed`` — list of ``{chunk_id, text, tokens, score, ...}`` items
          chosen by :func:`crp.envelope.packer.pack_facts`.
        * ``contradictions`` — list of pairs flagged by
          :func:`crp.extraction.contradiction.detect_contradictions`. The
          caller can surface these to the LLM as "note: hits X and Y
          partially disagree".
        * ``total_tokens`` / ``dropped`` — packer budget telemetry.
        * ``hits`` — the raw retrieval output (for debugging).
        """
        hits = self.query(query_text, top_k=top_k, source_filter=source_filter)
        if not hits:
            return {
                "packed": [],
                "contradictions": [],
                "total_tokens": 0,
                "dropped": 0,
                "hits": [],
            }
        contradictions = detect_hit_contradictions(hits)
        pack = pack_hits_to_envelope(
            hits,
            budget_tokens=budget_tokens,
            diversity_lambda=diversity_lambda,
            rerank_top_k=rerank_top_k,
        )
        return {
            "packed": pack["packed"],
            "contradictions": contradictions,
            "total_tokens": pack["total_tokens"],
            "dropped": pack["dropped"],
            "hits": hits,
        }

    def close(self) -> None:
        try:
            self.index.close()
        except Exception as _bandit_exc:  # pragma: no cover - best effort
            import logging as _logging

            _logging.getLogger(__name__).debug("swallowed in rag_service.close: %s", _bandit_exc)


__all__ = ["RagService"]
