# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for the Live Regulation Intelligence diff engine."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


from crp_comply.agent.corpus import CorpusChunk, CorpusDocument, write_manifest
from crp_comply.agent.live_regulation import (
    diff_manifests,
    render_markdown,
)


def _doc(
    source_id: str,
    *,
    version: str,
    chunks: list[tuple[str, str, str]],
) -> CorpusDocument:
    """Build a CorpusDocument with explicit content_hash so diffs are stable."""
    import hashlib

    corpus_chunks = [
        CorpusChunk(id=cid, text=text, article_id=art, title=art) for (cid, art, text) in chunks
    ]
    body = "\n".join(c.text for c in corpus_chunks)
    doc = CorpusDocument(
        source_id=source_id,
        source_url=f"https://example.test/{source_id}",
        jurisdiction="EU",
        version=version,
        license="EU-free-reuse",
        retrieved_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        content_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        chunks=corpus_chunks,
    )
    return doc


def _write(tmp_path: Path, subdir: str, docs: list[CorpusDocument]) -> Path:
    d = tmp_path / subdir
    d.mkdir(parents=True, exist_ok=True)
    for doc in docs:
        doc.write_json(d / f"{doc.source_id}.json")
    write_manifest(docs, d / "manifest.json")
    return d / "manifest.json"


def test_unchanged_sources(tmp_path: Path) -> None:
    doc = _doc(
        "eu_ai_act", version="v1", chunks=[("c1", "Art.1", "Alpha"), ("c2", "Art.2", "Beta")]
    )
    base = _write(tmp_path, "base", [doc])
    cand = _write(tmp_path, "cand", [doc])
    delta = diff_manifests(base, cand)
    assert delta.any_changes is False
    assert all(s.kind == "unchanged" for s in delta.sources)


def test_version_bump_with_chunk_edits(tmp_path: Path) -> None:
    base_doc = _doc(
        "eu_ai_act",
        version="2024-08-01",
        chunks=[("c1", "Art.1", "Alpha"), ("c2", "Art.2", "Beta")],
    )
    cand_doc = _doc(
        "eu_ai_act",
        version="2024-12-01",
        chunks=[
            ("c1", "Art.1", "Alpha v2 — amended"),  # modified
            ("c3", "Art.3", "Gamma"),  # added
        ],
    )
    base = _write(tmp_path, "base", [base_doc])
    cand = _write(tmp_path, "cand", [cand_doc])

    delta = diff_manifests(base, cand)
    assert delta.any_changes is True
    assert len(delta.changed_sources) == 1
    s = delta.changed_sources[0]
    assert s.source_id == "eu_ai_act"
    assert s.kind == "version_bump"
    assert s.added_chunks == ["c3"]
    assert s.removed_chunks == ["c2"]
    assert s.modified_chunks == ["c1"]
    assert any(sd["chunk_id"] == "c1" for sd in s.sample_diffs)


def test_added_and_removed_sources(tmp_path: Path) -> None:
    keep = _doc("gdpr", version="v1", chunks=[("g1", "Art.1", "X")])
    gone = _doc("nis2", version="v1", chunks=[("n1", "Art.1", "Y")])
    new_ = _doc("nist", version="v1", chunks=[("m1", "Core.1", "Z")])

    base = _write(tmp_path, "base", [keep, gone])
    cand = _write(tmp_path, "cand", [keep, new_])

    delta = diff_manifests(base, cand)
    kinds = {s.source_id: s.kind for s in delta.sources}
    assert kinds == {"gdpr": "unchanged", "nis2": "removed", "nist": "added"}


def test_markdown_report_contains_expected_sections(tmp_path: Path) -> None:
    base_doc = _doc("eu_ai_act", version="v1", chunks=[("c1", "Art.1", "Alpha")])
    cand_doc = _doc("eu_ai_act", version="v2", chunks=[("c1", "Art.1", "Alpha edited")])
    base = _write(tmp_path, "base", [base_doc])
    cand = _write(tmp_path, "cand", [cand_doc])

    delta = diff_manifests(base, cand)
    md = render_markdown(delta)

    assert "Live Regulation Intelligence" in md
    assert "eu_ai_act" in md
    assert "version_bump" in md
    assert "Before:" in md and "After:" in md


def test_markdown_no_changes(tmp_path: Path) -> None:
    doc = _doc("gdpr", version="v1", chunks=[("g1", "Art.1", "X")])
    base = _write(tmp_path, "base", [doc])
    cand = _write(tmp_path, "cand", [doc])
    md = render_markdown(diff_manifests(base, cand))
    assert "No regulatory changes detected" in md


def test_missing_baseline_manifest_treats_all_as_added(tmp_path: Path) -> None:
    cand_doc = _doc("nist", version="v1", chunks=[("n1", "Core.1", "Z")])
    cand = _write(tmp_path, "cand", [cand_doc])
    baseline_missing = tmp_path / "baseline" / "manifest.json"
    baseline_missing.parent.mkdir(parents=True, exist_ok=True)
    baseline_missing.write_text('{"sources": []}', encoding="utf-8")

    delta = diff_manifests(baseline_missing, cand)
    assert [s.kind for s in delta.sources] == ["added"]
    assert delta.sources[0].added_chunks == ["n1"]
