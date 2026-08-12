# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Agentic web-research loop for the crp-comply search sidecar.

The ResearchAgent treats web search as a reasoning task rather than a one-shot
retrieval. It expands queries, gathers evidence, uses a lightweight reasoning
step to identify coverage gaps, and re-searches until a budget is reached. The
output is a compact evidence pack with citations that the main compliance loop
can consume through CRPv5.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from .backends import Freshness, SearchHit, WebSearchBackend
from .intelligence import ChunkCiter, CrossEncoderReranker, QueryExpander
from .profiles import TrustTierProfile
from .reasoning import ReasoningClient

logger = logging.getLogger(__name__)

Intent = Literal[
    "regulation_text",
    "case_law",
    "guidance",
    "enforcement",
    "news",
    "vendor",
    "general",
]

ReasoningFn = Callable[[str, list[dict[str, Any]]], dict[str, Any]]


@dataclass
class ResearchState:
    """Lightweight state object for the research loop."""

    goal: str
    intent: Intent
    sub_queries: list[str] = field(default_factory=list)
    hits: list[SearchHit] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    coverage_score: float = 0.0
    gaps: list[str] = field(default_factory=list)
    iterations: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "intent": self.intent,
            "sub_queries": list(self.sub_queries),
            "coverage_score": self.coverage_score,
            "gaps": list(self.gaps),
            "iterations": self.iterations,
            "hits": [h.__dict__ for h in self.hits],
            "citations": list(self.citations),
        }


