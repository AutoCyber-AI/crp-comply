"""Smoke tests for the 7.15 client-side intelligence layer."""

from __future__ import annotations

from crp_comply_search.intelligence import (
    ChunkCiter,
    CrossEncoderReranker,
    QueryExpander,
)


# --- QueryExpander ---------------------------------------------------------


def test_query_expander_templated_default() -> None:
    qe = QueryExpander()
    out = qe.expand("GDPR Article 6", intent="regulation_text")
    assert out.strategy == "templated"
    assert out.intent == "regulation_text"
    assert any("eur-lex" in s.lower() for s in out.sub_queries)
    assert len(out.sub_queries) >= 2
    # No duplicates.
    assert len(out.sub_queries) == len(set(out.sub_queries))


def test_query_expander_unknown_intent_falls_to_general() -> None:
    qe = QueryExpander()
    out = qe.expand("hello world", intent="not_a_real_intent")
    # Falls through to "general" template.
    assert out.sub_queries
    assert all("hello world" in s for s in out.sub_queries)


def test_query_expander_empty_goal() -> None:
    qe = QueryExpander()
    out = qe.expand("", intent="general")
    assert out.sub_queries == []


def test_query_expander_llm_strategy_with_callable() -> None:
    def llm(goal: str, intent: str, n: int) -> list[str]:
        return [f"{goal} A", f"{goal} B"]

    qe = QueryExpander(llm_callable=llm)
    out = qe.expand("foo", intent="news", strategy="llm")
    assert out.strategy == "llm"
    assert out.sub_queries == ["foo A", "foo B"]


def test_query_expander_llm_failure_falls_back_to_templated() -> None:
    def boom(*_a, **_kw):
        raise RuntimeError("boom")

    qe = QueryExpander(llm_callable=boom)
    out = qe.expand("foo", intent="news", strategy="llm")
    assert out.strategy == "templated"
    assert out.sub_queries


# --- CrossEncoderReranker --------------------------------------------------


class _Hit:
    def __init__(self, title: str, snippet: str, weight: float) -> None:
        self.title = title
        self.snippet = snippet
        self.weight = weight


def test_reranker_heuristic_orders_by_overlap_and_weight() -> None:
    rr = CrossEncoderReranker(model_name="(force-fail)")
    rr._failed = True  # skip ML import attempt entirely
    hits = [
        _Hit("Off topic", "nothing relevant here", weight=0.1),
        _Hit("GDPR Article 6 lawful basis", "lawful basis", weight=1.0),
        _Hit("Random", "", weight=0.5),
    ]
    out = rr.rerank("GDPR Article 6 lawful basis", hits, top_k=2)
    assert out.candidates_in == 3
    assert out.candidates_out == 2
    assert out.model == "heuristic"
    # The high-overlap hit should be first.
    assert out.hits[0].title.startswith("GDPR")


def test_reranker_empty_input() -> None:
    rr = CrossEncoderReranker()
    out = rr.rerank("query", [], top_k=5)
    assert out.candidates_in == 0
    assert out.hits == []


# --- ChunkCiter -----------------------------------------------------------


class _FullHit:
    def __init__(self, full_text: str, url: str = "https://x.test/a") -> None:
        self.full_text = full_text
        self.url = url
        self.title = "doc"
        self.domain = "x.test"
        self.trust_tier = 1
        self.snippet = ""
        self.citation_id = "web:abc123"


def test_chunk_citer_splits_and_assigns_stable_ids() -> None:
    text = "Para one about GDPR.\n\nPara two about data minimisation.\n\nPara three." * 3
    cc = ChunkCiter(chunk_size=120, max_chunks_per_hit=3)
    cites = cc.cite("GDPR data minimisation", [_FullHit(text)])
    assert cites
    assert all(c.citation_id.startswith("web:abc123:c") for c in cites)
    assert cites[0].url == "https://x.test/a"
    assert cites[0].source_id == "web:abc123"
    # Ranked order: the chunk most overlapping with the query should be first.
    assert "data minimisation" in cites[0].excerpt.lower()


def test_chunk_citer_falls_back_to_snippet_when_no_full_text() -> None:
    class _Bare:
        full_text = ""
        snippet = "GDPR snippet"
        url = "u"
        title = "t"
        domain = "d"
        trust_tier = 2
        citation_id = "web:xyz"

    cc = ChunkCiter()
    cites = cc.cite("gdpr", [_Bare()])
    assert len(cites) == 1
    assert cites[0].excerpt == "GDPR snippet"
