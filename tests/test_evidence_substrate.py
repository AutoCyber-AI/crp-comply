# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Evidence-substrate integration tests.

These tests pin the contracts for the three §6 gap-fixes:

1. ``fetch_artefact`` — the agent's window onto the user's evidence
   uploads (model cards, dataset cards, DPAs, pen-tests).
2. ``query_proxy_metrics`` — the agent's window onto the runtime
   audit chain (PII rates, refusals, consent coverage, models used).
3. CRP context priming + per-paragraph provenance — the LLM enters
   each drafting session with a CRP-packed envelope of the relevant
   regulation already in working memory, and emits paragraphs whose
   provenance is auditable per-claim.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from crp_comply.agent.tools import (
    build_fetch_artefact_tool,
    build_query_proxy_metrics_tool,
    default_registry,
)
from crp_comply.recipes.executor import (
    RecipeRunner,
    _coerce_paragraphs,
)
from crp_comply.recipes.loader import Recipe, RecipeSection


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeArtefactStore:
    def __init__(self, artefacts):
        self._artefacts = list(artefacts)
        self.calls: list[tuple[str, list[str] | None]] = []

    def for_clauses(self, user_id, clauses):
        self.calls.append(("for_clauses", list(clauses)))
        out = []
        for a in self._artefacts:
            if any(c in (a.get("clauses") or []) for c in clauses):
                out.append(dict(a))
        # Tenant boundary: emulate the real store filtering by user_id.
        return [a for a in out if a.get("user_id", user_id) == user_id]

    def list(self, user_id):
        self.calls.append(("list", None))
        return [dict(a) for a in self._artefacts if a.get("user_id", user_id) == user_id]


class _FakeProxy:
    def __init__(self, stats, records=None):
        self._stats = stats
        self._records = records or []
        self.stats_calls: list[str | None] = []
        self.record_calls: list[dict] = []

    def get_compliance_stats(self, user_id=None):
        self.stats_calls.append(user_id)
        return self._stats

    def list_audit_records(self, limit=50, offset=0, user_id=None):
        self.record_calls.append({"limit": limit, "offset": offset, "user_id": user_id})
        return [dict(r) for r in self._records[: int(limit)]]


# ---------------------------------------------------------------------------
# fetch_artefact
# ---------------------------------------------------------------------------


def test_fetch_artefact_filters_by_clauses_and_strips_blob_fields():
    artefacts = [
        {
            "id": "art_1",
            "kind": "model_card",
            "filename": "card.md",
            "sha256": "abc",
            "clauses": ["eu_ai_act_art_10", "eu_ai_act_art_11"],
            "description": "Vision model card",
            "size_bytes": 1234,
            "created_at": "2025-01-01T00:00:00Z",
            "blob_path": "/srv/secret",  # must NOT leak
        },
        {
            "id": "art_2",
            "kind": "pen_test",
            "filename": "pentest.pdf",
            "sha256": "def",
            "clauses": ["eu_ai_act_art_15"],
            "description": "",
            "size_bytes": 9999,
            "created_at": "2025-02-02T00:00:00Z",
        },
    ]
    store = _FakeArtefactStore(artefacts)
    tool = build_fetch_artefact_tool(store, user_id="u1")
    out = tool.handler({"clauses": ["eu_ai_act_art_10"]})
    assert out["count"] == 1
    a = out["artefacts"][0]
    assert a["id"] == "art_1"
    assert a["kind"] == "model_card"
    assert "blob_path" not in a  # slim metadata only
    assert store.calls[0] == ("for_clauses", ["eu_ai_act_art_10"])


def test_fetch_artefact_kind_filter_and_empty_note():
    store = _FakeArtefactStore([])
    tool = build_fetch_artefact_tool(store, user_id="u1")
    out = tool.handler({"kind": "dpia"})
    assert out["count"] == 0
    assert "PLACEHOLDER" in out["note"]


