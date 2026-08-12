"""Concurrent loop budget soak test (PHASE_7 §21 7.12).

The full one-hour soak is run by ops, not CI. This pragmatic version
spins up 50 concurrent meters driving stubbed work and asserts:

* No shared-state leakage (each meter ends with its own counter values).
* No spurious BudgetExceeded under nominal usage.
* No deadlocks (test completes within 5 s).

Marked ``slow`` so plain ``pytest`` still runs it (same convention as
the rest of the suite); use ``pytest -m "not slow"`` to skip.
"""

from __future__ import annotations

import asyncio

import pytest

from crp_comply.agent.loop_budget import LoopBudget, LoopBudgetMeter


@pytest.mark.slow
@pytest.mark.asyncio
async def test_50_concurrent_meters_isolated() -> None:
    budget = LoopBudget(
        max_steps=20,
        max_tokens=10_000,
        max_wall_clock_s=10.0,
        max_clarifiers=6,
        max_plan_revisions=3,
    )

    async def one_run(idx: int) -> dict:
        meter = LoopBudgetMeter(budget=budget)
        # 10 fake "steps" with tokens, interleaved with cooperation points.
        for _ in range(10):
            meter.record_step()
            meter.record_tokens(50)
            await asyncio.sleep(0)
        return meter.usage()

    results = await asyncio.wait_for(
        asyncio.gather(*(one_run(i) for i in range(50))),
        timeout=5.0,
    )

    assert len(results) == 50
    for u in results:
        # Each meter must reflect its own work — not aggregated across
        # tasks, which would prove a shared-mutable bug.
        assert u["steps"] == 10
        assert u["tokens"] == 500
        assert u["clarifiers"] == 0
        assert u["plan_revisions"] == 0
