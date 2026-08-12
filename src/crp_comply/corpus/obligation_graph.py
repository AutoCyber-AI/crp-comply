# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Obligation graph builder for the Phase 4 corpus.

Converts regulation chunks into structured :class:`Obligation` nodes and derives
edges (supersedes, refines, contradicts, related_to) from chunk metadata and
article numbering. This is intentionally deterministic and rule-based so it
runs without an LLM during ingestion; downstream agents can enrich it later.
"""

from __future__ import annotations

import re
from typing import Iterable

from ..agent.corpus import CorpusChunk, CorpusDocument
from .models import Obligation, ObligationEdge, content_hash
from .repository import CorpusRepository

_OBLIGATION_RE = re.compile(
    r"\b(?P<actor>[A-Z][a-zA-Z\s]{0,40}?)\s+(?P<verb>shall|must|should|must not|may not|is required to|is prohibited from)\b(?P<rest>[^.;]*[.;]?)",
    re.IGNORECASE,
)

_TOPICS = {
    "risk": ["risk", "risk management", "risk assessment"],
    "data": ["data", "personal data", "training data", "dataset"],
    "transparency": ["transparency", "disclosure", "inform", "user"],
    "human oversight": ["human oversight", "human in the loop", "operator"],
    "conformity": ["conformity", "conformity assessment", "notified body", "ce"],
    "documentation": ["technical documentation", "documentation", "record"],
    "monitoring": ["monitor", "post-market", "surveillance"],
    "bias": ["bias", "fairness", "discrimination"],
    "accuracy": ["accuracy", "robustness", "performance"],
    "security": ["security", "cybersecurity", "confidentiality"],
}

_EDGE_WEIGHTS = {
    "supersedes": 1.0,
    "refines": 0.9,
    "contradicts": 1.0,
    "derived_from": 0.7,
    "related_to": 0.4,
}


def extract_obligations(doc: CorpusDocument) -> list[Obligation]:
    """Extract obligations from every chunk in a document."""
    obligations: list[Obligation] = []
    for chunk in doc.chunks:
        obligations.extend(_extract_from_chunk(doc.source_id, chunk))
    return obligations


def _extract_from_chunk(source_id: str, chunk: CorpusChunk) -> list[Obligation]:
    text = chunk.text or ""
    matches = list(_OBLIGATION_RE.finditer(text))
    if not matches:
        # If no explicit obligation language, store a single related-to fact
        # when the chunk is short enough to be a definitional/scope clause.
        if len(text.split()) <= 80:
            return [
                Obligation(
                    id=_obligation_id(source_id, chunk.id, 0),
                    source_id=source_id,
                    chunk_id=chunk.id,
                    text=text.strip()[:500],
                    article_id=chunk.article_id,
                    section_path=list(chunk.section_path),
                    obligation_type="definition",
                    topics=_infer_topics(text),
                    effective_date=chunk.effective_date,
                    superseded_by=chunk.superseded_by,
                )
            ]
        return []

    out: list[Obligation] = []
    for i, m in enumerate(matches):
        verb = m.group("verb").lower()
        actor = (m.group("actor") or "").strip()
        rest = (m.group("rest") or "").strip()
        sentence = (f"{actor} {verb} {rest}").strip()
        obligation_type = _verb_to_type(verb)
        out.append(
            Obligation(
                id=_obligation_id(source_id, chunk.id, i),
                source_id=source_id,
                chunk_id=chunk.id,
                text=sentence[:500],
                article_id=chunk.article_id,
                section_path=list(chunk.section_path),
                obligation_type=obligation_type,
                actors=[actor] if actor else [],
                topics=_infer_topics(sentence),
                effective_date=chunk.effective_date,
                superseded_by=chunk.superseded_by,
            )
        )
    return out


def _verb_to_type(verb: str) -> str:
    verb = verb.lower()
    if "must not" in verb or "may not" in verb or "prohibited" in verb:
        return "must_not"
    if "shall" in verb or "must" in verb or "required" in verb:
        return "shall"
    if "should" in verb:
        return "should"
    return "may"


def _infer_topics(text: str) -> list[str]:
    lowered = text.lower()
    return [topic for topic, keywords in _TOPICS.items() if any(k in lowered for k in keywords)]


def _obligation_id(source_id: str, chunk_id: str, idx: int) -> str:
    base = f"{source_id}:{chunk_id}:{idx}"
    return f"obl:{content_hash([base])[:16]}"


def derive_edges(obligations: Iterable[Obligation]) -> list[ObligationEdge]:
    """Derive edges between obligations in the same regulation."""
    obs = list(obligations)
    edges: list[ObligationEdge] = []
    by_chunk: dict[str, list[Obligation]] = {}
    by_article: dict[str, list[Obligation]] = {}
    for o in obs:
        by_chunk.setdefault(o.chunk_id, []).append(o)
        if o.article_id:
            by_article.setdefault(o.article_id, []).append(o)

    # Related-to edges between obligations in the same chunk.
    for chunk_obs in by_chunk.values():
        for i in range(len(chunk_obs)):
            for j in range(i + 1, len(chunk_obs)):
                edges.append(
                    _make_edge(chunk_obs[i].id, chunk_obs[j].id, "related_to", "same_chunk")
                )

    # Refines / related_to edges between obligations in the same article.
    for article_obs in by_article.values():
        for i in range(len(article_obs)):
            for j in range(i + 1, len(article_obs)):
                # If one is a definition and the other is a shall, label refines.
                types = {article_obs[i].obligation_type, article_obs[j].obligation_type}
                edge_type = "refines" if types == {"definition", "shall"} else "related_to"
                edges.append(
                    _make_edge(article_obs[i].id, article_obs[j].id, edge_type, "same_article")
                )

    # Supersedes edges when one obligation explicitly supersedes another.
    for o in obs:
        if o.superseded_by:
            edges.append(_make_edge(o.superseded_by, o.id, "supersedes", "superseded_by_metadata"))

    return edges


def _make_edge(source_id: str, target_id: str, edge_type: str, provenance: str) -> ObligationEdge:
    base = f"{source_id}->{target_id}:{edge_type}"
    edge_id = f"edge:{content_hash([base])[:16]}"
    return ObligationEdge(
        id=edge_id,
        source_id=source_id,
        target_id=target_id,
        edge_type=edge_type,
        weight=_EDGE_WEIGHTS.get(edge_type, 0.5),
        provenance=provenance,
    )


def build_graph_for_document(doc: CorpusDocument, repo: CorpusRepository) -> tuple[int, int]:
    """Extract obligations + edges for a document and persist them.

    Returns (obligation_count, edge_count).
    """
    obligations = extract_obligations(doc)
    # Clear prior graph for this source so re-ingestion is idempotent.
    repo.delete_edges_for_source(doc.source_id)
    repo.delete_obligations_for_source(doc.source_id)

    for obligation in obligations:
        repo.upsert_obligation(obligation)

    edges = derive_edges(obligations)
    for edge in edges:
        repo.upsert_edge(edge)

    return len(obligations), len(edges)
