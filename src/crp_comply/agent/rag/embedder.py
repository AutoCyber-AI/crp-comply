"""Embedding layer.

Wraps ``sentence-transformers`` with a small, opinionated surface:
- lazy model loading (first call pays the cost, subsequent calls are fast)
- deterministic batch encoding with L2 normalisation (so cosine == dot product)
- a ``dim`` property for schema validation

Default model: ``BAAI/bge-small-en-v1.5`` (384-dim, ~130 MB, fast on CPU).
Override via ``CRP_COMPLY_EMBED_MODEL`` env var or the ``model_name`` constructor
argument. ``bge-large-en-v1.5`` (1024-dim, ~1.3 GB) is the quality upgrade for
Enterprise deployments; works but needs more RAM.
"""

from __future__ import annotations

import os
from typing import Iterable, List, Sequence

import numpy as np

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"


def _resolve_model_name(override: str | None) -> str:
    if override:
        return override
    return os.environ.get("CRP_COMPLY_EMBED_MODEL", DEFAULT_MODEL)


class Embedder:
    """Thin wrapper around ``sentence_transformers.SentenceTransformer``."""

    def __init__(
        self,
        model_name: str | None = None,
        *,
        device: str | None = None,
        batch_size: int = 32,
    ) -> None:
        self.model_name = _resolve_model_name(model_name)
        self.device = device
        self.batch_size = batch_size
        self._model = None  # lazy
        self._dim: int | None = None

    # ------------------------------------------------------------------ core

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - import guard
            raise RuntimeError(
                "sentence-transformers is not installed. "
                'Run `pip install -e ".[agent]"` or `pip install sentence-transformers`.'
            ) from exc
        self._model = SentenceTransformer(self.model_name, device=self.device)
        self._dim = int(self._model.get_sentence_embedding_dimension())

    @property
    def dim(self) -> int:
        self._ensure_loaded()
        if not (self._dim is not None):
            raise RuntimeError("embedder dimension not initialised")
        return self._dim

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        """Return ``(len(texts), dim)`` float32 array, L2-normalised."""
        self._ensure_loaded()
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        vectors = self._model.encode(  # type: ignore[union-attr]
            list(texts),
            batch_size=self.batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return np.asarray(vectors, dtype=np.float32)

    def encode_iter(self, texts: Iterable[str]) -> np.ndarray:
        """Convenience for generators / lazy inputs."""
        buffered: List[str] = list(texts)
        return self.encode(buffered)
