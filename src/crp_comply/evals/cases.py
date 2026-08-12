# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Case / result dataclasses + YAML loader.

Cases are intentionally declarative — the whole schema is documented by
:class:`EvalCase`. Unknown keys are ignored with a warning so old cases
don't break when the schema grows.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - PyYAML is a declared dep
    yaml = None

log = logging.getLogger("crp_comply.evals.cases")


@dataclass
class EvalCase:
    """A single evaluation case.

    Fields
    ------
    case_id:
        Short stable identifier (``ai_act_cv_screening``) used in reports.
    task:
        The user prompt the agent will be run against.
    system_id / customer_id:
        Optional routing hints the agent uses when talking to the CKF.
    expected_risk_level:
        One of ``unacceptable | high | limited | minimal`` or empty to
        skip the risk-level check.
    expected_citations:
        Article/annex references that must appear in the final text
        (e.g. ``["Article 6", "Annex III"]``) — substring match.
    must_contain / must_not_contain:
        Literal substrings that must / must not appear in ``final_text``.
    expected_tools:
        Tool names that must have been invoked at least once.
    tags:
        Free-form labels for filtering (``ai_act``, ``gdpr``, ``iso42001``).
    """

    case_id: str
    task: str
    system_id: str = ""
    customer_id: str = ""
    expected_risk_level: str = ""
    expected_citations: list[str] = field(default_factory=list)
    must_contain: list[str] = field(default_factory=list)
    must_not_contain: list[str] = field(default_factory=list)
    expected_tools: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvalCase":
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known
        if unknown:
            log.warning(
                "eval case %s ignoring unknown keys: %s", data.get("case_id", "?"), sorted(unknown)
            )
        init_kwargs: dict[str, Any] = {k: data[k] for k in known if k in data}
        return cls(**init_kwargs)


@dataclass
class EvalResult:
    """Outcome of running a single :class:`EvalCase`."""

    case_id: str
    passed: bool
    score: float  # 0.0 – 1.0
    checks: dict[str, bool] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    tools_used: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "passed": self.passed,
            "score": round(self.score, 4),
            "checks": dict(self.checks),
            "errors": list(self.errors),
            "tokens_in": int(self.tokens_in),
            "tokens_out": int(self.tokens_out),
            "cost_usd": round(float(self.cost_usd), 6),
            "duration_ms": int(self.duration_ms),
            "tools_used": list(self.tools_used),
        }


# ── Loaders ──────────────────────────────────────────────────


def load_case(path: Path | str) -> EvalCase:
    p = Path(path)
    if yaml is None:
        raise RuntimeError(
            "PyYAML is required to load eval cases. Install with `pip install pyyaml`."
        )
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    data.setdefault("case_id", p.stem)
    return EvalCase.from_dict(data)


def load_suite(directory: Path | str) -> list[EvalCase]:
    d = Path(directory)
    if not d.exists() or not d.is_dir():
        raise FileNotFoundError(f"eval suite not found: {d}")
    cases: list[EvalCase] = []
    for p in sorted(d.glob("*.yaml")):
        cases.append(load_case(p))
    return cases


def load_all_suites(root: Path | str) -> list[EvalCase]:
    """Recursively load every ``*.yaml`` case under ``root``.

    Use when you want a single combined eval pass across all packs
    (``ai_act_basic``, ``gdpr``, ``iso42001``, ``nist_rmf``, ...).
    """
    r = Path(root)
    if not r.exists() or not r.is_dir():
        raise FileNotFoundError(f"eval root not found: {r}")
    cases: list[EvalCase] = []
    for p in sorted(r.rglob("*.yaml")):
        cases.append(load_case(p))
    return cases


def filter_suite(
    cases: Iterable[EvalCase],
    *,
    tags: Iterable[str] | None = None,
) -> list[EvalCase]:
    if not tags:
        return list(cases)
    wanted = {t.lower() for t in tags}
    return [c for c in cases if wanted.intersection(t.lower() for t in c.tags)]


__all__ = [
    "EvalCase",
    "EvalResult",
    "load_case",
    "load_suite",
    "load_all_suites",
    "filter_suite",
]
