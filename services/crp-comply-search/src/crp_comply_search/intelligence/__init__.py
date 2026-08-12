"""Client-side intelligence layer for crp-comply-search.

Three modules — each independently disable-able via flags so unit
tests stay cheap and lane A (cache-fast-path) can opt out:

* :class:`QueryExpander`   — sub-query fan-out per intent.
* :class:`CrossEncoderReranker` — top-N rerank of candidate hits.
* :class:`ChunkCiter`      — split full_text into citable passages.

All three are deliberately dependency-light. Heavy ML deps
(``sentence-transformers``, ``torch``) are imported lazily; if the
import fails the modules fall back to deterministic, no-ML behaviour
so the sidecar still works on a slim image.
"""

from .query_expander import ExpansionResult, QueryExpander
from .reranker import CrossEncoderReranker, RerankResult
from .chunker import ChunkCiter, Citation

__all__ = [
    "ChunkCiter",
    "Citation",
    "CrossEncoderReranker",
    "ExpansionResult",
    "QueryExpander",
    "RerankResult",
]
