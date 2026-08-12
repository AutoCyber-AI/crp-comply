# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Recipe schema + YAML loader.

The recipe schema is intentionally conservative — every field has a
strict type and unknown keys emit warnings rather than failing loads,
so old recipes keep working as the schema evolves.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None

log = logging.getLogger("crp_comply.recipes.loader")

_BUILTIN_DIR = Path(__file__).parent / "builtin"


@dataclass
class ClarificationSpec:
    """How to ask the user when a profile key is missing/uncertain.

    Attached to an applicability block via ``ask_when_unknown: {key: spec}``.
    The tailoring engine turns the entry for any unresolved key into a
    :class:`ClarificationRequest` that the agent can surface (chat ringer,
    email, etc.) — the same contract the existing
    :class:`~crp_comply.agent.tools.ClarificationNeeded` uses.

    Fields
    ------
    question:
        Plain-English question text shown to the user.
    context:
        Short regulatory justification ("Art. 6(2) makes this the deciding
        factor for high-risk classification"). Rendered as subtext.
    priority:
        ``high`` | ``medium`` | ``low`` — feeds the clarification budget
        ordering and the notification urgency.
    fact_key:
        CKF key under which the answer is persisted — reused across
        recipes so the user is never asked twice.
    citation:
        Specific article/clause the question is anchored to — shown as a
        link so the user can verify the source.
    answer_type:
        ``bool`` (default) | ``choice`` | ``text``.
    options:
        For ``answer_type=choice``, the allowed set.
    examples:
        One-line hints ("e.g. CV-screening tool → 'employment'"). Max 3.
    """

    question: str = ""
    context: str = ""
    priority: str = "medium"
    fact_key: str = ""
    citation: str = ""
    answer_type: str = "bool"
    options: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)


def _parse_clarification_specs(raw: Any) -> dict[str, ClarificationSpec]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, ClarificationSpec] = {}
    for key, spec in raw.items():
        if not isinstance(spec, dict):
            continue
        out[str(key)] = ClarificationSpec(
            question=str(spec.get("question") or "").strip(),
            context=str(spec.get("context") or "").strip(),
            priority=str(spec.get("priority") or "medium").lower().strip(),
            fact_key=str(spec.get("fact_key") or key).strip(),
            citation=str(spec.get("citation") or "").strip(),
            answer_type=str(spec.get("answer_type") or "bool").lower().strip(),
            options=[str(x) for x in (spec.get("options") or [])],
            examples=[str(x) for x in (spec.get("examples") or [])][:3],
        )
    return out


@dataclass
class InterviewBranch:
    """One arm of a branching Socratic interview tree.

    A branch fires when ``when`` evaluates true against the user
    profile (using the same DSL as ``applies_when``); only then are the
    branch's ``ask`` clarifications surfaced to the user. Branches
    chain via ``follow_up`` — the next branch keeps asking when the
    current branch's conditions remain true and its prerequisite
    facts are answered.

    Example YAML::

        interview_branches:
          - id: data_subjects
            when: ["uses_personal_data"]
            citation: "GDPR Art. 4(1)"
            ask:
              automated_decisions:
                question: "Does the system make automated decisions about people?"
                priority: high
                citation: "GDPR Art. 22"
          - id: high_stakes_decisions
            when: ["uses_personal_data", "automated_decisions"]
            ask:
              human_in_the_loop:
                question: "Is there a human in the loop for every output?"
                priority: high
                citation: "GDPR Art. 22(3)"
    """

    id: str = ""
    when: list[str] = field(default_factory=list)
    not_when: list[str] = field(default_factory=list)
    citation: str = ""
    follow_up: list[str] = field(default_factory=list)
    ask: dict[str, ClarificationSpec] = field(default_factory=dict)


def _parse_interview_branches(raw: Any) -> list[InterviewBranch]:
    if not isinstance(raw, list):
        return []
    out: list[InterviewBranch] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        out.append(
            InterviewBranch(
                id=str(entry.get("id") or "").strip(),
                when=[str(x) for x in (entry.get("when") or [])],
                not_when=[str(x) for x in (entry.get("not_when") or [])],
                citation=str(entry.get("citation") or "").strip(),
                follow_up=[str(x) for x in (entry.get("follow_up") or [])],
                ask=_parse_clarification_specs(entry.get("ask")),
            )
        )
    return out


