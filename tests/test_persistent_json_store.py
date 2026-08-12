# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for the generic file/Redis JSON persistence layer."""

from __future__ import annotations

from crp_comply.persistent_json_store import FileJsonStore, get_json_store


def test_file_json_store_round_trip(tmp_path):
    store = FileJsonStore(tmp_path / "kv")
    assert store.get("tenant:a") is None
    store.set("tenant:a", {"x": 1})
    assert store.get("tenant:a") == {"x": 1}
    assert store.delete("tenant:a") is True
    assert store.get("tenant:a") is None
    assert store.delete("tenant:a") is False


def test_file_json_store_list_keys(tmp_path):
    store = FileJsonStore(tmp_path / "kv")
    store.set("user:1", {"a": 1})
    store.set("user:2", {"b": 2})
    store.set("org:1", {"c": 3})
    keys = store.list_keys("user:")
    assert sorted(keys) == ["user_1", "user_2"]


def test_get_json_store_defaults_to_file(monkeypatch, tmp_path):
    monkeypatch.setenv("CRP_COMPLY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CRP_COMPLY_PERSISTENCE_STORE", "file")
    store = get_json_store("sessions")
    assert isinstance(store, FileJsonStore)
    store.set("a", {"ok": True})
    assert store.get("a") == {"ok": True}


def test_get_json_store_redis_without_redis_url(monkeypatch):
    """Redis backend should degrade gracefully when redis is unreachable."""
    monkeypatch.setenv("CRP_COMPLY_PERSISTENCE_STORE", "redis")
    monkeypatch.delenv("CRP_COMPLY_REDIS_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    store = get_json_store("sessions")
    # Without a Redis server, get/set/delete are no-ops and do not raise.
    store.set("a", {"ok": True})
    assert store.get("a") is None
    assert store.delete("a") is False


def test_file_store_ignores_malformed_json(tmp_path):
    store = FileJsonStore(tmp_path / "kv")
    store.set("good", {"ok": True})
    bad_path = store._path("bad")
    bad_path.write_text("not json", encoding="utf-8")
    assert store.get("bad") is None
    assert store.get("good") == {"ok": True}
