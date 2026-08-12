# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""FastAPI routes for the LLM-powered Compliance Agent (Phase 4.6).

Exposes the Phase 4.2 :class:`crp_comply.agent.ComplianceAgent` as a REST
surface with session persistence so UIs and SDK clients can:

* ``POST /agent/start``          — kick off a new reasoning session
* ``GET  /agent/sessions``       — list this user's sessions
* ``GET  /agent/{session_id}``   — poll current state
* ``POST /agent/{session_id}/clarify``  — answer a pending question → resume
* ``POST /agent/{session_id}/finalize`` — persist final_text as a report
* ``DELETE /agent/{session_id}`` — cancel / delete

Sessions are persisted via :mod:`crp_comply.persistent_json_store`
(default file, optional Redis) so frontends can resume across browser reloads
and multi-worker / serverless deployments see a consistent view without
relying on a single attached volume.

Design notes
------------

* The agent's :meth:`ComplianceAgent.run` is not natively resumable after a
  ``ClarificationNeeded`` — each call rebuilds its in-memory message history
  from the system prompt + task. To *resume*, this router replays the prior
  clarification(s) into ``extra_context`` so the LLM sees the full Q/A log
  and doesn't ask the same question twice. The per-customer CKF also
  surfaces prior tool results via the ``recall_facts`` tool.
* Feature + quota: the whole router is gated on ``agent_intelligence``
  via ``_require_feature`` and every mutating call is metered.
* LLM provider: defaults to env-autodetect through
  :class:`crp_comply.agent.ComplianceLLM`. BYOK per-user credentials will be
  wired in a later phase (see ``STRATEGIC_REASSESSMENT.md``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path as PathParam, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..agent import ComplianceAgent, ComplianceLLM, default_registry
from ..agent.memory import CompliantMemory
from ..agent.preference_learner import PreferenceLearner
from ..agent.preferences import get_preference_store
from ..agent.rag_service import RagService
from ..agent.slm_profile import apply_slm_profile, detect_slm_profile, model_name_from_llm
from ..org_profile import get_org_profile_store
from ..persistent_json_store import JsonStore, get_json_store
from .auth import Tier, check_feature_access
from .deps import get_current_tenant, get_current_tier, get_current_user, meter_call
from .models import (
    AgentClarifyRequest,
    AgentContinueRequest,
    AgentFeedbackRequest,
    AgentPreviewRequest,
    AgentEstimateRequest,
    AgentFinalizeRequest,
    AgentFinalizeResponse,
    AgentSessionList,
    AgentSessionState,
    AgentStartRequest,
)

logger = logging.getLogger("crp_comply.api.agent")

# Rate-limit every endpoint under /agent/* using the "agent" group
# (PRODUCT_SECURITY.md §4 gap #1).
from fastapi import Depends as _Depends

from .rate_limit import rate_limit_dep as _rate_limit_dep

router = APIRouter(
    prefix="/agent",
    tags=["agent"],
    dependencies=[_Depends(_rate_limit_dep("agent"))],
)

_FEATURE = "agent_intelligence"
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{6,80}$")


# ═══════════════════════════════════════════════════════════════
# Session store
# ═══════════════════════════════════════════════════════════════

_session_store: JsonStore | None = None
_store_root_override: Path | None = None


def init_agent_sessions(data_dir: Path | str | None = None) -> None:
    """Called once at app startup to pin the session store."""
    global _session_store, _store_root_override
    _session_store = get_json_store("agent_sessions", data_dir)
    # Keep a filesystem root for legacy trace artefacts even when sessions
    # themselves live in Redis.
    data_dir_path = Path(data_dir or os.environ.get("CRP_COMPLY_DATA_DIR", "data"))
    _store_root_override = data_dir_path / "agent_sessions"
    _store_root_override.mkdir(parents=True, exist_ok=True)


def _store_root() -> Path:
    if _store_root_override is not None:
        return _store_root_override
    data_dir = Path(os.environ.get("CRP_COMPLY_DATA_DIR", "data"))
    root = data_dir / "agent_sessions"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_dir_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-]", "_", name) or "anonymous"


def _session_key(user_id: str, session_id: str) -> str:
    if not _SESSION_ID_RE.match(session_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid session_id format",
        )
    return f"{_safe_dir_name(user_id)}:{session_id}"


def _load_session(user_id: str, session_id: str) -> dict[str, Any]:
    store = _session_store or get_json_store("agent_sessions")
    rec = store.get(_session_key(user_id, session_id))
    if rec is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent session not found: {session_id}",
        )
    return rec


def _save_session(user_id: str, record: dict[str, Any]) -> None:
    store = _session_store or get_json_store("agent_sessions")
    record["updated_at"] = _now_iso()
    store.set(_session_key(user_id, record["session_id"]), record)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_to_state(record: dict[str, Any]) -> AgentSessionState:
    return AgentSessionState(
        session_id=record["session_id"],
        user_id=record.get("user_id", ""),
        state=record.get("state", "unknown"),
        task=record.get("task", ""),
        system_id=record.get("system_id", ""),
        customer_id=record.get("customer_id", ""),
        iterations=int(record.get("iterations", 0)),
        tool_calls=int(record.get("tool_calls", 0)),
        facts_stored=int(record.get("facts_stored", 0)),
        pending_question=record.get("pending_question", ""),
        pending_context=record.get("pending_context", ""),
        pending_priority=record.get("pending_priority", ""),
        pending_skippable=bool(record.get("pending_skippable", False)),
        pending_fact_key=record.get("pending_fact_key", ""),
        pending_options=list(record.get("pending_options") or []),
        resume_token=record.get("resume_token", ""),
        pending_action=record.get("pending_action", "probe"),
        final_text=record.get("final_text", ""),
        error=record.get("error", ""),
        clarifications=list(record.get("clarifications", [])),
        created_at=record.get("created_at", _now_iso()),
        updated_at=record.get("updated_at", _now_iso()),
        trace_path=record.get("trace_path", ""),
        messages=list(record.get("messages", [])),
        reasoning_tape=list(record.get("reasoning_tape", [])),
        experts_invoked=list(record.get("experts_invoked", [])),
    )


# ═══════════════════════════════════════════════════════════════
# Agent factory
# ═══════════════════════════════════════════════════════════════

# Module-level hook so tests can inject a deterministic factory.
_agent_factory_override: Any = None


def set_agent_factory(factory: Any) -> None:
    """Override the agent factory (used by tests to inject a fake LLM)."""
    global _agent_factory_override
    _agent_factory_override = factory


def _llm_ctx_window(llm: Any) -> int:
    """Best-effort context-window probe for the configured LLM.

    Used to pass ``ctx_window`` to ``default_registry`` so the
    query_regulation envelope budget is scaled to the actual carrier
    rather than defaulting to 1500 tokens (which is too large on 4096-
    token LM Studio models).
    """
    try:
        if hasattr(llm, "context_window_size"):
            return int(llm.context_window_size())
    except Exception:
        pass
    try:
        provider = getattr(llm, "provider", None)
        if provider is not None and hasattr(provider, "context_window_size"):
            return int(provider.context_window_size())
    except Exception:
        pass
    try:
        return int(os.environ.get("CRP_COMPLY_CTX_WINDOW", "0"))
    except Exception:
        return 0


def _load_profile(tenant_id: str | None, user_id: str) -> dict[str, Any] | None:
    """Load the stored OrgProfile, preferring the tenant scope.

    Falls back to the user's own profile if no tenant profile exists.
    Returns ``None`` when the store is unavailable or no profile exists.
    """
    try:
        store = get_org_profile_store()
    except Exception:
        return None
    for key in (tenant_id, user_id):
        if not key:
            continue
        try:
            profile = store.get(key)
            if profile:
                return profile
        except Exception:
            logger.debug("Failed to load OrgProfile for %s", key, exc_info=True)
    return None


def _map_autonomy_to_enforcer_mode(autonomy: str | None) -> str | None:
    """Map a frontend autonomy level to an agent PEP mode.

    * ``suggest`` → ``strict`` (all actions gated)
    * ``draft`` / ``autonomous_with_checkpoints`` → ``default``
    * ``full`` → ``off`` (no tool-call checkpoints)
    * Any unknown value leaves the env default in place.
    """
    mapping = {
        "suggest": "strict",
        "draft": "default",
        "autonomous_with_checkpoints": "default",
        "full": "off",
    }
    if not autonomy:
        return None
    return mapping.get(autonomy.strip().lower())


def _build_agent(
    *,
    user_id: str,
    max_iters: int,
    profile: dict[str, Any] | None = None,
    preferred_regulations: list[str] | None = None,
    autonomy: str | None = None,
) -> ComplianceAgent:
    """Construct a ComplianceAgent for this request.

    Uses env-autodetected credentials via :class:`ComplianceLLM`. Wires the
    per-user CKF so recall_facts/store_fact respect tenancy. In tests,
    :func:`set_agent_factory` replaces this wholesale.
    """
    if _agent_factory_override is not None:
        return _agent_factory_override(
            user_id=user_id, max_iters=max_iters, profile=profile, autonomy=autonomy
        )

    try:
        llm = ComplianceLLM.for_user(user_id)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"No LLM provider configured: {exc}. Set CRP_COMPLY_LLM_BASE_URL, "
                "OPENAI_API_KEY, or ANTHROPIC_API_KEY; or configure a BYOK "
                "provider for your account."
            ),
        ) from exc

    # Per-user CKF (reuses the pattern from routes.py::_get_user_ckf but via
    # a deferred import to keep the module import cheap + avoid circulars).
    try:
        from .routes import _get_user_ckf  # type: ignore

        fabric = _get_user_ckf(user_id)
    except Exception:  # pragma: no cover
        fabric = None

    # RAG service — optional; only wire if the corpus index exists.
    rag = None
    try:
        rag = RagService()
    except Exception:  # pragma: no cover
        rag = None

    # Evidence-substrate backends — let the agent pull from the user's
    # own data room (artefact uploads) and from runtime audit chain
    # (proxy events). Deferred imports keep the cold path cheap and
    # avoid pulling proxy state when the proxy is not initialised.
    artefact_store = None
    proxy_metrics = None
    try:
        from .artefacts import get_artefact_store

        artefact_store = get_artefact_store()
    except Exception:  # pragma: no cover - artefacts is best-effort
        artefact_store = None
    try:
        from ..proxy.routes import _interceptor as _proxy_singleton  # type: ignore

        proxy_metrics = _proxy_singleton
    except Exception:  # pragma: no cover
        proxy_metrics = None

    # Phase 7.15.b — wire the web-search sidecar so the agent can call
    # ``web_search`` / ``web_research`` / ``vendor_profile`` /
    # ``compare_documents`` autonomously. ``build_default_web_client``
    # returns ``None`` when ``CRP_COMPLY_SEARCH_URL`` is not set, in
    # which case the registry simply omits the web tools and the agent
    # falls back to corpus-only retrieval.
    web_client = None
    try:
        from ..agent.web_client import build_default_web_client

        web_client = build_default_web_client()
    except Exception:  # pragma: no cover - never let web wiring crash request path
        logger.exception("web_client init failed; running corpus-only")

    ctx_window = _llm_ctx_window(llm)
    slm_profile = detect_slm_profile(
        model_name_from_llm(llm),
        context_window=ctx_window,
    )
    if slm_profile is not None:
        ctx_window = min(ctx_window, slm_profile.context_window)
        logger.debug("applying SLM profile %s for user %s", slm_profile.name, user_id)

    registry = default_registry(
        rag=rag,
        fabric=fabric,
        artefact_store=artefact_store,
        proxy_metrics=proxy_metrics,
        user_id=user_id,
        web_client=web_client,
        ctx_window=ctx_window,
        preferred_regulations=preferred_regulations,
    )

    trace_dir = Path(_store_root()).parent / "agent_traces" / _safe_dir_name(user_id)
    trace_dir.mkdir(parents=True, exist_ok=True)

    agent_kwargs = dict(
        llm=llm,
        fabric=fabric,
        tools=registry,
        max_iters=max_iters,
        trace_dir=trace_dir,
        rag=rag,
        web_client=web_client,
        profile=profile,
    )
    if slm_profile is not None:
        agent_kwargs = apply_slm_profile(
            slm_profile,
            agent_kwargs,
            filter_tools=True,
        )
        if not slm_profile.enable_web_research:
            agent_kwargs["web_client"] = None

    agent = ComplianceAgent(**agent_kwargs)

    # Map the caller's autonomy preference to the agent's Policy Enforcement
    # Point mode. Empty / unknown values leave the env default unchanged.
    _mapped_mode = _map_autonomy_to_enforcer_mode(autonomy)
    if _mapped_mode is not None:
        agent.enforcer_mode = _mapped_mode

    # Apply per-user dispatch mode preference from the provider config store,
    # so users can choose agentic / with_tools / etc. from the Settings UI.
    try:
        from .provider import get_provider_store as _get_ps

        _ps_cfg = _get_ps().get(user_id)
        if _ps_cfg:
            _mode = (_ps_cfg.get("dispatch_mode") or "").strip().lower()
            if _mode in {"agentic", "with_tools", "stream_augmented", "plain"}:
                agent.dispatch_mode_override = _mode
    except Exception:
        pass  # Non-fatal — fall through to env var / default

    return agent


