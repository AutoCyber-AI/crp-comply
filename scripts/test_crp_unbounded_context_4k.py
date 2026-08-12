# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Reproduce and verify CRP unbounded-context behaviour on a 4K model.

Run with LM Studio loaded at 4096 tokens and ``n_parallel=1`` (or any
parallel count; the script reports the per-slot budget). It builds a
long message history, runs CRP compaction, and optionally dispatches to
the local LLM to prove the prompt fits.

Usage (from repo root) with miniforge / crp-comply Python:
    python scripts/test_crp_unbounded_context_4k.py

Environment:
    CRP_COMPLY_WORKER_CONTEXT_TOKENS  - override detected context window
    CRP_COMPLY_WORKER_N_PARALLEL      - parallel slot count if not auto-detected
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import httpx

# Ensure repo source is on path when run directly.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from crp_comply.agent.crp_integration import compact_messages_for_budget


def _probe_lmstudio() -> tuple[int, int, str | None]:
    """Return (loaded_context_length, detected_n_parallel, first_model_id)."""
    try:
        resp = httpx.get("http://127.0.0.1:1234/api/v0/models", timeout=5.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: could not probe LM Studio /api/v0/models: {exc}")
        return 4096, 1, None

    import re
    from collections import Counter

    loaded_llms = [
        it
        for it in data.get("data", [])
        if isinstance(it, dict)
        and it.get("state") == "loaded"
        and it.get("type") == "llm"
    ]
    base_counts = Counter(
        re.sub(r":\d+$", "", str(it.get("id", ""))) for it in loaded_llms
    )
    n_parallel = max(base_counts.values()) if base_counts else 1

    ctx = None
    first_model: str | None = None
    for it in data.get("data", []):
        if isinstance(it, dict) and it.get("loaded_context_length"):
            ctx = int(it["loaded_context_length"])
        if first_model is None and isinstance(it, dict) and it.get("id"):
            mid = str(it["id"])
            if ":" not in mid:
                first_model = mid
    if ctx is None:
        ctx = int(os.environ.get("CRP_COMPLY_WORKER_CONTEXT_TOKENS", "4096"))
    return ctx, n_parallel, first_model


def _build_messages() -> list[dict[str, Any]]:
    """Build a realistic compliance-agent message list that exceeds a 4K
    budget unless CRP folding is applied."""
    system_prompt = (
        "You are a senior AI-compliance analyst (EU AI Act, GDPR, NIS2, "
        "ISO 42001, NIST AI RMF). METHOD — follow this loop on EVERY user "
        "question: 1. Call `query_regulation` AT LEAST ONCE before producing "
        "any final answer. Use a focused natural-language query. "
        "2. If the first call returns 0 hits, retry with a different phrasing. "
        "3. Only call `request_clarification` when genuinely missing facts. "
        "4. Use `web_search` for recent events. "
        "5. WIDEN the evidence base — do NOT stop after a single call. "
        "ANSWER QUALITY: produce a comprehensive, structured answer. Cite "
        "EVERY substantive claim with the corresponding chunk_id. Do not "
        "invent tool names or chunk_ids."
    )
    primer = "\n".join(
        f"[corpus primer {i}] Article {i}: providers of high-risk AI systems "
        "shall ensure that their systems comply with the requirements laid down "
        "in this Chapter. " * 5
        for i in range(6)
    )
    history: list[dict[str, Any]] = []
    for i in range(8):
        history.append(
            {
                "role": "assistant",
                "content": f"Turn {i}: here is a moderately long assistant response "
                "exploring compliance obligations and citing retrieved chunks. " * 4,
            }
        )
        history.append(
            {
                "role": "user",
                "content": f"Follow-up question number {i} about high-risk systems.",
            }
        )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "system", "name": "crp_session_context", "content": primer},
        *history,
        {"role": "user", "content": "Summarise the EU AI Act obligations for high-risk AI providers."},
    ]


def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
    return sum(int(len(m.get("content", "")) / 2.5) for m in messages)


def _send_to_lmstudio(
    messages: list[dict[str, Any]], max_tokens: int, model: str | None
) -> dict[str, Any]:
    payload = {
        "model": model or "auto",
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }
    resp = httpx.post(
        "http://127.0.0.1:1234/v1/chat/completions",
        json=payload,
        timeout=120.0,
    )
    resp.raise_for_status()
    return resp.json()


def main() -> int:
    raw_ctx, detected_n_parallel, first_model = _probe_lmstudio()
    n_parallel_env = os.environ.get("CRP_COMPLY_WORKER_N_PARALLEL")
    n_parallel = int(n_parallel_env) if n_parallel_env else detected_n_parallel
    per_slot_ctx = max(1024, raw_ctx // max(1, n_parallel))

    print(f"LM Studio raw loaded_context_length: {raw_ctx}")
    print(f"Detected n_parallel: {detected_n_parallel}")
    print(f"Effective per-slot context: {per_slot_ctx}")

    messages = _build_messages()
    before_tokens = _estimate_tokens(messages)
    print(f"\nRaw message list: {len(messages)} messages, ~{before_tokens} tokens")

    # Reserve output + tool-schema headroom as the orchestrator does.
    output_reserve = 384 if per_slot_ctx <= 4096 else 768
    tool_schema_tokens = 1100
    reserve = output_reserve + tool_schema_tokens + int(0.15 * per_slot_ctx)
    budget = max(1024, per_slot_ctx - reserve)
    print(f"Reserve: {reserve}, CRP compaction budget: {budget}")

    compacted, stats = compact_messages_for_budget(
        messages, budget_tokens=budget, chars_per_token=2.5
    )
    after_tokens = _estimate_tokens(compacted)
    print(f"Compacted: {len(compacted)} messages, ~{after_tokens} tokens")
    print(f"Compact stats: {json.dumps(stats, indent=2)}")

    if after_tokens > per_slot_ctx:
        print("\nFAIL: compacted prompt still exceeds per-slot context")
        return 1

    print("\nSending compacted prompt to LM Studio...")
    print(f"Model identifier: {first_model or 'auto'}")
    try:
        result = _send_to_lmstudio(compacted, max_tokens=output_reserve, model=first_model)
        finish = result["choices"][0].get("finish_reason", "unknown")
        content_preview = result["choices"][0]["message"].get("content", "")[:200]
        print(f"HTTP 200, finish_reason={finish}")
        print(f"Content preview: {content_preview!r}")
        print("\nPASS: 4K CRP unbounded-context path works")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"\nFAIL: LM Studio rejected the prompt: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
