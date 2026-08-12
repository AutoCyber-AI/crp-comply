"""Tests for FederatedFabric (PHASE_7 \u00a721 7.7)."""

from __future__ import annotations

import time
from typing import Any

import pytest

from crp_comply.agent.federated_fabric import (
    CKFBackend,
    Fact,
    FederatedFabric,
    FederationError,
)


# ── In-memory backend for tests ─────────────────────────────────────


class StubBackend:
    """A list-of-Facts backend that responds to every CKF mode.

    The constructor takes either a list of facts (returned for every
    mode) or a dict ``mode -> list[Fact]``. Latency simulates the
    real DB call so the parallel-execution test can assert wall-clock
    is bounded by the slower side.
    """

    def __init__(
        self,
        facts: list[Fact] | dict[str, list[Fact]] | None = None,
        latency_ms: float = 0.0,
    ) -> None:
        if isinstance(facts, dict):
            self._by_mode: dict[str, list[Fact]] = facts
            self._default: list[Fact] = []
        elif facts is None:
            self._by_mode = {}
            self._default = []
        else:
            self._by_mode = {}
            self._default = list(facts)
        self.latency_ms = latency_ms
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def _go(self, mode: str, kwargs: dict[str, Any]) -> list[Fact]:
        self.calls.append((mode, dict(kwargs)))
        if self.latency_ms:
            time.sleep(self.latency_ms / 1000.0)
        return list(self._by_mode.get(mode, self._default))

    def pattern_query(self, **kw):
        return self._go("pattern_query", kw)

    def graph_walk(self, **kw):
        return self._go("graph_walk", kw)

    def community_summary(self, **kw):
        return self._go("community_summary", kw)

    def temporal_query(self, **kw):
        return self._go("temporal_query", kw)

    def recall_facts(self, **kw):
        return self._go("recall_facts", kw)

    def semantic(self, **kw):
        return self._go("semantic", kw)


def _f(fid: str, conf: float = 0.5, **kw: Any) -> Fact:
    return Fact(
        id=fid,
        subject=kw.get("subject", "subj"),
        predicate=kw.get("predicate", "pred"),
        object=kw.get("object", f"obj-{fid}"),
        confidence=conf,
        source=kw.get("source", ""),
    )


@pytest.fixture
def captured():
    return []


# ── Protocol conformance ────────────────────────────────────────────


def test_stub_backend_satisfies_protocol():
    assert isinstance(StubBackend(), CKFBackend)


# ── Tenant ID is mandatory ──────────────────────────────────────────


def test_query_without_tenant_id_raises():
    fed = FederatedFabric(corpus=StubBackend(), tenant_factory=lambda _t: StubBackend())
    try:
        with pytest.raises(FederationError, match="tenant_id required"):
            fed.pattern_query(tenant_id="", pattern="x")
    finally:
        fed.shutdown()


# ── Fan-out + scope tagging ─────────────────────────────────────────


def test_facts_tagged_by_scope(captured):
    corpus = StubBackend([_f("c1"), _f("c2")])
    tenant = StubBackend([_f("t1")])
    fed = FederatedFabric(
        corpus=corpus,
        tenant_factory=lambda _t: tenant,
        event_sink=captured.append,
        run_id="r",
    )
    try:
        result = fed.pattern_query(tenant_id="alice", pattern="x")
    finally:
        fed.shutdown()
    by_id = {f.id: f for f in result.facts}
    assert by_id["c1"].scope == "corpus"
    assert by_id["c2"].scope == "corpus"
    assert by_id["t1"].scope == "tenant"


# ── Dedupe by Fact.id (federated tag, max confidence) ───────────────


def test_dedupe_keeps_max_confidence_and_tags_federated(captured):
    shared_low = _f("dup", conf=0.3, source="corpus-side")
    shared_high = _f("dup", conf=0.9, source="tenant-side")
    fed = FederatedFabric(
        corpus=StubBackend([shared_low, _f("c-only")]),
        tenant_factory=lambda _t: StubBackend([shared_high, _f("t-only")]),
        event_sink=captured.append,
    )
    try:
        result = fed.pattern_query(tenant_id="alice", pattern="x")
    finally:
        fed.shutdown()
    by_id = {f.id: f for f in result.facts}
    assert len(result.facts) == 3  # exactly one of the dup, plus singletons
    assert by_id["dup"].confidence == 0.9
    assert by_id["dup"].scope == "federated"
    assert by_id["c-only"].scope == "corpus"
    assert by_id["t-only"].scope == "tenant"


# ── Telemetry: per-layer events ─────────────────────────────────────


def test_emits_one_ckf_query_event_per_layer(captured):
    fed = FederatedFabric(
        corpus=StubBackend([_f("c1", conf=0.7)]),
        tenant_factory=lambda _t: StubBackend([_f("t1", conf=0.8)]),
        event_sink=captured.append,
        run_id="r",
    )
    try:
        fed.pattern_query(tenant_id="alice", pattern="x")
    finally:
        fed.shutdown()
    events = [e for e in captured if e["event"] == "loop.ckf.query"]
    scopes = sorted(e["scope"] for e in events)
    assert scopes == ["corpus", "tenant"]
    corpus_evt = next(e for e in events if e["scope"] == "corpus")
    tenant_evt = next(e for e in events if e["scope"] == "tenant")
    assert corpus_evt["mode"] == "pattern_query"
    assert corpus_evt["hits"] == 1
    assert corpus_evt["top_confidence"] == 0.7
    assert tenant_evt["hits"] == 1
    assert tenant_evt["top_confidence"] == 0.8


