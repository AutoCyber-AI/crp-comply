"""Tests for Phase 7.15 web-loop event emission.

Covers ``_translate_agent_event`` fan-out of ``WEB_EXPAND``, ``WEB_RERANK``,
and ``WEB_CITE`` events and their payload schemas.
"""

from __future__ import annotations

from typing import Any

from crp_comply.agent.loop_runtime import _translate_agent_event
from crp_comply.api.events import LoopEvent, validate_event


def _event_names(out: dict[str, Any] | list[dict[str, Any]] | None) -> list[str]:
    if out is None:
        return []
    if isinstance(out, dict):
        return [out["event"]]
    return [e["event"] for e in out]


def test_web_tool_result_emits_expand_rerank_cite_and_result():
    ev = {
        "event": "tool_result",
        "tool": "web_research",
        "result": {
            "goal": "latest GDPR fines",
            "intent": "enforcement",
            "expansion": {
                "strategy": "templated",
                "sub_queries": ["GDPR fine 2025", "ICO enforcement action"],
            },
            "rerank": {
                "model": "cross-encoder/ms-marco",
                "candidates_in": 12,
                "candidates_out": 6,
                "latency_ms": 45.0,
            },
            "results": [
                {
                    "url": "https://ico.org.uk/news",
                    "domain": "ico.org.uk",
                    "trust_tier": 1,
                    "title": "ICO news",
                    "blocked": False,
                }
            ],
            "blocked": 0,
            "latency_ms": 123.0,
            "citations": [
                {
                    "citation_id": "cite-1",
                    "source_id": "https://ico.org.uk/news",
                    "url": "https://ico.org.uk/news",
                    "chunk_index": 0,
                    "score": 0.91,
                    "excerpt": "ICO fined Example Ltd £100k.",
                }
            ],
        },
    }
    out = _translate_agent_event(ev, run_id="r1", step_id="s1")
    names = _event_names(out)
    assert "loop.web.expand" in names
    assert "loop.web.rerank" in names
    assert "loop.web.cite" in names
    assert "loop.web.result" in names

    # Validate schemas.
    events = out if isinstance(out, list) else [out]
    for e in events:
        validate_event(e["event"], e)


def test_web_expand_payload_shape():
    ev = {
        "event": "tool_result",
        "tool": "web_research",
        "result": {
            "goal": "AI Act high-risk list",
            "intent": "regulation_text",
            "expansion": {
                "strategy": "templated",
                "sub_queries": ["q1", "q2"],
            },
            "results": [],
        },
    }
    out = _translate_agent_event(ev, run_id="r2", step_id="s2")
    events = out if isinstance(out, list) else [out]
    expand = [e for e in events if e["event"] == "loop.web.expand"][0]
    assert expand["goal"] == "AI Act high-risk list"
    assert expand["intent"] == "regulation_text"
    assert expand["sub_queries"] == ["q1", "q2"]
    assert expand["strategy"] == "templated"
    assert expand["run_id"] == "r2"
    assert expand["step_id"] == "s2"


def test_web_rerank_payload_shape():
    ev = {
        "event": "tool_result",
        "tool": "web_research",
        "result": {
            "rerank": {
                "model": "cross-encoder",
                "candidates_in": 8,
                "candidates_out": 4,
                "latency_ms": 22.0,
            },
            "results": [],
        },
    }
    out = _translate_agent_event(ev, run_id="r3", step_id="s3")
    events = out if isinstance(out, list) else [out]
    rerank = [e for e in events if e["event"] == "loop.web.rerank"][0]
    assert rerank["model"] == "cross-encoder"
    assert rerank["candidates_in"] == 8
    assert rerank["candidates_out"] == 4
    assert rerank["latency_ms"] == 22.0


def test_web_cite_payload_shape():
    ev = {
        "event": "tool_result",
        "tool": "web_research",
        "result": {
            "citations": [
                {
                    "citation_id": "c-1",
                    "source_id": "https://eur-lex.europa.eu/x",
                    "chunk_index": 2,
                    "score": 0.88,
                    "excerpt": "High-risk systems shall...",
                }
            ],
            "results": [],
        },
    }
    out = _translate_agent_event(ev, run_id="r4", step_id="s4")
    events = out if isinstance(out, list) else [out]
    cite = [e for e in events if e["event"] == "loop.web.cite"][0]
    assert cite["citation_id"] == "c-1"
    assert cite["source_id"] == "https://eur-lex.europa.eu/x"
    assert cite["chunk_index"] == 2
    assert cite["score"] == 0.88
    assert cite["excerpt"] == "High-risk systems shall..."


def test_web_result_without_metadata_emits_only_result():
    ev = {
        "event": "tool_result",
        "tool": "web_search",
        "result": {
            "results": [
                {
                    "url": "https://example.com",
                    "domain": "example.com",
                    "trust_tier": 3,
                    "title": "Example",
                    "blocked": False,
                }
            ],
            "blocked": 0,
            "latency_ms": 7.0,
        },
    }
    out = _translate_agent_event(ev, run_id="r5", step_id="s5")
    assert isinstance(out, dict)
    assert out["event"] == "loop.web.result"
    assert out["hits"][0]["url"] == "https://example.com"


def test_web_events_are_registered_in_loop_event():
    assert LoopEvent.WEB_EXPAND.value == "loop.web.expand"
    assert LoopEvent.WEB_RERANK.value == "loop.web.rerank"
    assert LoopEvent.WEB_CITE.value == "loop.web.cite"


def test_non_web_tool_result_does_not_emit_web_events():
    ev = {
        "event": "tool_result",
        "tool": "query_regulation",
        "result": {"hits": [{"chunk_id": "x"}]},
    }
    out = _translate_agent_event(ev, run_id="r6", step_id="s6")
    assert isinstance(out, dict)
    assert out["event"] == "loop.tool.result"
    assert "loop.web" not in out["event"]


def test_missing_result_keys_do_not_crash():
    ev = {
        "event": "tool_result",
        "tool": "web_research",
        "result": {
            "expansion": {},
            "rerank": {},
            "citations": [],
            "results": [],
        },
    }
    out = _translate_agent_event(ev, run_id="r7", step_id="s7")
    assert isinstance(out, dict)
    assert out["event"] == "loop.web.result"
