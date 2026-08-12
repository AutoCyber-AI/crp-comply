# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Live Regulation Intelligence — diff engine for the weekly CI.

Implements the semantic-diff step of ``LLM_INTELLIGENCE_DESIGN.md`` §15.

Given a **baseline** manifest (committed corpus) and a **candidate** manifest
(freshly scraped), compute:

* source-level deltas — added / removed / version-bumped / content_hash-changed
  sources
* chunk-level deltas for changed sources — added / removed / modified chunk
  ids with before/after text snippets
* a short markdown impact report suitable for a GitHub PR body
* a machine-readable JSON delta record

The CLI wrapper ``python -m crp_comply.agent.live_regulation diff`` is what
the weekly ``.github/workflows/live-regulation-ci.yml`` cron invokes after
re-running the scrapers.

This module is intentionally dependency-free beyond the stdlib + the
already-present ``CorpusDocument`` schema so the CI job stays fast (< 30 s
for a cold run on a small runner).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .corpus import CorpusChunk, CorpusDocument, scraped_output_dir


log = logging.getLogger("crp_comply.agent.live_regulation")


# ---------------------------------------------------------------------------
# Public result types
# ---------------------------------------------------------------------------


@dataclass
class SourceDelta:
    """Per-source summary of what changed between baseline and candidate."""

    source_id: str
    kind: str  # "added" | "removed" | "version_bump" | "content_changed" | "unchanged"
    baseline_version: str | None = None
    candidate_version: str | None = None
    baseline_hash: str | None = None
    candidate_hash: str | None = None
    added_chunks: list[str] = field(default_factory=list)
    removed_chunks: list[str] = field(default_factory=list)
    modified_chunks: list[str] = field(default_factory=list)
    sample_diffs: list[dict[str, str]] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return self.kind != "unchanged"

    @property
    def total_changed_chunks(self) -> int:
        return len(self.added_chunks) + len(self.removed_chunks) + len(self.modified_chunks)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CorpusDelta:
    """Top-level result returned by :func:`diff_manifests`."""

    generated_at: str
    baseline_manifest: str
    candidate_manifest: str
    sources: list[SourceDelta] = field(default_factory=list)

    @property
    def changed_sources(self) -> list[SourceDelta]:
        return [s for s in self.sources if s.has_changes]

    @property
    def any_changes(self) -> bool:
        return bool(self.changed_sources)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "baseline_manifest": self.baseline_manifest,
            "candidate_manifest": self.candidate_manifest,
            "sources": [s.to_dict() for s in self.sources],
        }


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _load_manifest(path: Path) -> dict[str, dict[str, Any]]:
    """Return ``{source_id: source_record}`` from a manifest.json."""
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {s["source_id"]: s for s in data.get("sources", [])}


def _load_doc(docs_dir: Path, source_id: str) -> CorpusDocument | None:
    """Load a single ``{docs_dir}/{source_id}.json`` as a ``CorpusDocument``."""
    p = docs_dir / f"{source_id}.json"
    if not p.is_file():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    chunks = [
        CorpusChunk(
            id=c.get("id", ""),
            text=c.get("text", ""),
            title=c.get("title", ""),
            article_id=c.get("article_id", ""),
            section_path=tuple(c.get("section_path") or []),
            tags=c.get("tags") or {},
            effective_date=c.get("effective_date"),
            superseded_by=c.get("superseded_by"),
        )
        for c in data.get("chunks", [])
    ]
    return CorpusDocument(
        source_id=data.get("source_id", source_id),
        source_url=data.get("source_url", ""),
        jurisdiction=data.get("jurisdiction", ""),
        version=data.get("version", ""),
        license=data.get("license", ""),
        retrieved_at=data.get("retrieved_at", ""),
        content_hash=data.get("content_hash", ""),
        chunks=chunks,
        notes=data.get("notes", ""),
    )


# ---------------------------------------------------------------------------
# Chunk-level diff
# ---------------------------------------------------------------------------


