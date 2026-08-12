"""Smoke test for per-host scraper politeness delays (BATCH 2)."""

from __future__ import annotations

import time

from crp_comply.agent.scrapers import base as scraper_base


def test_scraper_delay_enforced_between_calls(monkeypatch):
    monkeypatch.setenv("CRP_COMPLY_SCRAPER_DELAYS", '{"example.test": 0.2, "default": 0.05}')
    scraper_base._reset_scraper_delays_for_tests()
    url = "https://example.test/a"

    t0 = time.monotonic()
    scraper_base._wait_for_host(url)  # first call is free
    scraper_base._wait_for_host(url)  # second call must wait ≥ 0.2s
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.18, f"delay not enforced: {elapsed:.3f}s"


def test_scraper_delay_is_per_host(monkeypatch):
    monkeypatch.setenv("CRP_COMPLY_SCRAPER_DELAYS", '{"a.test": 0.5, "b.test": 0.5}')
    scraper_base._reset_scraper_delays_for_tests()

    # Hitting two distinct hosts back-to-back is fine — no cross-host throttle.
    t0 = time.monotonic()
    scraper_base._wait_for_host("https://a.test/x")
    scraper_base._wait_for_host("https://b.test/y")
    elapsed = time.monotonic() - t0
    assert elapsed < 0.4, f"unexpected cross-host delay: {elapsed:.3f}s"
