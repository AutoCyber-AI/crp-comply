"""Triage layer tests \u2014 PHASE_7 \u00a721 7.1.

Acceptance criteria these cover:

* ``triage_patterns.yaml`` has \u2265 30 patterns and they all compile.
* ``Triage.classify(query)`` runs in \u2264 50 ms p95 on CPU
  (we use 50 ms p99 over 200 calls, much stricter than the spec).
* Lane selection is deterministic: same query \u2192 same lane every
  time across N invocations.
* A 50-query golden file maps each fixture query to its expected lane;
  any mismatch fails the test.
* Unknown queries fall back with ``confidence < 0.5`` and
  ``reasoning='fallback'`` (explicit fallback, not silent).
* ``loop.triage`` payload validates against the typed event schema.
"""

from __future__ import annotations

import time

import pytest

from crp_comply.agent.triage import (
    Triage,
    TriageError,
    TriageResult,
    load_default_triage,
)
from crp_comply.api.events import validate_event


@pytest.fixture(scope="module")
def triage() -> Triage:
    return load_default_triage()


def test_pattern_set_meets_spec_size(triage: Triage) -> None:
    # PHASE_7 \u00a721 7.1: "\u2265 30 patterns from \u00a714.4".
    assert len(triage.patterns) >= 30, f"need \u2265 30 patterns, got {len(triage.patterns)}"


def test_pattern_ids_are_unique(triage: Triage) -> None:
    ids = [p.id for p in triage.patterns]
    assert len(ids) == len(set(ids))


def test_classify_deterministic(triage: Triage) -> None:
    # Same query 20\u00d7 must produce identical results.
    q = "Generate a DPIA for our HR analytics tool"
    results = [triage.classify(q) for _ in range(20)]
    first = results[0]
    for r in results[1:]:
        assert r.complexity == first.complexity
        assert r.lane == first.lane
        assert r.intent == first.intent
        assert r.pattern_id == first.pattern_id


def test_classify_under_p99_50ms(triage: Triage) -> None:
    # 200 mixed queries. Spec is 50 ms p95; we test p99.
    queries = [
        "what is gdpr",
        "cite article 6 gdpr",
        "compare gdpr and ccpa",
        "are we compliant with nis2",
        "generate a dpia for our hr analytics tool",
        "am i in scope of the eu ai act",
        "what does article 5 of the eu ai act say",
        "draft a risk assessment for our chatbot",
        "lawful basis under article 6",
        "deadline for nis2 transposition",
    ]
    timings: list[float] = []
    for _ in range(20):
        for q in queries:
            t0 = time.perf_counter()
            triage.classify(q)
            timings.append((time.perf_counter() - t0) * 1000.0)
    timings.sort()
    p99 = timings[int(0.99 * len(timings))]
    assert p99 < 50.0, f"p99 latency {p99:.2f} ms exceeds 50 ms"


# ── Golden file: 50 queries \u2192 expected lane ───────────────────────


