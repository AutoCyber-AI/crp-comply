# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Unit tests for the agentic web-research loop."""

from __future__ import annotations

from typing import Any

import pytest

from crp_comply_search.backends import SearchHit, SearchResult
from crp_comply_search.profiles import ProfileRegistry
from crp_comply_search.research_agent import ResearchAgent


class _FakeBackend:
    name = "local"

    def __init__(self, hits: list[SearchHit] | None = None) -> None:
        self._hits = hits or []
        self.calls: list[list[str]] = []

    def research(
        self,
        queries: Any,
        *,
        profile: Any,
        freshness: str = "any",
        max_results: int = 10,
        fetch_full_text: bool = True,
        intent: str | None = None,
    ) -> SearchResult:
        self.calls.append(list(queries))
        return SearchResult(
            query="; ".join(queries),
            backend=self.name,
            profile=profile.name,
            results=list(self._hits),
        )


@pytest.fixture
def profile() -> Any:
    reg = ProfileRegistry.load_dir(None)
    return reg.get("crp_comply_official")


def test_research_agent_runs_single_iteration_when_coverage_good(profile: Any) -> None:
    hits = [
        SearchHit(
            title="A",
            url="https://a.example.com/x",
            snippet="snippet A",
            domain="a.example.com",
            trust_tier=1,
            weight=1.0,
            blocked=False,
            full_text="A says something important about the topic.",
            content_hash="hash-a",
        ),
        SearchHit(
            title="B",
            url="https://b.example.com/y",
            snippet="snippet B",
            domain="b.example.com",
            trust_tier=2,
            weight=0.9,
            blocked=False,
            full_text="B offers a complementary view.",
            content_hash="hash-b",
        ),
        SearchHit(
            title="C",
            url="https://c.example.com/z",
            snippet="snippet C",
            domain="c.example.com",
            trust_tier=2,
            weight=0.8,
            blocked=False,
            full_text="C adds a third perspective.",
            content_hash="hash-c",
        ),
    ]
    backend = _FakeBackend(hits=hits)
    agent = ResearchAgent(backend, profile)
    state = agent.run("What is the EU AI Act?", max_iterations=2)

    assert state.iterations == 1
    assert state.coverage_score >= 0.85
    assert len(state.citations) > 0
    assert any(e["event"] == "loop.web.expand" for e in state.events)


def test_research_agent_deduplicates_hits_across_iterations(profile: Any) -> None:
    hit = SearchHit(
        title="A",
        url="https://a.example.com/x",
        snippet="snippet A",
        domain="a.example.com",
        trust_tier=1,
        weight=1.0,
        blocked=False,
        full_text="A says something.",
        content_hash="hash-a",
    )
    backend = _FakeBackend(hits=[hit])
    agent = ResearchAgent(backend, profile)
    state = agent.run("EU AI Act enforcement 2025", max_iterations=2)

    urls = {h.url for h in state.hits}
    assert len(urls) == 1
    assert state.iterations <= 2
