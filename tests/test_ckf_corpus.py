# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for Phase 6 corpus CKF (CRP-on-data)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from crp_comply.agent.ckf_corpus import (
    bootstrap_ckf_from_corpus,
    get_corpus_ckf,
    query_corpus_ckf,
)
from crp_comply.agent.corpus import scraped_output_dir


class _FakeFact:
    def __init__(self, text: str, confidence: float = 0.9) -> None:
        self.text = text
        self.confidence = confidence


class _FakeCKF:
    def __init__(self) -> None:
        self.facts: list[_FakeFact] = []
        self._persisted: str | None = None

    def fact_count(self) -> int:
        return len(self.facts)

    def query(
        self,
        *,
        entity_type: str | None = None,
        relationship_type: Any | None = None,
        min_confidence: float = 0.0,
        max_results: int = 200,
    ) -> Any:
        filtered = [f for f in self.facts if f.confidence >= min_confidence]
        return SimpleNamespace(facts=filtered[:max_results])

    def store(self, facts: list[Any], *, window_id: str = "") -> None:
        self.facts.extend(facts)

    def snapshot(self, path: str) -> None:
        self._persisted = path

    def restore(self, path: str) -> None:
        pass


@pytest.fixture
def isolated_ckf(monkeypatch, tmp_path):
    """Provide a fresh corpus CKF backed by a temporary data directory."""
    monkeypatch.setenv("CRP_COMPLY_DATA_DIR", str(tmp_path))
    fake = _FakeCKF()
    monkeypatch.setattr(
        "crp_comply.agent.ckf_corpus._corpus_ckf",
        fake,
    )
    # get_corpus_ckf returns the singleton; ensure it is the fake.
    monkeypatch.setattr(
        "crp_comply.agent.ckf_corpus.get_corpus_ckf",
        lambda: fake,
    )
    # Point scraped output to a temp dir so we can write JSONL facts.
    scraped = tmp_path / "corpus_scraped"
    scraped.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CRP_COMPLY_SCRAPED_DIR", str(scraped))
    return fake, tmp_path


class TestBootstrap:
    def test_bootstrap_loads_jsonl_facts(self, isolated_ckf):
        fake, tmp_path = isolated_ckf
        facts_dir = scraped_output_dir() / "facts"
        facts_dir.mkdir(parents=True, exist_ok=True)
        facts_file = facts_dir / "gdpr.jsonl"
        records = [
            {"text": "Controllers must implement appropriate measures.", "confidence": 0.92},
            {"text": "Processors act on behalf of the controller.", "confidence": 0.88},
        ]
        facts_file.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")

        loaded = bootstrap_ckf_from_corpus()
        assert loaded == 2
        assert fake.fact_count() == 2
        assert fake._persisted is not None

    def test_bootstrap_is_idempotent(self, isolated_ckf):
        fake, tmp_path = isolated_ckf
        facts_dir = scraped_output_dir() / "facts"
        facts_dir.mkdir(parents=True, exist_ok=True)
        facts_file = facts_dir / "eu_ai_act.jsonl"
        facts_file.write_text(
            json.dumps(
                {"text": "High-risk systems require a risk management system.", "confidence": 0.95}
            )
            + "\n",
            encoding="utf-8",
        )

        first = bootstrap_ckf_from_corpus()
        assert first == 1
        # Pre-seed the fake so the second call sees an existing CKF.
        assert fake.fact_count() == 1

        # A second bootstrap should report the existing count without loading again.
        second = bootstrap_ckf_from_corpus()
        assert second == 1


class TestQuery:
    def test_query_returns_facts(self, isolated_ckf):
        fake, _ = isolated_ckf
        fake.facts = [
            _FakeFact("Controllers must implement appropriate measures."),
            _FakeFact("Processors act on behalf of the controller."),
            _FakeFact("Data subjects have the right to erasure."),
        ]

        results = query_corpus_ckf(pattern="controller", max_results=10)
        assert len(results) == 2
        texts = {f.text for f in results}
        assert "Controllers must implement appropriate measures." in texts
        assert "Processors act on behalf of the controller." in texts

    def test_query_filters_by_min_confidence(self, isolated_ckf):
        fake, _ = isolated_ckf
        fake.facts = [
            _FakeFact("High confidence fact.", confidence=0.9),
            _FakeFact("Low confidence fact.", confidence=0.3),
        ]

        results = query_corpus_ckf(min_confidence=0.5)
        assert len(results) == 1
        assert results[0].text == "High confidence fact."

    def test_query_respects_max_results(self, isolated_ckf):
        fake, _ = isolated_ckf
        fake.facts = [_FakeFact(f"fact {i}") for i in range(20)]

        results = query_corpus_ckf(max_results=5)
        assert len(results) == 5


class TestGetCorpusCKF:
    def test_get_corpus_ckf_returns_same_instance(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CRP_COMPLY_DATA_DIR", str(tmp_path))
        first = get_corpus_ckf()
        second = get_corpus_ckf()
        assert first is second