def _chunk_hash(chunk: CorpusChunk) -> str:
    """Hash used for modification detection — text + title + article id."""
    payload = "\n".join([chunk.article_id or "", chunk.title or "", chunk.text or ""])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _truncate(text: str, limit: int = 400) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _diff_chunks(
    baseline: CorpusDocument | None,
    candidate: CorpusDocument | None,
    *,
    max_samples: int = 5,
) -> tuple[list[str], list[str], list[str], list[dict[str, str]]]:
    """Return ``(added, removed, modified, samples)`` by chunk id."""
    base_map = {c.id: c for c in (baseline.chunks if baseline else [])}
    cand_map = {c.id: c for c in (candidate.chunks if candidate else [])}

    base_ids = set(base_map)
    cand_ids = set(cand_map)

    added = sorted(cand_ids - base_ids)
    removed = sorted(base_ids - cand_ids)

    modified: list[str] = []
    samples: list[dict[str, str]] = []
    for cid in sorted(base_ids & cand_ids):
        if _chunk_hash(base_map[cid]) != _chunk_hash(cand_map[cid]):
            modified.append(cid)
            if len(samples) < max_samples:
                samples.append(
                    {
                        "chunk_id": cid,
                        "article_id": cand_map[cid].article_id or base_map[cid].article_id,
                        "title": cand_map[cid].title or base_map[cid].title,
                        "before": _truncate(base_map[cid].text),
                        "after": _truncate(cand_map[cid].text),
                    }
                )

    # Also pull up to `max_samples` samples from added/removed to seed the PR.
    for cid in added[: max(0, max_samples - len(samples))]:
        samples.append(
            {
                "chunk_id": cid,
                "article_id": cand_map[cid].article_id,
                "title": cand_map[cid].title,
                "before": "",
                "after": _truncate(cand_map[cid].text),
            }
        )

    return added, removed, modified, samples


# ---------------------------------------------------------------------------
# Top-level diff
# ---------------------------------------------------------------------------


def diff_manifests(
    baseline_manifest: Path,
    candidate_manifest: Path,
    *,
    baseline_docs_dir: Path | None = None,
    candidate_docs_dir: Path | None = None,
) -> CorpusDelta:
    """Compute a :class:`CorpusDelta` between two manifests.

    ``baseline_docs_dir`` and ``candidate_docs_dir`` default to the directory
    containing each manifest — which matches how ``_write_docs`` writes out
    ``{scraped_output_dir()}/{source_id}.json`` alongside ``manifest.json``.
    """
    baseline_docs_dir = baseline_docs_dir or baseline_manifest.parent
    candidate_docs_dir = candidate_docs_dir or candidate_manifest.parent

    base = _load_manifest(baseline_manifest)
    cand = _load_manifest(candidate_manifest)

    all_ids = sorted(set(base) | set(cand))
    deltas: list[SourceDelta] = []

    for sid in all_ids:
        b = base.get(sid)
        c = cand.get(sid)

        if b is None and c is not None:
            cand_doc = _load_doc(candidate_docs_dir, sid)
            added_chunks = [ch.id for ch in (cand_doc.chunks if cand_doc else [])]
            deltas.append(
                SourceDelta(
                    source_id=sid,
                    kind="added",
                    candidate_version=c.get("version"),
                    candidate_hash=c.get("content_hash"),
                    added_chunks=added_chunks,
                )
            )
            continue

        if c is None and b is not None:
            base_doc = _load_doc(baseline_docs_dir, sid)
            removed_chunks = [ch.id for ch in (base_doc.chunks if base_doc else [])]
            deltas.append(
                SourceDelta(
                    source_id=sid,
                    kind="removed",
                    baseline_version=b.get("version"),
                    baseline_hash=b.get("content_hash"),
                    removed_chunks=removed_chunks,
                )
            )
            continue

        if not (b is not None and c is not None):
            raise RuntimeError("expected b and c to be set in diff calculation")
        version_bump = b.get("version") != c.get("version")
        content_changed = b.get("content_hash") != c.get("content_hash")

        if not version_bump and not content_changed:
            deltas.append(
                SourceDelta(
                    source_id=sid,
                    kind="unchanged",
                    baseline_version=b.get("version"),
                    candidate_version=c.get("version"),
                    baseline_hash=b.get("content_hash"),
                    candidate_hash=c.get("content_hash"),
                )
            )
            continue

        base_doc = _load_doc(baseline_docs_dir, sid)
        cand_doc = _load_doc(candidate_docs_dir, sid)
        added, removed, modified, samples = _diff_chunks(base_doc, cand_doc)
        kind = "version_bump" if version_bump else "content_changed"
        deltas.append(
            SourceDelta(
                source_id=sid,
                kind=kind,
                baseline_version=b.get("version"),
                candidate_version=c.get("version"),
                baseline_hash=b.get("content_hash"),
                candidate_hash=c.get("content_hash"),
                added_chunks=added,
                removed_chunks=removed,
                modified_chunks=modified,
                sample_diffs=samples,
            )
        )

    return CorpusDelta(
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        baseline_manifest=str(baseline_manifest),
        candidate_manifest=str(candidate_manifest),
        sources=deltas,
    )


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------


_KIND_EMOJI = {
    "added": "🆕",
    "removed": "🗑️",
    "version_bump": "🔁",
    "content_changed": "✏️",
    "unchanged": "✅",
}


