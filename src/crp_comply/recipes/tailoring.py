# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Recipe tailoring engine.

Given a ``Recipe`` and a ``UserProfile`` (plain dict of facts about
the user / system / organisation), return a :class:`TailoringPlan`
that tells the caller — and the UI — **which sections apply, which
do not, and the rationale for every skip**.

The profile is an arbitrary ``dict[str, Any]`` so callers can pass
whatever they have. Conditions use a tiny DSL designed for YAML:

* ``"is_high_risk"`` — ``profile["is_high_risk"]`` must be truthy.
* ``"!is_high_risk"`` — negation.
* ``"actor=provider"`` — equality against a string value.
* ``"actor=provider|deployer"`` — OR-set: value must be in the set.
* ``"jurisdiction~EU"`` — membership (``EU`` in the list value).
* Multiple strings in a list are combined with **AND**.

The evaluator is intentionally pure (no ``eval``, no network). It
ignores unknown keys (returns ``False`` for truthy-style checks,
``False`` for equality) and never raises on a malformed condition —
it logs a warning and returns ``False``.

Example
-------

.. code-block:: python

    from crp_comply.recipes import load_recipe
    from crp_comply.recipes.tailoring import tailor_recipe

    recipe = load_recipe("eu_ai_act_art_27_fria")
    plan = tailor_recipe(recipe, {
        "actor": "deployer",
        "organisation_type": "public_body",
        "is_high_risk": True,
        "annex_iii_row": "5(a) credit scoring",
        "processes_personal_data": True,
    })
    print(plan.should_produce, plan.why)
    for s in plan.applicable_sections:
        ...
    for s, reason in plan.skipped_sections:
        ...
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .loader import ClarificationSpec, Recipe, RecipeSection

log = logging.getLogger("crp_comply.recipes.tailoring")


# ── Profile contract (informational) ──────────────────────────

#: Canonical profile keys the tailoring layer understands.
#: Callers are free to pass extra keys — they're simply available to
#: recipe-level conditions but ignored if never referenced.
CANONICAL_PROFILE_KEYS: tuple[str, ...] = (
    "actor",  # provider | deployer | importer | distributor |
    # authorised_representative | gpai_provider |
    # controller | processor | any
    "established_in_eu",  # bool
    "organisation_type",  # public_body | private_public_service | credit_scoring |
    # life_health_insurance | general | sme
    "system_category",  # high_risk | limited_risk | minimal_risk | prohibited |
    # gpai | gpai_systemic
    "annex_iii_row",  # str (blank = N/A)
    "is_high_risk",  # bool
    "is_gpai",  # bool
    "is_gpai_systemic",  # bool
    "processes_personal_data",  # bool
    "processes_special_category_data",  # bool
    "uses_biometrics",  # bool
    "is_chatbot",  # bool — Art 50(1)
    "generates_synthetic_content",  # bool — Art 50(2)
    "is_emotion_recognition",  # bool — Art 50(3)
    "is_biometric_categorisation",  # bool — Art 50(3)
    "is_deepfake_generator",  # bool — Art 50(4)
    "uses_continuous_learning",  # bool — Art 15(4)
    "workplace_deployment",  # bool — Art 26(7)
    "automated_decision_making",  # bool — GDPR Art 22 / AI Act Art 86
    "has_children_users",  # bool — Art 9(9), Art 27(1)(d)
    "iso_42001_certified",  # bool
    "iso_27001_certified",  # bool
    "jurisdiction",  # list[str] — ["EU","UK","US","AU",...]
    "sector",  # str — health | finance | employment | education | ...
    "deploys_public_service",  # bool — Art 27(1)
)


# ── Result types ──────────────────────────────────────────────


@dataclass
class SkippedSection:
    """Record of a section that was removed from the tailored recipe."""

    section_id: str
    title: str
    reason: str  # human-readable "why not" for UI surfacing
    rule: str = ""  # the condition string that triggered the skip, for audit


