"""Cross-encoder reranker for candidate web hits.

Wraps ``sentence-transformers/cross-encoder/ms-marco-MiniLM-L-6-v2``.
The model + torch are imported **lazily** — if either is missing the
reranker falls back to a deterministic heuristic that ranks by
``trust_tier × profile.weight + small_snippet_overlap`` so the
sidecar still works without ML deps installed (slim image, CI runs,
unit tests).

Public contract:

    rr = CrossEncoderReranker()
    out = rr.rerank(query, hits, top_k=6)
    out.hits           # reordered list[SearchHit]
    out.model          # which engine made the call (or "heuristic")
    out.latency_ms     # wall-clock ms of the rerank stage
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


_DEFAULT_MODEL = os.environ.get(
    "CRP_COMPLY_RERANK_MODEL",
    "cross-encoder/ms-marco-MiniLM-L-6-v2",
)


@dataclass
class RerankResult:
    hits: list[Any] = field(default_factory=list)
    model: str = ""
    latency_ms: float = 0.0
    candidates_in: int = 0
    candidates_out: int = 0


class CrossEncoderReranker:
    """Top-N rerank of hits against the user query."""

    def __init__(self, model_name: str | None = None) -> None:
        self._model_name = model_name or _DEFAULT_MODEL
        self._model: Any | None = None  # lazy
        self._failed = False  # don't retry import after the first miss

    # ----------------------------------------------------------------
    # Public API.
    # ----------------------------------------------------------------
    def rerank(
        self, query: str, hits: list[Any], *, top_k: int = 6,
    ) -> RerankResult:
        t0 = time.perf_counter()
        if not hits:
            return RerankResult(model="(empty)")
        candidates_in = len(hits)
        scored = self._score(query, hits)
        scored.sort(key=lambda pair: -pair[1])
        out = [h for h, _s in scored[:top_k]]
        return RerankResult(
            hits=out,
            model=self._model_label(),
            latency_ms=(time.perf_counter() - t0) * 1000.0,
            candidates_in=candidates_in,
            candidates_out=len(out),
        )

    # ----------------------------------------------------------------
    # Internals.
    # ----------------------------------------------------------------
    def _score(self, query: str, hits: list[Any]) -> list[tuple[Any, float]]:
        model = self._load()
        if model is not None:
            try:
                pairs = [
                    (
                        query,
                        (getattr(h, "title", "") + " " + getattr(h, "snippet", ""))[:512],
                    )
                    for h in hits
                ]
                scores = model.predict(pairs)
                return list(zip(hits, [float(s) for s in scores]))
            except Exception:  # noqa: BLE001
                logger.warning("cross-encoder.predict failed; using heuristic",
                               exc_info=True)
        return [(h, self._heuristic(query, h)) for h in hits]

    def _load(self) -> Any | None:
        if self._model is not None or self._failed:
            return self._model
        try:
            from sentence_transformers import CrossEncoder  # type: ignore
            self._model = CrossEncoder(self._model_name)
            return self._model
        except Exception:  # noqa: BLE001
            logger.info(
                "cross-encoder unavailable (sentence-transformers/torch "
                "not installed?); falling back to heuristic",
            )
            self._failed = True
            return None

    def _model_label(self) -> str:
        return self._model_name if self._model is not None else "heuristic"

    @staticmethod
    def _heuristic(query: str, hit: Any) -> float:
        """Trust × overlap heuristic. Stable, deterministic, fast."""
        q_tokens = {t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 2}
        if not q_tokens:
            return float(getattr(hit, "weight", 0.0))
        text = (
            (getattr(hit, "title", "") or "")
            + " "
            + (getattr(hit, "snippet", "") or "")
        ).lower()
        h_tokens = set(re.findall(r"[a-z0-9]+", text))
        overlap = len(q_tokens & h_tokens) / max(1, len(q_tokens))
        return float(getattr(hit, "weight", 0.0)) * 1.0 + overlap
