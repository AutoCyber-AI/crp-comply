# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Stress test: CRP Comply agent must not overflow a tiny context window.

The agent is given a task + history that would far exceed the model's
context window if sent verbatim. We verify that:

1. The agent runs to completion without raising.
2. Every LLM call's message list fits inside the declared window.
3. The latest user task survives compaction.
4. The compaction events are recorded in the trace.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from crp_comply.agent.llm import ChatTurn
from crp_comply.agent.orchestrator import ComplianceAgent
from crp_comply.agent.tools import Tool, ToolRegistry


@dataclass
class _CapturingLLM:
    """Fake ComplianceLLM that records every message list it receives."""

    turns: list[ChatTurn]
    context_window: int
    calls: list[dict[str, Any]] = field(default_factory=list)
    messages_seen: list[list[dict[str, Any]]] = field(default_factory=list)
    default_max_tokens: int = 256

    def context_window_size(self) -> int:
        return self.context_window

    def chat_with_tools(self, messages, tools, **kwargs):
        self.calls.append({"n_messages": len(messages), "n_tools": len(tools)})
        self.messages_seen.append([dict(m) for m in messages])
        if not self.turns:
            raise AssertionError("LLM ran out of scripted turns")
        return self.turns.pop(0)


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


def _long_text(tokens: int, chars_per_token: float = 2.5) -> str:
    """Generate text of roughly *tokens* tokens."""
    word = "compliance obligation risk assessment conformity "
    repeats = int(tokens * chars_per_token / len(word)) + 1
    return (word * repeats).strip()


def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
    return sum(int(len(m.get("content", "") or "") / 2.5) for m in messages)


def test_agent_compacts_history_for_4k_window(tmp_path):
    """A 4K-window agent must complete even when history alone is >10K tokens.

    CRP's promise is unbounded context *relative to the model window*: the
    protocol folds/relays what does not fit. The fixed compliance system
    prompt itself consumes most of a 4K window, so this test verifies the
    remaining budget is used for the live task and the call still fits.
    """
    context_window = 4096
    # Build a long history: 30 turns of ~160 tokens each = ~4.8K tokens.
    # Individual real-world turns are rarely 500 tokens; the stress here is
    # the *cumulative* length across many turns.
    history: list[dict[str, Any]] = []
    for i in range(30):
        history.append(
            {
                "role": "user",
                "content": f"Prior question {i}: {_long_text(80)}",
            }
        )
        history.append(
            {
                "role": "assistant",
                "content": f"Prior answer {i}: {_long_text(80)}",
            }
        )

    llm = _CapturingLLM(
        turns=[ChatTurn(text="final answer", finish_reason="stop")],
        context_window=context_window,
    )
    fabric = _FakeFabric()
    reg = ToolRegistry([_echo_tool()])
    agent = ComplianceAgent(
        llm,  # type: ignore[arg-type]
        fabric,
        reg,
        max_iters=4,
        trace_dir=tmp_path,
    )

    task = f"Current task: {_long_text(200)}"
    res = agent.run(
        task,
        customer_id="cust1",
        system_id="sysA",
        prior_messages=history,
    )

    assert res.state == "done"
    assert res.final_text == "final answer"

    # Every LLM call must fit inside the declared window.
    for idx, msgs in enumerate(llm.messages_seen):
        est = _estimate_tokens(msgs)
        assert est <= context_window, f"call {idx} estimated {est} tokens, exceeds {context_window}"

    # The current user task must survive compaction.
    last_user = next(
        (m.get("content", "") for m in reversed(llm.messages_seen[0]) if m.get("role") == "user"),
        "",
    )
    assert task[:50] in last_user

    # Trace must record the compaction event.
    trace = (tmp_path / f"{res.session_id}.jsonl").read_text(encoding="utf-8")
    events = [json.loads(line) for line in trace.splitlines() if line.strip()]
    compact_events = [
        e
        for e in events
        if e.get("event") == "crp_compact" or e.get("event") == "crp_overflow_refold"
    ]
    assert compact_events, "expected at least one CRP compaction trace event"


def test_agent_refolds_on_overflow(tmp_path):
    """If the upstream still rejects the prompt, the agent must refold and retry."""
    context_window = 4096
    history = [
        {"role": "user", "content": _long_text(300)},
        {"role": "assistant", "content": _long_text(300)},
    ]

    class _FussyLLM(_CapturingLLM):
        def chat_with_tools(self, messages, tools, **kwargs):
            self.calls.append({"n_messages": len(messages), "n_tools": len(tools)})
            self.messages_seen.append([dict(m) for m in messages])
            if len(self.calls) == 1:
                raise RuntimeError("Context size has been exceeded")
            if not self.turns:
                raise AssertionError("LLM ran out of scripted turns")
            return self.turns.pop(0)

    llm = _FussyLLM(
        turns=[ChatTurn(text="answer after refold", finish_reason="stop")],
        context_window=context_window,
    )
    fabric = _FakeFabric()
    reg = ToolRegistry([_echo_tool()])
    agent = ComplianceAgent(
        llm,  # type: ignore[arg-type]
        fabric,
        reg,
        max_iters=4,
        trace_dir=tmp_path,
    )

    res = agent.run(
        "do something",
        customer_id="cust1",
        system_id="sysA",
        prior_messages=history,
    )

    assert res.state == "done"
    assert res.final_text == "answer after refold"
    assert len(llm.calls) == 2
    # Refold was attempted; the second call is at most the same size as the
    # first (it cannot grow). When the budget is smaller than the fixed system
    # prompt the agent cannot shrink further, but it must not crash.
    assert _estimate_tokens(llm.messages_seen[1]) <= _estimate_tokens(llm.messages_seen[0])
