# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for Round 9 sidecar client intent-aware routing."""

from __future__ import annotations

from unittest.mock import patch

from crp_comply.sidecar_client import (
    SidecarConfig,
    compare_documents,
    research_intelligent,
    search,
    vendor_profile,
)


def _cfg() -> SidecarConfig:
    return SidecarConfig(base_url="http://search", api_key="key", allow_feedback=True)


class TestSearchRouting:
    def test_search_forwards_intent_and_profile(self) -> None:
        with patch("crp_comply.sidecar_client.httpx.post") as post:
            post.return_value.status_code = 200
            post.return_value.json.return_value = {"results": []}
            search(
                "GDPR Article 6",
                intent="regulation_text",
                profile="crp_comply_official",
                cfg=_cfg(),
            )
        body = post.call_args.kwargs["json"]
        assert body["query"] == "GDPR Article 6"
        assert body["intent"] == "regulation_text"
        assert body["profile"] == "crp_comply_official"

    def test_research_intelligent_forwards_strategy(self) -> None:
        with patch("crp_comply.sidecar_client.httpx.post") as post:
            post.return_value.status_code = 200
            post.return_value.json.return_value = {"results": []}
            research_intelligent(
                "AI Act high-risk requirements",
                intent="regulation_text",
                expansion_strategy="llm",
                rerank_top_k=4,
                cfg=_cfg(),
            )
        body = post.call_args.kwargs["json"]
        assert body["goal"] == "AI Act high-risk requirements"
        assert body["expansion_strategy"] == "llm"
        assert body["rerank_top_k"] == 4

    def test_vendor_profile_payload(self) -> None:
        with patch("crp_comply.sidecar_client.httpx.post") as post:
            post.return_value.status_code = 200
            post.return_value.json.return_value = {"buckets": {}}
            vendor_profile("OpenAI", max_results=5, cfg=_cfg())
        body = post.call_args.kwargs["json"]
        assert body["vendor"] == "OpenAI"
        assert body["max_results"] == 5

    def test_compare_documents_payload(self) -> None:
        with patch("crp_comply.sidecar_client.httpx.post") as post:
            post.return_value.status_code = 200
            post.return_value.json.return_value = {"matrix": {}}
            compare_documents(
                ["doc1", "doc2"],
                claims=["claim A"],
                cfg=_cfg(),
            )
        body = post.call_args.kwargs["json"]
        assert body["documents"] == ["doc1", "doc2"]
        assert body["claims"] == ["claim A"]
