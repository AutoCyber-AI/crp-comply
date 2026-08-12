# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Evaluation harness for the compliance agent.

Closes DESIGN_GAP_ASSESSMENT §12 (no eval suite) and REMAINING_WORK B3
(evals are launch-blocking before recipes).

The harness is deliberately small and dependency-free:

* A *case* is a YAML file with a ``task`` prompt, expected risk level,
  expected citations (article numbers), and a list of keywords the final
  narrative must / must not contain.
* A *suite* is a directory of cases.
* :class:`EvalRunner` runs each case against an agent factory (or any
  callable that returns ``{"final_text", "risk_level", "citations"}``)
  and computes deterministic metrics. No LLM-as-judge — every check is
  a keyword or literal match so scores are reproducible.

Typical usage::

    from crp_comply.evals import EvalRunner, load_suite

    cases = load_suite(Path("src/crp_comply/evals/cases/ai_act_basic"))
    runner = EvalRunner(agent_fn=my_agent_callable)
    report = runner.run(cases)
    print(report.summary())

The runner is also exposed via a CLI (see :mod:`crp_comply.evals.cli`).
"""

from .cases import EvalCase, EvalResult, filter_suite, load_all_suites, load_case, load_suite
from .runner import EvalReport, EvalRunner

__all__ = [
    "EvalCase",
    "EvalResult",
    "EvalRunner",
    "EvalReport",
    "filter_suite",
    "load_case",
    "load_suite",
    "load_all_suites",
]
