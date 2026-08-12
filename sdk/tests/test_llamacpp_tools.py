"""Tests for llama.cpp content-based tool-call normalization."""

from __future__ import annotations

import json

from crp_comply_sdk.llamacpp_tools import (
    inject_llamacpp_tool_instruction,
    normalize_content_tool_calls,
)


_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_regulation",
            "description": "Search regulation corpus",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web",
            "parameters": {
                "type": "object",
                "properties": {"q": {"type": "string"}},
                "required": ["q"],
            },
        },
    },
]


def test_normalize_no_op_when_native_tool_calls_present():
    response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "query_regulation", "arguments": "{}"},
                        }
                    ],
                }
            }
        ]
    }
    out = normalize_content_tool_calls(response, _TOOLS)
    assert out["choices"][0]["message"]["tool_calls"][0]["id"] == "call_1"


def test_normalize_extracts_flat_json_tool_call():
    response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": '{"name": "query_regulation", "arguments": {"query": "EU AI Act high-risk"}}',
                }
            }
        ]
    }
    out = normalize_content_tool_calls(response, _TOOLS)
    message = out["choices"][0]["message"]
    assert message["content"] == ""
    assert len(message["tool_calls"]) == 1
    assert message["tool_calls"][0]["function"]["name"] == "query_regulation"
    assert json.loads(message["tool_calls"][0]["function"]["arguments"]) == {
        "query": "EU AI Act high-risk"
    }


def test_normalize_extracts_parameters_alias():
    response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": '{"name": "web_search", "parameters": {"q": "foo"}}',
                }
            }
        ]
    }
    out = normalize_content_tool_calls(response, _TOOLS)
    message = out["choices"][0]["message"]
    assert message["tool_calls"][0]["function"]["name"] == "web_search"
    assert json.loads(message["tool_calls"][0]["function"]["arguments"]) == {"q": "foo"}


def test_normalize_extracts_from_code_fence():
    response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "```json\n{\"name\": \"query_regulation\", \"arguments\": {\"query\": \"x\"}}\n```",
                }
            }
        ]
    }
    out = normalize_content_tool_calls(response, _TOOLS)
    assert out["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "query_regulation"


def test_normalize_ignores_unknown_tool_name():
    response = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": '{"name": "unknown_tool", "arguments": {}}',
                }
            }
        ]
    }
    out = normalize_content_tool_calls(response, _TOOLS)
    assert "tool_calls" not in out["choices"][0]["message"]


def test_normalize_ignores_plain_text():
    response = {
        "choices": [
            {"message": {"role": "assistant", "content": "Hello, how can I help?"}}
        ]
    }
    out = normalize_content_tool_calls(response, _TOOLS)
    assert "tool_calls" not in out["choices"][0]["message"]


def test_inject_instruction_appends_system_message():
    messages = [{"role": "system", "content": "You are helpful."}]
    out = inject_llamacpp_tool_instruction(messages, _TOOLS)
    assert len(out) == 2
    assert out[1]["role"] == "system"
    assert "query_regulation" in out[1]["content"]
    assert "web_search" in out[1]["content"]
