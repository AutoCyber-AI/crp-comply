#!/usr/bin/env python3
# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Latency benchmark for the crp-comply-search web-research sidecar.

Usage:
    export CRP_COMPLY_SEARCH_URL=http://127.0.0.1:8081
    export CRP_COMPLY_SEARCH_API_KEY=...
    python scripts/benchmark_web_research.py

The script runs each endpoint N times, prints per-call and aggregate latency,
and flags calls that miss the target budgets:
  * /search fast lane < 3 s
  * /research_agent deep research < 10 s
"""

from __future__ import annotations

import statistics
import time
from typing import Any, Callable

from crp_comply.sidecar_client import (
    SidecarConfig,
    SidecarError,
    research_agent,
    research_intelligent,
    search,
)

WARMUP = 1
RUNS = 3
BUDGETS = {
    "search": 3.0,
    "research_intelligent": 5.0,
    "research_agent": 10.0,
}


def _time_call(fn: Callable[[], dict[str, Any]]) -> tuple[float, dict[str, Any]]:
    t0 = time.perf_counter()
    try:
        result = fn()
    except SidecarError as exc:
        result = {"_error": str(exc)}
    elapsed = time.perf_counter() - t0
    return elapsed, result


def _benchmark(name: str, fn: Callable[[], dict[str, Any]], runs: int = RUNS) -> dict[str, Any]:
    print(f"\n=== {name} ({runs} runs) ===")
    latencies: list[float] = []
    for i in range(runs):
        elapsed, result = _time_call(fn)
        latencies.append(elapsed)
        status = "ok" if "_error" not in result else "error"
        marker = ""
        if status == "ok" and elapsed > BUDGETS.get(name, float("inf")):
            marker = " [OVER BUDGET]"
        print(f"  run {i + 1}: {elapsed:.2f}s {status}{marker}")
    return {
        "name": name,
        "runs": len(latencies),
        "min_s": min(latencies),
        "max_s": max(latencies),
        "mean_s": statistics.mean(latencies),
        "median_s": statistics.median(latencies),
        "p95_s": max(latencies),  # small N
        "budget_s": BUDGETS.get(name),
    }


def main() -> None:
    cfg = SidecarConfig.from_env()
    # Health check first.
    from crp_comply.sidecar_client import health

    try:
        health(cfg)
        print(f"sidecar healthy: {cfg.base_url}")
    except SidecarError as exc:
        print(f"sidecar health check failed: {exc}")
        raise SystemExit(1) from exc

    query = "EU AI Act high risk AI systems obligations 2025"

    # Warmup.
    print(f"warming up ({WARMUP} call)...")
    search(query, max_results=3, cfg=cfg)

    results = []
    results.append(
        _benchmark("search", lambda: search(query, max_results=5, cfg=cfg))
    )
    results.append(
        _benchmark(
            "research_intelligent",
            lambda: research_intelligent(
                goal=query, intent="regulation_text", max_results_per_query=4, cfg=cfg
            ),
        )
    )
    results.append(
        _benchmark(
            "research_agent",
            lambda: research_agent(
                goal=query, intent="regulation_text", max_results_per_query=4, cfg=cfg
            ),
        )
    )

    print("\n=== summary ===")
    for r in results:
        within = "yes" if r["max_s"] <= (r["budget_s"] or float("inf")) else "no"
        print(
            f"{r['name']:<22} mean={r['mean_s']:.2f}s "
            f"median={r['median_s']:.2f}s max={r['max_s']:.2f}s "
            f"budget={r['budget_s']}s within={within}"
        )


if __name__ == "__main__":
    main()
