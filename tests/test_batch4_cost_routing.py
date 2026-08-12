# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""BATCH 4 — cost telemetry + per-task model routing.

Covers:
* ``UsageTracker.record_tokens`` / ``get_cost_summary`` (design §6.1)
* ``crp_comply.api.model_router.choose`` (design §6.2)
"""

from __future__ import annotations

import json

from crp_comply.api.usage import UsageTracker
from crp_comply.api import model_router


# ── Cost telemetry ───────────────────────────────────────────


def test_record_tokens_aggregates_and_drill_down(tmp_path):
    tracker = UsageTracker(data_dir=tmp_path)
    tracker.record_tokens(
        user_id="u1",
        provider="openai",
        model="gpt-4o-mini",
        input_tokens=1200,
        output_tokens=400,
        cost_usd=0.003,
        session_id="s1",
        latency_ms=850,
    )
    tracker.record_tokens(
        user_id="u1",
        provider="openai",
        model="gpt-4o-mini",
        input_tokens=800,
        output_tokens=200,
        cost_usd=0.002,
        session_id="s1",
    )
    tracker.record_tokens(
        user_id="u1",
        provider="groq",
        model="llama-3.3-70b-versatile",
        input_tokens=5000,
        output_tokens=1000,
        cost_usd=0.001,
        session_id="s2",
    )
    summary = tracker.get_cost_summary("u1")
    assert summary["input_tokens"] == 7000
    assert summary["output_tokens"] == 1600
    assert round(summary["cost_usd"], 6) == 0.006
    # Per-model breakdown
    assert "gpt-4o-mini" in summary["by_model"]
    assert summary["by_model"]["gpt-4o-mini"]["calls"] == 2
    assert summary["by_model"]["llama-3.3-70b-versatile"]["calls"] == 1
    # NDJSON drill-down recorded three rows
    drill = (tmp_path / "usage_tokens.ndjson").read_text(encoding="utf-8").strip().splitlines()
    assert len(drill) == 3
    first = json.loads(drill[0])
    assert first["session_id"] == "s1"
    assert first["input_tokens"] == 1200
    assert first["latency_ms"] == 850


def test_record_tokens_zero_costs_are_safe(tmp_path):
    tracker = UsageTracker(data_dir=tmp_path)
    tracker.record_tokens(
        user_id="u1",
        provider="groq",
        model="llama-3.3-70b-versatile",
        input_tokens=0,
        output_tokens=0,
    )
    summary = tracker.get_cost_summary("u1")
    assert summary["cost_usd"] == 0.0
    assert summary["by_model"]["llama-3.3-70b-versatile"]["calls"] == 1


def test_get_cost_summary_isolates_users(tmp_path):
    tracker = UsageTracker(data_dir=tmp_path)
    tracker.record_tokens(
        user_id="u1",
        provider="openai",
        model="gpt-4o-mini",
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.0005,
    )
    summary_other = tracker.get_cost_summary("u2")
    assert summary_other["input_tokens"] == 0
    assert summary_other["by_model"] == {}


# ── Model router ────────────────────────────────────────────


def test_router_defaults_map_each_task(monkeypatch):
    monkeypatch.delenv("CRP_COMPLY_MODEL_ROUTING", raising=False)
    model_router._reset_for_tests()
    # pro tier gets matrix entries
    ext = model_router.choose("extraction", tier="pro")
    assert ext.provider == "groq"
    assert "llama-3.1-8b-instant" in ext.model
    draft = model_router.choose("drafting", tier="pro")
    assert draft.provider == "groq"


def test_router_starter_tier_uses_default(monkeypatch):
    monkeypatch.delenv("CRP_COMPLY_MODEL_ROUTING", raising=False)
    model_router._reset_for_tests()
    choice = model_router.choose("extraction", tier="starter")
    assert choice.task == "extraction"
    # starter is forced to default — typically the BYOK-friendly path
    assert choice.model == model_router._DEFAULTS["default"]["model"]


def test_router_falls_back_when_provider_unavailable(monkeypatch):
    monkeypatch.delenv("CRP_COMPLY_MODEL_ROUTING", raising=False)
    model_router._reset_for_tests()
    # Escalation defaults to anthropic; if only groq is available the
    # router must fall back to the default groq model.
    choice = model_router.choose("escalation", tier="pro", available_providers=frozenset({"groq"}))
    assert choice.fallback_used is True
    assert choice.provider.lower() == "groq"


def test_router_respects_env_override(monkeypatch):
    monkeypatch.setenv(
        "CRP_COMPLY_MODEL_ROUTING",
        json.dumps({"extraction": {"provider": "anthropic", "model": "claude-haiku-4-5"}}),
    )
    model_router._reset_for_tests()
    try:
        choice = model_router.choose("extraction", tier="enterprise")
        assert choice.provider == "anthropic"
        assert choice.model == "claude-haiku-4-5"
    finally:
        monkeypatch.delenv("CRP_COMPLY_MODEL_ROUTING", raising=False)
        model_router._reset_for_tests()


def test_router_unknown_task_uses_default(monkeypatch):
    monkeypatch.delenv("CRP_COMPLY_MODEL_ROUTING", raising=False)
    model_router._reset_for_tests()
    choice = model_router.choose("nonsense-task", tier="pro")
    assert choice.model == model_router._DEFAULTS["default"]["model"]


def test_router_matrix_summary_is_serialisable(monkeypatch):
    monkeypatch.delenv("CRP_COMPLY_MODEL_ROUTING", raising=False)
    model_router._reset_for_tests()
    summary = model_router.matrix_summary()
    json.dumps(summary)  # must round-trip
    assert "extraction" in summary["matrix"]
