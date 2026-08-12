# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""CLI: ``python -m crp_comply.evals run --suite <dir> [--tags ...]``.

By default the CLI uses a stub agent that echoes the case's own
expectations — useful for smoke-testing the harness. Real runs inject
``--agent crp_comply.evals.agents:live`` or similar.
"""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import sys
from pathlib import Path
from typing import Any, Callable

from .cases import EvalCase, filter_suite, load_suite
from .runner import AgentFn, EvalRunner

log = logging.getLogger("crp_comply.evals.cli")


def _stub_agent(case: EvalCase) -> dict[str, Any]:
    """Echo-back agent used for harness self-tests.

    Trivially reflects every expectation so every case passes. Handy to
    verify scoring logic independently of real LLM wiring.
    """
    return {
        "final_text": " ".join(
            [case.task] + case.must_contain + [f"see {c}" for c in case.expected_citations]
        ),
        "risk_level": case.expected_risk_level,
        "citations": list(case.expected_citations),
        "tools_used": list(case.expected_tools),
    }


def _resolve_agent(spec: str | None) -> AgentFn:
    if not spec or spec == "stub":
        return _stub_agent
    if ":" not in spec:
        raise SystemExit(f"--agent must be 'module.path:callable' (got {spec!r})")
    mod_path, name = spec.split(":", 1)
    mod = importlib.import_module(mod_path)
    fn: Callable[..., Any] = getattr(mod, name)
    return fn  # type: ignore[return-value]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="crp_comply.evals")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="Run an eval suite")
    p_run.add_argument("--suite", required=True, type=Path)
    p_run.add_argument("--agent", default="stub", help="'stub' (default) or 'module.path:callable'")
    p_run.add_argument("--tags", nargs="*", default=None)
    p_run.add_argument("--out", type=Path, default=None, help="Optional path to write JSON report")
    p_run.add_argument(
        "--threshold",
        type=float,
        default=1.0,
        help="Pass-threshold for composite score (default 1.0)",
    )

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.cmd != "run":
        parser.error(f"unknown command {args.cmd}")

    cases = load_suite(args.suite)
    cases = filter_suite(cases, tags=args.tags)
    if not cases:
        print("no cases matched filters", file=sys.stderr)
        return 2

    runner = EvalRunner(_resolve_agent(args.agent), pass_threshold=args.threshold)
    report = runner.run(cases)

    summary = report.summary()
    print(
        json.dumps(
            {
                "total": summary["total"],
                "passed": summary["passed"],
                "failed": summary["failed"],
                "pass_rate": summary["pass_rate"],
                "mean_score": summary["mean_score"],
                "total_cost_usd": summary["total_cost_usd"],
                "duration_ms": summary["duration_ms"],
            },
            indent=2,
        )
    )

    if args.out:
        report.write_json(args.out)
        print(f"wrote full report to {args.out}", file=sys.stderr)

    return 0 if report.pass_rate >= 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
