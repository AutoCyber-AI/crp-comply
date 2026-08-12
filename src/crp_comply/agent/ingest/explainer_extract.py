# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Extract a headings-only crosswalk from a Markdown commentary book.

Runs against ``corpus/iso/42001/explainer/benraouane_2024.md`` and produces a
pointer-only JSON index at ``corpus/iso/42001/explainer/benraouane_2024.headings.json``
containing ONLY:

* ``section_path`` — e.g. ``"Part 2 > AIMS > Risk Assessment (Clause 6.1.2)"``
* ``level``       — heading level (1..6)
* ``line``        — line number in the source
* ``hash``        — short sha256 of the section title only

The book is third-party commentary by Sid Ahmed Benraouane (© 2024 Routledge,
Taylor & Francis, ISBN 978-1-032-73397-5). Because it is copyright-restricted,
we do NOT persist its body prose into any index we serve. The output of this
extractor is structural metadata sufficient for:

1. Letting the agent cite "Benraouane (2024) §4.2 — Context Analysis" as a
   *pointer*, without reproducing book prose.
2. Building the ISO 42001 ↔ explainer crosswalk in
   ``STRATEGIC_REASSESSMENT.md`` and in future tool outputs.

Run:

    python -m crp_comply.agent.ingest.explainer_extract

No arguments required.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

_DEFAULT_SOURCE = (
    Path(__file__).resolve().parents[4]
    / "corpus"
    / "iso"
    / "42001"
    / "explainer"
    / "benraouane_2024.md"
)
_DEFAULT_OUTPUT = _DEFAULT_SOURCE.with_suffix(".headings.json")

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


@dataclass(frozen=True)
class Heading:
    level: int
    title: str
    line: int
    section_path: str
    hash: str


def _short_hash(title: str) -> str:
    return hashlib.sha256(title.encode("utf-8")).hexdigest()[:12]


def extract(source: Path) -> list[Heading]:
    """Parse markdown headings into a hierarchical section path."""
    if not source.exists():
        raise FileNotFoundError(f"Source not found: {source}")

    stack: list[str] = []
    out: list[Heading] = []

    with source.open("r", encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, start=1):
            m = _HEADING_RE.match(raw.rstrip("\n"))
            if not m:
                continue
            level = len(m.group(1))
            title = m.group(2).strip()
            if not title:
                continue
            # Maintain a stack of ancestors by level
            while len(stack) >= level:
                stack.pop()
            stack.append(title)
            section_path = " > ".join(stack)
            out.append(
                Heading(
                    level=level,
                    title=title,
                    line=line_no,
                    section_path=section_path,
                    hash=_short_hash(title),
                )
            )
    return out


def write_index(headings: list[Heading], output: Path, source: Path) -> dict:
    manifest = {
        "source_file": source.name,
        "source_kind": "third-party-commentary",
        "copyright": (
            "© 2024 Sid Ahmed Benraouane. Published by Routledge / "
            "Taylor & Francis Group, LLC. ISBN 978-1-032-73397-5. "
            "This index contains structural headings only — no book prose. "
            "Do NOT reproduce body text; cite by section path only."
        ),
        "heading_count": len(headings),
        "headings": [asdict(h) for h in headings],
    }
    output.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    source = Path(argv[0]) if argv else _DEFAULT_SOURCE
    output = Path(argv[1]) if len(argv) > 1 else source.with_suffix(".headings.json")

    headings = extract(source)
    manifest = write_index(headings, output, source)
    print(
        f"extracted {manifest['heading_count']} headings → {output}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
