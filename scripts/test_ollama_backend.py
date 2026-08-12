# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Verify Ollama backend for CRP Comply.

Requires a small model such as ``qwen2.5:0.5b`` to be available locally:
    ollama pull qwen2.5:0.5b

The script checks the OpenAI-compatible endpoint and optionally verifies
content-based tool instruction support.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

OLLAMA_URL = os.environ.get("CRP_COMPLY_TEST_OLLAMA_URL", "http://127.0.0.1:11434")
MODEL = os.environ.get("CRP_COMPLY_TEST_OLLAMA_MODEL", "qwen2.5:0.5b")
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


def _list_models() -> list[str]:
    try:
        data = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=5.0).json()
        return [str(m["name"]) for m in data.get("models", [])]
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: could not list Ollama models: {exc}")
        return []


def _chat(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": MODEL,
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    resp = httpx.post(
        f"{OLLAMA_URL}/v1/chat/completions",
        json=payload,
        timeout=120.0,
    )
    resp.raise_for_status()
    return resp.json()


def main() -> int:
    print(f"Ollama server: {OLLAMA_URL}")
    models = _list_models()
    print(f"Available models: {models}")
    if MODEL not in models:
        print(f"\nFAIL: model {MODEL!r} not found. Run: ollama pull {MODEL}")
        return 1

    print(f"\nBasic chat with {MODEL}...")
    result = _chat([{"role": "user", "content": "Say hello"}])
    content = result["choices"][0]["message"].get("content", "")
    print(f"Response: {content!r}")

    print("\nTool-instructed chat...")
    messages = [
        {
            "role": "system",
            "content": (
                "You are a compliance assistant. If you need to call a tool, "
                "output ONLY a JSON object of the form "
                '{"name": "TOOL_NAME", "arguments": {"arg": "value"}} '
                "and no other text. Available tools: query_regulation."
            ),
        },
        {"role": "user", "content": "What does the EU AI Act say about high-risk AI?"},
    ]
    result = _chat(messages, TOOLS)
    msg = result["choices"][0]["message"]
    print(f"content: {msg.get('content', '')!r}")
    print(f"tool_calls: {msg.get('tool_calls')}")

    if msg.get("tool_calls"):
        print("\nPASS: Ollama backend emitted a tool call")
        return 0
    print("\nFAIL: no tool call emitted")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
