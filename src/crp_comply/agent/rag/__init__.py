"""Retrieval-augmented generation layer for the CRP-Comply compliance agent.

- ``embedder`` — loads a sentence-transformers model (default ``bge-small-en-v1.5``)
  and turns ``CorpusChunk`` objects into dense vectors.
- ``index`` — sqlite-backed chunk + blob storage with in-memory numpy top-k cosine
  search. Good enough for ~50k chunks; fewer moving parts than sqlite-vec.

The CLI lives in ``crp_comply.agent.rag.__main__``.
"""

from .embedder import Embedder, DEFAULT_MODEL
from .index import CorpusIndex, QueryHit, build_from_scraped

__all__ = ["Embedder", "DEFAULT_MODEL", "CorpusIndex", "QueryHit", "build_from_scraped"]
