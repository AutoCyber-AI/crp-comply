# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for the derivation manifest (Gap #7 — staleness detection)."""

from __future__ import annotations

from crp_comply.recipes.derivation import (
    build_manifest,
    diff_manifests,
    is_stale,
)


def _base(**overrides):
    base = {
        "recipe_id": "iso_42001_soa",
        "recipe_version": "1.0.0",
        "profile": {"sector": "fintech", "deploys_high_risk": True},
        "inputs": {"organisation": "Acme", "scope": "CV bot"},
        "artefact_index": {"a1": "sha-aaa", "a2": "sha-bbb"},
        "proxy_window": {
            "total_requests": 100,
            "blocked_requests": 2,
            "pii_input_count": 5,
            "pii_output_count": 1,
            "injection_count": 0,
            "window_start": "2026-01-01T00:00:00+00:00",
            "window_end": "2026-01-08T00:00:00+00:00",
        },
        "corpus_manifest_hash": "deadbeef",
    }
    base.update(overrides)
    return base


def test_identical_inputs_produce_identical_manifests():
    m1 = build_manifest(**_base())
    m2 = build_manifest(**_base())
    # generated_at differs but the substantive hashes must match
    assert m1.profile_hash == m2.profile_hash
    assert m1.input_hash == m2.input_hash
    assert m1.artefact_hashes == m2.artefact_hashes
    assert m1.corpus_manifest_hash == m2.corpus_manifest_hash
    assert diff_manifests(m1, m2) == []
    assert is_stale(m1, m2) is False


def test_proxy_signature_ignores_window_timestamps():
    m1 = build_manifest(**_base())
    later_window = dict(m1.proxy_window)
    later_window.update(
        {
            "window_start": "2030-12-31T00:00:00+00:00",
            "window_end": "2030-12-31T23:59:59+00:00",
        }
    )
    m2 = build_manifest(**_base(proxy_window=later_window))
    # Same counters, different window timestamps — must NOT be stale.
    assert diff_manifests(m1, m2) == []


def test_profile_change_is_detected():
    m1 = build_manifest(**_base())
    m2 = build_manifest(**_base(profile={"sector": "fintech", "deploys_high_risk": False}))
    reasons = diff_manifests(m1, m2)
    assert any("profile" in r.lower() for r in reasons)


def test_artefact_added_removed_and_mutated_are_detected():
    m1 = build_manifest(**_base())
    # mutate a1, drop a2, add a3
    m2 = build_manifest(**_base(artefact_index={"a1": "sha-NEW", "a3": "sha-ccc"}))
    reasons = diff_manifests(m1, m2)
    joined = " | ".join(reasons).lower()
    assert "a1" in joined
    assert "a2" in joined
    assert "a3" in joined


def test_recipe_version_bump_marks_stale():
    m1 = build_manifest(**_base())
    m2 = build_manifest(**_base(recipe_version="2.0.0"))
    reasons = diff_manifests(m1, m2)
    assert any("version" in r.lower() for r in reasons)
    assert is_stale(m1, m2) is True


def test_injection_count_jump_marks_stale():
    m1 = build_manifest(**_base())
    bumped = dict(m1.proxy_window)
    bumped["injection_count"] = 7
    m2 = build_manifest(**_base(proxy_window=bumped))
    reasons = diff_manifests(m1, m2)
    assert any("proxy" in r.lower() for r in reasons)


def test_round_trip_dict():
    m = build_manifest(**_base())
    restored = type(m).from_dict(m.to_dict())
    assert restored.profile_hash == m.profile_hash
    assert restored.artefact_hashes == m.artefact_hashes
    assert diff_manifests(m, restored) == []
