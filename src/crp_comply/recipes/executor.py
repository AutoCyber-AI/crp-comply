# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Recipe executor.

The executor builds a structured prompt from the recipe, drives the
agent section-by-section (or in a single pass for short recipes), and
assembles the markdown + json outputs. It is deliberately *transport*-
agnostic — callers inject either a real :class:`ComplianceAgent` or any
object exposing ``run(task, **kwargs) -> AgentResult``.

Section-citation wiring
-----------------------

Every section in the output carries a ``section_citations`` list built
from:

1. the recipe's declared ``citations`` for that section,
2. any ``Article N`` / ``Annex N`` / clause references the LLM surfaces
   in the drafted text (extracted deterministically, no LLM-as-judge).

This gives callers a stable, auditable contract: ``output.json`` always
has ``{section_id: {title, text, citations}}`` for every section, even
when the LLM forgets to cite explicitly.

Per-paragraph provenance
------------------------

Section drafting now asks the LLM to emit a JSON envelope of the form
``{"paragraphs": [{"text": "...", "provenance": [{"kind": "...",
"ref": "...", "label": "..."}]}]}``. Recognised provenance kinds are:

* ``regulation`` — a clause returned by ``query_regulation``; ``ref``
  is the ``chunk_id``.
* ``artefact`` — an upload returned by ``fetch_artefact``; ``ref`` is
  the artefact id.
* ``runtime`` — a stat or sample returned by ``query_proxy_metrics``;
  ``ref`` describes the metric (e.g. ``stats.total_requests``).
* ``interview`` — a clarification answer or user-supplied input.
* ``profile`` — a fact from the captured ``OrgProfile``.
* ``placeholder`` — the LLM could not source the paragraph; the
  executor replaces the body with a ``[PLACEHOLDER:<reason>]`` marker
  so the deliverable cannot silently ship fiction.

If the LLM returns plain markdown (no envelope), the executor falls
back to a single ``regulation``-tagged paragraph and records a
warning so callers know provenance was best-effort.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from .loader import Recipe, RecipeSection

log = logging.getLogger("crp_comply.recipes.executor")


# Regexes for deterministic citation extraction from the drafted text.
_CITATION_PATTERNS = [
    # Article 6, Article 6(2), Article 27(1)(a), Article 50
    re.compile(r"\bArticle\s+\d+(?:\([0-9a-z]+\))*", re.IGNORECASE),
    re.compile(r"\bAnnex\s+[IVX]+(?:\s+row\s+\d+)?\b", re.IGNORECASE),
    re.compile(r"\bClause\s+\d+(?:\.\d+)*\b", re.IGNORECASE),
    re.compile(r"\bSection\s+\d+(?:\.\d+)*\b", re.IGNORECASE),
]


class _AgentLike(Protocol):
    def run(self, task: str, **kwargs: Any) -> Any: ...


@dataclass
class RecipeOutput:
    """Structured output of a recipe run."""

    recipe_id: str
    title: str
    regulation: str
    markdown: str
    json_payload: dict[str, Any] = field(default_factory=dict)
    section_citations: dict[str, list[str]] = field(default_factory=dict)
    inputs: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    warnings: list[str] = field(default_factory=list)
    #: ``DerivationManifest.to_dict()`` — binds this output to the exact
    #: evidence that produced it so callers can detect staleness later.
    derivation: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "recipe_id": self.recipe_id,
            "title": self.title,
            "regulation": self.regulation,
            "markdown": self.markdown,
            "json": dict(self.json_payload),
            "section_citations": {k: list(v) for k, v in self.section_citations.items()},
            "inputs": dict(self.inputs),
            "duration_ms": int(self.duration_ms),
            "warnings": list(self.warnings),
            "derivation": dict(self.derivation),
        }


def _extract_citations(text: str) -> list[str]:
    seen: list[str] = []
    seen_set: set[str] = set()
    for pat in _CITATION_PATTERNS:
        for match in pat.findall(text or ""):
            norm = " ".join(match.split())
            key = norm.lower()
            if key not in seen_set:
                seen_set.add(key)
                seen.append(norm)
    return seen


# Recognised provenance kinds (kept in sync with the prompt + frontend).
_PROV_KINDS = {
    "regulation",
    "artefact",
    "runtime",
    "interview",
    "profile",
    "placeholder",
    "unsourced",
}