def test_fetch_artefact_no_filter_returns_all():
    artefacts = [
        {"id": "a", "kind": "model_card", "filename": "x", "clauses": []},
    ]
    store = _FakeArtefactStore(artefacts)
    tool = build_fetch_artefact_tool(store, user_id="u1")
    out = tool.handler({})
    assert out["count"] == 1
    assert store.calls[-1] == ("list", None)


# ---------------------------------------------------------------------------
# query_proxy_metrics
# ---------------------------------------------------------------------------


def test_query_proxy_metrics_returns_aggregates():
    stats = SimpleNamespace(
        total_requests=42,
        pii_detections=3,
        injection_attempts=1,
        compliance_rate=0.97,
        models_used={"gpt-4o": 30, "claude-3.5": 12},
        risk_distribution={"low": 35, "medium": 7, "high": 0},
        quality_distribution={"high": 40, "medium": 2},
        consent_coverage=1.0,
        retention_tracked=42,
        lineage_tracked=42,
    )
    proxy = _FakeProxy(stats)
    tool = build_query_proxy_metrics_tool(proxy, user_id="u1")
    out = tool.handler({})
    assert out["evidence_available"] is True
    assert out["user_id"] == "u1"
    assert out["stats"]["total_requests"] == 42
    assert proxy.stats_calls == ["u1"]


def test_query_proxy_metrics_empty_emits_placeholder_note():
    stats = SimpleNamespace(
        total_requests=0,
        pii_detections=0,
        injection_attempts=0,
        compliance_rate=1.0,
        models_used={},
        risk_distribution={},
        quality_distribution={},
        consent_coverage=0.0,
        retention_tracked=0,
        lineage_tracked=0,
    )
    proxy = _FakeProxy(stats)
    tool = build_query_proxy_metrics_tool(proxy, user_id="u1")
    out = tool.handler({})
    assert out["evidence_available"] is False
    assert "PLACEHOLDER:runtime" in out["note"]


def test_query_proxy_metrics_includes_slim_samples():
    stats = SimpleNamespace(
        total_requests=2,
        pii_detections=0,
        injection_attempts=0,
        compliance_rate=1.0,
        models_used={"gpt": 2},
        risk_distribution={},
        quality_distribution={},
        consent_coverage=1.0,
        retention_tracked=2,
        lineage_tracked=2,
    )
    records = [
        {
            "record_id": "r1",
            "timestamp": "2025-01-01T00:00:00Z",
            "model": "gpt-4o",
            "risk_level": "low",
            "pii_detected_input": False,
            "pii_detected_output": False,
            "injection_risk": "none",
            "input_tokens": 100,
            "output_tokens": 50,
            "prompt": "SECRET PROMPT MUST NOT LEAK",  # must be stripped
            "response": "SECRET RESPONSE MUST NOT LEAK",
        },
    ]
    proxy = _FakeProxy(stats, records)
    tool = build_query_proxy_metrics_tool(proxy, user_id="u1")
    out = tool.handler({"include_samples": True, "sample_limit": 3})
    assert "recent_records" in out
    sample = out["recent_records"][0]
    assert sample["record_id"] == "r1"
    assert "prompt" not in sample  # PII-adjacent payload stripped
    assert "response" not in sample


# ---------------------------------------------------------------------------
# default_registry wiring
# ---------------------------------------------------------------------------


def test_default_registry_registers_evidence_tools_when_provided():
    store = _FakeArtefactStore([])
    proxy = _FakeProxy(SimpleNamespace(total_requests=0))
    reg = default_registry(artefact_store=store, proxy_metrics=proxy, user_id="u1")
    names = set(reg._tools.keys())
    assert "fetch_artefact" in names
    assert "query_proxy_metrics" in names


def test_default_registry_skips_evidence_tools_without_user_id():
    store = _FakeArtefactStore([])
    reg = default_registry(artefact_store=store, user_id="")
    names = set(reg._tools.keys())
    assert "fetch_artefact" not in names


# ---------------------------------------------------------------------------
# Per-paragraph provenance
# ---------------------------------------------------------------------------


