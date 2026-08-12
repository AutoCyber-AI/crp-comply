"""Copyright-safe redaction for licensed corpus documents.

Regulations like the EU AI Act are published under free-reuse licenses and can
be stored + quoted verbatim. ISO/IEC standards are **copyrighted by ISO** —
we hold a single licensed copy locally for *internal* recipe authoring and
embedding-quality, but we MUST NOT reproduce that prose in API responses or
LLM context.

Two-tier policy
---------------

* **At rest.** Documents whose ``license`` field marks them restricted are
  *tagged* (``tags['copyright'] = 'restricted'``) but their full text is
  retained in the local RAG sqlite — so semantic retrieval works on real
  prose and our own engineering team can author recipes against the
  authoritative source. ``tag_document_restricted()`` is the entry point.

* **At output.** Every code path that surfaces chunk text to the LLM /
  client checks the tag and substitutes a non-copyrighted **surrogate**
  built from clause id + title + section path + word count. No prose
  from the original document survives the boundary. Tools call
  :func:`surrogate_for_hit` and :func:`surrogate_chunk_for_response`.

Legacy ``redact_document()`` still exists and still mutates the document
in place — it is kept for callers that explicitly want stripped-at-rest
behaviour (e.g. exporting a corpus subset to a third party). The default
ingest path no longer calls it.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from .corpus import CorpusChunk, CorpusDocument


# Licenses we treat as "copyright-restricted: redact body":
RESTRICTED_LICENSES: frozenset[str] = frozenset(
    {
        "ISO-copyright",
        "ISO/IEC-copyright",
        "IEC-copyright",
        "ITU-copyright",
        "ANSI-copyright",
        "third-party-commentary",  # vendor explainers may also be restricted
    }
)


def _surrogate_text(chunk: CorpusChunk, source_id: str) -> str:
    """Build the non-copyrighted stand-in text used for embedding and storage."""
    title = (chunk.title or "").strip()
    article = (chunk.article_id or "").strip()
    path = " / ".join(chunk.section_path) if chunk.section_path else ""
    words = len(chunk.text.split()) if chunk.text else 0

    parts: list[str] = []
    # The clause/article identifier always comes first so embeddings cluster
    # by structural position across standards.
    header = source_id.upper().replace("_", " ")
    if article:
        parts.append(f"{header} {article}".strip())
    else:
        parts.append(header)
    if title:
        parts.append(title)
    if path and path not in title:
        parts.append(f"Section path: {path}")
    parts.append(
        f"[body redacted under {source_id} copyright — "
        f"~{words} words in source; see official publication]"
    )
    return ". ".join(p for p in parts if p)


def redact_chunk(chunk: CorpusChunk, *, source_id: str) -> CorpusChunk:
    """Return a copy of ``chunk`` whose ``text`` is a copyright-safe surrogate."""
    tags = dict(chunk.tags or {})
    tags["copyright"] = "restricted"
    tags["verbatim_stored"] = "false"
    tags["word_count"] = str(len(chunk.text.split()) if chunk.text else 0)
    return replace(
        chunk,
        text=_surrogate_text(chunk, source_id=source_id),
        tags=tags,
    )


def redact_document(doc: CorpusDocument) -> CorpusDocument:
    """Mutating-return: strip body text from every chunk of a restricted doc.

    No-op when ``doc.license`` is not in :data:`RESTRICTED_LICENSES`.
    """
    if doc.license not in RESTRICTED_LICENSES:
        return doc
    doc.chunks = [redact_chunk(c, source_id=doc.source_id) for c in doc.chunks]
    # Refresh the content hash so it reflects the surrogate content, not the
    # discarded original — the hash is a fingerprint of what we actually store.
    doc.finalise()
    # Stamp a copyright marker in notes so every downstream consumer can see it.
    marker = "[copyright-restricted: only clause IDs + titles stored; full text at publisher]"
    doc.notes = f"{doc.notes}. {marker}" if doc.notes else marker
    return doc


def is_restricted(license_str: str) -> bool:
    return license_str in RESTRICTED_LICENSES


def redact_many(docs: Iterable[CorpusDocument]) -> list[CorpusDocument]:
    return [redact_document(d) for d in docs]


# ---------------------------------------------------------------------------
# Output-boundary surrogate (preferred for new code paths)
# ---------------------------------------------------------------------------


def tag_document_restricted(doc: CorpusDocument) -> CorpusDocument:
    """Mark every chunk of a restricted doc as copyright-restricted **without**
    altering body text.

    No-op when ``doc.license`` is not in :data:`RESTRICTED_LICENSES`. This is
    the default ingest transform — it preserves full prose for embedding +
    internal use while ensuring downstream tool wrappers know to surrogate at
    output time. Pair with :func:`surrogate_for_hit` /
    :func:`surrogate_chunk_for_response` at every boundary that returns
    text to the LLM or HTTP client.
    """
    if doc.license not in RESTRICTED_LICENSES:
        return doc
    new_chunks: list[CorpusChunk] = []
    for c in doc.chunks:
        tags = dict(c.tags or {})
        tags["copyright"] = "restricted"
        tags["verbatim_stored"] = "true"  # we DO hold the prose at rest
        tags["word_count"] = str(len(c.text.split()) if c.text else 0)
        new_chunks.append(replace(c, tags=tags))
    doc.chunks = new_chunks
    doc.finalise()
    marker = "[copyright-restricted: full text held internally; surrogate served at API boundary]"
    doc.notes = f"{doc.notes}. {marker}" if doc.notes else marker
    return doc


def surrogate_for_hit(hit: dict) -> str:
    """Build a non-copyrighted surrogate string from a RAG-hit dict.

    Used by tool wrappers (``query_regulation``, ``query_regulation_packed``)
    that pull rows out of the RAG sqlite and need to swap the body before
    handing it to the LLM. The hit dict is the loose shape returned by
    :class:`RagService.query` — keys: ``source_id``, ``title``, ``article_id``,
    ``section_path``, ``text``, ``tags``.
    """
    title = (hit.get("title") or "").strip()
    article = (hit.get("article_id") or "").strip()
    section_path = hit.get("section_path") or []
    if isinstance(section_path, str):
        path = section_path
    else:
        path = " / ".join(section_path)
    body = hit.get("text") or ""
    words = int((hit.get("tags") or {}).get("word_count") or 0) or len(body.split())
    source_id = (hit.get("source_id") or "").strip()
    header = source_id.upper().replace("_", " ") if source_id else ""

    parts: list[str] = []
    if header and article:
        parts.append(f"{header} {article}".strip())
    elif header:
        parts.append(header)
    if title:
        parts.append(title)
    if path and path not in title:
        parts.append(f"Section path: {path}")
    parts.append(
        f"[body redacted under {source_id or 'publisher'} copyright — "
        f"~{words} words in source; see official publication]"
    )
    return ". ".join(p for p in parts if p)


def surrogate_chunk_for_response(hit: dict) -> dict:
    """Return a copy of ``hit`` with ``text`` replaced by the surrogate when
    ``tags.copyright == 'restricted'``. Otherwise return ``hit`` unchanged.
    """
    tags = hit.get("tags") or {}
    if tags.get("copyright") != "restricted":
        return hit
    out = dict(hit)
    out["text"] = surrogate_for_hit(hit)
    return out


__all__ = [
    "RESTRICTED_LICENSES",
    "is_restricted",
    "redact_chunk",
    "redact_document",
    "redact_many",
    "tag_document_restricted",
    "surrogate_for_hit",
    "surrogate_chunk_for_response",
]