def _user_has_own_llm(user_id: str) -> bool:
    """True if the caller is bringing their own LLM (BYOK provider stored
    or SDK worker currently attached). Used to grant ``agent_intelligence``
    irrespective of plan tier when the user is paying their own inference
    cost — free-plan growth without giving away hosted LLM credits.
    """
    try:
        from .provider import get_provider_store

        cfg = get_provider_store().get(user_id)
        if cfg and cfg.get("provider"):
            return True
    except Exception:  # pragma: no cover — store may not be initialised
        pass
    try:
        from .worker_registry import get_worker_registry

        if get_worker_registry().is_attached(user_id):
            return True
    except Exception:  # pragma: no cover
        pass
    return False


def _require_feature_or_403(tier: Tier) -> None:
    """Legacy helper kept for non-route callers. Route handlers should
    use :func:`require_agent_access` instead so the gate runs *before*
    the per-call meter and quota counter."""
    if not check_feature_access(tier, _FEATURE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"The compliance agent requires a tier with '{_FEATURE}' "
                f"enabled. Current tier: {tier.value}."
            ),
        )


async def require_agent_access(
    user_id: Annotated[str, Depends(get_current_user)],
    tier: Annotated[Tier, Depends(get_current_tier)],
) -> None:
    """FastAPI dependency: 403 unless caller can use the agent.

    Granted when EITHER the plan tier includes ``agent_intelligence`` OR
    the user has configured their own LLM (BYOK or SDK worker). Runs
    before :func:`meter_call` so a denied call is **not** counted
    against the user's monthly quota — fixes the "failed calls still
    decrement the meter" UX bug.
    """
    if user_id == "anonymous":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Agent sessions require authentication.",
        )
    if check_feature_access(tier, _FEATURE):
        return
    if _user_has_own_llm(user_id):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            f"The compliance agent requires either a tier with '{_FEATURE}' "
            f"enabled (current tier: {tier.value}) or a configured LLM "
            f"provider — set one up in Settings → LLM Provider (BYOK or "
            f"local SDK worker) and the agent will unlock immediately."
        ),
    )


# ═══════════════════════════════════════════════════════════════
# Core sync-runner (offloaded to thread for FastAPI)
# ═══════════════════════════════════════════════════════════════


def _merge_clarifications(base_context: str, clarifications: list[dict[str, str]]) -> str:
    """Append clarification Q/A history to the extra_context so the resumed
    agent run does not re-ask anything the user already answered."""
    if not clarifications:
        return base_context
    lines: list[str] = []
    if base_context.strip():
        lines.append(base_context.strip())
        lines.append("")
    lines.append("Previously answered clarifications (authoritative — do not re-ask):")
    for i, pair in enumerate(clarifications, 1):
        q = (pair.get("question") or "").strip()
        a = (pair.get("answer") or "").strip()
        if q and a:
            lines.append(f"{i}. Q: {q}")
            lines.append(f"   A: {a}")
    return "\n".join(lines)


def _clear_pending_clarification(record: dict[str, Any]) -> None:
    """Reset the clarification-pending fields on a session record."""
    record["pending_question"] = ""
    record["pending_context"] = ""
    record["pending_priority"] = ""
    record["pending_skippable"] = False
    record["pending_fact_key"] = ""
    record["pending_options"] = []
    record["resume_token"] = ""
    record["pending_action"] = "probe"


def _append_clarification(
    record: dict[str, Any],
    question: str,
    answer: str,
    *,
    skipped: bool = False,
) -> None:
    """Record a clarification Q/A pair in the session record."""
    record.setdefault("clarifications", []).append(
        {
            "question": question,
            "answer": answer,
            "skipped": "true" if skipped else "false",
            "ts": _now_iso(),
        }
    )


def _resume_via_tracker(
    *,
    user_id: str,
    tenant_id: str,
    record: dict[str, Any],
    answer: str,
    skip: bool = False,
    token: str | None = None,
) -> tuple[AgentSessionState | None, Any, Any]:
    """Resume a clarification using the Round-3 dialogue tracker when possible.

    Returns ``(state, tracker)``:
      * If ``state`` is not ``None``, another clarification is pending and the
        caller should return that state (or stream the clarifier event).
      * If ``state`` is ``None`` and ``tracker`` is not ``None``, the dialogue
        tracker resolved the clarification and the caller can continue the loop
        or agent run with the updated slots.
      * If both are ``None``, the record has no dialogue-state snapshot and the
        legacy text-replay path should be used.
    """
    from ..agent.clarifier import ClarifierStore, ToolError as _ClarifierError, make_resume_token
    from ..agent.dialogue import DialogueStateTracker
    from ..agent.memory import CompliantMemory
    from ..agent.nlu import NluEngine

    resolved_token = token or record.get("resume_token", "")
    snapshot: dict[str, Any] = {}
    question = ""
    if resolved_token:
        try:
            rec = ClarifierStore().load(resume_token=resolved_token, tenant_id=tenant_id or user_id)
            if rec is not None:
                snapshot = rec.snapshot or {}
                question = rec.question or ""
        except _ClarifierError:
            snapshot = {}
        except Exception:
            logger.exception("failed to load clarifier record")

    dialogue_state_data = snapshot.get("dialogue_state")
    if dialogue_state_data is None:
        return None, None, None

    memory = CompliantMemory(user_id=user_id, session_id=record["session_id"])
    profile = record.get("org_profile") or _load_profile(record.get("customer_id"), user_id)

    def _load_dialogue(_uid: str) -> dict[str, Any] | None:
        return dialogue_state_data

    tracker = DialogueStateTracker(
        user_id=user_id,
        nlu=NluEngine(),
        load_fn=_load_dialogue,
        memory=memory,
        user_profile=profile,
    )
    # The load_fn seeded the state; also seed the stored policy decision so
    # resume() has the exact action/options context.
    pending = snapshot.get("policy_decision")
    if pending and tracker.state.pending_decision is None:
        tracker.state.pending_decision = pending

    if skip:
        tracker.state.pending_decision = None
        _append_clarification(record, question, "[SKIPPED by user]", skipped=True)
        _clear_pending_clarification(record)
        tracker.save()
        return None, tracker, memory

    try:
        next_decision = tracker.resume(answer)
    except Exception:
        logger.exception("dialogue tracker resume failed")
        return None, None, None

    if next_decision is None:
        _append_clarification(record, question, answer, skipped=False)
        _clear_pending_clarification(record)
        tracker.save()
        return None, tracker, memory

    # Another clarification needed — persist the new decision and update record.
    action = next_decision.action
    options = list(next_decision.options or [])
    missing = list(next_decision.args.get("missing") or [])
    slot_id = next_decision.args.get("slot") or (missing[0] if missing else "")
    question_text = next_decision.reply_text or ""
    new_token = make_resume_token()
    try:
        ClarifierStore().suspend(
            resume_token=new_token,
            session_id=record["session_id"],
            run_id=record["session_id"],
            tenant_id=tenant_id or user_id,
            slot_id=slot_id or "",
            question=question_text,
            options=options or None,
            snapshot={
                "task": record.get("task", ""),
                "dialogue_state": tracker.state.to_dict(),
                "dialogue_action": action,
                "policy_options": options,
                "policy_decision": next_decision.to_dict(),
            },
        )
    except Exception:
        logger.exception("failed to suspend next clarification")

    _append_clarification(record, question, answer, skipped=False)
    record["state"] = "awaiting_clarification"
    record["pending_question"] = question_text
    record["pending_options"] = options
    record["pending_action"] = action
    record["resume_token"] = new_token
    record["pending_priority"] = "medium"
    record["pending_skippable"] = False
    _save_session(user_id, record)
    return _record_to_state(record), tracker, memory


async def _run_agent_async(
    agent: ComplianceAgent,
    *,
    task: str,
    system_id: str,
    customer_id: str,
    session_id: str,
    extra_context: str,
    clarifications_used: int = 0,
    prior_messages: list[dict[str, Any]] | None = None,
) -> Any:
    """Run the blocking agent loop in a worker thread.

    ``clarifications_used`` is passed as a keyword only if the agent's
    :meth:`run` method accepts it. This keeps the API compatible with
    test doubles that script a simpler ``run(task, *, system_id, …)``
    signature.
    """
    import inspect

    kwargs: dict[str, Any] = {
        "system_id": system_id,
        "customer_id": customer_id,
        "session_id": session_id,
        "extra_context": extra_context,
    }
    try:
        sig = inspect.signature(agent.run)
        params = sig.parameters
        accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
        if "clarifications_used" in params or accepts_kwargs:
            kwargs["clarifications_used"] = clarifications_used
        if prior_messages and ("prior_messages" in params or accepts_kwargs):
            kwargs["prior_messages"] = prior_messages
    except (TypeError, ValueError):
        pass
    return await asyncio.to_thread(agent.run, task, **kwargs)


