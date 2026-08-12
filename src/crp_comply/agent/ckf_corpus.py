"""CRP-on-data: pre-compile the regulation corpus into a shared CKF.

Most "RAG over regulation" stacks treat the corpus as static text — every
query at run-time has to extract structure (article numbers, obligations,
who-must-do-what triples) from raw chunks on the fly. The CRP gives us a
better option: apply the *Contextual Knowledge Fabric* to the corpus
itself at deploy time, so the agent inherits a pre-extracted graph of
**Facts** (subject / predicate / object / category / confidence) over
the regulation, not just embedded chunks.

Pipeline (one-shot per deploy):

    corpus/_scraped/*.json        # raw scraped regulation docs
        │
        │  (1) crp.extraction.ExtractionPipeline    ── 6-stage NLI graph
        ▼                                              extraction
    corpus/_scraped/facts/*.jsonl # structured Facts
        │
        │  (2) ContextualKnowledgeFabric.store
        ▼
    data/ckf/__corpus__/ckf.db    # shared semantic memory of the
                                  # regulation, queryable via
                                  # pattern_query / temporal_query /
                                  # community_summary / graph_walk

The orchestrator's ``_seed_prior_facts_primer`` then queries this shared
fabric in addition to the per-user fabric, so even brand-new tenants
start with full regulation grounding (~thousands of pre-extracted Facts
about EU AI Act articles, GDPR rights, NIST AI RMF functions, etc.)
without paying the GLiNER+NLI extraction cost on every query.

This module is invoked from the FastAPI lifespan when
``CRP_COMPLY_BOOTSTRAP_CKF=true``.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import warnings
from pathlib import Path
from typing import Any

# Side-effect import: registers a synthetic ``uie`` top-level module so
# the CRP SDK's Stage 4 (``crp.extraction.stage4_uie``) finds a backend
# and stops logging "UIE not available — Stage 4 will be skipped".
from .. import extraction as _extraction  # noqa: F401
from .corpus import scraped_output_dir

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sub-chunking parameters for Stage 3 (GLiNER)
# ---------------------------------------------------------------------------
#
# GLiNER's processor truncates inputs to 384 sub-word tokens and emits a
# ``UserWarning`` per oversized sentence. Many regulation chunks land in
# the 400-450 token range, which means we silently lose the tail of every
# chunk and spam the logs. We pre-split each chunk into windows of at
# most ``_GLINER_MAX_WORDS`` whitespace tokens (≈ 280 sub-word tokens for
# typical English regulation prose, well under the 384 cap) with a small
# overlap so entities spanning a boundary are still captured.
_GLINER_MAX_WORDS = 220
_GLINER_OVERLAP_WORDS = 30


def _split_for_extraction(text: str) -> list[str]:
    """Split *text* into <=``_GLINER_MAX_WORDS`` overlapping windows."""
    words = text.split()
    if len(words) <= _GLINER_MAX_WORDS:
        return [text]
    out: list[str] = []
    step = _GLINER_MAX_WORDS - _GLINER_OVERLAP_WORDS
    i = 0
    while i < len(words):
        out.append(" ".join(words[i : i + _GLINER_MAX_WORDS]))
        i += step
    return out


def _silence_known_upstream_warnings() -> None:
    """Filter the noisy upstream warnings emitted during extraction.

    The CRP extraction pipeline pulls in ``transformers``,
    ``huggingface_hub``, ``sentencepiece`` and ``gliner``, each of which
    emits warnings that cannot be silenced without re-pinning the
    upstream library. They are informational and do not affect output
    correctness for our use, so we filter them at the boundary where
    we *invoke* extraction — not globally.
    """
    # GLiNER processor: "Sentence of length N has been truncated to 384"
    # — we already pre-chunk to keep this from firing, but a long single
    # word can still trigger it. Filter as a safety net.
    warnings.filterwarnings(
        "ignore",
        message=r"Sentence of length \d+ has been truncated.*",
        category=UserWarning,
    )
    # huggingface_hub: ``resume_download`` deprecation. Emitted by older
    # transformers. Harmless; resume always happens now.
    warnings.filterwarnings(
        "ignore",
        message=r".*resume_download.*deprecated.*",
        category=FutureWarning,
    )
    # transformers tokenizer conversion warning about sentencepiece
    # byte-fallback. Cannot be fixed without retraining the tokenizer.
    warnings.filterwarnings(
        "ignore",
        message=r"The sentencepiece tokenizer that you are converting.*",
        category=UserWarning,
    )
    # transformers: "Asking to truncate to max_length but no maximum
    # length is provided" — we pass max_length explicitly where it
    # matters; this fires from internal calls that we do not own.
    warnings.filterwarnings(
        "ignore",
        message=r"Asking to truncate to max_length but no maximum length.*",
        category=UserWarning,
    )


_CORPUS_USER = "__corpus__"
_corpus_ckf: Any = None
_lock = threading.Lock()


def _persist_path() -> Path:
    data_dir = Path(os.environ.get("CRP_COMPLY_DATA_DIR", "data"))
    persist_dir = data_dir / "ckf" / _CORPUS_USER
    persist_dir.mkdir(parents=True, exist_ok=True)
    return persist_dir / "ckf.db"


def _build_corpus_ckf() -> Any:
    """Construct (or restore) the shared corpus CKF instance."""
    try:
        from crp.ckf.fabric import CKFConfig, ContextualKnowledgeFabric
    except Exception as exc:
        logger.warning("CRP CKF unavailable: %s", exc)
        return None

    persist_path = _persist_path()
    config = CKFConfig(
        max_facts=50_000,  # corpus is large; ~3k facts/source × 11 sources
        hnsw_threshold=1000,
        persist_path=str(persist_path),
        gc_budget_bytes=1024 * 1024 * 1024,
        community_detect_enabled=True,
    )
    ckf = ContextualKnowledgeFabric(config)
    if persist_path.exists():
        try:
            ckf.restore(str(persist_path))
        except Exception:
            logger.debug("corpus CKF restore failed (non-fatal)", exc_info=True)
    return ckf


def get_corpus_ckf() -> Any | None:
    """Module-level singleton accessor."""
    global _corpus_ckf
    with _lock:
        if _corpus_ckf is None:
            _corpus_ckf = _build_corpus_ckf()
        return _corpus_ckf


def _load_facts_jsonl(path: Path) -> list[Any]:
    """Hydrate a ``corpus/_scraped/facts/{source_id}.jsonl`` into Fact objects.

    The JSONL was emitted by ``crp_comply.agent.ingest --extract-facts``;
    each line is a flat dict with the fields the extraction pipeline
    captures plus our own ``source_id`` / ``chunk_id`` / ``article_id``
    pointers back to the RAG index.
    """
    try:
        from crp.extraction.types import Fact  # type: ignore[import-not-found]
    except Exception:
        return []

    facts: list[Any] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except Exception:
                    continue
                # The Fact dataclass varies between CRP versions; build
                # defensively and skip any field the constructor rejects.
                kwargs: dict[str, Any] = {}
                for key in ("id", "text", "category", "confidence"):
                    if key in payload:
                        kwargs[key] = payload[key]
                try:
                    fact = Fact(**kwargs)  # type: ignore[arg-type]
                except TypeError:
                    # Fall back to text-only construction.
                    try:
                        fact = Fact(text=str(payload.get("text", "")))  # type: ignore[arg-type]
                    except Exception:
                        continue
                # Stash the source pointers in metadata if the dataclass
                # exposes one (newer CRP versions do).
                meta = getattr(fact, "metadata", None)
                if isinstance(meta, dict):
                    for k in ("source_id", "chunk_id", "article_id", "section_path"):
                        if k in payload:
                            meta[k] = payload[k]
                facts.append(fact)
    except FileNotFoundError:
        pass
    except Exception:
        logger.debug("failed reading %s", path, exc_info=True)
    return facts


def _run_extraction_pipeline() -> int:
    """Apply ``crp.extraction.ExtractionPipeline`` to every scraped doc.

    Reads ``corpus/_scraped/*.json`` (the regulation chunks produced by
    the lifespan scrapers), runs each chunk through the 6-stage CRP
    extraction pipeline, and writes the resulting Facts as JSONL to
    ``corpus/_scraped/facts/{source_id}.jsonl``. Returns total facts
    written.
    """
    _silence_known_upstream_warnings()
    try:
        from crp.extraction import ExtractionPipeline  # type: ignore[import-not-found]
    except Exception as exc:
        logger.warning(
            "ExtractionPipeline unavailable (%s) \u2014 corpus CKF will load whatever JSONLs exist",
            exc,
        )
        return 0

    out_dir = scraped_output_dir()
    facts_dir = out_dir / "facts"
    facts_dir.mkdir(parents=True, exist_ok=True)

    json_files = [p for p in sorted(out_dir.glob("*.json")) if p.name != "manifest.json"]
    if not json_files:
        return 0

    pipeline = ExtractionPipeline()
    total = 0
    for jp in json_files:
        try:
            payload = json.loads(jp.read_text(encoding="utf-8"))
        except Exception:
            continue
        source_id = payload.get("source_id") or jp.stem
        out_path = facts_dir / f"{source_id}.jsonl"
        if out_path.exists() and out_path.stat().st_size > 0:
            # Already extracted; skip (idempotent re-runs).
            continue
        chunks = payload.get("chunks") or []
        doc_facts = 0
        try:
            with out_path.open("w", encoding="utf-8") as fh:
                for chunk in chunks:
                    text = (chunk.get("text") or "").strip()
                    if not text:
                        continue
                    # Pre-split to keep GLiNER (Stage 3) under its
                    # 384-token cap. See ``_split_for_extraction``.
                    seen_fact_ids: set[str] = set()
                    for sub_text in _split_for_extraction(text):
                        try:
                            result = pipeline.extract(sub_text)
                        except Exception:
                            continue
                        for fact in getattr(result, "facts", None) or []:
                            fid = str(getattr(fact, "id", "") or "")
                            if fid and fid in seen_fact_ids:
                                continue
                            if fid:
                                seen_fact_ids.add(fid)
                            rec = {
                                "id": getattr(fact, "id", ""),
                                "text": getattr(fact, "text", ""),
                                "category": getattr(fact, "category", ""),
                                "confidence": float(getattr(fact, "confidence", 0.0)),
                                "source_id": source_id,
                                "chunk_id": chunk.get("id", ""),
                                "article_id": chunk.get("article_id", ""),
                                "section_path": list(chunk.get("section_path", []) or []),
                            }
                            fh.write(json.dumps(rec, ensure_ascii=False))
                            fh.write("\n")
                            doc_facts += 1
        except Exception:
            logger.exception("extraction failed for %s", source_id)
            continue
        logger.info("extracted %d facts from %s \u2192 %s", doc_facts, source_id, out_path.name)
        total += doc_facts
    return total


def bootstrap_ckf_from_corpus() -> int:
    """Build & load the shared corpus CKF.

    Pipeline (idempotent across restarts):

    1. If the persisted corpus CKF already has facts, return early.
    2. If ``corpus/_scraped/facts/*.jsonl`` is missing, run the CRP
       ExtractionPipeline over the scraped JSON chunks to generate it.
       This is heavy (~1 GB of GLiNER+NLI weights, several minutes per
       source) but it only runs *once* per Railway volume \u2014 the
       resulting JSONL is cached on disk and the populated CKF db is
       persisted at ``data/ckf/__corpus__/ckf.db``.
    3. Replay every JSONL into the corpus CKF and snapshot.

    Returns the total number of facts loaded into the CKF.
    """
    ckf = get_corpus_ckf()
    if ckf is None:
        return 0

    # Already populated? Skip the load (idempotent across restarts).
    try:
        existing = int(getattr(ckf, "fact_count", lambda: 0)())
    except Exception:
        existing = 0
    if existing > 0:
        logger.info("corpus CKF already has %d facts \u2014 skipping reload", existing)
        return existing

    facts_dir = scraped_output_dir() / "facts"
    jsonl_files = sorted(facts_dir.glob("*.jsonl")) if facts_dir.exists() else []

    if not jsonl_files:
        # Auto-extract: deploy-time, one-shot, results cached on the
        # mounted volume so subsequent boots are fast.
        logger.info(
            "no corpus/_scraped/facts/*.jsonl found \u2014 running "
            "ExtractionPipeline over the scraped corpus. This is a "
            "one-time per-deploy operation (5\u201315 minutes) and the "
            "output is persisted to the mounted volume."
        )
        n_extracted = _run_extraction_pipeline()
        logger.info("ExtractionPipeline emitted %d facts total", n_extracted)
        jsonl_files = sorted(facts_dir.glob("*.jsonl")) if facts_dir.exists() else []

    if not jsonl_files:
        logger.warning(
            "corpus CKF stays empty \u2014 extraction produced no JSONL "
            "(check that scraping completed and crp.extraction is installed)"
        )
        return 0

    total = 0
    for path in jsonl_files:
        facts = _load_facts_jsonl(path)
        if not facts:
            continue
        try:
            ckf.store(facts, window_id=f"corpus:{path.stem}")
            total += len(facts)
            logger.info("loaded %d facts from %s into corpus CKF", len(facts), path.name)
        except Exception:
            logger.exception("failed storing facts from %s", path.name)

    # Persist the populated CKF so subsequent boots are no-ops.
    try:
        persist_path = _persist_path()
        if hasattr(ckf, "snapshot"):
            ckf.snapshot(str(persist_path))
        elif hasattr(ckf, "persist"):
            ckf.persist(str(persist_path))
    except Exception:
        logger.debug("corpus CKF snapshot failed (non-fatal)", exc_info=True)

    return total


def query_corpus_ckf(
    *,
    pattern: str | None = None,
    entity_type: str | None = None,
    min_confidence: float = 0.5,
    max_results: int = 8,
) -> list[Any]:
    """Pattern-query the shared corpus CKF.

    Used by the orchestrator's primer to seed every fresh task with
    regulation-grounded facts (in addition to user-specific facts from
    the per-user CKF). Returns an empty list when the corpus CKF is
    unavailable or empty.
    """
    ckf = get_corpus_ckf()
    if ckf is None:
        return []
    try:
        if int(getattr(ckf, "fact_count", lambda: 0)()) <= 0:
            return []
    except Exception:
        return []
    try:
        # ``ContextualKnowledgeFabric.query`` exposes entity/relationship
        # filtering but not a free-text pattern. We run the structured query
        # and then post-filter on ``Fact.text`` when a text pattern is given.
        result = ckf.query(
            entity_type=entity_type,
            relationship_type=None,
            min_confidence=min_confidence,
            max_results=max_results,
        )
    except Exception:
        return []
    facts = getattr(result, "facts", None)
    if facts is None and isinstance(result, dict):
        facts = result.get("facts")
    facts = list(facts or [])
    if pattern:
        pattern_lower = pattern.lower()
        facts = [f for f in facts if pattern_lower in getattr(f, "text", "").lower()]
    return facts


__all__ = [
    "bootstrap_ckf_from_corpus",
    "get_corpus_ckf",
    "query_corpus_ckf",
]
