# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for the Programme lifecycle store (Gap #5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from crp_comply.programme.lifecycle import (
    InvalidTransition,
    LifecycleState,
    ProgrammeStore,
)


@pytest.fixture
def store(tmp_path: Path) -> ProgrammeStore:
    return ProgrammeStore(data_dir=tmp_path)


def test_initial_transition_creates_record(store: ProgrammeStore) -> None:
    rec = store.transition(
        user_id="u1",
        obligation_id="iso_42001",
        recipe_id="iso_42001",
        new_state=LifecycleState.INTERVIEW_IN_PROGRESS,
        reason="kickoff",
    )
    assert rec.state == LifecycleState.INTERVIEW_IN_PROGRESS.value
    assert len(rec.history) == 1
    assert rec.history[0]["reason"] == "kickoff"


def test_legal_transition_chain(store: ProgrammeStore) -> None:
    chain = [
        LifecycleState.INTERVIEW_IN_PROGRESS,
        LifecycleState.AWAITING_ANSWER,
        LifecycleState.WAITING_ON_ARTEFACT,
        LifecycleState.DRAFT_READY,
        LifecycleState.SIGNED,
    ]
    for st in chain:
        store.transition(
            user_id="u1",
            obligation_id="ob1",
            recipe_id="r1",
            new_state=st,
        )
    rec = store.get("u1", "ob1")
    assert rec is not None
    assert rec.state == LifecycleState.SIGNED.value
    assert len(rec.history) == 5


def test_illegal_transition_rejected(store: ProgrammeStore) -> None:
    store.transition(
        user_id="u1",
        obligation_id="ob1",
        recipe_id="r1",
        new_state=LifecycleState.INTERVIEW_IN_PROGRESS,
    )
    # cannot jump straight to SIGNED from INTERVIEW_IN_PROGRESS
    with pytest.raises(InvalidTransition):
        store.transition(
            user_id="u1",
            obligation_id="ob1",
            recipe_id="r1",
            new_state=LifecycleState.SIGNED,
        )


def test_signed_can_only_become_stale(store: ProgrammeStore) -> None:
    for st in (
        LifecycleState.INTERVIEW_IN_PROGRESS,
        LifecycleState.DRAFT_READY,
        LifecycleState.SIGNED,
    ):
        store.transition(user_id="u1", obligation_id="ob1", recipe_id="r1", new_state=st)
    with pytest.raises(InvalidTransition):
        store.transition(
            user_id="u1", obligation_id="ob1", recipe_id="r1", new_state=LifecycleState.DRAFT_READY
        )
    rec = store.transition(
        user_id="u1", obligation_id="ob1", recipe_id="r1", new_state=LifecycleState.STALE
    )
    assert rec.state == LifecycleState.STALE.value


def test_tenant_isolation(store: ProgrammeStore) -> None:
    store.transition(
        user_id="alice", obligation_id="ob1", recipe_id="r1", new_state=LifecycleState.DRAFT_READY
    )
    store.transition(
        user_id="bob",
        obligation_id="ob1",
        recipe_id="r1",
        new_state=LifecycleState.INTERVIEW_IN_PROGRESS,
    )
    a = store.list("alice")
    b = store.list("bob")
    assert len(a) == 1 and a[0].state == LifecycleState.DRAFT_READY.value
    assert len(b) == 1 and b[0].state == LifecycleState.INTERVIEW_IN_PROGRESS.value


def test_persistence_across_instances(tmp_path: Path) -> None:
    s1 = ProgrammeStore(data_dir=tmp_path)
    s1.transition(
        user_id="u1", obligation_id="ob1", recipe_id="r1", new_state=LifecycleState.DRAFT_READY
    )
    s2 = ProgrammeStore(data_dir=tmp_path)
    rec = s2.get("u1", "ob1")
    assert rec is not None
    assert rec.state == LifecycleState.DRAFT_READY.value


def test_mark_stale_helper(store: ProgrammeStore) -> None:
    store.transition(
        user_id="u1", obligation_id="ob1", recipe_id="r1", new_state=LifecycleState.DRAFT_READY
    )
    store.transition(
        user_id="u1", obligation_id="ob1", recipe_id="r1", new_state=LifecycleState.SIGNED
    )
    rec = store.mark_stale(user_id="u1", obligation_id="ob1", reason="artefact-rotated")
    assert rec is not None
    assert rec.state == LifecycleState.STALE.value
    assert rec.history[-1]["reason"] == "artefact-rotated"


def test_delete_returns_false_when_missing(store: ProgrammeStore) -> None:
    assert store.delete("u1", "nope") is False
    store.transition(
        user_id="u1", obligation_id="ob1", recipe_id="r1", new_state=LifecycleState.DRAFT_READY
    )
    assert store.delete("u1", "ob1") is True
    assert store.get("u1", "ob1") is None
