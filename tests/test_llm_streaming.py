# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for ``ComplianceLLM.chat_with_tools_streaming``.

Covers:

* Native OpenAI-streaming path: text deltas accumulate, tool-call
  argument JSON is reassembled across chunks, ``ChatTurn`` is
  returned with ``finish_reason='tool_calls'`` when applicable.
* Fallback path for non-OpenAI providers: a single terminal
  ``on_text_delta`` call and a normal ``ChatTurn`` from the blocking
  tool call.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from crp_comply.agent.llm import ChatTurn, ComplianceLLM


# ── Stub the OpenAI client streaming API ─────────────────────────────


@dataclass
class _ChunkDeltaTC:
    index: int
    id: str | None = None
    function: Any = None  # _ChunkDeltaFn


@dataclass
class _ChunkDeltaFn:
    name: str | None = None
    arguments: str | None = None


@dataclass
class _ChunkDelta:
    content: str | None = None
    tool_calls: list[_ChunkDeltaTC] | None = None


@dataclass
class _ChunkChoice:
    delta: _ChunkDelta
    finish_reason: str | None = None


@dataclass
class _Chunk:
    choices: list[_ChunkChoice]


class _StubCompletions:
    def __init__(self, chunks):
        self._chunks = chunks
        self.last_kwargs: dict[str, Any] = {}

    def create(self, **kwargs):
        self.last_kwargs = dict(kwargs)
        assert kwargs.get("stream") is True, "must be called with stream=True"
        return iter(self._chunks)


class _StubChat:
    def __init__(self, completions):
        self.completions = completions


class _StubOpenAIClient:
    def __init__(self, completions):
        self.chat = _StubChat(completions)


# Class name is what ComplianceLLM.supports_streaming_tools checks for.
class OpenAIAdapter:
    """Mimic crp.providers.OpenAIAdapter just enough for streaming."""

    def __init__(self, chunks):
        self._client = _StubOpenAIClient(_StubCompletions(chunks))
        self._model = "stub-model"
        self._max_tokens = 1024

    def generate_chat_with_tools(self, *, messages, tools, **kw):
        # Used only by the fallback path; tests should never hit this.
        return ("", "stop", None, None)

    def generate_chat(self, messages, **kw):  # pragma: no cover
        return ("", "stop")


_StubOpenAIAdapter = OpenAIAdapter


# ── Tests ────────────────────────────────────────────────────────────


def test_chat_with_tools_streaming_emits_text_deltas_and_returns_turn():
    chunks = [
        _Chunk(choices=[_ChunkChoice(delta=_ChunkDelta(content="Hello "))]),
        _Chunk(choices=[_ChunkChoice(delta=_ChunkDelta(content="world"))]),
        _Chunk(choices=[_ChunkChoice(delta=_ChunkDelta(content="!"), finish_reason="stop")]),
    ]
    provider = _StubOpenAIAdapter(chunks)
    llm = ComplianceLLM(provider=provider)  # type: ignore[arg-type]

    deltas: list[str] = []
    turn = llm.chat_with_tools_streaming(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        on_text_delta=deltas.append,
    )

    assert deltas == ["Hello ", "world", "!"]
    assert isinstance(turn, ChatTurn)
    assert turn.text == "Hello world!"
    assert turn.finish_reason == "stop"
    assert turn.tool_calls == []


def test_chat_with_tools_streaming_assembles_tool_call_args_across_chunks():
    """OpenAI streams tool-call arguments as partial JSON; we must concat."""
    chunks = [
        _Chunk(
            choices=[
                _ChunkChoice(
                    delta=_ChunkDelta(
                        tool_calls=[
                            _ChunkDeltaTC(
                                index=0,
                                id="call_abc",
                                function=_ChunkDeltaFn(name="query_regulation", arguments='{"que'),
                            )
                        ]
                    )
                )
            ]
        ),
        _Chunk(
            choices=[
                _ChunkChoice(
                    delta=_ChunkDelta(
                        tool_calls=[
                            _ChunkDeltaTC(
                                index=0,
                                function=_ChunkDeltaFn(arguments='ry": "GDPR Art 5"}'),
                            )
                        ]
                    )
                )
            ]
        ),
        _Chunk(choices=[_ChunkChoice(delta=_ChunkDelta(), finish_reason="tool_calls")]),
    ]
    provider = _StubOpenAIAdapter(chunks)
    llm = ComplianceLLM(provider=provider)  # type: ignore[arg-type]

    turn = llm.chat_with_tools_streaming(
        messages=[{"role": "user", "content": "x"}],
        tools=[{"type": "function", "function": {"name": "query_regulation"}}],
        on_text_delta=lambda c: None,
    )

    assert turn.finish_reason == "tool_calls"
    assert len(turn.tool_calls) == 1
    tc = turn.tool_calls[0]
    assert tc["id"] == "call_abc"
    assert tc["function"]["name"] == "query_regulation"
    assert tc["function"]["arguments"] == {"query": "GDPR Art 5"}
    assert turn.raw_assistant_message is not None
    raw_args = turn.raw_assistant_message["tool_calls"][0]["function"]["arguments"]
    assert isinstance(raw_args, str)
    assert json.loads(raw_args) == {"query": "GDPR Art 5"}


# ── Fallback path — non-streaming provider ───────────────────────────


class _NonStreamProvider:
    """A provider without streaming support — must trigger fallback."""

    def generate_chat_with_tools(self, *, messages, tools, **kw):
        return ("plain answer", "stop", None, None)

    def generate_chat(self, messages, **kw):  # pragma: no cover - unused
        return ("", "stop")


def test_fallback_calls_blocking_path_with_single_terminal_delta():
    llm = ComplianceLLM(provider=_NonStreamProvider())  # type: ignore[arg-type]
    assert not llm.supports_streaming_tools()

    deltas: list[str] = []
    turn = llm.chat_with_tools_streaming(messages=[], tools=[], on_text_delta=deltas.append)
    assert turn.text == "plain answer"
    assert turn.finish_reason == "stop"
    assert deltas == ["plain answer"]
