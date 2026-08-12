"""CLI: ``python -m crp_comply.agent.ingest [all|iso|eu_ai_act|...]``."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from ..corpus import CorpusDocument, scraped_output_dir, write_manifest


log = logging.getLogger("crp_comply.agent.ingest")


# Map CLI name -> callable that returns list[CorpusDocument]
def _registry():
    from ..scrapers import eurlex, intl, nist
    from . import iso_loader

    return {
        "eu_ai_act": lambda: [eurlex.scrape_eu_ai_act()],
        "gdpr": lambda: [eurlex.scrape_gdpr()],
        "nis2": lambda: [eurlex.scrape_nis2()],
        "nist": nist.scrape,
        "oecd_coe_uk_edpb": intl.scrape,
        "iso": iso_loader.load_all,
        "iso_enterprise": lambda: iso_loader.load_all(include_enterprise=True),
    }


DEFAULT_V1 = ["eu_ai_act", "gdpr", "nist", "oecd_coe_uk_edpb", "iso"]


def _write_docs(docs: list[CorpusDocument]) -> list[Path]:
    out_dir = scraped_output_dir()
    paths: list[Path] = []
    for doc in docs:
        p = out_dir / f"{doc.source_id}.json"
        doc.write_json(p)
        paths.append(p)
        log.info("wrote %s (%d chunks, %.1f KB)", p.name, len(doc.chunks), p.stat().st_size / 1024)
    # manifest across all docs produced this run
    write_manifest(docs, out_dir / "manifest.json")
    return paths


def _extract_facts_from_docs(docs: list[CorpusDocument], out_dir: Path) -> int:
    """Run :mod:`crp.extraction.pipeline` over every chunk of every doc.

    The extracted :class:`crp.extraction.types.Fact` objects are written as
    JSONL under ``{out_dir}/facts/{source_id}.jsonl`` so the RAG index
    build step (or any downstream process) can load them without
    re-running the expensive 6-stage extraction pipeline.

    This path is opt-in via ``--extract-facts`` because it loads
    GLiNER/NLI models (~1 GB of weights) and can take several minutes per
    document. For a weekly Live Regulation CI run, that cost is fine; for
    a dev loop it is not, so the default remains off.

    Returns the total number of facts written.
    """
    try:
        from crp.extraction import ExtractionPipeline  # type: ignore[import-not-found]
    except Exception as exc:
        log.error("extraction pipeline unavailable: %s", exc)
        return 0

    facts_dir = out_dir / "facts"
    facts_dir.mkdir(parents=True, exist_ok=True)
    pipeline = ExtractionPipeline()
    total = 0

    for doc in docs:
        out_path = facts_dir / f"{doc.source_id}.jsonl"
        doc_facts = 0
        with out_path.open("w", encoding="utf-8") as fh:
            for chunk in doc.chunks:
                try:
                    result = pipeline.extract(chunk.text)
                except Exception as exc:
                    log.debug("extraction failed for %s chunk: %s", doc.source_id, exc)
                    continue
                facts = getattr(result, "facts", None) or []
                for fact in facts:
                    import json

                    payload = {
                        "id": getattr(fact, "id", ""),
                        "text": getattr(fact, "text", ""),
                        "category": getattr(fact, "category", ""),
                        "confidence": float(getattr(fact, "confidence", 0.0)),
                        "source_id": doc.source_id,
                        "chunk_id": getattr(chunk, "id", ""),
                        "article_id": getattr(chunk, "article_id", ""),
                        "section_path": list(getattr(chunk, "section_path", []) or []),
                    }
                    fh.write(json.dumps(payload, ensure_ascii=False))
                    fh.write("\n")
                    doc_facts += 1
        log.info("extracted %d facts from %s -> %s", doc_facts, doc.source_id, out_path.name)
        total += doc_facts
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CRP-Comply regulation corpus ingest")
    parser.add_argument(
        "targets",
        nargs="*",
        help="Target names (default: v1 set). Use 'all' to include enterprise packs. "
        "Use 'list' to show available targets.",
    )
    parser.add_argument("-v", "--verbose", action="count", default=0)
    parser.add_argument(
        "--extract-facts",
        action="store_true",
        help=(
            "After writing corpus docs, run crp.extraction.pipeline over "
            "every chunk and emit structured Fact JSONL under "
            "data/_scraped/facts/. Enables the Live Regulation CI to track "
            "semantic deltas between regulation versions. Slow."
        ),
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG
        if args.verbose >= 2
        else (logging.INFO if args.verbose else logging.WARNING),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    reg = _registry()

    if not args.targets or args.targets == ["default"]:
        targets = DEFAULT_V1
    elif args.targets == ["all"]:
        targets = list(reg.keys())
    elif args.targets == ["list"]:
        print("Available ingest targets:")
        for name in reg:
            print(f"  {name}")
        return 0
    else:
        targets = args.targets

    all_docs: list[CorpusDocument] = []
    for name in targets:
        fn = reg.get(name)
        if fn is None:
            log.error("unknown target %r — try 'python -m crp_comply.agent.ingest list'", name)
            continue
        log.info("── target: %s", name)
        try:
            docs = fn()
        except Exception as exc:
            log.error("target %s failed: %s", name, exc, exc_info=args.verbose >= 2)
            continue
        all_docs.extend(docs)

    if not all_docs:
        log.error("no documents produced — nothing written.")
        return 2

    _write_docs(all_docs)
    print(f"ingested {len(all_docs)} document(s) → {scraped_output_dir()}")

    if args.extract_facts:
        out_dir = scraped_output_dir()
        n = _extract_facts_from_docs(all_docs, out_dir)
        print(f"extracted {n} fact(s) → {out_dir / 'facts'}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