@dataclass
class ClarificationRequest:
    """A question the agent must ask the user to resolve an uncertainty.

    Produced by the tri-state tailoring engine when a condition touches
    a profile key the user hasn't answered yet. Downstream consumers:

    * the in-app chat UI (renders with a ringer sound),
    * the notification multiplexer (routes to email / SMS / webhook),
    * the agent orchestrator (re-raises as
      :class:`~crp_comply.agent.tools.ClarificationNeeded` to honour the
      existing clarification budget).

    The ``scope`` distinguishes a recipe-level blocker from a
    section-scoped refinement so the UI can group them.
    """

    profile_key: str
    question: str
    context: str = ""
    priority: str = "medium"  # high | medium | low
    fact_key: str = ""
    citation: str = ""
    answer_type: str = "bool"
    options: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    recipe_id: str = ""
    scope: str = "recipe"  # "recipe" | "section"
    section_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_key": self.profile_key,
            "question": self.question,
            "context": self.context,
            "priority": self.priority,
            "fact_key": self.fact_key,
            "citation": self.citation,
            "answer_type": self.answer_type,
            "options": list(self.options),
            "examples": list(self.examples),
            "recipe_id": self.recipe_id,
            "scope": self.scope,
            "section_id": self.section_id,
        }


@dataclass
class TailoringPlan:
    """What the engine returns.

    Attributes
    ----------
    recipe_id:
        Mirrors the input recipe id.
    should_produce:
        ``True``/``False``/``"uncertain"``. ``"uncertain"`` means the
        engine needs at least one answer before it can decide; see
        :attr:`pending_questions`.
    why:
        Human-readable applicability verdict — shown in the UI before
        the user clicks "run".
    pending_questions:
        Clarification requests the agent should surface before it can
        finalise the plan. Ordered by priority (high → medium → low).
    applicable_sections / skipped_sections / profile_keys_used:
        As before — but during ``should_produce="uncertain"`` the
        applicable set is the best-effort optimistic projection (any
        section whose own gating is known and passes).
    """

    recipe_id: str
    should_produce: Any  # bool | "uncertain"
    why: str
    purpose: str = ""
    triggers: list[str] = field(default_factory=list)
    deadline: str = ""
    actors: list[str] = field(default_factory=list)
    applicable_sections: list[RecipeSection] = field(default_factory=list)
    skipped_sections: list[SkippedSection] = field(default_factory=list)
    profile_keys_used: list[str] = field(default_factory=list)
    pending_questions: list[ClarificationRequest] = field(default_factory=list)

    @property
    def is_uncertain(self) -> bool:
        return self.should_produce == "uncertain"

    def to_dict(self) -> dict[str, Any]:
        return {
            "recipe_id": self.recipe_id,
            "should_produce": self.should_produce,
            "why": self.why,
            "purpose": self.purpose,
            "triggers": list(self.triggers),
            "deadline": self.deadline,
            "actors": list(self.actors),
            "applicable_sections": [
                {"id": s.id, "title": s.title, "citations": list(s.citations)}
                for s in self.applicable_sections
            ],
            "skipped_sections": [
                {
                    "section_id": s.section_id,
                    "title": s.title,
                    "reason": s.reason,
                    "rule": s.rule,
                }
                for s in self.skipped_sections
            ],
            "profile_keys_used": sorted(set(self.profile_keys_used)),
            "pending_questions": [q.to_dict() for q in self.pending_questions],
        }


# ── Condition DSL evaluator ───────────────────────────────────


def _parse_condition(cond: str) -> tuple[str, str, str]:
    """Return ``(op, key, value)``.

    ``op`` ∈ ``{"truthy", "!truthy", "eq", "neq", "in", "contains"}``.
    """
    c = cond.strip()
    if not c:
        return ("noop", "", "")
    if c.startswith("!"):
        return ("!truthy", c[1:].strip(), "")
    # "key~value" contains — value in list-valued key
    if "~" in c and "=" not in c:
        k, v = c.split("~", 1)
        return ("contains", k.strip(), v.strip())
    if "!=" in c:
        k, v = c.split("!=", 1)
        return ("neq", k.strip(), v.strip())
    if "=" in c:
        k, v = c.split("=", 1)
        v = v.strip()
        if "|" in v:
            return ("in", k.strip(), v)
        return ("eq", k.strip(), v)
    return ("truthy", c, "")


