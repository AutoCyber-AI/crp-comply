# Copyright © 2025 Constantinos Vidiniotis. All rights reserved.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for :mod:`crp_comply.sidecar_client`.

These exercise the bearer-auth header, the URL/key environment
contract, error mapping, and the ``self_check`` happy/sad paths
without touching the real network.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import httpx
import pytest

from crp_comply import sidecar_client as sc


def _mock_response(status: int = 200, body: Any | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        json=body if body is not None else {},
        request=httpx.Request("GET", "http://stub/"),
    )


def test_config_from_env_requires_url(monkeypatch):
    monkeypatch.delenv("CRP_COMPLY_SEARCH_URL", raising=False)
    monkeypatch.delenv("CRP_COMPLY_SEARCH_API_KEY", raising=False)
    with pytest.raises(sc.SidecarError):
        sc.SidecarConfig.from_env()


def test_config_from_env_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("CRP_COMPLY_SEARCH_URL", "http://side/")
    monkeypatch.setenv("CRP_COMPLY_SEARCH_API_KEY", "k")
    cfg = sc.SidecarConfig.from_env()
    assert cfg.base_url == "http://side"
    assert cfg.api_key == "k"


def test_health_sends_bearer_and_returns_json():
    cfg = sc.SidecarConfig(base_url="http://side", api_key="secret")

    captured: dict[str, Any] = {}

    def fake_get(url: str, **kw: Any) -> httpx.Response:
        captured["url"] = url
        captured["headers"] = kw.get("headers") or {}
        return _mock_response(200, {"status": "ok", "backend": "local"})

    with patch.object(sc.httpx, "get", side_effect=fake_get):
        out = sc.health(cfg)

    assert out == {"status": "ok", "backend": "local"}
    assert captured["url"] == "http://side/health"
    assert captured["headers"]["authorization"] == "Bearer secret"


def test_health_maps_http_error():
    cfg = sc.SidecarConfig(base_url="http://side", api_key=None)
    with patch.object(sc.httpx, "get", return_value=_mock_response(503, {"e": "x"})):
        with pytest.raises(sc.SidecarError):
            sc.health(cfg)


def test_search_posts_payload():
    cfg = sc.SidecarConfig(base_url="http://side", api_key="k")
    seen: dict[str, Any] = {}

    def fake_post(url: str, **kw: Any) -> httpx.Response:
        seen["url"] = url
        seen["json"] = kw.get("json")
        return _mock_response(200, {"hits": [], "blocked": 0})

    with patch.object(sc.httpx, "post", side_effect=fake_post):
        out = sc.search("GDPR Art. 6", profile="crp_comply_official", cfg=cfg)

    assert out == {"hits": [], "blocked": 0}
    assert seen["url"] == "http://side/search"
    assert seen["json"]["query"] == "GDPR Art. 6"
    assert seen["json"]["profile"] == "crp_comply_official"
    assert seen["json"]["fetch_full_text"] is False


def test_self_check_happy_path():
    cfg = sc.SidecarConfig(base_url="http://side", api_key="k")

    def fake_get(url: str, **kw: Any) -> httpx.Response:
        return _mock_response(200, {"status": "ok", "backend": "local"})

    def fake_post(url: str, **kw: Any) -> httpx.Response:
        return _mock_response(200, {"hits": [{"url": "x"}], "blocked": 0})

    with (
        patch.object(sc.httpx, "get", side_effect=fake_get),
        patch.object(sc.httpx, "post", side_effect=fake_post),
    ):
        report = sc.self_check(cfg)

    assert report["ok"] is True
    assert report["health"]["status"] == "ok"
    assert report["search"]["hits"]
    assert report["errors"] == []
    assert report["auth"] == "bearer"


def test_self_check_health_failure_short_circuits():
    cfg = sc.SidecarConfig(base_url="http://side", api_key=None)

    with (
        patch.object(sc.httpx, "get", side_effect=httpx.ConnectError("boom")),
        patch.object(sc.httpx, "post") as posted,
    ):
        report = sc.self_check(cfg)

    assert report["ok"] is False
    assert any("health" in e for e in report["errors"])
    assert posted.called is False
    assert report["auth"] == "none"


def test_self_check_search_failure_keeps_health(monkeypatch):
    cfg = sc.SidecarConfig(base_url="http://side", api_key="k")

    with (
        patch.object(sc.httpx, "get", return_value=_mock_response(200, {"status": "ok"})),
        patch.object(sc.httpx, "post", return_value=_mock_response(401, {"e": "x"})),
    ):
        report = sc.self_check(cfg)

    assert report["ok"] is False
    assert report["health"]["status"] == "ok"
    assert any("search" in e for e in report["errors"])
