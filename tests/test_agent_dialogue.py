# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Unit tests for the Round 3 / Round 7 dialogue manager."""

from __future__ import annotations

import pytest

from crp_comply.agent.dialogue import (
    DialoguePolicy,
    DialogueState,
    DialogueStateTracker,
    FormOrchestrator,
    NluEngine,
)


@pytest.fixture
def policy() -> DialoguePolicy:
    return DialoguePolicy()


@pytest.fixture
def form(policy: DialoguePolicy) -> FormOrchestrator:
    return FormOrchestrator(policy)


@pytest.fixture
def tracker() -> DialogueStateTracker:
    return DialogueStateTracker(user_id="u-test")


def test_policy_probe_when_slots_missing(policy: DialoguePolicy) -> None:
    nlu = NluEngine().parse("Draft a DPIA")
    state = DialogueState()
    decision = policy.decide(nlu, state)
    assert decision.action == "probe"
    assert "regulation" in decision.args["missing"]


def test_policy_produce_artefact_when_slots_filled(policy: DialoguePolicy) -> None:
    nlu = NluEngine().parse("Draft a GDPR DPIA for my hiring assistant")
    state = DialogueState()
    decision = policy.decide(nlu, state)
    # Slots are present but unconfirmed, so the policy asks for confirmation.
    assert decision.action == "confirm"
    assert decision.options is not None
    assert "Yes, that's right" in decision.options
    assert decision.args["slots"]["task_type"] == "dpia"


def test_policy_confirms_then_continues(policy: DialoguePolicy) -> None:
    nlu = NluEngine().parse("Draft a GDPR DPIA for my hiring assistant")
    state = DialogueState()
    policy.decide(nlu, state)
    state.confirmed = True
    decision = policy.decide(nlu, state)
    assert decision.action == "produce_artefact"
    assert decision.requires_llm is True


def test_policy_define_intent(policy: DialoguePolicy) -> None:
    nlu = NluEngine().parse("What is the EU AI Act?")
    state = DialogueState()
    decision = policy.decide(nlu, state)
    assert decision.action == "define"
    assert decision.requires_llm is True


def test_policy_repair_on_contradiction(policy: DialoguePolicy) -> None:
    state = DialogueState()
    state.slots.set("regulation", "gdpr")
    nlu = NluEngine().parse("Under the EU AI Act")  # contradicts existing slot
    decision = policy.decide(nlu, state, prior_slots={"regulation": "gdpr"})
    assert decision.action == "repair"
    assert decision.args["slot"] == "regulation"
    assert decision.args["reason"] == "contradiction"


def test_policy_repair_on_vague_value(policy: DialoguePolicy) -> None:
    state = DialogueState()
    nlu = NluEngine().parse("Draft a DPIA")
    nlu.slots["regulation"] = "idk"
    decision = policy.decide(nlu, state)
    assert decision.action == "repair"
    assert decision.args["reason"] == "vague"


def test_form_updates_slots_and_decides(form: FormOrchestrator) -> None:
    nlu = NluEngine().parse("It processes CVs in the EU")
    state = DialogueState()
    decision = form.decide(nlu, state)
    assert state.slots.get("data_type") == "cv"
    assert state.slots.get("jurisdiction") == "eu"
    assert state.current_intent == nlu.intent
    # Without a known intent, the policy delegates to the reasoner.
    assert decision.action == "delegate_reasoner"


def test_state_persistence_round_trip(tracker: DialogueStateTracker) -> None:
    tracker.process_utterance("Draft a GDPR DPIA")
    tracker.add_agent_turn("Which system is this for?")
    data = tracker.state.to_dict()
    assert data["current_intent"] == "produce_artefact"
    assert data["slots"]["regulation"] == "gdpr"
    assert len(data["history"]) == 2
    assert "confirmed" in data


def test_tracker_probe_flow(tracker: DialogueStateTracker) -> None:
    _, decision = tracker.process_utterance("Draft a DPIA")
    assert decision.action == "probe"
    assert tracker.state.pending_clarification == "regulation"