@dataclass
class ParagraphProvenance:
    """One paragraph plus the evidence it cites.

    ``provenance`` is a list of ``{"kind": str, "ref": str, "label":
    str}`` dicts. ``kind`` ∈ :data:`_PROV_KINDS`. ``ref`` is the
    backing identifier (chunk_id for regulation, artefact_id for
    artefact, ``stats.<key>`` for runtime, etc.). ``label`` is an
    optional human-readable annotation.
    """

    text: str
    provenance: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "provenance": [dict(p) for p in self.provenance],
        }


def _coerce_paragraphs(payload: Any) -> list[ParagraphProvenance] | None:
    """Try to read ``{paragraphs: [...]}`` out of an LLM response.

    The LLM may return:
      * a ``dict`` with key ``paragraphs``
      * a JSON string starting with ``{`` or ``[``
      * a string with a JSON object embedded between the first ``{``
        and last ``}`` (common when the LLM prefixes prose).

    Returns ``None`` when no recognisable envelope is present so the
    caller can fall back to flat-markdown handling.
    """

    obj: Any = payload
    if isinstance(payload, str):
        s = payload.strip()
        if not s:
            return None
        if s.startswith("```"):
            # Strip ``` fences; tolerate ```json or bare ```.
            s = re.sub(r"^```[a-zA-Z0-9]*\s*", "", s)
            if s.endswith("```"):
                s = s[:-3]
            s = s.strip()
        if not (s.startswith("{") or s.startswith("[")):
            # Try to locate a JSON object somewhere in the body.
            first = s.find("{")
            last = s.rfind("}")
            if first == -1 or last <= first:
                return None
            s = s[first : last + 1]
        try:
            obj = json.loads(s)
        except (ValueError, TypeError):
            return None

    if isinstance(obj, list):
        items = obj
    elif isinstance(obj, dict):
        items = obj.get("paragraphs")
        if items is None:
            return None
    else:
        return None
    if not isinstance(items, list) or not items:
        return None

    paragraphs: list[ParagraphProvenance] = []
    for raw in items:
        if isinstance(raw, str):
            text = raw.strip()
            if text:
                paragraphs.append(ParagraphProvenance(text=text, provenance=[]))
            continue
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "").strip()
        if not text:
            continue
        prov_raw = raw.get("provenance") or raw.get("citations") or []
        if not isinstance(prov_raw, list):
            prov_raw = []
        prov: list[dict[str, str]] = []
        for p in prov_raw:
            if isinstance(p, str):
                # Tolerate the LLM dropping plain strings; treat them
                # as unsourced labels rather than dropping the data.
                prov.append({"kind": "unsourced", "ref": p, "label": p})
                continue
            if not isinstance(p, dict):
                continue
            kind = str(p.get("kind") or "").strip().lower()
            if kind not in _PROV_KINDS:
                kind = "unsourced"
            ref = str(p.get("ref") or p.get("chunk_id") or p.get("id") or "").strip()
            label = str(p.get("label") or "").strip()
            prov.append({"kind": kind, "ref": ref, "label": label})
        paragraphs.append(ParagraphProvenance(text=text, provenance=prov))
    return paragraphs or None


def _flatten_paragraphs(paragraphs: list[ParagraphProvenance]) -> str:
    return "\n\n".join(p.text for p in paragraphs).strip()


