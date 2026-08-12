# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""AI-enhanced onboarding API.

The static 5-step wizard captures the canonical OrgProfile but most
non-experts struggle to map their business onto our DSL terms (actor,
``annex_iii_row``, ``is_gpai_systemic`` etc.). This module wraps a
small system-prompted LLM round-trip that turns free-text descriptions
of the user's business into structured profile suggestions, and that
adapts the next clarifying question based on which recipes would
unlock if a profile gap were resolved.

Endpoints
---------

``POST /api/v1/onboarding/extract``
    Body: ``{text: "We're a 25-person Berlin startup that builds…"}``
    Returns: ``{suggested_profile: {...partial OrgProfile},
                rationale: "...", confidence: 0..1, clarifying_question: "..."}``

``POST /api/v1/onboarding/suggest``
    Body: ``{profile: {...partial OrgProfile}}``
    Returns the most useful next question + 2-4 candidate answers,
    chosen to maximise the number of additional recipes that become
    applicable in :func:`recommend_recipes`.

Both endpoints are **PII-safe**: the LLM only sees the free-text the
user volunteered, which is also what they would have typed into the
form anyway. We never include account email, IP, or other server-side
identifiers in the prompt.

Cost control
------------

Both endpoints route to the cheapest model in the per-tier matrix
(see :class:`crp_comply.api.model_router.ModelRouter`) and cap output
tokens to 600. A misuse-resistant 60-call/day floor is enforced via
the standard :func:`meter_call` dependency.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from ..recipes import list_builtin_recipes, load_recipe, recommend_recipes
from .auth import Tier
from .deps import get_current_tier, get_current_user, meter_call

logger = logging.getLogger("crp_comply.api.onboarding")

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


# ── Schemas ──────────────────────────────────────────────────────


class OnboardingExtractRequest(BaseModel):
    text: str = Field(..., min_length=4, max_length=4000)
    locale: str | None = Field(default=None, max_length=8)


class OnboardingExtractResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    suggested_profile: dict[str, Any] = Field(default_factory=dict)
    rationale: str = ""
    confidence: float = 0.0
    clarifying_question: str = ""
    next_fields: list[str] = Field(default_factory=list)


class OnboardingSuggestRequest(BaseModel):
    profile: dict[str, Any] = Field(default_factory=dict)


class OnboardingSuggestResponse(BaseModel):
    next_question: str
    next_field: str
    options: list[str] = Field(default_factory=list)
    why_it_matters: str = ""
    recipes_unlocked_if_answered: list[str] = Field(default_factory=list)


class OnboardingQuickRequest(BaseModel):
    """Three-question microsurvey payload.

    The frontend asks one question each for role, jurisdiction, and system
    type, then the backend deterministically maps those answers onto the
    canonical OrgProfile fields and recommends the most relevant recipes.
    """

    actor: str = Field(..., min_length=1, max_length=40)
    jurisdictions: list[str] = Field(default_factory=list)
    system_types: list[str] = Field(default_factory=list)
    org_name: str | None = Field(default=None, max_length=200)


class RecommendedRecipe(BaseModel):
    recipe_id: str
    title: str
    should_produce: bool | str
    why: str


class OnboardingQuickResponse(BaseModel):
    profile: dict[str, Any]
    classification: str
    recommended_recipes: list[RecommendedRecipe]
    checklist: list[str]


# ── Profile schema (mirrors frontend/src/lib/profile.tsx OrgProfile) ──

_BOOL_FIELDS = (
    "established_in_eu",
    "is_high_risk",
    "is_gpai",
    "is_gpai_systemic",
    "processes_personal_data",
    "special_categories",
    "biometric",
    "is_chatbot",
    "synthetic_content",
    "emotion_recognition",
    "deepfake",
    "automated_decision_making",
    "children_users",
    "iso_42001_certified",
    "iso_27001_certified",
    "soc2_certified",
)
_STR_FIELDS = ("org_name", "actor", "system_category", "annex_iii_row")
_LIST_FIELDS = ("jurisdictions",)
_ALL_FIELDS = _BOOL_FIELDS + _STR_FIELDS + _LIST_FIELDS

_ALLOWED_ACTORS = {
    "provider",
    "deployer",
    "importer",
    "distributor",
    "authorised_representative",
    "gpai_provider",
}


# ── System prompt (carefully scoped, no copyrighted text) ──

