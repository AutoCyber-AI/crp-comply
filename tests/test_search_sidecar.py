"""Tests for the crp-comply-search sidecar (PHASE_7 \u00a77.8)."""

from __future__ import annotations

import time
from typing import Any
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from crp_comply_search.app import AppConfig, create_app
from crp_comply_search.backends import (
    BackendDisabledError,
    BraveBackend,
    LocalDDGBackend,
    SearchHit,
    SearchResult,
    TavilyBackend,
    apply_trust_tier,
)
from crp_comply_search.profiles import (
    ProfileError,
    ProfileRegistry,
    TrustTierProfile,
    default_profiles_dir,
)
from crp_comply_search.rate_limiter import DDGRateLimiter


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def registry() -> ProfileRegistry:
    return ProfileRegistry.load_dir(default_profiles_dir())


@pytest.fixture
def official(registry: ProfileRegistry) -> TrustTierProfile:
    return registry.get("crp_comply_official")


class StubBackend:
    """Hand-rolled :class:`WebSearchBackend` for FastAPI tests."""

    name = "local"

    def __init__(self, hits: list[SearchHit]) -> None:
        self._hits = hits
        self.search_calls: list[dict[str, Any]] = []

    def search(
        self,
        query: str,
        *,
        profile,
        freshness,
        max_results,
        fetch_full_text,
        intent: str | None = None,
    ):
        self.search_calls.append(
            {
                "query": query,
                "profile": profile.name,
                "freshness": freshness,
                "max_results": max_results,
                "intent": intent,
            }
        )
        kept, blocked = apply_trust_tier(list(self._hits), profile)
        return SearchResult(
            query=query,
            backend="local",
            profile=profile.name,
            results=kept,
            blocked=blocked,
            latency_ms=1.0,
        )

    def research(
        self,
        queries,
        *,
        profile,
        freshness,
        max_results,
        fetch_full_text,
        intent: str | None = None,
    ):
        kept, blocked = apply_trust_tier(list(self._hits), profile)
        return SearchResult(
            query=next(iter(queries)),
            backend="local",
            profile=profile.name,
            results=kept,
            blocked=blocked,
            latency_ms=2.0,
        )


def _hit(url: str, title: str = "T", snippet: str = "S") -> SearchHit:
    return SearchHit(
        title=title,
        url=url,
        snippet=snippet,
        domain="",
        trust_tier=4,
        weight=0.0,
        blocked=False,
    )


# ── Profile schema validation ────────────────────────────────────────


