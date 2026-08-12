"""Evaluation harness tests — Round 18."""

from __future__ import annotations

from crp_comply.core import CRPComply
from crp_comply.eval.runner import run_eval


def test_eval_suite_reaches_threshold():
    summary = run_eval(comply=CRPComply())
    assert summary["total"] >= 20, f"expected ≥20 cases, got {summary['total']}"
    assert summary["ok"], (
        f"eval pass rate {summary['pass_rate']:.1%} below threshold {summary['threshold']:.0%}"
    )
    for r in summary["results"]:
        assert r["passed"], f"case {r['case_id']}: {r['message']}"


def test_eval_failure_details():
    summary = run_eval(comply=CRPComply())
    assert summary["passed"] == summary["total"]
    assert all("case_id" in r for r in summary["results"])


def test_compliance_report_covers_eu_ai_act():
    summary = run_eval(comply=CRPComply())
    case = next(r for r in summary["results"] if r["case_id"] == "report-includes-eu-ai-act")
    assert case["passed"]


def test_compliance_report_covers_iso42001():
    summary = run_eval(comply=CRPComply())
    case = next(r for r in summary["results"] if r["case_id"] == "report-includes-iso42001")
    assert case["passed"]
