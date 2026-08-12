"""CLI: ``python -m crp_comply.agent.rag {build|query|stats}``.

Examples:
    python -m crp_comply.agent.rag build
    python -m crp_comply.agent.rag build --only nist_ai_rmf_core --verbose
    python -m crp_comply.agent.rag stats
    python -m crp_comply.agent.rag query "human oversight of high-risk AI" -k 5
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from .embedder import DEFAULT_MODEL, Embedder
from .index import CorpusIndex, build_from_scraped


def _cmd_build(args: argparse.Namespace) -> int:
    embedder = Embedder(model_name=args.model)
    summary = build_from_scraped(
        embedder=embedder,
        source_ids=args.only or None,
        verbose=args.verbose,
    )
    print(json.dumps(summary, indent=2))
    return 0


def _cmd_stats(_args: argparse.Namespace) -> int:
    with CorpusIndex() as index:
        stats = index.stats()
    print(json.dumps(stats, indent=2))
    return 0


def _cmd_query(args: argparse.Namespace) -> int:
    embedder = Embedder(model_name=args.model)
    q_vec = embedder.encode([args.text])[0]
    with CorpusIndex() as index:
        hits = index.query(
            q_vec,
            top_k=args.top_k,
            source_filter=args.source or None,
        )
    for i, hit in enumerate(hits, 1):
        snippet = hit.text.strip().replace("\n", " ")
        if len(snippet) > 220:
            snippet = snippet[:217] + "..."
        print(f"[{i}] {hit.score:+.4f}  {hit.source_id}  {hit.chunk_id}")
        if hit.title:
            print(f"     title: {hit.title}")
        print(f"     {snippet}")
    if not hits:
        print("(no results — did you run `... rag build` first?)", file=sys.stderr)
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m crp_comply.agent.rag",
        description="CRP-Comply regulation corpus RAG index.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=f"sentence-transformers model name (default: {DEFAULT_MODEL} "
        "or $CRP_COMPLY_EMBED_MODEL)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="embed scraped corpus JSON into the index")
    p_build.add_argument(
        "--only",
        nargs="*",
        help="restrict to these source_ids (default: all in corpus/_scraped)",
    )
    p_build.add_argument("-v", "--verbose", action="store_true")
    p_build.set_defaults(func=_cmd_build)

    p_stats = sub.add_parser("stats", help="print index statistics")
    p_stats.set_defaults(func=_cmd_stats)

    p_query = sub.add_parser("query", help="ad-hoc similarity query")
    p_query.add_argument("text", help="the question or phrase to search")
    p_query.add_argument("-k", "--top-k", type=int, default=8)
    p_query.add_argument(
        "--source",
        nargs="*",
        help="restrict to these source_ids",
    )
    p_query.set_defaults(func=_cmd_query)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