class ResearchAgent:
    """Iterative search-reason-cite agent."""

    def __init__(
        self,
        backend: WebSearchBackend,
        profile: TrustTierProfile,
        *,
        expander: QueryExpander | None = None,
        reranker: CrossEncoderReranker | None = None,
        chunker: ChunkCiter | None = None,
        reasoning_fn: ReasoningFn | None = None,
        reasoning_client: ReasoningClient | None = None,
    ) -> None:
        self.backend = backend
        self.profile = profile
        self.expander = expander or QueryExpander()
        self.reranker = reranker or CrossEncoderReranker()
        self.chunker = chunker or ChunkCiter()
        self.reasoning_fn = reasoning_fn
        self.reasoning_client = reasoning_client

    def run(
        self,
        goal: str,
        *,
        intent: Intent = "general",
        freshness: Freshness = "any",
        max_results_per_query: int = 8,
        rerank_top_k: int = 6,
        max_iterations: int = 2,
        budget_seconds: float = 8.0,
        fetch_full_text: bool = True,
        chunk_cite: bool = True,
    ) -> ResearchState:
        """Run the agentic research loop and return the final state."""
        state = ResearchState(goal=goal, intent=intent)
        deadline = time.perf_counter() + budget_seconds

        # Initial expansion.
        expansion = self.expander.expand(goal, intent=intent, strategy="templated")
        state.sub_queries = expansion.sub_queries or [goal]
        state.events.append(
            {
                "event": "loop.web.expand",
                "goal": goal,
                "intent": intent,
                "sub_queries": list(state.sub_queries),
                "strategy": expansion.strategy,
            }
        )

        for iteration in range(1, max_iterations + 1):
            if time.perf_counter() > deadline:
                state.gaps.append("time budget exhausted")
                break

            # Search current sub-queries in parallel-ish via backend.research.
            results = self.backend.research(
                state.sub_queries,
                profile=self.profile,
                freshness=freshness,
                max_results=max_results_per_query,
                fetch_full_text=fetch_full_text and iteration == 1,
                intent=intent,
            )
            # Deduplicate by content hash / URL.
            seen: set[str] = {h.content_hash or h.url for h in state.hits}
            for h in results.results:
                key = h.content_hash or h.url
                if key and key in seen:
                    continue
                seen.add(key)
                state.hits.append(h)

            state.events.append(
                {
                    "event": "loop.web.result",
                    "backend": results.backend,
                    "hits": [h.to_event_hit() for h in results.results],
                    "blocked": results.blocked,
                    "latency_ms": results.latency_ms,
                }
            )

            # Rerank.
            reranked = self.reranker.rerank(goal, list(state.hits), top_k=rerank_top_k)
            state.events.append(
                {
                    "event": "loop.web.rerank",
                    "model": reranked.model,
                    "candidates_in": reranked.candidates_in,
                    "candidates_out": reranked.candidates_out,
                    "latency_ms": reranked.latency_ms,
                }
            )

            # Chunk-and-cite over the reranked hits.
            if chunk_cite:
                citations = self.chunker.cite(goal, reranked.hits, scorer=self.reranker)
                state.citations = [c.to_dict() for c in citations]
                for c in citations:
                    state.events.append(
                        {
                            "event": "loop.web.cite",
                            "citation_id": c.citation_id,
                            "source_id": c.source_id,
                            "chunk_index": c.chunk_index,
                            "score": c.score,
                            "excerpt": c.excerpt[:240],
                        }
                    )

            state.iterations = iteration
            state.coverage_score = self._score_coverage(reranked.hits)

            # Stop early if coverage is good enough.
            if state.coverage_score >= 0.85:
                break

            # Reason about gaps and plan next sub-queries.
            gaps = self._identify_gaps(goal, reranked.hits, intent=intent)
            if not gaps or iteration == max_iterations:
                state.gaps = gaps or []
                break

            state.gaps = gaps
            # Add gap-driven queries; avoid duplicates.
            new_queries: list[str] = []
            for q in gaps:
                if q not in state.sub_queries:
                    new_queries.append(q)
            if not new_queries:
                break
            state.sub_queries.extend(new_queries)
            state.events.append(
                {
                    "event": "loop.web.expand",
                    "goal": goal,
                    "intent": intent,
                    "sub_queries": list(new_queries),
                    "strategy": "gap_driven",
                }
            )

        return state

    def _score_coverage(self, hits: list[SearchHit]) -> float:
        """Coverage heuristic: trust, diversity, freshness, and depth."""
        if not hits:
            return 0.0
        domains = {h.domain for h in hits if h.domain}
        avg_weight = sum(h.weight for h in hits) / len(hits)
        diversity = min(1.0, len(domains) / 3.0)
        freshness = sum(self._freshness_score(h.published_at) for h in hits) / len(
            hits
        )
        return min(1.0, 0.45 * avg_weight + 0.25 * diversity + 0.20 * freshness + 0.10 * min(1.0, len(hits) / 5.0))

    @staticmethod
    def _freshness_score(published_at: float | None) -> float:
        """Return a recency score from 0 (old/unknown) to 1 (today)."""
        if published_at is None:
            return 0.75
        age_days = max(0.0, (time.time() - published_at) / 86400)
        if age_days <= 7:
            return 1.0
        if age_days <= 30:
            return 0.85
        if age_days <= 90:
            return 0.65
        if age_days <= 365:
            return 0.4
        return 0.2

    def _identify_gaps(
        self, goal: str, hits: list[SearchHit], *, intent: Intent
    ) -> list[str]:
        """Return follow-up sub-queries to fill coverage gaps.

        If a reasoning client or function is configured, it is used first.
        Otherwise a deterministic heuristic is used.
        """
        hits_dict = [h.__dict__ for h in hits]
        if self.reasoning_client is not None:
            try:
                result = self.reasoning_client.evaluate_coverage(
                    goal, hits_dict, intent=intent
                )
                gaps = result.get("gaps") or []
                follow_ups = result.get("follow_up_queries") or []
                # Prefer concrete follow-up queries when the model supplies them.
                candidates = follow_ups if follow_ups else gaps
                return [str(g) for g in candidates if g]
            except Exception:
                logger.debug("reasoning_client failed; falling back", exc_info=True)

        if self.reasoning_fn is not None:
            try:
                prompt = self._reasoning_prompt(goal, hits, intent)
                result = self.reasoning_fn(prompt, hits_dict)
                gaps = result.get("gaps") or []
                if isinstance(gaps, list):
                    return [str(g) for g in gaps if g]
            except Exception:
                logger.debug("reasoning_fn failed; falling back to heuristic", exc_info=True)

        # Heuristic fallback.
        gaps: list[str] = []
        if len(hits) < 3:
            gaps.append(f"broader perspective on {goal}")
        domains = {h.domain for h in hits if h.domain}
        if len(domains) < 2:
            gaps.append(f"alternative source for {goal}")
        if intent in {"enforcement", "news", "guidance"}:
            gaps.append(f"recent {intent} update {goal}")
        return gaps

    @staticmethod
    def _reasoning_prompt(goal: str, hits: list[SearchHit], intent: Intent) -> str:
        domains = ", ".join(sorted({h.domain for h in hits if h.domain}))
        return (
            "You are a research reasoning model. Given the user's goal and the "
            "retrieved web evidence, identify 0-3 specific gaps in coverage. "
            "Return JSON with a single key 'gaps' containing a list of follow-up "
            "search queries.\n\n"
            f"Goal: {goal}\n"
            f"Intent: {intent}\n"
            f"Sources retrieved from: {domains}\n"
            f"Number of hits: {len(hits)}\n"
        )
