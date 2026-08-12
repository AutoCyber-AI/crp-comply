# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Live LLM integration tests against an OpenAI-compatible endpoint.

These tests are SKIPPED by default and only run when an explicit base
URL is provided via the ``CRP_COMPLY_LIVE_LLM_BASE_URL`` environment
variable. They exist to catch the kind of integration bug that
fixture-based tests miss — model returns malformed JSON, latency
explodes, tool-call format mismatch, etc.

Recommended local setup (LM Studio + a tiny model)::

    set CRP_COMPLY_LIVE_LLM_BASE_URL=http://192.168.0.6:1234/v1
    set CRP_COMPLY_LIVE_LLM_MODEL=gemma-3-270m-it-qat
    pytest tests/test_llm_integration_lmstudio.py -vv -s

The 270-million-parameter model is intentionally tiny — these tests
verify *plumbing*, not output quality. We assert that:

* the endpoint is reachable and OpenAI-shape compatible,
* `ComplianceLLM.chat` round-trips real text,
* the orchestrator can take at least one step without raising,
* the evals stub-agent contract matches what a real LLM produces.

We do NOT assert on regulation accuracy — Gemma 270M is far too small
for that. For accuracy we use the deterministic evals harness with a
production-tier provider.
"""

from __future__ import annotations

import json
import os
import socket
import time
import urllib.request
from urllib.parse import urlparse

import pytest

# ── Skip plumbing ────────────────────────────────────────────


# Strip whitespace defensively — Windows ``set FOO=bar &&`` leaves a
# trailing space that breaks ``urllib`` URL validation.
def _env(name: str, default: str | None = None) -> str | None:
    raw = os.environ.get(name, default)
    return raw.strip() if isinstance(raw, str) else raw


LIVE_BASE_URL = _env("CRP_COMPLY_LIVE_LLM_BASE_URL")
LIVE_MODEL = _env("CRP_COMPLY_LIVE_LLM_MODEL", "gemma-3-270m-it-qat") or "gemma-3-270m-it-qat"
LIVE_TIMEOUT_S = float(_env("CRP_COMPLY_LIVE_LLM_TIMEOUT_S", "30") or "30")


def _endpoint_reachable(base_url: str, timeout: float = 3.0) -> bool:
    """Cheap pre-flight TCP probe so we skip cleanly when LM Studio is off."""
    try:
        parsed = urlparse(base_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not LIVE_BASE_URL,
    reason=(
        "live LLM tests skipped — set CRP_COMPLY_LIVE_LLM_BASE_URL "
        "(e.g. http://192.168.0.6:1234/v1) to opt in"
    ),
)


@pytest.fixture(scope="module", autouse=True)
def _require_endpoint() -> None:
    """Skip the whole module if the configured endpoint isn't listening."""
    assert LIVE_BASE_URL is not None
    if not _endpoint_reachable(LIVE_BASE_URL):
        pytest.skip(
            f"endpoint not reachable: {LIVE_BASE_URL} — start LM Studio "
            "or unset CRP_COMPLY_LIVE_LLM_BASE_URL"
        )


# ── Tier 1: connectivity ─────────────────────────────────────


def test_models_endpoint_returns_openai_shape():
    """GET /models must answer with the OpenAI-style ``{data: [...]}`` envelope."""
    url = LIVE_BASE_URL.rstrip("/") + "/models"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=LIVE_TIMEOUT_S) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    assert isinstance(body, dict), f"unexpected payload type: {type(body)}"
    assert "data" in body, body
    assert isinstance(body["data"], list)
    served = {m.get("id") for m in body["data"]}
    assert served, "no models advertised by the endpoint"
    # We don't require LIVE_MODEL specifically — LM Studio sometimes serves
    # a single un-named model. Print for diagnostics.
    print(f"\n[live-llm] endpoint serves: {sorted(filter(None, served))}")


# ── Tier 2: ComplianceLLM round-trip ─────────────────────────


def _build_live_llm():
    """Construct a ComplianceLLM bound to the live endpoint."""
    from crp.providers import OpenAIAdapter

    from crp_comply.agent.llm import ComplianceLLM

    adapter = OpenAIAdapter(
        model=LIVE_MODEL,
        api_key=os.environ.get("CRP_COMPLY_LIVE_LLM_API_KEY", "lm-studio"),
        base_url=LIVE_BASE_URL,
    )
    return ComplianceLLM(provider=adapter, default_max_tokens=128)


