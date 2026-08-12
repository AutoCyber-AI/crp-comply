# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Recipes API — list and execute deliverable recipes.

Endpoints
---------

``GET  /api/v1/recipes``
    List all built-in recipes (id, title, regulation, required_inputs).
``GET  /api/v1/recipes/{recipe_id}``
    Return a single recipe's public manifest.
``POST /api/v1/recipes/{recipe_id}/run``
    Execute a recipe against the caller's agent session and return
    ``{markdown, json, section_citations, warnings}``.

Recipe execution is gated to paid tiers only (Pro+). Free tier callers
receive a ``402 Payment Required`` redirecting to the template endpoints.
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
from typing import Annotated, Any, AsyncGenerator, Callable

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from ..recipes import (
    RecipeRunner,
    RecipeOutput,
    enumerate_human_inputs,
    list_builtin_recipes,
    load_recipe,
    recommend_recipes,
    tailor_recipe,
    tailor_recipe_dynamic,
)
from ..org_profile import get_org_profile_store
from .auth import Tier
from .deps import get_current_tenant, get_current_tier, get_current_user, meter_call
from .reports import get_report_store

logger = logging.getLogger("crp_comply.api.recipes")

router = APIRouter(prefix="/recipes", tags=["recipes"])


_PAID_TIERS = frozenset(
    {
        Tier.PRO.value,
        Tier.SCALE.value,
        Tier.ENTERPRISE.value,
        Tier.CLOUD.value,
    }
)


def _require_paid(tier: Tier) -> None:
    if tier.value not in _PAID_TIERS:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                "Recipes are a paid-tier feature. "
                "Upgrade at /billing or use the free /api/v1/reports/* endpoints."
            ),
        )


# ── Response models ──────────────────────────────────────────


class RecipeSummary(BaseModel):
    recipe_id: str
    title: str
    regulation: str
    version: str
    description: str = ""
    required_inputs: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class RecipeManifest(RecipeSummary):
    sections: list[dict[str, Any]] = Field(default_factory=list)
    ckf_queries: list[str] = Field(default_factory=list)
    tools_allowed: list[str] = Field(default_factory=list)
    output_format: str = "markdown"


