"""Tests for the loop telemetry / replay store (PHASE_7 §21 7.12)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crp_comply.agent.telemetry import LoopTelemetry


@pytest.fixture
def tel(tmp_path: Path) -> LoopTelemetry:
    root = tmp_path / "loop_runs"
    root.mkdir(parents=True, exist_ok=True)
    return LoopTelemetry(root=root)


def _opened(run_id: str = "r1") -> dict:
    return {
        "event": "loop.opened",
        "ts": 1717070000.0,
        "run_id": run_id,
        "session_id": "s1",
        "query": "draft FRIA",
        "model": "gpt-4o-mini",
    }


def _final(run_id: str = "r1") -> dict:
    return {
        "event": "loop.final",
        "ts": 1717070100.0,
        "run_id": run_id,
        "summary": "done",
        "total_steps": 2,
    }


def test_open_store_replay_round_trip(tel: LoopTelemetry) -> None:
    tel.open_run(run_id="r1", session_id="s1", tenant_id="t1")
    tel.store_event(run_id="r1", tenant_id="t1", event=_opened())
    tel.store_event(run_id="r1", tenant_id="t1", event=_final())
    tel.close_run(run_id="r1", tenant_id="t1")

    events = tel.replay(run_id="r1", tenant_id="t1")
    assert [e["event"] for e in events] == ["loop.opened", "loop.final"]
    assert events[0]["query"] == "draft FRIA"
    assert events[1]["total_steps"] == 2

    rec = tel.find_run(run_id="r1", tenant_id="t1")
    assert rec is not None
    assert rec.session_id == "s1"
    assert rec.closed_at is not None


def test_cross_tenant_replay_returns_empty(tel: LoopTelemetry) -> None:
    tel.open_run(run_id="r1", session_id="s1", tenant_id="t1")
    tel.store_event(run_id="r1", tenant_id="t1", event=_opened())

    assert tel.replay(run_id="r1", tenant_id="t2") == []
    assert tel.find_run(run_id="r1", tenant_id="t2") is None


def test_unknown_run_returns_empty(tel: LoopTelemetry) -> None:
    assert tel.replay(run_id="missing", tenant_id="t1") == []
    assert tel.find_run(run_id="missing", tenant_id="t1") is None


def test_corrupt_jsonl_lines_are_skipped(tel: LoopTelemetry) -> None:
    tel.open_run(run_id="r1", session_id="s1", tenant_id="t1")
    tel.store_event(run_id="r1", tenant_id="t1", event=_opened())
    # Inject garbage line directly.
    path = tel.root / "t1" / "r1.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write("{not valid json\n")
        fh.write("\n")
    tel.store_event(run_id="r1", tenant_id="t1", event=_final())

    events = tel.replay(run_id="r1", tenant_id="t1")
    assert [e["event"] for e in events] == ["loop.opened", "loop.final"]


def test_close_after_open_records_closed_at(tel: LoopTelemetry) -> None:
    tel.open_run(run_id="r1", session_id="s1", tenant_id="t1")
    rec1 = tel.find_run(run_id="r1", tenant_id="t1")
    assert rec1 is not None and rec1.closed_at is None
    tel.close_run(run_id="r1", tenant_id="t1")
    rec2 = tel.find_run(run_id="r1", tenant_id="t1")
    assert rec2 is not None and rec2.closed_at is not None


def test_store_event_ignores_malformed_event(tel: LoopTelemetry) -> None:
    tel.open_run(run_id="r1", session_id="s1", tenant_id="t1")
    tel.store_event(run_id="r1", tenant_id="t1", event={})
    tel.store_event(run_id="r1", tenant_id="t1", event={"event": "", "ts": 0})
    tel.store_event(run_id="", tenant_id="t1", event=_opened())
    assert tel.replay(run_id="r1", tenant_id="t1") == []


def test_tenant_dir_path_traversal_safe(tel: LoopTelemetry) -> None:
    """Tenant ids with slashes/dots must not escape the root."""
    bad = "../../etc"
    tel.open_run(run_id="r1", session_id="s1", tenant_id=bad)
    tel.store_event(run_id="r1", tenant_id=bad, event=_opened())
    # No file outside the root.
    for child in tel.root.iterdir():
        assert child.is_dir()
        # Sanitised name cannot equal the literal bad value.
        assert child.name != bad
        assert ".." not in child.name


def test_sealed_mode_round_trip(tel: LoopTelemetry, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRP_COMPLY_LOOP_TELEMETRY_SEAL", "1")

    tel.open_run(run_id="r1", session_id="s1", tenant_id="t1")
    tel.store_event(run_id="r1", tenant_id="t1", event=_opened())

    # Raw JSONL must NOT contain the plaintext payload key "query".
    raw = (tel.root / "t1" / "r1.jsonl").read_text(encoding="utf-8")
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    assert all("envelope" in r for r in rows)
    assert "draft FRIA" not in raw

    # Replay decrypts.
    events = tel.replay(run_id="r1", tenant_id="t1")
    assert events[0]["query"] == "draft FRIA"