# ═══════════════════════════════════════════════════════════════
# Phase 6 \u2014 Multi-turn message history
# ═══════════════════════════════════════════════════════════════
#
# Inspired by wasa-ai's ChatSessionManager pattern: each session keeps
# a flat list of `{role, content, ts}` entries. On every continuation
# turn the API selects the most-relevant subset under a token budget
# and replays it to the orchestrator as a real chat history (rather
# than as a text-blob system message). This gives the LLM a true
# conversation view, which dramatically improves follow-up quality.
#
# Selection strategy (mirrors wasa-ai's MessageRelevanceScorer but
# leaner — no separate summarizer dependency):
#   * Always preserve the last ``preserve_recent`` messages.
#   * For older messages, score by recency × keyword overlap with the
#     new user query × role weight; take top-N within the token budget.
#   * Cap total replayed messages at ``max_messages``.

_MULTITURN_DEFAULTS = {
    "max_messages": 12,
    "max_chars": 12_000,  # ~3000 tokens; leaves headroom on 8k models
    "preserve_recent": 4,
}


def _now_msg_ts() -> str:
    return _now_iso()


def _append_user_message(record: dict[str, Any], content: str) -> None:
    msgs = record.setdefault("messages", [])
    if not content.strip():
        return
    msgs.append(
        {
            "role": "user",
            "content": content.strip(),
            "ts": _now_msg_ts(),
        }
    )


def _append_assistant_message(record: dict[str, Any], content: str) -> None:
    msgs = record.setdefault("messages", [])
    if not content.strip():
        return
    # Avoid duplicate appends if the same final_text is committed twice
    # (e.g. SSE flush + record-save race).
    if msgs and msgs[-1].get("role") == "assistant" and msgs[-1].get("content") == content.strip():
        return
    msgs.append(
        {
            "role": "assistant",
            "content": content.strip(),
            "ts": _now_msg_ts(),
        }
    )


def _score_message(
    msg: dict[str, Any],
    *,
    current_query: str,
    position: int,
    total: int,
) -> float:
    """Lightweight relevance score; same heuristics as wasa-ai's scorer
    minus the security-focused keyword list (we substitute compliance
    keywords)."""
    role = msg.get("role", "user")
    content = (msg.get("content") or "").lower()

    score = {"assistant": 0.6, "user": 0.5}.get(role, 0.4)

    if total > 1:
        recency = position / (total - 1)
        score += recency * 0.2

    high_value = (
        "article",
        "obligation",
        "requirement",
        "shall",
        "must",
        "regulation",
        "ce marking",
        "conformity",
        "annex",
        "high-risk",
        "gpai",
        "data protection",
        "controller",
        "processor",
        "dpa",
        "iso/iec",
        "nist",
        "framework",
    )
    kw_hits = sum(1 for kw in high_value if kw in content)
    score += min(kw_hits * 0.04, 0.16)

    q = (current_query or "").lower()
    if q:
        q_words = set(w for w in q.split() if len(w) > 3)
        c_words = set(content.split())
        overlap = len(q_words & c_words)
        if overlap:
            score += min(overlap * 0.03, 0.15)

    return max(0.0, min(1.0, score))


# Minimum character budget before we spend tokens on a fact-envelope preamble.
# Below this we fall back to the legacy score-and-trim behavior so tiny test
# budgets and very small context windows don't get swamped by the envelope.
_MIN_CHARS_FOR_FACT_ENVELOPE = 300


def _select_history_for_run(
    record: dict[str, Any],
    *,
    new_user_message: str,
    max_messages: int | None = None,
    max_chars: int | None = None,
    preserve_recent: int | None = None,
    summarize_after: int = 6,
) -> list[dict[str, str]]:
    """Pick the relevant slice of session history to replay this turn.

    Returns a list of ``{role, content}`` dicts in chronological order,
    excluding the active ``new_user_message`` (which the orchestrator
    appends itself as the live user task).

    When history grows past ``summarize_after`` turns and the budget is large
    enough, old turns are converted to facts and stored in the session's
    conversation ledger; only the most recent ``preserve_recent`` turns are
    replayed verbatim.  For very tight budgets the function falls back to the
    legacy relevance-scored selection so the window is not starved by the
    envelope.
    """
    from crp_comply.agent.conversation_ledger import ConversationLedger

    history = list(record.get("messages") or [])
    if not history:
        return []

    max_msgs = int(max_messages or _MULTITURN_DEFAULTS["max_messages"])
    max_c = int(max_chars or _MULTITURN_DEFAULTS["max_chars"])
    preserve = int(preserve_recent or _MULTITURN_DEFAULTS["preserve_recent"])

    # Tight-budget fallback: score and trim the raw history so tiny context
    # windows still get the best verbatim slice.
    if max_c < _MIN_CHARS_FOR_FACT_ENVELOPE:
        return _select_history_legacy(
            history,
            new_user_message=new_user_message,
            max_messages=max_msgs,
            max_chars=max_c,
            preserve_recent=preserve,
        )

    # Convert aged turns into facts and carry them in a session ledger.
    ledger_data = record.get("conversation_ledger") or {}
    ledger = ConversationLedger.from_dict(ledger_data)
    if ledger.session_id != record.get("session_id"):
        ledger.session_id = record.get("session_id", "")
    for m in history:
        ledger.add_turn(str(m.get("role", "user")), str(m.get("content", "")))
    if len(history) > summarize_after:
        ledger.summarize_old_turns()
        record["conversation_ledger"] = ledger.to_dict()

    # Build replay list: recent turns only, plus a fact-envelope preamble.
    recent_turns = history[-preserve:] if preserve > 0 else history
    envelope_text = ledger.pack_envelope(max_facts=30)

    # Char-budget tail trim \u2014 keep newest within budget.
    replayed: list[dict[str, str]] = []
    total_chars = 0
    for m in reversed(recent_turns):
        content = (m.get("content") or "").strip()
        if not content:
            continue
        if total_chars + len(content) > max_c and replayed:
            break
        replayed.append({"role": m.get("role", "user"), "content": content})
        total_chars += len(content)
    replayed.reverse()

    if envelope_text:
        envelope = {
            "role": "system",
            "name": "crp_conversation_facts",
            "content": envelope_text,
        }
        # Only prepend the envelope if there is room; otherwise drop it so the
        # live recent turns are not evicted.
        if total_chars + len(envelope_text) <= max_c:
            return [envelope] + replayed
    return replayed


def _select_history_legacy(
    history: list[dict[str, Any]],
    *,
    new_user_message: str,
    max_messages: int,
    max_chars: int,
    preserve_recent: int,
) -> list[dict[str, str]]:
    """Legacy relevance-scored history selection for tight budgets."""
    if len(history) <= max_messages:
        selected = history
    else:
        recent = history[-preserve_recent:] if preserve_recent > 0 else []
        older = history[:-preserve_recent] if preserve_recent > 0 else history
        slots = max_messages - len(recent)
        if slots <= 0 or not older:
            selected = recent
        else:
            scored = [
                (
                    _score_message(
                        m,
                        current_query=new_user_message,
                        position=i,
                        total=len(older),
                    ),
                    i,
                    m,
                )
                for i, m in enumerate(older)
            ]
            scored.sort(key=lambda x: x[0], reverse=True)
            top = scored[:slots]
            top.sort(key=lambda x: x[1])
            selected = [m for _, _, m in top] + recent

    out: list[dict[str, str]] = []
    total_chars = 0
    for m in reversed(selected):
        content = (m.get("content") or "").strip()
        if not content:
            continue
        if total_chars + len(content) > max_chars and out:
            break
        out.append({"role": m.get("role", "user"), "content": content})
        total_chars += len(content)
    out.reverse()
    return out


def _apply_result(record: dict[str, Any], result: Any) -> None:
    """Merge an AgentResult into a session record (cumulative counters)."""
    # tool_calls + iterations + facts_stored are cumulative across resumes
    record["iterations"] = int(record.get("iterations", 0)) + int(getattr(result, "iterations", 0))
    record["tool_calls"] = int(record.get("tool_calls", 0)) + int(getattr(result, "tool_calls", 0))
    record["facts_stored"] = int(record.get("facts_stored", 0)) + int(
        getattr(result, "facts_stored", 0)
    )
    record["state"] = getattr(result, "state", "error")
    record["pending_question"] = getattr(result, "pending_question", "") or ""
    record["pending_context"] = getattr(result, "pending_context", "") or ""
    record["pending_priority"] = getattr(result, "pending_priority", "") or ""
    record["pending_skippable"] = bool(getattr(result, "pending_skippable", False))
    record["pending_fact_key"] = getattr(result, "pending_fact_key", "") or ""
    record["pending_options"] = list(getattr(result, "options", None) or [])
    record["resume_token"] = getattr(result, "resume_token", "") or ""
    record["pending_action"] = getattr(result, "pending_action", "probe") or "probe"
    final = getattr(result, "final_text", "") or ""
    if final:
        record["final_text"] = final
        # Phase 6 multi-turn: append the assistant's reply to the
        # message log so the next /continue turn can replay it.
        _append_assistant_message(record, final)
    err = getattr(result, "error", "") or ""
    if err:
        record["error"] = err
    tp = getattr(result, "trace_path", "") or ""
    if tp:
        record["trace_path"] = tp
    # Clarification budget + privacy telemetry surfaced to the UI so the
    # user sees both how many rounds they have left and how many PII
    # spans were scrubbed before hitting the LLM.
    record["clarifications_used"] = int(getattr(result, "clarifications_used", 0))
    record["clarification_budget"] = int(getattr(result, "clarification_budget", 6))
    record["pii_redactions"] = int(record.get("pii_redactions", 0)) + int(
        getattr(result, "pii_redactions", 0)
    )
    cw = int(getattr(result, "continuation_windows", 1))
    if cw > 1:
        record["continuation_windows"] = cw
        record["continuation_reason"] = getattr(result, "continuation_reason", "") or ""
    tape = getattr(result, "reasoning_tape", None) or []
    if tape:
        record.setdefault("reasoning_tape", []).extend(tape)
    experts = getattr(result, "experts_invoked", None) or []
    if experts:
        seen = set(record.get("experts_invoked", []))
        seen.update(experts)
        record["experts_invoked"] = sorted(seen)


# ═══════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════


