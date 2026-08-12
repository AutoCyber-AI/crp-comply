# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Recipe library load and schema validation tests."""

from __future__ import annotations

import pytest

from crp_comply.recipes import list_builtin_recipes, load_recipe


@pytest.mark.parametrize("recipe_id", list_builtin_recipes())
def test_builtin_recipe_loads_and_validates(recipe_id: str) -> None:
    recipe = load_recipe(recipe_id)

    assert recipe.recipe_id == recipe_id
    assert isinstance(recipe.required_inputs, list)
    assert recipe.validate() == []

    section_ids = [s.id for s in recipe.sections]
    assert section_ids, f"{recipe_id}: recipe must define at least one section"
    assert all(section_ids), f"{recipe_id}: section ids must be non-empty"
    assert len(section_ids) == len(set(section_ids)), f"{recipe_id}: section ids must be unique"

    all_citations = [c for s in recipe.sections for c in s.citations]
    assert all_citations, f"{recipe_id}: at least one citation must be declared"

    assert recipe.output_artefacts, f"{recipe_id}: output_artefacts must be non-empty"