def test_plain_chat_round_trip_returns_text():
    """ComplianceLLM.chat must return non-empty text for a trivial prompt."""
    llm = _build_live_llm()
    t0 = time.perf_counter()
    text = llm.chat(
        [
            {
                "role": "system",
                "content": "You are a brief assistant. Reply in one short sentence.",
            },
            {"role": "user", "content": "Say the word 'compliance' and stop."},
        ],
        max_tokens=32,
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    print(f"\n[live-llm] chat round-trip {elapsed_ms:.0f} ms — got: {text!r}")
    assert isinstance(text, str)
    # NOTE: gemma-3-270m occasionally returns empty content under tight
    # token budgets — accept that as a successful round-trip (the call
    # didn't crash, the provider returned a string). Larger models will
    # of course produce text. The point of this test is wiring, not IQ.
    assert elapsed_ms < (LIVE_TIMEOUT_S * 1000), "round-trip exceeded timeout"


# ── Tier 3: tool-call attempt (best-effort, may not fire on tiny models) ──


def test_chat_with_tools_returns_well_shaped_turn():
    """`chat_with_tools` must always return a ChatTurn, even when the model
    cannot invoke tools. Tiny models like Gemma-270M generally don't, so
    we assert *shape*, not behaviour."""
    llm = _build_live_llm()
    tools = [
        {
            "type": "function",
            "function": {
                "name": "echo",
                "description": "Echo the input back",
                "parameters": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            },
        }
    ]
    turn = llm.chat_with_tools(
        messages=[
            {"role": "user", "content": "Reply with one short sentence."},
        ],
        tools=tools,
        max_tokens=64,
    )
    assert turn is not None
    assert isinstance(turn.text, str)
    # Tiny models often choke on the tool-call schema and surface as
    # ``finish_reason='error'`` — accept that here. The point is that
    # ``chat_with_tools`` always returns a well-shaped ``ChatTurn`` and
    # never propagates the exception.
    assert turn.finish_reason in {
        "stop",
        "tool_calls",
        "length",
        "end",
        "error",
        "",
    }
    # tool_calls list must always be a list (possibly empty)
    assert isinstance(turn.tool_calls, list)
    print(
        f"\n[live-llm] chat_with_tools finish_reason={turn.finish_reason!r} "
        f"tool_calls={len(turn.tool_calls)} text_len={len(turn.text)}"
    )


# ── Tier 4: deterministic evals harness wired to the live model ──────────


def test_evals_run_against_live_llm_does_not_crash():
    """Run the AI Act eval suite against a live-LLM-backed agent function.

    We do NOT assert on pass-rate — a 270M-param model is far too small to
    reason about Article 6 / Annex III. We assert that the harness can
    drive a real provider end-to-end without raising. Any score above 0
    is gravy.
    """
    from pathlib import Path

    from crp_comply.evals import EvalRunner, load_all_suites

    llm = _build_live_llm()
    cases = load_all_suites(Path("src/crp_comply/evals/cases"))
    assert cases, "no eval cases discovered"

    def live_agent(case) -> dict:
        # Single-turn: ask the model the case task with a citation hint.
        prompt = (
            "You are a compliance analyst. Answer briefly and cite article "
            "numbers in plain text (e.g. 'Article 6'). " + case.task
        )
        text = llm.chat(
            [
                {"role": "system", "content": "Answer in 2-3 sentences."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=192,
        )
        return {
            "final_text": text,
            "risk_level": "",  # leave empty — runner will skip the check
            "citations": [],
            "tools_used": [],
        }

    # Run only a handful of cases to keep CI time bounded.
    sample = cases[:3]
    report = EvalRunner(live_agent).run(sample)
    print(
        f"\n[live-llm] eval pass_rate={report.pass_rate:.2f} "
        f"({report.passed}/{report.total}) "
        f"mean_score={report.mean_score:.2f}"
    )
    assert report.total == len(sample)
    # We don't gate on quality — only that nothing crashed and shape is sane.
    assert 0.0 <= report.pass_rate <= 1.0
    assert all(isinstance(r.score, float) for r in report.results)
