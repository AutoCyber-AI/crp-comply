# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Citation validation and evidence grounding (Round 8).

The validator builds a registry of citation identifiers that were actually
returned by tools in the current session, then checks the final answer for
``[...]`` markers that reference IDs outside that registry. Invalid markers
can be stripped or surfaced as ``loop.citation.invalid`` events so the UI can
warn the user.

Supported citation keys (in priority order):

* ``chunk_id`` — primary corpus chunk identifier.
* ``fact_id`` / ``id`` — CKF fact identifier.
* ``citation_id`` / ``source_id`` — web-search citation identifiers.
* ``url`` — web source (normalised).

Surrogate chunks (retrieval misses filled by the LLM) must be explicitly
marked with ``surrogate=True`` in the citation dict. The validator tracks
which surrogate IDs are valid so answers can distinguish them from real
corpus hits.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Matches bracketed markers like [chunk_abc123], [art:gdpr-6], [source_1].
# Intentionally permissive inside the brackets so we catch anything the LLM
# might emit; validation then decides whether the token is in the registry.
_CITATION_MARKER_RE = re.compile(r"\[([A-Za-z][A-Za-z0-9_:.\-]{1,})\]")

# A small set of bracket tokens that are NOT citation claims and should be
# ignored during validation (e.g. markdown link text, UI badges).
_IGNORED_MARKERS = {
    "model-only",
    "model only",
    "removed",
    "citation needed",
    "source needed",
}


def _normalise_url(value: str) -> str:
    """Strip trailing slash and fragment for looser URL matching."""
    return value.split("#")[0].rstrip("/")


def _extract_id(citation: dict[str, Any]) -> tuple[str, bool]:
    """Return ``(id, is_surrogate)`` for a citation dict.

    The identifier is drawn from the first present key in the priority order
    above. ``is_surrogate`` is True if the dict explicitly declares it.
    """
    surrogate = bool(citation.get("surrogate") or citation.get("is_surrogate"))
    for key in ("chunk_id", "fact_id", "id", "citation_id", "source_id"):
        value = citation.get(key)
        if value:
            return str(value), surrogate
    url = citation.get("url")
    if url:
        return _normalise_url(str(url)), surrogate
    return "", surrogate


@dataclass
class CitationRegistry:
    """Set of citation IDs that are valid in the current turn/session."""

    valid_ids: set[str] = field(default_factory=set)
    surrogate_ids: set[str] = field(default_factory=set)

    def add(self, citation: dict[str, Any]) -> None:
        """Register one citation dict."""
        cid, surrogate = _extract_id(citation)
        if not cid:
            return
        if surrogate:
            self.surrogate_ids.add(cid)
        self.valid_ids.add(cid)

    def add_many(self, citations: list[dict[str, Any]]) -> None:
        for c in citations:
            self.add(c)

    def add_tool_result(self, result: Any) -> None:
        """Best-effort registration from a tool result object/dict."""
        if result is None:
            return
        if isinstance(result, dict):
            raw = result.get("citations")
            if isinstance(raw, list):
                self.add_many(raw)
            for key in ("chunks", "hits", "facts"):
                entries = result.get(key) or []
                if isinstance(entries, list):
                    for entry in entries:
                        if isinstance(entry, dict):
                            self.add(entry)
            return
        # Object-style result
        raw = getattr(result, "citations", None)
        if isinstance(raw, list):
            self.add_many(raw)

    def is_valid(self, marker: str) -> bool:
        return marker in self.valid_ids

    def is_surrogate(self, marker: str) -> bool:
        return marker in self.surrogate_ids


@dataclass
class CitationValidationResult:
    """Outcome of validating a piece of text."""

    original_text: str
    cleaned_text: str
    invalid_ids: list[str] = field(default_factory=list)
    valid_ids: list[str] = field(default_factory=list)
    surrogate_ids: list[str] = field(default_factory=list)
    stripped: bool = False

    @property
    def ok(self) -> bool:
        return not self.invalid_ids


def extract_citation_markers(text: str) -> list[str]:
    """Return all bracketed citation tokens found in *text*."""
    if not text:
        return []
    markers = []
    for token in _CITATION_MARKER_RE.findall(text):
        lower = token.lower().strip()
        if lower in _IGNORED_MARKERS:
            continue
        markers.append(token)
    return markers


class CitationValidator:
    """Validate final-answer citations against a registry of tool outputs."""

    def __init__(self, registry: CitationRegistry | None = None) -> None:
        self.registry = registry or CitationRegistry()

    def register_citations(self, citations: list[dict[str, Any]]) -> None:
        self.registry.add_many(citations)

    def register_tool_result(self, result: Any) -> None:
        self.registry.add_tool_result(result)

    def validate(
        self,
        text: str,
        *,
        on_invalid: str = "strip",
        append_note: bool = True,
    ) -> CitationValidationResult:
        """Check every citation marker in *text* against the registry.

        Parameters
        ----------
        on_invalid:
            ``"strip"`` removes invalid markers from ``cleaned_text``.
            ``"mark"`` keeps them but the caller can emit a warning.
        append_note:
            If stripping, append a short note listing removed citations.
        """
        if not text:
            return CitationValidationResult(original_text=text, cleaned_text=text)

        markers = extract_citation_markers(text)
        invalid: list[str] = []
        valid: list[str] = []
        surrogate: list[str] = []

        for marker in markers:
            if self.registry.is_valid(marker):
                valid.append(marker)
                if self.registry.is_surrogate(marker):
                    surrogate.append(marker)
            else:
                invalid.append(marker)

        cleaned = text
        stripped = False
        if invalid and on_invalid == "strip":
            cleaned = self._strip_markers(text, invalid)
            stripped = True
            if append_note and invalid:
                note = (
                    "\n\n*(Citation validation: removed invalid or "
                    f"unresolved markers: {', '.join(invalid)})*"
                )
                cleaned = cleaned.rstrip() + note

        return CitationValidationResult(
            original_text=text,
            cleaned_text=cleaned,
            invalid_ids=invalid,
            valid_ids=valid,
            surrogate_ids=surrogate,
            stripped=stripped,
        )

    @staticmethod
    def _strip_markers(text: str, invalid_ids: list[str]) -> str:
        """Remove invalid ``[id]`` markers from text, preserving surrounding whitespace."""
        out = text
        for marker in invalid_ids:
            # Escape regex-special chars in the marker (e.g. dots in URLs).
            pattern = re.escape(f"[{marker}]")
            out = re.sub(rf"\s*{pattern}\s*", " ", out)
        # Collapse multiple spaces and clean up around punctuation.
        out = re.sub(r" +", " ", out)
        out = re.sub(r" \.", ".", out)
        out = re.sub(r" ,", ",", out)
        return out.strip()


__all__ = [
    "CitationRegistry",
    "CitationValidator",
    "CitationValidationResult",
    "extract_citation_markers",
]
