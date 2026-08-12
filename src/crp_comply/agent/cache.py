"""Three-tier answer cache for the language-agent loop \u2014 PHASE_7 \u00a721 7.2.

Lanes A's foundation: skip the loop entirely when we already have an
answer that is provably the same regulation version, the same tenant
CKF, and either an exact textual match (cheap) or a high semantic
similarity match (cosine \u2265 0.92 by default).

Three caches share one sqlite file (``data/cache/agent_responses.db``):

* **exact** \u2014 sha256(tenant + corpus_version + ckf_version +
  normalise(query)) \u2192 stored answer + citations + tool log.
* **semantic** \u2014 same scope key, but indexed by an injected
  ``Embedder`` (``embed(text) -> list[float]``). Cosine similarity
  ranking is done in Python over rows scoped to the same
  (tenant_id, corpus_version, ckf_version). When no embedder is
  injected, semantic lookups simply miss \u2014 we never silently fall
  back to "any tenant's answer".
* **plan** \u2014 sha256(tenant + intent + complexity_bucket) \u2192 cached
  plan skeleton. 24-hour TTL.

No bypasses (PHASE_7 \u00a721 7.2):
* ``put_answer`` rejects entries with zero citations or a non-``ok``
  reflector verdict (uncited answers are unprovable).
* Tenant ID is the first key field for *every* lookup; cross-tenant
  reads are structurally impossible (assertion-tested).
* Bumping ``corpus_version`` or ``ckf_version`` invalidates entries
  by silently failing every lookup with the old key \u2014 the
  ``invalidate_corpus_version`` helper is provided for explicit
  cleanup, but stale rows never *match* anyway.
* "Re-run from scratch" is implemented at the API layer (a request
  flag), but the cache exposes :meth:`force_miss` so the orchestrator
  can record the override in telemetry.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Literal

__all__ = [
    "AgentCache",
    "CachedAnswer",
    "CachedPlan",
    "CacheLookup",
    "CacheError",
]


# ── Types ────────────────────────────────────────────────────────────


KeyKind = Literal["exact", "semantic", "plan"]
EmbedFn = Callable[[str], list[float]]


class CacheError(RuntimeError):
    """Raised when a contract violation is attempted (e.g. uncited put)."""


@dataclass(frozen=True)
class CachedAnswer:
    """Payload stored against an exact/semantic key.

    *answer* is the final assembled string (no streaming chunks).
    *citations* is the structured list rendered into the UI rail.
    *tool_log* is the abridged tool-call trace for "Why this answer?".
    *reflector_verdict* records the verdict at the time of the write.
    """

    answer: str
    citations: list[dict[str, Any]]
    tool_log: list[dict[str, Any]] = field(default_factory=list)
    reflector_verdict: str = "ok"


@dataclass(frozen=True)
class CachedPlan:
    """Skeleton plan re-used across queries with the same intent shape."""

    steps: list[dict[str, Any]]
    should_loop: bool = True


@dataclass(frozen=True)
class CacheLookup:
    """Outcome of an answer lookup.

    ``hit`` is None on a miss. ``key_kind`` is always set so the
    SSE bridge can emit the correct ``loop.cache.hit`` /
    ``loop.cache.miss`` event regardless.
    """

    key_kind: KeyKind
    hit: CachedAnswer | None
    similarity: float | None = None
    age_seconds: float = 0.0
    lookup_ms: float = 0.0


# ── Helpers ──────────────────────────────────────────────────────────


def _normalise_query(q: str) -> str:
    """Whitespace-collapse + lowercase. Cheap, deterministic, audit-stable."""
    return " ".join((q or "").lower().split())


def _sha(parts: Iterable[str]) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode("utf-8"))
        h.update(b"\x1f")  # unit separator avoids accidental collisions
    return h.hexdigest()


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    num = sum(x * y for x, y in zip(a, b))
    da = math.sqrt(sum(x * x for x in a))
    db = math.sqrt(sum(y * y for y in b))
    if da == 0.0 or db == 0.0:
        return 0.0
    return num / (da * db)


def _default_sim_threshold() -> float:
    raw = os.environ.get("CRP_COMPLY_CACHE_SIM_THRESHOLD", "0.92")
    try:
        v = float(raw)
    except ValueError:
        return 0.92
    return max(0.0, min(1.0, v))


# ── The cache ────────────────────────────────────────────────────────


_SCHEMA = """
CREATE TABLE IF NOT EXISTS answers (
    cache_key       TEXT PRIMARY KEY,
    tenant_id       TEXT NOT NULL,
    corpus_version  TEXT NOT NULL,
    ckf_version     TEXT NOT NULL,
    norm_query      TEXT NOT NULL,
    embedding_json  TEXT,
    answer          TEXT NOT NULL,
    citations_json  TEXT NOT NULL,
    tool_log_json   TEXT NOT NULL,
    reflector_verdict TEXT NOT NULL,
    created_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_answers_scope
    ON answers(tenant_id, corpus_version, ckf_version);

CREATE TABLE IF NOT EXISTS plans (
    cache_key   TEXT PRIMARY KEY,
    tenant_id   TEXT NOT NULL,
    intent      TEXT NOT NULL,
    complexity  TEXT NOT NULL,
    steps_json  TEXT NOT NULL,
    should_loop INTEGER NOT NULL,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_plans_tenant
    ON plans(tenant_id, intent, complexity);
"""

_PLAN_TTL_SECONDS = 24 * 3600


@dataclass
class AgentCache:
    """Three-tier sqlite-backed cache.

    Construct with an explicit ``db_path`` for tests; production code
    should use the default ``data/cache/agent_responses.db``.
    """

    db_path: Path = field(default_factory=lambda: Path("data/cache/agent_responses.db"))
    embed: EmbedFn | None = None
    sim_threshold: float = field(default_factory=_default_sim_threshold)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    # -- connection helper -----------------------------------------

    def _connect(self) -> sqlite3.Connection:
        # ``check_same_thread=False`` so we can serve concurrent
        # SSE streams; the explicit Lock around mutating ops keeps
        # writes safe.
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    # -- key construction ------------------------------------------

    @staticmethod
    def _scope_key(
        tenant_id: str,
        corpus_version: str,
        ckf_version: str,
        norm_query: str,
    ) -> str:
        if not tenant_id:
            raise CacheError("tenant_id is required for every cache call")
        return _sha([tenant_id, corpus_version, ckf_version, norm_query])

    @staticmethod
    def _plan_key(tenant_id: str, intent: str, complexity: str) -> str:
        if not tenant_id:
            raise CacheError("tenant_id is required for every cache call")
        return _sha([tenant_id, intent, complexity])

    # -- writes ----------------------------------------------------

    def put_answer(
        self,
        *,
        tenant_id: str,
        corpus_version: str,
        ckf_version: str,
        query: str,
        cached: CachedAnswer,
    ) -> None:
        """Persist an answer for later lookup.

        Refuses uncited answers and non-``ok`` verdicts \u2014 PHASE_7 \u00a721
        7.2 forbids caching anything we can't defend in audit.
        """
        if cached.reflector_verdict != "ok":
            raise CacheError(f"refusing to cache verdict={cached.reflector_verdict!r}")
        if not cached.citations:
            raise CacheError("refusing to cache an answer with no citations")
        norm = _normalise_query(query)
        key = self._scope_key(tenant_id, corpus_version, ckf_version, norm)
        emb_json: str | None = None
        if self.embed is not None:
            try:
                vec = self.embed(norm)
                if vec:
                    emb_json = json.dumps(list(vec))
            except Exception:  # pragma: no cover - embed failures are non-fatal
                emb_json = None
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO answers ("
                "cache_key, tenant_id, corpus_version, ckf_version, norm_query, "
                "embedding_json, answer, citations_json, tool_log_json, "
                "reflector_verdict, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    key,
                    tenant_id,
                    corpus_version,
                    ckf_version,
                    norm,
                    emb_json,
                    cached.answer,
                    json.dumps(cached.citations),
                    json.dumps(cached.tool_log),
                    cached.reflector_verdict,
                    time.time(),
                ),
            )
            conn.commit()

    def put_plan(
        self,
        *,
        tenant_id: str,
        intent: str,
        complexity: str,
        plan: CachedPlan,
    ) -> None:
        key = self._plan_key(tenant_id, intent, complexity)
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO plans ("
                "cache_key, tenant_id, intent, complexity, steps_json, "
                "should_loop, created_at) VALUES (?,?,?,?,?,?,?)",
                (
                    key,
                    tenant_id,
                    intent,
                    complexity,
                    json.dumps(plan.steps),
                    1 if plan.should_loop else 0,
                    time.time(),
                ),
            )
            conn.commit()

    # -- reads -----------------------------------------------------

    def lookup_answer(
        self,
        *,
        tenant_id: str,
        corpus_version: str,
        ckf_version: str,
        query: str,
    ) -> CacheLookup:
        """Try exact, then semantic. Returns a :class:`CacheLookup`.

        On miss, returns ``CacheLookup(key_kind='exact', hit=None, ...)``
        so callers can still emit ``loop.cache.miss``.
        """
        t0 = time.perf_counter()
        norm = _normalise_query(query)
        # 1. Exact.
        exact_key = self._scope_key(tenant_id, corpus_version, ckf_version, norm)
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM answers WHERE cache_key = ?", (exact_key,)).fetchone()
        if row is not None:
            return CacheLookup(
                key_kind="exact",
                hit=_row_to_answer(row),
                similarity=1.0,
                age_seconds=max(0.0, time.time() - float(row["created_at"])),
                lookup_ms=(time.perf_counter() - t0) * 1000.0,
            )
        # 2. Semantic (only if we have an embedder).
        if self.embed is not None:
            try:
                qvec = self.embed(norm)
            except Exception:  # pragma: no cover
                qvec = []
            if qvec:
                hit, sim, created = self._semantic_search(
                    tenant_id, corpus_version, ckf_version, qvec
                )
                if hit is not None:
                    return CacheLookup(
                        key_kind="semantic",
                        hit=hit,
                        similarity=sim,
                        age_seconds=max(0.0, time.time() - created),
                        lookup_ms=(time.perf_counter() - t0) * 1000.0,
                    )
        # 3. Miss.
        return CacheLookup(
            key_kind="exact",
            hit=None,
            similarity=None,
            age_seconds=0.0,
            lookup_ms=(time.perf_counter() - t0) * 1000.0,
        )

    def _semantic_search(
        self,
        tenant_id: str,
        corpus_version: str,
        ckf_version: str,
        qvec: list[float],
    ) -> tuple[CachedAnswer | None, float, float]:
        """Brute-force cosine over the (tenant, corpus, ckf) scope."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM answers "
                "WHERE tenant_id = ? AND corpus_version = ? AND ckf_version = ? "
                "  AND embedding_json IS NOT NULL",
                (tenant_id, corpus_version, ckf_version),
            ).fetchall()
        best: tuple[float, sqlite3.Row] | None = None
        for row in rows:
            try:
                vec = json.loads(row["embedding_json"])
            except (TypeError, ValueError):
                continue
            sim = _cosine(qvec, vec)
            if best is None or sim > best[0]:
                best = (sim, row)
        if best is None or best[0] < self.sim_threshold:
            return None, 0.0, 0.0
        sim, row = best
        return _row_to_answer(row), sim, float(row["created_at"])

    def lookup_plan(
        self,
        *,
        tenant_id: str,
        intent: str,
        complexity: str,
    ) -> CachedPlan | None:
        key = self._plan_key(tenant_id, intent, complexity)
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM plans WHERE cache_key = ?", (key,)).fetchone()
        if row is None:
            return None
        if time.time() - float(row["created_at"]) > _PLAN_TTL_SECONDS:
            return None
        return CachedPlan(
            steps=json.loads(row["steps_json"]),
            should_loop=bool(row["should_loop"]),
        )

    # -- maintenance / overrides -----------------------------------

    def invalidate_corpus_version(self, corpus_version: str) -> int:
        """Drop every answer cached against a given corpus version.

        Strictly optional: stale rows already fail to match because
        ``corpus_version`` is part of the key. Use this when you
        want the rows physically gone (disk pressure, audit).
        """
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM answers WHERE corpus_version = ?",
                (corpus_version,),
            )
            conn.commit()
            return cur.rowcount or 0

    def invalidate_tenant(self, tenant_id: str) -> int:
        """Drop every cached entry (answers + plans) for one tenant."""
        with self._lock, self._connect() as conn:
            a = conn.execute("DELETE FROM answers WHERE tenant_id = ?", (tenant_id,)).rowcount or 0
            p = conn.execute("DELETE FROM plans WHERE tenant_id = ?", (tenant_id,)).rowcount or 0
            conn.commit()
            return a + p

    @staticmethod
    def force_miss() -> CacheLookup:
        """Sentinel for the "Re-run from scratch" UI button.

        The orchestrator calls this when ``X-CRP-Cache-Bypass: 1`` is
        present so the SSE stream still emits a coherent
        ``loop.cache.miss`` event with ``key_kind='exact'``.
        """
        return CacheLookup(
            key_kind="exact",
            hit=None,
            similarity=None,
            age_seconds=0.0,
            lookup_ms=0.0,
        )


def _row_to_answer(row: sqlite3.Row) -> CachedAnswer:
    return CachedAnswer(
        answer=row["answer"],
        citations=json.loads(row["citations_json"]),
        tool_log=json.loads(row["tool_log_json"]),
        reflector_verdict=row["reflector_verdict"],
    )
