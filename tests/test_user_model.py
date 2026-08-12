# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Round 12 — OrgProfile seeding into dialogue slots and NLU bias."""

from __future__ import annotations

from typing import Any

import pytest

from crp_comply.agent.dialogue import (
    DialogueStateTracker,
    UserModel,
    _profile_to_slots,
)
from crp_comply.agent.nlu import NluEngine


SAMPLE_PROFILE: dict[str, Any] = {
    "org_name": "Acme AI",
    "actor": "provider",
    "jurisdictions": ["EU", "UK"],
    "system_category": "recruitment tool",
    "annex_iii_row": "Annex III row 1",
    "is_high_risk": True,
    "is_gpai": False,
    "processes_personal_data": True,
    "biometric": True,
}


def test_profile_to_slots_maps_fields() -> None:
    slots = _profile_to_slots(SAMPLE_PROFILE)
    assert slots["org_name"] == "Acme AI"
    assert slots["system_type"] == "provider"
    assert slots["jurisdiction"] == "EU, UK"
    assert slots["risk_class"] == "high-risk"
    assert slots["data_type"] == "biometric data"


def test_profile_to_slots_gpai_overrides_actor() -> None:
    profile = {"actor": "deployer", "is_gpai": True}
    slots = _profile_to_slots(profile)
    assert slots["system_type"] == "GPAI provider"


def test_profile_to_slots_single_jurisdiction() -> None:
    profile = {"jurisdictions": ["EU"]}
    slots = _profile_to_slots(profile)
    assert slots["jurisdiction"] == "EU"


def test_profile_to_slots_children_hint() -> None:
    profile = {"processes_personal_data": True, "children_users": True}
    slots = _profile_to_slots(profile)
    assert slots["data_type"] == "children's personal data"
    assert slots["purpose"] == "children"


def test_user_model_wrapper() -> None:
    model = UserModel(SAMPLE_PROFILE)
    slots = model.to_slots()
    assert slots["org_name"] == "Acme AI"


def test_tracker_load_user_model_fills_slots() -> None:
    tracker = DialogueStateTracker(user_id="user-1")
    tracker.load_user_model(SAMPLE_PROFILE)
    assert tracker.state.slots.get("org_name") == "Acme AI"
    assert tracker.state.slots.get("system_type") == "provider"
    assert tracker.state.slots.get("jurisdiction") == "EU, UK"
    assert tracker.state.slots.get("risk_class") == "high-risk"
    assert tracker.state.slots.get("data_type") == "biometric data"


def test_tracker_initializes_with_user_profile() -> None:
    tracker = DialogueStateTracker(user_id="user-1", user_profile=SAMPLE_PROFILE)
    assert tracker.state.slots.get("system_type") == "provider"


def test_tracker_load_user_model_does_not_overwrite_existing_slots() -> None:
    tracker = DialogueStateTracker(user_id="user-1")
    tracker.state.slots.set("system_type", "chatbot")
    tracker.load_user_model(SAMPLE_PROFILE)
    assert tracker.state.slots.get("system_type") == "chatbot"


def test_nlu_merges_filled_slots() -> None:
    engine = NluEngine()
    result = engine.parse(
        "What are the requirements?",
        filled_slots={"system_type": "provider", "jurisdiction": "EU"},
    )
    assert result.slots.get("system_type") == "provider"
    assert result.slots.get("jurisdiction") == "EU"


def test_nlu_filled_slots_do_not_override_extracted_values() -> None:
    engine = NluEngine()
    result = engine.parse(
        "What does the UK AI whitepaper say?",
        filled_slots={"jurisdiction": "EU"},
    )
    # The utterance explicitly mentions the UK; extracted value wins.
    assert result.slots.get("jurisdiction") == "uk"


def test_nlu_does_not_reask_profile_filled_slot() -> None:
    """If the profile already filled 'jurisdiction', NLU should surface it so the
    dialogue policy does not probe for it again.
    """
    engine = NluEngine()
    result = engine.parse(
        "Is my system high-risk?",
        user_profile={"jurisdictions": ["EU"]},
        filled_slots={"jurisdiction": "EU"},
    )
    assert result.slots.get("jurisdiction") == "EU"


def test_nlu_profile_bias_eu_ai() -> None:
    engine = NluEngine()
    result = engine.parse(
        "Tell me about AI compliance.",
        user_profile={"jurisdictions": ["EU"]},
    )
    # The EU bias should fill the regulation slot even though the user did not
    # name a regulation explicitly.
    assert result.slots.get("regulation") == "eu ai act"
    assert result.intent == "define"


def test_cross_user_isolation() -> None:
    """Seeding user A's profile must not leak into user B's slot board."""
    tracker_a = DialogueStateTracker(user_id="user-a", user_profile=SAMPLE_PROFILE)
    tracker_b = DialogueStateTracker(user_id="user-b")

    assert tracker_a.state.slots.get("org_name") == "Acme AI"
    assert tracker_b.state.slots.get("org_name") is None
    assert tracker_b.state.slots.get("system_type") is None


@pytest.mark.asyncio
async def test_tracker_process_utterance_uses_profile_slots() -> None:
    tracker = DialogueStateTracker(
        user_id="user-1",
        user_profile={"jurisdictions": ["EU"], "actor": "provider"},
    )
    nlu, decision = tracker.process_utterance("What are the requirements?")
    # The profile-supplied slots should be visible in the NLU result.
    assert nlu.slots.get("jurisdiction") == "EU"
    assert nlu.slots.get("system_type") == "provider"
    # With regulation + task_type inferred, the policy should not probe.
    assert decision.action != "probe" or "jurisdiction" not in (decision.args.get("missing") or [])
