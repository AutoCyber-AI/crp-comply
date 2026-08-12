# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Bridge layer between ``crp-comply`` and the Context Relay Protocol SDK.

This module wires the following CRP primitives into the compliance agent:

* :mod:`crp.continuation.manager` — long-form final-answer continuation
* :mod:`crp.extraction.contradiction` — regulation supersession detection
* :mod:`crp.extraction.pipeline` — optional Fact extraction during ingest
* :mod:`crp.envelope.packer` / :mod:`crp.envelope.reranker` — budget-aware
  RAG result packing
* :mod:`crp.security.pii_scanner` — automatic pre-LLM PII redaction

The helpers here are deliberately **best-effort**: if a CRP subsystem is
unavailable (e.g. sentence-transformers missing in a thin deployment) the
function falls back to a no-op instead of raising. The goal is to light up
CRP intelligence where it is present without making ``crp-comply`` refuse
to start when it is not.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

logger = logging.getLogger(__name__)


# =============================================================================
# PII redaction (pre-LLM)
# =============================================================================

# Conservative regex fallbacks used when ``crp.security.PIIScanner`` is not
# available or silently returns no detections. These match the EU AI Act +
# GDPR attacker model: keep precision high, coverage can be tightened by
# the real scanner when present.
_PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("PHONE", re.compile(r"\+?\d[\d \-()]{7,}\d")),
    # Credit-card-ish (13–19 digits in groups of 4)
    ("CARD", re.compile(r"\b(?:\d[ -]*?){13,19}\b")),
    # IBAN-ish (2 letters + 13..32 alphanumeric)
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")),
)


@dataclass
class RedactionResult:
    text: str
    redactions: list[dict[str, Any]] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.redactions)


def redact_pii(text: str) -> RedactionResult:
    """Redact PII from ``text`` before it crosses an LLM boundary.

    Order of operations:

    1. Try :class:`crp.security.PIIScanner` (regex + heuristic pipeline).
    2. Supplement with local regex patterns for EMAIL/PHONE/CARD/IBAN in
       case the installed CRP build returned no detections.
    3. Replace every detected span with a typed placeholder like
       ``[EMAIL]`` / ``[PHONE]`` so the LLM still gets a well-formed
       prompt but the original value never leaves this process.

    Safe to call on short strings; returns the input unchanged if nothing
    matches.
    """
    if not text or not text.strip():
        return RedactionResult(text=text)

    detections: list[tuple[int, int, str, str]] = []  # (start, end, type, value)

    # 1) Try CRP scanner (strong path).
    try:
        from crp.security.pii_scanner import PIIScanner  # type: ignore[import-not-found]

        scanner = PIIScanner()
        scan_fn = getattr(scanner, "scan", None) or getattr(scanner, "detect", None)
        if scan_fn is not None:
            result = scan_fn(text)
            raw: Sequence[Any] = getattr(result, "detections", None) or (
                result if isinstance(result, list) else []
            )
            for d in raw:
                start = int(getattr(d, "start", -1))
                end = int(getattr(d, "end", -1))
                kind = str(getattr(d, "type", getattr(d, "category", "PII"))).upper()
                if 0 <= start < end <= len(text):
                    detections.append((start, end, kind, text[start:end]))
    except Exception:  # pragma: no cover - best-effort
        logger.debug("pii_scanner unavailable; falling back to regex", exc_info=True)

    # 2) Regex fallback/top-up.
    for kind, pat in _PII_PATTERNS:
        for m in pat.finditer(text):
            start, end = m.start(), m.end()
            # Skip overlaps with existing hits.
            if any(not (end <= s or start >= e) for s, e, _k, _v in detections):
                continue
            detections.append((start, end, kind, m.group(0)))

    if not detections:
        return RedactionResult(text=text)

    # Redact highest start first so earlier offsets stay valid.
    detections.sort(key=lambda d: d[0], reverse=True)
    redacted = text
    for start, end, kind, value in detections:
        redacted = f"{redacted[:start]}[{kind}]{redacted[end:]}"
    return RedactionResult(
        text=redacted,
        redactions=[
            {
                "type": kind,
                "start": start,
                "end": end,
                "value_sha256": hashlib.sha256(value.encode("utf-8")).hexdigest()[:16],
            }
            for start, end, kind, value in detections
        ],
    )


# =============================================================================
# Contradiction detection on RAG hits
# =============================================================================


def _hit_to_fact(hit: dict[str, Any]) -> Any | None:
    """Convert a :class:`RagService.query` hit dict into a :class:`crp.extraction.Fact`."""
    try:
        from crp.extraction import Fact  # type: ignore[import-not-found]
    except Exception:  # pragma: no cover
        return None
    text = str(hit.get("text") or "")
    if not text:
        return None
    return Fact(
        id=str(hit.get("chunk_id") or uuid.uuid4()),
        text=text,
        category=str(hit.get("source_id") or "regulation"),
        source_window_id="rag",
        confidence=float(hit.get("score") or 0.0),
        extraction_stage=0,
        created_at=time.time(),
        metadata={
            "title": hit.get("title"),
            "article_id": hit.get("article_id"),
            "section_path": hit.get("section_path"),
            "tags": hit.get("tags") or {},
        },
    )


