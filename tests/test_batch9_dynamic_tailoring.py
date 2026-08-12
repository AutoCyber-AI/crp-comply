# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""BATCH 9 — dynamic tri-state tailoring + notification multiplexer.

Verifies the three layers that turn BATCH 8's static DSL into an
actually agentic subsystem:

* ``ClarificationSpec`` parses from YAML and hangs off ``Applicability``
  and ``SectionApplicability``.
* Tri-state DSL (True / False / UNKNOWN sentinel) short-circuits
  correctly and propagates the missing key.
* ``tailor_recipe_dynamic`` returns ``should_produce="uncertain"``
  plus ordered ``pending_questions`` when facts are missing, and
  auto-fills known keys from a CKF stub before asking.
* ``NotificationDispatcher`` routes HIGH priority to in-app chat with
  ``ring=True`` forced on, falls back when preferred channel can't
  deliver, and every message carries a verifiable HMAC token that
  binds ``user_id + email + notification_id``.
* API endpoints ``POST /recipes/{id}/plan`` and
  ``POST /notifications/test`` surface the new capabilities.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from crp_comply.api.app import create_app
from crp_comply.api.auth import AuthManager
from crp_comply.api.deps import init_dependencies
from crp_comply.api.reports import init_report_store
from crp_comply.api.usage import init_usage_tracker
from crp_comply.core import CRPComply
from crp_comply.notifications import (
    DeliveryReceipt,
    InAppChatChannel,
    Notification,
    NotificationDispatcher,
    NotificationPriority,
    UserContactProfile,
    make_verification_token,
    verify_token,
)
from crp_comply.recipes import load_recipe, tailor_recipe_dynamic
from crp_comply.recipes.loader import (
    Applicability,
    ClarificationSpec,
    Recipe,
    RecipeSection,
    SectionApplicability,
)
from crp_comply.recipes.tailoring import (
    UNKNOWN,
    _build_clarification,
    evaluate_all_tri,
    evaluate_any_tri,
)


# ── Loader: ClarificationSpec parsing ───────────────────────


def test_clarification_spec_parses_from_dict():
    raw = {
        "recipe_id": "probe",
        "title": "t",
        "regulation": "r",
        "sections": [{"id": "s1", "title": "S"}],
        "applicability": {
            "applies_when": ["is_high_risk"],
            "ask_when_unknown": {
                "is_high_risk": {
                    "question": "Is this high-risk?",
                    "priority": "high",
                    "citation": "Art. 6",
                    "answer_type": "bool",
                },
            },
        },
    }
    _ = Recipe.from_dict(raw) if hasattr(Recipe, "from_dict") else None
    # loader.py uses from_dict as a free function if not a classmethod
    from crp_comply.recipes.loader import Recipe as R

    assert hasattr(R, "from_dict")
    recipe = R.from_dict(raw)
    spec = recipe.applicability.ask_when_unknown["is_high_risk"]
    assert isinstance(spec, ClarificationSpec)
    assert spec.priority == "high"
    assert spec.citation == "Art. 6"
    assert spec.answer_type == "bool"


def test_section_level_clarification_spec_parses():
    raw = {
        "recipe_id": "probe",
        "title": "t",
        "regulation": "r",
        "sections": [
            {
                "id": "s1",
                "title": "S",
                "applicability": {
                    "applies_when": ["is_chatbot"],
                    "ask_when_unknown": {
                        "is_chatbot": {
                            "question": "Is it a chatbot?",
                            "priority": "medium",
                            "answer_type": "bool",
                        },
                    },
                },
            },
        ],
    }
    from crp_comply.recipes.loader import Recipe as R

    recipe = R.from_dict(raw)
    spec = recipe.sections[0].applicability.ask_when_unknown["is_chatbot"]
    assert spec.question == "Is it a chatbot?"


# ── Tri-state DSL ───────────────────────────────────────────


def test_evaluate_all_tri_false_dominates_unknown():
    used: set[str] = set()
    unknown: set[str] = set()
    # actor is known and wrong → False wins even though is_high_risk missing
    result = evaluate_all_tri(
        ["actor=provider", "is_high_risk"],
        {"actor": "deployer"},
        used,
        unknown,
    )
    assert result is False
    # unknown set should NOT include is_high_risk because we short-circuited
    assert "is_high_risk" not in unknown


