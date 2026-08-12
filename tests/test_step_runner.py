"""Tests for the ReAct step runner (PHASE_7 \u00a721 7.4)."""

from __future__ import annotations

import pytest

from crp_comply.agent.loop_state import PlanStep
from crp_comply.agent.step_runner import (
    StepRunner,
    ToolError,
    ToolRegistry,
    ToolResult,
    ToolSpec,
    build_default_registry,
)


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def captured_events():
    sink: list[dict] = []
    return sink


@pytest.fixture
def registry():
    reg = build_default_registry()

    def _pattern_query(*, pattern: str, top_k: int = 3) -> ToolResult:
        return ToolResult(
            summary=f"matched 2 patterns for {pattern!r}",
            citations=[
                {"source": "GDPR", "article": "Art. 6"},
                {"source": "GDPR", "article": "Art. 7"},
            ],
            raw={"hits": ["a", "b"]},
        )

    def _graph_walk(*, anchor: str, depth: int = 1) -> ToolResult:
        return ToolResult(
            summary=f"walked from {anchor!r} depth={depth}",
            citations=[],
        )

    def _crash(**_kw) -> ToolResult:
        raise RuntimeError("boom")

    reg.register(
        ToolSpec(
            name="pattern_query",
            description="Query the pattern KB.",
            handler=_pattern_query,
            input_schema={
                "type": "object",
                "required": ["pattern"],
                "properties": {
                    "pattern": {"type": "string"},
                    "top_k": {"type": "integer"},
                },
            },
        )
    )
    reg.register(
        ToolSpec(
            name="graph_walk",
            description="Walk the GraphRAG graph.",
            handler=_graph_walk,
            input_schema={
                "type": "object",
                "required": ["anchor"],
                "properties": {
                    "anchor": {"type": "string"},
                    "depth": {"type": "integer"},
                },
            },
        )
    )
    reg.register(
        ToolSpec(
            name="crash",
            description="Always crashes.",
            handler=_crash,
            input_schema={"type": "object"},
        )
    )
    return reg


# ── Registry ────────────────────────────────────────────────────────


def test_registry_rejects_unknown_tool(registry):
    with pytest.raises(ToolError, match="unknown tool"):
        registry.dispatch("does_not_exist", {})


def test_registry_rejects_double_register(registry):
    with pytest.raises(ToolError, match="already registered"):
        registry.register(
            ToolSpec(
                name="pattern_query",
                description="dup",
                handler=lambda **_: ToolResult(summary=""),
            )
        )


def test_registry_validates_required_args(registry):
    with pytest.raises(ToolError, match="missing required"):
        registry.dispatch("pattern_query", {})


def test_registry_validates_arg_types(registry):
    with pytest.raises(ToolError, match="expected string"):
        registry.dispatch("pattern_query", {"pattern": 42})


def test_registry_rejects_non_toolresult_return(registry):
    registry._tools["bad"] = ToolSpec(  # type: ignore[attr-defined]
        name="bad",
        description="returns a dict",
        handler=lambda **_: {"not": "a tool result"},  # type: ignore[return-value]
        input_schema={},
    )
    with pytest.raises(ToolError, match="expected ToolResult"):
        registry.dispatch("bad", {})


def test_registry_names_lists_registered(registry):
    assert "recall_facts" in registry.names()
    assert "pattern_query" in registry.names()


# ── Step runner: event order ────────────────────────────────────────