def render_markdown(delta: CorpusDelta) -> str:
    """Format ``delta`` as a GitHub-friendly markdown PR body."""
    lines: list[str] = []
    lines.append("# Live Regulation Intelligence — weekly diff")
    lines.append("")
    lines.append(f"Generated: `{delta.generated_at}`")
    lines.append("")

    changed = delta.changed_sources
    if not changed:
        lines.append("✅ **No regulatory changes detected this week.**")
        lines.append("")
        lines.append("All ingested sources match the committed corpus byte-for-byte.")
        return "\n".join(lines)

    lines.append(f"**{len(changed)} source(s) changed:**")
    lines.append("")
    lines.append("| Source | Change | Baseline → Candidate | Chunks (+/-/~) |")
    lines.append("|---|---|---|---|")
    for s in changed:
        emoji = _KIND_EMOJI.get(s.kind, "❓")
        versions = f"`{s.baseline_version or '—'}` → `{s.candidate_version or '—'}`"
        counts = f"+{len(s.added_chunks)} / −{len(s.removed_chunks)} / ~{len(s.modified_chunks)}"
        lines.append(f"| `{s.source_id}` | {emoji} {s.kind} | {versions} | {counts} |")
    lines.append("")

    for s in changed:
        lines.append(f"## {_KIND_EMOJI.get(s.kind, '')} `{s.source_id}` — {s.kind}")
        lines.append("")
        if s.baseline_hash or s.candidate_hash:
            lines.append(
                f"`content_hash`: "
                f"`{(s.baseline_hash or '—')[:12]}` → "
                f"`{(s.candidate_hash or '—')[:12]}`"
            )
            lines.append("")
        if s.sample_diffs:
            lines.append("<details><summary>Sample chunk diffs</summary>")
            lines.append("")
            for sample in s.sample_diffs:
                header = sample.get("article_id") or sample.get("chunk_id") or "(chunk)"
                title = sample.get("title") or ""
                lines.append(f"### `{header}` {title}".rstrip())
                lines.append("")
                if sample.get("before"):
                    lines.append("**Before:**")
                    lines.append("")
                    lines.append("> " + sample["before"].replace("\n", "\n> "))
                    lines.append("")
                if sample.get("after"):
                    lines.append("**After:**")
                    lines.append("")
                    lines.append("> " + sample["after"].replace("\n", "\n> "))
                    lines.append("")
            lines.append("</details>")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("### What to do")
    lines.append("")
    lines.append("1. Review the sample diffs above; spot-check the source URLs.")
    lines.append(
        "2. If the changes are legitimate regulatory updates, **merge this PR**. "
        "The corpus will be re-indexed and affected customers notified per "
        "`CONTINUOUS_COMPLIANCE.md` §5."
    )
    lines.append(
        "3. If something looks wrong (e.g. scraper broke, partial fetch), "
        "**close this PR** — the baseline stays in force until next week's run."
    )
    lines.append("")
    lines.append(
        "_This PR was opened automatically by `.github/workflows/live-regulation-ci.yml`._"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _default_baseline() -> Path:
    return scraped_output_dir() / "manifest.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m crp_comply.agent.live_regulation",
        description="Live Regulation Intelligence — manifest diff CLI",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_diff = sub.add_parser("diff", help="Diff two manifests")
    p_diff.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="Baseline manifest.json (defaults to corpus/_scraped/manifest.json)",
    )
    p_diff.add_argument(
        "--candidate",
        type=Path,
        required=True,
        help="Candidate manifest.json from a fresh scrape",
    )
    p_diff.add_argument(
        "--baseline-docs-dir",
        type=Path,
        default=None,
    )
    p_diff.add_argument(
        "--candidate-docs-dir",
        type=Path,
        default=None,
    )
    p_diff.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Write machine-readable delta JSON to this path",
    )
    p_diff.add_argument(
        "--md-out",
        type=Path,
        default=None,
        help="Write markdown PR body to this path",
    )
    p_diff.add_argument(
        "--fail-on-change",
        action="store_true",
        help="Exit 1 if any source changed (default: 0 regardless)",
    )
    p_diff.add_argument("-v", "--verbose", action="count", default=0)

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG
        if args.verbose >= 2
        else (logging.INFO if args.verbose else logging.WARNING),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    baseline = args.baseline or _default_baseline()
    delta = diff_manifests(
        baseline_manifest=baseline,
        candidate_manifest=args.candidate,
        baseline_docs_dir=args.baseline_docs_dir,
        candidate_docs_dir=args.candidate_docs_dir,
    )

    md = render_markdown(delta)
    if args.md_out:
        args.md_out.parent.mkdir(parents=True, exist_ok=True)
        args.md_out.write_text(md, encoding="utf-8")
    else:
        print(md)

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(delta.to_dict(), indent=2), encoding="utf-8")

    # Always print a one-line summary on stderr so CI logs are greppable.
    summary = (
        f"live-regulation-diff: {len(delta.changed_sources)} changed / "
        f"{len(delta.sources)} total sources"
    )
    print(summary, file=sys.stderr)

    if args.fail_on_change and delta.any_changes:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