class TestProfileSchema:
    def test_loads_bundled_official_profile(self, official):
        assert official.name == "crp-comply-official"
        assert official.version == 1
        assert "reddit.com" in official.blocked
        assert official.tiers[1][0] == 1.0  # weight
        assert "edpb.europa.eu" in official.tiers[1][1]

    def test_loads_bundled_news_profile(self, registry):
        news = registry.get("crp_comply_news")
        assert news.name == "crp-comply-news"
        # Reuters is T2 in the news profile (boosted vs official).
        tier, weight, blocked = news.classify("https://www.reuters.com/x")
        assert tier == 2
        assert blocked is False
        assert weight == 0.9

    def test_classify_handles_subdomains(self, official):
        tier, _, _ = official.classify("https://edpb.europa.eu/news")
        assert tier == 1

    def test_classify_blocked_overrides_tier(self, official):
        tier, weight, blocked = official.classify("https://www.reddit.com/r/foo")
        assert blocked is True
        assert weight == 0.0

    def test_classify_generic_domain_is_t4(self, official):
        tier, weight, blocked = official.classify("https://random-blog.example.org/post")
        assert tier == 4
        assert blocked is False
        assert weight == 0.5

    def test_suffix_match_does_not_cross_label_boundary(self, official):
        # europa.eu is T1; europa.eu.evil.example must NOT be T1.
        tier, _, _ = official.classify("https://europa.eu.evil.example")
        assert tier == 4

    def test_malformed_profile_missing_name(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text("version: 1\ntiers: {}\n", encoding="utf-8")
        with pytest.raises(ProfileError, match="profile.name"):
            TrustTierProfile.from_yaml(path)

    def test_malformed_profile_bad_tier_weight(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text(
            "name: x\nversion: 1\ntiers:\n  1:\n    weight: 5\n    domains: []\n",
            encoding="utf-8",
        )
        with pytest.raises(ProfileError, match=r"weight must be in"):
            TrustTierProfile.from_yaml(path)

    def test_malformed_profile_unknown_tier_key(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text(
            "name: x\nversion: 1\ntiers:\n  9:\n    weight: 0.5\n    domains: []\n",
            encoding="utf-8",
        )
        with pytest.raises(ProfileError, match=r"tier 9 out of range"):
            TrustTierProfile.from_yaml(path)


# ── Trust-tier filter behaviour ──────────────────────────────────────


class TestTrustTierFilter:
    def test_drops_blocked_hits_and_counts_them(self, official):
        hits = [
            _hit("https://www.reddit.com/r/x"),
            _hit("https://eur-lex.europa.eu/eli/reg/2016/679"),
            _hit("https://twitter.com/foo"),
        ]
        kept, blocked = apply_trust_tier(hits, official)
        assert blocked == 2
        assert len(kept) == 1
        assert kept[0].domain == "eur-lex.europa.eu"
        assert kept[0].trust_tier == 1

    def test_sorts_by_tier_weight_descending(self, official):
        hits = [
            _hit("https://random.example.com/a"),  # T4 0.5
            _hit("https://eur-lex.europa.eu/x"),  # T1 1.0
            _hit("https://openai.com/policies/usage"),  # T2 0.85
        ]
        kept, _ = apply_trust_tier(hits, official)
        domains = [h.domain for h in kept]
        assert domains == [
            "eur-lex.europa.eu",
            "openai.com",
            "random.example.com",
        ]


# ── Stubbed backends fail loud ───────────────────────────────────────


class TestStubBackends:
    def test_brave_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("CRP_COMPLY_ENABLE_BRAVE", raising=False)
        with pytest.raises(BackendDisabledError, match="Brave"):
            BraveBackend(api_key="k")

    def test_tavily_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("CRP_COMPLY_ENABLE_TAVILY", raising=False)
        with pytest.raises(BackendDisabledError, match="Tavily"):
            TavilyBackend(api_key="k")

    def test_brave_enabled_without_key_still_raises(self, monkeypatch):
        monkeypatch.setenv("CRP_COMPLY_ENABLE_BRAVE", "1")
        with pytest.raises(BackendDisabledError, match="BRAVE_API_KEY"):
            BraveBackend(api_key=None)

    def test_brave_enabled_with_key_can_be_instantiated(self, monkeypatch):
        # The backend is now implemented; it should instantiate cleanly when
        # enabled and a key is supplied.
        monkeypatch.setenv("CRP_COMPLY_ENABLE_BRAVE", "1")
        backend = BraveBackend(api_key="k")
        assert backend.name == "brave"
        assert backend.api_key == "k"


# ── Rate limiter ─────────────────────────────────────────────────────


class TestRateLimiter:
    def test_first_acquire_is_immediate(self):
        lim = DDGRateLimiter(min_delay=0.05)
        assert lim.acquire() == 0.0

    def test_second_acquire_blocks(self):
        lim = DDGRateLimiter(min_delay=0.05)
        lim.acquire()
        t0 = time.perf_counter()
        lim.acquire()
        elapsed = time.perf_counter() - t0
        assert elapsed >= 0.04  # allow small clock slop


# ── LocalDDGBackend audit fields ─────────────────────────────────────


class TestLocalDDGAudit:
    def test_content_hash_stable_for_same_body(self, official):
        backend = LocalDDGBackend()

        # Stub out the network.
        canned_html = "<html><body><p>EU AI Act compliance.</p></body></html>"
        with (
            mock.patch.object(
                LocalDDGBackend,
                "_ddg_search",
                return_value=[
                    _hit("https://eur-lex.europa.eu/eli/reg/2024/1689", "AI Act"),
                ],
            ),
            mock.patch("crp_comply_search.backends.httpx.Client") as mock_cli,
        ):
            mock_resp = mock.Mock(status_code=200, text=canned_html)
            mock_cli.return_value.__enter__.return_value.get.return_value = mock_resp
            r1 = backend.search("ai act", profile=official, max_results=1)
            r2 = backend.search("ai act", profile=official, max_results=1)

        assert r1.results and r2.results
        h1 = r1.results[0]
        h2 = r2.results[0]
        assert h1.content_hash
        assert h1.content_hash == h2.content_hash
        assert h1.raw_text_blob_id == f"sha256:{h1.content_hash}"
        assert "EU AI Act compliance" in h1.full_text


# ── FastAPI surface ──────────────────────────────────────────────────


@pytest.fixture
def app_with_stub(registry: ProfileRegistry):
    backend = StubBackend(
        [
            _hit("https://eur-lex.europa.eu/eli/reg/2024/1689", "AI Act"),
            _hit("https://www.reddit.com/r/lawtech", "noise"),
            _hit("https://random.example.org/post", "blog"),
        ]
    )
    cfg = AppConfig(
        backend="local",
        profile_name="crp_comply_official",
        api_key="secret-key",
    )
    app = create_app(cfg, backend=backend, registry=registry)
    return app, backend


class TestApiRoutes:
    def test_health_no_auth_required(self, app_with_stub):
        app, _ = app_with_stub
        client = TestClient(app)
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["backend"] == "local"
        assert "crp_comply_official" in body["profiles"]

    def test_search_requires_bearer(self, app_with_stub):
        app, _ = app_with_stub
        client = TestClient(app)
        r = client.post("/search", json={"query": "AI Act"})
        assert r.status_code == 401

    def test_search_rejects_wrong_bearer(self, app_with_stub):
        app, _ = app_with_stub
        client = TestClient(app)
        r = client.post(
            "/search",
            headers={"Authorization": "Bearer nope"},
            json={"query": "AI Act"},
        )
        assert r.status_code == 401

    def test_search_returns_filtered_hits(self, app_with_stub):
        app, _ = app_with_stub
        client = TestClient(app)
        r = client.post(
            "/search",
            headers={"Authorization": "Bearer secret-key"},
            json={"query": "EU AI Act"},
        )
        assert r.status_code == 200
        body = r.json()
        # reddit.com must be dropped; eur-lex must rank above the
        # generic example.org domain.
        domains = [h["domain"] for h in body["results"]]
        assert "reddit.com" not in domains
        assert domains[0] == "eur-lex.europa.eu"
        assert body["blocked"] == 1
        assert body["backend"] == "local"

    def test_search_unknown_profile_400(self, app_with_stub):
        app, _ = app_with_stub
        client = TestClient(app)
        r = client.post(
            "/search",
            headers={"Authorization": "Bearer secret-key"},
            json={"query": "x", "profile": "does-not-exist"},
        )
        assert r.status_code == 400

    def test_search_extra_fields_rejected(self, app_with_stub):
        app, _ = app_with_stub
        client = TestClient(app)
        r = client.post(
            "/search",
            headers={"Authorization": "Bearer secret-key"},
            json={"query": "x", "evil_override_block_list": ["nist.gov"]},
        )
        # extra="forbid" on the request model.
        assert r.status_code == 422

    def test_research_multi_query(self, app_with_stub):
        app, backend = app_with_stub
        client = TestClient(app)
        r = client.post(
            "/research",
            headers={"Authorization": "Bearer secret-key"},
            json={"queries": ["a", "b", "c"]},
        )
        assert r.status_code == 200
        assert r.json()["backend"] == "local"

    def test_metrics_exposed(self, app_with_stub):
        app, _ = app_with_stub
        client = TestClient(app)
        client.post(
            "/search",
            headers={"Authorization": "Bearer secret-key"},
            json={"query": "AI Act"},
        )
        r = client.get("/metrics")
        assert r.status_code == 200
        assert "crp_comply_search_requests_total" in r.text


class TestStartupValidation:
    def test_unknown_backend_falls_back_to_official(self, registry):
        cfg = AppConfig(
            backend="local",
            profile_name="does_not_exist",
            api_key=None,
        )
        # Should NOT raise — falls back to crp_comply_official with a warning.
        app = create_app(cfg, registry=registry)
        assert app.state.config.profile_name == "crp_comply_official"

    def test_brave_backend_without_env_fails_at_create_app(self, registry, monkeypatch):
        monkeypatch.delenv("CRP_COMPLY_ENABLE_BRAVE", raising=False)
        cfg = AppConfig(
            backend="brave",
            profile_name="crp_comply_official",
            api_key=None,
        )
        with pytest.raises(BackendDisabledError):
            create_app(cfg, registry=registry)
