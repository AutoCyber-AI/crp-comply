# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Smoke tests for the FastAPI lifespan bootstrap (Phase 6)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI


@pytest.mark.asyncio
async def test_lifespan_invokes_ckf_bootstrap(monkeypatch, tmp_path):
    """The lifespan background task calls corpus CKF bootstrap when enabled."""
    monkeypatch.setenv("CRP_COMPLY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CRP_COMPLY_JWT_SECRET", "test-jwt-secret-for-lifespan")
    monkeypatch.setenv("CRP_COMPLY_RAG_BOOTSTRAP", "true")
    monkeypatch.setenv("CRP_COMPLY_BOOTSTRAP_CKF", "true")
    # Disable the forever-running maintenance loops so the only background task
    # we need to worry about is the corpus bootstrap.
    monkeypatch.setenv("CRP_COMPLY_RETENTION_ENABLED", "false")
    monkeypatch.setenv("CRP_COMPLY_BACKUP_INPROCESS", "false")

    scraped_dir = tmp_path / "corpus_scraped"
    scraped_dir.mkdir(parents=True, exist_ok=True)
    # A pre-existing scraped JSON prevents the lifespan from trying to hit live
    # EUR-Lex / NIST endpoints in the test.
    (scraped_dir / "gdpr.json").write_text(
        json.dumps({"source_id": "gdpr", "chunks": []}), encoding="utf-8"
    )

    from crp_comply.api.app import lifespan

    ckf_mock = MagicMock(return_value=1234)

    fake_index = MagicMock()
    fake_index.__enter__ = MagicMock(return_value=fake_index)
    fake_index.__exit__ = MagicMock(return_value=False)
    fake_index.stats.return_value = {"total_chunks": 0}

    app = FastAPI()

    with (
        patch("crp_comply.agent.ckf_corpus.bootstrap_ckf_from_corpus", ckf_mock),
        patch("crp_comply.agent.corpus.scraped_output_dir", lambda: scraped_dir),
        patch("crp_comply.agent.rag.CorpusIndex", return_value=fake_index),
        patch(
            "crp_comply.agent.rag.build_from_scraped",
            return_value={"total_chunks": 1, "sources": ["gdpr"]},
        ),
    ):
        async with lifespan(app):
            # Give the background bootstrap task time to run to completion.
            await asyncio.sleep(0.5)

    ckf_mock.assert_called_once()
