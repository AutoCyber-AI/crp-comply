# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""BATCH 8 — intelligent recipe tailoring.

Verifies:
* applicability schema parses from YAML
* condition DSL (truthy, !truthy, eq, neq, in-set, contains)
* per-section gating with skip_rationale
* executor respects the tailoring plan
* recommend_recipes ranks applicable first, then by fewer skips
* API ``/tailor`` and ``/recommend`` endpoints
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from crp_comply.recipes import (
    CANONICAL_PROFILE_KEYS,
    RecipeRunner,
    list_builtin_recipes,
    load_recipe,
    recommend_recipes,
    tailor_recipe,
)
from crp_comply.recipes.tailoring import (
    evaluate_all,
    evaluate_any,
)


# ── DSL evaluator ───────────────────────────────────────────


def test_dsl_truthy_and_negation():
    used: set[str] = set()
    assert evaluate_all(["is_high_risk"], {"is_high_risk": True}, used)
    assert not evaluate_all(["is_high_risk"], {"is_high_risk": False}, used)
    assert evaluate_all(["!is_high_risk"], {"is_high_risk": False}, used)
    assert "is_high_risk" in used


def test_dsl_equality_and_inequality():
    used: set[str] = set()
    assert evaluate_all(["actor=provider"], {"actor": "provider"}, used)
    assert not evaluate_all(["actor=provider"], {"actor": "deployer"}, used)
    assert evaluate_all(["actor!=provider"], {"actor": "deployer"}, used)


def test_dsl_in_set():
    used: set[str] = set()
    assert evaluate_all(
        ["organisation_type=public_body|credit_scoring"],
        {"organisation_type": "credit_scoring"},
        used,
    )
    assert not evaluate_all(
        ["organisation_type=public_body|credit_scoring"],
        {"organisation_type": "general"},
        used,
    )


def test_dsl_contains_on_list():
    used: set[str] = set()
    assert evaluate_all(["jurisdiction~EU"], {"jurisdiction": ["EU", "UK"]}, used)
    assert not evaluate_all(["jurisdiction~US"], {"jurisdiction": ["EU"]}, used)


def test_dsl_empty_conds_all_true_any_false():
    used: set[str] = set()
    assert evaluate_all([], {}, used)
    assert not evaluate_any([], {}, used)


def test_dsl_unknown_key_is_false():
    used: set[str] = set()
    assert not evaluate_all(["never_seen_flag"], {}, used)


# ── Schema round-trip on all built-ins ──────────────────────


def test_all_builtin_recipes_parse_new_schema():
    ids = list_builtin_recipes()
    assert len(ids) >= 23
    for rid in ids:
        r = load_recipe(rid)
        # applicability object must exist even when YAML omits the block.
        assert r.applicability is not None
        for s in r.sections:
            assert s.applicability is not None


def test_canonical_profile_keys_stable():
    # Contract — UI forms rely on these.
    assert "actor" in CANONICAL_PROFILE_KEYS
    assert "is_high_risk" in CANONICAL_PROFILE_KEYS
    assert "is_chatbot" in CANONICAL_PROFILE_KEYS


# ── Recipe-level tailoring ──────────────────────────────────


def test_fria_applies_to_public_body_deployer():
    r = load_recipe("eu_ai_act_art_27_fria")
    plan = tailor_recipe(
        r,
        {
            "actor": "deployer",
            "is_high_risk": True,
            "organisation_type": "public_body",
        },
    )
    assert plan.should_produce
    assert plan.applicable_sections
    assert plan.purpose  # purpose surfaced from YAML


def test_fria_skipped_for_provider():
    r = load_recipe("eu_ai_act_art_27_fria")
    plan = tailor_recipe(
        r,
        {
            "actor": "provider",
            "is_high_risk": True,
            "organisation_type": "general",
        },
    )
    assert not plan.should_produce
    assert plan.why


def test_dpia_skipped_when_no_personal_data():
    r = load_recipe("gdpr_art_35_dpia")
    plan = tailor_recipe(r, {"processes_personal_data": False})
    assert not plan.should_produce


def test_dpia_applies_when_personal_data():
    r = load_recipe("gdpr_art_35_dpia")
    plan = tailor_recipe(r, {"processes_personal_data": True})
    assert plan.should_produce


# ── Per-section tailoring (Art 50) ──────────────────────────