def test_step_runner_emits_canonical_event_sequence(registry, captured_events):
    runner = StepRunner(
        registry=registry,
        event_sink=captured_events.append,
        run_id="run-1",
    )
    step = PlanStep(
        id="s1",
        intent="check Art. 6 lawful basis",
        tool_hint="pattern_query",
    )
    outcome = runner.run_step(
        step,
        thoughts=["I should ", "search the pattern KB."],
        tool_calls=[
            ("pattern_query", {"pattern": "art6"}),
            ("graph_walk", {"anchor": "Art. 6", "depth": 2}),
        ],
    )
    names = [e["event"] for e in captured_events]
    # Mandatory: step.start \u2192 (recall_facts call+result) \u2192
    # 2 thought deltas \u2192 (pattern_query call+result) \u2192
    # (graph_walk call+result) \u2192 step.end
    assert names == [
        "loop.step.start",
        "loop.tool.call",
        "loop.tool.result",  # recall_facts prefix
        "loop.thought.delta",
        "loop.thought.delta",
        "loop.tool.call",
        "loop.tool.result",  # pattern_query
        "loop.tool.call",
        "loop.tool.result",  # graph_walk
        "loop.step.end",
    ]
    # First tool call is *always* recall_facts (audit trail).
    first_call = next(e for e in captured_events if e["event"] == "loop.tool.call")
    assert first_call["tool"] == "recall_facts"
    assert outcome.status == "ok"
    assert any(c["article"] == "Art. 6" for c in outcome.citations)


def test_step_runner_text_only_step_still_has_recall_prefix(registry, captured_events):
    runner = StepRunner(registry=registry, event_sink=captured_events.append, run_id="run-2")
    step = PlanStep(id="s1", intent="just think")
    runner.run_step(step, thoughts=["thinking..."], tool_calls=[])
    names = [e["event"] for e in captured_events]
    assert names == [
        "loop.step.start",
        "loop.tool.call",
        "loop.tool.result",  # recall_facts
        "loop.thought.delta",
        "loop.step.end",
    ]


def test_step_runner_run_id_stamped_on_every_event(registry, captured_events):
    runner = StepRunner(registry=registry, event_sink=captured_events.append, run_id="abc")
    runner.run_step(PlanStep(id="s1", intent="x"), tool_calls=[("pattern_query", {"pattern": "p"})])
    assert all(e.get("run_id") == "abc" for e in captured_events)


# ── Step runner: error paths ────────────────────────────────────────


def test_step_runner_unknown_tool_emits_tool_result_with_error(registry, captured_events):
    runner = StepRunner(registry=registry, event_sink=captured_events.append, run_id="r")
    outcome = runner.run_step(
        PlanStep(id="s1", intent="boom"),
        tool_calls=[("nope", {})],
    )
    # The bad tool produced a call+result pair where the result has
    # error set (no silent swallow).
    bad = [e for e in captured_events if e["event"] == "loop.tool.result" and e["tool"] == "nope"]
    assert bad, "expected a loop.tool.result for the unknown tool"
    assert "unknown tool" in bad[0]["error"]
    assert outcome.status == "failed"
    end = [e for e in captured_events if e["event"] == "loop.step.end"][0]
    assert end["status"] == "failed"


def test_step_runner_invalid_args_does_not_swallow(registry, captured_events):
    runner = StepRunner(registry=registry, event_sink=captured_events.append, run_id="r")
    outcome = runner.run_step(
        PlanStep(id="s1", intent="bad args"),
        tool_calls=[("pattern_query", {"pattern": 42})],  # int not str
    )
    bad = [
        e
        for e in captured_events
        if e["event"] == "loop.tool.result" and e["tool"] == "pattern_query"
    ][-1]
    assert "expected string" in bad["error"]
    assert outcome.status == "failed"


def test_step_runner_handler_crash_surfaces_as_error(registry, captured_events):
    runner = StepRunner(registry=registry, event_sink=captured_events.append, run_id="r")
    outcome = runner.run_step(
        PlanStep(id="s1", intent="trip the crasher"),
        tool_calls=[("crash", {})],
    )
    bad = [e for e in captured_events if e["event"] == "loop.tool.result" and e["tool"] == "crash"][
        -1
    ]
    assert "RuntimeError" in (bad["error"] or "")
    assert "boom" in (bad["error"] or "")
    assert outcome.status == "failed"


def test_step_runner_recall_prefix_can_be_disabled_for_tests(captured_events):
    reg = ToolRegistry()  # no recall_facts at all
    runner = StepRunner(
        registry=reg,
        event_sink=captured_events.append,
        run_id="r",
        require_recall_prefix=False,
    )
    runner.run_step(PlanStep(id="s1", intent="x"))
    names = [e["event"] for e in captured_events]
    assert names == ["loop.step.start", "loop.step.end"]