_SYSTEM_PROMPT = """You are an EU AI compliance onboarding assistant.

Your one job is to turn a short free-text description of a business
into structured fields for the OrgProfile schema below. You MUST:

* Output STRICT JSON matching the response schema. No prose outside JSON.
* Only fill fields you are clearly confident about from the user's text.
  Leave anything ambiguous as null/empty — do NOT guess.
* Set ``confidence`` realistically: 1.0 = explicit in text, 0.5 = strong
  inference, 0.2 = guess. If lower than 0.4 leave the field empty.
* Pick exactly ONE follow-up ``clarifying_question`` that, if answered,
  would most increase the number of EU AI Act / GDPR / NIS2 obligations
  we can correctly tailor for this business. Phrase it in plain English
  with NO jargon — never say "Annex III", "GPAI", "actor role".

OrgProfile fields you may set:

* org_name: string
* actor: one of {"provider","deployer","importer","distributor",
                  "authorised_representative","gpai_provider"}
* established_in_eu: bool
* jurisdictions: list of ISO codes ("EU","UK","US","CA","AU",...)
* system_category: short string (e.g. "credit-scoring","content-moderation",
                                   "medical-imaging","HR-screening")
* annex_iii_row: free-form short string only if user explicitly says it
* is_high_risk: bool — true ONLY if user says "high-risk" or describes
  one of: biometrics, critical infrastructure, education, employment,
  essential services, law enforcement, migration, justice
* is_gpai: bool — true if they say "general-purpose model" or "foundation model"
* is_gpai_systemic: bool — true ONLY if they say >10^25 FLOPs or systemic
* processes_personal_data: bool
* special_categories: bool — health, biometric, ethnic origin, etc.
* biometric: bool
* is_chatbot: bool
* synthetic_content: bool — they generate text/image/video output
* emotion_recognition: bool
* deepfake: bool
* automated_decision_making: bool
* children_users: bool
* iso_42001_certified, iso_27001_certified, soc2_certified: bool

Output JSON shape:
{
  "suggested_profile": { ...subset of fields above, only what's confident... },
  "rationale": "1-2 sentences explaining what you inferred and why",
  "confidence": 0.0-1.0 (overall),
  "clarifying_question": "plain-English next question",
  "next_fields": ["field_a","field_b"] (which fields the question targets)
}
"""


def _coerce_profile(raw: dict[str, Any]) -> dict[str, Any]:
    """Defensively coerce LLM output to the OrgProfile schema.

    The LLM is fast but not perfectly schema-compliant. We strip
    unknown keys, coerce booleans, and reject suspicious values.
    """
    out: dict[str, Any] = {}
    if not isinstance(raw, dict):
        return out
    for k in _ALL_FIELDS:
        if k not in raw:
            continue
        v = raw[k]
        if v in (None, "", [], {}):
            continue
        if k in _BOOL_FIELDS:
            if isinstance(v, bool):
                out[k] = v
            elif isinstance(v, str):
                out[k] = v.strip().lower() in ("true", "yes", "1")
        elif k in _STR_FIELDS:
            if isinstance(v, str) and v.strip():
                s = v.strip()
                if k == "actor" and s not in _ALLOWED_ACTORS:
                    continue
                out[k] = s[:200]
        elif k in _LIST_FIELDS:
            if isinstance(v, list):
                out[k] = [str(x).strip()[:8] for x in v if isinstance(x, str)][:20]
    return out


# ── Endpoints ────────────────────────────────────────────────────


