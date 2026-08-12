"""Tests for continuation state persistence/resume (Phase 6, Round 6)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from crp_comply.agent.crp_integration import continue_truncated_answer
from crp_comply.agent.memory import CompliantMemory


def test_continue_truncated_answer_calls_on_window_each_window() -> None:
    """The continuation hook receives the current window list after every
    new window, including the initial first_window."""
    calls: list[list[str]] = []

    def continue_fn(last: str) -> tuple[str, str | None]:
        return (f"{last} more", "stop")

    outcome = continue_truncated_answer(
        "hello",
        continue_fn,
        max_windows=3,
        on_window=lambda windows: calls.append(list(windows)),
    )

    assert outcome.windows == 2
    assert len(calls) == 2
    assert calls[0] == ["hello"]
    assert calls[1] == ["hello", "hello more"]


def test_compliant_memory_persists_continuation_state(tmp_path: Path) -> None:
    """Continuation state round-trips through CompliantMemory save/load."""
    data_dir = tmp_path / "data"
    mem = CompliantMemory(
        user_id="u1",
        session_id="continuation-s1",
        data_dir=data_dir,
    )
    state: dict[str, Any] = {
        "partial_answer": "partial answer text",
        "windows": ["partial answer text", "more text"],
        "envelope": [{"role": "user", "content": "task"}],
        "task_input": "task",
        "remaining_windows": 2,
        "max_total_chars": 40_000,
    }
    mem.save_continuation_state(state)

    # Simulate server restart: fresh CompliantMemory loads the saved record.
    mem2 = CompliantMemory(
        user_id="u1",
        session_id="continuation-s1",
        data_dir=data_dir,
    )
    loaded = mem2.load_continuation_state()
    assert loaded is not None
    assert loaded["partial_answer"] == state["partial_answer"]
    assert loaded["windows"] == state["windows"]
    assert loaded["remaining_windows"] == 2
    assert "updated_at" in loaded

    mem2.clear_continuation_state()
    mem3 = CompliantMemory(
        user_id="u1",
        session_id="continuation-s1",
        data_dir=data_dir,
    )
    assert mem3.load_continuation_state() is None
