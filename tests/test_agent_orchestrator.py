"""Unit tests for :class:`crp_comply.agent.orchestrator.ComplianceAgent`.

All tests use a scripted ``FakeLLM`` so they run offline and deterministically.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from crp_comply.agent.llm import ChatTurn
from crp_comply.agent.orchestrator import ComplianceAgent
from crp_comply.agent.tools import (
    Tool,
    ToolRegistry,
    build_request_clarification_tool,
)


# ---------------------------------------------------------------------------
# Scripted LLM
# ---------------------------------------------------------------------------


@dataclass
class _ScriptedLLM:
    """Pretends to be a :class:`ComplianceLLM`. Returns pre-canned turns."""

    turns: list[ChatTurn]
    calls: list[dict[str, Any]] = field(default_factory=list)
    messages_seen: list[list[dict[str, Any]]] = field(default_factory=list)

    def chat_with_tools(self, messages, tools, **kwargs):
        self.calls.append(
            {
                "n_messages": len(messages),
                "last_role": messages[-1].get("role") if messages else None,
                "n_tools": len(tools),
            }
        )
        # Snapshot a shallow copy so later mutations don't affect our view.
        self.messages_seen.append([dict(m) for m in messages])
        if not self.turns:
            raise AssertionError("LLM ran out of scripted turns")
        return self.turns.pop(0)


def _tc(call_id: str, name: str, args: dict) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)},
    }


def _assistant_msg(tool_calls: list[dict]) -> dict:
    return {"role": "assistant", "content": None, "tool_calls": tool_calls}


# ---------------------------------------------------------------------------
# Fakes for fabric + tool
# ---------------------------------------------------------------------------


class _FakeFabric:
    def __init__(self) -> None:
        self.stored: list[tuple[list, str]] = []

    def store(self, facts, window_id=""):
        self.stored.append((list(facts), window_id))

    def fact_count(self) -> int:
        return sum(len(f) for f, _ in self.stored)


def _echo_tool() -> Tool:
    def handler(args):
        return {"echo": args}

    return Tool(
        name="echo",
        description="Echo arguments back.",
        parameters={
            "type": "object",
            "properties": {"x": {"type": "string"}},
            "required": ["x"],
        },
        handler=handler,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_single_turn_no_tools_returns_done(tmp_path):
    llm = _ScriptedLLM(
        turns=[
            ChatTurn(text="final answer", finish_reason="stop"),
        ]
    )
    fabric = _FakeFabric()
    reg = ToolRegistry([_echo_tool()])
    agent = ComplianceAgent(llm, fabric, reg, max_iters=4, trace_dir=tmp_path)  # type: ignore[arg-type]

    res = agent.run("hi", customer_id="cust1", system_id="sysA")

    assert res.state == "done"
    assert res.final_text == "final answer"
    assert res.iterations == 1
    assert res.tool_calls == 0
    assert len(llm.calls) == 1
    # Final answer persisted as a CKF fact
    assert res.facts_stored == 1
    assert fabric.stored[0][1].startswith("cust1/sysA/")
    # Trace written
    trace = (tmp_path / f"{res.session_id}.jsonl").read_text(encoding="utf-8")
    events = [json.loads(line) for line in trace.splitlines() if line.strip()]
    kinds = [e["event"] for e in events]
    assert kinds[0] == "session_start"
    assert kinds[-1] == "session_end"


def test_tool_call_then_final(tmp_path):
    raw_assistant = _assistant_msg([_tc("call_1", "echo", {"x": "hello"})])
    llm = _ScriptedLLM(
        turns=[
            ChatTurn(
                text="",
                finish_reason="tool_calls",
                tool_calls=[_tc("call_1", "echo", {"x": "hello"})],
                raw_assistant_message=raw_assistant,
            ),
            ChatTurn(text="wrapped up", finish_reason="stop"),
        ]
    )
    fabric = _FakeFabric()
    reg = ToolRegistry([_echo_tool()])
    agent = ComplianceAgent(llm, fabric, reg, max_iters=4, trace_dir=tmp_path)  # type: ignore[arg-type]

    res = agent.run("please echo", customer_id="c", system_id="s")

    assert res.state == "done"
    assert res.tool_calls == 1
    assert res.iterations == 2
    # Tool fact + final fact
    assert res.facts_stored == 2
    # Second LLM call must have been given the assistant + tool message
    roles_second_call = [m["role"] for m in llm.messages_seen[1]]
    assert "assistant" in roles_second_call
    assert "tool" in roles_second_call


def test_clarification_pauses_loop(tmp_path):
    clar_call = _tc("call_9", "request_clarification", {"question": "What region?"})
    llm = _ScriptedLLM(
        turns=[
            ChatTurn(
                text="",
                finish_reason="tool_calls",
                tool_calls=[clar_call],
                raw_assistant_message=_assistant_msg([clar_call]),
            ),
        ]
    )
    fabric = _FakeFabric()
    reg = ToolRegistry([build_request_clarification_tool()])
    agent = ComplianceAgent(llm, fabric, reg, max_iters=4, trace_dir=tmp_path)  # type: ignore[arg-type]

    res = agent.run("assess me")

    assert res.state == "awaiting_clarification"
    assert res.pending_question == "What region?"
    assert res.iterations == 1
    # Clarification fact persisted so the resume path can pick it up
    assert res.facts_stored == 1


def test_max_iters_exhausted(tmp_path):
    _tc("call_i", "echo", {"x": "loop"})
    llm = _ScriptedLLM(
        turns=[
            ChatTurn(
                text="",
                finish_reason="tool_calls",
                tool_calls=[_tc(f"c{i}", "echo", {"x": str(i)})],
                raw_assistant_message=_assistant_msg([_tc(f"c{i}", "echo", {"x": str(i)})]),
            )
            for i in range(3)
        ]
    )
    fabric = _FakeFabric()
    reg = ToolRegistry([_echo_tool()])
    agent = ComplianceAgent(llm, fabric, reg, max_iters=3, trace_dir=tmp_path)  # type: ignore[arg-type]

    res = agent.run("infinite loop")
    assert res.state == "max_iters"
    assert res.iterations == 3
    assert res.tool_calls == 3


def test_llm_error_returns_error_state(tmp_path):
    class _ExplodingLLM:
        def chat_with_tools(self, messages, tools, **kwargs):
            raise RuntimeError("provider offline")

    fabric = _FakeFabric()
    reg = ToolRegistry([_echo_tool()])
    agent = ComplianceAgent(_ExplodingLLM(), fabric, reg, max_iters=2, trace_dir=tmp_path)  # type: ignore[arg-type]

    res = agent.run("hi")
    assert res.state == "error"
    assert "provider offline" in res.error


def test_requires_at_least_one_tool():
    with pytest.raises(ValueError):
        ComplianceAgent(_ScriptedLLM(turns=[]), _FakeFabric(), ToolRegistry())  # type: ignore[arg-type]


def test_unknown_tool_call_surfaces_as_tool_message(tmp_path):
    bad_call = _tc("call_x", "no_such_tool", {})
    llm = _ScriptedLLM(
        turns=[
            ChatTurn(
                text="",
                finish_reason="tool_calls",
                tool_calls=[bad_call],
                raw_assistant_message=_assistant_msg([bad_call]),
            ),
            ChatTurn(text="giving up", finish_reason="stop"),
        ]
    )
    fabric = _FakeFabric()
    reg = ToolRegistry([_echo_tool()])
    agent = ComplianceAgent(llm, fabric, reg, max_iters=3, trace_dir=tmp_path)  # type: ignore[arg-type]

    res = agent.run("call bad tool")
    assert res.state == "done"
    # Tool error was appended and then LLM resumed to a final text answer
    assert res.tool_calls == 1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# No helpers required — assertions read ``llm.messages_seen`` directly.