def test_emits_corpus_event_when_tenant_empty(captured):
    """PHASE_7 \u00a721 7.7: do *not* silently fall back \u2014 the user must
    see that corpus-only was used."""
    fed = FederatedFabric(
        corpus=StubBackend([_f("c1")]),
        tenant_factory=lambda _t: StubBackend([]),  # tenant present but empty
        event_sink=captured.append,
    )
    try:
        result = fed.pattern_query(tenant_id="alice", pattern="x")
    finally:
        fed.shutdown()
    events = [e for e in captured if e["event"] == "loop.ckf.query"]
    scopes = {e["scope"] for e in events}
    assert "corpus" in scopes and "tenant" in scopes
    tenant_evt = next(e for e in events if e["scope"] == "tenant")
    assert tenant_evt["hits"] == 0
    assert len(result.facts) == 1


def test_no_tenant_event_when_factory_returns_none(captured):
    """If the tenant has *no* CKF at all (factory returns None), we
    emit only the corpus event \u2014 there's nothing to report."""
    fed = FederatedFabric(
        corpus=StubBackend([_f("c1")]),
        tenant_factory=lambda _t: None,
        event_sink=captured.append,
    )
    try:
        fed.pattern_query(tenant_id="alice", pattern="x")
    finally:
        fed.shutdown()
    events = [e for e in captured if e["event"] == "loop.ckf.query"]
    assert [e["scope"] for e in events] == ["corpus"]


# ── Tenant isolation ────────────────────────────────────────────────


def test_factory_receives_tenant_id_and_isolates(captured):
    seen: list[str] = []

    def factory(tenant: str) -> CKFBackend:
        seen.append(tenant)
        return StubBackend([_f(f"{tenant}-fact")])

    fed = FederatedFabric(
        corpus=StubBackend([]),
        tenant_factory=factory,
        event_sink=captured.append,
    )
    try:
        a = fed.pattern_query(tenant_id="alice", pattern="x")
        b = fed.pattern_query(tenant_id="bob", pattern="x")
    finally:
        fed.shutdown()
    assert seen == ["alice", "bob"]
    a_ids = {f.id for f in a.facts}
    b_ids = {f.id for f in b.facts}
    assert a_ids == {"alice-fact"}
    assert b_ids == {"bob-fact"}
    assert a_ids.isdisjoint(b_ids)


# ── Parallelism: combined latency \u2248 max(corpus, tenant), not sum ──


def test_query_runs_layers_in_parallel():
    corpus = StubBackend([_f("c1")], latency_ms=120)
    tenant = StubBackend([_f("t1")], latency_ms=120)
    fed = FederatedFabric(
        corpus=corpus,
        tenant_factory=lambda _t: tenant,
    )
    try:
        t0 = time.perf_counter()
        fed.pattern_query(tenant_id="alice", pattern="x")
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
    finally:
        fed.shutdown()
    # Sequential would be \u2265 240ms; parallel should be < 200ms with
    # generous slack for thread pool overhead on Windows.
    assert elapsed_ms < 200, f"expected parallel fan-out, got {elapsed_ms:.1f}ms"


# ── All CKF modes route to the right backend method ─────────────────


@pytest.mark.parametrize(
    "mode",
    [
        "pattern_query",
        "graph_walk",
        "community_summary",
        "temporal_query",
        "recall_facts",
        "semantic",
    ],
)
def test_all_modes_dispatched(mode):
    corpus = StubBackend({mode: [_f(f"c-{mode}")]})
    tenant = StubBackend({mode: [_f(f"t-{mode}")]})
    fed = FederatedFabric(corpus=corpus, tenant_factory=lambda _t: tenant)
    try:
        result = getattr(fed, mode)(tenant_id="alice", q="x")
    finally:
        fed.shutdown()
    ids = {f.id for f in result.facts}
    assert ids == {f"c-{mode}", f"t-{mode}"}
    assert result.mode == mode


# ── Backend returning wrong type is rejected ────────────────────────


def test_backend_returning_non_list_raises():
    class BadBackend:
        def pattern_query(self, **_kw):
            return "not a list"

        def graph_walk(self, **_kw):
            return []

        def community_summary(self, **_kw):
            return []

        def temporal_query(self, **_kw):
            return []

        def recall_facts(self, **_kw):
            return []

        def semantic(self, **_kw):
            return []

    fed = FederatedFabric(
        corpus=BadBackend(),
        tenant_factory=lambda _t: StubBackend(),
    )
    try:
        with pytest.raises(FederationError, match="expected list"):
            fed.pattern_query(tenant_id="alice", pattern="x")
    finally:
        fed.shutdown()


# ── Result shape ────────────────────────────────────────────────────


def test_result_carries_per_layer_view_and_top_confidence():
    fed = FederatedFabric(
        corpus=StubBackend([_f("c1", conf=0.6)]),
        tenant_factory=lambda _t: StubBackend([_f("t1", conf=0.95)]),
    )
    try:
        result = fed.pattern_query(tenant_id="alice", pattern="x")
    finally:
        fed.shutdown()
    assert result.tenant_id == "alice"
    assert {f.id for f in result.per_layer["corpus"]} == {"c1"}
    assert {f.id for f in result.per_layer["tenant"]} == {"t1"}
    assert result.top_confidence == 0.95
    assert result.latency_ms >= 0
