# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for Round 9 web-search feedback wiring."""

from __future__ import annotations

from unittest.mock import patch

from crp_comply.agent.web_client import WebClient
from crp_comply.sidecar_client import SidecarConfig, SidecarError, feedback


class TestWebClientFeedback:
    def test_feedback_passes_url_and_query(self) -> None:
        cfg = SidecarConfig(base_url="http://search", api_key="key", allow_feedback=True)
        client = WebClient(cfg=cfg)
        with patch("crp_comply.sidecar_client._post") as post:
            post.return_value = {"ok": True}
            result = client.feedback(
                intent="guidance",
                engine="searxng",
                useful=True,
                weight=2.0,
                url="https://ico.org.uk/guide",
                query="GDPR AI",
            )
        assert result["ok"] is True
        body = post.call_args.args[2]
        assert body["intent"] == "guidance"
        assert body["engine"] == "searxng"
        assert body["url"] == "https://ico.org.uk/guide"
        assert body["query"] == "GDPR AI"

    def test_feedback_swallows_sidecar_error(self) -> None:
        cfg = SidecarConfig(base_url="http://search", api_key="key", allow_feedback=True)
        client = WebClient(cfg=cfg)
        with patch("crp_comply.sidecar_client._post") as post:
            post.side_effect = SidecarError("down")
            result = client.feedback(intent="general", engine="auto")
        assert result["ok"] is False
        assert "down" in result["error"]


class TestSidecarFeedbackDisabled:
    def test_feedback_disabled_returns_early(self) -> None:
        cfg = SidecarConfig(base_url="http://search", api_key="key", allow_feedback=False)
        with patch("crp_comply.sidecar_client._post") as post:
            result = feedback(intent="general", engine="auto", cfg=cfg)
        assert result["ok"] is False
        assert result["feedback_disabled"] is True
        post.assert_not_called()
