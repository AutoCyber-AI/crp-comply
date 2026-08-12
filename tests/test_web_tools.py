"""Unit tests for the Phase 7.15 web-search tool wrappers.

All tests run offline with a fake ``web_client``; no sidecar is required.
"""

from __future__ import annotations

from typing import Any

from crp_comply.agent.tools import (
    build_compare_documents_tool,
    build_vendor_profile_tool,
    build_web_research_tool,
    build_web_search_tool,
    default_registry,
)


class _FakeWebClient:
    """Captures tool calls and returns canned sidecar-shaped responses."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.search_result: dict[str, Any] = {
            "results": [
                {
                    "url": "https://example.com/a",
                    "title": "Example A",
                    "snippet": "snippet a",
                    "domain": "example.com",
                    "trust_tier": 2,
                    "weight": 1.0,
                    "blocked": False,
                }
            ],
            "backend": "searxng",
            "blocked": 0,
            "latency_ms": 12.0,
        }
        self.research_result: dict[str, Any] = {
            "goal": "latest GDPR fines",
            "intent": "enforcement",
            "expansion": {
                "strategy": "templated",
                "sub_queries": ["GDPR fine 2025", "ICO enforcement action"],
            },
            "rerank": {
                "model": "cross-encoder",
                "candidates_in": 10,
                "candidates_out": 6,
                "latency_ms": 34.0,
            },
            "results": [],
            "citations": [
                {
                    "citation_id": "cite-1",
                    "source_id": "https://ico.org.uk/news",
                    "url": "https://ico.org.uk/news",
                    "chunk_index": 0,
                    "score": 0.91,
                    "excerpt": "ICO fined Example Ltd",
                }
            ],
        }
        self.vendor_result: dict[str, Any] = {
            "vendor": "Acme Corp",
            "buckets": {"privacy_policy": [{"url": "https://acme.com/privacy"}]},
            "backend": "searxng",
        }
        self.compare_result: dict[str, Any] = {
            "documents": ["https://a.com/tos", "https://b.com/tos"],
            "matrix": {
                "data portability": {
                    "https://a.com/tos": {
                        "score": 0.8,
                        "excerpt": "you can export data",
                        "chunk_index": 1,
                        "citation_id": "c1",
                    }
                }
            },
        }

    def search(self, query: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "search", "query": query, **kwargs})
        return self.search_result

    def research_intelligent(self, goal: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "research_intelligent", "goal": goal, **kwargs})
        return self.research_result

    def vendor_profile(self, vendor: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "vendor_profile", "vendor": vendor, **kwargs})
        return self.vendor_result

    def compare_documents(self, documents: list[str], **kwargs: Any) -> dict[str, Any]:
        self.calls.append({"method": "compare_documents", "documents": documents, **kwargs})
        return self.compare_result


def test_web_search_tool_forwards_query_and_returns_hits():
    client = _FakeWebClient()
    tool = build_web_search_tool(client)
    res = tool.invoke(
        {
            "query": "GDPR article 32",
            "intent": "regulation_text",
            "freshness": "month",
            "max_results": 5,
        }
    )
    assert res.ok
    assert res.payload["query"] == "GDPR article 32"
    assert res.payload["intent"] == "regulation_text"
    assert res.payload["backend"] == "searxng"
    assert len(res.payload["results"]) == 1
    assert client.calls[0]["method"] == "search"
    assert client.calls[0]["max_results"] == 5


def test_web_search_empty_query_is_noop():
    client = _FakeWebClient()
    tool = build_web_search_tool(client)
    res = tool.invoke({"query": "   "})
    assert res.ok
    assert res.payload["hits"] == []
    assert client.calls == []


def test_web_research_tool_forwards_intelligent_research():
    client = _FakeWebClient()
    tool = build_web_research_tool(client)
    res = tool.invoke(
        {
            "goal": "latest GDPR fines",
            "intent": "enforcement",
            "freshness": "week",
            "max_results_per_query": 4,
            "expansion_strategy": "llm",
            "rerank_top_k": 3,
        }
    )
    assert res.ok
    assert res.payload["goal"] == "latest GDPR fines"
    assert res.payload["intent"] == "enforcement"
    assert res.payload["expansion"]["sub_queries"] == [
        "GDPR fine 2025",
        "ICO enforcement action",
    ]
    call = client.calls[0]
    assert call["method"] == "research_intelligent"
    assert call["freshness"] == "week"
    assert call["max_results_per_query"] == 4
    assert call["expansion_strategy"] == "llm"
    assert call["rerank_top_k"] == 3


def test_web_research_empty_goal_is_noop():
    client = _FakeWebClient()
    tool = build_web_research_tool(client)
    res = tool.invoke({"goal": ""})
    assert res.ok
    assert res.payload["results"] == []
    assert client.calls == []


def test_vendor_profile_tool_buckets_results():
    client = _FakeWebClient()
    tool = build_vendor_profile_tool(client)
    res = tool.invoke({"vendor": "Acme Corp", "max_results": 6})
    assert res.ok
    assert res.payload["vendor"] == "Acme Corp"
    assert "privacy_policy" in res.payload["buckets"]
    call = client.calls[0]
    assert call["method"] == "vendor_profile"
    assert call["max_results"] == 6


def test_vendor_profile_empty_vendor_is_noop():
    client = _FakeWebClient()
    tool = build_vendor_profile_tool(client)
    res = tool.invoke({"vendor": "   "})
    assert res.ok
    assert res.payload["buckets"] == {}
    assert client.calls == []


def test_compare_documents_tool_builds_matrix():
    client = _FakeWebClient()
    tool = build_compare_documents_tool(client)
    res = tool.invoke(
        {
            "documents": ["https://a.com/tos", "https://b.com/tos"],
            "claims": ["data portability"],
        }
    )
    assert res.ok
    assert res.payload["documents"] == ["https://a.com/tos", "https://b.com/tos"]
    matrix = res.payload["matrix"]
    assert "data portability" in matrix
    assert matrix["data portability"]["https://a.com/tos"]["score"] == 0.8
    call = client.calls[0]
    assert call["method"] == "compare_documents"
    assert call["documents"] == ["https://a.com/tos", "https://b.com/tos"]
    assert call["claims"] == ["data portability"]


def test_compare_documents_rejects_short_list():
    client = _FakeWebClient()
    tool = build_compare_documents_tool(client)
    res = tool.invoke({"documents": ["https://a.com/tos"]})
    assert res.ok
    assert res.payload["matrix"] == {}
    assert "note" in res.payload
    assert client.calls == []


def test_default_registry_includes_web_tools_with_client():
    client = _FakeWebClient()
    reg = default_registry(rag=None, fabric=None, web_client=client)
    names = reg.names()
    assert "web_search" in names
    assert "web_research" in names
    assert "vendor_profile" in names
    assert "compare_documents" in names


def test_default_registry_omits_web_tools_without_client():
    reg = default_registry(rag=None, fabric=None, web_client=None)
    names = reg.names()
    assert "web_search" not in names
    assert "web_research" not in names
    assert "vendor_profile" not in names
    assert "compare_documents" not in names
