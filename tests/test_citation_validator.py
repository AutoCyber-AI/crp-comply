# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for Round 8 citation validation."""

from __future__ import annotations

from crp_comply.agent.citation_validator import (
    CitationRegistry,
    CitationValidator,
    extract_citation_markers,
)


class TestCitationRegistry:
    def test_add_chunk_id(self) -> None:
        reg = CitationRegistry()
        reg.add({"chunk_id": "eu_ai_act_art_6_001", "score": 0.9})
        assert reg.is_valid("eu_ai_act_art_6_001")
        assert not reg.is_surrogate("eu_ai_act_art_6_001")

    def test_add_surrogate(self) -> None:
        reg = CitationRegistry()
        reg.add({"chunk_id": "missing_001", "surrogate": True})
        assert reg.is_valid("missing_001")
        assert reg.is_surrogate("missing_001")

    def test_add_url(self) -> None:
        reg = CitationRegistry()
        reg.add({"url": "https://edpb.europa.eu/news/news_en"})
        assert reg.is_valid("https://edpb.europa.eu/news/news_en")

    def test_add_tool_result_payload(self) -> None:
        reg = CitationRegistry()
        payload = {
            "citations": [{"chunk_id": "A"}, {"chunk_id": "B"}],
            "hits": [{"url": "https://example.com"}],
        }
        reg.add_tool_result(payload)
        assert reg.is_valid("A")
        assert reg.is_valid("B")
        assert reg.is_valid("https://example.com")


class TestExtractCitationMarkers:
    def test_extract_markers(self) -> None:
        text = "High-risk systems must meet requirements [eu_ai_act_annex_3] and [art:gdpr-6]."
        markers = extract_citation_markers(text)
        assert markers == ["eu_ai_act_annex_3", "art:gdpr-6"]

    def test_ignored_markers(self) -> None:
        text = "This is a model-only section [model-only] and [citation needed]."
        assert extract_citation_markers(text) == []


class TestCitationValidator:
    def test_valid_citations_pass(self) -> None:
        validator = CitationValidator()
        validator.register_citations(
            [
                {"chunk_id": "eu_ai_act_art_6_001"},
                {"chunk_id": "eu_ai_act_art_6_002"},
            ]
        )
        text = "Art. 6 covers high-risk systems [eu_ai_act_art_6_001][eu_ai_act_art_6_002]."
        result = validator.validate(text)
        assert result.ok
        assert result.invalid_ids == []
        assert result.valid_ids == ["eu_ai_act_art_6_001", "eu_ai_act_art_6_002"]

    def test_invalid_citation_is_flagged_and_stripped(self) -> None:
        validator = CitationValidator()
        validator.register_citations([{"chunk_id": "eu_ai_act_art_6_001"}])
        text = "High-risk systems are defined [eu_ai_act_art_6_001] and also [eu_ai_act_art_6_999]."
        result = validator.validate(text)
        assert not result.ok
        assert result.invalid_ids == ["eu_ai_act_art_6_999"]
        assert "[eu_ai_act_art_6_999]" not in result.cleaned_text
        assert "eu_ai_act_art_6_001" in result.cleaned_text
        assert result.stripped is True

    def test_surrogate_id_tracked(self) -> None:
        validator = CitationValidator()
        validator.register_citations([{"chunk_id": "surrogate_1", "surrogate": True}])
        result = validator.validate("Text [surrogate_1].")
        assert result.ok
        assert result.surrogate_ids == ["surrogate_1"]

    def test_url_citation(self) -> None:
        validator = CitationValidator()
        validator.register_citations([{"url": "https://ico.org.uk/guide"}])
        text = "ICO guidance says X [https://ico.org.uk/guide]."
        result = validator.validate(text)
        assert result.ok

    def test_on_invalid_mark_mode_keeps_text(self) -> None:
        validator = CitationValidator()
        text = "Claim [missing_id]."
        result = validator.validate(text, on_invalid="mark")
        assert not result.ok
        assert result.cleaned_text == text
        assert result.stripped is False