def _build_section_prompt(recipe: Recipe, section: RecipeSection, inputs: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"## Task: produce section '{section.title}' of {recipe.title}")
    lines.append(f"Regulation: {recipe.regulation}")
    if recipe.description:
        lines.append(f"Context: {recipe.description}")
    if inputs:
        rendered = ", ".join(f"{k}={v!r}" for k, v in sorted(inputs.items()))
        lines.append(f"Inputs: {rendered}")
    if section.instructions:
        lines.append(f"Instructions: {section.instructions}")
    if section.citations:
        lines.append(
            "Required citations (must be surfaced verbatim in-line): "
            + ", ".join(section.citations)
        )
    if recipe.ckf_queries:
        lines.append(
            "Recall the following from the Contextual Knowledge Fabric before "
            "drafting: " + "; ".join(recipe.ckf_queries)
        )
    if section.word_budget:
        lines.append(
            f"Target length: approximately {section.word_budget} words. "
            "Concise, evidence-first, no filler."
        )
    lines.append("")
    lines.append(
        "OUTPUT CONTRACT — return a single JSON object, no prose before or after, with this shape:"
    )
    lines.append(
        '{"paragraphs": ['
        '{"text": "<one paragraph of markdown>", '
        '"provenance": [{"kind": "<regulation|artefact|runtime|interview|profile|placeholder>", '
        '"ref": "<chunk_id or artefact_id or stats.<key> or interview:<question_id>>", '
        '"label": "<short human label, optional>"}]}'
        "]}"
    )
    lines.append(
        "Provenance rules:\n"
        "  • Every paragraph MUST list at least one provenance entry.\n"
        "  • kind=regulation: ref must be a chunk_id you obtained from "
        "query_regulation, query_regulation_packed, lookup_annex, "
        "lookup_gdpr, search_iso42001, OR a chunk_id pre-loaded in the "
        "CRP context primer system message.\n"
        "  • kind=artefact: ref must be an artefact id returned by "
        "fetch_artefact in this session.\n"
        "  • kind=runtime: ref must reference a stat from "
        'query_proxy_metrics (e.g. "stats.total_requests", '
        '"stats.compliance_rate", "stats.models_used").\n'
        "  • kind=interview / profile: ref names the input field or "
        "fact id that supplied the answer.\n"
        "  • kind=placeholder: use ONLY when evidence is missing — set "
        'the paragraph text to "[PLACEHOLDER:<reason>]" and call '
        "request_clarification (or note that the proxy is not wired) "
        "in the same turn.\n"
        "  • Never invent a chunk_id or artefact id."
    )
    return "\n".join(lines)


def _build_recipe_context(
    recipe: Recipe, section: RecipeSection, profile: dict[str, Any] | None
) -> dict[str, Any]:
    """Build the ``recipe_context`` payload for ``ComplianceAgent.run``.

    The agent uses this to pre-pack the relevant regulatory chunks
    into the LLM's working memory before the first turn — see
    ``ComplianceAgent._prime_corpus_envelope``.
    """

    keywords: list[str] = []
    if section.title:
        keywords.append(section.title)
    keywords.extend(section.citations or [])
    if recipe.regulation:
        keywords.append(recipe.regulation)
    if recipe.title:
        keywords.append(recipe.title)
    return {
        "recipe_id": recipe.recipe_id,
        "regulation": recipe.regulation,
        "section_id": section.id,
        "topic_keywords": keywords,
        "profile": dict(profile or {}),
    }


def _render_markdown(
    recipe: Recipe,
    drafts: dict[str, str],
    inputs: dict[str, Any],
    sections: list[RecipeSection] | None = None,
    section_paragraphs: dict[str, list[ParagraphProvenance]] | None = None,
) -> str:
    parts: list[str] = []
    parts.append(f"# {recipe.title}")
    parts.append(f"*{recipe.regulation} — recipe v{recipe.version}*")
    if inputs:
        kv = ", ".join(f"`{k}`={v!r}" for k, v in sorted(inputs.items()))
        parts.append(f"**Inputs:** {kv}")
    parts.append("")
    paragraphs_map = section_paragraphs or {}
    for section in sections if sections is not None else recipe.sections:
        parts.append(f"## {section.title}")
        paragraphs = paragraphs_map.get(section.id) or []
        if paragraphs:
            # Build numbered footnotes per section so the rendered
            # markdown ships an evidence trail under every clause.
            footnotes: list[str] = []
            for idx, para in enumerate(paragraphs, 1):
                if para.provenance:
                    parts.append(f"{para.text} [^{section.id}-{idx}]")
                    refs = ", ".join(_format_provenance(p) for p in para.provenance)
                    footnotes.append(f"[^{section.id}-{idx}]: {refs}")
                else:
                    parts.append(para.text)
                parts.append("")
            if footnotes:
                parts.extend(footnotes)
                parts.append("")
        else:
            body = drafts.get(section.id, "").strip() or "_(section not produced)_"
            parts.append(body)
            parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def _format_provenance(p: dict[str, str]) -> str:
    kind = p.get("kind") or "unsourced"
    ref = p.get("ref") or ""
    label = p.get("label") or ""
    head = f"`{kind}`"
    if ref:
        head += f" `{ref}`"
    if label:
        head += f" — {label}"
    return head


