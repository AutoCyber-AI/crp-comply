# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0.
"""Smoke tests for the new security primitives (PRODUCT_SECURITY.md §4)."""

from __future__ import annotations

import base64
import os
import time

import pytest

from crp_comply.api import evidence_signing, kek, rate_limit, retention, webhooks
from crp_comply.api.auth import Tier


# ── rate_limit ─────────────────────────────────────────────────


def test_rate_limit_allow_and_deny(monkeypatch):
    monkeypatch.setenv("CRP_COMPLY_RATE_LIMITS", '{"free": 3, "anonymous": 3}')
    rate_limit._reset_for_tests()
    for _ in range(3):
        allowed, _rem, _lim = rate_limit._allow("u1", Tier.FREE, "default")
        assert allowed
    allowed, _rem, _lim = rate_limit._allow("u1", Tier.FREE, "default")
    assert not allowed


def test_rate_limit_per_user_independence(monkeypatch):
    monkeypatch.setenv("CRP_COMPLY_RATE_LIMITS", '{"free": 2}')
    rate_limit._reset_for_tests()
    for _ in range(2):
        assert rate_limit._allow("alice", Tier.FREE, "g")[0]
    assert not rate_limit._allow("alice", Tier.FREE, "g")[0]
    assert rate_limit._allow("bob", Tier.FREE, "g")[0]


# ── webhooks ──────────────────────────────────────────────────


def test_webhook_sign_verify_roundtrip():
    secret = "whsec_test_" + "a" * 32
    payload = b'{"event":"report.created","id":"r_1"}'
    header = webhooks.sign_payload(secret, payload)
    assert header.startswith("t=") and ",v1=" in header
    assert webhooks.verify_signature(secret, payload, header)
    assert not webhooks.verify_signature(secret, payload + b"x", header)


def test_webhook_replay_window_rejects_stale():
    secret = "whsec_test"
    payload = b"{}"
    stale_ts = int(time.time()) - 10_000
    header = webhooks.sign_payload(secret, payload, ts=stale_ts)
    assert not webhooks.verify_signature(secret, payload, header, tolerance_seconds=300)


# ── evidence_signing ──────────────────────────────────────────


def test_evidence_signing_roundtrip(tmp_path):
    key = evidence_signing.load_or_create_keys(tmp_path)
    assert key.algorithm in ("ed25519", "hmac-sha256-fallback")
    assert key.fingerprint
    data = b'{"manifest":"evidence","n":1}'
    sig = evidence_signing.sign(data, key)
    pub = sig.public_key_b64 or ""
    assert evidence_signing.verify(data, sig.signature_b64, pub)
    assert not evidence_signing.verify(data + b"!", sig.signature_b64, pub)


def test_evidence_signing_rotation_archives_old_key(tmp_path):
    k1 = evidence_signing.load_or_create_keys(tmp_path)
    k2 = evidence_signing.rotate_keys(tmp_path)
    assert k1.fingerprint != k2.fingerprint
    history = tmp_path / ".keys" / "history"
    assert history.exists()
    assert any(history.iterdir())


# ── retention ─────────────────────────────────────────────────


def test_retention_policy_bounds(tmp_path):
    retention.init_retention_store(data_dir=tmp_path)
    rs = retention.get_retention_store()
    p = rs.set("user1", Tier.PRO, reports_days=200, evidence_days=500, traces_days=30)
    assert p.reports_days == 200
    with pytest.raises(ValueError):
        rs.set("user1", Tier.PRO, reports_days=10)
    with pytest.raises(ValueError):
        rs.set("user1", Tier.PRO, traces_days=9999)


def test_retention_free_tier_capped(tmp_path):
    retention.init_retention_store(data_dir=tmp_path)
    rs = retention.get_retention_store()
    with pytest.raises(ValueError):
        rs.set("free_user", Tier.FREE, reports_days=3000)


def test_retention_default_policy(tmp_path):
    retention.init_retention_store(data_dir=tmp_path)
    rs = retention.get_retention_store()
    p = rs.get("never_configured")
    assert p.reports_days > 0 and p.evidence_days > 0 and p.traces_days > 0


# ── kek ───────────────────────────────────────────────────────


def test_kek_seal_open_roundtrip(monkeypatch):
    key_b64 = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("CRP_COMPLY_KEK_CHAIN", f"v1={key_b64}")
    kek._reset_for_tests()
    env = kek.seal("super-secret-api-key")
    assert env.startswith("v1.")
    pt, version = kek.open_envelope(env)
    assert pt == b"super-secret-api-key"
    assert version == 1


def test_kek_rotation_triggers_rewrap(monkeypatch):
    k1 = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("CRP_COMPLY_KEK_CHAIN", f"v1={k1}")
    kek._reset_for_tests()
    env1 = kek.seal("payload")

    k2 = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("CRP_COMPLY_KEK_CHAIN", f"v1={k1}:v2={k2}")
    kek._reset_for_tests()
    assert kek.needs_rewrap(env1)
    env2 = kek.rewrap(env1)
    assert env2.startswith("v2.")
    pt, version = kek.open_envelope(env2)
    assert pt == b"payload"
    assert version == 2