@router.post("/extract", response_model=OnboardingExtractResponse)
async def extract_profile(
    req: OnboardingExtractRequest,
    user: Annotated[str, Depends(get_current_user)],
    tier: Annotated[Tier, Depends(get_current_tier)],
    _meter: Annotated[None, Depends(meter_call("onboarding-extract"))],
) -> OnboardingExtractResponse:
    """Run the LLM extractor over the user's free-text business description.

    Returns suggested OrgProfile fields + a follow-up question chosen
    to maximise next-step recipe applicability.
    """
    # Free tier: previously returned an empty stub, which made the entire
    # onboarding wizard feel "AI-enhanced for paid users only" and was the
    # #1 source of new-user frustration ("the wizard is just a form").
    # We now run the same extraction but with a tighter token cap and a
    # per-IP-style cap on call frequency at the LLM facade level — the
    # cost of one extraction call (≈600 input tokens, 400 output) is far
    # below the cost of losing a free-tier user to a worse first impression.
    free_tier_call = tier.value == Tier.FREE.value
    free_max_tokens = 400

    try:
        from ..agent.llm import ComplianceLLM

        llm = ComplianceLLM.for_user(
            user if isinstance(user, str) else None,
            default_max_tokens=free_max_tokens if free_tier_call else 600,
        )
    except Exception as exc:
        logger.warning("onboarding extract: LLM unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI onboarding temporarily unavailable; please complete the form manually.",
        )

    messages: list[dict[str, str]] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": req.text.strip()[:4000]},
    ]

    try:
        # CRITICAL: llm.chat() is synchronous. For the "local_worker" provider
        # it bridges to the SDK WebSocket relay via
        # ``WorkerRegistry.dispatch_from_sync``, which schedules a coroutine on
        # *this same* event loop and then blocks the calling thread waiting for
        # it (``future.result(timeout=...)``). Calling it directly from this
        # async route handler would freeze the loop that the scheduled
        # coroutine itself needs to run on — a guaranteed deadlock that stalls
        # every other request on the process (not just this one) until the
        # internal timeout fires. ``asyncio.to_thread`` runs the blocking call
        # on a worker thread instead, exactly like ``_run_agent_async`` does
        # for the main agent path.
        text = await asyncio.to_thread(llm.chat, messages, temperature=0.1)
    except Exception as exc:  # noqa: BLE001
        logger.warning("onboarding extract: LLM call failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI onboarding temporarily unavailable; please complete the form manually.",
        )

    payload = _strip_to_json(text)
    if not payload:
        # Graceful degradation — surface SOME progress.
        return OnboardingExtractResponse(
            rationale="Could not parse the AI response; please continue manually.",
            confidence=0.0,
            clarifying_question="Where do you operate? (EU, UK, US, ...)",
            next_fields=["jurisdictions"],
        )

    suggested = _coerce_profile(payload.get("suggested_profile") or {})
    return OnboardingExtractResponse(
        suggested_profile=suggested,
        rationale=str(payload.get("rationale") or "")[:500],
        confidence=float(payload.get("confidence") or 0.0),
        clarifying_question=str(payload.get("clarifying_question") or "")[:400],
        next_fields=[str(f)[:40] for f in (payload.get("next_fields") or []) if isinstance(f, str)][
            :5
        ],
    )


@router.post("/suggest", response_model=OnboardingSuggestResponse)
async def suggest_next_question(
    req: OnboardingSuggestRequest,
    user: Annotated[str, Depends(get_current_user)],
    tier: Annotated[Tier, Depends(get_current_tier)],
    _meter: Annotated[None, Depends(meter_call("onboarding-suggest"))],
) -> OnboardingSuggestResponse:
    """Pick the next-best onboarding question.

    Strategy: enumerate built-in recipes, run :func:`recommend_recipes`
    against the current profile, surface the *missing* required input
    that is referenced by the largest number of currently-non-applicable
    recipes. This makes onboarding adaptive: we don't ask about ISO 42001
    certification first if their primary gap is jurisdictional scope.
    """
    profile = _coerce_profile(req.profile)

    try:
        recipes = list_builtin_recipes()
    except Exception as exc:  # noqa: BLE001
        logger.warning("onboarding suggest: recipe enumeration failed: %s", exc)
        recipes = []

    plans = []
    if recipes:
        try:
            plans = recommend_recipes(recipes, profile)
        except Exception as exc:  # noqa: BLE001
            logger.warning("onboarding suggest: recommend_recipes failed: %s", exc)

    # Tally clarification-question hits across non-applicable plans.
    field_hits: dict[str, list[str]] = {}
    for plan in plans:
        # ``TailoringPlan`` exposes ``recipe_id`` + ``clarification_questions``
        # (list[str]) + ``applicable`` bool. Tolerate dict-shaped fallbacks.
        applicable = getattr(plan, "applicable", None)
        if applicable is None and isinstance(plan, dict):
            applicable = plan.get("applicable")
        if applicable is True:
            continue
        rid = (
            getattr(plan, "recipe_id", None)
            or (plan.get("recipe_id") if isinstance(plan, dict) else None)
            or ""
        )
        questions = getattr(plan, "clarification_questions", None)
        if questions is None and isinstance(plan, dict):
            questions = plan.get("clarification_questions") or []
        for q in questions or []:
            field_hits.setdefault(_question_to_field(q), []).append(rid)

    # Always prioritise jurisdictions and actor — they cascade everywhere.
    priority = [
        "jurisdictions",
        "actor",
        "processes_personal_data",
        "is_high_risk",
        "is_gpai",
        "system_category",
    ]
    for f in priority:
        if f not in profile and f in field_hits:
            return _question_for(f, field_hits.get(f, []))
    # Fallback: the field referenced by the most recipes.
    if field_hits:
        f, recs = max(field_hits.items(), key=lambda kv: len(kv[1]))
        return _question_for(f, recs)
    # Cold start.
    return _question_for("jurisdictions", [])


