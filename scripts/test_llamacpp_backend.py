# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Verify llama.cpp server backend with CRP content-based tool normalization.

Run with a llama.cpp server on http://127.0.0.1:8123. The script sends a
chat-completion with tools and checks that the returned JSON-in-content is
converted to OpenAI-style ``tool_calls``.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdk", "src"))

from crp_comply_sdk.llamacpp_tools import (
    inject_llamacpp_tool_instruction,
    normalize_content_tool_calls,
)


LLAMACPP_URL = os.environ.get("CRP_COMPLY_TEST_LLAMACPP_URL", "http://127.0.0.1:8123")
TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "query_regulation",
            "description": "Search the regulation corpus",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }
]


def _resolve_model() -> str:
    try:
        data = httpx.get(f"{LLAMACPP_URL}/v1/models", timeout=5.0).json()
        models = data.get("data", [])
        if models:
            return str(models[0]["id"])
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: could not list models: {exc}")
    return "auto"


def main() -> int:
    model = _resolve_model()
    print(f"llama.cpp server: {LLAMACPP_URL}")
    print(f"Model: {model}")

    messages = inject_llamacpp_tool_instruction(
        [
            {
                "role": "system",
                "content": "You are a compliance assistant. Use the query_regulation tool to answer.",
            },
            {"role": "user", "content": "What does the EU AI Act say about high-risk AI?"},
        ],
        TOOLS,
    )

    payload = {
        "model": model,
        "messages": messages,
        "tools": TOOLS,
        "tool_choice": "auto",
        "max_tokens": 256,
    }
    print("\nSending request...")
    resp = httpx.post(
        f"{LLAMACPP_URL}/v1/chat/completions",
        json=payload,
        timeout=120.0,
    )
    resp.raise_for_status()
    data = resp.json()

    raw_msg = data["choices"][0]["message"]
    print("\nRAW response:")
    print(f"  content: {raw_msg.get('content', '')!r}")
    print(f"  tool_calls: {raw_msg.get('tool_calls')}")

    normalized = normalize_content_tool_calls(data, TOOLS)
    norm_msg = normalized["choices"][0]["message"]
    print("\nNORMALIZED response:")
    print(f"  content: {norm_msg.get('content', '')!r}")
    print(f"  tool_calls: {norm_msg.get('tool_calls')}")

    if norm_msg.get("tool_calls"):
        print("\nPASS: content-based tool call was normalized")
        return 0
    print("\nFAIL: no tool call found")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