@dataclass
class Applicability:
    """Top-level "when / why" metadata for a recipe.

    Conditions use the tiny DSL described in
    :mod:`crp_comply.recipes.tailoring` (flag, ``!flag``, ``key=value``,
    ``key=a|b`` OR-set; multiple strings in a list are AND).

    Fields
    ------
    applies_when:
        Conditions all of which must hold for the recipe to be
        *applicable* to a given user profile. Empty list ⇒ always.
    not_applicable_when:
        Conditions any of which, if true, mark the recipe as
        *not applicable* (takes precedence over ``applies_when``).
    triggers:
        Human-readable plain-English events that trigger production of
        the deliverable (e.g. "before placing a high-risk system on the
        EU market"). Rendered in the UI and the doc front-matter.
    purpose:
        One-paragraph "why this exists" statement the tailoring engine
        surfaces to the user before they run the recipe.
    actors:
        The actor categories the recipe targets — one or more of
        ``provider``, ``deployer``, ``importer``, ``distributor``,
        ``authorised_representative``, ``gpai_provider``, ``controller``,
        ``processor``, ``any``.
    deadline:
        Human-readable deadline (e.g. "within 15 days of becoming aware",
        "before placing on the market"). Advisory — no enforcement here.
    """

    applies_when: list[str] = field(default_factory=list)
    not_applicable_when: list[str] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)
    purpose: str = ""
    actors: list[str] = field(default_factory=list)
    deadline: str = ""
    #: Per-profile-key clarification templates for uncertain answers.
    ask_when_unknown: dict[str, ClarificationSpec] = field(default_factory=dict)


@dataclass
class SectionApplicability:
    """Per-section applicability rules.

    Fields
    ------
    required:
        If ``True`` the section is always included — skip rules are
        ignored. Use for identification / sign-off sections.
    applies_when:
        All listed conditions must hold; otherwise section is skipped
        with a default "condition not met" rationale.
    skip_when:
        Any listed condition being true skips the section and emits
        ``skip_rationale`` as the explanation to the user.
    skip_rationale:
        Human-readable reason surfaced to the user when the section is
        skipped (e.g. "Your organisation does not process personal
        data, so GDPR cross-references are not required here.").
    """

    required: bool = False
    applies_when: list[str] = field(default_factory=list)
    skip_when: list[str] = field(default_factory=list)
    skip_rationale: str = ""
    #: Per-profile-key clarification templates scoped to this section.
    ask_when_unknown: dict[str, ClarificationSpec] = field(default_factory=dict)


@dataclass
class RecipeSection:
    """A single section of a deliverable.

    Fields
    ------
    id:
        Stable key (``scope``, ``risk_assessment``, ...) used in the JSON
        output and in section_citations entries.
    title:
        Human-readable section heading for the markdown rendering.
    instructions:
        Natural-language prompt segment the executor appends to the
        LLM turn for this section — keeps the narrative style consistent.
    citations:
        Article/clause references that must be surfaced in this section.
    word_budget:
        Soft target for this section's word count (advisory only).
    applicability:
        Optional tailoring rules; if unset the section is always
        included regardless of profile.
    """

    id: str
    title: str
    instructions: str = ""
    citations: list[str] = field(default_factory=list)
    word_budget: int = 0
    applicability: SectionApplicability = field(default_factory=SectionApplicability)