# ── 60-second microsurvey ───────────────────────────────────────


_SYSTEM_TYPE_FLAGS: dict[str, dict[str, Any]] = {
    "high_risk": {"is_high_risk": True},
    "gpai": {"is_gpai": True},
    "chatbot": {"is_chatbot": True},
    "personal_data": {"processes_personal_data": True},
    "synthetic_content": {"synthetic_content": True},
    "biometric": {"biometric": True, "emotion_recognition": True},
    "automated_decision": {"automated_decision_making": True},
    "children": {"children_users": True},
    "special_categories": {"special_categories": True},
    "deepfake": {"deepfake": True},
}


def _system_category_from_types(types: list[str]) -> str:
    if "biometric" in types:
        return "biometric identification"
    if "chatbot" in types:
        return "chatbot / AI assistant"
    if "high_risk" in types:
        return "high-risk AI system"
    if "gpai" in types:
        return "general-purpose AI model"
    if "synthetic_content" in types or "deepfake" in types:
        return "synthetic content generation"
    return "AI system"


def _actor_label(actor: str) -> str:
    return {
        "provider": "Provider",
        "deployer": "Deployer",
        "importer": "Importer",
        "distributor": "Distributor",
        "authorised_representative": "Authorised representative",
        "gpai_provider": "GPAI provider",
    }.get(actor, actor.replace("_", " ").title())


def _classify(profile: dict[str, Any]) -> str:
    actor = _actor_label(profile.get("actor") or "provider")
    jurisdictions = profile.get("jurisdictions") or []
    location = ", ".join(jurisdictions) if jurisdictions else "unspecified region"
    category = profile.get("system_category") or "AI system"
    return f"{actor} in {location} building a {category}"


@router.post("/quick", response_model=OnboardingQuickResponse)
async def quick_onboarding(
    req: OnboardingQuickRequest,
    user: Annotated[str, Depends(get_current_user)],
    tier: Annotated[Tier, Depends(get_current_tier)],
    _meter: Annotated[None, Depends(meter_call("onboarding-quick"))],
) -> OnboardingQuickResponse:
    """Deterministic onboarding from a 3-question microsurvey.

    Maps plain-English answers to OrgProfile fields, runs the recipe
    tailoring engine, and returns a classification + recommended next
    steps. No LLM is used, so the result is instant and free-tier safe.
    """
    actor = req.actor.strip()
    if actor not in _ALLOWED_ACTORS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid actor: {actor}",
        )

    jurisdictions = sorted(
        {str(j).strip().upper()[:8] for j in req.jurisdictions if str(j).strip()}
    )

    profile: dict[str, Any] = {
        "actor": actor,
        "jurisdictions": jurisdictions,
        "established_in_eu": "EU" in jurisdictions,
    }
    if req.org_name:
        profile["org_name"] = req.org_name.strip()[:200]

    selected_types = [t for t in req.system_types if isinstance(t, str)]
    for t in selected_types:
        profile.update(_SYSTEM_TYPE_FLAGS.get(t, {}))
    profile["system_category"] = _system_category_from_types(selected_types)

    recipes: list[Any] = []
    try:
        recipes = [load_recipe(rid) for rid in list_builtin_recipes()]
    except Exception as exc:
        logger.warning("quick onboarding: recipe load failed: %s", exc)

    recommended: list[RecommendedRecipe] = []
    if recipes:
        try:
            plans = recommend_recipes(recipes, profile)
        except Exception as exc:
            logger.warning("quick onboarding: recommend_recipes failed: %s", exc)
            plans = []
        for plan in plans:
            if plan.should_produce is False:
                continue
            try:
                recipe = load_recipe(plan.recipe_id)
                title = recipe.title
            except Exception:
                title = plan.recipe_id
            recommended.append(
                RecommendedRecipe(
                    recipe_id=plan.recipe_id,
                    title=title,
                    should_produce=plan.should_produce,
                    why=plan.why,
                )
            )
            if len(recommended) >= 6:
                break

    checklist: list[str] = []
    if recommended:
        checklist.append("Review your recommended deliverables below")
        for rec in recommended[:3]:
            checklist.append(f"Prepare {rec.title}")
    else:
        checklist.append("Explore the deliverable catalogue")
    checklist.append("Complete your organisation profile in Settings")
    checklist.append("Generate your first compliance report")

    return OnboardingQuickResponse(
        profile=_coerce_profile(profile),
        classification=_classify(profile),
        recommended_recipes=recommended,
        checklist=checklist,
    )


