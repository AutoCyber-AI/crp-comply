"""Cache layer tests \u2014 PHASE_7 \u00a721 7.2.

Acceptance criteria covered:

* Hit/miss round-trip for exact and semantic keys.
* Tenant isolation: tenant A's writes never leak to tenant B even
  with identical query / corpus_version / ckf_version.
* Bumping ``corpus_version`` or ``ckf_version`` causes lookups with
  the *old* version to miss (no silent stale reuse).
* Refusal to cache uncited answers or non-``ok`` reflector verdicts.
* Plan cache TTL semantics.
* "Re-run from scratch" produces a coherent ``CacheLookup`` miss.
* The ``loop.cache.hit`` payload validates against the typed schema.
"""

from __future__ import annotations

import hashlib
import time

import pytest

from crp_comply.agent.cache import (
    AgentCache,
    CacheError,
    CachedAnswer,
    CachedPlan,
)
from crp_comply.api.events import validate_event


@pytest.fixture()
def cache(tmp_path) -> AgentCache:
    return AgentCache(db_path=tmp_path / "cache.db")


def _stub_embed(text: str) -> list[float]:
    """Deterministic 16-dim hash-bucket embedding so tests don't pull ML."""
    h = hashlib.sha256(text.encode("utf-8")).digest()
    # Map to 16 floats in [0,1].
    return [b / 255.0 for b in h[:16]]


@pytest.fixture()
def semantic_cache(tmp_path) -> AgentCache:
    return AgentCache(db_path=tmp_path / "cache.db", embed=_stub_embed)


def _ans(answer: str = "Article 6 GDPR sets out lawful bases.") -> CachedAnswer:
    return CachedAnswer(
        answer=answer,
        citations=[{"source": "GDPR", "article": "6"}],
        tool_log=[{"tool": "pattern_query", "args": {}}],
        reflector_verdict="ok",
    )


# ── Exact hit/miss ───────────────────────────────────────────────────


def test_exact_hit_roundtrip(cache: AgentCache) -> None:
    cache.put_answer(
        tenant_id="t1",
        corpus_version="2026-05-01",
        ckf_version="ckf-1",
        query="What is Article 6 GDPR?",
        cached=_ans(),
    )
    out = cache.lookup_answer(
        tenant_id="t1",
        corpus_version="2026-05-01",
        ckf_version="ckf-1",
        query="what is article 6 gdpr?",
    )
    assert out.hit is not None
    assert out.key_kind == "exact"
    assert out.similarity == 1.0
    assert "lawful bases" in out.hit.answer


def test_exact_miss(cache: AgentCache) -> None:
    out = cache.lookup_answer(
        tenant_id="t1",
        corpus_version="v",
        ckf_version="ckf",
        query="never seen this query",
    )
    assert out.hit is None
    assert out.key_kind == "exact"
    assert out.lookup_ms >= 0.0


# ── Tenant isolation (PHASE_7 \u00a721 7.2: tenant_id is the first key field) ──


def test_tenant_isolation_strict(cache: AgentCache) -> None:
    cache.put_answer(
        tenant_id="tenant_A",
        corpus_version="v1",
        ckf_version="ckf1",
        query="What is consent?",
        cached=_ans("Tenant A answer"),
    )
    out = cache.lookup_answer(
        tenant_id="tenant_B",
        corpus_version="v1",
        ckf_version="ckf1",
        query="What is consent?",
    )
    assert out.hit is None, "tenant_B must not see tenant_A's cached answer"


def test_missing_tenant_id_rejected(cache: AgentCache) -> None:
    with pytest.raises(CacheError, match="tenant_id"):
        cache.put_answer(
            tenant_id="",
            corpus_version="v1",
            ckf_version="ckf1",
            query="q",
            cached=_ans(),
        )


# ── Version-bump invalidation ────────────────────────────────────────


def test_corpus_version_bump_invalidates(cache: AgentCache) -> None:
    cache.put_answer(
        tenant_id="t1",
        corpus_version="2026-05-01",
        ckf_version="ckf-1",
        query="q",
        cached=_ans(),
    )
    out_old = cache.lookup_answer(
        tenant_id="t1",
        corpus_version="2026-05-01",
        ckf_version="ckf-1",
        query="q",
    )
    assert out_old.hit is not None
    out_new = cache.lookup_answer(
        tenant_id="t1",
        corpus_version="2026-06-01",  # bumped
        ckf_version="ckf-1",
        query="q",
    )
    assert out_new.hit is None


def test_ckf_version_bump_invalidates(cache: AgentCache) -> None:
    cache.put_answer(
        tenant_id="t1",
        corpus_version="v",
        ckf_version="ckf-1",
        query="q",
        cached=_ans(),
    )
    out = cache.lookup_answer(
        tenant_id="t1",
        corpus_version="v",
        ckf_version="ckf-2",  # bumped
        query="q",
    )
    assert out.hit is None


def test_invalidate_corpus_version_drops_rows(cache: AgentCache) -> None:
    cache.put_answer(
        tenant_id="t1",
        corpus_version="v1",
        ckf_version="ckf",
        query="q",
        cached=_ans(),
    )
    n = cache.invalidate_corpus_version("v1")
    assert n == 1
    out = cache.lookup_answer(
        tenant_id="t1",
        corpus_version="v1",
        ckf_version="ckf",
        query="q",
    )
    assert out.hit is None


