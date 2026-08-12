"""Unit tests for the CRP SearXNG-host plugins.

No SearXNG instance is required; the tests exercise the pure helper logic
(query routing, authority fingerprinting, feedback decay) with lightweight
mocks supplied by ``conftest.py``.
"""

from __future__ import annotations

import os
import tempfile
from types import SimpleNamespace
from typing import Any

import pytest


# ── Query Router ────────────────────────────────────────────────────────


def test_extract_intent_from_args(query_router_module: Any) -> None:
    class FakeRequest:
        form: dict[str, str] = {}
        args = {"crp_intent": "case_law"}

    assert query_router_module.CrpQueryRouter._extract_intent(FakeRequest()) == "case_law"


def test_extract_intent_defaults_to_general(query_router_module: Any) -> None:
    class FakeRequest:
        form: dict[str, str] = {}
        args: dict[str, str] = {}

    assert query_router_module.CrpQueryRouter._extract_intent(FakeRequest()) == "general"


def test_extract_intent_from_form_overrides(query_router_module: Any) -> None:
    class FakeRequest:
        form = {"crp_intent": "vendor"}
        args = {"crp_intent": "news"}

    assert query_router_module.CrpQueryRouter._extract_intent(FakeRequest()) == "vendor"


def test_authority_fingerprint_boosts_eur_lex_for_celex(query_router_module: Any) -> None:
    ordering = ["bing", "duckduckgo"]
    out = query_router_module.CrpQueryRouter._apply_authority_fingerprint(
        "2023/1234 AI Act", ordering
    )
    assert out[0] == "eur-lex"


def test_authority_fingerprint_boosts_eur_lex_for_regulation(query_router_module: Any) -> None:
    ordering = ["duckduckgo", "bing"]
    out = query_router_module.CrpQueryRouter._apply_authority_fingerprint(
        "What does GDPR say?", ordering
    )
    assert out[0] == "eur-lex"


def test_authority_fingerprint_boosts_curia_and_bailii_for_case(query_router_module: Any) -> None:
    ordering = ["bing", "duckduckgo"]
    out = query_router_module.CrpQueryRouter._apply_authority_fingerprint(
        "Case C-123/22 ruling", ordering
    )
    assert out[0] == "curia"
    assert out[1] == "bailii"


def test_router_trims_to_budget(query_router_module: Any) -> None:
    router = query_router_module.CrpQueryRouter()

    class Engineref:
        def __init__(self, name: str) -> None:
            self.name = name

    class SearchQuery:
        query = "AI Act high risk"
        engineref_list = [Engineref("bing"), Engineref("duckduckgo"), Engineref("eur-lex")]

    class Search:
        search_query = SearchQuery()

    class FakeRequest:
        form: dict[str, str] = {}
        args = {"crp_intent": "regulation_text"}

    router._route(FakeRequest(), Search())
    chosen = [er.name for er in SearchQuery.engineref_list]
    assert len(chosen) <= router._budget
    assert "eur-lex" in chosen


def test_router_applies_feedback_boost(query_router_module: Any) -> None:
    router = query_router_module.CrpQueryRouter()

    class Engineref:
        def __init__(self, name: str) -> None:
            self.name = name

    class SearchQuery:
        query = "x"
        engineref_list = [Engineref("bing"), Engineref("duckduckgo"), Engineref("eur-lex")]

    class Search:
        search_query = SearchQuery()

    class FakeRequest:
        form: dict[str, str] = {}
        args = {"crp_intent": "regulation_text"}

    # Monkey-patch the feedback lookup to prefer bing.
    import sys

    fake_lr = sys.modules["searx.plugins._crp.learning_reranker"]
    fake_lr.engine_scores = lambda intent: {"bing": 5.0, "eur-lex": 1.0, "curia": 0.0}

    router._route(FakeRequest(), Search())
    assert SearchQuery.engineref_list[0].name == "bing"


# ── Learning Reranker ───────────────────────────────────────────────────


def _reranker_mod(tmp_path: Any) -> Any:
    """Return the learning_reranker module configured to use a temp DB."""
    import sys

    import learning_reranker

    # Force a fresh in-file DB per test so observations do not leak.
    db_path = tmp_path / "feedback.sqlite"
    settings = sys.modules["searx.settings"]
    settings._data["crp_agent"]["reranker"]["feedback_db"] = str(db_path)
    return learning_reranker


def test_record_feedback_and_score_boost(tmp_path: Any) -> None:
    lr = _reranker_mod(tmp_path)
    for _ in range(2):
        lr.record_feedback("regulation_text", "eur_lex", True, weight=1.0)
    scores = lr.engine_scores("regulation_text")
    assert "eur_lex" in scores
    assert scores["eur_lex"] > 0


def test_negative_feedback_reduces_score(tmp_path: Any) -> None:
    lr = _reranker_mod(tmp_path)
    for _ in range(2):
        lr.record_feedback("regulation_text", "bad_engine", False, weight=1.0)
    scores = lr.engine_scores("regulation_text")
    assert scores.get("bad_engine", 0) < 0


def test_scores_require_min_observations(tmp_path: Any) -> None:
    lr = _reranker_mod(tmp_path)
    lr.record_feedback("guidance", "edpb", True, weight=1.0)
    scores = lr.engine_scores("guidance")
    # min_observations is 2 in conftest, so a single observation is hidden.
    assert "edpb" not in scores


def test_score_decay_over_time(tmp_path: Any) -> None:
    lr = _reranker_mod(tmp_path)
    now = 1_000_000_000.0
    # Patch time so we can control age.
    original_time = lr.time.time
    try:
        lr.time.time = lambda: now
        for _ in range(2):
            lr.record_feedback("news", "bing", True, weight=1.0)
        fresh = lr.engine_scores("news")["bing"]

        lr.time.time = lambda: now + (100 * 86400)  # 100 days later
        stale = lr.engine_scores("news")["bing"]
        assert stale < fresh
    finally:
        lr.time.time = original_time