@router.post(
    "/start",
    response_model=AgentSessionState,
    summary="Start a new compliance agent reasoning session.",
    # NOTE: gate runs *before* the meter so 403s don't count.
    dependencies=[Depends(require_agent_access), Depends(meter_call("agent_start"))],
)
async def agent_start(
    req: AgentStartRequest,
    user_id: Annotated[str, Depends(get_current_user)],
    tier: Annotated[Tier, Depends(get_current_tier)],
) -> AgentSessionState:
    if user_id == "anonymous":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Agent sessions require authentication.",
        )

    session_id = uuid.uuid4().hex
    record: dict[str, Any] = {
        "session_id": session_id,
        "user_id": user_id,
        "tier": tier.value,
        "task": req.task,
        "system_id": req.system_id,
        "customer_id": req.customer_id,
        "extra_context": req.extra_context,
        "max_iters": int(req.max_iters),
        "autonomy": req.autonomy,
        "state": "running",
        "iterations": 0,
        "tool_calls": 0,
        "facts_stored": 0,
        "pending_question": "",
        "pending_context": "",
        "final_text": "",
        "error": "",
        "clarifications": [],
        "messages": [],
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "trace_path": "",
    }
    _save_session(user_id, record)
    _append_user_message(record, req.task)

    profile = _load_profile(req.customer_id, user_id)
    if profile:
        record["org_profile"] = profile
        _save_session(user_id, record)

    agent = _build_agent(
        user_id=user_id, max_iters=int(req.max_iters), profile=profile, autonomy=req.autonomy
    )
    try:
        result = await _run_agent_async(
            agent,
            task=req.task,
            system_id=req.system_id,
            customer_id=req.customer_id,
            session_id=session_id,
            extra_context=req.extra_context,
        )
    except Exception as exc:
        logger.exception("agent_start failed session=%s", session_id)
        record["state"] = "error"
        record["error"] = f"{type(exc).__name__}: {exc}"
        _save_session(user_id, record)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Agent run failed: {exc}",
        ) from exc

    _apply_result(record, result)
    _save_session(user_id, record)
    return _record_to_state(record)


@router.get(
    "/sessions",
    response_model=AgentSessionList,
    summary="List this user's agent sessions (most-recent first).",
)
async def agent_list(
    user_id: Annotated[str, Depends(get_current_user)],
    tier: Annotated[Tier, Depends(get_current_tier)],
) -> AgentSessionList:
    if user_id == "anonymous":
        return AgentSessionList(sessions=[])
    if not check_feature_access(tier, _FEATURE) and not _user_has_own_llm(user_id):
        # Read-only: list is empty rather than 403 so the UI can render
        # a helpful empty-state instead of an error toast.
        return AgentSessionList(sessions=[])

    store = _session_store or get_json_store("agent_sessions")
    prefix = f"{_safe_dir_name(user_id)}:"
    records: list[AgentSessionState] = []
    for key in store.list_keys(prefix):
        try:
            rec = store.get(key)
        except Exception:
            continue
        if not rec:
            continue
        try:
            records.append(_record_to_state(rec))
        except Exception as _bandit_exc:
            logger.debug("swallowed in agent_sessions: %s", _bandit_exc)
            continue
    # Most-recent first: fall back to created_at if mtime is unavailable.
    records.sort(
        key=lambda s: s.created_at or "",
        reverse=True,
    )
    return AgentSessionList(sessions=records)


@router.get(
    "/{session_id}",
    response_model=AgentSessionState,
    summary="Get the current state of an agent session.",
    dependencies=[Depends(require_agent_access)],
)
async def agent_get(
    session_id: Annotated[str, PathParam(min_length=6, max_length=80)],
    user_id: Annotated[str, Depends(get_current_user)],
    tier: Annotated[Tier, Depends(get_current_tier)],
) -> AgentSessionState:
    record = _load_session(user_id, session_id)
    return _record_to_state(record)


# ── Phase 7.12: replay endpoint ────────────────────────────────────────────


_RUN_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{4,80}$")


@router.get(
    "/runs/{run_id}/replay",
    summary="Replay the typed loop event log for one run.",
    dependencies=[Depends(require_agent_access)],
)
async def agent_run_replay(
    run_id: Annotated[str, PathParam(min_length=4, max_length=80)],
    user_id: Annotated[str, Depends(get_current_user)],
) -> dict[str, Any]:
    """Return the full ordered event log for ``run_id``.

    The store is keyed on tenant *and* run id, so a cross-tenant
    request resolves to ``404`` (existence is not leaked). The
    response shape is::

        {"run_id": "...", "events": [{"event": "loop.opened", ...}, ...]}

    Sealed-on-disk envelopes are decrypted lazily by the store; events
    that fail to decrypt (e.g. KEK rotation gap) are dropped, so the
    replay is best-effort and may be shorter than the original log.
    """
    if not _RUN_ID_RE.match(run_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="run_id has invalid characters or length.",
        )
    telemetry = _telemetry_singleton()
    record = telemetry.find_run(run_id=run_id, tenant_id=user_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="run not found.",
        )
    events = telemetry.replay(run_id=run_id, tenant_id=user_id)
    return {
        "run_id": run_id,
        "session_id": record.session_id,
        "opened_at": record.opened_at,
        "closed_at": record.closed_at,
        "events": events,
    }


_telemetry_instance: Any = None


def _telemetry_singleton():
    """Lazy module-level singleton; importable from tests."""
    global _telemetry_instance
    if _telemetry_instance is None:
        from ..agent.telemetry import LoopTelemetry

        _telemetry_instance = LoopTelemetry()
    return _telemetry_instance


def _reset_telemetry_for_tests() -> None:
    """Tests use this to point the singleton at a tmp dir."""
    global _telemetry_instance
    _telemetry_instance = None


@router.post(
    "/{session_id}/clarify",
    response_model=AgentSessionState,
    summary="Answer a pending clarification and resume the agent.",
    dependencies=[Depends(require_agent_access), Depends(meter_call("agent_clarify"))],
)
async def agent_clarify(
    session_id: Annotated[str, PathParam(min_length=6, max_length=80)],
    req: AgentClarifyRequest,
    user_id: Annotated[str, Depends(get_current_user)],
    tier: Annotated[Tier, Depends(get_current_tier)],
) -> AgentSessionState:
    record = _load_session(user_id, session_id)

    if record.get("state") != "awaiting_clarification":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Session is in state '{record.get('state')}' and cannot be "
                "clarified. Only 'awaiting_clarification' sessions accept a clarify()."
            ),
        )

    # Backfill autonomy for sessions created before this field existed; an empty
    # value keeps the env default behaviour unchanged.
    if "autonomy" not in record:
        record["autonomy"] = ""
        _save_session(user_id, record)

    question = record.get("pending_question", "")
    pending_skippable = bool(record.get("pending_skippable", False))
    pending_fact_key = record.get("pending_fact_key", "") or ""
    answer = req.answer.strip()
    skipping = bool(getattr(req, "skip", False))

    if skipping:
        if not pending_skippable:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "The pending clarification is not marked skippable. "
                    "Provide an answer or raise priority before skipping."
                ),
            )
        # Record an explicit 'unknown' assumption so the evidence pack
        # reflects the user's choice. The LLM sees this as the answer
        # and is instructed to flag residual assumptions.
        answer = answer or (
            f"[SKIPPED by user — fact '{pending_fact_key}' treated as "
            "unknown; flag assumption in the final report]"
            if pending_fact_key
            else "[SKIPPED by user — treat this datum as unknown and "
            "flag the assumption in the final report]"
        )
    elif not answer:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="answer must be non-empty unless skip=true is set.",
        )

    # Round 7: if the agent suspended through ClarifierStore, record the
    # answer there so legacy and Phase-7 paths share the same resume surface.
    resume_token = record.get("resume_token", "")
    if resume_token:
        try:
            from ..agent.clarifier import ClarifierStore, ToolError as _ClarifierError

            ClarifierStore().answer(
                resume_token=str(resume_token),
                tenant_id=user_id,
                answer=answer,
            )
        except _ClarifierError:
            logger.warning("clarifier answer failed for token %s", str(resume_token)[:8])
        except Exception:  # pragma: no cover — best-effort persistence
            logger.exception("unexpected clarifier answer error")

    # Round 7 — unified dialogue-tracker resume. If the suspended question
    # carries a dialogue-state snapshot, the tracker interprets the answer
    # and may produce a follow-up confirm/repair/probe before the agent runs.
    clarification_state, tracker_for_agent, _ = _resume_via_tracker(
        user_id=user_id,
        tenant_id=user_id,
        record=record,
        answer=answer,
        skip=skipping,
        token=resume_token,
    )
    if clarification_state is not None:
        return clarification_state

    # Legacy fallback or tracker with no dialogue snapshot: append the Q/A
    # and continue the agent run with the usual text-replay context.
    if tracker_for_agent is None:
        _append_clarification(record, question, answer, skipped=skipping)

    # CRP integration: extract structured facts from the free-text answer
    # and check them against prior CKF facts for contradictions. The
    # results are written into the session record so the resumed agent
    # sees them as authoritative context.
    extracted_count = 0
    contradictions: list[dict[str, Any]] = []
    if not skipping and answer:
        try:
            from ..agent.crp_integration import (
                detect_ckf_contradictions,
                extract_facts_from_text,
            )

            extracted = extract_facts_from_text(
                answer,
                source_window_id=f"clarify:{session_id}",
                category="user_clarification",
            )
            extracted_count = extracted.fact_count

            # Best-effort: contradict against this user's CKF if the
            # agent has one wired up. We keep this defensive because the
            # API layer cannot assume a fabric is available in test mode.
            try:
                from ..agent.tools import default_registry as _dr  # noqa: F401
                from .deps import get_ckf_for_user  # type: ignore[attr-defined]

                fabric = get_ckf_for_user(user_id)
                if fabric is not None and extracted.facts:
                    prior = list(getattr(fabric.query(max_results=200), "facts", []) or [])
                    contradictions = detect_ckf_contradictions(extracted.facts, prior)
            except Exception:
                logger.debug(
                    "ckf contradiction detection skipped session=%s",
                    session_id,
                    exc_info=True,
                )
        except Exception:
            logger.debug("extraction pipeline skipped session=%s", session_id, exc_info=True)

    if extracted_count or contradictions:
        record["clarification_extraction"] = {
            "facts_extracted": extracted_count,
            "contradictions": contradictions,
        }

    record["state"] = "running"
    _clear_pending_clarification(record)
    _save_session(user_id, record)

    # Build augmented context so the resumed run has the Q/A visible.
    clarifications = list(record.get("clarifications", []))
    base_ctx = record.get("extra_context", "")
    merged_ctx = _merge_clarifications(base_ctx, clarifications)

    profile = record.get("org_profile") or _load_profile(record.get("customer_id"), user_id)
    agent = _build_agent(
        user_id=user_id,
        max_iters=int(record.get("max_iters", 8)),
        profile=profile,
        autonomy=record.get("autonomy"),
    )
    try:
        result = await _run_agent_async(
            agent,
            task=record.get("task", ""),
            system_id=record.get("system_id", ""),
            customer_id=record.get("customer_id", ""),
            session_id=session_id,
            extra_context=merged_ctx,
            clarifications_used=len(clarifications),
        )
    except Exception as exc:
        logger.exception("agent_clarify failed session=%s", session_id)
        record["state"] = "error"
        record["error"] = f"{type(exc).__name__}: {exc}"
        _save_session(user_id, record)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Agent resume failed: {exc}",
        ) from exc

    _apply_result(record, result)
    _save_session(user_id, record)
    return _record_to_state(record)


