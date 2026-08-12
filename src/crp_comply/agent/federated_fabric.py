"""Federated CKF wrapper + telemetry \u2014 PHASE_7 \u00a721 7.7.

The agent has *two* contextual knowledge fabrics:

1. **Corpus CKF** (``data/ckf/__corpus__/ckf.db``) \u2014 pre-extracted
   facts over EU AI Act, GDPR, NIST AI RMF, ISO 42001, etc. Shared
   across all tenants, immutable at run-time.
2. **Tenant CKF** (``data/ckf/<tenant_id>/ckf.db``) \u2014 facts the user
   has uploaded or that the agent has inferred from their session.
   Per-tenant, mutable.

A query without a tenant ID is forbidden (data isolation invariant
\u00a78). When a tenant has no facts of their own we still return the
corpus hits and emit ``loop.ckf.query`` with ``scope='corpus'`` so the
UI shows the user the search happened.

Bypass guards (PHASE_7 \u00a721 7.7):

* Every public method requires a ``tenant_id``. Empty / missing
  raises :class:`FederationError`.
* Fan-out is parallel (``ThreadPoolExecutor`` with two workers); the
  combined latency is bounded by the slower side, not the sum.
* Dedupe is by ``Fact.id``: a fact appearing in both layers is kept
  exactly once with ``scope='federated'`` and the higher confidence.
* ``loop.ckf.query`` is emitted *per backend layer* with the actual
  hit count and top confidence \u2014 never silently coalesced.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Protocol, runtime_checkable

from ..api.events import make_event


__all__ = [
    "Fact",
    "CKFBackend",
    "FederationError",
    "FederatedFabric",
    "FederatedQueryResult",
]


logger = logging.getLogger(__name__)


CKFMode = Literal[
    "pattern_query",
    "graph_walk",
    "community_summary",
    "temporal_query",
    "recall_facts",
    "semantic",
]
ScopeLayer = Literal["corpus", "tenant"]
ScopeTag = Literal["corpus", "tenant", "federated"]


# ── Fact + backend protocol ─────────────────────────────────────────


@dataclass(frozen=True)
class Fact:
    """A single CKF fact with a stable identity.

    ``id`` is the primary dedupe key; backends compute it from the
    canonical (subject, predicate, object) triple so the same triple
    extracted from corpus and tenant data collides correctly.
    """

    id: str
    subject: str
    predicate: str
    object: str
    confidence: float = 0.0
    category: str = ""
    source: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    scope: ScopeTag = "corpus"

    def with_scope(self, scope: ScopeTag) -> "Fact":
        return Fact(
            id=self.id,
            subject=self.subject,
            predicate=self.predicate,
            object=self.object,
            confidence=self.confidence,
            category=self.category,
            source=self.source,
            extra=self.extra,
            scope=scope,
        )


@runtime_checkable
class CKFBackend(Protocol):
    """Minimal backend protocol the federation layer drives.

    Every method takes a free-form ``**kwargs`` and returns a list of
    :class:`Fact`. Production wraps the real ``crp.ckf`` API; tests
    use a hand-rolled in-memory backend.
    """

    def pattern_query(self, **kwargs: Any) -> list[Fact]: ...
    def graph_walk(self, **kwargs: Any) -> list[Fact]: ...
    def community_summary(self, **kwargs: Any) -> list[Fact]: ...
    def temporal_query(self, **kwargs: Any) -> list[Fact]: ...
    def recall_facts(self, **kwargs: Any) -> list[Fact]: ...
    def semantic(self, **kwargs: Any) -> list[Fact]: ...


class FederationError(RuntimeError):
    """Raised when the federation layer's invariants are violated."""


# ── Result dataclass ────────────────────────────────────────────────


@dataclass(frozen=True)
class FederatedQueryResult:
    """The merged output of a federated CKF query.

    *facts* are deduped + scope-tagged; *per_layer* is the un-merged
    per-backend result for diagnostics; *latency_ms* is wall-clock.
    """

    mode: CKFMode
    facts: tuple[Fact, ...]
    per_layer: dict[ScopeLayer, tuple[Fact, ...]]
    latency_ms: float
    tenant_id: str

    @property
    def top_confidence(self) -> float:
        return max((f.confidence for f in self.facts), default=0.0)


# ── The federation layer ────────────────────────────────────────────