class RecipeRunRequest(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    profile: dict[str, Any] | None = None
    autonomy: str = Field(
        default="",
        max_length=40,
        description=(
            "User-selected autonomy level: suggest | draft | "
            "autonomous_with_checkpoints | full. Maps to the agent's "
            "Policy Enforcement Point mode."
        ),
    )
    #: Optional post-run notification. When set, the dispatcher rings the
    #: user's preferred channel with a "your deliverable is ready" message
    #: once the recipe finishes. Priority defaults to ``medium``; use
    #: ``high`` to force in-app chat fan-out.
    notify: dict[str, Any] | None = None


class TailorRequest(BaseModel):
    profile: dict[str, Any] = Field(default_factory=dict)


class SkippedSectionDTO(BaseModel):
    section_id: str
    title: str
    reason: str
    rule: str = ""


class ApplicableSectionDTO(BaseModel):
    id: str
    title: str
    citations: list[str] = Field(default_factory=list)


class TailoringPlanDTO(BaseModel):
    recipe_id: str
    # Tri-state: ``True`` / ``False`` / ``"uncertain"`` for dynamic plans.
    should_produce: bool | str
    why: str
    purpose: str = ""
    triggers: list[str] = Field(default_factory=list)
    deadline: str = ""
    actors: list[str] = Field(default_factory=list)
    applicable_sections: list[ApplicableSectionDTO] = Field(default_factory=list)
    skipped_sections: list[SkippedSectionDTO] = Field(default_factory=list)
    profile_keys_used: list[str] = Field(default_factory=list)
    pending_questions: list[dict[str, Any]] = Field(default_factory=list)


class DynamicPlanRequest(BaseModel):
    """Request body for the dynamic ``/plan`` endpoint.

    ``profile`` holds whatever the caller already knows. Missing keys
    will be surfaced as ``pending_questions`` rather than silently
    treated as False.
    """

    profile: dict[str, Any] = Field(default_factory=dict)
    user_id: str | None = None


class RecipeRunResponse(BaseModel):
    recipe_id: str
    title: str
    regulation: str
    markdown: str
    json_payload: dict[str, Any] = Field(default_factory=dict, alias="json")
    section_citations: dict[str, list[str]] = Field(default_factory=dict)
    duration_ms: int = 0
    warnings: list[str] = Field(default_factory=list)
    #: Populated when a run completes with outstanding human-input items
    #: (missing required inputs, unanswered ask_when_unknown, etc.). The
    #: RecipeRunner also auto-dispatches a HIGH-priority notification for
    #: each item so the user's chat rings even if they close the browser.
    pending_human_inputs: list[dict[str, Any]] = Field(default_factory=list)
    #: Derivation manifest (Gap #7) — binds the deliverable to the
    #: exact evidence that produced it so callers can detect staleness.
    #: Empty until the runner has computed inputs/profile/artefact hashes.
    derivation: dict[str, Any] = Field(default_factory=dict)
    report_id: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class HumanInputDTO(BaseModel):
    key: str
    question: str
    source: str
    priority: str = "medium"
    context: str = ""
    citation: str = ""
    fact_key: str = ""
    answer_type: str = "text"
    options: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    recipe_id: str = ""
    section_id: str = ""


class HumanInputsRequest(BaseModel):
    profile: dict[str, Any] = Field(default_factory=dict)
    inputs: dict[str, Any] = Field(default_factory=dict)


# ── Endpoints ────────────────────────────────────────────────


@router.get("", response_model=list[RecipeSummary], summary="List built-in recipes")
async def list_recipes() -> list[RecipeSummary]:
    out: list[RecipeSummary] = []
    for rid in list_builtin_recipes():
        try:
            r = load_recipe(rid)
        except Exception as exc:  # pragma: no cover — skip broken recipes
            logger.warning("skipping broken recipe %s: %s", rid, exc)
            continue
        out.append(
            RecipeSummary(
                recipe_id=r.recipe_id,
                title=r.title,
                regulation=r.regulation,
                version=r.version,
                description=r.description,
                required_inputs=r.required_inputs,
                tags=r.tags,
            )
        )
    return out


@router.get(
    "/{recipe_id}",
    response_model=RecipeManifest,
    summary="Get a recipe's public manifest",
)
async def get_recipe(recipe_id: str) -> RecipeManifest:
    try:
        r = load_recipe(recipe_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RecipeManifest(
        recipe_id=r.recipe_id,
        title=r.title,
        regulation=r.regulation,
        version=r.version,
        description=r.description,
        required_inputs=r.required_inputs,
        tags=r.tags,
        ckf_queries=r.ckf_queries,
        tools_allowed=r.tools_allowed,
        output_format=r.output_format,
        sections=[
            {
                "id": s.id,
                "title": s.title,
                "citations": s.citations,
                "word_budget": s.word_budget,
            }
            for s in r.sections
        ],
    )


# Module-level factory override so tests can inject a deterministic runner.
_runner_factory_override: Any = None


def _build_completion_notifier(*, user_id: str, notify: dict[str, Any]) -> Any:
    """Build a post-run hook that dispatches a "recipe ready" notification.

    ``notify`` keys: email, phone_e164, preferred_channel, webhook_url,
    priority (high|medium|low), subject (optional), cta_url (optional).
    Missing fields are filled in from the tenant's stored contact
    profile so a one-line ``{"notify": {}}`` still reaches the user.
    """
    from ..notifications import (
        Notification,
        NotificationPriority,
        UserContactProfile,
    )
    from .notifications import get_dispatcher

    def _hook(output: Any, _inputs: dict[str, Any]) -> None:
        try:
            priority = NotificationPriority(str(notify.get("priority") or "medium").lower())
        except ValueError:
            priority = NotificationPriority.MEDIUM

        # Start from the stored tenant profile (resolves email / phone /
        # preferred_channel without needing them in every request), then
        # let the request body override field-by-field.
        try:
            from ..contacts import get_contact_store
            from .deps import get_auth

            tenant_id = get_auth().get_tenant_id(user_id)
            base = get_contact_store().get_or_default(tenant_id)
            profile = UserContactProfile(
                user_id=tenant_id,
                email=base.email,
                phone_e164=base.phone_e164,
                preferred_channel=base.preferred_channel,
                webhook_url=base.webhook_url,
                full_name=base.full_name,
                timezone=base.timezone,
                language=base.language,
            )
        except Exception:  # pragma: no cover — contacts store optional
            profile = UserContactProfile(user_id=user_id, email="")

        for fld in (
            "email",
            "phone_e164",
            "preferred_channel",
            "webhook_url",
            "full_name",
        ):
            val = notify.get(fld)
            if val:
                setattr(profile, fld, str(val))
        subject = str(notify.get("subject") or f"Your deliverable is ready — {output.title}")
        body = (
            f"The '{output.title}' ({output.regulation}) has finished drafting. "
            f"Duration: {output.duration_ms} ms. "
            f"{len(output.warnings)} warning(s)."
        )
        n = Notification(
            kind="evidence_ready",
            subject=subject,
            body=body,
            priority=priority,
            ring=priority == NotificationPriority.HIGH,
            cta_label="Open deliverable",
            cta_url=str(notify.get("cta_url") or ""),
            metadata={
                "recipe_id": output.recipe_id,
                "duration_ms": output.duration_ms,
                "warning_count": len(output.warnings),
            },
        )
        get_dispatcher().dispatch(user=profile, notification=n)

    return _hook


def _default_runner_factory(user_id: str, autonomy: str | None = None) -> RecipeRunner:
    """Build a RecipeRunner bound to the caller's compliance agent.

    Deferred import avoids circulars and keeps agent startup cost out of
    the recipes list endpoint.
    """
    from .agent import _build_agent  # type: ignore

    agent = _build_agent(user_id=user_id, max_iters=6, autonomy=autonomy)

    def derivation_provider(_recipe, _provided):  # type: ignore[no-untyped-def]
        """Snapshot the evidence that produced this draft (Gap #7).

        We swallow individual lookup failures so the recipe still ships
        when the artefact store / proxy interceptor are unavailable —
        the manifest then degrades gracefully to a profile-only hash.
        """
        artefact_index: dict[str, str] = {}
        proxy_window: dict[str, Any] = {}
        corpus_manifest_hash = ""

        try:
            from .artefacts import get_artefact_store

            for art in get_artefact_store().list(user_id):
                sha = (
                    art.get("sha256") if isinstance(art, dict) else getattr(art, "sha256", "")
                ) or ""
                aid = (art.get("id") if isinstance(art, dict) else getattr(art, "id", "")) or ""
                if sha and aid:
                    artefact_index[aid] = sha
        except Exception as exc:  # pragma: no cover — optional substrate
            logger.debug("artefact snapshot failed for derivation: %s", exc)

        try:
            from ..proxy.routes import _get_interceptor

            stats = _get_interceptor().get_compliance_stats(user_id)
            if stats is not None:
                proxy_window = stats.model_dump() if hasattr(stats, "model_dump") else dict(stats)
        except Exception as exc:  # pragma: no cover — optional substrate
            logger.debug("proxy snapshot failed for derivation: %s", exc)

        try:
            from pathlib import Path
            import hashlib

            manifest_path = Path("corpus") / "_scraped" / "manifest.json"
            if manifest_path.exists():
                corpus_manifest_hash = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        except Exception as exc:  # pragma: no cover — best effort
            logger.debug("corpus manifest hash skipped: %s", exc)

        return {
            "artefact_index": artefact_index,
            "proxy_window": proxy_window,
            "corpus_manifest_hash": corpus_manifest_hash,
        }

    return RecipeRunner(agent=agent, derivation_provider=derivation_provider)


def _build_runner(user_id: str, autonomy: str | None = None) -> RecipeRunner:
    if _runner_factory_override is not None:
        return _runner_factory_override(user_id)
    return _default_runner_factory(user_id, autonomy=autonomy)


def _dispatch_human_input_notifications(
    *,
    tenant_id: str,
    recipe_title: str,
    recipe_id: str,
    requirements: list[Any],
    notify_override: dict[str, Any] | None = None,
) -> None:
    """Ring the tenant's preferred channel for each outstanding input.

    The contact store (persisted per-tenant) is the source of truth for
    *where* to send. A request-scoped ``notify_override`` wins field-by-
    field so a one-off call can still supply an email without mutating
    the stored profile.

    Exceptions are logged and swallowed — missing inputs are a user-
    visible signal regardless of delivery success.
    """
    if not requirements:
        return
    try:
        from ..contacts import get_contact_store
        from ..notifications import (
            Notification,
            NotificationPriority,
            UserContactProfile,
        )
        from .notifications import get_dispatcher

        try:
            store = get_contact_store()
            profile = store.get_or_default(tenant_id)
        except Exception:  # pragma: no cover — store not initialised
            profile = UserContactProfile(user_id=tenant_id, email="")

        # Apply per-request overrides (email, phone_e164, etc.)
        if notify_override:
            for fld in (
                "email",
                "full_name",
                "phone_e164",
                "preferred_channel",
                "webhook_url",
            ):
                val = notify_override.get(fld)
                if val:
                    setattr(profile, fld, str(val))

        # Guarantee the tenant id — overrides cannot change the inbox key.
        profile.user_id = tenant_id

        dispatcher = get_dispatcher()
        for req in requirements:
            prio = (
                NotificationPriority.HIGH
                if req.priority == "high"
                else NotificationPriority.MEDIUM
                if req.priority == "medium"
                else NotificationPriority.LOW
            )
            subject = f"Action needed: {recipe_title} — {req.key}"
            body_lines = [req.question]
            if req.context:
                body_lines.append("")
                body_lines.append(f"Why we're asking: {req.context}")
            if req.citation:
                body_lines.append(f"Citation: {req.citation}")
            if req.options:
                body_lines.append("Options: " + ", ".join(req.options))
            body = "\n".join(body_lines)
            n = Notification(
                kind="human_input_required",
                subject=subject,
                body=body,
                priority=prio,
                ring=prio == NotificationPriority.HIGH,
                cta_label="Answer now",
                metadata={
                    "recipe_id": recipe_id,
                    "fact_key": req.fact_key or req.key,
                    "section_id": req.section_id,
                    "source": req.source,
                    "answer_type": req.answer_type,
                    "options": list(req.options),
                },
            )
            dispatcher.dispatch(user=profile, notification=n)
    except Exception as exc:  # pragma: no cover
        logger.warning("human-input dispatch failed: %s", exc)


@router.post(
    "/{recipe_id}/human-inputs",
    response_model=list[HumanInputDTO],
    summary="Enumerate every outstanding human input / confirmation for a recipe",
)
async def list_human_inputs(
    recipe_id: str,
    req: HumanInputsRequest,
    _tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> list[HumanInputDTO]:
    """Returns the full list of items the human still has to answer.

    Safe to call anonymously at low tiers (no LLM spend) so the UI can
    render a "before you start" checklist pre-login.
    """
    try:
        recipe = load_recipe(recipe_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    items = enumerate_human_inputs(
        recipe,
        profile=req.profile or {},
        inputs=req.inputs or {},
    )
    return [HumanInputDTO(**r.to_dict()) for r in items]


def _recipe_response(
    out: RecipeOutput,
    pending: list[Any],
    report_id: str | None,
) -> RecipeRunResponse:
    """Build the public RecipeRunResponse from executor output."""
    return RecipeRunResponse(
        recipe_id=out.recipe_id,
        title=out.title,
        regulation=out.regulation,
        markdown=out.markdown,
        json_payload=out.json_payload,
        section_citations=out.section_citations,
        duration_ms=out.duration_ms,
        warnings=out.warnings,
        pending_human_inputs=[r.to_dict() for r in pending],
        derivation=out.derivation,
        report_id=report_id,
    )


def _execute_recipe(
    recipe_id: str,
    req: RecipeRunRequest,
    user_id: str,
    tenant_id: str,
    tier: Tier,
    on_section: Callable[[dict[str, Any]], None] | None = None,
    autonomy: str | None = None,
) -> tuple[RecipeOutput, list[Any], str | None]:
    """Synchronous recipe execution pipeline shared by JSON and SSE endpoints."""
    try:
        recipe = load_recipe(recipe_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # If the caller did not supply a profile, fall back to the stored
    # OrgProfile (tenant-scoped first, then user-scoped).
    profile = req.profile or {}
    if not profile:
        try:
            store = get_org_profile_store()
            profile = store.get(tenant_id) or store.get(user_id) or {}
        except Exception:
            logger.debug("OrgProfile store unavailable for recipe run", exc_info=True)
            profile = {}

    # Enumerate outstanding human-input items BEFORE anything else can
    # fail. Required-input gaps still raise ValueError inside the runner,
    # so this list primarily surfaces recipe- and section-level
    # clarifications the caller hasn't answered yet — plus any
    # ``required_inputs`` that made it past the DSL (belt-and-braces).
    pending = enumerate_human_inputs(
        recipe,
        profile=profile,
        inputs=req.inputs or {},
    )

    # Auto-dispatch notifications so the user is alerted even when the
    # run itself fails — a missing LLM config or a bad runner factory
    # must NOT silently swallow the human-input prompts. This happens
    # before ``_build_runner`` on purpose: the inbox is the user's
    # durable channel and has to populate regardless of runtime state.
    _dispatch_human_input_notifications(
        tenant_id=tenant_id,
        recipe_title=recipe.title,
        recipe_id=recipe.recipe_id,
        requirements=pending,
        notify_override=req.notify,
    )

    try:
        runner = _build_runner(user_id, autonomy=autonomy)
    except Exception as exc:
        logger.exception("recipe runner factory failed")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Recipe runtime unavailable: {exc}",
        ) from exc

    # Install a completion-notification hook when the caller provided a
    # ``notify`` block. The hook rings the user's preferred channel with
    # a "your deliverable is ready" message. Failures never block the run.
    if req.notify:
        runner.notifier = _build_completion_notifier(user_id=user_id, notify=req.notify)

    try:
        out = runner.run(
            recipe,
            inputs=req.inputs or {},
            profile=profile,
            on_section=on_section,
        )
    except ValueError as exc:  # bad inputs
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        # The agent's clarification-needed signal is a *control flow*
        # exception, not a runtime failure — surface it as 409 so the
        # caller can collect the answer and re-run with richer profile.
        try:
            from ..agent.tools import ClarificationNeeded
        except ImportError:  # pragma: no cover — agent always available in API
            ClarificationNeeded = None  # type: ignore[assignment]
        if ClarificationNeeded is not None and isinstance(exc, ClarificationNeeded):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "clarification_needed",
                    "recipe_id": recipe.recipe_id,
                    "question": exc.question,
                    "context": exc.context,
                    "priority": exc.priority,
                    "fact_key": exc.fact_key,
                    "skippable": exc.skippable,
                    "pending_human_inputs": [r.to_dict() for r in pending],
                },
            ) from exc
        logger.exception("recipe execution failed for %s", recipe_id)
        raise HTTPException(
            status_code=500,
            detail=f"Recipe execution failed: {exc}",
        ) from exc

    # Best-effort lifecycle transition: a successful draft moves the
    # obligation forward so Programme.tsx can show the right state
    # without us forcing the caller to make a second API call. Any
    # failure here is logged and swallowed — drafts must not be lost
    # because the lifecycle store hiccupped.
    try:
        from ..programme import LifecycleState, get_programme_store

        get_programme_store().transition(
            user_id=user_id,
            obligation_id=recipe.recipe_id,
            recipe_id=recipe.recipe_id,
            new_state=LifecycleState.DRAFT_READY,
            reason="recipe drafted",
            observed_evidence=True,
        )
    except Exception as exc:  # pragma: no cover — programme store optional
        logger.debug("programme transition skipped: %s", exc)

    # Persist the run as a report so Workspace can save it to the vault.
    report_id: str | None = None
    try:
        rec = get_report_store().save(
            user_id=user_id,
            kind="recipe_run",
            system_name=profile.get("system_name") or profile.get("org_name") or recipe_id,
            tier=tier.value,
            payload={
                "recipe_id": out.recipe_id,
                "title": out.title,
                "regulation": out.regulation,
                "section_citations": out.section_citations,
                "warnings": out.warnings,
                "pending_human_inputs": [r.to_dict() for r in pending],
                "derivation": out.derivation,
            },
            markdown=out.markdown,
            risk_level=None,
            derivation=out.derivation,
        )
        report_id = rec.get("id")
    except Exception as exc:
        logger.warning("failed to persist recipe run report: %s", exc)

    return out, pending, report_id


@router.post(
    "/{recipe_id}/run",
    response_model=RecipeRunResponse,
    summary="Execute a recipe and return the drafted deliverable",
    dependencies=[Depends(meter_call("recipes_run"))],
)
async def run_recipe(
    recipe_id: str,
    req: RecipeRunRequest,
    user_id: Annotated[str, Depends(get_current_user)],
    tenant_id: Annotated[str, Depends(get_current_tenant)],
    tier: Annotated[Tier, Depends(get_current_tier)],
) -> RecipeRunResponse:
    _require_paid(tier)
    out, pending, report_id = await asyncio.to_thread(
        _execute_recipe, recipe_id, req, user_id, tenant_id, tier, None, req.autonomy
    )
    return _recipe_response(out, pending, report_id)


def _sse(event: str, data: Any) -> bytes:
    return f"event: {event}\ndata: {_json.dumps(data)}\n\n".encode("utf-8")


@router.post(
    "/{recipe_id}/run/stream",
    summary="Execute a recipe and stream section-level draft events",
    dependencies=[Depends(meter_call("recipes_run"))],
)
async def run_recipe_stream(
    recipe_id: str,
    req: RecipeRunRequest,
    user_id: Annotated[str, Depends(get_current_user)],
    tenant_id: Annotated[str, Depends(get_current_tenant)],
    tier: Annotated[Tier, Depends(get_current_tier)],
) -> StreamingResponse:
    _require_paid(tier)

    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    def on_section(info: dict[str, Any]) -> None:
        try:
            queue.put_nowait({"event": "recipe.section.delta", "data": info})
        except Exception:
            # Queue full / closed — never break the runner for the UI sink.
            pass

    async def runner_task() -> RecipeRunResponse | None:
        try:
            out, pending, report_id = await asyncio.to_thread(
                _execute_recipe,
                recipe_id,
                req,
                user_id,
                tenant_id,
                tier,
                on_section,
                req.autonomy,
            )
            return _recipe_response(out, pending, report_id)
        except HTTPException as exc:
            queue.put_nowait(
                {
                    "event": "recipe.error",
                    "data": {"status_code": exc.status_code, "detail": exc.detail},
                }
            )
            return None
        except Exception as exc:
            logger.exception("recipe stream execution failed")
            queue.put_nowait(
                {
                    "event": "recipe.error",
                    "data": {"status_code": 500, "detail": f"Recipe execution failed: {exc}"},
                }
            )
            return None
        finally:
            queue.put_nowait(None)

    task = asyncio.create_task(runner_task())

    async def event_generator() -> AsyncGenerator[bytes, None]:
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield _sse(item["event"], item["data"])
            if task.done():
                result = task.result()
                if result is not None:
                    yield _sse("recipe.done", result.model_dump())
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post(
    "/{recipe_id}/tailor",
    response_model=TailoringPlanDTO,
    summary="Tailor a recipe to a user profile (no LLM call)",
)
async def tailor_recipe_endpoint(recipe_id: str, req: TailorRequest) -> TailoringPlanDTO:
    try:
        recipe = load_recipe(recipe_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    plan = tailor_recipe(recipe, req.profile or {})
    return TailoringPlanDTO(**plan.to_dict())


@router.post(
    "/recommend",
    response_model=list[TailoringPlanDTO],
    summary="Rank all built-in recipes against a profile",
)
async def recommend_recipes_endpoint(req: TailorRequest) -> list[TailoringPlanDTO]:
    recipes = []
    for rid in list_builtin_recipes():
        try:
            recipes.append(load_recipe(rid))
        except Exception as exc:  # pragma: no cover
            logger.warning("skipping broken recipe %s: %s", rid, exc)
    plans = recommend_recipes(recipes, req.profile or {})
    return [TailoringPlanDTO(**p.to_dict()) for p in plans]


@router.post(
    "/{recipe_id}/plan",
    response_model=TailoringPlanDTO,
    summary="Dynamic tri-state tailoring — returns questions when uncertain",
)
async def plan_recipe_endpoint(recipe_id: str, req: DynamicPlanRequest) -> TailoringPlanDTO:
    """Tailor with the tri-state engine.

    Unlike ``/tailor`` (which collapses unknowns to False), this endpoint
    returns ``should_produce="uncertain"`` plus a list of
    ``pending_questions`` the agent must ask before the plan can be
    finalised. When ``user_id`` is supplied, the caller's CKF is used
    to auto-fill known facts before deciding what to ask.
    """
    try:
        recipe = load_recipe(recipe_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    ckf_lookup = None
    if req.user_id:
        try:
            # Lazy import — avoids a hard dependency at module import time.
            from ..agent.ckf import CKFStore  # type: ignore

            ckf_lookup = CKFStore.for_user(req.user_id)  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover — optional enrichment
            ckf_lookup = None

    plan = tailor_recipe_dynamic(recipe, req.profile or {}, ckf_lookup=ckf_lookup)
    return TailoringPlanDTO(**plan.to_dict())


__all__ = ["router"]
