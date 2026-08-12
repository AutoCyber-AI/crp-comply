"""Unit tests for :mod:`crp_comply.agent.tools`.

Everything here is offline — no LLM, no real sqlite index, no real CKF. The
tests pin down the tool contract so the orchestrator can rely on it.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from crp_comply.agent.tools import (
    ClarificationNeeded,
    Tool,
    ToolRegistry,
    ToolResult,
    build_classify_ai_act_risk_tool,
    build_query_regulation_tool,
    build_recall_facts_tool,
    build_request_clarification_tool,
    default_registry,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeRag:
    def __init__(self, hits):
        self._hits = hits
        self.last_call: dict | None = None

    def query(self, query_text, *, top_k=5, source_filter=None):
        self.last_call = {"q": query_text, "k": top_k, "src": source_filter}
        return [dict(h) for h in self._hits]


class _FakeFabric:
    def __init__(self, pattern_facts, walk_facts=None):
        self._pattern = pattern_facts
        self._walk = walk_facts or []
        self.pattern_call: dict | None = None
        self.walk_call: dict | None = None

    def query(self, **kwargs):
        self.pattern_call = kwargs
        return SimpleNamespace(facts=list(self._pattern))

    def graph_walk(self, **kwargs):
        self.walk_call = kwargs
        return SimpleNamespace(facts=list(self._walk))


def _mk_fact(fid, text, category="x"):
    return SimpleNamespace(
        id=fid,
        text=text,
        category=category,
        confidence=0.9,
        source_window_id="win",
        created_at=1.0,
        metadata={"k": "v"},
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_rejects_duplicates():
    t = build_request_clarification_tool()
    reg = ToolRegistry([t])
    with pytest.raises(ValueError):
        reg.register(t)


def test_registry_schemas_and_invoke_unknown():
    reg = ToolRegistry([build_request_clarification_tool()])
    schemas = reg.schemas()
    assert schemas and schemas[0]["type"] == "function"
    assert schemas[0]["function"]["name"] == "request_clarification"

    res = reg.invoke("no_such_tool", {})
    assert res.ok is False
    assert "unknown tool" in res.error


def test_tool_schema_has_required_openai_fields():
    reg = default_registry(rag=_FakeRag([]), fabric=_FakeFabric([]))
    for spec in reg.schemas():
        assert spec["type"] == "function"
        fn = spec["function"]
        assert fn["name"] and fn["description"]
        assert fn["parameters"]["type"] == "object"
        assert "properties" in fn["parameters"]


def test_tool_result_as_tool_message_shape():
    res = ToolResult(tool_name="x", ok=True, payload={"a": 1})
    msg = res.as_tool_message("call_1")
    assert msg["role"] == "tool"
    assert msg["tool_call_id"] == "call_1"
    assert json.loads(msg["content"]) == {"a": 1}

    err = ToolResult(tool_name="x", ok=False, error="boom")
    msg = err.as_tool_message("call_2")
    assert json.loads(msg["content"]) == {"error": "boom"}


def test_handler_exception_surfaces_as_failed_toolresult():
    def bad(_args):
        raise RuntimeError("kaboom")

    tool = Tool(
        name="bad", description="d", parameters={"type": "object", "properties": {}}, handler=bad
    )
    res = tool.invoke({})
    assert res.ok is False
    assert "kaboom" in res.error


# ---------------------------------------------------------------------------
# query_regulation
# ---------------------------------------------------------------------------


def test_query_regulation_happy_path():
    rag = _FakeRag(
        [
            {
                "chunk_id": "eu_ai_act:art_6",
                "source_id": "eu_ai_act",
                "title": "Classification rules",
                "article_id": "Art. 6",
                "section_path": ["Title III", "Chapter 1"],
                "score": 0.87123,
                "text": "x" * 3000,
                "tags": {"copyright": "open"},
            }
        ]
    )
    tool = build_query_regulation_tool(rag)
    res = tool.invoke({"query": "high-risk classification", "top_k": 20})
    assert res.ok
    assert rag.last_call["q"] == "high-risk classification"
    assert rag.last_call["k"] == 15  # capped
    hit = res.payload["hits"][0]
    assert hit["chunk_id"] == "eu_ai_act:art_6"
    assert hit["score"] == 0.8712
    assert hit["text"].endswith("…[truncated]")
    assert hit["copyright_restricted"] is False


def test_query_regulation_respects_restricted_tag():
    rag = _FakeRag(
        [
            {
                "chunk_id": "iso_42001:5.2",
                "source_id": "iso_42001",
                "title": "Policy",
                "article_id": "5.2",
                "section_path": [],
                "score": 0.5,
                "text": "surrogate",
                "tags": {"copyright": "restricted"},
            }
        ]
    )
    tool = build_query_regulation_tool(rag)
    res = tool.invoke({"query": "ai policy"})
    assert res.payload["hits"][0]["copyright_restricted"] is True


def test_query_regulation_empty_query_returns_no_hits():
    rag = _FakeRag(
        [
            {
                "chunk_id": "x",
                "source_id": "y",
                "title": "",
                "article_id": "",
                "section_path": [],
                "score": 0.0,
                "text": "",
                "tags": {},
            }
        ]
    )
    tool = build_query_regulation_tool(rag)
    res = tool.invoke({"query": "   "})
    assert res.ok
    assert res.payload["hits"] == []
    assert rag.last_call is None  # never hit the backend


def test_query_regulation_source_filter_string_normalised():
    rag = _FakeRag([])
    tool = build_query_regulation_tool(rag)
    tool.invoke({"query": "gdpr", "source_filter": "gdpr"})
    assert rag.last_call["src"] == ["gdpr"]


def test_query_regulation_applies_mmr_and_surfaces_contradictions(monkeypatch):
    """Phase 7.16 — CRP MMR rerank + contradiction detection wired live.

    The handler is expected to:
    1. Call ``mmr_rerank`` to drop near-duplicate chunks before
       returning hits.
    2. Call ``detect_hit_contradictions`` and surface its output under
       a ``contradictions`` key alongside a guidance ``contradiction_note``.
    """
    rag = _FakeRag(
        [
            {
                "chunk_id": f"gdpr:art_{i}",
                "source_id": "gdpr",
                "title": "Art",
                "article_id": f"Art. {i}",
                "section_path": [],
                "score": 0.9 - 0.01 * i,
                "text": f"text {i}",
                "tags": {"copyright": "open"},
            }
            for i in range(3)
        ]
    )

    rerank_calls: list[dict] = []
    detect_calls: list[int] = []

    def _fake_mmr(hits, *, top_k=None, lambda_mult=0.7):
        rerank_calls.append({"n": len(hits), "lambda": lambda_mult})
        # Return reversed order so we can prove the rerank was applied.
        return list(reversed(hits))

    def _fake_detect(hits):
        detect_calls.append(len(hits))
        return [
            {
                "fact_a_id": "gdpr:art_0",
                "fact_b_id": "gdpr:art_2",
                "fact_a_text": "text 0",
                "fact_b_text": "text 2",
                "similarity": 0.8,
                "content_diff": "differ",
                "confidence": 0.7,
            }
        ]

    monkeypatch.setattr("crp_comply.agent.crp_integration.mmr_rerank", _fake_mmr)
    monkeypatch.setattr(
        "crp_comply.agent.crp_integration.detect_hit_contradictions",
        _fake_detect,
    )

    tool = build_query_regulation_tool(rag)
    res = tool.invoke({"query": "gdpr lawful basis"})

    assert res.ok
    assert rerank_calls and rerank_calls[0]["n"] == 3
    assert detect_calls == [3]
    # Reversed order from _fake_mmr proves rerank output flowed through.
    assert [h["chunk_id"] for h in res.payload["hits"]] == [
        "gdpr:art_2",
        "gdpr:art_1",
        "gdpr:art_0",
    ]
    assert "contradictions" in res.payload
    assert res.payload["contradictions"][0]["fact_a_id"] == "gdpr:art_0"
    assert "contradiction_note" in res.payload


def test_query_regulation_safe_when_crp_advanced_fails(monkeypatch):
    """If MMR or contradiction detection raises, the tool still returns hits."""

    def _boom(*a, **kw):
        raise RuntimeError("crp boom")

    monkeypatch.setattr("crp_comply.agent.crp_integration.mmr_rerank", _boom)

    rag = _FakeRag(
        [
            {
                "chunk_id": "x:1",
                "source_id": "x",
                "title": "",
                "article_id": "",
                "section_path": [],
                "score": 0.5,
                "text": "raw",
                "tags": {"copyright": "open"},
            },
            {
                "chunk_id": "x:2",
                "source_id": "x",
                "title": "",
                "article_id": "",
                "section_path": [],
                "score": 0.4,
                "text": "raw2",
                "tags": {"copyright": "open"},
            },
        ]
    )
    tool = build_query_regulation_tool(rag)
    res = tool.invoke({"query": "anything"})
    assert res.ok
    assert len(res.payload["hits"]) == 2
    assert "contradictions" not in res.payload  # silent skip


# ---------------------------------------------------------------------------
# classify_ai_act_risk
# ---------------------------------------------------------------------------


def test_classify_ai_act_risk_invokes_crp_classifier():
    tool = build_classify_ai_act_risk_tool()
    res = tool.invoke(
        {
            "intended_purpose": "biometric categorisation of employees",
            "processes_personal_data": True,
            "makes_automated_decisions": True,
            "affects_fundamental_rights": True,
            "profiles_individuals": True,
        }
    )
    assert res.ok
    # We don't pin the exact risk level — CRP owns the rubric. But it must be
    # one of the documented levels and ship mitigations.
    assert res.payload["risk_level"] in {
        "minimal",
        "limited",
        "high",
        "unacceptable",
        "prohibited",
    }
    assert isinstance(res.payload["mitigations"], list)
    assert res.payload["intended_purpose"].startswith("biometric")


# ---------------------------------------------------------------------------
# recall_facts
# ---------------------------------------------------------------------------


def test_recall_facts_pattern_only():
    fabric = _FakeFabric([_mk_fact("f1", "text one"), _mk_fact("f2", "text two")])
    tool = build_recall_facts_tool(fabric)
    res = tool.invoke({"entity_type": "risk_assessment", "max_results": 5})
    assert res.ok
    assert len(res.payload["pattern_matches"]) == 2
    assert res.payload["pattern_matches"][0]["id"] == "f1"
    assert res.payload["graph_walk"] == {}  # hops=0 by default
    assert fabric.pattern_call["entity_type"] == "risk_assessment"
    assert fabric.pattern_call["max_results"] == 5


def test_recall_facts_with_graph_walk():
    fabric = _FakeFabric(
        pattern_facts=[_mk_fact("seed", "seed fact")],
        walk_facts=[_mk_fact("nbr1", "neighbour")],
    )
    tool = build_recall_facts_tool(fabric)
    res = tool.invoke({"graph_hops": 2})
    assert res.ok
    assert fabric.walk_call["max_hops"] == 2
    assert res.payload["graph_walk"]["facts"][0]["id"] == "nbr1"


# ---------------------------------------------------------------------------
# request_clarification
# ---------------------------------------------------------------------------


def test_request_clarification_raises_and_propagates_via_registry():
    tool = build_request_clarification_tool()
    reg = ToolRegistry([tool])
    with pytest.raises(ClarificationNeeded) as excinfo:
        reg.invoke(
            "request_clarification",
            {"question": "What data do you store?", "context": "GDPR art 30"},
        )
    assert excinfo.value.question == "What data do you store?"
    assert excinfo.value.context == "GDPR art 30"


def test_request_clarification_empty_question_returns_error():
    tool = build_request_clarification_tool()
    res = tool.invoke({"question": "   "})
    # Empty question → handler returns error dict, does NOT raise
    assert res.ok is True
    assert "error" in res.payload


# ---------------------------------------------------------------------------
# default_registry composition
# ---------------------------------------------------------------------------


def test_default_registry_without_backends():
    reg = default_registry()
    # No rag, no fabric → only the deterministic tools.
    names = set(reg.names())
    assert names == {
        "classify_ai_act_risk",
        "check_high_risk_criteria",
        "check_dpia_required",
        "check_dpo_required",
        "estimate_fine_exposure",
        "run_pii_scan",
        "run_injection_check",
        "request_clarification",
        "plan_recipe",
        "crp_get_continuation_state",
        "explain_nocode_capability",
        "list_nocode_presets",
        "get_nocode_preset",
    }


def test_default_registry_full_set():
    reg = default_registry(rag=_FakeRag([]), fabric=_FakeFabric([]))
    names = set(reg.names())
    assert names == {
        "classify_ai_act_risk",
        "check_high_risk_criteria",
        "check_dpia_required",
        "check_dpo_required",
        "estimate_fine_exposure",
        "run_pii_scan",
        "run_injection_check",
        "request_clarification",
        "query_regulation",
        "query_regulation_packed",
        "lookup_annex",
        "lookup_gdpr",
        "search_iso42001",
        "recall_facts",
        "crp_get_related_facts",
        "crp_retrieve_context",
        "crp_check_facts",
        "crp_get_continuation_state",
        "explain_nocode_capability",
        "list_nocode_presets",
        "get_nocode_preset",
        "plan_recipe",
        "consult_regulation_expert",
    }
