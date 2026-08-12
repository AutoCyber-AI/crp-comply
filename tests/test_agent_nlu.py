# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Unit tests for the Round 3 NLU layer."""

import pytest

from crp_comply.agent.nlu import NluEngine, NluEntity, SlotBoard


@pytest.fixture
def engine() -> NluEngine:
    return NluEngine()


def test_empty_input_returns_unknown(engine: NluEngine) -> None:
    result = engine.parse("")
    assert result.intent == "unknown"
    assert result.entities == []
    assert result.slots == {}


def test_produce_artefact_intent(engine: NluEngine) -> None:
    result = engine.parse("Draft a DPIA for my HR hiring assistant")
    assert result.intent == "produce_artefact"
    assert result.intent_confidence == pytest.approx(0.9)
    assert result.slots.get("task_type") == "dpia"
    assert result.slots.get("system_type") == "hiring assistant"


def test_compare_intent(engine: NluEngine) -> None:
    result = engine.parse("Compare GDPR and the EU AI Act")
    assert result.intent == "compare"
    assert "gdpr" in [e.value for e in result.entities if e.type == "regulation"]
    assert "eu ai act" in [e.value for e in result.entities if e.type == "regulation"]


def test_define_intent_from_regulation(engine: NluEngine) -> None:
    result = engine.parse("What is ISO 42001?")
    assert result.intent == "define"
    assert result.slots.get("regulation") == "iso 42001"


def test_entity_extraction_jurisdiction_and_data(engine: NluEngine) -> None:
    result = engine.parse("It processes CVs and scores candidates in the EU")
    assert result.slots.get("jurisdiction") == "eu"
    assert result.slots.get("data_type") == "cv"
    assert result.slots.get("purpose") == "scoring candidates"


def test_sentiment_negative(engine: NluEngine) -> None:
    result = engine.parse("This answer is terrible and useless")
    assert result.sentiment == "negative"
    assert result.sentiment_score < 0


def test_sentiment_positive(engine: NluEngine) -> None:
    result = engine.parse("Thanks, that was very helpful and great")
    assert result.sentiment == "positive"
    assert result.sentiment_score > 0


def test_coreference_repair(engine: NluEngine) -> None:
    last = [NluEntity(type="system_type", value="hiring assistant", span=(0, 0))]
    result = engine.parse("It processes CVs", last_entities=last)
    assert "hiring assistant" in result.coreferred_text


def test_slot_board() -> None:
    board = SlotBoard()
    board.set("regulation", "gdpr")
    assert board.get("regulation") == "gdpr"
    assert board.missing(["regulation", "system_type"]) == ["system_type"]

    data = board.to_dict()
    restored = SlotBoard.from_dict(data)
    assert restored.get("regulation") == "gdpr"


def test_llm_fallback_used_for_missing_slots(monkeypatch: pytest.MonkeyPatch) -> None:
    called_with: list[tuple[str, list[str]]] = []

    def fake_llm(text: str, missing: list[str]) -> dict[str, str]:
        called_with.append((text, missing))
        return {"system_type": "chatbot"}

    engine = NluEngine(llm_fallback=fake_llm)
    result = engine.parse("Tell me about GDPR", required_slots=["system_type"])
    assert result.slots.get("system_type") == "chatbot"
    assert called_with


@pytest.mark.parametrize(
    "text,expected_depth",
    [
        ("Give me a brief summary of GDPR", "brief"),
        ("What is the EU AI Act?", ""),
        ("Explain the EU AI Act thoroughly", "thorough"),
        ("Give me a step by step DPIA guide", "thorough"),
        ("Short answer: does GDPR apply?", "brief"),
    ],
)
def test_extract_depth_slot(engine: NluEngine, text: str, expected_depth: str) -> None:
    result = engine.parse(text)
    assert result.slots.get("depth") == (expected_depth or None)


def test_extract_format_slot(engine: NluEngine) -> None:
    assert engine.parse("Give me a checklist for GDPR").slots.get("format") == "checklist"
    assert engine.parse("Summarise the EU AI Act").slots.get("format") == "summary"
    assert engine.parse("What is ISO 42001?").slots.get("format") is None


def test_extract_audience_slot(engine: NluEngine) -> None:
    assert engine.parse("Explain to my engineering team").slots.get("audience") == "engineer"
    assert engine.parse("Board-level summary of DORA").slots.get("audience") == "executive"


def test_extract_urgency_slot(engine: NluEngine) -> None:
    assert engine.parse("Urgent: is my system high-risk?").slots.get("urgency") == "high"
    assert engine.parse("No rush, just curious").slots.get("urgency") == "low"


def test_extract_satisfaction_criteria(engine: NluEngine) -> None:
    result = engine.parse(
        "Compare GDPR and the AI Act. It must include fines and extra-territorial scope."
    )
    criteria = result.slots.get("satisfaction_criteria") or []
    assert any("must include" in c.lower() for c in criteria)
    assert any("compare" in c.lower() for c in criteria)
