# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for Phase 5b sidecar hardening: retries, circuit breaker, cache."""

from __future__ import annotations

from unittest import mock

import pytest

from crp_comply import sidecar_client
from crp_comply.sidecar_client import (
    SidecarConfig,
    SidecarError,
    SidecarTimeoutError,
    research_intelligent,
)


def _cfg() -> SidecarConfig:
    return SidecarConfig(base_url="http://sidecar.test", api_key="key", timeout=1.0)


@pytest.fixture(autouse=True)
def _reset_circuit():
    sidecar_client._circuit._state.clear()
    sidecar_client._cache._store.clear()


def test_retry_on_503_then_success():
    cfg = _cfg()
    responses = [
        mock.MagicMock(status_code=503, text="busy"),
        mock.MagicMock(status_code=503, text="busy"),
        mock.MagicMock(status_code=200, json=lambda: {"ok": True}),
    ]
    with mock.patch("httpx.post", side_effect=responses) as post:
        result = sidecar_client._post(cfg, "/test", {"q": "x"})
        assert result == {"ok": True}
        assert post.call_count == 3


def test_retry_gives_up_after_max_attempts():
    cfg = _cfg()
    responses = [mock.MagicMock(status_code=503, text="busy") for _ in range(3)]
    with mock.patch("httpx.post", side_effect=responses):
        with pytest.raises(SidecarError):
            sidecar_client._post(cfg, "/test", {"q": "x"})


def test_circuit_opens_after_threshold():
    cfg = _cfg()
    bad = mock.MagicMock(status_code=503, text="busy")
    with mock.patch("httpx.post", return_value=bad):
        for _ in range(5):
            with pytest.raises(SidecarError):
                sidecar_client._post(cfg, "/test", {"q": "x"})
    with pytest.raises(SidecarError, match="circuit open"):
        sidecar_client._post(cfg, "/test", {"q": "x"})


def test_research_intelligent_cache_hit():
    cfg = _cfg()
    good = mock.MagicMock(status_code=200, json=lambda: {"results": ["a"]})
    with mock.patch("httpx.post", return_value=good) as post:
        r1 = research_intelligent("goal", cfg=cfg)
        r2 = research_intelligent("goal", cfg=cfg)
        assert r1 == r2
        assert r2.get("_cached")
        assert post.call_count == 1


def test_timeout_raises_structured_timeout_error():
    cfg = _cfg()
    import httpx

    with mock.patch("httpx.post", side_effect=httpx.TimeoutException("deadline")):
        with pytest.raises(SidecarTimeoutError) as exc_info:
            sidecar_client._post(cfg, "/test", {"q": "x"})
        payload = exc_info.value.args[0]
        assert "timeout" in payload
        assert "fallback" in payload