# ── No-bypass: uncited / non-ok refused ─────────────────────────────


def test_refuses_uncited_answer(cache: AgentCache) -> None:
    with pytest.raises(CacheError, match="citations"):
        cache.put_answer(
            tenant_id="t1",
            corpus_version="v",
            ckf_version="ckf",
            query="q",
            cached=CachedAnswer(answer="x", citations=[]),
        )


def test_refuses_non_ok_verdict(cache: AgentCache) -> None:
    with pytest.raises(CacheError, match="verdict"):
        cache.put_answer(
            tenant_id="t1",
            corpus_version="v",
            ckf_version="ckf",
            query="q",
            cached=CachedAnswer(
                answer="x",
                citations=[{"src": "x"}],
                reflector_verdict="retry",
            ),
        )


# ── Semantic ────────────────────────────────────────────────────────


def test_semantic_hit_when_threshold_met(semantic_cache: AgentCache) -> None:
    # The stub embedder returns the exact same vector for the exact same
    # normalised string. So putting "Foo bar baz" and querying "foo bar baz"
    # gives exact hit; we want a *semantic* hit, so we put one query and
    # look up another that normalises differently. To do that
    # deterministically, lower the threshold for this test.
    semantic_cache.sim_threshold = 0.0  # any non-zero similarity wins
    semantic_cache.put_answer(
        tenant_id="t1",
        corpus_version="v",
        ckf_version="ckf",
        query="What is the lawful basis?",
        cached=_ans(),
    )
    out = semantic_cache.lookup_answer(
        tenant_id="t1",
        corpus_version="v",
        ckf_version="ckf",
        query="lawful basis under article six",  # different surface
    )
    assert out.hit is not None
    assert out.key_kind == "semantic"
    assert 0.0 < (out.similarity or 0.0) <= 1.0


def test_semantic_threshold_blocks_distant_queries(
    semantic_cache: AgentCache,
) -> None:
    semantic_cache.sim_threshold = 0.99  # very strict
    semantic_cache.put_answer(
        tenant_id="t1",
        corpus_version="v",
        ckf_version="ckf",
        query="What is consent under GDPR?",
        cached=_ans(),
    )
    out = semantic_cache.lookup_answer(
        tenant_id="t1",
        corpus_version="v",
        ckf_version="ckf",
        query="completely unrelated question about astrophysics",
    )
    assert out.hit is None


def test_semantic_disabled_when_no_embedder(cache: AgentCache) -> None:
    cache.put_answer(
        tenant_id="t1",
        corpus_version="v",
        ckf_version="ckf",
        query="exact phrasing",
        cached=_ans(),
    )
    out = cache.lookup_answer(
        tenant_id="t1",
        corpus_version="v",
        ckf_version="ckf",
        query="paraphrased version",
    )
    assert out.hit is None
    assert out.key_kind == "exact"


# ── Plan cache ──────────────────────────────────────────────────────


def test_plan_cache_roundtrip(cache: AgentCache) -> None:
    cache.put_plan(
        tenant_id="t1",
        intent="produce_artefact",
        complexity="comprehensive",
        plan=CachedPlan(steps=[{"id": "s1", "intent": "scope"}]),
    )
    p = cache.lookup_plan(
        tenant_id="t1",
        intent="produce_artefact",
        complexity="comprehensive",
    )
    assert p is not None
    assert p.steps[0]["id"] == "s1"


def test_plan_cache_tenant_isolated(cache: AgentCache) -> None:
    cache.put_plan(
        tenant_id="t1",
        intent="define",
        complexity="simple",
        plan=CachedPlan(steps=[{"id": "x"}]),
    )
    assert cache.lookup_plan(tenant_id="t2", intent="define", complexity="simple") is None


def test_plan_cache_ttl(monkeypatch, cache: AgentCache) -> None:
    cache.put_plan(
        tenant_id="t1",
        intent="define",
        complexity="simple",
        plan=CachedPlan(steps=[{"id": "x"}]),
    )
    # Fast-forward 25h.
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + 25 * 3600)
    assert cache.lookup_plan(tenant_id="t1", intent="define", complexity="simple") is None


# ── force_miss + event payload validation ───────────────────────────


def test_force_miss_shape() -> None:
    out = AgentCache.force_miss()
    assert out.hit is None
    assert out.key_kind == "exact"


def test_loop_cache_hit_payload_validates(cache: AgentCache) -> None:
    cache.put_answer(
        tenant_id="t1",
        corpus_version="v",
        ckf_version="ckf",
        query="hello",
        cached=_ans(),
    )
    out = cache.lookup_answer(
        tenant_id="t1",
        corpus_version="v",
        ckf_version="ckf",
        query="hello",
    )
    assert out.hit is not None
    payload = {
        "key_kind": out.key_kind,
        "similarity": out.similarity,
        "age_seconds": out.age_seconds,
        "citations": out.hit.citations,
    }
    validated = validate_event("loop.cache.hit", payload)
    assert validated["key_kind"] == "exact"