# ── Helpers ──────────────────────────────────────────────────────


def _strip_to_json(text: str) -> dict[str, Any] | None:
    """Find and parse the first balanced JSON object in ``text``.

    LLMs sometimes wrap the JSON in ``\u0060\u0060\u0060json`` fences or add a
    leading explainer paragraph. We tolerate both.
    """
    if not text:
        return None
    s = text.strip()
    # Strip fenced blocks.
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s.rsplit("```", 1)[0]
    # Find first '{' and balance braces.
    i = s.find("{")
    if i < 0:
        return None
    depth = 0
    for j in range(i, len(s)):
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(s[i : j + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _question_to_field(question: str) -> str:
    """Map a recipe's clarification question text to an OrgProfile field.

    The mapping is intentionally loose-and-lossy — recipes don't expose
    structured field IDs in their clarifications today (gap noted in
    RECIPE_COVERAGE_TRACKER.md), so we keyword-match.
    """
    q = (question or "").lower()
    if any(w in q for w in ("jurisdiction", "operate", "country", "region")):
        return "jurisdictions"
    if any(w in q for w in ("provider", "deployer", "importer", "role")):
        return "actor"
    if any(w in q for w in ("personal data", "gdpr", "data subject")):
        return "processes_personal_data"
    if "high-risk" in q or "high risk" in q:
        return "is_high_risk"
    if any(w in q for w in ("gpai", "general-purpose", "foundation")):
        return "is_gpai"
    if any(w in q for w in ("biometric",)):
        return "biometric"
    if any(w in q for w in ("chatbot",)):
        return "is_chatbot"
    if any(w in q for w in ("synthetic", "deepfake")):
        return "synthetic_content"
    return "system_category"


_FIELD_COPY: dict[str, dict[str, Any]] = {
    "jurisdictions": {
        "question": "Where do you operate? (Pick all that apply.)",
        "options": ["EU", "UK", "US", "CA", "AU", "Other"],
        "why": "Determines which regimes apply (EU AI Act, UK regulator guidance, US sectoral law).",
    },
    "actor": {
        "question": "Which best describes your role with the AI system?",
        "options": [
            "We build it (provider)",
            "We use one we bought (deployer)",
            "We import or distribute it",
            "We provide a foundation/general-purpose model",
        ],
        "why": "EU AI Act splits obligations differently for providers vs. deployers.",
    },
    "processes_personal_data": {
        "question": "Does the system process information about identifiable people?",
        "options": ["Yes", "No", "Not sure"],
        "why": "Triggers GDPR + DPIA + records-of-processing obligations.",
    },
    "is_high_risk": {
        "question": "Is the system used in any of these areas: hiring, credit, healthcare, education, law enforcement, biometrics, critical infrastructure?",
        "options": ["Yes", "No", "Not sure"],
        "why": "These areas are 'high-risk' under EU AI Act Annex III with stricter conformity duties.",
    },
    "is_gpai": {
        "question": "Are you building or fine-tuning a general-purpose / foundation model?",
        "options": ["Yes", "No"],
        "why": "GPAI providers have a separate set of obligations (Article 53 / 55).",
    },
    "biometric": {
        "question": "Does the system identify or categorise people using biometric features (face, voice, gait)?",
        "options": ["Yes", "No"],
        "why": "Biometric uses are heavily restricted and may be high-risk or prohibited.",
    },
    "is_chatbot": {
        "question": "Does the system interact with people as a chatbot or AI assistant?",
        "options": ["Yes", "No"],
        "why": "Triggers transparency duties under EU AI Act Art. 50.",
    },
    "synthetic_content": {
        "question": "Does the system generate text, image, audio, or video output?",
        "options": ["Yes", "No"],
        "why": "Generated content must be machine-readably labelled as AI-generated.",
    },
    "system_category": {
        "question": "In one phrase, what does the system do?",
        "options": [],
        "why": "Helps us pick the right Annex III row and sectoral rules.",
    },
}


def _question_for(field: str, recipes_unlocked: list[str]) -> OnboardingSuggestResponse:
    spec = _FIELD_COPY.get(field, _FIELD_COPY["system_category"])
    return OnboardingSuggestResponse(
        next_question=spec["question"],
        next_field=field,
        options=list(spec["options"]),
        why_it_matters=spec["why"],
        recipes_unlocked_if_answered=sorted(set(recipes_unlocked))[:8],
    )


__all__ = ["router"]