class RecipeRunner:
    """Executes :class:`Recipe` objects against an agent or a stub function.

    Parameters
    ----------
    agent:
        Either a :class:`~crp_comply.agent.ComplianceAgent` (anything
        exposing ``.run(task, **kwargs)``) **or** a callable taking
        ``(prompt: str, section: RecipeSection) -> str`` — the latter is
        used by tests and by the CLI's stub mode.
    """

    def __init__(
        self,
        agent: _AgentLike | Callable[..., str],
        *,
        notifier: Callable[[RecipeOutput, dict[str, Any]], None] | None = None,
        derivation_provider: Callable[[Recipe, dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self.agent = agent
        #: Optional post-run hook. Called with ``(output, inputs)`` after a
        #: successful ``run()`` — the API layer wires this to the
        #: :class:`NotificationDispatcher` so the user gets a ring / email
        #: when a deliverable is ready. Exceptions in the notifier are
        #: logged and swallowed (never fail the run).
        self.notifier = notifier
        #: Optional callback that returns ``{artefact_index, proxy_window,
        #: corpus_manifest_hash}`` for the derivation manifest. Called
        #: with ``(recipe, inputs)``. Exceptions are logged and the run
        #: continues with an empty manifest — staleness is best-effort.
        self.derivation_provider = derivation_provider

    # ---- internals ---------------------------------------------------

    def _draft_section(
        self,
        recipe: Recipe,
        section: RecipeSection,
        inputs: dict[str, Any],
        *,
        profile: dict[str, Any] | None = None,
    ) -> tuple[str, list[ParagraphProvenance], list[str]]:
        prompt = _build_section_prompt(recipe, section, inputs)
        warnings: list[str] = []
        text = ""
        paragraphs: list[ParagraphProvenance] = []
        if callable(self.agent) and not hasattr(self.agent, "run"):
            # Stub / test callable.
            try:
                text = str(self.agent(prompt, section) or "")  # type: ignore[misc]
            except Exception as exc:  # pragma: no cover
                log.exception("recipe stub agent raised")
                warnings.append(f"stub agent error: {exc}")
        else:
            try:
                run = getattr(self.agent, "run")
                ctx = _build_recipe_context(recipe, section, profile)
                # ``recipe_context`` is keyword-only on ``ComplianceAgent``;
                # tolerate older / stub agents that don't accept it.
                try:
                    result = run(prompt, recipe_context=ctx)
                except TypeError:
                    result = run(prompt)
                text = str(getattr(result, "final_text", "") or "")
            except Exception as exc:
                log.exception("recipe agent.run failed for %s", section.id)
                warnings.append(f"agent error: {exc}")

        parsed = _coerce_paragraphs(text)
        if parsed is not None:
            paragraphs = parsed
            # Replace the raw envelope text with the flat paragraph
            # body so legacy citation extraction still sees clauses.
            text = _flatten_paragraphs(parsed)
        elif text.strip():
            warnings.append(
                f"section '{section.id}': LLM returned plain markdown without "
                "a provenance envelope — falling back to single unsourced "
                "paragraph (provenance is best-effort for this section)"
            )
            paragraphs = [
                ParagraphProvenance(
                    text=text.strip(),
                    provenance=[{"kind": "unsourced", "ref": "", "label": ""}],
                )
            ]
        return text, paragraphs, warnings

    # ---- public ------------------------------------------------------

    def run(
        self,
        recipe: Recipe,
        *,
        inputs: dict[str, Any] | None = None,
        profile: dict[str, Any] | None = None,
        on_section: Callable[[dict[str, Any]], None] | None = None,
    ) -> RecipeOutput:
        errs = recipe.validate()
        if errs:
            raise ValueError(f"invalid recipe: {'; '.join(errs)}")
        provided = dict(inputs or {})

        # Tailoring first — if the recipe doesn't apply to this profile,
        # fail fast before nagging for inputs the user won't need.
        tailoring_skipped: list[tuple[str, str, str]] = []
        sections_to_run = list(recipe.sections)
        if profile:
            from .tailoring import tailor_recipe

            plan = tailor_recipe(recipe, profile)
            if not plan.should_produce:
                raise ValueError(
                    f"recipe '{recipe.recipe_id}' does not apply to this profile: {plan.why}"
                )
            sections_to_run = list(plan.applicable_sections)
            tailoring_skipped = [(s.section_id, s.title, s.reason) for s in plan.skipped_sections]

        missing = [k for k in recipe.required_inputs if k not in provided]
        if missing:
            raise ValueError(f"recipe '{recipe.recipe_id}' missing required inputs: {missing}")

        t0 = time.perf_counter()
        drafts: dict[str, str] = {}
        section_citations: dict[str, list[str]] = {}
        section_paragraphs: dict[str, list[ParagraphProvenance]] = {}
        warnings: list[str] = []

        for section in sections_to_run:
            text, paragraphs, warns = self._draft_section(
                recipe, section, provided, profile=profile
            )
            warnings.extend(warns)
            drafts[section.id] = text
            section_paragraphs[section.id] = paragraphs
            found = _extract_citations(text)
            # Union with recipe-declared citations so downstream never
            # has to chase the LLM for compliance-required references.
            merged: list[str] = []
            seen: set[str] = set()
            for c in list(section.citations) + found:
                key = c.lower()
                if key not in seen:
                    seen.add(key)
                    merged.append(c)
            section_citations[section.id] = merged
            # Warn if the LLM forgot a mandatory citation.
            for required in section.citations:
                if required.lower() not in text.lower():
                    warnings.append(f"section '{section.id}' missing required citation: {required}")
            # Per-section streaming hook — used by the agent's
            # ``run_recipe`` tool to emit ``loop.recipe.delta`` events
            # so the frontend reasoning tape can show drafting
            # progress in real time. Exceptions are swallowed; a
            # broken UI sink must never fail a recipe run.
            if on_section is not None:
                try:
                    on_section(
                        {
                            "section_id": section.id,
                            "title": section.title,
                            "text": drafts.get(section.id, ""),
                            "paragraphs": [p.to_dict() for p in paragraphs],
                            "citations": list(section_citations[section.id]),
                            "paragraph_count": len(paragraphs),
                            "warnings": list(warns),
                        }
                    )
                except Exception:  # pragma: no cover — never break run()
                    log.debug("on_section callback raised; ignoring", exc_info=True)

        markdown = _render_markdown(recipe, drafts, provided, sections_to_run, section_paragraphs)
        json_payload: dict[str, Any] = {
            "recipe_id": recipe.recipe_id,
            "title": recipe.title,
            "regulation": recipe.regulation,
            "version": recipe.version,
            "inputs": provided,
            "sections": [
                {
                    "id": s.id,
                    "title": s.title,
                    "text": drafts.get(s.id, ""),
                    "citations": section_citations.get(s.id, []),
                    "paragraphs": [p.to_dict() for p in section_paragraphs.get(s.id, [])],
                }
                for s in sections_to_run
            ],
        }
        if tailoring_skipped:
            json_payload["skipped_sections"] = [
                {"section_id": sid, "title": t, "reason": r} for (sid, t, r) in tailoring_skipped
            ]
            for sid, _title, reason in tailoring_skipped:
                warnings.append(f"section '{sid}' skipped by tailoring: {reason}")

        output = RecipeOutput(
            recipe_id=recipe.recipe_id,
            title=recipe.title,
            regulation=recipe.regulation,
            markdown=markdown,
            json_payload=json_payload,
            section_citations=section_citations,
            inputs=provided,
            duration_ms=int((time.perf_counter() - t0) * 1000),
            warnings=warnings,
        )

        # Derivation manifest — binds the deliverable to the exact
        # evidence that produced it (Gap #7). The provider is optional;
        # tests and the CLI omit it and get an evidence-empty manifest
        # that still records recipe-version + input/profile hashes.
        from .derivation import build_manifest

        provider_payload: dict[str, Any] = {}
        if self.derivation_provider is not None:
            try:
                provider_payload = dict(self.derivation_provider(recipe, provided) or {})
            except Exception as exc:  # pragma: no cover — defensive
                log.warning("derivation provider failed: %s", exc)
                output.warnings.append(f"derivation_provider_failed: {exc}")
        manifest = build_manifest(
            recipe_id=recipe.recipe_id,
            recipe_version=recipe.version,
            profile=profile,
            inputs=provided,
            artefact_index=provider_payload.get("artefact_index") or {},
            proxy_window=provider_payload.get("proxy_window") or {},
            corpus_manifest_hash=str(provider_payload.get("corpus_manifest_hash") or ""),
        )
        output.derivation = manifest.to_dict()
        # Surface the manifest in the json payload too so anyone reading
        # the deliverable file (not the API envelope) sees provenance.
        json_payload["derivation"] = output.derivation

        # Fire completion notification (ring the user's chat, email, etc.)
        # Never allowed to break the run — bad notifier = warning only.
        if self.notifier is not None:
            try:
                self.notifier(output, provided)
            except Exception as exc:  # pragma: no cover — defensive
                log.warning("recipe notifier failed: %s", exc)
                output.warnings.append(f"notifier_failed: {exc}")

        return output


__all__ = ["RecipeRunner", "RecipeOutput", "ParagraphProvenance"]