@router.post(
    "/{session_id}/finalize",
    response_model=AgentFinalizeResponse,
    summary="Persist the session's final_text as a retrievable ComplianceReport.",
    dependencies=[Depends(require_agent_access), Depends(meter_call("agent_finalize"))],
)
async def agent_finalize(
    session_id: Annotated[str, PathParam(min_length=6, max_length=80)],
    req: AgentFinalizeRequest,
    user_id: Annotated[str, Depends(get_current_user)],
    tier: Annotated[Tier, Depends(get_current_tier)],
) -> AgentFinalizeResponse:
    record = _load_session(user_id, session_id)

    if record.get("state") != "done":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot finalize a session in state '{record.get('state')}'. "
                "Only 'done' sessions can be finalized."
            ),
        )

    final_text = record.get("final_text", "") or ""
    if not final_text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Session has no final_text to persist.",
        )

    system_name = req.system_name.strip() or record.get("system_id", "") or "unspecified-system"
    generated_at = _now_iso()

    payload: dict[str, Any] = {
        "session_id": session_id,
        "task": record.get("task", ""),
        "system_id": record.get("system_id", ""),
        "customer_id": record.get("customer_id", ""),
        "iterations": record.get("iterations", 0),
        "tool_calls": record.get("tool_calls", 0),
        "facts_stored": record.get("facts_stored", 0),
        "clarifications": record.get("clarifications", []),
        "generated_at": generated_at,
    }
    if req.include_trace and record.get("trace_path"):
        payload["trace_path"] = record["trace_path"]

    report_id: str | None = None
    try:
        from .reports import get_report_store

        rec = get_report_store().save(
            user_id=user_id,
            kind="agent_session",
            system_name=system_name,
            tier=tier.value,
            payload=payload,
            markdown=final_text,
        )
        report_id = rec.get("id")
    except Exception as exc:
        logger.warning("agent report persist failed: %s", exc)

    return AgentFinalizeResponse(
        session_id=session_id,
        report_id=report_id,
        markdown=final_text,
        system_name=system_name,
        generated_at=generated_at,
    )


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an agent session (soft — removes state file only).",
    dependencies=[Depends(require_agent_access)],
)
async def agent_delete(
    session_id: Annotated[str, PathParam(min_length=6, max_length=80)],
    user_id: Annotated[str, Depends(get_current_user)],
    tier: Annotated[Tier, Depends(get_current_tier)],
) -> None:
    store = _session_store or get_json_store("agent_sessions")
    try:
        store.delete(_session_key(user_id, session_id))
    except Exception as exc:  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete session: {exc}",
        )
    # 204 No Content — deleting a non-existent session is idempotent


@router.post(
    "/{session_id}/feedback",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Record per-answer / per-fact feedback and update learned preferences.",
    dependencies=[Depends(require_agent_access), Depends(meter_call("agent_feedback"))],
)
async def agent_feedback(
    session_id: Annotated[str, PathParam(min_length=6, max_length=80)],
    req: AgentFeedbackRequest,
    user_id: Annotated[str, Depends(get_current_user)],
    tier: Annotated[Tier, Depends(get_current_tier)],
    tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> None:
    """Phase 5a — record explicit feedback and learn from it.

    Writes three durable artefacts:

    1. A rich JSONL entry under ``data/feedback/<user>.jsonl``.
    2. A CRP per-fact RLHF signal when ``fact_id`` is provided.
    3. An update to the user's learned :class:`UserPreferenceProfile`.

    The CRP fact signal remains best-effort so a missing provider or
    offline user still sees their rating recorded.
    """
    record = _load_session(user_id, session_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )

    # 1. Append to the per-user feedback ledger.
    data_dir = os.environ.get("CRP_COMPLY_DATA_DIR", "data")
    ledger_dir = Path(data_dir) / "feedback"
    try:
        ledger_dir.mkdir(parents=True, exist_ok=True)
        ledger_path = ledger_dir / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', user_id)}.jsonl"
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "fact_id": req.fact_id,
            "signal": req.signal,
            "reason": req.reason,
            "message_id": req.message_id,
            "rating": req.rating,
            "helpful": req.helpful,
            "comment": req.comment,
            "regulation": req.regulation,
            "depth": req.depth,
            "format": req.format,
            "audience": req.audience,
            "sources": req.sources,
            "original_text": req.original_text,
            "edited_text": req.edited_text,
            "section_id": req.section_id,
            "user_id": user_id,
        }
        with ledger_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        logger.warning("failed to append feedback ledger", exc_info=True)

    # 2. Update the learned preference profile (best-effort).
    try:
        store = get_preference_store()
        profile = store.load(tenant_id, user_id)
        learner = PreferenceLearner()
        learner.update_from_feedback(profile, entry)
        store.save(profile)
    except Exception:
        logger.debug("preference learning failed (best-effort)", exc_info=True)

    # 3. Forward the signal into CRP's feedback loop when a fact is targeted.
    if req.fact_id:
        try:
            from ..agent.crp_integration import crp_apply_feedback

            llm = ComplianceLLM.for_user(user_id)
            if llm is not None and getattr(llm, "provider", None) is not None:
                result = crp_apply_feedback(
                    llm.provider,
                    fact_id=req.fact_id,
                    signal=req.signal,
                    reason=req.reason,
                )
                if result.get("error"):
                    logger.debug("crp feedback non-fatal: %s", result["error"])
        except Exception:
            logger.debug("crp feedback wiring failed (best-effort)", exc_info=True)
    # 204 No Content


@router.get(
    "/{session_id}/feedback",
    summary="List explicit feedback entries recorded for a session.",
)
async def agent_feedback_list(
    session_id: Annotated[str, PathParam(min_length=6, max_length=80)],
    user_id: Annotated[str, Depends(get_current_user)],
) -> list[dict[str, Any]]:
    """Return ledger entries for the requested session, filtered to this user."""
    record = _load_session(user_id, session_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )
    data_dir = os.environ.get("CRP_COMPLY_DATA_DIR", "data")
    ledger_path = Path(data_dir) / "feedback" / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', user_id)}.jsonl"
    out: list[dict[str, Any]] = []
    if not ledger_path.exists():
        return out
    try:
        with ledger_path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("session_id") == session_id:
                    out.append(e)
    except OSError:
        logger.warning("failed to read feedback ledger", exc_info=True)
    return out


# ═══════════════════════════════════════════════════════════════
# Phase 5: user preference surface + direct CRP capabilities
# (preview / estimate / export — see CRP_AUDIT_4 §C)
# ═══════════════════════════════════════════════════════════════


@router.post(
    "/preview",
    summary="Preview the CRP envelope that would be packed for a task (no dispatch).",
    dependencies=[Depends(require_agent_access), Depends(meter_call("agent_preview"))],
)
async def agent_preview(
    req: AgentPreviewRequest,
    user_id: Annotated[str, Depends(get_current_user)],
    tier: Annotated[Tier, Depends(get_current_tier)],
) -> dict[str, Any]:
    """CRP_AUDIT_4 §C.3 — surface ``client.preview_envelope`` so the UI
    can show *what the model is about to see* before committing."""
    from ..agent.crp_integration import crp_preview_envelope

    try:
        llm = ComplianceLLM.for_user(user_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"No LLM provider configured: {exc}",
        ) from exc

    full_task = req.task
    if req.extra_context.strip():
        full_task = f"{req.extra_context.strip()}\n\nTask:\n{req.task}"

    return crp_preview_envelope(
        llm.provider,
        system_prompt="",
        task=full_task,
    )


@router.post(
    "/estimate",
    summary="Estimate token / cost budget for a task before dispatch.",
    dependencies=[Depends(require_agent_access), Depends(meter_call("agent_estimate"))],
)
async def agent_estimate(
    req: AgentEstimateRequest,
    user_id: Annotated[str, Depends(get_current_user)],
    tier: Annotated[Tier, Depends(get_current_tier)],
) -> dict[str, Any]:
    """CRP_AUDIT_4 §C.4 — surface ``client.estimate_session`` so users
    on metered providers see the expected spend up-front."""
    from ..agent.crp_integration import crp_estimate_session

    try:
        llm = ComplianceLLM.for_user(user_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"No LLM provider configured: {exc}",
        ) from exc

    full_task = req.task
    if req.extra_context.strip():
        full_task = f"{req.extra_context.strip()}\n\nTask:\n{req.task}"

    return crp_estimate_session(
        llm.provider,
        system_prompt="",
        task=full_task,
        planned_dispatches=req.planned_dispatches,
        avg_output_tokens=req.avg_output_tokens,
    )


