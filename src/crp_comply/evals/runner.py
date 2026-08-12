# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Deterministic eval runner.

The runner is model-free: it drives a caller-supplied ``agent_fn`` and
scores the returned payload against the expectations on each
:class:`EvalCase`. All checks are literal keyword / substring matches
so runs are bit-reproducible — no LLM-as-judge magic.

``agent_fn`` contract::

    def agent_fn(case: EvalCase) -> dict:
        return {
            "final_text": "...",          # required
            "risk_level": "high",          # optional; used if case has one
            "citations": ["Article 6"],    # optional; substrings allowed
            "tools_used": ["classify..."], # optional
            "tokens_in": 1234,              # optional
            "tokens_out": 567,              # optional
            "cost_usd": 0.003,              # optional
        }
"""

from __future__ import annotations

import json
import logging
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from .cases import EvalCase, EvalResult

log = logging.getLogger("crp_comply.evals.runner")

AgentFn = Callable[[EvalCase], dict[str, Any]]


# Relative weights for the composite score.
_WEIGHTS: dict[str, float] = {
    "risk_level": 1.0,
    "citations": 1.0,
    "must_contain": 1.0,
    "must_not_contain": 0.5,
    "tools": 0.5,
}


def _score_case(case: EvalCase, result: dict[str, Any]) -> tuple[dict[str, bool], float, list[str]]:
    """Return (per-check booleans, weighted score ∈ [0,1], errors)."""
    errors: list[str] = []
    checks: dict[str, bool] = {}
    final_text = str(result.get("final_text", "") or "")
    ft_low = final_text.lower()

    # Risk level
    if case.expected_risk_level:
        got = str(result.get("risk_level", "") or "").lower()
        ok = got == case.expected_risk_level.lower()
        checks["risk_level"] = ok
        if not ok:
            errors.append(f"risk_level expected='{case.expected_risk_level}' got='{got}'")

    # Citations — substring match against final_text OR citations list
    if case.expected_citations:
        cites = " ".join(str(c) for c in (result.get("citations") or []))
        haystack = (final_text + " " + cites).lower()
        missing = [c for c in case.expected_citations if c.lower() not in haystack]
        ok = not missing
        checks["citations"] = ok
        if not ok:
            errors.append(f"missing citations: {missing}")

    # Must-contain keywords
    if case.must_contain:
        missing = [kw for kw in case.must_contain if kw.lower() not in ft_low]
        ok = not missing
        checks["must_contain"] = ok
        if not ok:
            errors.append(f"missing required keywords: {missing}")

    # Must-not-contain
    if case.must_not_contain:
        hits = [kw for kw in case.must_not_contain if kw.lower() in ft_low]
        ok = not hits
        checks["must_not_contain"] = ok
        if not ok:
            errors.append(f"contains forbidden keywords: {hits}")

    # Expected tools
    if case.expected_tools:
        used = {str(t) for t in (result.get("tools_used") or [])}
        missing = [t for t in case.expected_tools if t not in used]
        ok = not missing
        checks["tools"] = ok
        if not ok:
            errors.append(f"expected tools not invoked: {missing}")

    # Compute weighted score
    if not checks:
        return checks, 1.0, errors
    total_weight = 0.0
    got = 0.0
    for name, passed in checks.items():
        w = _WEIGHTS.get(name, 1.0)
        total_weight += w
        if passed:
            got += w
    score = got / total_weight if total_weight else 1.0
    return checks, score, errors


@dataclass
class EvalReport:
    """Aggregate results for a suite run."""

    results: list[EvalResult] = field(default_factory=list)
    started_at: float = 0.0
    duration_ms: int = 0

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def pass_rate(self) -> float:
        return (self.passed / self.total) if self.total else 0.0

    @property
    def mean_score(self) -> float:
        if not self.results:
            return 0.0
        return statistics.fmean(r.score for r in self.results)

    @property
    def total_cost_usd(self) -> float:
        return round(sum(r.cost_usd for r in self.results), 6)

    def summary(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.total - self.passed,
            "pass_rate": round(self.pass_rate, 4),
            "mean_score": round(self.mean_score, 4),
            "total_cost_usd": self.total_cost_usd,
            "duration_ms": int(self.duration_ms),
            "cases": [r.to_dict() for r in self.results],
        }

    def write_json(self, path: Path | str) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.summary(), indent=2), encoding="utf-8")
        return p


class EvalRunner:
    """Runs a suite of :class:`EvalCase` against a caller-supplied agent fn.

    Parameters
    ----------
    agent_fn:
        Callable that takes an :class:`EvalCase` and returns a dict (see
        module docstring for the contract).
    pass_threshold:
        Cases with score below this threshold are marked ``passed=False``
        even if all individual checks are empty. Default ``1.0`` (strict).
    """

    def __init__(
        self,
        agent_fn: AgentFn,
        *,
        pass_threshold: float = 1.0,
    ) -> None:
        self.agent_fn = agent_fn
        self.pass_threshold = float(pass_threshold)

    def run(self, cases: Iterable[EvalCase]) -> EvalReport:
        report = EvalReport(started_at=time.time())
        t0 = time.perf_counter()
        for case in cases:
            report.results.append(self._run_one(case))
        report.duration_ms = int((time.perf_counter() - t0) * 1000)
        return report

    def _run_one(self, case: EvalCase) -> EvalResult:
        t0 = time.perf_counter()
        try:
            out = self.agent_fn(case) or {}
        except Exception as exc:  # agent failure is a hard fail
            log.exception("eval case %s raised", case.case_id)
            return EvalResult(
                case_id=case.case_id,
                passed=False,
                score=0.0,
                errors=[f"{type(exc).__name__}: {exc}"],
                duration_ms=int((time.perf_counter() - t0) * 1000),
            )
        checks, score, errors = _score_case(case, out)
        dur = int((time.perf_counter() - t0) * 1000)
        passed = score >= self.pass_threshold and not errors
        return EvalResult(
            case_id=case.case_id,
            passed=passed,
            score=score,
            checks=checks,
            errors=errors,
            tokens_in=int(out.get("tokens_in", 0) or 0),
            tokens_out=int(out.get("tokens_out", 0) or 0),
            cost_usd=float(out.get("cost_usd", 0.0) or 0.0),
            duration_ms=dur,
            tools_used=list(out.get("tools_used") or []),
        )


__all__ = ["EvalRunner", "EvalReport", "AgentFn"]
