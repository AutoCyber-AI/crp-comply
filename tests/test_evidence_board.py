# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for Round 10 EvidenceBoard working memory."""

from __future__ import annotations

from crp_comply.agent.evidence_board import EvidenceBoard


def test_add_fact() -> None:
    board = EvidenceBoard()
    board.add("Controllers must implement security measures.", source_id="gdpr_32")
    assert len(board.facts) == 1
    assert board.facts[0].source_id == "gdpr_32"


def test_deduplicates_facts() -> None:
    board = EvidenceBoard()
    board.add("Controllers must implement security measures.")
    board.add("controllers must implement security measures.")
    assert len(board.facts) == 1


def test_add_from_citations_extracts_sentences() -> None:
    board = EvidenceBoard()
    board.add_from_citations(
        step_id="s1",
        phase="RESEARCH",
        observation="Art. 6 requires lawful basis. Art. 32 requires security.",
        citations=[{"chunk_id": "gdpr_art_6"}],
    )
    assert len(board.facts) == 2
    assert all(f.citation == "[gdpr_art_6]" for f in board.facts)


def test_render_includes_citations() -> None:
    board = EvidenceBoard()
    board.add("Lawful basis is required.", citation="[gdpr_art_6]")
    rendered = board.render()
    assert "Lawful basis is required." in rendered
    assert "[gdpr_art_6]" in rendered


def test_by_phase_filter() -> None:
    board = EvidenceBoard()
    board.add("Research fact", phase="RESEARCH")
    board.add("Synthesis fact", phase="SYNTHESIS")
    assert len(board.by_phase("RESEARCH")) == 1
    assert board.by_phase("RESEARCH")[0].text == "Research fact"


def test_round_trip_dict() -> None:
    board = EvidenceBoard()
    board.add("Fact one", source_id="a")
    board.add("Fact two", source_id="b")
    restored = EvidenceBoard.from_dict(board.to_dict())
    assert len(restored.facts) == 2
