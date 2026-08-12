"""Tests for the SearXNG free meta-search backend (PHASE_7.12 free
alternative track)."""

from __future__ import annotations

from typing import Any
from unittest import mock

import pytest

from crp_comply_search.backends import (
    BackendDisabledError,
    SearXNGBackend,
)
from crp_comply_search.profiles import ProfileRegistry, default_profiles_dir


@pytest.fixture
def official():
    return ProfileRegistry.load_dir(default_profiles_dir()).get("crp_comply_official")


def _mock_searxng_response(rows: list[dict[str, Any]]):
    return {
        "query": "x",
        "number_of_results": len(rows),
        "results": rows,
    }


# ── Construction ────────────────────────────────────────────────────


def test_missing_url_raises_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CRP_COMPLY_SEARXNG_URL", raising=False)
    with pytest.raises(BackendDisabledError):
        SearXNGBackend()


def test_url_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRP_COMPLY_SEARXNG_URL", "https://example.org/")
    b = SearXNGBackend()
    assert b.base_url == "https://example.org"  # trailing slash stripped


def test_engines_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRP_COMPLY_SEARXNG_URL", "https://x.test")
    b = SearXNGBackend()
    assert "bing" in b.engines
    assert "duckduckgo" in b.engines


# ── Result mapping ──────────────────────────────────────────────────


def test_search_maps_results(official) -> None:
    backend = SearXNGBackend(base_url="https://x.test", engines="bing")
    rows = [
        {
            "url": "https://eur-lex.europa.eu/eli/reg/2024/1689",
            "title": "EU AI Act",
            "content": "Regulation 2024/1689 establishes...",
            "engine": "bing",
            "score": 0.93,
        },
        {
            "url": "https://www.reddit.com/r/lawtech",
            "title": "noise",
            "content": "...",
            "engine": "bing",
        },
    ]
    response = mock.Mock(status_code=200)
    response.raise_for_status = mock.Mock()
    response.json = mock.Mock(return_value=_mock_searxng_response(rows))
    with mock.patch("crp_comply_search.backends.httpx.Client") as mock_cli:
        mock_cli.return_value.__enter__.return_value.get.return_value = response
        result = backend.search(
            "ai act",
            profile=official,
            max_results=10,
            fetch_full_text=False,
        )

    # eur-lex retained (official tier), reddit is on the blocklist.
    assert len(result.results) == 1
    hit = result.results[0]
    assert hit.url.startswith("https://eur-lex.europa.eu")
    assert hit.snippet.startswith("Regulation 2024/1689")
    assert hit.domain == "eur-lex.europa.eu"
    assert hit.trust_tier == 1
    assert hit.citation_id.startswith("web:")
    assert result.blocked == 1
    assert result.backend == "searxng"


def test_freshness_passed_as_time_range(official) -> None:
    backend = SearXNGBackend(base_url="https://x.test", engines="bing")
    response = mock.Mock(status_code=200)
    response.raise_for_status = mock.Mock()
    response.json = mock.Mock(return_value=_mock_searxng_response([]))
    captured: dict[str, Any] = {}

    def _get(url: str, params=None):
        captured["url"] = url
        captured["params"] = params
        return response

    with mock.patch("crp_comply_search.backends.httpx.Client") as mock_cli:
        mock_cli.return_value.__enter__.return_value.get.side_effect = _get
        backend.search(
            "ai act", profile=official, freshness="week", max_results=5, fetch_full_text=False
        )

    assert captured["params"]["q"] == "ai act"
    assert captured["params"]["format"] == "json"
    assert captured["params"]["time_range"] == "week"
    assert captured["params"]["engines"] == "bing"


def test_http_error_returns_empty(official) -> None:
    backend = SearXNGBackend(base_url="https://x.test", engines="bing")
    import httpx

    with mock.patch("crp_comply_search.backends.httpx.Client") as mock_cli:
        mock_cli.return_value.__enter__.return_value.get.side_effect = httpx.ConnectError(
            "dns fail"
        )
        result = backend.search("x", profile=official, max_results=5, fetch_full_text=False)
    assert result.results == []
    assert result.backend == "searxng"


def test_research_dedupes_across_queries(official) -> None:
    backend = SearXNGBackend(base_url="https://x.test", engines="bing")
    same_url = "https://eur-lex.europa.eu/eli/reg/2024/1689"
    rows = [
        {"url": same_url, "title": "AI Act", "content": "..."},
        {"url": "https://www.edpb.europa.eu/x", "title": "EDPB", "content": "."},
    ]
    response = mock.Mock(status_code=200)
    response.raise_for_status = mock.Mock()
    response.json = mock.Mock(return_value=_mock_searxng_response(rows))
    with mock.patch("crp_comply_search.backends.httpx.Client") as mock_cli:
        mock_cli.return_value.__enter__.return_value.get.return_value = response
        result = backend.research(
            ["ai act", "ai act regulation"],
            profile=official,
            max_results=5,
            fetch_full_text=False,
        )

    # Two queries × 2 hits = 4 raw, dedupe → 2 unique URLs.
    urls = [h.url for h in result.results]
    assert urls.count(same_url) == 1
    assert any("edpb" in u for u in urls)
