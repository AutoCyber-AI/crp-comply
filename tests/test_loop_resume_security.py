"""Resume-token security tests (PHASE_7 §21 7.12).

These complement existing single-use / cross-tenant coverage by
exercising the new 24h TTL.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from crp_comply.agent.clarifier import ClarifierStore, ToolError


@pytest.fixture
def store(tmp_path: Path) -> ClarifierStore:
    return ClarifierStore(
        db_path=tmp_path / "awaiting.db",
        token_ttl_seconds=1.0,
    )


def _suspend(store: ClarifierStore, *, token: str = "tok") -> None:
    store.suspend(
        resume_token=token,
        session_id="s1",
        run_id="r1",
        tenant_id="t1",
        slot_id="slot1",
        question="purpose?",
        options=None,
        snapshot={"x": 1},
    )


def test_load_returns_none_after_ttl(store: ClarifierStore) -> None:
    _suspend(store)
    # Inside TTL.
    rec = store.load(resume_token="tok", tenant_id="t1")
    assert rec is not None and rec.slot_id == "slot1"
    time.sleep(1.1)
    assert store.load(resume_token="tok", tenant_id="t1") is None


def test_answer_after_ttl_returns_unknown(store: ClarifierStore) -> None:
    _suspend(store)
    time.sleep(1.1)
    with pytest.raises(ToolError) as exc_info:
        store.answer(resume_token="tok", tenant_id="t1", answer="my answer")
    # Must NOT reveal that the token was once valid.
    assert "expired" not in str(exc_info.value).lower()
    assert "unknown" in str(exc_info.value).lower()


def test_zero_ttl_disables_expiry(tmp_path: Path) -> None:
    store = ClarifierStore(
        db_path=tmp_path / "awaiting.db",
        token_ttl_seconds=0,
    )
    store.suspend(
        resume_token="tok",
        session_id="s1",
        run_id="r1",
        tenant_id="t1",
        slot_id="slot1",
        question="purpose?",
        options=None,
        snapshot={},
    )
    time.sleep(0.05)
    rec = store.load(resume_token="tok", tenant_id="t1")
    assert rec is not None


def test_default_ttl_is_24h() -> None:
    s = ClarifierStore(db_path=Path("/tmp/_does_not_matter.db"))
    assert s.token_ttl_seconds == 24 * 60 * 60


def test_cross_tenant_load_returns_none_even_within_ttl(
    store: ClarifierStore,
) -> None:
    _suspend(store)
    assert store.load(resume_token="tok", tenant_id="other") is None