def test_evaluate_all_tri_unknown_when_any_missing():
    used: set[str] = set()
    unknown: set[str] = set()
    result = evaluate_all_tri(
        ["actor=deployer", "is_high_risk"],
        {"actor": "deployer"},
        used,
        unknown,
    )
    assert result is UNKNOWN
    assert "is_high_risk" in unknown


def test_evaluate_any_tri_true_dominates_unknown():
    used: set[str] = set()
    unknown: set[str] = set()
    result = evaluate_any_tri(
        ["is_high_risk", "is_gpai"],
        {"is_high_risk": True},
        used,
        unknown,
    )
    assert result is True


def test_is_key_known_treats_empty_values_as_unknown():
    from crp_comply.recipes.tailoring import _is_key_known

    assert _is_key_known("k", {"k": True})
    assert _is_key_known("k", {"k": False})
    assert _is_key_known("k", {"k": "x"})
    assert not _is_key_known("k", {})
    assert not _is_key_known("k", {"k": None})
    assert not _is_key_known("k", {"k": ""})
    assert not _is_key_known("k", {"k": []})


# ── Dynamic tailoring engine ────────────────────────────────


def _probe_recipe() -> Recipe:
    """Minimal recipe exercising recipe-level + section-level gating."""
    return Recipe(
        recipe_id="probe",
        title="Probe",
        regulation="test",
        applicability=Applicability(
            applies_when=["actor=deployer", "is_high_risk"],
            ask_when_unknown={
                "actor": ClarificationSpec(
                    question="What role?",
                    priority="high",
                    answer_type="choice",
                    options=["provider", "deployer"],
                ),
                "is_high_risk": ClarificationSpec(
                    question="Is it high-risk?",
                    priority="high",
                    answer_type="bool",
                ),
            },
        ),
        sections=[
            RecipeSection(
                id="s_always", title="Always", applicability=SectionApplicability(required=True)
            ),
            RecipeSection(
                id="s_personal",
                title="Personal data",
                applicability=SectionApplicability(
                    applies_when=["processes_personal_data"],
                    ask_when_unknown={
                        "processes_personal_data": ClarificationSpec(
                            question="Do you process personal data?",
                            priority="medium",
                            answer_type="bool",
                        ),
                    },
                ),
            ),
        ],
    )


def test_dynamic_plan_uncertain_when_missing_keys():
    recipe = _probe_recipe()
    plan = tailor_recipe_dynamic(recipe, {})
    assert plan.should_produce == "uncertain"
    assert plan.is_uncertain
    keys = {q.profile_key for q in plan.pending_questions}
    # Every unknown key the engine touched must be surfaced.
    assert "actor" in keys
    assert "is_high_risk" in keys
    assert "processes_personal_data" in keys
    # Priority ordering: high first.
    priorities = [q.priority for q in plan.pending_questions]
    assert priorities == sorted(priorities, key=lambda p: {"high": 0, "medium": 1, "low": 2}[p])


def test_dynamic_plan_true_when_all_known_and_match():
    recipe = _probe_recipe()
    plan = tailor_recipe_dynamic(
        recipe,
        {
            "actor": "deployer",
            "is_high_risk": True,
            "processes_personal_data": True,
        },
    )
    assert plan.should_produce is True
    assert plan.pending_questions == []
    assert {s.id for s in plan.applicable_sections} == {"s_always", "s_personal"}


def test_dynamic_plan_false_short_circuits_questions():
    """When a definite False is reached, we don't nag the user."""
    recipe = _probe_recipe()
    plan = tailor_recipe_dynamic(
        recipe,
        {"actor": "provider"},  # contradicts actor=deployer → False
    )
    assert plan.should_produce is False
    # Missing is_high_risk/processes_personal_data must NOT be asked.
    assert plan.pending_questions == []


