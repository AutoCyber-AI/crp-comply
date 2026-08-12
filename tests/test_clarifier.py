"""Tests for ``ask_user`` + suspend/resume (PHASE_7 \u00a721 7.5)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from crp_comply.agent.clarifier import (
    AskUserSuspended,
    ClarifierStore,
    build_ask_user_tool,
    make_resume_token,
)
from crp_comply.agent.loop_state import LoopState, PlanStep
from crp_comply.agent.step_runner import (
    StepRunner,
    ToolError,
    build_default_registry,
)


@pytest.fixture
def store(tmp_path: Path) -> ClarifierStore:
    return ClarifierStore(db_path=tmp_path / "awaiting_user.db")


@pytest.fixture
def fsm() -> LoopState:
    return LoopState(session_id="sess-A", run_id="run-A")


# ── Resume tokens ───────────────────────────────────────────────────


def test_resume_tokens_are_unique_and_long():
    tokens = {make_resume_token() for _ in range(100)}
    assert len(tokens) == 100
    assert all(len(t) == 64 for t in tokens)  # 32 bytes hex


# ── ask_user tool: emits clarifier.ask + propagates suspend ────────


def test_ask_user_emits_clarifier_ask_and_propagates(fsm):
    captured: list[dict] = []
    reg = build_default_registry()
    token = make_resume_token()
    reg.register(build_ask_user_tool(resume_token=token))

    runner = StepRunner(registry=reg, event_sink=captured.append, run_id=fsm.run_id)
    step = PlanStep(id="s1", intent="determine processing scope")

    with pytest.raises(AskUserSuspended) as excinfo:
        runner.run_step(
            step,
            tool_calls=[
                (
                    "ask_user",
                    {
                        "question": "Do you process biometric data?",
                        "slot_id": "biometric_processing",
                        "options": ["yes", "no"],
                    },
                )
            ],
        )

    assert excinfo.value.resume_token == token
    assert excinfo.value.slot_id == "biometric_processing"
    asks = [e for e in captured if e["event"] == "loop.clarifier.ask"]
    assert len(asks) == 1
    data = asks[0]
    assert data["question"] == "Do you process biometric data?"
    assert data["resume_token"] == token
    assert data["options"] == ["yes", "no"]


# ── Persistence: round-trip ─────────────────────────────────────────


def test_store_round_trip(store: ClarifierStore, fsm: LoopState):
    token = make_resume_token()
    rec = store.suspend(
        resume_token=token,
        session_id=fsm.session_id,
        run_id=fsm.run_id,
        tenant_id="tenant-x",
        slot_id="biometric",
        question="Biometric?",
        options=["yes", "no"],
        snapshot=fsm.snapshot(),
    )
    assert rec.resume_token == token

    loaded = store.load(resume_token=token, tenant_id="tenant-x")
    assert loaded is not None
    assert loaded.question == "Biometric?"
    assert loaded.options == ["yes", "no"]
    assert loaded.snapshot["session_id"] == fsm.session_id


def test_store_survives_restart(tmp_path: Path, fsm: LoopState):
    db = tmp_path / "awaiting_user.db"
    s1 = ClarifierStore(db_path=db)
    token = make_resume_token()
    s1.suspend(
        resume_token=token,
        session_id=fsm.session_id,
        run_id=fsm.run_id,
        tenant_id="t",
        slot_id="x",
        question="q?",
        options=None,
        snapshot=fsm.snapshot(),
    )
    # Simulate a worker restart \u2014 fresh process, fresh store object.
    s2 = ClarifierStore(db_path=db)
    rec = s2.load(resume_token=token, tenant_id="t")
    assert rec is not None
    assert rec.snapshot["session_id"] == fsm.session_id


def test_store_isolates_by_tenant(store: ClarifierStore, fsm: LoopState):
    token = make_resume_token()
    store.suspend(
        resume_token=token,
        session_id=fsm.session_id,
        run_id=fsm.run_id,
        tenant_id="alice",
        slot_id="x",
        question="q?",
        options=None,
        snapshot=fsm.snapshot(),
    )
    # Bob may not see Alice's clarifier.
    assert store.load(resume_token=token, tenant_id="bob") is None
    with pytest.raises(ToolError, match="unknown resume_token"):
        store.answer(resume_token=token, tenant_id="bob", answer="hi")


def test_store_records_answer_and_blocks_replay(store: ClarifierStore, fsm: LoopState):
    token = make_resume_token()
    store.suspend(
        resume_token=token,
        session_id=fsm.session_id,
        run_id=fsm.run_id,
        tenant_id="t",
        slot_id="x",
        question="q?",
        options=None,
        snapshot=fsm.snapshot(),
    )
    rec = store.answer(resume_token=token, tenant_id="t", answer="yes")
    assert rec.answer == "yes"
    assert rec.answered_at is not None
    with pytest.raises(ToolError, match="already used"):
        store.answer(resume_token=token, tenant_id="t", answer="yes")


def test_store_unknown_token_raises(store: ClarifierStore):
    with pytest.raises(ToolError, match="unknown resume_token"):
        store.answer(resume_token="deadbeef", tenant_id="t", answer="x")


def test_store_pending_for_session(store: ClarifierStore, fsm: LoopState):
    a = make_resume_token()
    b = make_resume_token()
    store.suspend(
        resume_token=a,
        session_id=fsm.session_id,
        run_id="run-1",
        tenant_id="t",
        slot_id="x",
        question="q1?",
        options=None,
        snapshot=fsm.snapshot(),
    )
    store.suspend(
        resume_token=b,
        session_id=fsm.session_id,
        run_id="run-2",
        tenant_id="t",
        slot_id="y",
        question="q2?",
        options=None,
        snapshot=fsm.snapshot(),
    )
    pending = store.pending_for_session(session_id=fsm.session_id, tenant_id="t")
    assert {r.resume_token for r in pending} == {a, b}
    # After answering one, only the other remains pending.
    store.answer(resume_token=a, tenant_id="t", answer="yes")
    pending = store.pending_for_session(session_id=fsm.session_id, tenant_id="t")
    assert {r.resume_token for r in pending} == {b}


def test_store_purges_old_unanswered(store: ClarifierStore, fsm: LoopState):
    token = make_resume_token()
    store.suspend(
        resume_token=token,
        session_id=fsm.session_id,
        run_id=fsm.run_id,
        tenant_id="t",
        slot_id="x",
        question="q?",
        options=None,
        snapshot=fsm.snapshot(),
    )
    # Force the row's created_at into the past.
    with store._connect() as conn:
        conn.execute(
            "UPDATE awaiting_user SET created_at = ? WHERE resume_token = ?",
            (time.time() - 86_400, token),
        )
        conn.commit()
    dropped = store.purge_older_than(3600)
    assert dropped == 1
    assert store.load(resume_token=token, tenant_id="t") is None


def test_store_requires_tenant_and_session(store: ClarifierStore, fsm):
    with pytest.raises(ToolError, match="tenant_id required"):
        store.suspend(
            resume_token=make_resume_token(),
            session_id=fsm.session_id,
            run_id=fsm.run_id,
            tenant_id="",
            slot_id="x",
            question="q?",
            options=None,
            snapshot=fsm.snapshot(),
        )
    with pytest.raises(ToolError, match="session_id"):
        store.suspend(
            resume_token=make_resume_token(),
            session_id="",
            run_id=fsm.run_id,
            tenant_id="t",
            slot_id="x",
            question="q?",
            options=None,
            snapshot=fsm.snapshot(),
        )


# ── End-to-end: suspend, restart, resume ────────────────────────────


def test_e2e_suspend_kill_resume(tmp_path: Path, fsm: LoopState):
    """Simulate the spec's restart scenario: ask_user \u2192 persist \u2192
    drop the worker process \u2192 a fresh worker can resume the loop.
    """
    db = tmp_path / "awaiting_user.db"

    # --- Worker A: receives the question and persists --------------
    captured: list[dict] = []
    reg = build_default_registry()
    token = make_resume_token()
    reg.register(build_ask_user_tool(resume_token=token))
    runner = StepRunner(registry=reg, event_sink=captured.append, run_id=fsm.run_id)
    step = PlanStep(id="s1", intent="scope")

    fsm.set_plan(
        __import__("crp_comply.agent.loop_state", fromlist=["Plan"]).Plan(
            steps=(step,), should_loop=True
        )
    )
    fsm.transition(
        __import__("crp_comply.agent.loop_state", fromlist=["LoopStateName"]).LoopStateName.STEP
    )
    fsm.transition(
        __import__("crp_comply.agent.loop_state", fromlist=["LoopStateName"]).LoopStateName.ACTING
    )

    with pytest.raises(AskUserSuspended) as excinfo:
        runner.run_step(
            step,
            tool_calls=[
                (
                    "ask_user",
                    {
                        "question": "What jurisdiction?",
                        "slot_id": "jurisdiction",
                    },
                )
            ],
        )

    store_a = ClarifierStore(db_path=db)
    fsm.transition(
        __import__(
            "crp_comply.agent.loop_state", fromlist=["LoopStateName"]
        ).LoopStateName.AWAITING_USER,
        reason="ask_user",
    )
    fsm.record_clarifier()
    store_a.suspend(
        resume_token=excinfo.value.resume_token,
        session_id=fsm.session_id,
        run_id=fsm.run_id,
        tenant_id="t",
        slot_id=excinfo.value.slot_id,
        question=excinfo.value.question,
        options=excinfo.value.options,
        snapshot=fsm.snapshot(),
    )

    # --- Worker B: brand new process, only knows the token ---------
    store_b = ClarifierStore(db_path=db)
    rec = store_b.load(resume_token=excinfo.value.resume_token, tenant_id="t")
    assert rec is not None
    assert rec.question == "What jurisdiction?"
    assert rec.snapshot["state"] == "AWAITING_USER"
    assert rec.snapshot["session_id"] == fsm.session_id
    # Worker B records the answer; the orchestrator would now
    # rebuild a LoopState from rec.snapshot and resume from STEP.
    answered = store_b.answer(resume_token=rec.resume_token, tenant_id="t", answer="EU")
    assert answered.answer == "EU"


# ── Clarifier budget enforcement ────────────────────────────────────


def test_clarifier_budget_capped_at_six(fsm):
    for _ in range(6):
        fsm.record_clarifier()
    assert fsm.clarifier_count == 6
    with pytest.raises(Exception):  # LoopStateError, by 7.3 contract
        fsm.record_clarifier()
