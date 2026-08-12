# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Regression tests for the onboarding-extract event-loop deadlock fix.

``POST /api/v1/onboarding/extract`` calls ``ComplianceLLM.chat()``, which is
synchronous. For the ``local_worker`` provider that call bridges to the SDK
WebSocket relay via ``WorkerRegistry.dispatch_from_sync``, which schedules a
coroutine on the *calling* event loop and then blocks the calling thread
waiting for it. If ``extract_profile`` called ``llm.chat()`` directly (no
``asyncio.to_thread``), the scheduled coroutine could never run because the
one thread that could run it is the one blocked waiting on it — a deadlock
that freezes the *entire* single-process app (every other route, every other
user) until the internal timeout fires, surfacing as Cloudflare 524s across
completely unrelated endpoints. See crp-comply CRPV5_UPGRADE_REPORT.md and
the corresponding fix in the CRP protocol's own ``guard_prompt_budget`` work.

These tests don't need a real WebSocket/worker — they only need to prove the
route offloads the blocking call so the event loop stays free to run other
coroutines while it's in flight.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest

from crp_comply.api.onboarding import OnboardingExtractRequest, extract_profile
from crp_comply.api.auth import Tier


class _SlowBlockingLLM:
    """Stand-in for ComplianceLLM whose .chat() blocks synchronously.

    Mirrors what WorkerAdapter.generate_chat() looks like from the caller's
    side when it bridges to dispatch_from_sync: a plain blocking call with
    no awaits, taking real wall-clock time.
    """

    def __init__(self, delay: float, result: str | None = None, error: Exception | None = None):
        self.delay = delay
        self.result = result
        self.error = error

    def chat(self, messages, **kwargs):
        time.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self.result


@pytest.mark.asyncio
async def test_extract_profile_does_not_block_event_loop():
    """A concurrent task must keep making progress while llm.chat() blocks.

    Runs extract_profile() concurrently (asyncio.gather) with a canary
    coroutine that only advances via real await points. If extract_profile
    calls llm.chat() directly with no ``await`` in front of it (the bug),
    the canary can never be scheduled until extract_profile's synchronous
    body finishes, so total wall-clock time is close to the *sum* of both
    durations (serial). If the blocking call is correctly offloaded via
    ``asyncio.to_thread``, the event loop is free to run the canary while
    the thread executes, so total wall-clock time is close to the *max* of
    both durations (concurrent) — this is what distinguishes the fix from
    the bug; merely awaiting the canary *after* extract_profile returns
    would pass in both cases and prove nothing.
    """
    slow_llm = _SlowBlockingLLM(
        delay=0.3,
        result='{"suggested_profile": {"org_name": "Acme"}, "rationale": "ok", '
        '"confidence": 0.8, "clarifying_question": "Where do you operate?", '
        '"next_fields": ["jurisdictions"]}',
    )

    ticks = 0

    async def _canary():
        nonlocal ticks
        for _ in range(20):
            await asyncio.sleep(0.02)  # 20 * 0.02s = 0.4s total
            ticks += 1

    req = OnboardingExtractRequest(text="We are a 25-person Berlin startup building a chatbot.")

    with patch("crp_comply.agent.llm.ComplianceLLM.for_user", return_value=slow_llm):
        start = time.monotonic()
        result, _ = await asyncio.gather(
            extract_profile(req=req, user="test-user", tier=Tier.STARTER, _meter=None),
            _canary(),
        )
        elapsed = time.monotonic() - start

    assert result.suggested_profile.get("org_name") == "Acme"
    assert ticks == 20
    # Concurrent (fixed): elapsed ~= max(0.3, 0.4) = 0.4s (plus small thread-pool
    # scheduling overhead). Serial (buggy, no to_thread): elapsed ~= 0.3 + 0.4 =
    # 0.7s+. The 0.65s cutoff sits clearly between the two, measured empirically.
    assert elapsed < 0.65, (
        f"event loop appears blocked during llm.chat() (elapsed={elapsed:.3f}s, "
        "expected ~0.4s if concurrent, ~0.7s+ if the event loop was blocked)"
    )


@pytest.mark.asyncio
async def test_extract_profile_llm_failure_returns_503():
    from fastapi import HTTPException

    failing_llm = _SlowBlockingLLM(delay=0.01, error=RuntimeError("worker offline"))
    req = OnboardingExtractRequest(text="We are a 25-person Berlin startup building a chatbot.")

    with patch("crp_comply.agent.llm.ComplianceLLM.for_user", return_value=failing_llm):
        with pytest.raises(HTTPException) as exc_info:
            await extract_profile(req=req, user="test-user", tier=Tier.STARTER, _meter=None)

    assert exc_info.value.status_code == 503
