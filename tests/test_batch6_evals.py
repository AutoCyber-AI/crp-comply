# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""BATCH 6 — deterministic eval harness."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crp_comply.evals import EvalCase, EvalRunner, load_suite
from crp_comply.evals.cases import filter_suite


# ── Loader ─────────────────────────────────────────────────

SUITE_DIR = Path("src/crp_comply/evals/cases/ai_act_basic")


def test_load_suite_reads_seed_cases():
    cases = load_suite(SUITE_DIR)
    ids = {c.case_id for c in cases}
    assert "ai_act_cv_screening_high_risk" in ids
    assert "ai_act_social_scoring_prohibited" in ids
    assert "ai_act_chatbot_limited_risk" in ids
    assert len(cases) >= 3


def test_filter_suite_by_tag():
    cases = load_suite(SUITE_DIR)
    only_prohibited = filter_suite(cases, tags=["prohibited"])
    assert len(only_prohibited) == 1
    assert only_prohibited[0].case_id == "ai_act_social_scoring_prohibited"


def test_filter_suite_empty_tags_returns_all():
    cases = load_suite(SUITE_DIR)
    assert len(filter_suite(cases, tags=None)) == len(cases)


# ── Scoring ────────────────────────────────────────────────


def _stub(case: EvalCase) -> dict:
    return {
        "final_text": (
            case.task
            + " "
            + " ".join(case.must_contain)
            + " "
            + " ".join(f"see {c}" for c in case.expected_citations)
        ),
        "risk_level": case.expected_risk_level,
        "citations": list(case.expected_citations),
        "tools_used": list(case.expected_tools),
    }


def test_runner_passes_with_perfect_stub():
    cases = load_suite(SUITE_DIR)
    report = EvalRunner(_stub).run(cases)
    assert report.total == len(cases)
    assert report.passed == report.total
    assert report.pass_rate == 1.0
    assert report.mean_score == 1.0


def test_runner_fails_on_wrong_risk_level():
    cases = load_suite(SUITE_DIR)
    target = next(c for c in cases if c.case_id == "ai_act_cv_screening_high_risk")

    def bad_agent(case: EvalCase) -> dict:
        out = _stub(case)
        out["risk_level"] = "limited"  # wrong
        return out

    report = EvalRunner(bad_agent).run([target])
    assert report.passed == 0
    result = report.results[0]
    assert result.checks.get("risk_level") is False
    assert any("risk_level" in e for e in result.errors)


def test_runner_fails_on_missing_citation():
    cases = load_suite(SUITE_DIR)
    target = next(c for c in cases if c.case_id == "ai_act_cv_screening_high_risk")

    def no_cite(case: EvalCase) -> dict:
        out = _stub(case)
        out["final_text"] = "some generic prose with no article references"
        out["citations"] = []
        return out

    report = EvalRunner(no_cite).run([target])
    assert report.passed == 0
    assert report.results[0].checks.get("citations") is False


def test_runner_fails_on_forbidden_keyword():
    target = EvalCase(
        case_id="forbidden_kw",
        task="t",
        must_not_contain=["banned-phrase"],
    )

    def leaky(case: EvalCase) -> dict:
        return {"final_text": "This output contains a banned-phrase oops."}

    report = EvalRunner(leaky).run([target])
    assert report.passed == 0
    assert report.results[0].checks.get("must_not_contain") is False


def test_runner_captures_tokens_and_cost():
    case = EvalCase(case_id="tc", task="t", must_contain=["ok"])

    def agent(_: EvalCase) -> dict:
        return {
            "final_text": "ok done",
            "tokens_in": 100,
            "tokens_out": 50,
            "cost_usd": 0.0012,
        }

    report = EvalRunner(agent).run([case])
    r = report.results[0]
    assert r.passed is True
    assert r.tokens_in == 100
    assert r.tokens_out == 50
    assert r.cost_usd == pytest.approx(0.0012)
    assert report.total_cost_usd == pytest.approx(0.0012)


def test_runner_handles_agent_exception():
    case = EvalCase(case_id="boom", task="t")

    def agent(_: EvalCase) -> dict:
        raise RuntimeError("kaboom")

    report = EvalRunner(agent).run([case])
    r = report.results[0]
    assert r.passed is False
    assert r.score == 0.0
    assert any("RuntimeError" in e for e in r.errors)


def test_report_write_json_roundtrip(tmp_path):
    case = EvalCase(case_id="rt", task="t", must_contain=["hello"])

    def agent(_: EvalCase) -> dict:
        return {"final_text": "hello world"}

    report = EvalRunner(agent).run([case])
    out = report.write_json(tmp_path / "report.json")
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["total"] == 1
    assert data["passed"] == 1
    assert data["cases"][0]["case_id"] == "rt"


def test_cli_runs_stub_agent_end_to_end(tmp_path, capsys):
    from crp_comply.evals.cli import main

    out_path = tmp_path / "r.json"
    rc = main(
        [
            "run",
            "--suite",
            str(SUITE_DIR),
            "--agent",
            "stub",
            "--out",
            str(out_path),
        ]
    )
    assert rc == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["total"] >= 3
    assert payload["pass_rate"] == 1.0


def test_cli_threshold_below_one_still_passes_perfect_run(tmp_path):
    from crp_comply.evals.cli import main

    rc = main(
        [
            "run",
            "--suite",
            str(SUITE_DIR),
            "--agent",
            "stub",
            "--threshold",
            "0.8",
        ]
    )
    assert rc == 0
