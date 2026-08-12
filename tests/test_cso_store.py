# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for CRP Comply CSO store adapters."""

from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from crp_comply.agent.cso_store import FileCSOStore, RedisCSOStore, get_cso_store


@pytest.fixture
def temp_data_dir():
    with tempfile.TemporaryDirectory() as tmp:
        yield tmp


class TestFileCSOStore:
    def test_round_trip(self, temp_data_dir):
        store = FileCSOStore(temp_data_dir)
        data = {"version": 1, "cso": {"slots": {"x": 1}}}
        store.save("user@example.com", "sess-123", data)
        loaded = store.load("user@example.com", "sess-123")
        assert loaded == data

    def test_load_missing_returns_none(self, temp_data_dir):
        store = FileCSOStore(temp_data_dir)
        assert store.load("user", "sess") is None

    def test_sanitises_unsafe_ids(self, temp_data_dir):
        store = FileCSOStore(temp_data_dir)
        store.save("user/name", "sess:one", {"x": 1})
        loaded = store.load("user/name", "sess:one")
        assert loaded == {"x": 1}


class TestRedisCSOStore:
    def test_round_trip_with_mock_redis(self):
        fake_redis = MagicMock()
        fake_redis.get.return_value = json.dumps({"version": 1})
        store = RedisCSOStore(url="redis://localhost:6379/0", ttl_seconds=60)
        store._client = fake_redis

        loaded = store.load("user", "sess")
        assert loaded == {"version": 1}
        fake_redis.get.assert_called_once_with("crp:comply:memory:user:sess")

        store.save("user", "sess", {"version": 2})
        fake_redis.setex.assert_called_once()
        key, ttl, raw = fake_redis.setex.call_args.args
        assert key == "crp:comply:memory:user:sess"
        assert ttl == 60
        assert json.loads(raw) == {"version": 2}

    def test_load_missing_returns_none(self):
        fake_redis = MagicMock()
        fake_redis.get.return_value = None
        store = RedisCSOStore()
        store._client = fake_redis
        assert store.load("user", "sess") is None

    def test_load_failure_returns_none(self):
        fake_redis = MagicMock()
        fake_redis.get.side_effect = Exception("redis down")
        store = RedisCSOStore()
        store._client = fake_redis
        assert store.load("user", "sess") is None

    def test_save_failure_is_silent(self):
        fake_redis = MagicMock()
        fake_redis.setex.side_effect = Exception("redis down")
        store = RedisCSOStore()
        store._client = fake_redis
        store.save("user", "sess", {"x": 1})  # should not raise


class TestGetCSOStore:
    def test_default_is_file_store(self, temp_data_dir):
        with patch.dict(os.environ, {"CRP_COMPLY_CSO_STORE": ""}, clear=False):
            store = get_cso_store(data_dir=temp_data_dir)
        assert isinstance(store, FileCSOStore)

    def test_env_selects_redis(self, temp_data_dir):
        with patch.dict(os.environ, {"CRP_COMPLY_CSO_STORE": "redis"}, clear=False):
            store = get_cso_store(data_dir=temp_data_dir)
        assert isinstance(store, RedisCSOStore)
