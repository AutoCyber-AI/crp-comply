"""Deterministic evaluation harness for CRP Comply core primitives.

Round 18 goal: ≥20 YAML cases across EU AI Act, GDPR, ISO 42001, NIST AI RMF
with ≥95 % pass rate. All assertions are exact or bounded — no live LLM is
required, so this harness can run in CI.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..core import CRPComply

logger = logging.getLogger("crp_comply.eval")


@dataclass
class EvalResult:
    case_id: str
    passed: bool
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


def _load_cases(path: Path | str | None = None) -> dict[str, Any]:
    if path is None:
        path = Path(__file__).with_name("cases.yaml")
    with Path(path).open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _check_risk_level(actual: Any, expected: str) -> tuple[bool, str]:
    level = (
        actual.risk_level.value if hasattr(actual.risk_level, "value") else str(actual.risk_level)
    )
    if level != expected:
        return False, f"expected risk_level={expected}, got {level}"
    return True, ""


def _run_case(comply: CRPComply, case: dict[str, Any]) -> EvalResult:
    case_id = case["id"]
    task = case["task"]
    inputs = case.get("input", {})
    expect = case.get("expect", {})

    try:
        if task == "risk_assessment":
            actual = comply.assess_risk(**inputs)
            if expect.get("risk_level"):
                ok, msg = _check_risk_level(actual, expect["risk_level"])
                if not ok:
                    return EvalResult(
                        case_id,
                        False,
                        msg,
                        {
                            "risk_level": actual.risk_level.value
                            if hasattr(actual.risk_level, "value")
                            else str(actual.risk_level)
                        },
                    )
            if "min_mitigations" in expect:
                n = len(actual.mitigations)
                if n < expect["min_mitigations"]:
                    return EvalResult(
                        case_id,
                        False,
                        f"expected ≥{expect['min_mitigations']} mitigations, got {n}",
                    )
            if "min_residual_risks" in expect:
                n = len(actual.residual_risks)
                if n < expect["min_residual_risks"]:
                    return EvalResult(
                        case_id,
                        False,
                        f"expected ≥{expect['min_residual_risks']} residual risks, got {n}",
                    )
            return EvalResult(
                case_id,
                True,
                "",
                {
                    "risk_level": actual.risk_level.value
                    if hasattr(actual.risk_level, "value")
                    else str(actual.risk_level)
                },
            )

        if task == "compliance_report":
            actual = comply.compliance_report(**inputs)
            frameworks = set(actual.get("frameworks", {}).keys())
            for fw in expect.get("frameworks", []):
                if fw not in frameworks:
                    return EvalResult(case_id, False, f"expected framework {fw}, got {frameworks}")
            summary = actual.get("summary", {})
            score = summary.get("compliance_score", 0)
            if "min_score" in expect and score < expect["min_score"]:
                return EvalResult(case_id, False, f"score {score} < {expect['min_score']}")
            if "max_score" in expect and score > expect["max_score"]:
                return EvalResult(case_id, False, f"score {score} > {expect['max_score']}")
            total = summary.get("total_controls", 0)
            if "min_controls" in expect and total < expect["min_controls"]:
                return EvalResult(
                    case_id, False, f"total_controls {total} < {expect['min_controls']}"
                )
            return EvalResult(case_id, True, "", {"score": score, "frameworks": sorted(frameworks)})

        if task == "dpia":
            actual = comply.generate_dpia(**inputs)
            actual_dict = actual.to_dict() if hasattr(actual, "to_dict") else actual
            for key in ("dpia_required", "consultation_required"):
                if key in expect:
                    expected = expect[key]
                    got = actual_dict.get(key)
                    if bool(got) != bool(expected):
                        return EvalResult(case_id, False, f"expected {key}={expected}, got {got}")
            return EvalResult(
                case_id,
                True,
                "",
                {"consultation_required": bool(actual_dict.get("consultation_required"))},
            )

        if task == "technical_documentation":
            actual = comply.technical_documentation(**inputs)
            doc = actual.get("documentation", actual)
            keys = {str(k).lower() for k in (doc.keys() if isinstance(doc, dict) else [])}
            for section in expect.get("required_sections", []):
                if section.lower() not in keys:
                    return EvalResult(
                        case_id, False, f"missing section {section}; keys={sorted(keys)}"
                    )
            return EvalResult(case_id, True, "", {"sections": sorted(keys)})

        if task == "transparency_declaration":
            actual = comply.transparency_declaration(**inputs)
            declaration = actual.get("declaration", actual)
            keys = declaration.keys() if isinstance(declaration, dict) else []
            if "min_keys" in expect and len(list(keys)) < expect["min_keys"]:
                return EvalResult(
                    case_id,
                    False,
                    f"expected ≥{expect['min_keys']} declaration keys, got {len(list(keys))}",
                )
            return EvalResult(case_id, True, "", {"keys": len(list(keys))})

        return EvalResult(case_id, False, f"unknown task {task}")
    except Exception as exc:  # pragma: no cover — keep harness resilient
        logger.exception("case %s failed", case_id)
        return EvalResult(case_id, False, f"exception: {exc}")


def run_eval(
    cases_path: Path | str | None = None, comply: CRPComply | None = None
) -> dict[str, Any]:
    """Run all evaluation cases and return a summary dict."""
    data = _load_cases(cases_path)
    comply = comply or CRPComply()
    cases = data.get("cases", [])
    results: list[EvalResult] = []
    for case in cases:
        results.append(_run_case(comply, case))

    passed = sum(1 for r in results if r.passed)
    total = len(results)
    rate = passed / total if total else 0.0
    threshold = data.get("meta", {}).get("pass_threshold", 0.95)

    return {
        "meta": data.get("meta", {}),
        "threshold": threshold,
        "passed": passed,
        "total": total,
        "pass_rate": rate,
        "ok": rate >= threshold,
        "results": [
            {
                "case_id": r.case_id,
                "passed": r.passed,
                "message": r.message,
                "details": r.details,
            }
            for r in results
        ],
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="CRP Comply deterministic evaluation harness")
    parser.add_argument("--cases", default=None, help="Path to cases.yaml")
    parser.add_argument("--json", action="store_true", help="Emit JSON summary")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print per-case results")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    summary = run_eval(args.cases)

    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print(f"Eval: {summary['passed']}/{summary['total']} passed ({summary['pass_rate']:.1%})")
        if not summary["ok"]:
            print(f"Threshold: {summary['threshold']:.0%}")
        if args.verbose:
            for r in summary["results"]:
                status = "PASS" if r["passed"] else "FAIL"
                print(f"  [{status}] {r['case_id']}: {r['message'] or 'ok'}")

    return 0 if summary["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
