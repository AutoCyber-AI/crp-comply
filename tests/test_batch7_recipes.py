# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""BATCH 7 — deliverable recipes.

Covers:
* loader + validation
* executor: section prompt construction, citation extraction, warnings
* API endpoints: list / get / run (happy path + paywall)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from crp_comply.recipes import (
    Recipe,
    RecipeRunner,
    RecipeSection,
    list_builtin_recipes,
    load_recipe,
)
from crp_comply.recipes.executor import _extract_citations


# ── Loader ──────────────────────────────────────────────────


def test_list_builtin_recipes_includes_new_must_haves():
    ids = list_builtin_recipes()
    assert "iso_42001_statement_of_applicability" in ids
    assert "nist_ai_rmf_profile" in ids
    assert "eu_ai_act_art_27_fria" in ids


@pytest.mark.parametrize(
    "recipe_id",
    [
        "iso_42001_statement_of_applicability",
        "nist_ai_rmf_profile",
        "eu_ai_act_art_27_fria",
    ],
)
def test_builtin_recipes_load_and_validate(recipe_id):
    r = load_recipe(recipe_id)
    assert r.recipe_id == recipe_id
    assert r.sections, "recipe must have sections"
    assert r.validate() == []
    assert r.title
    assert r.regulation


def test_recipe_validation_rejects_duplicate_section_ids():
    r = Recipe(
        recipe_id="dup",
        title="t",
        regulation="x",
        sections=[RecipeSection(id="a", title="A"), RecipeSection(id="a", title="B")],
    )
    errs = r.validate()
    assert any("unique" in e for e in errs)


def test_recipe_validation_rejects_empty_sections():
    r = Recipe(recipe_id="empty", title="t", regulation="x", sections=[])
    assert any("at least one section" in e for e in r.validate())


# ── Citation extraction ─────────────────────────────────────


def test_extract_citations_dedupes_and_normalises():
    text = (
        "This complies with Article 6 and again Article 6(2). "
        "Per Annex III row 4 and Annex III, and Clause 6.1.3."
    )
    cites = _extract_citations(text)
    # All three distinct patterns present, case-insensitive dedupe
    assert "Article 6" in cites
    assert any(c.lower().startswith("article 6(2)") for c in cites)
    assert any(c.lower().startswith("annex iii") for c in cites)
    assert any(c.lower().startswith("clause 6.1.3") for c in cites)


# ── Executor ─────────────────────────────────────────────────


def _stub_llm(prompt: str, section) -> str:
    """Mock LLM that echoes back declared citations."""
    cites = " ".join(section.citations)
    return f"Draft for {section.title}. References: {cites}."


def test_runner_produces_markdown_and_json():
    recipe = load_recipe("iso_42001_statement_of_applicability")
    runner = RecipeRunner(agent=_stub_llm)
    out = runner.run(
        recipe,
        inputs={
            "organisation": "Acme Ltd",
            "scope": "CV screening AI",
            "ai_systems": ["cv-bot-v1"],
        },
    )
    assert out.recipe_id == recipe.recipe_id
    # Markdown has the title header and every section heading
    assert out.markdown.startswith(f"# {recipe.title}")
    for s in recipe.sections:
        assert f"## {s.title}" in out.markdown
    # JSON payload mirrors sections with citations
    sids = {s["id"] for s in out.json_payload["sections"]}
    assert sids == set(recipe.section_ids())
    # Declared citations surface in the section_citations map
    first = recipe.sections[0]
    if first.citations:
        assert any(
            c.lower() in " ".join(out.section_citations[first.id]).lower() for c in first.citations
        )


def test_runner_missing_required_inputs_raises():
    recipe = load_recipe("nist_ai_rmf_profile")
    runner = RecipeRunner(agent=_stub_llm)
    with pytest.raises(ValueError) as exc:
        runner.run(recipe, inputs={})  # missing organisation + use_case
    assert "missing required inputs" in str(exc.value)


def test_runner_warns_when_llm_skips_required_citation():
    recipe = Recipe(
        recipe_id="t",
        title="T",
        regulation="X",
        sections=[
            RecipeSection(
                id="s1",
                title="S1",
                citations=["Article 13", "Annex IV"],
            )
        ],
    )

    def no_cite_llm(prompt: str, section) -> str:
        return "Plain narrative with no legal references."

    runner = RecipeRunner(agent=no_cite_llm)
    out = runner.run(recipe)
    # Warning surfaced for each missing citation
    assert any("Article 13" in w for w in out.warnings)
    assert any("Annex IV" in w for w in out.warnings)
    # Declared citations still appear in the structured output even
    # though the LLM skipped them — auditable contract.
    assert "Article 13" in out.section_citations["s1"]


def test_runner_handles_agent_exception_gracefully():
    recipe = Recipe(
        recipe_id="t",
        title="T",
        regulation="X",
        sections=[RecipeSection(id="s1", title="S1")],
    )

    def broken(prompt: str, section) -> str:
        raise RuntimeError("nope")

    runner = RecipeRunner(agent=broken)
    out = runner.run(recipe)
    assert any("stub agent error" in w for w in out.warnings)


# ── API endpoints ───────────────────────────────────────────


@pytest.fixture
def api_client(monkeypatch, tmp_path):
    """Lightweight API client that stubs the recipe runner."""
    monkeypatch.setenv("CRP_COMPLY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CRP_COMPLY_JWT_SECRET", "t" * 32)

    from crp_comply.api import recipes as recipes_mod
    from crp_comply.api.app import create_app

    # Deterministic runner — avoid needing a real LLM provider.
    class _StubRunner:
        def __init__(self, user_id: str) -> None:
            self.user_id = user_id

        def run(self, recipe, *, inputs=None):
            # Use the module-level executor helpers
            real = RecipeRunner(agent=_stub_llm)
            return real.run(recipe, inputs=inputs or {})

    recipes_mod._runner_factory_override = lambda uid: _StubRunner(uid)

    app = create_app()
    try:
        with TestClient(app) as client:
            yield client
    finally:
        recipes_mod._runner_factory_override = None


def test_api_list_recipes(api_client):
    r = api_client.get("/api/v1/recipes")
    assert r.status_code == 200
    data = r.json()
    ids = {item["recipe_id"] for item in data}
    assert "iso_42001_statement_of_applicability" in ids
    assert "nist_ai_rmf_profile" in ids


def test_api_get_recipe_manifest(api_client):
    r = api_client.get("/api/v1/recipes/eu_ai_act_art_27_fria")
    assert r.status_code == 200
    body = r.json()
    assert body["recipe_id"] == "eu_ai_act_art_27_fria"
    assert body["required_inputs"] == ["deployer", "system_id", "intended_purpose"]
    assert len(body["sections"]) >= 5


def test_api_get_recipe_404(api_client):
    r = api_client.get("/api/v1/recipes/does-not-exist")
    assert r.status_code == 404