@dataclass
class Recipe:
    """A single regulatory deliverable recipe."""

    recipe_id: str
    title: str
    regulation: str  # e.g. "ISO 42001", "EU AI Act", "NIST AI RMF"
    version: str = "1.0"
    description: str = ""
    required_inputs: list[str] = field(default_factory=list)
    ckf_queries: list[str] = field(default_factory=list)
    tools_allowed: list[str] = field(default_factory=list)
    sections: list[RecipeSection] = field(default_factory=list)
    output_format: str = "markdown"  # markdown | json | both
    output_artefacts: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    applicability: Applicability = field(default_factory=Applicability)
    #: Branching Socratic interview tree. Resolved at run-time against
    #: the user profile to decide which questions to ask, in what order,
    #: anchored to which articles. See :class:`InterviewBranch`.
    interview_branches: list[InterviewBranch] = field(default_factory=list)

    def section_ids(self) -> list[str]:
        return [s.id for s in self.sections]

    def validate(self) -> list[str]:
        """Return a list of validation error strings (empty if OK)."""
        errs: list[str] = []
        if not self.recipe_id:
            errs.append("recipe_id is required")
        if not self.sections:
            errs.append("recipe must define at least one section")
        ids = [s.id for s in self.sections]
        if len(ids) != len(set(ids)):
            errs.append("section ids must be unique")
        allowed_formats = {"markdown", "json", "both"}
        if self.output_format not in allowed_formats:
            errs.append(f"output_format must be one of {sorted(allowed_formats)}")
        return errs

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Recipe":
        section_entries = data.get("sections") or []
        sections: list[RecipeSection] = []
        for s in section_entries:
            if not isinstance(s, dict):
                continue
            app_raw = s.get("applicability") or {}
            app = SectionApplicability(
                required=bool(app_raw.get("required", False)),
                applies_when=[str(x) for x in (app_raw.get("applies_when") or [])],
                skip_when=[str(x) for x in (app_raw.get("skip_when") or [])],
                skip_rationale=str(app_raw.get("skip_rationale") or "").strip(),
                ask_when_unknown=_parse_clarification_specs(app_raw.get("ask_when_unknown")),
            )
            sections.append(
                RecipeSection(
                    id=str(s.get("id") or "").strip(),
                    title=str(s.get("title") or "").strip(),
                    instructions=str(s.get("instructions") or "").strip(),
                    citations=[str(c) for c in (s.get("citations") or [])],
                    word_budget=int(s.get("word_budget", 0) or 0),
                    applicability=app,
                )
            )
        top_app_raw = data.get("applicability") or {}
        top_app = Applicability(
            applies_when=[str(x) for x in (top_app_raw.get("applies_when") or [])],
            not_applicable_when=[str(x) for x in (top_app_raw.get("not_applicable_when") or [])],
            triggers=[str(x) for x in (top_app_raw.get("triggers") or [])],
            purpose=str(top_app_raw.get("purpose") or "").strip(),
            actors=[str(x) for x in (top_app_raw.get("actors") or [])],
            deadline=str(top_app_raw.get("deadline") or "").strip(),
            ask_when_unknown=_parse_clarification_specs(top_app_raw.get("ask_when_unknown")),
        )
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(data) - known - {"sections"}
        if unknown:
            log.warning(
                "recipe %s ignoring unknown keys: %s",
                data.get("recipe_id", "?"),
                sorted(unknown),
            )
        return cls(
            recipe_id=str(data.get("recipe_id", "")).strip(),
            title=str(data.get("title", "")).strip(),
            regulation=str(data.get("regulation", "")).strip(),
            version=str(data.get("version", "1.0")).strip(),
            description=str(data.get("description", "")).strip(),
            required_inputs=[str(x) for x in (data.get("required_inputs") or [])],
            ckf_queries=[str(x) for x in (data.get("ckf_queries") or [])],
            tools_allowed=[str(x) for x in (data.get("tools_allowed") or [])],
            sections=sections,
            output_format=str(data.get("output_format", "markdown")).lower().strip(),
            output_artefacts=[str(x) for x in (data.get("output_artefacts") or [])],
            tags=[str(x) for x in (data.get("tags") or [])],
            applicability=top_app,
            interview_branches=_parse_interview_branches(data.get("interview_branches")),
        )


# ── Loaders ─────────────────────────────────────────────────


def _require_yaml() -> None:
    if yaml is None:
        raise RuntimeError("PyYAML is required to load recipes. Install with `pip install pyyaml`.")


def load_recipe_from_file(path: Path | str) -> Recipe:
    _require_yaml()
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"recipe not found: {p}")
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    recipe = Recipe.from_dict(data)
    errs = recipe.validate()
    if errs:
        raise ValueError(f"invalid recipe {p}: {'; '.join(errs)}")
    return recipe


def builtin_recipe_path(recipe_id: str) -> Path:
    """Resolve a recipe id to its built-in YAML path."""
    p = _BUILTIN_DIR / f"{recipe_id}.yaml"
    if not p.exists():
        raise FileNotFoundError(f"builtin recipe '{recipe_id}' not found at {p}")
    return p


def load_recipe(recipe_id: str) -> Recipe:
    """Load a recipe by id from the built-in library."""
    return load_recipe_from_file(builtin_recipe_path(recipe_id))


def list_builtin_recipes() -> list[str]:
    if not _BUILTIN_DIR.exists():
        return []
    return sorted(p.stem for p in _BUILTIN_DIR.glob("*.yaml"))


__all__ = [
    "Recipe",
    "RecipeSection",
    "InterviewBranch",
    "ClarificationSpec",
    "load_recipe",
    "load_recipe_from_file",
    "list_builtin_recipes",
    "builtin_recipe_path",
]