def test_coerce_paragraphs_parses_envelope():
    payload = json.dumps(
        {
            "paragraphs": [
                {
                    "text": "Article 6 governs high-risk AI systems.",
                    "provenance": [
                        {"kind": "regulation", "ref": "eu_ai_act:art_6:1", "label": "Art. 6"},
                    ],
                },
                {
                    "text": "Our model card documents the training data.",
                    "provenance": [
                        {"kind": "artefact", "ref": "art_1", "label": "model_card"},
                    ],
                },
            ],
        }
    )
    paragraphs = _coerce_paragraphs(payload)
    assert paragraphs is not None
    assert len(paragraphs) == 2
    assert paragraphs[0].provenance[0]["kind"] == "regulation"
    assert paragraphs[1].provenance[0]["kind"] == "artefact"


def test_coerce_paragraphs_strips_code_fences():
    payload = (
        "```json\n"
        + json.dumps(
            {"paragraphs": [{"text": "x", "provenance": [{"kind": "interview", "ref": "q1"}]}]}
        )
        + "\n```"
    )
    paragraphs = _coerce_paragraphs(payload)
    assert paragraphs is not None
    assert paragraphs[0].text == "x"
    assert paragraphs[0].provenance[0]["kind"] == "interview"


def test_coerce_paragraphs_returns_none_on_plain_markdown():
    assert _coerce_paragraphs("Just a regular paragraph.") is None


def test_coerce_paragraphs_unknown_kind_falls_back_to_unsourced():
    payload = json.dumps(
        {"paragraphs": [{"text": "x", "provenance": [{"kind": "made_up", "ref": "r"}]}]}
    )
    paragraphs = _coerce_paragraphs(payload)
    assert paragraphs[0].provenance[0]["kind"] == "unsourced"


# ---------------------------------------------------------------------------
# Recipe runner — paragraph plumbing
# ---------------------------------------------------------------------------


class _StubAgent:
    """Agent stub that returns a JSON paragraph envelope."""

    def __init__(self, payload):
        self.payload = payload
        self.runs: list[dict] = []

    def run(self, prompt, *, recipe_context=None):
        self.runs.append({"prompt": prompt, "recipe_context": recipe_context})
        return SimpleNamespace(final_text=self.payload)


def _make_recipe():
    return Recipe(
        recipe_id="test_recipe",
        title="Test Recipe",
        regulation="EU AI Act",
        version="1.0",
        description="",
        sections=[
            RecipeSection(
                id="overview",
                title="Overview",
                instructions="Write the overview.",
                citations=["Article 6"],
                word_budget=200,
            ),
        ],
    )


def test_recipe_runner_emits_paragraphs_and_passes_recipe_context():
    payload = json.dumps(
        {
            "paragraphs": [
                {
                    "text": "High-risk AI systems must meet Article 6.",
                    "provenance": [{"kind": "regulation", "ref": "eu_ai_act:art_6"}],
                },
            ],
        }
    )
    agent = _StubAgent(payload)
    runner = RecipeRunner(agent)
    recipe = _make_recipe()
    out = runner.run(recipe, inputs={})
    section = out.json_payload["sections"][0]
    assert "paragraphs" in section
    assert len(section["paragraphs"]) == 1
    assert section["paragraphs"][0]["provenance"][0]["kind"] == "regulation"
    # recipe_context must be threaded so the agent can CRP-prime.
    assert agent.runs[0]["recipe_context"] is not None
    ctx = agent.runs[0]["recipe_context"]
    assert ctx["regulation"] == "EU AI Act"
    assert "Article 6" in ctx["topic_keywords"]


def test_recipe_runner_falls_back_when_envelope_missing():
    agent = _StubAgent("Plain markdown body about Article 6.")
    runner = RecipeRunner(agent)
    out = runner.run(_make_recipe(), inputs={})
    section = out.json_payload["sections"][0]
    assert len(section["paragraphs"]) == 1
    assert section["paragraphs"][0]["provenance"][0]["kind"] == "unsourced"
    # Warning must be surfaced so callers can detect best-effort mode.
    assert any("provenance envelope" in w for w in out.warnings)