def _truthy(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        return v.strip().lower() not in {"", "false", "no", "0", "none", "null"}
    if isinstance(v, (list, tuple, set, dict)):
        return len(v) > 0
    return True


def _eval_one(cond: str, profile: dict[str, Any], used: set[str]) -> bool:
    op, key, value = _parse_condition(cond)
    if op == "noop":
        return True
    used.add(key)
    v = profile.get(key)
    if op == "truthy":
        return _truthy(v)
    if op == "!truthy":
        return not _truthy(v)
    if op == "eq":
        return str(v) == value
    if op == "neq":
        return str(v) != value
    if op == "in":
        options = {o.strip() for o in value.split("|") if o.strip()}
        return str(v) in options
    if op == "contains":
        if isinstance(v, (list, tuple, set)):
            return value in {str(x) for x in v}
        if isinstance(v, str):
            return value in v
        return False
    log.warning("unknown condition op in %r", cond)
    return False


# ── Tri-state evaluation (True / False / Unknown) ─────────────
#
# The classic evaluator collapses a missing key to False. That's fine
# for the executor's "should I run this section?" question but it's a
# lie for the tailoring UI: we shouldn't silently tell a user "FRIA
# doesn't apply" just because they haven't yet told us their actor
# type. The tri-state evaluator raises the missing key up to the
# caller so the clarification generator can turn it into a question.


UNKNOWN = object()


def _is_key_known(key: str, profile: dict[str, Any]) -> bool:
    """A key is *known* when the profile contains it with a non-None value.

    Empty strings and empty collections also count as unknown because
    they carry no signal (the user hasn't answered yet).
    """
    if key not in profile:
        return False
    v = profile[key]
    if v is None:
        return False
    if isinstance(v, str) and not v.strip():
        return False
    if isinstance(v, (list, tuple, set, dict)) and len(v) == 0:
        return False
    return True


def _eval_tri(cond: str, profile: dict[str, Any], used: set[str], unknown_keys: set[str]) -> Any:
    """Tri-state: return ``True``, ``False`` or the ``UNKNOWN`` sentinel.

    Any condition touching a key not present in the profile returns
    ``UNKNOWN`` and appends the key to ``unknown_keys`` so the caller
    can generate a clarification.
    """
    op, key, _value = _parse_condition(cond)
    if op == "noop":
        return True
    used.add(key)
    if not _is_key_known(key, profile):
        unknown_keys.add(key)
        return UNKNOWN
    return _eval_one(cond, profile, used)


def evaluate_all_tri(
    conds: list[str], profile: dict[str, Any], used: set[str], unknown_keys: set[str]
) -> Any:
    """AND-combined tri-state.

    * All True → True.
    * Any False → False (short-circuit; unknowns beyond the failure are
      not surfaced because they're moot).
    * Otherwise (no definite False, at least one Unknown) → UNKNOWN.
    """
    has_unknown = False
    local_unknowns: set[str] = set()
    for c in conds:
        r = _eval_tri(c, profile, used, local_unknowns)
        if r is False:
            return False
        if r is UNKNOWN:
            has_unknown = True
    if has_unknown:
        unknown_keys.update(local_unknowns)
        return UNKNOWN
    return True


def evaluate_any_tri(
    conds: list[str], profile: dict[str, Any], used: set[str], unknown_keys: set[str]
) -> Any:
    """OR-combined tri-state.

    * Any True → True.
    * All False → False.
    * Otherwise → UNKNOWN.
    """
    if not conds:
        return False
    has_unknown = False
    local_unknowns: set[str] = set()
    for c in conds:
        r = _eval_tri(c, profile, used, local_unknowns)
        if r is True:
            return True
        if r is UNKNOWN:
            has_unknown = True
    if has_unknown:
        unknown_keys.update(local_unknowns)
        return UNKNOWN
    return False


def evaluate_all(conds: list[str], profile: dict[str, Any], used: set[str]) -> bool:
    """AND-combined evaluation of a list of conditions.

    Empty list returns ``True`` (vacuously applies).
    """
    return all(_eval_one(c, profile, used) for c in conds)


def evaluate_any(conds: list[str], profile: dict[str, Any], used: set[str]) -> bool:
    """OR-combined evaluation.

    Empty list returns ``False``.
    """
    return any(_eval_one(c, profile, used) for c in conds)


# ── Public API ────────────────────────────────────────────────


def tailor_recipe(recipe: Recipe, profile: dict[str, Any] | None) -> TailoringPlan:
    """Tailor a recipe to a user profile.

    When ``profile`` is ``None`` or empty, the plan marks the recipe
    ``should_produce=True`` (vacuously) and includes every section —
    this is the conservative default for profile-less preview in the
    marketing catalogue.
    """
    profile = dict(profile or {})
    used: set[str] = set()
    app = recipe.applicability

    # ── Recipe-level verdict ─────────────────────────────────
    if app.not_applicable_when and evaluate_any(app.not_applicable_when, profile, used):
        return TailoringPlan(
            recipe_id=recipe.recipe_id,
            should_produce=False,
            why=(
                "This recipe does not apply to your profile because one or "
                "more exclusion conditions are met: " + ", ".join(app.not_applicable_when)
            ),
            purpose=app.purpose,
            triggers=list(app.triggers),
            deadline=app.deadline,
            actors=list(app.actors),
            applicable_sections=[],
            skipped_sections=[],
            profile_keys_used=sorted(used),
        )

    recipe_applies = evaluate_all(app.applies_when, profile, used)

    # ── Section-by-section ───────────────────────────────────
    applicable: list[RecipeSection] = []
    skipped: list[SkippedSection] = []
    for s in recipe.sections:
        sa = s.applicability
        if sa.required:
            applicable.append(s)
            continue
        # Hard exclusion: skip_when wins over applies_when.
        if sa.skip_when and evaluate_any(sa.skip_when, profile, used):
            reason = sa.skip_rationale or (
                "Section skipped because one of its exclusion conditions "
                "is true for your profile: " + ", ".join(sa.skip_when)
            )
            skipped.append(
                SkippedSection(
                    section_id=s.id,
                    title=s.title,
                    reason=reason,
                    rule="; ".join(sa.skip_when),
                )
            )
            continue
        if sa.applies_when and not evaluate_all(sa.applies_when, profile, used):
            reason = sa.skip_rationale or (
                "Section skipped because your profile does not meet its "
                "inclusion conditions: " + ", ".join(sa.applies_when)
            )
            skipped.append(
                SkippedSection(
                    section_id=s.id,
                    title=s.title,
                    reason=reason,
                    rule="; ".join(sa.applies_when),
                )
            )
            continue
        applicable.append(s)

    if recipe_applies:
        why = (
            "This recipe applies to your profile. "
            + (f"Purpose: {app.purpose} " if app.purpose else "")
            + (f"Trigger: {app.triggers[0]}." if app.triggers else "")
        ).strip()
    else:
        why = (
            "This recipe does not fully match your profile; conditions not "
            "met: " + ", ".join(app.applies_when)
            if app.applies_when
            else "This recipe has no applicability conditions declared."
        )

    return TailoringPlan(
        recipe_id=recipe.recipe_id,
        should_produce=recipe_applies if app.applies_when else True,
        why=why,
        purpose=app.purpose,
        triggers=list(app.triggers),
        deadline=app.deadline,
        actors=list(app.actors),
        applicable_sections=applicable,
        skipped_sections=skipped,
        profile_keys_used=sorted(used),
    )


def recommend_recipes(
    recipes: list[Recipe],
    profile: dict[str, Any] | None,
) -> list[TailoringPlan]:
    """Rank recipes for a profile — applicable first, sorted by
    number of skipped sections ascending (more relevant = fewer skips).
    """
    plans = [tailor_recipe(r, profile) for r in recipes]
    plans.sort(
        key=lambda p: (
            0 if p.should_produce is True else (1 if p.should_produce == "uncertain" else 2),
            len(p.skipped_sections),
            p.recipe_id,
        )
    )
    return plans


# ── Dynamic (tri-state) tailoring ─────────────────────────────


#: Fallback question templates, used when a recipe's YAML did not
#: declare an :class:`~crp_comply.recipes.loader.ClarificationSpec` for
#: a profile key. The agent still gets a sensible question so nothing
#: is ever asked in raw-flag form ("is_high_risk?"). Recipes should
#: override these with clause-specific prompts.
_FALLBACK_QUESTIONS: dict[str, dict[str, Any]] = {
    "actor": {
        "question": "What role does your organisation play for this AI system?",
        "answer_type": "choice",
        "options": [
            "provider",
            "deployer",
            "importer",
            "distributor",
            "authorised_representative",
            "gpai_provider",
        ],
        "priority": "high",
        "context": "Your role decides which obligations apply across the AI Act.",
    },
    "is_high_risk": {
        "question": "Is this system classified as high-risk under the EU AI Act?",
        "answer_type": "bool",
        "priority": "high",
        "context": (
            "High-risk classification (Art. 6 + Annex III) triggers most "
            "documentation and conformity-assessment duties."
        ),
    },
    "is_gpai": {
        "question": "Is this a general-purpose AI model (GPAI)?",
        "answer_type": "bool",
        "priority": "high",
        "context": "GPAI model providers face Art. 53 obligations.",
    },
    "is_gpai_systemic": {
        "question": "Is this a GPAI model with systemic risk (Art. 51)?",
        "answer_type": "bool",
        "priority": "medium",
        "context": "Systemic-risk GPAI models face additional Art. 55 duties.",
    },
    "processes_personal_data": {
        "question": "Does the system process personal data (as defined by GDPR)?",
        "answer_type": "bool",
        "priority": "high",
        "context": "Processing of personal data brings GDPR obligations in scope.",
    },
    "established_in_eu": {
        "question": "Is your organisation established in the European Union?",
        "answer_type": "bool",
        "priority": "medium",
        "context": "Non-EU providers must appoint an authorised representative (Art. 22).",
    },
    "is_chatbot": {
        "question": "Does the system interact with natural persons as a chatbot or conversational agent?",
        "answer_type": "bool",
        "priority": "medium",
        "context": "Art. 50(1) requires user-notification for chatbots.",
    },
    "is_deepfake_generator": {
        "question": "Can the system generate or manipulate deepfake content?",
        "answer_type": "bool",
        "priority": "medium",
        "context": "Art. 50(4) requires disclosure of AI-generated deepfakes.",
    },
    "organisation_type": {
        "question": "Which category best describes your organisation?",
        "answer_type": "choice",
        "options": [
            "public_body",
            "private_public_service",
            "credit_scoring",
            "life_health_insurance",
            "general",
            "sme",
        ],
        "priority": "medium",
        "context": "Only certain deployer categories owe a Fundamental Rights Impact Assessment (Art. 27).",
    },
    "automated_decision_making": {
        "question": "Does the system produce decisions with legal or similarly significant effects on individuals?",
        "answer_type": "bool",
        "priority": "medium",
        "context": "Triggers the Art. 86 right-to-explanation and GDPR Art. 22.",
    },
}


def _build_clarification(
    profile_key: str,
    *,
    recipe_id: str,
    scope: str,
    section_id: str = "",
    spec_lookup: dict[str, ClarificationSpec] | None = None,
) -> ClarificationRequest:
    """Build a ``ClarificationRequest`` for ``profile_key``.

    Lookup order: section-scoped YAML spec → recipe-scoped YAML spec →
    built-in fallback templates → generic "please tell us X" question.
    """
    spec = (spec_lookup or {}).get(profile_key)
    if spec and spec.question:
        return ClarificationRequest(
            profile_key=profile_key,
            question=spec.question,
            context=spec.context,
            priority=spec.priority,
            fact_key=spec.fact_key or profile_key,
            citation=spec.citation,
            answer_type=spec.answer_type,
            options=list(spec.options),
            examples=list(spec.examples),
            recipe_id=recipe_id,
            scope=scope,
            section_id=section_id,
        )
    fb = _FALLBACK_QUESTIONS.get(profile_key)
    if fb:
        return ClarificationRequest(
            profile_key=profile_key,
            question=str(fb["question"]),
            context=str(fb.get("context", "")),
            priority=str(fb.get("priority", "medium")),
            fact_key=profile_key,
            answer_type=str(fb.get("answer_type", "bool")),
            options=list(fb.get("options", [])),
            recipe_id=recipe_id,
            scope=scope,
            section_id=section_id,
        )
    # Last-resort generic question — keep it sensible rather than raw.
    human = profile_key.replace("_", " ")
    return ClarificationRequest(
        profile_key=profile_key,
        question=f"Can you tell us about '{human}' for this AI system?",
        context="We need this to tailor the document to your situation.",
        priority="medium",
        fact_key=profile_key,
        answer_type="text",
        recipe_id=recipe_id,
        scope=scope,
        section_id=section_id,
    )


_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def tailor_recipe_dynamic(
    recipe: Recipe,
    profile: dict[str, Any] | None,
    *,
    ckf_lookup: Any = None,
) -> TailoringPlan:
    """Tri-state tailoring.

    Behaves like :func:`tailor_recipe` when every referenced profile
    key is known; otherwise returns a plan with
    ``should_produce="uncertain"`` and a list of
    :class:`ClarificationRequest` objects ordered by priority.

    ``ckf_lookup`` may be any callable/object exposing
    ``get(fact_key) -> value | None`` — used to auto-fill profile keys
    from the user's Contextual Knowledge Fabric before asking. This is
    how we avoid re-asking the user the same thing across sessions.
    """
    profile = dict(profile or {})
    used: set[str] = set()
    unknown: set[str] = set()
    app = recipe.applicability

    # ── CKF auto-fill pass ───────────────────────────────────
    def _resolve_key(key: str) -> None:
        if ckf_lookup is None or _is_key_known(key, profile):
            return
        getter = getattr(ckf_lookup, "get", None)
        if not callable(getter):
            return
        try:
            val = getter(key)
        except Exception:  # pragma: no cover
            val = None
        if val is None:
            return
        profile[key] = val

    # Pre-resolve every key the recipe might touch so we only ask
    # about genuine gaps.
    for cond in list(app.applies_when) + list(app.not_applicable_when):
        _, k, _ = _parse_condition(cond)
        if k:
            _resolve_key(k)
    for s in recipe.sections:
        for cond in list(s.applicability.applies_when) + list(s.applicability.skip_when):
            _, k, _ = _parse_condition(cond)
            if k:
                _resolve_key(k)

    # ── Recipe-level verdict ─────────────────────────────────
    not_app = (
        evaluate_any_tri(app.not_applicable_when, profile, used, unknown)
        if app.not_applicable_when
        else False
    )
    if not_app is True:
        return TailoringPlan(
            recipe_id=recipe.recipe_id,
            should_produce=False,
            why=(
                "This recipe does not apply to your profile because one or "
                "more exclusion conditions are met: " + ", ".join(app.not_applicable_when)
            ),
            purpose=app.purpose,
            triggers=list(app.triggers),
            deadline=app.deadline,
            actors=list(app.actors),
            profile_keys_used=sorted(used),
        )

    applies = (
        evaluate_all_tri(app.applies_when, profile, used, unknown) if app.applies_when else True
    )

    pending: list[ClarificationRequest] = []
    if applies is UNKNOWN or not_app is UNKNOWN:
        for key in sorted(unknown):
            pending.append(
                _build_clarification(
                    key,
                    recipe_id=recipe.recipe_id,
                    scope="recipe",
                    spec_lookup=app.ask_when_unknown,
                )
            )

    # Skip section processing entirely when recipe is already False —
    # there's no point asking the user to clarify section-level facts
    # for a recipe that doesn't apply to them.
    recipe_is_false = applies is False

    # ── Section-by-section (still tri-state) ─────────────────
    applicable: list[RecipeSection] = []
    skipped: list[SkippedSection] = []
    iter_sections = [] if recipe_is_false else recipe.sections
    for s in iter_sections:
        sa = s.applicability
        if sa.required:
            applicable.append(s)
            continue
        sec_unknown: set[str] = set()
        skip_verdict = (
            evaluate_any_tri(sa.skip_when, profile, used, sec_unknown) if sa.skip_when else False
        )
        if skip_verdict is True:
            reason = sa.skip_rationale or (
                "Section skipped because one of its exclusion conditions "
                "is true for your profile: " + ", ".join(sa.skip_when)
            )
            skipped.append(
                SkippedSection(
                    section_id=s.id,
                    title=s.title,
                    reason=reason,
                    rule="; ".join(sa.skip_when),
                )
            )
            continue
        apply_verdict = (
            evaluate_all_tri(sa.applies_when, profile, used, sec_unknown)
            if sa.applies_when
            else True
        )
        if apply_verdict is False:
            reason = sa.skip_rationale or (
                "Section skipped because your profile does not meet its "
                "inclusion conditions: " + ", ".join(sa.applies_when)
            )
            skipped.append(
                SkippedSection(
                    section_id=s.id,
                    title=s.title,
                    reason=reason,
                    rule="; ".join(sa.applies_when),
                )
            )
            continue
        if apply_verdict is UNKNOWN or skip_verdict is UNKNOWN:
            for key in sorted(sec_unknown):
                pending.append(
                    _build_clarification(
                        key,
                        recipe_id=recipe.recipe_id,
                        scope="section",
                        section_id=s.id,
                        spec_lookup={**app.ask_when_unknown, **sa.ask_when_unknown},
                    )
                )
        # Optimistic include: section is rendered unless definitely skipped.
        applicable.append(s)

    # De-duplicate questions by (profile_key, scope, section_id).
    dedup: dict[tuple[str, str, str], ClarificationRequest] = {}
    for q in pending:
        key = (q.profile_key, q.scope, q.section_id)
        if key not in dedup or _PRIORITY_ORDER.get(q.priority, 1) < _PRIORITY_ORDER.get(
            dedup[key].priority, 1
        ):
            dedup[key] = q
    pending_sorted = sorted(
        dedup.values(),
        key=lambda q: (_PRIORITY_ORDER.get(q.priority, 1), q.profile_key),
    )

    if applies is True and not pending_sorted:
        verdict: Any = True
        why = (
            "This recipe applies to your profile. "
            + (f"Purpose: {app.purpose} " if app.purpose else "")
            + (f"Trigger: {app.triggers[0]}." if app.triggers else "")
        ).strip()
    elif applies is False:
        verdict = False
        why = "This recipe does not fully match your profile; conditions not met: " + ", ".join(
            app.applies_when
        )
    else:
        verdict = "uncertain"
        why = (
            f"I need {len(pending_sorted)} answer"
            f"{'s' if len(pending_sorted) != 1 else ''} before I can "
            "confirm whether this recipe applies to your situation."
        )

    return TailoringPlan(
        recipe_id=recipe.recipe_id,
        should_produce=verdict,
        why=why,
        purpose=app.purpose,
        triggers=list(app.triggers),
        deadline=app.deadline,
        actors=list(app.actors),
        applicable_sections=applicable if verdict is not False else [],
        skipped_sections=skipped,
        profile_keys_used=sorted(used),
        pending_questions=pending_sorted,
    )


__all__ = [
    "CANONICAL_PROFILE_KEYS",
    "ClarificationRequest",
    "SkippedSection",
    "TailoringPlan",
    "UNKNOWN",
    "evaluate_all",
    "evaluate_all_tri",
    "evaluate_any",
    "evaluate_any_tri",
    "recommend_recipes",
    "tailor_recipe",
    "tailor_recipe_dynamic",
]