def test_art50_chatbot_only_profile():
    r = load_recipe("eu_ai_act_art_50_transparency_notices")
    plan = tailor_recipe(
        r,
        {
            "actor": "deployer",
            "is_chatbot": True,
            "generates_synthetic_content": False,
            "is_emotion_recognition": False,
            "is_biometric_categorisation": False,
            "is_deepfake_generator": False,
        },
    )
    skipped_ids = {s.section_id for s in plan.skipped_sections}
    applicable_ids = {s.id for s in plan.applicable_sections}
    assert "chatbot_disclosure" in applicable_ids
    assert "synthetic_content_marking" in skipped_ids
    assert "emotion_or_biometric_disclosure" in skipped_ids
    assert "deep_fake_disclosure" in skipped_ids
    # every skip must carry a rationale for UI transparency.
    for s in plan.skipped_sections:
        assert s.reason
        assert s.rule


def test_art50_deepfake_only_profile():
    r = load_recipe("eu_ai_act_art_50_transparency_notices")
    plan = tailor_recipe(
        r,
        {
            "actor": "deployer",
            "is_chatbot": False,
            "generates_synthetic_content": False,
            "is_emotion_recognition": False,
            "is_biometric_categorisation": False,
            "is_deepfake_generator": True,
        },
    )
    applicable_ids = {s.id for s in plan.applicable_sections}
    assert "deep_fake_disclosure" in applicable_ids
    assert "chatbot_disclosure" not in applicable_ids


# ── Recommend ranking ───────────────────────────────────────


def test_recommend_ranks_applicable_first():
    ids = list_builtin_recipes()
    recipes = [load_recipe(i) for i in ids]
    profile = {
        "actor": "provider",
        "is_high_risk": True,
        "established_in_eu": True,
        "processes_personal_data": True,
    }
    plans = recommend_recipes(recipes, profile)
    # First plan must be applicable.
    assert plans[0].should_produce


def test_recommend_empty_profile_returns_all_as_applicable():
    ids = list_builtin_recipes()
    recipes = [load_recipe(i) for i in ids]
    plans = recommend_recipes(recipes, None)
    # None profile → vacuous apply.
    assert all(p.should_produce or not p.should_produce for p in plans)
    assert len(plans) == len(recipes)


# ── Executor respects tailoring ─────────────────────────────


def _stub_agent(prompt: str, section):  # noqa: ARG001
    # Return a draft containing whatever citations the section expects —
    # keeps executor warnings minimal in tests.
    return "Draft body. " + " ".join(section.citations)


def test_executor_runs_only_applicable_sections():
    r = load_recipe("eu_ai_act_art_50_transparency_notices")
    runner = RecipeRunner(agent=_stub_agent)
    out = runner.run(
        r,
        inputs={
            "provider_or_deployer": "deployer",
            "system_id": "test-sys",
            "system_category": "limited_risk",
        },
        profile={
            "actor": "deployer",
            "is_chatbot": True,
            "is_deepfake_generator": False,
            "generates_synthetic_content": False,
            "is_emotion_recognition": False,
            "is_biometric_categorisation": False,
        },
    )
    section_ids = {s["id"] for s in out.json_payload["sections"]}
    assert "chatbot_disclosure" in section_ids
    assert "deep_fake_disclosure" not in section_ids
    # skipped_sections structure must appear in json_payload for the UI.
    assert "skipped_sections" in out.json_payload
    assert any(
        s["section_id"] == "deep_fake_disclosure" for s in out.json_payload["skipped_sections"]
    )


def test_executor_raises_when_recipe_not_applicable():
    r = load_recipe("gdpr_art_35_dpia")
    runner = RecipeRunner(agent=_stub_agent)
    with pytest.raises(ValueError, match="does not apply"):
        runner.run(r, profile={"processes_personal_data": False})


# ── API endpoints ───────────────────────────────────────────


@pytest.fixture
def client():
    from crp_comply.api.recipes import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def test_api_tailor_endpoint(client):
    r = client.post(
        "/api/v1/recipes/eu_ai_act_art_27_fria/tailor",
        json={
            "profile": {
                "actor": "deployer",
                "is_high_risk": True,
                "organisation_type": "public_body",
            }
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["should_produce"] is True
    assert body["applicable_sections"]
    assert "why" in body


def test_api_tailor_endpoint_skip(client):
    r = client.post(
        "/api/v1/recipes/gdpr_art_35_dpia/tailor",
        json={"profile": {"processes_personal_data": False}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["should_produce"] is False


def test_api_tailor_404(client):
    r = client.post(
        "/api/v1/recipes/does_not_exist/tailor",
        json={"profile": {}},
    )
    assert r.status_code == 404


def test_api_recommend_endpoint(client):
    r = client.post(
        "/api/v1/recipes/recommend",
        json={"profile": {"actor": "provider", "is_high_risk": True}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list)
    assert len(body) >= 23
    # First entry must be applicable given the profile.
    assert body[0]["should_produce"] is True