def detect_hit_contradictions(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run :func:`crp.extraction.contradiction.detect_contradictions` over RAG hits.

    Returns a list of contradiction dicts suitable for LLM consumption
    (each contradiction flags two hits that partially disagree — e.g. a
    superseded directive vs its recast). Empty list on any failure.
    """
    if len(hits) < 2:
        return []
    try:
        from crp.extraction.contradiction import detect_contradictions  # type: ignore[import-not-found]
    except Exception:  # pragma: no cover
        return []

    facts = [f for f in (_hit_to_fact(h) for h in hits) if f is not None]
    if len(facts) < 2:
        return []

    # Pairwise: compare each fact against all earlier facts in the same
    # result set. Contradiction detection is symmetric so we only need to
    # run the upper triangle.
    out: list[dict[str, Any]] = []
    for i, fact in enumerate(facts):
        earlier = facts[:i]
        try:
            cs = detect_contradictions(
                new_facts=[fact],
                existing_facts=earlier,
                similarity_threshold=0.65,
                content_diff_threshold=0.25,
            )
        except Exception as _bandit_exc:
            logger.debug("swallowed in _extract_sources_from_facts: %s", _bandit_exc)
            continue
        for c in cs:
            out.append(
                {
                    "fact_a_id": getattr(c.fact_a, "id", ""),
                    "fact_b_id": getattr(c.fact_b, "id", ""),
                    "fact_a_text": (getattr(c.fact_a, "text", "") or "")[:240],
                    "fact_b_text": (getattr(c.fact_b, "text", "") or "")[:240],
                    "similarity": round(float(c.similarity), 4),
                    "content_diff": round(float(c.content_diff), 4),
                    "confidence": round(float(c.confidence), 4),
                }
            )
    return out


# =============================================================================
# Envelope packing on RAG hits (budget-aware)
# =============================================================================


def mmr_rerank(
    hits: list[dict[str, Any]],
    *,
    top_k: int | None = None,
    lambda_mult: float = 0.7,
) -> list[dict[str, Any]]:
    """Maximal-Marginal-Relevance diversity rerank over RAG hits.

    Optimises ``lambda * relevance - (1-lambda) * redundancy`` where
    redundancy is jaccard overlap on the hit body (embedding-free, so
    it works without any extra dependency). Always safe: if ``hits`` is
    empty or ``lambda_mult`` is 1.0 we fall back to score-sorted order.

    This closes the DESIGN_GAP_ASSESSMENT "reranker" item in §3.3: when
    an LLM asks for top-k clauses on e.g. "high-risk obligations", we
    don't want 5 near-duplicate EU-AI-Act Art. 9 chunks crowding out a
    single relevant GDPR Art. 35 chunk.
    """
    if not hits:
        return []
    lam = max(0.0, min(1.0, float(lambda_mult)))
    n = len(hits) if top_k is None else max(1, min(int(top_k), len(hits)))
    if lam >= 0.999 or n == 1:
        return sorted(hits, key=lambda h: float(h.get("score") or 0.0), reverse=True)[:n]

    def _tokens(h: dict[str, Any]) -> frozenset[str]:
        return frozenset((h.get("text") or "").lower().split())

    bag = [_tokens(h) for h in hits]
    scores = [float(h.get("score") or 0.0) for h in hits]
    remaining = list(range(len(hits)))
    picked: list[int] = []

    # Seed with the top-scoring hit.
    first = max(remaining, key=lambda i: scores[i])
    picked.append(first)
    remaining.remove(first)

    while remaining and len(picked) < n:

        def _mmr(i: int) -> float:
            rel = scores[i]
            red = 0.0
            for j in picked:
                if not bag[i] or not bag[j]:
                    continue
                inter = len(bag[i] & bag[j])
                union = len(bag[i] | bag[j])
                if union:
                    red = max(red, inter / union)
            return lam * rel - (1.0 - lam) * red

        nxt = max(remaining, key=_mmr)
        picked.append(nxt)
        remaining.remove(nxt)

    return [hits[i] for i in picked]


def pack_hits_to_envelope(
    hits: list[dict[str, Any]],
    *,
    budget_tokens: int = 1800,
    chars_per_token: float = 3.3,
    diversity_lambda: float | None = None,
    rerank_top_k: int | None = None,
) -> dict[str, Any]:
    """Pack hits into a token budget via :func:`crp.envelope.packer.pack_facts`.

    When ``diversity_lambda`` is set (0..1), an MMR rerank runs before
    packing so the final envelope balances relevance with clause
    diversity. ``rerank_top_k`` caps the slate fed to the packer.

    Falls back to naive truncation if CRP's packer is unavailable.
    Returns ``{'packed': [...], 'total_tokens': int, 'dropped': int}``.
    """
    if not hits:
        return {"packed": [], "total_tokens": 0, "dropped": 0}

    if diversity_lambda is not None:
        hits = mmr_rerank(hits, top_k=rerank_top_k, lambda_mult=diversity_lambda)

    facts = [f for f in (_hit_to_fact(h) for h in hits) if f is not None]

    # Try the full CRP envelope path: score → rerank → pack.
    try:
        from crp.envelope.packer import pack_facts  # type: ignore[import-not-found]
        from crp.envelope.scoring import ScoredFact  # type: ignore[import-not-found]
        from crp.extraction.types import FactGraph  # type: ignore[import-not-found]

        # Build a minimal ScoredFact list using the hit's cosine score as
        # the composite score. The packer respects ordering, so pre-sort.
        scored: list[ScoredFact] = []
        for fact, hit in zip(facts, hits):
            score = float(hit.get("score") or 0.0)
            scored.append(
                ScoredFact(
                    fact=fact,
                    score=score,
                    sim=score,
                    recency=1.0,
                    novelty=1.0,
                    dep_bonus=0.0,
                )
            )
        scored.sort(key=lambda s: s.score, reverse=True)

        result = pack_facts(
            scored_facts=scored,
            graph=FactGraph(),
            budget_tokens=int(budget_tokens),
            chars_per_token=chars_per_token,
        )
        packed = [
            {
                "chunk_id": pf.fact_id,
                "text": pf.text,
                "tokens": pf.tokens,
                "score": pf.score,
                "is_bookend": pf.is_bookend,
                "is_compressed": pf.is_compressed,
            }
            for pf in result.packed_facts
        ]
        dropped = max(0, len(hits) - result.facts_packed)
        return {"packed": packed, "total_tokens": result.total_tokens, "dropped": dropped}
    except Exception:  # pragma: no cover
        logger.debug("envelope packer unavailable; falling back to naive truncation", exc_info=True)

    # Naive fallback.
    packed: list[dict[str, Any]] = []
    used = 0
    for hit in sorted(hits, key=lambda h: float(h.get("score") or 0.0), reverse=True):
        text = str(hit.get("text") or "")
        tokens = max(1, int(len(text) / chars_per_token + 0.5))
        if used + tokens > budget_tokens:
            continue
        packed.append(
            {
                "chunk_id": hit.get("chunk_id"),
                "text": text,
                "tokens": tokens,
                "score": float(hit.get("score") or 0.0),
                "is_bookend": False,
                "is_compressed": False,
            }
        )
        used += tokens
    return {"packed": packed, "total_tokens": used, "dropped": max(0, len(hits) - len(packed))}


# =============================================================================
# Continuation wrap on length-truncated final answers
# =============================================================================


@dataclass
class ContinuationOutcome:
    final_text: str
    windows: int = 1
    termination_reason: str = "single_window"
    stitched: bool = False


def continue_truncated_answer(
    first_window: str,
    continue_fn: Callable[[str], tuple[str, str | None]],
    *,
    max_windows: int = 4,
    max_total_chars: int = 40_000,
    on_window: Callable[[list[str]], None] | None = None,
) -> ContinuationOutcome:
    """Extend a length-truncated LLM answer using multiple continuation windows.

    ``continue_fn(last_window)`` must return ``(next_window_text,
    finish_reason)``. The loop stops on ``finish_reason == "stop"``, on
    ``max_windows`` reached, or when ``max_total_chars`` is exceeded.

    When ``crp.continuation.stitch`` is available, windows are stitched to
    remove echoed overlap; otherwise they are concatenated with ``\\n\\n``.
    """
    if not first_window:
        return ContinuationOutcome(final_text="", windows=0, termination_reason="empty")

    windows = [first_window]
    last = first_window
    reason = "max_windows"
    if on_window is not None:
        try:
            on_window(list(windows))
        except Exception:  # pragma: no cover - persistence is best-effort
            logger.debug("continuation on_window hook failed", exc_info=True)
    for _ in range(max_windows - 1):
        try:
            nxt, fr = continue_fn(last)
        except Exception:
            reason = "dispatch_error"
            break
        if not nxt:
            reason = "empty_continuation"
            break
        windows.append(nxt)
        last = nxt
        if on_window is not None:
            try:
                on_window(list(windows))
            except Exception:  # pragma: no cover
                logger.debug("continuation on_window hook failed", exc_info=True)
        if fr == "stop":
            reason = "stop"
            break
        if sum(len(w) for w in windows) >= max_total_chars:
            reason = "max_chars"
            break

    stitched = False
    try:
        from crp.continuation.stitch import stitch_many  # type: ignore[import-not-found]

        stitched_result = stitch_many(windows)
        combined = getattr(stitched_result, "text", None) or "\n\n".join(windows)
        stitched = True
    except Exception:  # pragma: no cover
        combined = "\n\n".join(windows)

    return ContinuationOutcome(
        final_text=combined,
        windows=len(windows),
        termination_reason=reason,
        stitched=stitched,
    )


# =============================================================================
# Free-text extraction (clarification answers → structured Facts)
# =============================================================================


@dataclass
class ExtractedClarification:
    """Output of running ``crp.extraction.pipeline`` on a free-text answer."""

    facts: list[Any] = field(default_factory=list)
    contradictions: list[dict[str, Any]] = field(default_factory=list)
    quality_issues: list[str] = field(default_factory=list)

    @property
    def fact_count(self) -> int:
        return len(self.facts)


def extract_facts_from_text(
    text: str,
    *,
    source_window_id: str = "clarification",
    category: str = "user_clarification",
) -> ExtractedClarification:
    """Run ``crp.extraction.ExtractionPipeline`` over a free-text user reply.

    Closes LLM_INTELLIGENCE_DESIGN §3.3: clarification answers should not
    just be stored as opaque blobs — the 6-stage extractor pulls
    structured ``Fact`` objects out (entities, scopes, dates, claims) so
    they become first-class citizens in the CKF.

    Best-effort: returns an empty :class:`ExtractedClarification` if the
    pipeline is unavailable. Never raises.
    """
    if not text or not text.strip():
        return ExtractedClarification()

    try:
        from crp.extraction import ExtractionPipeline  # type: ignore[import-not-found]
    except Exception:  # pragma: no cover - CRP not installed
        return ExtractedClarification()

    try:
        pipeline = ExtractionPipeline()
        # Sentence-transformers models have a hard 512-token limit (~1700
        # chars at 3.3 cpt). Feeding longer text produces the warning
        # "Asking to truncate to max_length but no maximum length is
        # provided" and silently truncates — worse, on Railway CPU it
        # can add several seconds of blocking inference. We truncate to
        # 1500 chars (≈455 tokens) before handing off; facts beyond this
        # window are covered by the CKF / RAG layer anyway.
        _extract_text = text[:1500] if len(text) > 1500 else text
        result = pipeline.extract(_extract_text)
    except Exception:
        logger.debug("ExtractionPipeline.extract failed", exc_info=True)
        return ExtractedClarification()

    raw_facts = list(getattr(result, "facts", None) or [])
    # Tag every fact with its provenance so the CKF can show them in the
    # programme tracker as "answered by the user, extracted automatically".
    for f in raw_facts:
        try:
            if not getattr(f, "category", None):
                f.category = category
            if not getattr(f, "source_window_id", None):
                f.source_window_id = source_window_id
        except Exception as _bandit_exc:
            logger.debug("swallowed in _extract_clarifications: %s", _bandit_exc)
            continue

    contradictions: list[dict[str, Any]] = []
    for c in getattr(result, "contradictions", None) or []:
        try:
            contradictions.append(
                {
                    "fact_a_id": getattr(c.fact_a, "id", ""),
                    "fact_b_id": getattr(c.fact_b, "id", ""),
                    "similarity": round(float(c.similarity), 4),
                    "confidence": round(float(c.confidence), 4),
                }
            )
        except Exception as _bandit_exc:
            logger.debug("swallowed in _extract_contradictions: %s", _bandit_exc)
            continue

    quality: list[str] = []
    for issue in getattr(result, "quality_issues", None) or []:
        msg = getattr(issue, "message", None) or str(issue)
        if msg:
            quality.append(str(msg)[:240])

    return ExtractedClarification(
        facts=raw_facts,
        contradictions=contradictions,
        quality_issues=quality,
    )


# =============================================================================
# Live CKF contradiction detection (clarification vs prior facts)
# =============================================================================


def detect_ckf_contradictions(
    new_facts: Sequence[Any],
    existing_facts: Sequence[Any],
    *,
    similarity_threshold: float = 0.65,
    content_diff_threshold: float = 0.25,
) -> list[dict[str, Any]]:
    """Flag when freshly-extracted facts contradict prior CKF facts.

    Closes LLM_INTELLIGENCE_DESIGN §3.3: "If a user says 'we don't
    process biometric data' but an earlier CKF node says the system does
    facial recognition, the agent surfaces the conflict before writing a
    wrong report."
    """
    if not new_facts or not existing_facts:
        return []
    try:
        from crp.extraction.contradiction import detect_contradictions  # type: ignore[import-not-found]
    except Exception:  # pragma: no cover
        return []

    try:
        contradictions = detect_contradictions(
            new_facts=list(new_facts),
            existing_facts=list(existing_facts),
            similarity_threshold=similarity_threshold,
            content_diff_threshold=content_diff_threshold,
        )
    except Exception:
        logger.debug("detect_contradictions on CKF failed", exc_info=True)
        return []

    out: list[dict[str, Any]] = []
    for c in contradictions:
        try:
            out.append(
                {
                    "new_fact_id": getattr(c.fact_a, "id", ""),
                    "prior_fact_id": getattr(c.fact_b, "id", ""),
                    "new_text": (getattr(c.fact_a, "text", "") or "")[:240],
                    "prior_text": (getattr(c.fact_b, "text", "") or "")[:240],
                    "similarity": round(float(c.similarity), 4),
                    "content_diff": round(float(c.content_diff), 4),
                    "confidence": round(float(c.confidence), 4),
                }
            )
        except Exception as _bandit_exc:
            logger.debug("swallowed in _extract_quality_issues: %s", _bandit_exc)
            continue
    return out


# =============================================================================
# Named pattern query (typed wrapper over fabric.query)
# =============================================================================


def pattern_query_ckf(
    fabric: Any,
    *,
    entity_type: str | None = None,
    relationship_type: str | None = None,
    min_confidence: float = 0.0,
    max_results: int = 20,
) -> dict[str, Any]:
    """Typed wrapper around :func:`crp.ckf.pattern_query`.

    Falls through to ``fabric.query(**kwargs)`` when the named function
    is not exposed by the installed CRP build, so the caller never has
    to branch on availability.
    """
    if fabric is None:
        return {"facts": [], "matched_count": 0}

    try:
        from crp.ckf import pattern_query  # type: ignore[import-not-found]

        result = pattern_query(
            fabric,
            entity_type=entity_type,
            relationship_type=relationship_type,
            min_confidence=min_confidence,
            max_results=max_results,
        )
        facts = list(getattr(result, "facts", None) or [])
        matched = int(getattr(result, "matched_count", len(facts)))
        return {"facts": facts, "matched_count": matched}
    except Exception:
        logger.debug("crp.ckf.pattern_query unavailable; using fabric.query", exc_info=True)

    # Fallback to the generic protocol.
    try:
        result = fabric.query(
            entity_type=entity_type,
            relationship_type=relationship_type,
            min_confidence=min_confidence,
            max_results=max_results,
        )
    except TypeError:
        result = fabric.query()
    except Exception:
        return {"facts": [], "matched_count": 0}

    facts = list(getattr(result, "facts", None) or (result if isinstance(result, list) else []))
    return {"facts": facts, "matched_count": len(facts)}


# =============================================================================
# CRP observability event emitter (best-effort wrapper)
# =============================================================================


class CrpEventBus:
    """Emit structured events through ``crp.observability`` when present.

    Falls back to logger-only emission if the observability module is
    not installed. The wrapper keeps the orchestrator code free of
    optional-dependency branches.
    """

    def __init__(self, sink: Any | None = None) -> None:
        self._emitter: Any | None = None
        self._sink = sink
        try:
            from crp.observability.events import EventEmitter  # type: ignore[import-not-found]

            self._emitter = EventEmitter()
        except Exception:  # pragma: no cover
            self._emitter = None

    @property
    def crp_active(self) -> bool:
        return self._emitter is not None

    def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        """Emit ``event_type`` with ``payload`` — never raises."""
        try:
            if self._emitter is not None:
                emit = getattr(self._emitter, "emit", None)
                if emit is not None:
                    emit(event_type, dict(payload))
        except Exception:
            logger.debug("EventEmitter.emit failed for %s", event_type, exc_info=True)
        if self._sink is not None:
            try:
                self._sink({"type": event_type, **payload})
            except Exception:
                logger.debug("event sink failed for %s", event_type, exc_info=True)


# =============================================================================
# Prompt-injection scan (pre-LLM, agent-side mirror of proxy interceptor)
# =============================================================================


@dataclass
class InjectionReport:
    """Outcome of a CRP InjectionDetector scan on agent input.

    ``risk`` is one of ``"NONE"`` / ``"MEDIUM"`` / ``"HIGH"``.
    """

    risk: str = "NONE"
    confidence: float = 0.0
    flags: list[str] = field(default_factory=list)


def scan_for_injection(text: str) -> InjectionReport:
    """Scan ``text`` for prompt-injection attempts using ``crp.security.InjectionDetector``.

    Mirrors the protection that ``proxy/interceptor.py`` already runs at
    the proxy boundary, but applied to the *agent loop* user input so
    self-hosted agent calls (which bypass the proxy) still get the
    21-pattern + optional ML detection. Best-effort: returns
    :class:`InjectionReport` with ``risk='NONE'`` if CRP is unavailable
    or scanning fails. Never raises.
    """
    if not text or not text.strip():
        return InjectionReport()
    try:
        from crp.security import InjectionDetector  # type: ignore[import-not-found]
    except Exception:  # pragma: no cover
        return InjectionReport()
    try:
        detector = InjectionDetector()
        report = detector.scan(text)
    except Exception:
        logger.debug("InjectionDetector.scan failed", exc_info=True)
        return InjectionReport()

    has_flags = bool(getattr(report, "has_flags", False))
    if not has_flags:
        return InjectionReport()
    confidence = float(getattr(report, "highest_confidence", 0.0) or 0.0)
    if confidence >= 0.80:
        risk = "HIGH"
    elif confidence >= 0.50:
        risk = "MEDIUM"
    else:
        risk = "MEDIUM"
    flag_names: list[str] = []
    for f in getattr(report, "flags", None) or []:
        try:
            label = (
                getattr(f, "pattern", None)
                or getattr(f, "name", None)
                or getattr(f, "category", None)
            )
            if label:
                flag_names.append(str(label)[:80])
        except Exception:
            continue
    return InjectionReport(risk=risk, confidence=round(confidence, 3), flags=flag_names[:8])


# =============================================================================
# Proactive message compaction (CRP input-context window)
# =============================================================================


def _approx_tokens(s: str, chars_per_token: float = 3.3) -> int:
    if not s:
        return 0
    return max(1, int(len(s) / chars_per_token + 0.5))


def _message_text(msg: dict[str, Any]) -> str:
    """Best-effort flatten of an OpenAI-style message into a string."""
    content = msg.get("content")
    if isinstance(content, str):
        body = content
    elif isinstance(content, list):
        # multimodal content array
        parts: list[str] = []
        for p in content:
            if isinstance(p, dict):
                parts.append(str(p.get("text") or p.get("content") or ""))
            else:
                parts.append(str(p))
        body = " ".join(parts)
    else:
        body = ""
    tcs = msg.get("tool_calls")
    if isinstance(tcs, list) and tcs:
        body += " " + json.dumps(tcs, default=str)
    return body


def compact_messages_for_budget(
    messages: list[dict[str, Any]],
    *,
    budget_tokens: int,
    keep_last: int = 4,
    chars_per_token: float = 3.3,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Proactive CRP-style input-context compaction.

    The CRP protocol's headline guarantee is that callers never overflow
    a model's context window: large histories are *folded* into the
    envelope budget rather than the call being retried with greedy
    eviction. This helper applies that contract at the agent's tool-loop
    layer:

      * The system prompt is always preserved verbatim.
      * The first user turn (the original task) is always preserved.
      * The most-recent ``keep_last`` turns are always preserved (the
        model needs the live tool result it was just handed).
      * Older ``tool`` results are replaced with a one-line CRP marker
        ``[CRP-folded: <name> \u2014 <N> chars elided. Re-call to refetch.]``
        which keeps the assistant\u2192tool message structure valid (so the
        OpenAI tool-call protocol is not broken) while reclaiming space.
      * Older assistant prose is truncated to a leading sentence.

    Returns ``(new_messages, stats)`` where ``stats`` contains
    ``before``/``after`` token estimates and a ``folded`` count.
    Compaction is a no-op when the estimated total already fits within
    ``budget_tokens``.
    """
    if budget_tokens <= 0 or not messages:
        return messages, {"before": 0, "after": 0, "folded": 0, "skipped": True}

    sizes = [_approx_tokens(_message_text(m), chars_per_token) for m in messages]
    before = sum(sizes)
    if before <= budget_tokens:
        return messages, {"before": before, "after": before, "folded": 0, "skipped": True}

    n = len(messages)
    pinned: set[int] = set()
    # Pin every system message — EXCEPT those explicitly stamped with
    # ``name="crp_*_primer"`` / ``name="crp_*_seed"`` /
    # ``name="crp_session_context"`` markers, which the orchestrator
    # uses for the foldable per-session preambles (corpus primer,
    # task-evidence primer, CKF facts seed, session context). Without
    # this, a 4000-token primer would stay pinned forever and starve
    # every long session on small-context models. See CRP_AUDIT_3 §0
    # B-4 + 9 May 2026 LM Studio overflow incident.
    _FOLDABLE_NAMES = {
        "crp_corpus_primer",
        "crp_evidence_primer",
        "crp_ckf_seed",
        "crp_session_context",
        "crp_conversation_facts",
    }
    primer_indices: list[int] = []
    for i, m in enumerate(messages):
        if m.get("role") == "system":
            if m.get("name") in _FOLDABLE_NAMES:
                primer_indices.append(i)
                continue  # foldable
            pinned.add(i)
    # Pin the first user turn (the task).
    for i, m in enumerate(messages):
        if m.get("role") == "user":
            pinned.add(i)
            break
    # Pin the tail.
    for i in range(max(0, n - keep_last), n):
        pinned.add(i)

    out: list[dict[str, Any]] = list(messages)
    folded = 0

    # Zeroth pass: fold every foldable system primer the moment we are
    # over budget. The original code only folded once the live history
    # had grown past 60% of the budget, but on TURN 1 (no tool calls
    # yet, just primers + task) the primers ARE the entire prompt — so
    # the threshold check would never fire and the primers would stay
    # at 4000+ tokens, blowing a 4096-token LM Studio model. The CRP
    # contract is unconditional: if we are over budget, we fold.
    for primer_idx in primer_indices:
        if primer_idx in pinned:
            continue
        primer_msg = out[primer_idx]
        primer_text = _message_text(primer_msg)
        if not primer_text:
            continue
        primer_name = primer_msg.get("name") or "crp_primer"
        marker = (
            f"[CRP-folded: {primer_name} \u2014 "
            f"{len(primer_text)} chars elided. The relevant material has "
            "been pre-ingested into the warm fact store; call "
            "``query_regulation``, ``recall_facts`` or "
            "``query_regulation_packed`` to refetch any clause you need "
            "to cite.]"
        )
        out[primer_idx] = {**primer_msg, "content": marker}
        folded += 1
        sizes[primer_idx] = _approx_tokens(marker, chars_per_token)
        if sum(sizes) <= budget_tokens:
            return out, {
                "before": before,
                "after": sum(sizes),
                "folded": folded,
                "skipped": False,
            }

    # First pass: fold tool results.
    for i in range(n):
        if i in pinned:
            continue
        m = out[i]
        if m.get("role") != "tool":
            continue
        original = _message_text(m)
        if not original:
            continue
        marker = (
            f"[CRP-folded: {m.get('name') or 'tool_result'} \u2014 "
            f"{len(original)} chars elided. Re-call the tool if you need this evidence.]"
        )
        out[i] = {**m, "content": marker}
        folded += 1
        # Recompute and stop early if we're under budget.
        sizes[i] = _approx_tokens(marker, chars_per_token)
        if sum(sizes) <= budget_tokens:
            return out, {"before": before, "after": sum(sizes), "folded": folded, "skipped": False}

    # Second pass: truncate old assistant prose (preserve tool_calls so
    # the call/result chain stays valid for the upstream).
    for i in range(n):
        if i in pinned:
            continue
        m = out[i]
        if m.get("role") != "assistant":
            continue
        content = m.get("content")
        if isinstance(content, str) and content:
            head = content.strip().split("\n", 1)[0][:160]
            new_content = head + " [CRP-folded prose]" if head else "[CRP-folded prose]"
            out[i] = {**m, "content": new_content}
            folded += 1
            sizes[i] = _approx_tokens(new_content, chars_per_token)
            if sum(sizes) <= budget_tokens:
                break

    # Second-and-a-half pass: old user messages between the original task
    # and the live tail can also starve a small context window. Truncate
    # them to a leading sentence so the conversation structure survives.
    for i in range(n):
        if i in pinned:
            continue
        m = out[i]
        if m.get("role") != "user":
            continue
        content = m.get("content")
        if isinstance(content, str) and content:
            head = content.strip().split("\n", 1)[0][:120]
            new_content = (
                head + " [CRP-folded user message]" if head else "[CRP-folded user message]"
            )
            out[i] = {**m, "content": new_content}
            folded += 1
            sizes[i] = _approx_tokens(new_content, chars_per_token)
            if sum(sizes) <= budget_tokens:
                break

    # Third pass: evict old unpinned conversational turns. On tiny
    # windows even aggressively truncated user/assistant pairs
    # accumulate. Dropping them entirely (with a marker so the model
    # knows history was elided) is the next CRP strategy to honour the
    # "never overflow" contract. Tool messages are left alone — they
    # were handled in the first pass.
    if sum(sizes) > budget_tokens:
        evicted = 0
        new_out: list[dict[str, Any]] = []
        new_sizes: list[int] = []
        for i, m in enumerate(out):
            if i in pinned:
                new_out.append(m)
                new_sizes.append(sizes[i])
                continue
            role = m.get("role")
            if role in ("user", "assistant"):
                evicted += 1
                continue
            new_out.append(m)
            new_sizes.append(sizes[i])
        if evicted:
            marker = (
                f"[CRP-folded: {evicted} prior conversational turn(s) elided "
                "to fit the context budget. Recent turns and the current "
                "task are preserved.]"
            )
            insert_at = 1 if new_out and new_out[0].get("role") == "system" else 0
            new_out.insert(insert_at, {"role": "system", "content": marker})
            new_sizes.insert(insert_at, _approx_tokens(marker, chars_per_token))
            out = new_out
            sizes = new_sizes
            folded += evicted

    # Fourth pass — last resort. If even after folding all unpinned
    # messages we are still over budget, the tail itself is too big
    # (a single ``query_regulation`` response can carry several
    # thousand tokens on small-context models). The CRP contract is
    # "never overflow" — so we now fold even pinned tail tool results,
    # working oldest-tail-first and stopping the moment we fit. The
    # most recent tool result (the one the model is reasoning about
    # right now) is preserved unless it alone exceeds the budget, in
    # which case its body is hard-clipped.
    if sum(sizes) > budget_tokens:
        tail_tool_indices = [
            i for i in range(max(0, n - keep_last), n) if out[i].get("role") == "tool"
        ]
        # Fold from oldest-of-tail to newest, keeping the very last
        # tool message untouched for as long as possible.
        for i in tail_tool_indices[:-1]:
            m = out[i]
            original = _message_text(m)
            if not original:
                continue
            marker = (
                f"[CRP-folded: {m.get('name') or 'tool_result'} \u2014 "
                f"{len(original)} chars elided to honour the context "
                "budget. Re-call if needed.]"
            )
            out[i] = {**m, "content": marker}
            folded += 1
            sizes[i] = _approx_tokens(marker, chars_per_token)
            if sum(sizes) <= budget_tokens:
                break

        # Still over? The last tool message is the offender. Hard-clip
        # its body to whatever budget remains so the OpenAI tool-call
        # protocol stays valid (assistant → tool message pairing).
        if sum(sizes) > budget_tokens and tail_tool_indices:
            last_i = tail_tool_indices[-1]
            other_total = sum(s for j, s in enumerate(sizes) if j != last_i)
            remaining = max(256, budget_tokens - other_total)
            max_chars = max(512, int(remaining * chars_per_token))
            m = out[last_i]
            content = m.get("content")
            if isinstance(content, str) and len(content) > max_chars:
                clipped = content[:max_chars] + " [CRP-clipped to fit budget]"
                out[last_i] = {**m, "content": clipped}
                folded += 1
                sizes[last_i] = _approx_tokens(clipped, chars_per_token)

    # Final scorched-earth pass — if we are STILL over budget after
    # every other strategy, the prompt's pinned system messages
    # themselves are the offender (a 4000-token main system prompt on a
    # 4096-token model, or a "Session context" / CKF preload that the
    # orchestrator forgot to stamp with a foldable name). Hard-clip
    # every system message except index 0 (the agent's main prompt,
    # which we leave intact so the model's role still has a coherent
    # frame) and, if even that fails, hard-clip the main system prompt
    # itself. The CRP contract is unconditional: never overflow.
    if sum(sizes) > budget_tokens:
        for i in range(1, n):
            m = out[i]
            if m.get("role") != "system":
                continue
            content = m.get("content")
            if not isinstance(content, str) or not content:
                continue
            other_total = sum(s for j, s in enumerate(sizes) if j != i)
            remaining = max(128, budget_tokens - other_total)
            max_chars = max(256, int(remaining * chars_per_token))
            if len(content) > max_chars:
                name_tag = m.get("name") or "system_context"
                clipped = content[:max_chars] + f" [CRP-clipped {name_tag} to fit budget]"
                out[i] = {**m, "content": clipped}
                folded += 1
                sizes[i] = _approx_tokens(clipped, chars_per_token)
                if sum(sizes) <= budget_tokens:
                    break

        # If we are still over budget after folding every named
        # primer the only thing left to clip is the main system
        # prompt at index 0 — but a model whose role/instructions
        # have been amputated will produce garbage tool calls (see
        # the 9 May 2026 LM Studio log: with a clipped system prompt
        # the model called ``recall_facts(min_confidence="0",
        # max_results="20")`` — strings instead of numbers — and
        # never reached ``query_regulation`` first as instructed).
        # We refuse to clip index 0. The orchestrator's CRP
        # carrier-fit gate is supposed to prevent this case before
        # the slate is ever built; if we get here something upstream
        # is wrong and the caller should see a clean error rather
        # than a brain-damaged completion.

    return out, {
        "before": before,
        "after": sum(sizes),
        "folded": folded,
        "skipped": False,
    }


# ─────────────────────────────────────────────────────────────────────
# CRP auto-ingest of oversized tool-result messages
#
# This is the **input-ingestion** half of the CRP "never overflow"
# guarantee. ``compact_messages_for_budget`` (above) folds OLD messages
# once the slate as a whole has grown past budget — but it cannot help
# when a SINGLE freshly-arrived tool result is itself larger than the
# model's context window (e.g. a 6000-token ``query_regulation`` blob
# landing in a 4096-token LM Studio session).
#
# ``crp_autoingest_message`` runs the SDK's
# :func:`crp.advanced.auto_ingest.auto_ingest` over the body of an
# oversized tool message: structure-aware chunking, per-chunk fact
# extraction (via :class:`crp.extraction.pipeline.ExtractionPipeline`
# when available, otherwise auto_ingest's built-in fallback), boundary
# reconciliation, and synthesis. The bulky JSON content is replaced
# with a short summary string; the extracted ``Fact`` objects are
# pushed into the agent's session warm store so the next envelope
# rebuild surfaces them naturally.
#
# Best-effort: if any CRP subsystem is unavailable the original
# message is returned untouched.
# ─────────────────────────────────────────────────────────────────────


def crp_autoingest_message(
    message: dict[str, Any],
    *,
    warm_store: Any | None = None,
    context_window: int,
    threshold_tokens: int = 1500,
    system_prompt: str = "",
    task_intent: str = "",
    tool_name: str = "",
    chars_per_token: float = 3.3,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compress an oversized tool-result message via CRP auto-ingest.

    Args:
        message: An OpenAI-style message dict (typically ``role="tool"``).
        warm_store: Optional :class:`crp.state.WarmStateStore` instance.
            When provided, extracted facts are persisted there with a
            unique source-window id so subsequent envelope rebuilds can
            surface them.
        context_window: The model's full context window in tokens. Used
            by ``auto_ingest`` to size structure-aware chunks.
        threshold_tokens: Messages whose body is below this token count
            are returned untouched. Default 1500 keeps the helper out of
            the way for normal-sized tool results.
        system_prompt: Active system prompt (used by ``auto_ingest`` to
            compute the available token budget).
        task_intent: Short description of what the agent is trying to do
            (used by ``auto_ingest`` for the synthesised reference).
        tool_name: Name of the tool whose output is being ingested
            (surfaces in the synthesised summary).
        chars_per_token: Heuristic for the local token approximation.

    Returns:
        ``(new_message, stats)``. ``stats["skipped"]`` is True when no
        compression occurred. On compression, ``stats`` reports the
        chunk count, fact counts and the warm-store persistence count.
    """
    body = _message_text(message)
    if not body:
        return message, {"skipped": True, "reason": "empty"}
    approx = _approx_tokens(body, chars_per_token)
    if approx < int(threshold_tokens):
        return message, {
            "skipped": True,
            "reason": "under_threshold",
            "tokens": approx,
        }

    try:
        from crp.advanced.auto_ingest import (  # type: ignore[import-not-found]
            IngestFact,
            auto_ingest,
        )
    except Exception:
        return message, {"skipped": True, "reason": "crp_unavailable"}

    def _count(text: str) -> int:
        return _approx_tokens(text, chars_per_token)

    # Optional graduated extraction pipeline. When unavailable,
    # auto_ingest uses its built-in fallback (one fact per chunk).
    extract_fn: Callable[[str, str], list[Any]] | None = None
    try:
        from crp.extraction.pipeline import (  # type: ignore[import-not-found]
            ExtractionPipeline,
        )

        _pipe = ExtractionPipeline()
        _ai_window_id = f"crp-comply-autoingest-{tool_name or 'tool'}-{uuid.uuid4().hex[:8]}"

        def _extract_fn(chunk_text: str, _intent: str) -> list[Any]:
            try:
                if not hasattr(_pipe, "extract"):
                    return []
                # Guard against the "Asking to truncate to max_length but
                # no maximum length is provided" warning from the
                # sentence-transformers tokenizer. Chunks from auto_ingest
                # should already be small, but we cap at 1500 chars
                # (≈ 455 tokens) to be safe.
                _safe_chunk = chunk_text[:1500] if len(chunk_text) > 1500 else chunk_text
                ex_result = _pipe.extract(
                    _safe_chunk,
                    source_window_id=_ai_window_id,
                )
                facts_in = list(getattr(ex_result, "facts", []) or [])
                return [
                    IngestFact(
                        text=str(getattr(f, "text", ""))[:2000],
                        confidence=float(getattr(f, "confidence", 0.6)),
                        source=str(getattr(f, "source_window_id", "") or _ai_window_id),
                    )
                    for f in facts_in
                ]
            except Exception:
                logger.debug("extract_fn failed", exc_info=True)
                return []

        extract_fn = _extract_fn
    except Exception:
        extract_fn = None

    try:
        ingest_facts, ingest_result = auto_ingest(
            system_prompt=system_prompt or "",
            task_input=body,
            task_intent_text=(task_intent or tool_name or "tool result")[:500],
            context_window=max(1024, int(context_window)),
            count_tokens=_count,
            extract_fn=extract_fn,
        )
    except Exception:
        logger.debug("auto_ingest failed", exc_info=True)
        return message, {"skipped": True, "reason": "auto_ingest_error"}

    # Persist extracted facts to the agent's warm store so the next
    # envelope rebuild can surface them. Best-effort.
    stored = 0
    if warm_store is not None and ingest_facts:
        try:
            from crp.extraction.types import Fact  # type: ignore[import-not-found]

            window_id = f"crp-comply-autoingest-{tool_name or 'tool'}-{uuid.uuid4().hex[:8]}"
            facts_objs: list[Any] = []
            for ifact in ingest_facts[:200]:
                text = str(getattr(ifact, "text", ""))[:2000]
                if not text:
                    continue
                facts_objs.append(
                    Fact(
                        text=text,
                        confidence=float(getattr(ifact, "confidence", 0.6)),
                        source_window_id=window_id,
                        extraction_stage=0,
                    )
                )
            if facts_objs and hasattr(warm_store, "add_facts"):
                warm_store.add_facts(facts_objs)
                stored = len(facts_objs)
        except Exception:
            logger.debug("warm_store.add_facts failed", exc_info=True)

    summary = (
        f"[CRP auto-ingested {tool_name or message.get('name') or 'tool_result'}: "
        f"{ingest_result.chunks_created} chunks \u2192 "
        f"{ingest_result.facts_after_reconciliation} facts "
        f"(stored={stored}, original\u2248{approx} tokens). "
        f"Specifics will surface in the next envelope rebuild; re-call the "
        f"same tool with a narrower query if you need an exact quote.]\n"
        f"Synthesised intent: {ingest_result.synthesized_task[:400]}"
    )
    new_msg = {**message, "content": summary}
    return new_msg, {
        "skipped": False,
        "original_tokens": approx,
        "summary_tokens": _approx_tokens(summary, chars_per_token),
        "chunks": ingest_result.chunks_created,
        "facts_extracted": ingest_result.facts_extracted,
        "facts_after_reconciliation": ingest_result.facts_after_reconciliation,
        "facts_stored_in_warm": stored,
    }


# ─────────────────────────────────────────────────────────────────────
# Phase 3 — native CRP dispatch wrappers
# ─────────────────────────────────────────────────────────────────────


@dataclass
class CrpDispatchOutcome:
    """Result of running a task through one of CRP's native dispatch
    methods (``dispatch``, ``dispatch_with_tools``, ``dispatch_agentic``,
    ``dispatch_stream_augmented``).

    ``mode`` records which strategy was used so callers can attribute
    behaviour back to the CRP cognitive loop. ``quality`` is the
    :class:`crp.QualityReport` returned by the SDK (or ``None`` if the
    dispatch fell back to plain text generation).
    """

    output: str
    mode: str
    quality: Any | None = None
    error: str = ""


# ─────────────────────────────────────────────────────────────────────
# CRP message ledger — comprehensive integration of WarmStateStore +
# ExtractionPipeline + envelope packer + supersession on the live
# tool-calling loop.
#
# This is the "massive context processing" capability: instead of
# letting tool results pile up as raw JSON in ``messages``, every
# tool result is run through CRP extraction, stored as ``Fact`` objects
# in a session-scoped warm store, contradictions are detected and
# stale facts are superseded, and before each LLM call the message
# history is *rebuilt* from a freshly packed CRP envelope. The result:
# the LLM never sees more than ``budget_tokens`` worth of evidence at
# a time, and that evidence is the highest-relevance, deduplicated,
# supersession-aware slate the warm store can produce.
# ─────────────────────────────────────────────────────────────────────


class CrpMessageLedger:
    """Per-session CRP fact ledger that drives message-history rebuilds.

    Pipeline per tool result:

    1. ``ingest_tool_result(name, payload)`` extracts ``Fact`` objects
       from the JSON response (regulation hits, recipe outputs,
       web-search snippets, classification verdicts) and stores them in
       a :class:`crp.state.WarmStateStore` with a stable per-call id.
    2. New facts are checked against existing warm-store facts via
       :func:`crp.extraction.contradiction.detect_contradictions`; on
       high-confidence contradictions, the older fact is superseded.
    3. ``pack_envelope(task, budget_tokens)`` runs the warm store's
       ranked facts through :func:`crp.envelope.packer.pack_facts` and
       returns a single Markdown evidence digest sized to fit the
       budget. The orchestrator inserts this digest into the message
       history *in place of* the bulk tool-result JSON.

    All CRP imports are lazy and best-effort; if a subsystem is
    missing the ledger silently degrades to a list-of-dicts shim that
    still respects the budget.
    """

    def __init__(self, *, max_facts: int = 4000) -> None:
        self._store: Any | None = None
        self._max_facts = max(64, int(max_facts))
        self._fact_count = 0
        self._supersessions = 0
        self._tool_calls_ingested = 0
        # Fallback flat storage when WarmStateStore is unavailable.
        self._fallback: list[dict[str, Any]] = []
        try:
            from crp.state.warm_store import (  # type: ignore[import-not-found]
                WarmStateStore,
                WarmStoreConfig,
            )

            self._store = WarmStateStore(WarmStoreConfig(max_facts=self._max_facts))
        except Exception:  # pragma: no cover
            logger.debug("WarmStateStore unavailable; ledger fallback active", exc_info=True)

    @property
    def fact_count(self) -> int:
        if self._store is not None:
            try:
                return int(self._store.fact_count)
            except Exception:
                return 0
        return len(self._fallback)

    @property
    def supersessions(self) -> int:
        return self._supersessions

    @property
    def tool_calls_ingested(self) -> int:
        return self._tool_calls_ingested

    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------

    def ingest_tool_result(
        self,
        tool_name: str,
        payload: Any,
        *,
        call_id: str = "",
        window_id: str = "tool",
    ) -> int:
        """Convert a tool result into ``Fact`` objects and stash them.

        Returns the number of facts added. Never raises.
        """
        self._tool_calls_ingested += 1
        try:
            facts = self._payload_to_facts(tool_name, payload, call_id=call_id, window_id=window_id)
        except Exception:
            logger.debug("payload→facts failed for %s", tool_name, exc_info=True)
            return 0
        if not facts:
            return 0

        if self._store is None:
            # Flat fallback — keep raw dicts under cap.
            for f in facts:
                self._fallback.append(f)
            if len(self._fallback) > self._max_facts:
                self._fallback = self._fallback[-self._max_facts :]
            return len(facts)

        # Detect contradictions vs prior store facts and supersede.
        try:
            from crp.extraction.contradiction import (  # type: ignore[import-not-found]
                detect_contradictions,
            )

            existing = [sf.fact for sf in self._store.get_facts()]
            if existing:
                conflicts = detect_contradictions(
                    new_facts=list(facts),
                    existing_facts=existing,
                    similarity_threshold=0.7,
                    content_diff_threshold=0.3,
                )
                for c in conflicts or []:
                    try:
                        if float(getattr(c, "confidence", 0.0)) >= 0.75:
                            old_id = getattr(c.fact_b, "id", "")
                            new_id = getattr(c.fact_a, "id", "")
                            if old_id and new_id:
                                self._store.supersede(old_id, new_id)
                                self._supersessions += 1
                    except Exception:
                        continue
        except Exception:
            logger.debug("supersession step skipped", exc_info=True)

        try:
            added = self._store.add_facts(list(facts))
            n = len(added)
            self._fact_count += n
            return n
        except Exception:
            logger.debug("warm_store.add_facts failed", exc_info=True)
            return 0

    # ------------------------------------------------------------------
    # Envelope rebuild
    # ------------------------------------------------------------------

    def pack_envelope(
        self,
        *,
        task: str,
        budget_tokens: int,
        chars_per_token: float = 2.5,
        max_facts: int = 60,
    ) -> dict[str, Any]:
        """Produce a budget-bounded evidence digest for ``task``.

        Returns ``{"text", "facts_packed", "total_tokens", "dropped",
        "supersessions"}``. ``text`` is empty when no facts have been
        ingested yet.
        """
        facts = self._collect_active_facts()
        if not facts:
            return {
                "text": "",
                "facts_packed": 0,
                "total_tokens": 0,
                "dropped": 0,
                "supersessions": self._supersessions,
            }

        packed_items: list[dict[str, Any]] = []
        total_tokens = 0
        dropped = 0
        try:
            from crp.envelope.packer import pack_facts  # type: ignore[import-not-found]
            from crp.envelope.scoring import ScoredFact  # type: ignore[import-not-found]
            from crp.extraction.types import FactGraph  # type: ignore[import-not-found]

            scored = [
                ScoredFact(
                    fact=f,
                    score=float(getattr(f, "confidence", 0.5)),
                    sim=float(getattr(f, "confidence", 0.5)),
                    recency=1.0,
                    novelty=1.0,
                    dep_bonus=0.0,
                )
                for f in facts[: max_facts * 2]
            ]
            scored.sort(key=lambda s: s.score, reverse=True)
            scored = scored[:max_facts]
            result = pack_facts(
                scored_facts=scored,
                graph=FactGraph(),
                budget_tokens=int(budget_tokens),
                chars_per_token=chars_per_token,
            )
            for pf in result.packed_facts:
                packed_items.append(
                    {
                        "id": pf.fact_id,
                        "text": pf.text,
                        "tokens": int(pf.tokens),
                        "score": float(pf.score),
                    }
                )
            total_tokens = int(result.total_tokens)
            dropped = max(0, len(scored) - len(packed_items))
        except Exception:
            logger.debug("envelope packer fallback in ledger", exc_info=True)
            # Fallback: greedy by confidence under budget.
            sorted_facts = sorted(
                facts,
                key=lambda f: float(getattr(f, "confidence", 0.0)),
                reverse=True,
            )
            for f in sorted_facts[:max_facts]:
                text = str(getattr(f, "text", "") or "")
                tok = max(1, int(len(text) / chars_per_token + 0.5))
                if total_tokens + tok > budget_tokens:
                    dropped += 1
                    continue
                packed_items.append(
                    {
                        "id": getattr(f, "id", ""),
                        "text": text,
                        "tokens": tok,
                        "score": float(getattr(f, "confidence", 0.5)),
                    }
                )
                total_tokens += tok

        if not packed_items:
            return {
                "text": "",
                "facts_packed": 0,
                "total_tokens": 0,
                "dropped": dropped,
                "supersessions": self._supersessions,
            }

        # Render into a compact Markdown digest the LLM can read.
        lines = [
            "## CRP evidence ledger (envelope-packed, budget-bounded)",
            (
                f"_{len(packed_items)} facts · {total_tokens} tokens · "
                f"{dropped} dropped · {self._supersessions} superseded · "
                "older bulk tool results have been folded — "
                "call ``recall_facts`` or ``query_regulation`` to refetch._"
            ),
            "",
        ]
        for item in packed_items:
            txt = item["text"].strip().replace("\n", " ")
            if len(txt) > 600:
                txt = txt[:597] + "…"
            tag = f"[{item['id']}]" if item["id"] else ""
            lines.append(f"- {tag} {txt}")
        return {
            "text": "\n".join(lines),
            "facts_packed": len(packed_items),
            "total_tokens": total_tokens,
            "dropped": dropped,
            "supersessions": self._supersessions,
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _collect_active_facts(self) -> list[Any]:
        if self._store is not None:
            try:
                return [sf.fact for sf in self._store.get_facts()]
            except Exception:
                return []
        # Fallback path: synthesise lightweight Fact-like objects
        try:
            from crp.extraction import Fact  # type: ignore[import-not-found]
        except Exception:
            Fact = None  # type: ignore[assignment]

        out: list[Any] = []
        for d in self._fallback:
            if Fact is not None:
                out.append(
                    Fact(
                        id=str(d.get("id") or uuid.uuid4()),
                        text=str(d.get("text") or ""),
                        category=str(d.get("category") or "tool"),
                        source_window_id=str(d.get("window_id") or "tool"),
                        confidence=float(d.get("confidence") or 0.5),
                        extraction_stage=0,
                        created_at=time.time(),
                        metadata=dict(d.get("metadata") or {}),
                    )
                )
            else:
                out.append(d)
        return out

    def _payload_to_facts(
        self,
        tool_name: str,
        payload: Any,
        *,
        call_id: str,
        window_id: str,
    ) -> list[Any]:
        """Per-tool extraction of structured Facts from a tool payload."""
        try:
            from crp.extraction import Fact  # type: ignore[import-not-found]
        except Exception:
            return []
        if not isinstance(payload, dict):
            return []

        out: list[Any] = []

        def _mk(
            text: str, *, category: str, confidence: float, meta: dict[str, Any] | None = None
        ) -> Any:
            t = (text or "").strip()
            if len(t) < 8:
                return None
            return Fact(
                id=hashlib.sha256(f"{call_id}|{category}|{t}".encode("utf-8")).hexdigest()[:24],
                text=t[:1200],
                category=category,
                source_window_id=window_id,
                confidence=max(0.0, min(1.0, float(confidence))),
                extraction_stage=0,
                created_at=time.time(),
                metadata={"tool": tool_name, "call_id": call_id, **(meta or {})},
            )

        # query_regulation → one fact per hit
        if tool_name == "query_regulation":
            for hit in payload.get("hits") or []:
                if not isinstance(hit, dict):
                    continue
                text = str(hit.get("text") or "")
                if not text:
                    continue
                hid = str(hit.get("chunk_id") or "")
                article = str(hit.get("article_id") or "")
                title = str(hit.get("title") or "")
                heading = " · ".join([p for p in (title, article) if p])
                composed = f"{heading} — {text}" if heading else text
                f = _mk(
                    composed,
                    category="regulation_clause",
                    confidence=float(hit.get("score") or 0.6),
                    meta={
                        "chunk_id": hid,
                        "article_id": article,
                        "source_id": hit.get("source_id"),
                        "title": title,
                    },
                )
                if f is not None:
                    # Use the chunk_id as the stable Fact id where available
                    # so re-emitting the same chunk dedups via warm-store
                    # text-hash check.
                    if hid:
                        f.id = f"chunk:{hid}"
                    out.append(f)
            for c in payload.get("contradictions") or []:
                if not isinstance(c, dict):
                    continue
                txt = (
                    f"Contradiction signal between {c.get('fact_a_id')} "
                    f"and {c.get('fact_b_id')} (sim="
                    f"{c.get('similarity')}, conf={c.get('confidence')})"
                )
                f = _mk(txt, category="regulation_contradiction", confidence=0.7)
                if f is not None:
                    out.append(f)

        # classify_ai_act_risk / check_high_risk_criteria
        elif tool_name in ("classify_ai_act_risk", "check_high_risk_criteria"):
            verdict = payload.get("risk_level") or payload.get("classification") or ""
            reasoning = payload.get("reasoning") or payload.get("rationale") or ""
            if verdict or reasoning:
                f = _mk(
                    f"AI Act risk verdict: {verdict}. {reasoning}",
                    category="ai_act_risk_verdict",
                    confidence=0.9,
                )
                if f is not None:
                    out.append(f)

        # web_search / web_research
        elif tool_name in ("web_search", "web_research"):
            for r in payload.get("results") or payload.get("hits") or []:
                if not isinstance(r, dict):
                    continue
                title = str(r.get("title") or "")
                snippet = str(r.get("snippet") or r.get("text") or "")
                url = str(r.get("url") or r.get("href") or "")
                composed = f"{title} ({url}) — {snippet}".strip(" —")
                f = _mk(
                    composed,
                    category="web_evidence",
                    confidence=0.55,
                    meta={"url": url},
                )
                if f is not None:
                    out.append(f)

        # store_fact / recall_facts / generic
        else:
            text = str(payload.get("text") or payload.get("content") or "")
            if text:
                f = _mk(
                    text,
                    category=f"tool.{tool_name}",
                    confidence=0.6,
                )
                if f is not None:
                    out.append(f)

        return out


def fold_messages_with_ledger(
    messages: list[dict[str, Any]],
    *,
    ledger_text: str,
    keep_last: int = 2,
) -> tuple[list[dict[str, Any]], int]:
    """Replace the bulk tool-result history with a single ledger digest.

    The most recent ``keep_last`` tool messages are preserved verbatim
    (the model is actively reasoning about them); every older
    ``role="tool"`` message has its body replaced with a one-line
    pointer back into the ledger. The system prompt and the original
    user task are untouched.

    Returns ``(new_messages, folded_count)``.
    """
    if not messages:
        return list(messages), 0

    n = len(messages)
    tool_idx = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    if not tool_idx:
        return list(messages), 0
    keep = set(tool_idx[-keep_last:]) if keep_last > 0 else set()
    folded = 0
    out: list[dict[str, Any]] = list(messages)

    # Insert the ledger as a system message right before the LAST
    # assistant/tool turn so the LLM sees it as the most-current
    # evidence digest.
    if ledger_text:
        insert_at = n
        for i in range(n - 1, -1, -1):
            if messages[i].get("role") in {"user", "assistant"}:
                insert_at = i + 1
                break
        out.insert(
            insert_at,
            {
                "role": "system",
                "name": "crp_evidence_ledger",
                "content": ledger_text,
            },
        )

    for i in tool_idx:
        if i in keep:
            continue
        m = out[i] if i < len(out) else None
        if not m or m.get("role") != "tool":
            continue
        original = m.get("content") or ""
        if not isinstance(original, str) or not original:
            continue
        marker = (
            f"[CRP-folded: {m.get('name') or 'tool_result'} — "
            f"{len(original)} chars elided. The fact is now in the "
            "CRP evidence ledger above. Re-call the tool only if you "
            "need a value not present there.]"
        )
        out[i] = {**m, "content": marker}
        folded += 1
    return out, folded


#: CRP emitter event types we forward into the orchestrator SSE
#: stream when ``event_sink`` is supplied. Subset chosen to mirror the
#: events the legacy tool loop already emits, so the UI handles them
#: with no extra code.
_CRP_FORWARDED_EVENTS: tuple[str, ...] = (
    "extraction_complete",
    "extraction_quality_low",
    "envelope_packed",
    "dispatch_progress",
    "quality_report",
    "budget_warning",
    "fact_created",
    "fact_updated",
    "fact_rejected",
    "tool_call",
    "tool_result",
    "revision_round",
    "human_oversight_required",
)


def dispatch_via_crp(
    provider: Any,
    *,
    system_prompt: str,
    task: str,
    mode: str = "agentic",
    pre_ingest: list[dict[str, Any]] | None = None,
    pre_ingest_label: str = "agent.preseed",
    max_tool_rounds: int = 10,
    max_revision_rounds: int = 2,
    max_output_tokens: int | None = None,
    event_sink: Callable[[dict[str, Any]], None] | None = None,
) -> CrpDispatchOutcome:
    """Run a single task through CRP's native dispatch loop.

    This is the Phase 3 entry-point for callers who want to bypass the
    bespoke compliance-agent tool loop and instead use CRP's §22
    cognitive protocol end-to-end. It wraps :class:`crp.Client` so the
    LLM provider, WarmStateStore and CKF are all owned and orchestrated
    by the SDK rather than re-implemented in ``crp-comply``.

    Parameters
    ----------
    provider:
        An :class:`crp.providers.base.LLMProvider` instance (any
        ``ComplianceLLM().provider`` is compatible).
    system_prompt:
        System prompt — kept short. Per CRP Axiom 4 the SDK does not
        mutate this string; it is delivered verbatim to the model.
    task:
        Natural-language task / user message.
    mode:
        ``"agentic"`` runs the §22 8-phase loop (analyse → plan →
        synthesise → route → generate → evaluate → revise → curate);
        ``"with_tools"`` runs the pull-mode tool relay using
        ``CRP_CONTEXT_TOOLS``; ``"stream_augmented"`` runs the
        sentence-by-sentence injection loop; ``"plain"`` is the basic
        single-shot push-mode :meth:`crp.Client.dispatch`.
    pre_ingest:
        Optional list of ``{text, source}`` records ingested into the
        client's WarmStateStore *before* dispatch so the cognitive loop
        has facts to retrieve. Best-effort — failures are logged.

    Returns
    -------
    CrpDispatchOutcome
        Always returns; on internal CRP failure the ``error`` field
        carries the message and ``output`` is the empty string.
    """

    try:
        import crp as _crp
    except ImportError as exc:  # pragma: no cover - SDK is a hard dep
        return CrpDispatchOutcome(output="", mode=mode, error=f"crp SDK unavailable: {exc}")

    try:
        client = _crp.Client(provider=provider)
    except Exception as exc:
        logger.exception("crp.Client init failed")
        return CrpDispatchOutcome(output="", mode=mode, error=f"client init: {exc}")

    # Wire the SDK's protocol event bus into the caller's event sink
    # (typically the orchestrator's SSE pump). This is how
    # extraction / quality / budget / revision events surface in the
    # UI when running on the CRP-native dispatch path. Best-effort:
    # an SDK that doesn't expose ``emitter.on`` simply isn't
    # subscribed.
    if event_sink is not None:
        try:
            emitter = getattr(client, "emitter", None)
            if emitter is not None and hasattr(emitter, "on"):

                def _make_listener(evt: str) -> Callable[..., None]:
                    def _forward(payload: Any = None, *args: Any, **kwargs: Any) -> None:
                        try:
                            data: dict[str, Any] = {"event": f"crp_{evt}"}
                            if isinstance(payload, dict):
                                data.update(
                                    {k: v for k, v in payload.items() if isinstance(k, str)}
                                )
                            elif payload is not None:
                                data["payload"] = str(payload)[:2000]
                            event_sink(data)
                        except Exception:
                            logger.debug("event_sink forward failed", exc_info=True)

                    return _forward

                for evt in _CRP_FORWARDED_EVENTS:
                    try:
                        emitter.on(evt, _make_listener(evt))
                    except Exception:
                        # Silently skip event types this SDK build
                        # doesn't recognise.
                        pass
        except Exception:
            logger.debug("emitter wiring failed", exc_info=True)

    if pre_ingest:
        for item in pre_ingest:
            try:
                client.ingest(
                    raw_text=str(item.get("text") or ""),
                    source_label=str(item.get("source") or pre_ingest_label),
                )
            except Exception:
                logger.debug("pre_ingest failed for one item", exc_info=True)

    try:
        # Forward per-tier output-token cap so CRP's dispatch loops
        # honour the same ``max_tokens`` we'd apply on the legacy path.
        # CRP's dispatch methods accept arbitrary ``**kwargs`` and pass
        # them down to the provider's ``generate_chat_*`` calls.
        dispatch_kwargs: dict[str, Any] = {}
        if max_output_tokens is not None and max_output_tokens > 0:
            dispatch_kwargs["max_tokens"] = int(max_output_tokens)

        if mode == "agentic":
            output, report = client.dispatch_agentic(
                system_prompt,
                task,
                max_revision_rounds=max_revision_rounds,
                **dispatch_kwargs,
            )
        elif mode == "with_tools":
            output, report = client.dispatch_with_tools(
                system_prompt,
                task,
                max_tool_rounds=max_tool_rounds,
                **dispatch_kwargs,
            )
        elif mode == "stream_augmented":
            output, report = client.dispatch_stream_augmented(
                system_prompt,
                task,
                **dispatch_kwargs,
            )
        elif mode == "plain":
            res = client.dispatch(system_prompt, task, **dispatch_kwargs)
            # Handle both (text, report) and bare-text return shapes
            if isinstance(res, tuple) and len(res) == 2:
                output, report = res
            else:
                output, report = str(res), None
        else:
            return CrpDispatchOutcome(
                output="",
                mode=mode,
                error=f"unknown dispatch mode: {mode!r}",
            )
        return CrpDispatchOutcome(output=str(output), mode=mode, quality=report)
    except Exception as exc:
        logger.exception("crp dispatch (%s) failed", mode)
        return CrpDispatchOutcome(output="", mode=mode, error=f"{type(exc).__name__}: {exc}")
    finally:
        try:
            client.close()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────
# Phase 5 — direct CRP capability surface (server-side wrappers)
# ─────────────────────────────────────────────────────────────────────


def crp_preview_envelope(
    provider: Any,
    *,
    system_prompt: str,
    task: str,
) -> dict[str, Any]:
    """Return the envelope CRP *would* pack for this task without
    actually dispatching. Mirrors :meth:`crp.Client.preview_envelope`
    so the UI can show "what the model is about to see".

    Returns a plain dict; never raises — failures surface as
    ``{"error": "..."}``.
    """
    try:
        import crp as _crp
    except ImportError as exc:
        return {"error": f"crp SDK unavailable: {exc}"}
    try:
        client = _crp.Client(provider=provider)
    except Exception as exc:
        return {"error": f"client init: {exc}"}
    try:
        preview = client.preview_envelope(system_prompt, task)
        # Normalise to a dict — CRP returns an ``EnvelopePreview`` dataclass.
        if hasattr(preview, "to_dict"):
            return dict(preview.to_dict())
        if hasattr(preview, "__dict__"):
            return {k: v for k, v in vars(preview).items() if not k.startswith("_")}
        return {"raw": str(preview)}
    except Exception as exc:
        logger.debug("preview_envelope failed", exc_info=True)
        return {"error": f"{type(exc).__name__}: {exc}"}
    finally:
        try:
            client.close()
        except Exception:
            pass


def crp_estimate_session(
    provider: Any,
    *,
    system_prompt: str = "",
    task: str = "",
    planned_dispatches: int = 1,
    avg_output_tokens: int | None = None,
) -> dict[str, Any]:
    """Pre-flight cost / token estimate via :meth:`crp.Client.estimate_session`.

    Returns a dict with ``input_tokens``, ``output_tokens``,
    ``total_tokens``, ``estimated_cost_usd`` (when the provider
    publishes pricing). Never raises.
    """
    try:
        import crp as _crp
    except ImportError as exc:
        return {"error": f"crp SDK unavailable: {exc}"}
    try:
        client = _crp.Client(provider=provider)
    except Exception as exc:
        return {"error": f"client init: {exc}"}
    try:
        est = client.estimate_session(
            system_prompt=system_prompt,
            task_input=task,
            planned_dispatches=planned_dispatches,
            avg_output_tokens=avg_output_tokens,
        )
        if hasattr(est, "to_dict"):
            return dict(est.to_dict())
        if hasattr(est, "__dict__"):
            return {k: v for k, v in vars(est).items() if not k.startswith("_")}
        return {"raw": str(est)}
    except Exception as exc:
        logger.debug("estimate_session failed", exc_info=True)
        return {"error": f"{type(exc).__name__}: {exc}"}
    finally:
        try:
            client.close()
        except Exception:
            pass


def crp_apply_feedback(
    provider: Any,
    *,
    fact_id: str,
    signal: str,
    reason: str = "",
    delta: float | None = None,
) -> dict[str, Any]:
    """Forward a per-fact feedback signal to CRP's feedback loop.

    ``signal`` is ``"boost"``, ``"penalize"`` or ``"reject"`` — these
    map directly onto ``Client.boost_fact / penalize_fact /
    reject_fact``. The SDK's feedback loop persists the adjustment in
    the WarmStateStore so subsequent retrievals reflect it.

    Returns ``{"ok": True}`` on success or ``{"error": "..."}``.
    """
    sig = (signal or "").strip().lower()
    if sig not in {"boost", "penalize", "reject"}:
        return {"error": f"invalid signal: {signal!r}"}
    try:
        import crp as _crp
    except ImportError as exc:
        return {"error": f"crp SDK unavailable: {exc}"}
    try:
        client = _crp.Client(provider=provider)
    except Exception as exc:
        return {"error": f"client init: {exc}"}
    try:
        if sig == "boost":
            kwargs: dict[str, Any] = {"reason": reason}
            if delta is not None:
                kwargs["delta"] = float(delta)
            client.boost_fact(fact_id, **kwargs)
        elif sig == "penalize":
            kwargs = {"reason": reason}
            if delta is not None:
                kwargs["delta"] = float(delta)
            client.penalize_fact(fact_id, **kwargs)
        else:  # reject
            client.reject_fact(fact_id, reason=reason)
        return {"ok": True, "signal": sig, "fact_id": fact_id}
    except Exception as exc:
        logger.debug("crp feedback failed", exc_info=True)
        return {"error": f"{type(exc).__name__}: {exc}"}
    finally:
        try:
            client.close()
        except Exception:
            pass


def crp_export_state_bytes(
    provider: Any,
    *,
    fmt: str | None = None,
    pre_ingest: list[dict[str, Any]] | None = None,
    ledger: Any | None = None,
) -> tuple[bytes, str]:
    """Produce a sealed AES-256-GCM state bundle via
    :meth:`crp.Client.export_state`. Used by the
    ``POST /agent/{id}/export`` endpoint to hand off audit-grade
    session evidence.

    Parameters
    ----------
    ledger
        Optional :class:`~crp_comply.agent.crp_ledger.CrpMessageLedger`
        instance. When provided its active facts are folded into
        ``pre_ingest`` so the exported bundle contains the session's
        accumulated evidence (LLM-GAP-D fix — the throwaway client used
        previously never saw live session facts).

    Returns ``(payload_bytes, content_type)``. On failure returns
    ``(b"", "application/json")`` and logs.
    """
    # LLM-GAP-D: if a live ledger is provided, harvest its active facts
    # and prepend them to pre_ingest so the export bundle is complete.
    if ledger is not None:
        try:
            facts = ledger._collect_active_facts()
            ledger_items: list[dict[str, Any]] = [
                {
                    "text": str(getattr(f, "text", "") or ""),
                    "source": str(getattr(f, "category", "agent.ledger") or "agent.ledger"),
                }
                for f in facts
                if str(getattr(f, "text", "") or "").strip()
            ]
            if ledger_items:
                pre_ingest = list(pre_ingest or []) + ledger_items
                logger.debug("crp_export_state_bytes: folded %d ledger facts", len(ledger_items))
        except Exception:
            logger.debug("ledger\u2192pre_ingest for export failed (non-fatal)", exc_info=True)
    try:
        import crp as _crp
    except ImportError:
        return b"", "application/json"
    try:
        client = _crp.Client(provider=provider)
    except Exception:
        logger.exception("client init failed for export_state")
        return b"", "application/json"
    try:
        if pre_ingest:
            for item in pre_ingest:
                try:
                    client.ingest(
                        raw_text=str(item.get("text") or ""),
                        source_label=str(item.get("source") or "agent.export"),
                    )
                except Exception:
                    logger.debug("export pre-ingest failed", exc_info=True)
        kwargs: dict[str, Any] = {}
        if fmt is not None:
            kwargs["fmt"] = fmt
        data = client.export_state(**kwargs)
        if isinstance(data, (bytes, bytearray)):
            return bytes(data), "application/octet-stream"
        # JSON-formatted export
        return str(data).encode("utf-8"), "application/json"
    except Exception:
        logger.exception("export_state failed")
        return b"", "application/json"
    finally:
        try:
            client.close()
        except Exception:
            pass


def crp_ckf_communities(ckf: Any, *, limit: int = 20) -> list[dict[str, Any]]:
    """Return detected fact communities from a CKF instance via
    ``ckf.detect_communities`` + ``community_summary``. Best-effort —
    returns ``[]`` if the SDK build doesn't have Leiden / igraph
    installed (i.e. base ``crprotocol`` instead of ``[full]``).
    """
    out: list[dict[str, Any]] = []
    try:
        if not hasattr(ckf, "detect_communities"):
            return out
        comms = ckf.detect_communities()
    except Exception:
        logger.debug("detect_communities failed", exc_info=True)
        return out
    if not comms:
        return out
    summarise = getattr(ckf, "community_summary", None)
    for cid in list(comms)[:limit]:
        entry: dict[str, Any] = {"community_id": str(cid)}
        if summarise is not None:
            try:
                summary = summarise(cid)
                if hasattr(summary, "to_dict"):
                    entry.update(summary.to_dict())
                elif isinstance(summary, dict):
                    entry.update(summary)
                else:
                    entry["summary"] = str(summary)[:500]
            except Exception:
                logger.debug("community_summary failed for %s", cid, exc_info=True)
        out.append(entry)
    return out


def crp_ckf_graph_walk(
    ckf: Any,
    *,
    seed_ids: Sequence[str],
    max_hops: int = 2,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Multi-hop fact expansion via ``ckf.graph_walk``. Returns a list
    of fact dicts. Best-effort — returns ``[]`` on failure."""
    out: list[dict[str, Any]] = []
    if not seed_ids or not hasattr(ckf, "graph_walk"):
        return out
    try:
        results = ckf.graph_walk(list(seed_ids), max_hops=int(max_hops))
    except Exception:
        logger.debug("graph_walk failed", exc_info=True)
        return out
    for item in list(results)[:limit]:
        if hasattr(item, "to_dict"):
            out.append(item.to_dict())
        elif isinstance(item, dict):
            out.append(item)
        else:
            out.append({"raw": str(item)[:500]})
    return out


__all__ = [
    "RedactionResult",
    "redact_pii",
    "detect_hit_contradictions",
    "mmr_rerank",
    "pack_hits_to_envelope",
    "compact_messages_for_budget",
    "crp_autoingest_message",
    "ContinuationOutcome",
    "continue_truncated_answer",
    "ExtractedClarification",
    "extract_facts_from_text",
    "detect_ckf_contradictions",
    "pattern_query_ckf",
    "CrpEventBus",
    "InjectionReport",
    "scan_for_injection",
    "CrpDispatchOutcome",
    "dispatch_via_crp",
    "CrpMessageLedger",
    "fold_messages_with_ledger",
    "crp_preview_envelope",
    "crp_estimate_session",
    "crp_apply_feedback",
    "crp_export_state_bytes",
    "crp_ckf_communities",
    "crp_ckf_graph_walk",
]
