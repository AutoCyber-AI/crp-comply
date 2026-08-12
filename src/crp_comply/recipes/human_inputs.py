# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Enumerate everything in a recipe that needs human input or confirmation.

The compliance agent cannot invent facts: every recipe has points
where the only correct answer is "ask the human". This module walks
a :class:`Recipe` and a caller-supplied profile + inputs and returns
an ordered list of :class:`InputRequirement` items describing exactly
what's outstanding.

Three sources feed the list:

1. **Missing required inputs** — ``recipe.required_inputs`` that the
   caller has not provided. Priority: ``high``.
2. **Recipe-level `ask_when_unknown`** clarifications whose fact_key
   is absent from the profile. Priority: as declared in the YAML
   (typically ``high`` for applies-when / not-applies-when gates).
3. **Section-level `ask_when_unknown`** clarifications — surfaced even
   when the recipe-level verdict is already known so the user can
   confirm section-scoped refinements before drafting.

Every item includes the citation, the answer type, and the channel
hint the notification dispatcher will honour when surfacing the
question to the user (chat ringer for ``high``, email for ``medium``,
digest for ``low``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .loader import ClarificationSpec, Recipe


@dataclass
class InputRequirement:
    """One outstanding piece of human input / confirmation.

    Mirrors the shape the UI already knows from
    :class:`~crp_comply.recipes.tailoring.ClarificationRequest` with
    an extra ``source`` field so the frontend can group the list
    ("we need these before we can start" vs. "confirm these as we go").
    """

    key: str
    question: str
    source: str  # "required_input" | "recipe_clarification" | "section_clarification"
    priority: str = "medium"  # high | medium | low
    context: str = ""
    citation: str = ""
    fact_key: str = ""
    answer_type: str = "text"
    options: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    recipe_id: str = ""
    section_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "question": self.question,
            "source": self.source,
            "priority": self.priority,
            "context": self.context,
            "citation": self.citation,
            "fact_key": self.fact_key,
            "answer_type": self.answer_type,
            "options": list(self.options),
            "examples": list(self.examples),
            "recipe_id": self.recipe_id,
            "section_id": self.section_id,
        }


_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def _is_unknown(profile: dict[str, Any], key: str) -> bool:
    if key not in profile:
        return True
    v = profile.get(key)
    if v is None:
        return True
    if isinstance(v, str) and not v.strip():
        return True
    if isinstance(v, (list, tuple, set, dict)) and len(v) == 0:
        return True
    return False


def _spec_to_requirement(
    key: str,
    spec: ClarificationSpec,
    *,
    source: str,
    recipe_id: str,
    section_id: str = "",
) -> InputRequirement:
    return InputRequirement(
        key=key,
        question=spec.question or f"Please answer: {key}",
        source=source,
        priority=spec.priority or "medium",
        context=spec.context,
        citation=spec.citation,
        fact_key=spec.fact_key or key,
        answer_type=spec.answer_type or "text",
        options=list(spec.options),
        examples=list(spec.examples),
        recipe_id=recipe_id,
        section_id=section_id,
    )


def _required_input_requirement(key: str, recipe_id: str) -> InputRequirement:
    return InputRequirement(
        key=key,
        question=(f"Please provide '{key}' — this recipe cannot start without it."),
        source="required_input",
        priority="high",
        context="Declared as a required input on the recipe manifest.",
        fact_key=key,
        answer_type="text",
        recipe_id=recipe_id,
    )


def enumerate_human_inputs(
    recipe: Recipe,
    *,
    profile: dict[str, Any] | None = None,
    inputs: dict[str, Any] | None = None,
    include_section_clarifications: bool = True,
) -> list[InputRequirement]:
    """Return every item the human still has to answer / confirm.

    Ordering: ``high`` before ``medium`` before ``low``; stable by
    source within a priority band (required inputs first, then recipe
    clarifications, then section clarifications).

    The function is pure — no I/O, no LLM — so it's cheap to call on
    every page render and every ``POST /recipes/{id}/run``.
    """
    profile = dict(profile or {})
    inputs = dict(inputs or {})
    out: list[InputRequirement] = []

    # 1. Required inputs the caller hasn't supplied.
    for key in recipe.required_inputs or []:
        if _is_unknown(inputs, key):
            out.append(_required_input_requirement(key, recipe.recipe_id))

    # 2. Recipe-level ask_when_unknown for keys still missing.
    app = recipe.applicability
    specs: dict[str, ClarificationSpec] = dict(getattr(app, "ask_when_unknown", {}) or {})
    for key, spec in specs.items():
        fact_key = spec.fact_key or key
        if _is_unknown(profile, fact_key):
            out.append(
                _spec_to_requirement(
                    key,
                    spec,
                    source="recipe_clarification",
                    recipe_id=recipe.recipe_id,
                )
            )

    # 3. Section-level ask_when_unknown — UI groups by section_id.
    if include_section_clarifications:
        for section in recipe.sections:
            sa = getattr(section, "applicability", None)
            if sa is None:
                continue
            sspecs: dict[str, ClarificationSpec] = dict(getattr(sa, "ask_when_unknown", {}) or {})
            for key, spec in sspecs.items():
                fact_key = spec.fact_key or key
                if _is_unknown(profile, fact_key):
                    out.append(
                        _spec_to_requirement(
                            key,
                            spec,
                            source="section_clarification",
                            recipe_id=recipe.recipe_id,
                            section_id=section.id,
                        )
                    )

    # 4. Branching interview tree (Gap #1 — article-cited Socratic
    #    questions ordered by branch). A branch only contributes
    #    questions when its ``when`` conditions evaluate true and its
    #    ``not_when`` conditions evaluate false against the current
    #    profile. Branches asking about facts already in the profile
    #    silently drop those questions so the user is never asked twice.
    branches = list(getattr(recipe, "interview_branches", []) or [])
    if branches:
        from .tailoring import evaluate_all, evaluate_any

        for branch in branches:
            used: set[str] = set()
            if branch.when and not evaluate_all(branch.when, profile, used):
                continue
            if branch.not_when and evaluate_any(branch.not_when, profile, used):
                continue
            for key, spec in (branch.ask or {}).items():
                fact_key = spec.fact_key or key
                if not _is_unknown(profile, fact_key):
                    continue
                req = _spec_to_requirement(
                    key,
                    spec,
                    source="interview_branch",
                    recipe_id=recipe.recipe_id,
                )
                # Inherit the branch's anchor citation when the spec
                # didn't override it — keeps the UI's "why are we
                # asking?" link useful even on terse YAML.
                if not req.citation and branch.citation:
                    req.citation = branch.citation
                out.append(req)

    # Stable sort: priority first, source second (retain original order
    # within each bucket so the YAML ordering is surfaced to the user).
    source_order = {
        "required_input": 0,
        "recipe_clarification": 1,
        "interview_branch": 2,
        "section_clarification": 3,
    }
    out.sort(
        key=lambda r: (
            _PRIORITY_ORDER.get(r.priority, 99),
            source_order.get(r.source, 99),
        )
    )
    return out


def to_dicts(requirements: Iterable[InputRequirement]) -> list[dict[str, Any]]:
    """Convenience for API responses."""
    return [r.to_dict() for r in requirements]


__all__ = [
    "InputRequirement",
    "enumerate_human_inputs",
    "to_dicts",
]