def test_tracker_fill_then_answer(tracker: DialogueStateTracker) -> None:
    tracker.process_utterance("Draft a GDPR DPIA for my hiring assistant")
    tracker.state.confirmed = True
    _, decision = tracker.process_utterance("It is deployed in the EU")
    assert decision.action == "produce_artefact"
    assert tracker.state.slots.get("jurisdiction") == "eu"


def test_confirmation_composer_includes_slots(policy: DialoguePolicy) -> None:
    nlu = NluEngine().parse("Draft a GDPR DPIA for my hiring assistant")
    state = DialogueState()
    decision = policy.decide(nlu, state)
    assert decision.action == "confirm"
    assert "GDPR" in decision.reply_text or "gdpr" in decision.reply_text
    assert "DPIA" in decision.reply_text or "dpia" in decision.reply_text


# ── Round 7 — resume / confirm / repair ───────────────────────────────────


def test_tracker_confirm_yes_proceeds(tracker: DialogueStateTracker) -> None:
    _, decision = tracker.process_utterance("Draft a GDPR DPIA for my hiring assistant")
    assert decision.action == "confirm"
    next_decision = tracker.resume("Yes, that's right")
    assert next_decision is None
    assert tracker.state.confirmed is True
    assert tracker.state.confirmed_slots.get("regulation") == "gdpr"
    assert tracker.state.confirmed_slots.get("task_type") == "dpia"


def test_tracker_confirm_no_asks_which_slot_to_correct(tracker: DialogueStateTracker) -> None:
    _, decision = tracker.process_utterance("Draft a GDPR DPIA for my hiring assistant")
    assert decision.action == "confirm"
    next_decision = tracker.resume("No, let me correct it")
    assert next_decision is not None
    assert next_decision.action == "repair"
    assert "Which detail" in next_decision.reply_text
    assert next_decision.options
    assert any("Regulation" in opt for opt in next_decision.options)


def test_tracker_confirm_no_select_slot_then_rephrase(tracker: DialogueStateTracker) -> None:
    tracker.process_utterance("Draft a GDPR DPIA for my hiring assistant")
    tracker.resume("No, let me correct it")
    probe = tracker.resume("Correct Regulation")
    assert probe is not None
    assert probe.action == "probe"
    assert probe.args.get("slot") == "regulation"

    # Answer the rephrase probe.
    final = tracker.resume("EU AI Act")
    assert final is not None
    assert tracker.state.slots.get("regulation") == "eu ai act"


def test_tracker_repair_contradiction_keep_original(tracker: DialogueStateTracker) -> None:
    # Establish a regulation slot and then contradict it.
    tracker.process_utterance("Draft a GDPR DPIA")
    _, decision = tracker.process_utterance("It is regulated under the EU AI Act")
    assert decision.action == "repair"
    assert decision.args["reason"] == "contradiction"

    _ = tracker.resume("Keep the original value")
    # The original GDPR value is preserved.
    assert tracker.state.slots.get("regulation") == "gdpr"
    assert tracker.state.repair_history
    assert tracker.state.repair_history[-1]["final"] == "gdpr"


def test_tracker_repair_vague_then_rephrase(tracker: DialogueStateTracker) -> None:
    _, decision = tracker.process_utterance("Draft a DPIA")
    # Force a vague regulation value to trigger the repair branch.
    tracker.state.slots.set("regulation", "idk")
    tracker.state.pending_decision = None
    nlu = NluEngine().parse("Draft a DPIA")
    nlu.slots["regulation"] = "idk"
    decision = tracker.policy.decide(nlu, tracker.state, prior_slots={"task_type": "dpia"})
    tracker.state.pending_decision = decision.to_dict()
    assert decision.action == "repair"
    assert decision.args["reason"] == "vague"

    probe = tracker.resume("Let me rephrase")
    assert probe is not None
    assert probe.action == "probe"
    assert probe.args.get("slot") == "regulation"

    _ = tracker.resume("GDPR")
    assert tracker.state.slots.get("regulation") == "gdpr"