def test_dynamic_plan_autofills_from_ckf_lookup():
    recipe = _probe_recipe()

    class StubCKF:
        def __init__(self, facts: dict) -> None:
            self._facts = facts

        def get(self, key: str):
            return self._facts.get(key)

    ckf = StubCKF(
        {
            "actor": "deployer",
            "is_high_risk": True,
            "processes_personal_data": True,
        }
    )
    plan = tailor_recipe_dynamic(recipe, {}, ckf_lookup=ckf)
    assert plan.should_produce is True
    assert plan.pending_questions == []


def test_dynamic_plan_dedupes_pending_questions():
    recipe = _probe_recipe()
    plan = tailor_recipe_dynamic(recipe, {})
    keys = [(q.profile_key, q.scope, q.section_id) for q in plan.pending_questions]
    assert len(keys) == len(set(keys))


# ── Clarification builder ───────────────────────────────────


def test_build_clarification_prefers_spec_over_fallback():
    spec = ClarificationSpec(
        question="Custom question?",
        context="Custom context",
        priority="high",
        answer_type="bool",
    )
    cr = _build_clarification(
        "is_high_risk",
        recipe_id="r",
        scope="recipe",
        spec_lookup={"is_high_risk": spec},
    )
    assert cr.question == "Custom question?"
    assert cr.context == "Custom context"


def test_build_clarification_uses_fallback_templates():
    cr = _build_clarification("is_high_risk", recipe_id="r", scope="recipe")
    assert "high-risk" in cr.question.lower()
    assert cr.priority == "high"


def test_build_clarification_generic_fallback_for_unknown_keys():
    cr = _build_clarification("fictitious_flag", recipe_id="r", scope="recipe")
    assert "fictitious flag" in cr.question.lower()
    assert cr.answer_type == "text"


# ── FRIA recipe uses the new schema ─────────────────────────


def test_fria_recipe_declares_ask_when_unknown():
    recipe = load_recipe("eu_ai_act_art_27_fria")
    assert "actor" in recipe.applicability.ask_when_unknown
    assert "is_high_risk" in recipe.applicability.ask_when_unknown
    assert "organisation_type" in recipe.applicability.ask_when_unknown


def test_fria_plan_is_uncertain_for_empty_profile():
    recipe = load_recipe("eu_ai_act_art_27_fria")
    plan = tailor_recipe_dynamic(recipe, {})
    assert plan.is_uncertain
    # FRIA should ask its three critical recipe-level questions.
    keys = {q.profile_key for q in plan.pending_questions}
    assert {"actor", "is_high_risk", "organisation_type"}.issubset(keys)
    # Custom citation from YAML should appear on at least one question.
    citations = [q.citation for q in plan.pending_questions]
    assert any("27" in c for c in citations)


# ── Notification: verification tokens ───────────────────────


def test_verification_token_roundtrip():
    user = UserContactProfile(user_id="u1", email="a@b.test")
    token = make_verification_token(user, "n-123")
    assert verify_token(token, user, "n-123")
    # Wrong notification id → fails.
    assert not verify_token(token, user, "n-999")
    # Different email → fails (receiver binding).
    other = UserContactProfile(user_id="u1", email="evil@c.test")
    assert not verify_token(token, other, "n-123")


# ── Notification: dispatcher routing ────────────────────────


def test_dispatcher_high_priority_forces_in_app_ring():
    inbox = InAppChatChannel()
    dispatcher = NotificationDispatcher([inbox])
    user = UserContactProfile(user_id="u1", email="a@b.test", preferred_channel="in_app")
    n = Notification(
        kind="clarification",
        subject="urgent",
        body="answer now",
        priority=NotificationPriority.HIGH,
        ring=False,  # dispatcher must override to True
    )
    receipts = dispatcher.dispatch(user=user, notification=n)
    assert any(r.ok and r.channel == "in_app" for r in receipts)
    assert n.ring is True  # override happened


def test_dispatcher_fallback_when_preferred_cannot_deliver():
    inbox = InAppChatChannel()

    class DeadChannel:
        name = "email"

        def can_deliver(self, user):  # noqa: ARG002
            return False

        def send(self, user, notification):  # noqa: ARG002
            return DeliveryReceipt(channel="email", ok=False, delivered_to="", error="x")

    dispatcher = NotificationDispatcher([inbox, DeadChannel()])
    user = UserContactProfile(user_id="u1", email="a@b.test", preferred_channel="email")
    n = Notification(kind="info", subject="hi", body="body")
    receipts = dispatcher.dispatch(user=user, notification=n)
    # Should fall back to in_app since email can't deliver.
    assert any(r.ok and r.channel == "in_app" for r in receipts)


