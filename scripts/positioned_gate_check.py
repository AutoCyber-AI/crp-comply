"""Round 1 gate check: CRP Comply's positioned bridge against a REAL LLM.

Not a pytest test (network-dependent) — a manual gate-check script per
CRPV5_UPGRADE_REPORT.md Round 1: "one end-to-end compliance question answered via
the positioned loop on the local 8B ... event stream captured as audit."

Run:
    python scripts/positioned_gate_check.py
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


class _LocalLLM:
    def __init__(self) -> None:
        self._client = httpx.Client(timeout=180.0)

    def chat(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        body = {"model": LOCAL_MODEL, "messages": messages, "temperature": 0.2, "max_tokens": 400}
        r = self._client.post(f"{LOCAL_BASE}/chat/completions", json=body)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"] or ""


def _registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(Tool(
        name="classify_ai_act_risk",
        description="Deterministically classify an AI system's EU AI Act risk tier.",
        parameters={"type": "object", "properties": {"system": {"type": "string"}}, "required": ["system"]},
        handler=lambda args: {
            "system": args.get("system"),
            "risk_tier": "high-risk",
            "article": "Annex III(4)(a) — employment/worker management",
        },
    ))
    return reg


def main() -> int:
    try:
        httpx.get(f"{LOCAL_BASE}/models", timeout=6).raise_for_status()
    except Exception as exc:  # noqa: BLE001
        print(f"LM Studio unreachable: {exc}")
        return 2

    agent = ComplianceAgent(llm=_LocalLLM(), fabric=None, tools=_registry())
    result = agent.run_positioned(
        "Is an automated CV-screening system a high-risk AI system under the EU AI Act?"
    )
    print(f"state           : {result.state}")
    print(f"tool_calls      : {result.tool_calls}")
    print(f"facts_stored    : {result.facts_stored}")
    print(f"operation_plan  : {result.enforcer_state.get('crp_agent_operation_plan')}")
    print(f"final_text      :\n{result.final_text}\n")
    ok = result.state == "done" and result.tool_calls >= 1 and result.facts_stored >= 1
    print("GATE " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