def test_recipe_runner_renders_footnotes_in_markdown():
    payload = json.dumps(
        {
            "paragraphs": [
                {
                    "text": "Claim grounded in Article 6.",
                    "provenance": [
                        {"kind": "regulation", "ref": "eu_ai_act:art_6:1", "label": "Art. 6"},
                    ],
                },
            ],
        }
    )
    runner = RecipeRunner(_StubAgent(payload))
    out = runner.run(_make_recipe(), inputs={})
    assert "[^overview-1]" in out.markdown
    assert "regulation" in out.markdown
    assert "eu_ai_act:art_6:1" in out.markdown


# ---------------------------------------------------------------------------
# CRP context priming in orchestrator
# ---------------------------------------------------------------------------


def test_orchestrator_primes_context_from_recipe_context(monkeypatch):
    """``ComplianceAgent.run`` must prepend a CRP-packed system message
    when ``rag`` is wired and ``recipe_context`` is provided."""

    from crp_comply.agent.orchestrator import ComplianceAgent
    from crp_comply.agent.tools import (
        ToolRegistry,
        build_classify_ai_act_risk_tool,
    )

    class _FakeRag:
        def __init__(self):
            self.calls: list[dict] = []

        def query_packed(self, query_text, **kwargs):
            self.calls.append({"q": query_text, **kwargs})
            return {
                "packed": [
                    {
                        "chunk_id": "eu_ai_act:art_6:1",
                        "text": "High-risk AI systems classification rules.",
                        "article_id": "Article 6",
                        "title": "EU AI Act",
                        "score": 0.91,
                    },
                ],
                "contradictions": [],
                "total_tokens": 25,
                "dropped": 0,
                "hits": [],
            }

    captured: dict = {}

    from crp_comply.agent.llm import ChatTurn

    class _FakeLLM:
        def chat_with_tools(self, *, messages, tools, tool_choice="auto", **kwargs):
            captured["messages"] = list(messages)
            return ChatTurn(text="Done.", finish_reason="stop")

    rag = _FakeRag()
    agent = ComplianceAgent(
        llm=_FakeLLM(),
        fabric=None,
        tools=ToolRegistry([build_classify_ai_act_risk_tool()]),
        rag=rag,
        prime_budget_tokens=1500,
    )
    result = agent.run(
        "draft something",
        recipe_context={
            "regulation": "EU AI Act",
            "topic_keywords": ["Article 6", "high-risk"],
        },
    )
    # The rag service must have been queried with the joined keywords.
    assert rag.calls and "Article 6" in rag.calls[0]["q"]
    # The first system message is the base prompt; the second must be
    # the CRP-packed primer with the chunk id present.
    sys_messages = [m for m in captured["messages"] if m["role"] == "system"]
    assert len(sys_messages) >= 2
    primer = sys_messages[1]["content"]
    assert "Pre-loaded regulatory context" in primer
    assert "eu_ai_act:art_6:1" in primer
    assert result.final_text == "Done."


def test_orchestrator_skips_priming_without_recipe_context():
    from crp_comply.agent.orchestrator import ComplianceAgent
    from crp_comply.agent.tools import (
        ToolRegistry,
        build_classify_ai_act_risk_tool,
    )

    class _FakeRag:
        def query_packed(self, *a, **k):
            raise AssertionError("must not call rag without recipe_context")

    captured: dict = {}

    from crp_comply.agent.llm import ChatTurn

    class _FakeLLM:
        def chat_with_tools(self, *, messages, tools, tool_choice="auto", **kwargs):
            captured["messages"] = list(messages)
            return ChatTurn(text="ok", finish_reason="stop")

    agent = ComplianceAgent(
        llm=_FakeLLM(),
        fabric=None,
        tools=ToolRegistry([build_classify_ai_act_risk_tool()]),
        rag=_FakeRag(),
    )
    agent.run("hi")  # no recipe_context — must NOT trigger priming
    sys_messages = [m for m in captured["messages"] if m["role"] == "system"]
    # Only the base system prompt — no primer.
    assert len(sys_messages) == 1