@router.get(
    "/{session_id}/export-sealed",
    summary="Export an AES-256-GCM sealed CRP state bundle for the session.",
    dependencies=[Depends(require_agent_access), Depends(meter_call("agent_export_sealed"))],
)
async def agent_export_sealed(
    session_id: Annotated[str, PathParam(min_length=6, max_length=80)],
    user_id: Annotated[str, Depends(get_current_user)],
    tier: Annotated[Tier, Depends(get_current_tier)],
) -> Any:
    """CRP_AUDIT_4 §C.6 — surface ``client.export_state`` so users can
    hand off audit-grade sealed evidence (AES-256-GCM) for a session.
    The bundle includes the WarmStateStore contents, fact integrity
    chain, and dispatch traces — verifiable offline."""
    from fastapi.responses import Response
    from ..agent.crp_integration import crp_export_state_bytes

    record = _load_session(user_id, session_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session {session_id} not found",
        )

    try:
        llm = ComplianceLLM.for_user(user_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"No LLM provider configured: {exc}",
        ) from exc

    # Pre-ingest the session's task + final output so the exported
    # bundle actually carries the audit content. Without this the
    # sealed bundle would be empty (the per-request CRP client has no
    # prior session memory).
    pre_ingest: list[dict[str, Any]] = []
    task = record.get("task", "")
    if task:
        pre_ingest.append({"text": task, "source": f"session:{session_id}:task"})
    final_text = record.get("final_text", "") or record.get("final_answer", "")
    if final_text:
        pre_ingest.append({"text": final_text, "source": f"session:{session_id}:answer"})
    for c in record.get("clarifications", []) or []:
        if isinstance(c, dict) and c.get("answer"):
            pre_ingest.append(
                {
                    "text": str(c.get("answer", "")),
                    "source": f"session:{session_id}:clarification",
                }
            )

    payload, content_type = crp_export_state_bytes(
        llm.provider,
        pre_ingest=pre_ingest,
    )
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="export_state unavailable (install crprotocol[full] for AES-256-GCM seal)",
        )
    filename = f"crp-session-{session_id}.sealed"
    return Response(
        content=payload,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ═══════════════════════════════════════════════════════════════
# Phase 2: SSE streaming + follow-up turn (continue)
# ═══════════════════════════════════════════════════════════════


def _sse_format(event: str, data: Any) -> str:
    """Encode a single ``text/event-stream`` frame.

    Multi-line ``data`` payloads are split across multiple ``data:``
    lines per the EventStream spec. Final blank line terminates the
    frame.

    For Phase 7 ``loop.*`` events we additionally schema-validate the
    payload against :mod:`crp_comply.api.events` before serialising,
    so a malformed loop event fails loudly rather than reaching the
    browser as an unparseable frame. Legacy event names (``tool_call``,
    ``llm_turn``, ``crp_*``) pass through unchanged \u2014 see PHASE_7
    \u00a721 7.0 (the 7.0 sub-phase is purely additive).
    """
    # Schema-check loop.* events. We import lazily so this module stays
    # importable in environments where pydantic isn't loaded yet.
    if isinstance(event, str) and event.startswith("loop."):
        try:
            from .events import LoopEventError, is_loop_event, validate_event

            if is_loop_event(event):
                payload = data if isinstance(data, dict) else {"raw": data}
                try:
                    data = validate_event(event, payload)
                except LoopEventError as exc:  # pragma: no cover - logged
                    logger.warning("dropping malformed loop event: %s", exc)
                    data = {"event": event, "error": str(exc)}
                    event = "loop.error"
        except Exception:  # pragma: no cover - defensive
            logger.debug("loop event validation skipped", exc_info=True)
    try:
        body = json.dumps(data, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        body = json.dumps({"raw": str(data)})
    lines = [f"event: {event}"]
    for line in body.splitlines() or [""]:
        lines.append(f"data: {line}")
    lines.append("")
    lines.append("")
    return "\n".join(lines)


async def _stream_agent_run(
    *,
    user_id: str,
    record: dict[str, Any],
    task: str,
    extra_context: str,
    clarifications_used: int,
    prior_messages: list[dict[str, Any]] | None = None,
    profile: dict[str, Any] | None = None,
    autonomy: str | None = None,
):
    """Async generator producing SSE frames for one agent ``run`` call.

    Pipes orchestrator trace events through an ``asyncio.Queue`` while
    the blocking ``ComplianceAgent.run`` executes in a worker thread.
    On completion, applies the result to ``record``, persists, and
    yields a terminal ``state`` frame so the browser can refresh.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue(maxsize=512)
    SENTINEL = object()

    def _emit(event_dict: dict[str, Any]) -> None:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, event_dict)
        except RuntimeError:  # pragma: no cover - loop already gone
            pass

    agent = _build_agent(
        user_id=user_id,
        max_iters=int(record.get("max_iters", 8)),
        profile=profile,
        autonomy=autonomy if autonomy is not None else record.get("autonomy"),
    )
    agent.event_sink = _emit

    def _runner():
        try:
            kwargs: dict[str, Any] = {
                "system_id": record.get("system_id", ""),
                "customer_id": record.get("customer_id", ""),
                "session_id": record["session_id"],
                "extra_context": extra_context,
                "clarifications_used": clarifications_used,
            }
            if prior_messages:
                # Best-effort \u2014 only pass if the orchestrator accepts it
                # (test doubles may not).
                import inspect as _inspect

                try:
                    sig = _inspect.signature(agent.run)
                    if "prior_messages" in sig.parameters or any(
                        p.kind == _inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
                    ):
                        kwargs["prior_messages"] = prior_messages
                except (TypeError, ValueError):
                    pass
            return agent.run(task, **kwargs)
        except Exception as exc:  # pragma: no cover - reported via SSE
            _emit({"event": "run_failed", "error": f"{type(exc).__name__}: {exc}"})
            return exc
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, SENTINEL)

    fut = loop.run_in_executor(None, _runner)

    # Initial frame so the client can confirm the stream is live before
    # the LLM produces anything.
    yield _sse_format("opened", {"session_id": record["session_id"]})

    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=20.0)
            except asyncio.TimeoutError:
                # Heartbeat keeps proxies + browsers from killing the
                # stream during long LLM stalls.
                yield ": ping\n\n"
                continue
            if item is SENTINEL:
                break
            evt_name = str(item.get("event") or "trace")
            yield _sse_format(evt_name, item)
    finally:
        agent.event_sink = None

    result = await fut
    if isinstance(result, Exception):
        record["state"] = "error"
        record["error"] = f"{type(result).__name__}: {result}"
        _save_session(user_id, record)
        yield _sse_format("error", {"message": record["error"]})
        yield _sse_format("done", _record_to_state(record).model_dump())
        return

    _apply_result(record, result)
    _save_session(user_id, record)
    yield _sse_format("done", _record_to_state(record).model_dump())


@router.post(
    "/start/stream",
    summary="Start a new agent session and stream progress as text/event-stream.",
    dependencies=[Depends(require_agent_access), Depends(meter_call("agent_start"))],
)
async def agent_start_stream(
    req: AgentStartRequest,
    user_id: Annotated[str, Depends(get_current_user)],
    tier: Annotated[Tier, Depends(get_current_tier)],
) -> StreamingResponse:
    if user_id == "anonymous":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Agent sessions require authentication.",
        )

    session_id = uuid.uuid4().hex
    record: dict[str, Any] = {
        "session_id": session_id,
        "user_id": user_id,
        "tier": tier.value,
        "task": req.task,
        "system_id": req.system_id,
        "customer_id": req.customer_id,
        "extra_context": req.extra_context,
        "max_iters": int(req.max_iters),
        "autonomy": req.autonomy,
        "state": "running",
        "iterations": 0,
        "tool_calls": 0,
        "facts_stored": 0,
        "pending_question": "",
        "pending_context": "",
        "final_text": "",
        "error": "",
        "clarifications": [],
        "messages": [],
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "trace_path": "",
    }
    _save_session(user_id, record)
    _append_user_message(record, req.task)

    profile = _load_profile(req.customer_id, user_id)
    if profile:
        record["org_profile"] = profile
        _save_session(user_id, record)

    headers = {
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return StreamingResponse(
        _stream_agent_run(
            user_id=user_id,
            record=record,
            task=req.task,
            extra_context=req.extra_context,
            clarifications_used=0,
            profile=profile,
            autonomy=req.autonomy,
        ),
        media_type="text/event-stream",
        headers=headers,
    )


@router.post(
    "/{session_id}/clarify/stream",
    summary="Answer a pending clarification and stream the resumed run.",
    dependencies=[Depends(require_agent_access), Depends(meter_call("agent_clarify"))],
)
async def agent_clarify_stream(
    session_id: Annotated[str, PathParam(min_length=6, max_length=80)],
    req: AgentClarifyRequest,
    user_id: Annotated[str, Depends(get_current_user)],
    tier: Annotated[Tier, Depends(get_current_tier)],
) -> StreamingResponse:
    record = _load_session(user_id, session_id)
    if record.get("state") != "awaiting_clarification":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Session is in state '{record.get('state')}' and cannot be "
                "clarified. Only 'awaiting_clarification' sessions accept a clarify()."
            ),
        )

    # Backfill autonomy for sessions created before this field existed.
    if "autonomy" not in record:
        record["autonomy"] = ""
        _save_session(user_id, record)

    pending_skippable = bool(record.get("pending_skippable", False))
    pending_fact_key = record.get("pending_fact_key", "") or ""
    answer = (req.answer or "").strip()
    skipping = bool(getattr(req, "skip", False))
    if skipping:
        if not pending_skippable:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "The pending clarification is not marked skippable. "
                    "Provide an answer or raise priority before skipping."
                ),
            )
        answer = answer or (
            f"[SKIPPED by user — fact '{pending_fact_key}' treated as unknown; "
            "flag assumption in the final report]"
            if pending_fact_key
            else "[SKIPPED by user — treat this datum as unknown and flag the "
            "assumption in the final report]"
        )
    elif not answer:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="answer must be non-empty unless skip=true is set.",
        )

    # Round 7: mark the token answered and try the unified tracker resume.
    resume_token = record.get("resume_token", "")
    if resume_token:
        try:
            from ..agent.clarifier import ClarifierStore, ToolError as _ClarifierError

            ClarifierStore().answer(
                resume_token=resume_token,
                tenant_id=user_id,
                answer=answer,
            )
        except _ClarifierError:
            logger.warning("clarifier answer failed for token %s", str(resume_token)[:8])
        except Exception:
            logger.exception("unexpected clarifier answer error")

    clarification_state, tracker_for_agent, _ = _resume_via_tracker(
        user_id=user_id,
        tenant_id=user_id,
        record=record,
        answer=answer,
        skip=skipping,
        token=resume_token,
    )

    headers = {
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }

    if clarification_state is not None:
        # The tracker produced a follow-up confirm/repair/probe question.
        async def _followup_stream():
            yield _sse_format("done", clarification_state.model_dump())

        return StreamingResponse(
            _followup_stream(),
            media_type="text/event-stream",
            headers=headers,
        )

    if tracker_for_agent is None:
        _append_clarification(record, record.get("pending_question", ""), answer, skipped=skipping)
    record["state"] = "running"
    _clear_pending_clarification(record)
    _save_session(user_id, record)

    clarifications = list(record.get("clarifications", []))
    base_ctx = record.get("extra_context", "")
    merged_ctx = _merge_clarifications(base_ctx, clarifications)

    profile = record.get("org_profile") or _load_profile(record.get("customer_id"), user_id)

    return StreamingResponse(
        _stream_agent_run(
            user_id=user_id,
            record=record,
            task=record.get("task", ""),
            extra_context=merged_ctx,
            clarifications_used=len(clarifications),
            profile=profile,
        ),
        media_type="text/event-stream",
        headers=headers,
    )


@router.post(
    "/{session_id}/continue",
    response_model=AgentSessionState,
    summary="Send a follow-up turn into a closed agent session (non-streaming).",
    dependencies=[Depends(require_agent_access), Depends(meter_call("agent_continue"))],
)
async def agent_continue(
    session_id: Annotated[str, PathParam(min_length=6, max_length=80)],
    req: AgentContinueRequest,
    user_id: Annotated[str, Depends(get_current_user)],
    tier: Annotated[Tier, Depends(get_current_tier)],
) -> AgentSessionState:
    record = _load_session(user_id, session_id)
    state = record.get("state")
    if state not in {"done", "max_iters", "error"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Session is in state '{state}' and is not ready for a "
                "follow-up turn. Use /clarify when awaiting_clarification."
            ),
        )

    new_task, merged_ctx = _prepare_continuation(record, req.message)
    # Phase 6 multi-turn \u2014 the new user message becomes part of the
    # session history immediately so the orchestrator's prior_messages
    # replay sees it (the orchestrator drops the trailing user msg
    # because it appends `safe_task` itself, but persisting the user
    # message before the run lets us recover correctly if the agent
    # crashes mid-turn).
    _append_user_message(record, req.message)
    prior_msgs = _select_history_for_run(record, new_user_message=req.message)
    # Drop the trailing entry which is the active user message; it's
    # appended by the orchestrator itself.
    if (
        prior_msgs
        and prior_msgs[-1].get("role") == "user"
        and prior_msgs[-1].get("content") == req.message.strip()
    ):
        prior_msgs = prior_msgs[:-1]
    record.update(
        {
            "task": new_task,
            "extra_context": merged_ctx,
            "state": "running",
            "final_text": "",
            "error": "",
            "pending_question": "",
            "pending_context": "",
            "pending_priority": "",
            "pending_skippable": False,
            "pending_fact_key": "",
        }
    )
    _save_session(user_id, record)

    profile = record.get("org_profile") or _load_profile(record.get("customer_id"), user_id)
    agent = _build_agent(
        user_id=user_id,
        max_iters=int(record.get("max_iters", 8)),
        profile=profile,
        autonomy=record.get("autonomy"),
    )
    try:
        result = await _run_agent_async(
            agent,
            task=new_task,
            system_id=record.get("system_id", ""),
            customer_id=record.get("customer_id", ""),
            session_id=session_id,
            extra_context=merged_ctx,
            prior_messages=prior_msgs,
        )
    except Exception as exc:
        logger.exception("agent_continue failed session=%s", session_id)
        record["state"] = "error"
        record["error"] = f"{type(exc).__name__}: {exc}"
        _save_session(user_id, record)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Agent continue failed: {exc}",
        ) from exc

    _apply_result(record, result)
    _save_session(user_id, record)
    return _record_to_state(record)


@router.post(
    "/{session_id}/continue/stream",
    summary="Stream a follow-up turn on a closed agent session.",
    dependencies=[Depends(require_agent_access), Depends(meter_call("agent_continue"))],
)
async def agent_continue_stream(
    session_id: Annotated[str, PathParam(min_length=6, max_length=80)],
    req: AgentContinueRequest,
    user_id: Annotated[str, Depends(get_current_user)],
    tier: Annotated[Tier, Depends(get_current_tier)],
) -> StreamingResponse:
    record = _load_session(user_id, session_id)
    state = record.get("state")
    if state not in {"done", "max_iters", "error"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Session is in state '{state}' and is not ready for a "
                "follow-up turn. Use /clarify/stream when awaiting_clarification."
            ),
        )

    new_task, merged_ctx = _prepare_continuation(record, req.message)
    _append_user_message(record, req.message)
    prior_msgs = _select_history_for_run(record, new_user_message=req.message)
    if (
        prior_msgs
        and prior_msgs[-1].get("role") == "user"
        and prior_msgs[-1].get("content") == req.message.strip()
    ):
        prior_msgs = prior_msgs[:-1]
    record.update(
        {
            "task": new_task,
            "extra_context": merged_ctx,
            "state": "running",
            "final_text": "",
            "error": "",
            "pending_question": "",
            "pending_context": "",
            "pending_priority": "",
            "pending_skippable": False,
            "pending_fact_key": "",
        }
    )
    _save_session(user_id, record)

    profile = record.get("org_profile") or _load_profile(record.get("customer_id"), user_id)

    headers = {
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return StreamingResponse(
        _stream_agent_run(
            user_id=user_id,
            record=record,
            task=new_task,
            extra_context=merged_ctx,
            clarifications_used=0,
            prior_messages=prior_msgs,
            profile=profile,
        ),
        media_type="text/event-stream",
        headers=headers,
    )


def _prepare_continuation(record: dict[str, Any], new_message: str) -> tuple[str, str]:
    """Build the follow-up ``(task, extra_context)`` pair.

    Phase 6 \u2014 the prior task/answer/clarifications are now replayed
    as proper chat messages via ``_select_history_for_run``, so this
    helper only needs to:

    1. Strip the new user message into the active task.
    2. Preserve the original ``extra_context`` (system metadata) and
       fold any *clarifications-only* slice that didn't make it into
       the message log into a one-line marker so authoritative
       answers survive even if the message list gets trimmed.
    """
    base_ctx = (record.get("extra_context") or "").strip()
    parts: list[str] = []
    if base_ctx:
        parts.append(base_ctx)
    clarifications = list(record.get("clarifications", []))
    if clarifications:
        parts.append(
            "Authoritative clarifications gathered earlier in this session (do NOT re-ask):"
        )
        for i, pair in enumerate(clarifications, 1):
            q = (pair.get("question") or "").strip()
            a = (pair.get("answer") or "").strip()
            if q and a:
                parts.append(f"{i}. Q: {q}\n   A: {a}")
    merged_ctx = "\n\n".join(parts)

    try:
        cap = int(os.environ.get("CRP_COMPLY_CONTINUATION_CTX_CHARS", "6000"))
    except ValueError:
        cap = 6000
    if cap > 0 and len(merged_ctx) > cap:
        elided = len(merged_ctx) - cap
        merged_ctx = (
            f"[CRP-folded: {elided} chars of older context elided. "
            "Prior facts persist in the session CKF \u2014 call ``recall_facts`` "
            "if you need them.]\n\n" + merged_ctx[-cap:]
        )

    return new_message.strip(), merged_ctx


# ═══════════════════════════════════════════════════════════════
# Phase 7.15 — live language-agent loop endpoint
# ═══════════════════════════════════════════════════════════════
#
# This endpoint flips the Phase 7 shelf modules (triage, cache, FSM,
# reflector, budget) into the production request path. It runs the
# loop runtime in :mod:`crp_comply.agent.loop_runtime` and SSE-encodes
# the typed ``loop.*`` events for the frontend reasoning tape.
#
# Backwards compatibility: ``/agent/start/stream`` is unchanged. UIs
# opt into the loop by hitting ``/agent/loop/stream``.


@router.post(
    "/loop/stream",
    summary="Start a Phase 7 reasoning loop and stream typed loop.* events.",
    dependencies=[
        Depends(require_agent_access),
        Depends(meter_call("agent_loop")),
    ],
)
async def agent_loop_stream(
    req: AgentStartRequest,
    user_id: Annotated[str, Depends(get_current_user)],
    tier: Annotated[Tier, Depends(get_current_tier)],
) -> StreamingResponse:
    """Open a streaming language-agent loop for a single user query.

    Behaviour (PHASE_7 §3, §14, §21):

    * Triage → Cache → Plan → Step×N → Reflect → Finalise.
    * Lane A (cache hit): ``loop.triage`` + ``loop.cache.hit`` + ``loop.final``.
    * Lane B / C: full reasoning tape with ``loop.thought.delta``,
      ``loop.tool.call`` / ``loop.tool.result`` per step.
    * Budget enforcement + ``loop.abort`` on breach.
    """
    if user_id == "anonymous":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Agent loop sessions require authentication.",
        )

    session_id = uuid.uuid4().hex
    # Mirror the start_stream session record so the existing list /
    # delete / poll endpoints remain useful for loop runs too.
    record: dict[str, Any] = {
        "session_id": session_id,
        "user_id": user_id,
        "tier": tier.value,
        "task": req.task,
        "system_id": req.system_id,
        "customer_id": req.customer_id,
        "extra_context": req.extra_context,
        "max_iters": int(req.max_iters),
        "autonomy": req.autonomy,
        "state": "running",
        "iterations": 0,
        "tool_calls": 0,
        "facts_stored": 0,
        "pending_question": "",
        "pending_context": "",
        "final_text": "",
        "error": "",
        "clarifications": [],
        "messages": [],
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "trace_path": "",
        "mode": "loop",
    }
    _save_session(user_id, record)
    _append_user_message(record, req.task)

    headers = {
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return StreamingResponse(
        _stream_loop_run(
            user_id=user_id,
            tenant_id=req.customer_id or user_id,
            record=record,
            task=req.task,
            extra_context=req.extra_context,
            depth=req.depth,
            autonomy=req.autonomy,
        ),
        media_type="text/event-stream",
        headers=headers,
    )


async def _stream_loop_run(
    *,
    user_id: str,
    tenant_id: str,
    record: dict[str, Any],
    task: str,
    extra_context: str,
    profile: dict[str, Any] | None = None,
    memory: CompliantMemory | None = None,
    dialogue_tracker: Any | None = None,
    depth: str = "",
    autonomy: str | None = None,
):
    """Async generator: drive the Phase 7 loop runtime and yield SSE frames."""
    from ..agent.loop_runtime import LoopRuntimeConfig, run_loop_stream

    # Phase 7.22 follow-up — the AgentCache was short-circuiting the
    # chat endpoint: a stale cache hit returned a previous (often
    # templated) answer with NO LLM call, so users saw "default
    # hardcoded template shows up" while LM Studio sat idle. With
    # always-on CRP evidence priming the LLM round-trip is now cheap
    # enough to re-run, and answers are evidence-fresh per turn.
    # Default OFF for the chat path; opt back in via env var.
    _cache_env = os.environ.get("CRP_COMPLY_AGENT_CACHE_ENABLED", "0")
    cache_enabled = _cache_env.strip().lower() in {"1", "true", "yes", "on"}

    # Phase 5a — load the user's learned preference profile. This is the
    # only place in the request path that touches the preference store.
    pref_store = get_preference_store()
    user_preference = pref_store.load(tenant_id or user_id, user_id)

    def _loop_agent_builder(user_id: str, max_iters: int) -> Any:
        return _build_agent(
            user_id=user_id,
            max_iters=max_iters,
            profile=profile,
            preferred_regulations=user_preference.preferred_regulations or None,
            autonomy=autonomy if autonomy is not None else record.get("autonomy"),
        )

    # Blend the user's preferred depth/format into the runtime config and
    # append a short footnote to the system context so the model knows it
    # can be overridden by explicit user instructions.
    effective_extra = extra_context or ""
    pref_footnote = user_preference.system_prompt_footnote()
    if pref_footnote:
        effective_extra = f"{effective_extra}\n\n{pref_footnote}".strip()

    cfg = LoopRuntimeConfig(
        user_id=user_id,
        tenant_id=tenant_id or user_id,
        session_id=record["session_id"],
        task=task,
        extra_context=effective_extra,
        depth=depth or user_preference.preferred_depth or "standard",
        cache_enabled=cache_enabled,
    )

    # Initial frame so the client confirms the stream is live before the
    # LLM has produced anything.
    yield _sse_format(
        "loop.opened",
        {
            "session_id": record["session_id"],
            "query": task,
            "run_id": "",
        },
    )

    final_text = ""
    final_citations: list[dict[str, Any]] = []
    state = "running"

    # 7.17 — heartbeat keepalive. Local providers (LM Studio / Ollama)
    # can spend 30-60s on prompt processing for long contexts; many
    # proxies / Cloudflare / Chrome's HTTP/3 stack will drop the SSE
    # connection after ~30s of silence with ERR_QUIC_PROTOCOL_ERROR.
    # We race the runtime iterator against a 10s timeout and emit an
    # SSE comment line whenever the runtime is silent so the
    # connection stays warm end-to-end.
    HEARTBEAT_INTERVAL_S = 10.0

    try:
        runtime_iter = run_loop_stream(
            cfg,
            agent_builder=_loop_agent_builder,
            memory=memory,
            dialogue_tracker=dialogue_tracker,
            user_preference=user_preference,
        ).__aiter__()
        while True:
            next_task = asyncio.create_task(runtime_iter.__anext__())
            # 7.23 — keep firing keepalives every HEARTBEAT_INTERVAL_S
            # until the next runtime event arrives. The previous version
            # only emitted ONE keepalive then awaited with no timeout, so
            # any LLM round-trip > ~40s caused Chrome's HTTP/3 stack to
            # drop the connection with ERR_QUIC_PROTOCOL_ERROR. That in
            # turn cancelled the StreamingResponse generator, which
            # cancelled agent.run() before LM Studio was ever called —
            # exactly the symptom users were reporting.
            ev: dict[str, Any] | None = None
            while True:
                try:
                    ev = await asyncio.wait_for(
                        asyncio.shield(next_task),
                        timeout=HEARTBEAT_INTERVAL_S,
                    )
                    break
                except asyncio.TimeoutError:
                    # Comment-only SSE frame; invisible to clients but
                    # resets idle timers on every hop. Loop again.
                    yield ": keepalive\n\n"
                    continue
                except StopAsyncIteration:
                    ev = None
                    break
            if ev is None:
                break

            evt_name = str(ev.get("event") or "loop.heartbeat")
            yield _sse_format(evt_name, ev)
            if evt_name == "loop.final":
                final_text = str(ev.get("summary") or "")
                final_citations = list(ev.get("citations") or [])
                state = "done"
            elif evt_name == "loop.abort":
                state = "aborted"
            elif evt_name == "loop.error":
                state = "error"
            elif evt_name == "loop.clarifier.ask":
                # Round 7 — surface the suspended clarification in the
                # session record so polling clients resume correctly.
                record["state"] = "awaiting_clarification"
                record["pending_question"] = str(ev.get("question") or "")
                record["pending_options"] = list(ev.get("options") or [])
                record["resume_token"] = str(ev.get("resume_token") or "")
                record["pending_action"] = str(ev.get("action") or "probe")
                record["pending_priority"] = "medium"
                record["pending_skippable"] = False
                state = "awaiting_clarification"
    except Exception as exc:  # pragma: no cover — surface as SSE
        logger.exception("loop runtime crashed")
        state = "error"
        yield _sse_format(
            "loop.error",
            {"message": f"{type(exc).__name__}: {exc}", "run_id": ""},
        )

    # Persist the final assistant text + citations into the session
    # record so the existing poll / list endpoints remain useful.
    record["state"] = state
    record["final_text"] = final_text
    if final_text:
        try:
            record["messages"].append(
                {
                    "role": "assistant",
                    "content": final_text,
                    "ts": _now_iso(),
                    "citations": final_citations,
                }
            )
        except Exception:  # pragma: no cover
            pass
    record["updated_at"] = _now_iso()
    _save_session(user_id, record)

    # Terminal "done" frame for symmetry with /agent/start/stream so any
    # client built against the legacy shape still picks up state changes.
    yield _sse_format("done", _record_to_state(record).model_dump())


@router.post(
    "/loop/{session_id}/continue/stream",
    summary="Continue a Phase 7 loop session with a follow-up message.",
    dependencies=[
        Depends(require_agent_access),
        Depends(meter_call("agent_loop_continue")),
    ],
)
async def agent_loop_continue_stream(
    session_id: Annotated[str, PathParam(min_length=6, max_length=80)],
    req: AgentContinueRequest,
    user_id: Annotated[str, Depends(get_current_user)],
    tier: Annotated[Tier, Depends(get_current_tier)],
) -> StreamingResponse:
    """Send a follow-up turn into an existing Phase-7 loop session.

    Unlike the legacy ``/{session_id}/continue/stream`` endpoint, this
    route reloads the persisted :class:`CompliantMemory` substrate so the
    CRP MultiHorizonContext, CognitiveStateObject and prior turns survive
    across requests. The runtime therefore sees the full conversation,
    not a flattened message log reconstructed from ``record["messages"]``.
    """
    if user_id == "anonymous":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Agent loop continuation requires authentication.",
        )

    record = _load_session(user_id, session_id)
    if record.get("mode") != "loop":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Session was not started via the Phase-7 loop endpoint.",
        )

    state = record.get("state")
    if state not in {"done", "max_iters", "error"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Session is in state '{state}' and is not ready for a "
                "follow-up turn. Use /agent/loop/resume/{token} when awaiting a clarification."
            ),
        )

    _append_user_message(record, req.message)

    # Surface the previous answer as context so follow-ups like
    # "which of those satisfy GDPR?" are grounded in the prior run.
    prior_answer = (record.get("final_text") or "").strip()
    base_ctx = (record.get("extra_context") or "").strip()
    context_pieces = [base_ctx] if base_ctx else []
    if prior_answer:
        context_pieces.append(f"Previous answer for context:\n{prior_answer[:2000]}")
    extra_context = "\n\n".join(context_pieces)

    record.update(
        {
            "task": req.message,
            "extra_context": extra_context,
            "state": "running",
            "final_text": "",
            "error": "",
            "pending_question": "",
            "pending_context": "",
            "pending_priority": "",
            "pending_skippable": False,
            "pending_fact_key": "",
        }
    )
    _save_session(user_id, record)

    profile = record.get("org_profile") or _load_profile(record.get("customer_id"), user_id)
    memory = CompliantMemory(user_id=user_id, session_id=session_id)
    if profile:
        memory.set_profile(profile)

    headers = {
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return StreamingResponse(
        _stream_loop_run(
            user_id=user_id,
            tenant_id=record.get("customer_id") or user_id,
            record=record,
            task=req.message,
            extra_context=extra_context,
            profile=profile,
            memory=memory,
            depth=req.depth,
        ),
        media_type="text/event-stream",
        headers=headers,
    )


class _AgentLoopResumeRequest(BaseModel):
    """Body for ``POST /agent/loop/resume/{token}``."""

    answer: str
    session_id: str = ""
    extra_context: str = ""


@router.post(
    "/loop/resume/{token}",
    summary="Resume a Phase 7 loop suspended on a clarifier question.",
    dependencies=[
        Depends(require_agent_access),
        Depends(meter_call("agent_loop_resume")),
    ],
)
async def agent_loop_resume(
    token: str,
    body: _AgentLoopResumeRequest,
    user_id: Annotated[str, Depends(get_current_user)],
    tier: Annotated[Tier, Depends(get_current_tier)],
) -> StreamingResponse:
    """Submit a user answer for a paused loop and stream the continuation."""
    if user_id == "anonymous":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Agent loop resume requires authentication.",
        )

    from ..agent.clarifier import ClarifierStore
    from ..agent.tools import ToolError as _ClarifierError

    tenant_id = user_id
    store = ClarifierStore()
    # LOOP-ISSUE-1: scan the user-supplied clarifier answer for PII before
    # it is stored in the ClarifierStore and replayed into the agent context.
    try:
        from crp.security import PIIScanner as _ClarPII

        _clr = _ClarPII().scan(str(body.answer or "")[:2000])
        if getattr(_clr, "has_pii", False):
            logger.warning(
                "PII detected in clarifier answer (user=%s token=%s)",
                user_id[:8],
                token[:8],
            )
    except Exception:  # pragma: no cover
        logger.debug("clarifier PII scan unavailable", exc_info=True)
    try:
        rec = store.answer(
            resume_token=token,
            tenant_id=tenant_id,
            answer=body.answer,
        )
    except _ClarifierError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )

    snapshot = rec.snapshot or {}
    original_task = str(snapshot.get("task") or "")
    if not original_task:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="snapshot missing original task",
        )

    session_id = body.session_id or rec.session_id or uuid.uuid4().hex
    record = _load_session(user_id, session_id) or {
        "session_id": session_id,
        "user_id": user_id,
        "tier": tier.value,
        "task": original_task,
        "system_id": "",
        "customer_id": tenant_id,
        "extra_context": body.extra_context or "",
        "max_iters": 4,
        "state": "running",
        "iterations": 0,
        "tool_calls": 0,
        "facts_stored": 0,
        "pending_question": "",
        "pending_context": "",
        "final_text": "",
        "error": "",
        "clarifications": [],
        "messages": [],
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "trace_path": "",
        "mode": "loop",
    }
    record["state"] = "running"
    record["pending_question"] = ""
    record["pending_context"] = ""
    try:
        record["clarifications"].append(
            {
                "question": rec.question,
                "answer": body.answer,
                "slot_id": rec.slot_id,
                "ts": _now_iso(),
            }
        )
    except Exception:  # pragma: no cover
        pass
    _save_session(user_id, record)

    # Round 7 — if the snapshot contains a dialogue state, use the tracker to
    # interpret the answer. This enables confirm/repair/probe follow-ups.
    clarification_state, tracker_for_agent, _ = _resume_via_tracker(
        user_id=user_id,
        tenant_id=tenant_id,
        record=record,
        answer=body.answer,
        skip=False,
        token=token,
    )

    headers = {
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }

    if clarification_state is not None:
        # The tracker produced a follow-up confirm/repair/probe question.
        async def _followup_stream():
            yield _sse_format(
                "loop.clarifier.ask",
                {
                    "question": clarification_state.pending_question,
                    "options": clarification_state.pending_options,
                    "resume_token": clarification_state.resume_token,
                    "action": clarification_state.pending_action,
                },
            )
            yield _sse_format("done", clarification_state.model_dump())

        return StreamingResponse(
            _followup_stream(),
            media_type="text/event-stream",
            headers=headers,
        )

    profile = record.get("org_profile") or _load_profile(record.get("customer_id"), user_id)
    memory = CompliantMemory(user_id=user_id, session_id=record["session_id"])
    if profile:
        memory.set_profile(profile)

    extra_bits: list[str] = []
    if body.extra_context:
        extra_bits.append(body.extra_context)
    extra_bits.append(
        f"USER CLARIFICATION (slot {rec.slot_id}):\nQ: {rec.question}\nA: {body.answer}"
    )

    return StreamingResponse(
        _stream_loop_run(
            user_id=user_id,
            tenant_id=tenant_id,
            record=record,
            task=original_task,
            extra_context="\n\n".join(extra_bits),
            profile=profile,
            memory=memory,
            dialogue_tracker=tracker_for_agent,
        ),
        media_type="text/event-stream",
        headers=headers,
    )
