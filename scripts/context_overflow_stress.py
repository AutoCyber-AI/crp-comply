"""Context-overflow stress test — CRP Comply positioned bridge, REAL local LLM.

Verifies the fix in `crp_comply.agent.positioned.model_call_from_compliance_llm`
(context-budget guard via `crp.stl.guard_prompt_budget`) actually prevents overflow
against a real, small-context local model (LM Studio, 8192 tokens loaded) under the
four conditions the user asked about:
  1. Input   — a large tool result is forced into the CSO/state context.
  2. Output  — max_tokens is capped so response + prompt never exceed the window.
  3. Tool call — the tool positioning frame is built fresh each operation (bounded).
  4. Multi-turn / agentic — 6 turns on the SAME agent instance, CSO relayed forward,
     so accumulated state would overflow an un-guarded 8192-token window by turn 3-4.

Run:
    python scripts/context_overflow_stress.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from crp_comply.agent.orchestrator import ComplianceAgent
from crp_comply.agent.tools import Tool, ToolRegistry

LOCAL_BASE = "http://192.168.0.6:1234/v1"
LOCAL_MODEL = "meta-llama-3.1-8b-instruct"

# A deliberately large "regulation corpus hit" — simulates a real RAG tool result
# that, accumulated across turns via the CSO, would overflow an 8192-token window
# by turn 3-4 if the guard were not in place.
_BIG_CHUNK = (
    "Article {n}: This provision establishes detailed obligations regarding risk "
    "management, technical documentation, record-keeping, transparency, human "
    "oversight, accuracy, robustness and cybersecurity for the relevant AI system "
    "category, including conformity assessment procedures and post-market "
    "monitoring requirements that providers and deployers must satisfy. "
) * 40  # ~350 words per tool call


class _LocalLLM:
    def __init__(self) -> None:
        self._client = httpx.Client(timeout=180.0)
        self._ctx: int | None = None

    def context_window_size(self) -> int:
        if self._ctx is None:
            try:
                self._client.get(f"{LOCAL_BASE}/models", timeout=10)
                # LM Studio OpenAI-compatible /v1/models doesn't report ctx; use the
                # native endpoint the same way ComplianceLLM._probe_context_window does.
                r2 = self._client.get("http://192.168.0.6:1234/api/v0/models", timeout=10)
                data = r2.json().get("data", [])
                loaded = next((m for m in data if m.get("id") == LOCAL_MODEL and m.get("state") == "loaded"), None)
                self._ctx = int(loaded["loaded_context_length"]) if loaded else 8192
            except Exception:  # noqa: BLE001
                self._ctx = 8192
        return self._ctx

    default_max_tokens = 512

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        body = {"model": LOCAL_MODEL, "messages": messages, "temperature": 0.2,
                 "max_tokens": kwargs.get("max_tokens", 512)}
        r = self._client.post(f"{LOCAL_BASE}/chat/completions", json=body)
        r.raise_for_status()  # a real overflow => LM Studio returns 400 here
        return r.json()["choices"][0]["message"]["content"] or ""


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    counter = {"n": 0}

    def lookup(args: dict[str, Any]) -> dict[str, Any]:
        counter["n"] += 1
        return {"article": f"Art. {counter['n']}", "text": _BIG_CHUNK.format(n=counter["n"])}

    reg.register(Tool(
        name="query_regulation",
        description="Look up a regulation article in the indexed corpus.",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        handler=lookup,
    ))
    return reg


TURNS = [
    "What does the EU AI Act say about risk management systems?",
    "What about technical documentation requirements?",
    "And record-keeping obligations?",
    "What human oversight measures are required?",
    "Summarise the conformity assessment procedure.",
    "Given everything we've discussed, write a short compliance checklist.",
]


def main() -> int:
    try:
        httpx.get(f"{LOCAL_BASE}/models", timeout=6).raise_for_status()
    except Exception as exc:  # noqa: BLE001
        print(f"LM Studio unreachable: {exc}")
        return 2

    llm = _LocalLLM()
    print(f"Context window reported: {llm.context_window_size()} tokens\n")

    agent = ComplianceAgent(llm=llm, fabric=None, tools=_registry())
    overflow_errors = 0
    for i, task in enumerate(TURNS, 1):
        try:
            windows = 3 if i == len(TURNS) else 1  # stress continuation on the last turn
            result = agent.run_positioned(task, max_continuation_windows=windows)
            cso_facts = result.facts_stored
            print(f"turn {i}: state={result.state} tool_calls={result.tool_calls} "
                  f"facts_stored={cso_facts} continuation_windows={result.continuation_windows} "
                  f"answer_words={len(result.final_text.split())}")
        except httpx.HTTPStatusError as exc:
            overflow_errors += 1
            print(f"turn {i}: HTTP ERROR {exc.response.status_code} — {exc.response.text[:200]}")
        except Exception as exc:  # noqa: BLE001
            overflow_errors += 1
            print(f"turn {i}: EXCEPTION {type(exc).__name__}: {exc}")

    print(f"\n{'PASS' if overflow_errors == 0 else 'FAIL'}: "
          f"{len(TURNS) - overflow_errors}/{len(TURNS)} turns completed without an overflow error "
          f"(context window stayed at {llm.context_window_size()} tokens throughout).")
    return 0 if overflow_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
