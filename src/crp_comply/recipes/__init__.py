# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Deliverable recipes — DESIGN_GAP_ASSESSMENT §16, REMAINING_WORK B4.

A *recipe* is a YAML-defined agent execution plan for a single regulatory
deliverable. It pins:

* the ``sections`` the output must contain (with order),
* the ``citations`` each section must surface (article/clause numbers),
* the ``ckf_queries`` the agent should run first to recall prior facts,
* the ``tools`` the agent is allowed to invoke, and
* the ``output`` schema (``markdown | json | both``).

The recipe executor orchestrates those steps around the existing
:class:`crp_comply.agent.ComplianceAgent`. Recipes are *not* templates —
the LLM writes the narrative, but the structure, citations, and evidence
wiring are fixed so every produced deliverable has the same auditable
shape.

Public API::

    from crp_comply.recipes import load_recipe, RecipeRunner

    recipe = load_recipe("iso_42001_statement_of_applicability")
    runner = RecipeRunner(agent=my_agent)
    out = runner.run(recipe, inputs={"system_id": "cv-bot-v1"})
    print(out.markdown)
"""

from .executor import RecipeRunner, RecipeOutput
from .human_inputs import InputRequirement, enumerate_human_inputs
from .loader import (
    Applicability,
    ClarificationSpec,
    Recipe,
    RecipeSection,
    SectionApplicability,
    builtin_recipe_path,
    list_builtin_recipes,
    load_recipe,
    load_recipe_from_file,
)
from .tailoring import (
    CANONICAL_PROFILE_KEYS,
    ClarificationRequest,
    SkippedSection,
    TailoringPlan,
    recommend_recipes,
    tailor_recipe,
    tailor_recipe_dynamic,
)

__all__ = [
    "Applicability",
    "CANONICAL_PROFILE_KEYS",
    "ClarificationRequest",
    "ClarificationSpec",
    "InputRequirement",
    "Recipe",
    "RecipeSection",
    "RecipeRunner",
    "RecipeOutput",
    "SectionApplicability",
    "SkippedSection",
    "TailoringPlan",
    "builtin_recipe_path",
    "enumerate_human_inputs",
    "list_builtin_recipes",
    "load_recipe",
    "load_recipe_from_file",
    "recommend_recipes",
    "tailor_recipe",
    "tailor_recipe_dynamic",
]
