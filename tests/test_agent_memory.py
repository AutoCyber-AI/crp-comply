# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Unit tests for the Round 4 CRPv4 memory substrate adapter."""

from pathlib import Path

import pytest

from crp_comply.agent.memory import CompliantMemory


@pytest.fixture
def tmp_data(tmp_path: Path) -> Path:
    return tmp_path / "data"


def test_memory_loads_blank_when_missing(tmp_data: Path) -> None:
    mem = CompliantMemory(user_id="u1", session_id="s1", data_dir=tmp_data)
    assert mem.user_id == "u1"
    assert mem.session_id == "s1"
    assert mem.recent_turns() == []
    assert mem.current_slots() == {}


def test_memory_persists_turns(tmp_data: Path) -> None:
    mem = CompliantMemory(user_id="u1", session_id="s1", data_dir=tmp_data)
    tid1 = mem.add_turn("user", "Classify my system")
    tid2 = mem.add_turn("agent", "What system type?")
    mem.save()

    loaded = CompliantMemory(user_id="u1", session_id="s1", data_dir=tmp_data)
    turns = loaded.recent_turns()
    assert len(turns) == 2
    assert turns[0]["role"] == "user"
    assert turns[1]["role"] == "agent"
    assert tid1 == 1
    assert tid2 == 2


def test_memory_cognitive_state_and_slots(tmp_data: Path) -> None:
    mem = CompliantMemory(user_id="u1", session_id="s1", data_dir=tmp_data)
    mem.update_cognitive_state(
        slots={"system_type": "hiring assistant", "jurisdiction": "EU"},
        intent="scope",
        open_questions=["What data does it process?"],
    )
    mem.save()

    loaded = CompliantMemory(user_id="u1", session_id="s1", data_dir=tmp_data)
    slots = loaded.current_slots()
    assert slots.get("system_type") == "hiring assistant"
    assert slots.get("jurisdiction") == "EU"
    assert "scope" in loaded.to_extra_context()
    assert "What data does it process?" in loaded.to_extra_context()


def test_memory_profile_tier(tmp_data: Path) -> None:
    mem = CompliantMemory(user_id="u1", session_id="s1", data_dir=tmp_data)
    mem.set_profile({"actor": "processor", "jurisdictions": ["EU", "UK"]})
    ctx = mem.to_extra_context()
    assert "Organisation profile" in ctx
    assert "EU" in ctx


def test_memory_migrate_from_flat_record(tmp_data: Path) -> None:
    mem = CompliantMemory(user_id="u1", session_id="s1", data_dir=tmp_data)
    old_record = {
        "messages": [
            {"role": "user", "content": "Classify my system"},
            {"role": "agent", "content": "What type?"},
        ],
        "slots": {"system_type": "hiring assistant"},
        "clarifications": ["What jurisdiction?"],
    }
    mem.migrate_from_flat_record(old_record)

    turns = mem.recent_turns()
    assert len(turns) == 2
    assert turns[0]["content"] == "Classify my system"
    ctx = mem.to_extra_context()
    assert "hiring assistant" in ctx
    assert "What jurisdiction?" in ctx