def test_inbox_drain_clears_and_peek_does_not():
    inbox = InAppChatChannel()
    user = UserContactProfile(user_id="u1", email="a@b.test")
    n = Notification(kind="test", subject="s", body="b")
    n.notification_id = "n1"
    inbox.send(user, n)
    assert len(inbox.peek("u1")) == 1
    assert len(inbox.peek("u1")) == 1  # peek is non-destructive
    drained = inbox.drain("u1")
    assert len(drained) == 1
    assert inbox.drain("u1") == []


# ── API: /recipes/{id}/plan ─────────────────────────────────


@pytest_asyncio.fixture
async def client(tmp_path):
    app = create_app()
    auth = AuthManager(data_dir=tmp_path, jwt_secret="test-secret")
    comply = CRPComply()
    init_dependencies(auth=auth, comply=comply)
    init_usage_tracker(data_dir=tmp_path)
    init_report_store(data_dir=tmp_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_api_plan_endpoint_returns_pending_questions(client):
    resp = await client.post(
        "/api/v1/recipes/eu_ai_act_art_27_fria/plan",
        json={"profile": {}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["should_produce"] == "uncertain"
    assert len(data["pending_questions"]) >= 3
    keys = {q["profile_key"] for q in data["pending_questions"]}
    assert {"actor", "is_high_risk", "organisation_type"}.issubset(keys)


@pytest.mark.asyncio
async def test_api_plan_endpoint_definitive_when_profile_complete(client):
    resp = await client.post(
        "/api/v1/recipes/eu_ai_act_art_27_fria/plan",
        json={
            "profile": {
                "actor": "deployer",
                "is_high_risk": True,
                "organisation_type": "public_body",
                "system_category": "high_risk",
            },
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["should_produce"] is True
    assert data["pending_questions"] == []


@pytest.mark.asyncio
async def test_api_notifications_test_endpoint(client):
    # Unauthenticated calls resolve to user_id="anonymous" — enough to
    # exercise the routing. Priority=high forces in_app fan-out.
    resp = await client.post(
        "/api/v1/notifications/test",
        json={
            "email": "notify@test.io",
            "preferred_channel": "in_app",
            "subject": "Hi",
            "body": "test",
            "priority": "high",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["notification_id"]
    assert any(r["channel"] == "in_app" and r["ok"] for r in data["receipts"])
    token_str = next(r["verification_token"] for r in data["receipts"] if r["channel"] == "in_app")
    assert token_str


@pytest.mark.asyncio
async def test_api_notifications_verify_endpoint(client):
    # Construct a known token outside the API then verify via endpoint.
    user = UserContactProfile(user_id="u-xyz", email="u@v.test")
    token = make_verification_token(user, "n-42")
    resp = await client.post(
        "/api/v1/notifications/verify",
        json={
            "user_id": "u-xyz",
            "email": "u@v.test",
            "notification_id": "n-42",
            "token": token,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    # Tampered token.
    bad = await client.post(
        "/api/v1/notifications/verify",
        json={
            "user_id": "u-xyz",
            "email": "u@v.test",
            "notification_id": "n-42",
            "token": "deadbeef" * 3,
        },
    )
    assert bad.json()["ok"] is False


# ── Agent tool: plan_recipe auto-raises ClarificationNeeded ─


def test_plan_recipe_tool_raises_clarification_when_uncertain():
    from crp_comply.agent.tools import (
        ClarificationNeeded,
        build_plan_recipe_tool,
    )

    tool = build_plan_recipe_tool(fabric=None)
    with pytest.raises(ClarificationNeeded) as exc_info:
        tool.handler({"recipe_id": "eu_ai_act_art_27_fria", "profile": {}})
    # Highest-priority question should be asked first (actor/is_high_risk/organisation_type).
    err = exc_info.value
    assert err.priority == "high"
    assert err.fact_key in {"actor", "is_high_risk", "organisation_type"}


def test_plan_recipe_tool_returns_definite_plan_when_facts_known():
    from crp_comply.agent.tools import build_plan_recipe_tool

    tool = build_plan_recipe_tool(fabric=None)
    out = tool.handler(
        {
            "recipe_id": "eu_ai_act_art_27_fria",
            "profile": {
                "actor": "deployer",
                "is_high_risk": True,
                "organisation_type": "public_body",
                "system_category": "high_risk",
            },
        }
    )
    assert "error" not in out
    assert out["should_produce"] is True
    assert out["pending_question_count"] == 0


def test_plan_recipe_tool_autofills_from_ckf_fabric():
    """The tool must consult the CKF before asking the user."""
    from crp_comply.agent.tools import build_plan_recipe_tool

    class StubFabric:
        def __init__(self, facts):
            self._facts = facts

        def query(self, key):
            v = self._facts.get(key)
            return {"value": v} if v is not None else None

    fabric = StubFabric(
        {
            "actor": "deployer",
            "is_high_risk": True,
            "organisation_type": "public_body",
            "system_category": "high_risk",
        }
    )
    tool = build_plan_recipe_tool(fabric=fabric)
    out = tool.handler({"recipe_id": "eu_ai_act_art_27_fria", "profile": {}})
    assert out["should_produce"] is True


def test_plan_recipe_tool_registered_in_default_registry():
    from crp_comply.agent.tools import default_registry

    reg = default_registry()
    assert "plan_recipe" in reg


# ── RecipeRunner: completion notifier fires ─────────────────


def test_recipe_runner_calls_completion_notifier():
    from crp_comply.recipes.executor import RecipeRunner
    from crp_comply.recipes.loader import Recipe, RecipeSection

    def stub_agent(prompt, section):  # noqa: ARG001
        return f"Draft for {section.id}."

    received: list = []

    def notifier(output, inputs):
        received.append((output.recipe_id, output.title, dict(inputs)))

    recipe = Recipe(
        recipe_id="test_mini",
        title="Mini",
        regulation="test",
        sections=[RecipeSection(id="s1", title="S1")],
    )
    runner = RecipeRunner(agent=stub_agent, notifier=notifier)
    out = runner.run(recipe, inputs={"x": 1})
    assert out.recipe_id == "test_mini"
    assert received == [("test_mini", "Mini", {"x": 1})]


def test_recipe_runner_notifier_failure_does_not_break_run():
    from crp_comply.recipes.executor import RecipeRunner
    from crp_comply.recipes.loader import Recipe, RecipeSection

    def bad_notifier(output, inputs):  # noqa: ARG001
        raise RuntimeError("boom")

    runner = RecipeRunner(
        agent=lambda p, s: "x",
        notifier=bad_notifier,
    )
    recipe = Recipe(
        recipe_id="t",
        title="T",
        regulation="r",
        sections=[RecipeSection(id="s", title="S")],
    )
    out = runner.run(recipe)
    assert any("notifier_failed" in w for w in out.warnings)


# ── Retrofit recipes declare ask_when_unknown ───────────────


def test_art50_recipe_has_ask_when_unknown_per_scenario():
    recipe = load_recipe("eu_ai_act_art_50_transparency_notices")
    assert "actor" in recipe.applicability.ask_when_unknown
    # Collect section-level specs.
    keys_by_section = {s.id: set(s.applicability.ask_when_unknown.keys()) for s in recipe.sections}
    assert "is_chatbot" in keys_by_section.get("chatbot_disclosure", set())
    assert "generates_synthetic_content" in keys_by_section.get("synthetic_content_marking", set())
    assert "is_deepfake_generator" in keys_by_section.get("deep_fake_disclosure", set())


def test_dpia_recipe_has_ask_when_unknown():
    recipe = load_recipe("gdpr_art_35_dpia")
    specs = recipe.applicability.ask_when_unknown
    assert "processes_personal_data" in specs
    assert "processes_special_category_data" in specs
    assert "automated_decision_making" in specs
    assert specs["processes_personal_data"].priority == "high"