_GOLDEN: list[tuple[str, str]] = [
    # cite (fast)
    ("cite article 6 gdpr", "fast"),
    ("reference annex iii", "fast"),
    ("show recital 71 gdpr", "fast"),
    ("find article 22 of the gdpr", "fast"),
    ("quote section 4 of the data protection act", "fast"),
    ("what does article 5 say", "fast"),
    ("text of article 32", "fast"),
    ("wording of recital 26", "fast"),
    # define (fast)
    ("define controller", "fast"),
    ("definition of personal data", "fast"),
    ("what is a data subject", "fast"),
    ("what does the gdpr say about consent", "fast"),
    ("how does the eu ai act define high-risk ai", "fast"),
    ("meaning of legitimate interests", "fast"),
    ("deadline for nis2 transposition", "fast"),
    ("penalty for gdpr breach", "fast"),
    ("lawful basis under article 6", "fast"),
    ("right to erasure", "fast"),
    ("controller role under gdpr", "fast"),
    # scope (slow)
    ("am i in scope of the eu ai act", "slow"),
    ("are we subject to nis2", "slow"),
    ("does the gdpr apply to our us subsidiary", "slow"),
    ("is our company in scope of dora", "slow"),
    ("what are our obligations under the ai act", "slow"),
    ("what must we do to comply with nis2", "slow"),
    ("how to comply with article 30 gdpr", "slow"),
    ("am i covered by the ai act", "slow"),
    # compare (slow)
    ("compare gdpr vs ccpa", "slow"),
    ("difference between controller and processor", "slow"),
    ("compare nist ai rmf and iso 42001", "slow"),
    ("how does gdpr differ from uk gdpr", "slow"),
    # produce_artefact (slow)
    ("generate a dpia for our hr analytics tool", "slow"),
    ("produce annex iv documentation", "slow"),
    ("draft a conformity declaration", "slow"),
    ("create a risk assessment for our chatbot", "slow"),
    ("write a breach notification template", "slow"),
    ("build me a model card", "slow"),
    ("i need a dpia", "slow"),
    ("draft sccs for transfers to a us processor", "slow"),
    # audit_existing (slow)
    ("audit our dpia", "slow"),
    ("review my privacy policy", "slow"),
    ("are we compliant with gdpr", "slow"),
    ("check our annex iv", "slow"),
    ("run a gap analysis", "slow"),
    ("perform a gap analysis on our programme", "slow"),
    # heuristics fallbacks (slow with low confidence)
    ("hello there", "slow"),
    ("can you do something", "slow"),
    # multi-regulation \u2192 complex/slow
    ("how do gdpr and the eu ai act interact for hr screening", "slow"),
    # long multi-clause
    (
        "we operate a recruitment platform across the eu and the uk, "
        "and we use an automated cv screening model; we also share "
        "candidate data with employers in the us and need to know "
        "what our obligations are",
        "slow",
    ),
    # high-risk ai
    ("is this a high-risk ai system under annex iii", "slow"),
]


def test_golden_file_size() -> None:
    assert len(_GOLDEN) >= 50


@pytest.mark.parametrize("query,expected_lane", _GOLDEN)
def test_golden_lane(triage: Triage, query: str, expected_lane: str) -> None:
    result = triage.classify(query)
    assert result.lane == expected_lane, (
        f"query {query!r}: got lane={result.lane} (reasoning={result.reasoning}), "
        f"expected {expected_lane}"
    )


def test_unknown_query_emits_explicit_fallback(triage: Triage) -> None:
    # No pattern, short, single-clause. Must hit the fallback branch.
    r = triage.classify("xyzzy")
    assert r.confidence < 0.5
    assert r.reasoning == "fallback"
    assert r.lane == "slow"


def test_empty_query_handled(triage: Triage) -> None:
    r = triage.classify("")
    assert r.lane == "slow"
    assert "fallback" in r.reasoning


def test_to_event_payload_validates(triage: Triage) -> None:
    r = triage.classify("cite article 6 gdpr")
    payload = r.to_event_payload()
    out = validate_event("loop.triage", payload)
    assert out["lane"] == r.lane
    assert out["intent"] == r.intent


def test_yaml_load_rejects_bad_pattern(tmp_path) -> None:
    bad = tmp_path / "p.yaml"
    bad.write_text(
        "patterns:\n"
        "  - id: bad\n"
        "    regex: '['\n"  # invalid regex
        "    intent: define\n"
        "    complexity: simple\n"
        "    lane: fast\n"
        "    confidence: 0.5\n",
        encoding="utf-8",
    )
    with pytest.raises(TriageError, match="regex compile"):
        Triage.from_yaml(bad)


def test_yaml_load_rejects_cache_lane(tmp_path) -> None:
    bad = tmp_path / "p.yaml"
    bad.write_text(
        "patterns:\n"
        "  - id: bad\n"
        "    regex: 'foo'\n"
        "    intent: define\n"
        "    complexity: simple\n"
        "    lane: cache\n"
        "    confidence: 0.5\n",
        encoding="utf-8",
    )
    with pytest.raises(TriageError, match="lane"):
        Triage.from_yaml(bad)


def test_result_typed() -> None:
    r = TriageResult(
        complexity="simple",
        intent="define",
        confidence=0.9,
        lane="fast",
        reasoning="test",
    )
    assert r.elapsed_ms == 0.0