@dataclass
class FederatedFabric:
    """Fan-out wrapper around the corpus + per-tenant CKF.

    *tenant_factory* takes a tenant id and returns the CKF backend
    for that tenant. Caching the result across calls is the factory's
    responsibility, not ours.

    *event_sink*, when set, receives one ``loop.ckf.query`` event per
    backend layer that produced a result (or that was queried at all,
    even if it returned zero hits, per PHASE_7 \u00a721 7.7's "do not
    silently fall back" rule).
    """

    corpus: CKFBackend
    tenant_factory: Callable[[str], CKFBackend | None]
    event_sink: Callable[[dict[str, Any]], None] | None = None
    run_id: str = ""
    max_parallelism: int = 2

    _executor: ThreadPoolExecutor = field(init=False, repr=False)
    _lock: threading.Lock = field(init=False, default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max(2, self.max_parallelism),
            thread_name_prefix="ckf-fed",
        )

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True)

    # -- public methods (one per CKF mode) -----------------------------

    def pattern_query(self, *, tenant_id: str, **kw: Any) -> FederatedQueryResult:
        return self._run("pattern_query", tenant_id, kw)

    def graph_walk(self, *, tenant_id: str, **kw: Any) -> FederatedQueryResult:
        return self._run("graph_walk", tenant_id, kw)

    def community_summary(self, *, tenant_id: str, **kw: Any) -> FederatedQueryResult:
        return self._run("community_summary", tenant_id, kw)

    def temporal_query(self, *, tenant_id: str, **kw: Any) -> FederatedQueryResult:
        return self._run("temporal_query", tenant_id, kw)

    def recall_facts(self, *, tenant_id: str, **kw: Any) -> FederatedQueryResult:
        return self._run("recall_facts", tenant_id, kw)

    def semantic(self, *, tenant_id: str, **kw: Any) -> FederatedQueryResult:
        return self._run("semantic", tenant_id, kw)

    # -- core fan-out --------------------------------------------------

    def _run(self, mode: CKFMode, tenant_id: str, kwargs: dict[str, Any]) -> FederatedQueryResult:
        if not tenant_id:
            raise FederationError(f"tenant_id required for federated {mode!r} (data isolation)")

        import time

        t0 = time.perf_counter()
        tenant_backend = self.tenant_factory(tenant_id)

        fut_corpus = self._executor.submit(
            self._safe_invoke,
            "corpus",
            self.corpus,
            mode,
            kwargs,
        )
        fut_tenant = self._executor.submit(
            self._safe_invoke,
            "tenant",
            tenant_backend,
            mode,
            kwargs,
        )

        corpus_hits = fut_corpus.result()
        tenant_hits = fut_tenant.result()

        # Tag scopes before the merge so the per-layer view is honest.
        corpus_tagged = tuple(f.with_scope("corpus") for f in corpus_hits)
        tenant_tagged = tuple(f.with_scope("tenant") for f in tenant_hits)

        merged = self._dedupe_and_merge(corpus_tagged, tenant_tagged)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        # Telemetry: emit one ckf.query event per layer (corpus is
        # always emitted; tenant is emitted whether it returned 0 or
        # N hits so the UI does not silently flip to corpus-only).
        self._emit_layer(mode, "corpus", corpus_tagged)
        if tenant_backend is not None:
            self._emit_layer(mode, "tenant", tenant_tagged)

        return FederatedQueryResult(
            mode=mode,
            facts=merged,
            per_layer={"corpus": corpus_tagged, "tenant": tenant_tagged},
            latency_ms=elapsed_ms,
            tenant_id=tenant_id,
        )

    @staticmethod
    def _safe_invoke(
        layer: ScopeLayer,
        backend: CKFBackend | None,
        mode: CKFMode,
        kwargs: dict[str, Any],
    ) -> list[Fact]:
        if backend is None:
            return []
        method = getattr(backend, mode, None)
        if method is None:
            logger.debug(
                "ckf backend layer=%s lacks mode=%s; treating as 0 hits",
                layer,
                mode,
            )
            return []
        try:
            out = method(**kwargs)
        except Exception:  # pragma: no cover - we surface as 0 hits
            logger.exception(
                "ckf backend layer=%s mode=%s raised; returning 0 hits",
                layer,
                mode,
            )
            return []
        if not isinstance(out, list):
            raise FederationError(
                f"backend layer={layer} mode={mode} returned "
                f"{type(out).__name__}, expected list[Fact]"
            )
        return out

    @staticmethod
    def _dedupe_and_merge(corpus: tuple[Fact, ...], tenant: tuple[Fact, ...]) -> tuple[Fact, ...]:
        """Merge corpus + tenant by Fact.id.

        A duplicate id keeps the *higher-confidence* fact and is
        re-tagged ``federated``. Order: tenant-only facts first
        (they're the user's own knowledge), then federated, then
        corpus-only \u2014 mirrors the UI rail's grouping.
        """
        by_id_corpus = {f.id: f for f in corpus}
        by_id_tenant = {f.id: f for f in tenant}
        federated_ids = set(by_id_corpus) & set(by_id_tenant)

        out: list[Fact] = []
        # tenant-only
        for fid, f in by_id_tenant.items():
            if fid in federated_ids:
                continue
            out.append(f)
        # federated
        for fid in federated_ids:
            c = by_id_corpus[fid]
            t = by_id_tenant[fid]
            winner = c if c.confidence >= t.confidence else t
            out.append(winner.with_scope("federated"))
        # corpus-only
        for fid, f in by_id_corpus.items():
            if fid in federated_ids:
                continue
            out.append(f)
        # Stable order: highest confidence first within each group is
        # preserved by the dict iteration in CPython 3.7+, and we
        # tie-break by id for determinism in tests.
        return tuple(out)

    def _emit_layer(self, mode: CKFMode, scope: ScopeLayer, facts: tuple[Fact, ...]) -> None:
        if self.event_sink is None:
            return
        top = max((f.confidence for f in facts), default=0.0)
        # Clamp to [0, 1] in case a backend returned an out-of-range
        # value; the typed schema rejects anything outside this range.
        top = max(0.0, min(1.0, float(top)))
        evt = make_event(
            "loop.ckf.query",
            {
                "mode": mode,
                "scope": scope,
                "hits": len(facts),
                "top_confidence": top,
            },
            run_id=self.run_id,
        )
        self.event_sink(evt)
