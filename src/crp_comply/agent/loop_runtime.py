# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Phase 7.15 — live language-agent loop runtime.

This is the integration layer that flips the Phase 7 shelf modules
(:mod:`triage`, :mod:`cache`, :mod:`loop_state`, :mod:`reflector`,
:mod:`loop_budget`, :mod:`federated_fabric`) from "tested in isolation"
to "wired into the production request path".

The runtime is exposed as :func:`run_loop_stream`, an ``async`` generator
that yields event dicts ready for SSE serialisation. The HTTP surface in
:mod:`crp_comply.api.agent` opens the stream at ``POST /agent/loop/stream``
and proxies the events to the browser.

Pipeline (PHASE_7 §3, §14, §21):

* Triage classifies the query → ``loop.triage``.
* Cache lookup (exact / semantic) → ``loop.cache.hit`` or ``loop.cache.miss``.
* On hit (Lane A): synthesise ``loop.final`` from the cached answer; stop.
* On miss: heuristic planner emits a 1–3-step plan → ``loop.plan``.
* For each step: delegate the per-step ReAct work to the proven
  :class:`crp_comply.agent.ComplianceAgent`, translating its
  ``tool_call`` / ``tool_result`` / ``llm_turn`` events into
  ``loop.thought.delta`` / ``loop.tool.call`` / ``loop.tool.result``.
* Reflector verdict per step → ``loop.reflection``.
* Budget meter records steps/tokens/wall-clock → may emit ``loop.abort``.
* Finalise: stitch step outputs → ``loop.final``; persist to cache; fire CRP
  feedback signal.

Design constraints
------------------

* The runtime is **opt-in**: callers explicitly hit ``/agent/loop/stream``.
  The legacy ``/agent/start/stream`` is unchanged.
* Per-step LLM work is delegated, not reinvented — that keeps the existing
  CRP integration (``compact_messages_for_budget``, ``dispatch_via_crp``,
  ``continue_truncated_answer``) firing on every turn.
* Every emit goes through one sink so SSE serialisation is the single
  source of truth; the FSM itself emits nothing.
* Failures degrade — a missing LLM, a Reflector exception, or a tool
  blow-up surfaces as a typed ``loop.error`` rather than a stack trace.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable

from .cache import AgentCache, CachedAnswer
from .citation_validator import CitationValidator, _normalise_url
from .clarifier import AskUserSuspended, ClarifierStore, make_resume_token
from .crp_integration import _approx_tokens
from .dialogue import DialoguePolicy, DialogueStateTracker
from .evidence_board import EvidenceBoard
from .loop_budget import BudgetExceeded, LoopBudget, LoopBudgetMeter
from .memory import CompliantMemory
from .loop_state import LoopState, LoopStateName, Phase, Plan, PlanStep
from .nlu import NluEngine
from .preferences import UserPreferenceProfile
from .reflector import Reflector, ReflectorResult
from .triage import Triage, TriageResult, load_default_triage
from .user_need import UserNeed

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────


# Type alias for the agent-builder callback the API hands in. Keeping
# this loose so test doubles don't need to import ComplianceAgent.
AgentBuilder = Callable[..., Any]


class _TokenRecorder:
    """Thread-safe bridge from the sync agent loop to the runtime token budget.

    The agent calls this callback after every LLM turn. A
    :class:`BudgetExceeded` breach is captured rather than raised, so the
    worker thread is not aborted mid-call. The runtime inspects
    ``breached`` after the step returns and emits ``loop.abort``.
    """

    def __init__(self, meter: LoopBudgetMeter) -> None:
        self.meter = meter
        self.breached: BudgetExceeded | None = None
        self.total: int = 0
        self._lock = threading.Lock()

    def __call__(self, n: int) -> None:
        with self._lock:
            if self.breached is not None:
                return
            try:
                self.meter.record_tokens(max(0, int(n)))
                self.total += max(0, int(n))
            except BudgetExceeded as exc:
                self.breached = exc


def _local_llm_for_user(user_id: str) -> Any | None:
    """Return a ComplianceLLM backed by the user's local worker, if connected.

    Phase 6 — used for mid-run fallback when the hosted provider hits a
    token quota, rate limit, or context-capacity error.
    """
    try:
        from ..api.worker_registry import get_worker_registry

        reg = get_worker_registry()
        status = reg.status(user_id)
        if not status or not status.get("connected"):
            return None
        from .llm import ComplianceLLM
        from .worker_adapter import WorkerAdapter

        return ComplianceLLM(provider=WorkerAdapter(user_id=user_id))
    except Exception:
        logger.debug("local LLM fallback lookup failed", exc_info=True)
        return None


def _is_hosted_capacity_error(error: str | None) -> bool:
    """True when an error text signals hosted-provider capacity exhaustion."""
    if not error:
        return False
    lowered = error.lower()
    return any(
        marker in lowered
        for marker in (
            "insufficient_quota",
            "rate_limit",
            "rate limit",
            "quota exceeded",
            "tokens exhausted",
            "context length",
            "context size",
            "context window",
            "maximum context length",
        )
    )


@dataclass
class LoopRuntimeConfig:
    """Per-request runtime configuration."""

    user_id: str
    tenant_id: str
    session_id: str
    task: str
    extra_context: str = ""
    max_iters_per_step: int = 4
    step_timeout_s: float = 120.0
    depth: str = ""
    corpus_version: str = field(
        default_factory=lambda: os.environ.get("CRP_COMPLY_CORPUS_VERSION", "v1")
    )
    ckf_version: str = field(default_factory=lambda: os.environ.get("CRP_COMPLY_CKF_VERSION", "v1"))
    cache_enabled: bool = True
    feedback_enabled: bool = True
    # 7.15.b — stream the final summary as `loop.thought.delta` chunks
    # before emitting the canonical `loop.final` so the chat surface
    # paints progressively. Disable in tests for deterministic event
    # counts.
    stream_final: bool = True
    final_chunk_chars: int = 60


async def run_loop_stream(
    cfg: LoopRuntimeConfig,
    *,
    agent_builder: AgentBuilder,
    triage: Triage | None = None,
    cache: AgentCache | None = None,
    budget: LoopBudget | None = None,
    dialogue_tracker: DialogueStateTracker | None = None,
    memory: CompliantMemory | None = None,
    user_preference: UserPreferenceProfile | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Drive one language-agent loop and yield typed ``loop.*`` events.

    Parameters
    ----------
    cfg
        Per-request configuration. ``tenant_id`` is mandatory for cache
        scope; ``user_id`` may equal ``tenant_id`` for individual users.
    agent_builder
        Callable returning a :class:`ComplianceAgent` (or a test
        double). Invoked once per *step*, not once per loop, so each
        step gets a fresh ReAct horizon.
    triage, cache, budget
        Optional injected components for tests. Production passes
        ``None`` and the runtime constructs defaults.

    Yields
    ------
    dict
        Event dicts shaped per :mod:`crp_comply.api.events`. Every
        dict has an ``"event"`` key naming a member of ``LoopEvent``.
    """
    run_id = uuid.uuid4().hex
    triage = triage or _safe_load_triage()
    cache = cache or AgentCache()
    budget_cfg = budget or LoopBudget.from_env()
    meter = LoopBudgetMeter(budget=budget_cfg)

    # 1. opened
    yield _ev(
        "loop.opened",
        run_id=run_id,
        session_id=cfg.session_id,
        query=cfg.task,
    )

    # 1b. Memory substrate (Round 4).
    # Load or create the CRPv4 memory substrate for this session. The profile
    # tier is seeded from the tenant's OrgProfile when available, falling back
    # to any profile already stored in the persisted memory (used by the
    # continue endpoint so prior-turn profile context is not lost).
    memory = memory or CompliantMemory(user_id=cfg.user_id, session_id=cfg.session_id)
    profile: dict[str, Any] | None = None
    try:
        from ..org_profile import get_org_profile_store

        profile = get_org_profile_store().get(cfg.tenant_id)
        if profile:
            memory.set_profile(profile)
    except Exception:
        logger.debug("OrgProfile not available for memory tier", exc_info=True)
    if not profile:
        profile = memory.profile or None

    # 1c. NLU + dialogue policy (Round 3).
    # These layers run before triage so the planner can use structured
    # intent/slots in addition to the deterministic triage fast path.
    dialogue_tracker = dialogue_tracker or DialogueStateTracker(
        user_id=cfg.user_id,
        nlu=NluEngine(),
        policy=DialoguePolicy(),
        memory=memory,
    )
    # Seed the dialogue slot board from the memory substrate so the policy
    # does not re-ask slots already established in prior turns.
    for key, value in memory.current_slots().items():
        if value and not dialogue_tracker.state.slots.get(key):
            dialogue_tracker.state.slots.set(key, value)
    # Seed slots from the OrgProfile using the canonical mapping (Round 12).
    dialogue_tracker.load_user_model(profile)
    nlu_result, policy_decision = dialogue_tracker.process_utterance(cfg.task)
    memory.add_turn("user", cfg.task, topic_tags=[nlu_result.intent])

    # Build the user-need model from NLU slots so the planner and formatter can
    # tailor depth, format, audience, and urgency.
    user_need = UserNeed(
        intent=nlu_result.intent,
        intent_confidence=nlu_result.intent_confidence,
        regulation=nlu_result.slots.get("regulation"),
        jurisdiction=nlu_result.slots.get("jurisdiction"),
        system_type=nlu_result.slots.get("system_type"),
        data_type=nlu_result.slots.get("data_type"),
        purpose=nlu_result.slots.get("purpose"),
        task_type=nlu_result.slots.get("task_type"),
        depth=str(nlu_result.slots.get("depth") or cfg.depth or "standard").lower(),
        format=str(nlu_result.slots.get("format") or "prose").lower(),
        audience=str(nlu_result.slots.get("audience") or "unknown").lower(),
        urgency=str(nlu_result.slots.get("urgency") or "normal").lower(),
        freshness_required=needs_fresh_web(cfg.task),
        satisfaction_criteria=list(nlu_result.slots.get("satisfaction_criteria") or []),
        raw_slots=dict(nlu_result.slots),
    )
    if user_preference is not None:
        user_preference.apply_to_user_need(user_need)
    yield _ev(
        "loop.nlu",
        run_id=run_id,
        intent=nlu_result.intent,
        intent_confidence=nlu_result.intent_confidence,
        slots=nlu_result.slots,
        entities=[
            {"type": e.type, "value": e.value, "span": e.span, "confidence": e.confidence}
            for e in nlu_result.entities
        ],
        sentiment=nlu_result.sentiment,
        sentiment_score=nlu_result.sentiment_score,
        need=user_need.to_event_payload(),
    )
    yield _ev(
        "loop.dialogue",
        run_id=run_id,
        action=policy_decision.action,
        args=policy_decision.args,
        reply_text=policy_decision.reply_text,
        requires_llm=policy_decision.requires_llm,
    )

    # If the policy decides we need more information, short-circuit before
    # any reasoning engine work and ask the user for the missing slot(s) or
    # for intent clarification when the utterance is too vague.
    if policy_decision.action in {"probe", "repair", "confirm", "clarify_intent"}:
        action = policy_decision.action
        missing = list(policy_decision.args.get("missing") or [])
        slot_id = policy_decision.args.get("slot") or (missing[0] if missing else "")
        question = policy_decision.reply_text or _build_clarification_question(
            missing, user_need=user_need
        )
        options = list(policy_decision.options or [])
        token = make_resume_token()
        try:
            store = ClarifierStore()
            store.suspend(
                resume_token=token,
                session_id=cfg.session_id,
                run_id=run_id,
                tenant_id=cfg.tenant_id,
                slot_id=slot_id,
                question=question,
                options=options or None,
                snapshot={
                    "task": cfg.task,
                    "dialogue_state": dialogue_tracker.state.to_dict(),
                    "dialogue_action": action,
                    "policy_options": options,
                    "policy_decision": policy_decision.to_dict(),
                },
            )
        except Exception:
            logger.exception("dialogue clarifier.suspend failed")
        yield _ev(
            "loop.clarifier.ask",
            run_id=run_id,
            step_id="dialogue",
            question=question,
            options=options,
            resume_token=token,
            action=action,
        )
        try:
            memory.save()
        except Exception:
            logger.debug("memory save after clarify failed", exc_info=True)
        return

    # 1d. Merge NLU slots + memory context into extra context for the
    # reasoning engine. Profile/session context from prior turns is included
    # so the agent does not re-ask known facts.
    memory_context = memory.to_extra_context()
    slot_context = _slots_to_extra_context(nlu_result.slots)
    pieces = [p for p in (memory_context, slot_context, cfg.extra_context) if p]
    merged_extra_context = "\n\n".join(pieces)

    # 1e. Response depth / length negotiation. The NLU extracts an explicit
    # depth slot; if missing we default to standard so the planner never has
    # to guess how thorough the answer should be.
    depth = str(nlu_result.slots.get("depth") or cfg.depth or "standard").lower()

    # 2. triage
    triage_result = triage.classify(cfg.task)
    yield _ev(
        "loop.triage",
        run_id=run_id,
        **triage_result.to_event_payload(),
    )

    # 3. cache lookup
    if cfg.cache_enabled:
        try:
            lookup = cache.lookup_answer(
                tenant_id=cfg.tenant_id,
                corpus_version=cfg.corpus_version,
                ckf_version=cfg.ckf_version,
                query=cfg.task,
            )
        except Exception:  # pragma: no cover - cache must never crash the loop
            logger.warning("cache lookup failed; proceeding as miss", exc_info=True)
            lookup = AgentCache.force_miss()
    else:
        lookup = AgentCache.force_miss()

    if lookup.hit is not None:
        yield _ev(
            "loop.cache.hit",
            run_id=run_id,
            key_kind=lookup.key_kind,
            similarity=lookup.similarity,
            age_seconds=lookup.age_seconds,
            citations=lookup.hit.citations,
        )
        # LOOP-GAP-C: audit the cache retrieval and PII-scan the cached answer
        # before returning it — cached responses must not bypass compliance checks.
        _audit_and_scan_cache_hit(cfg=cfg, run_id=run_id, cached=lookup.hit)
        # Lane A — synthesise final from cache and stop.
        yield _ev(
            "loop.final",
            run_id=run_id,
            artefacts=[],
            summary=lookup.hit.answer,
            total_steps=0,
            citations=lookup.hit.citations,
            cached=True,
        )
        return
    yield _ev(
        "loop.cache.miss",
        run_id=run_id,
        key_kind=lookup.key_kind,
        lookup_ms=lookup.lookup_ms,
    )

    # 4. plan (heuristic — LLM-driven planner is a follow-up sub-phase)
    plan = _plan_for(cfg.task, triage_result, nlu_result.intent, depth=depth, user_need=user_need)
    yield _ev(
        "loop.plan",
        run_id=run_id,
        depth=depth,
        **plan.to_event_payload(),
    )

    # 5. FSM init
    fsm = LoopState(session_id=cfg.session_id, run_id=run_id)
    fsm.max_plan_revisions = budget_cfg.max_plan_revisions
    fsm.max_clarifiers = budget_cfg.max_clarifiers
    fsm.set_plan(plan)
    fsm.transition(LoopStateName.STEP, reason="plan accepted")

    accumulated: list[_StepRecord] = []
    final_state: str = "ok"

    # Round 10 — working memory that accumulates facts across research steps.
    evidence_board = EvidenceBoard()
    _last_phase: str | None = None
    _phase_step_ids: list[str] = []

    # Phase 6 — wall-clock watchdog. It polls the budget every second so a
    # hung LLM call still eventually triggers graceful finalisation.
    _wall_clock_exceeded = asyncio.Event()

    async def _watchdog() -> None:
        while not _wall_clock_exceeded.is_set():
            try:
                await asyncio.wait_for(_wall_clock_exceeded.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                try:
                    meter.check_wall_clock()
                except BudgetExceeded:
                    _wall_clock_exceeded.set()
                    break

    _watchdog_task = asyncio.create_task(_watchdog())

    # 6. per-step loop
    try:
        while True:
            step = fsm.current_step()
            if step is None:
                break

            if _wall_clock_exceeded.is_set():
                final_state = "timeout"
                break

            # Budget check — record_step raises if we'd cross the ceiling.
            try:
                meter.record_step()
            except BudgetExceeded as exc:
                yield _ev(
                    "loop.abort",
                    run_id=run_id,
                    dimension=str(exc.dimension),
                    limit=float(exc.limit),
                    usage=float(exc.usage),
                    detail=str(exc),
                )
                final_state = "aborted"
                break

            fsm.transition(LoopStateName.ACTING, reason="step start")
            yield _ev(
                "loop.step.start",
                run_id=run_id,
                step_id=step.id,
                intent=step.intent,
                attempt=1,
            )

            step_buffer: list[dict[str, Any]] = []
            outcome = await _execute_step(
                cfg=cfg,
                run_id=run_id,
                step=step,
                prior=accumulated,
                agent_builder=agent_builder,
                sink_send=step_buffer.append,
                extra_context=merged_extra_context,
                evidence_context=evidence_board.render(),
                meter=meter,
                memory=memory,
            )

            # Phase 6 — one-shot local-LLM fallback on hosted capacity errors.
            if outcome.status == "failed" and _is_hosted_capacity_error(outcome.error):
                local_llm = _local_llm_for_user(cfg.user_id)
                if local_llm is not None:
                    for ev in step_buffer:
                        yield ev
                    step_buffer = []
                    yield _ev(
                        "loop.fallback.local",
                        run_id=run_id,
                        step_id=step.id,
                        reason="hosted_capacity_exceeded",
                    )
                    outcome = await _execute_step(
                        cfg=cfg,
                        run_id=run_id,
                        step=step,
                        prior=accumulated,
                        agent_builder=agent_builder,
                        sink_send=step_buffer.append,
                        extra_context=merged_extra_context,
                        evidence_context=evidence_board.render(),
                        meter=meter,
                        override_llm=local_llm,
                        memory=memory,
                    )

            # Drain any agent-side events the executor buffered while it ran.
            for ev in step_buffer:
                yield ev

            yield _ev(
                "loop.step.end",
                run_id=run_id,
                step_id=step.id,
                status=outcome.status,
            )

            # Phase 6 — token-budget breach surfaced by the agent step.
            if outcome.budget_breach is not None:
                yield _ev(
                    "loop.abort",
                    run_id=run_id,
                    dimension=str(outcome.budget_breach["dimension"]),
                    limit=float(outcome.budget_breach["limit"]),
                    usage=float(outcome.budget_breach["usage"]),
                    detail="token budget exceeded",
                )
                final_state = "aborted"
                break

            # Phase 6 — wall-clock timeout: finalise with whatever we have.
            if _wall_clock_exceeded.is_set():
                final_state = "timeout"
                break

            # Clarifier suspension — persist the awaiting_user record, emit a
            # typed event with the resume token, and exit the loop. The HTTP
            # layer surfaces the token to the client; on resume we fold the
            # answer into ``extra_context`` and re-enter the runtime.
            if outcome.status == "awaiting_user" and outcome.clarifier:
                clar = outcome.clarifier
                token = str(clar.get("resume_token") or make_resume_token())
                try:
                    store = ClarifierStore()
                    store.suspend(
                        resume_token=token,
                        session_id=cfg.session_id,
                        run_id=run_id,
                        tenant_id=cfg.tenant_id,
                        slot_id=str(clar.get("slot_id") or ""),
                        question=str(clar.get("question") or ""),
                        options=list(clar.get("options") or []) or None,
                        snapshot={
                            "task": cfg.task,
                            "step_id": step.id,
                            "prior": [
                                {
                                    "step_id": r.step_id,
                                    "observation": r.observation,
                                    "citations": r.citations,
                                }
                                for r in accumulated
                            ],
                        },
                    )
                except Exception:
                    logger.exception("clarifier.suspend failed")
                yield _ev(
                    "loop.clarifier.ask",
                    run_id=run_id,
                    step_id=step.id,
                    question=str(clar.get("question") or ""),
                    options=list(clar.get("options") or []),
                    resume_token=token,
                    action="probe",
                )
                final_state = "awaiting_user"
                break

            # Reflect.
            fsm.transition(LoopStateName.REFLECT, reason="step complete")
            try:
                verdict = Reflector().evaluate(
                    state=fsm,
                    step=step,
                    outcome=_to_step_outcome(step.id, outcome),
                    confidence=outcome.confidence,
                )
            except Exception:
                logger.warning("reflector raised; treating as ok", exc_info=True)
                verdict = ReflectorResult(verdict="ok", notes="reflector_error")

            yield _ev(
                "loop.reflection",
                run_id=run_id,
                step_id=step.id,
                verdict=verdict.verdict,
                notes=verdict.notes,
                plan_delta=verdict.plan_delta,
            )

            accumulated.append(outcome)

            # Round 10 — accumulate facts and detect completed phases.
            phase = step.phase.value if step.phase else "RESEARCH"
            evidence_board.add_from_citations(
                step_id=step.id,
                phase=phase,
                observation=outcome.observation,
                citations=outcome.citations,
            )
            if _last_phase is not None and _last_phase != phase:
                yield _ev(
                    "loop.phase.complete",
                    run_id=run_id,
                    phase=_last_phase,
                    step_ids=list(_phase_step_ids),
                    facts_gathered=len(evidence_board.by_phase(_last_phase)),
                    citations_count=sum(
                        len(r.citations) for r in accumulated if r.step_id in _phase_step_ids
                    ),
                    notes=f"completed {_last_phase} phase",
                )
                _phase_step_ids = []
            _phase_step_ids.append(step.id)
            _last_phase = phase

            try:
                target = fsm.apply_reflector_verdict(verdict.verdict)
                # revise_plan is handled in-place while still in REFLECT:
                # we rebuild the plan, call fsm.revise_plan(), then move to STEP.
                if target is not LoopStateName.PLANNING:
                    fsm.transition(target, reason=f"reflector:{verdict.verdict}")
            except Exception:
                logger.warning("FSM transition failed; finalising", exc_info=True)
                target = LoopStateName.FINALISE

            if target == LoopStateName.FINALISE:
                break
            if target == LoopStateName.STEP:
                # "ok" with more steps remaining → advance the cursor.
                # "retry" → repeat the same step (don't advance).
                if verdict.verdict == "ok":
                    fsm.advance_step()
                continue
            if target == LoopStateName.PLANNING:
                # Plan revision — counts toward budget.
                try:
                    meter.record_plan_revision()
                except BudgetExceeded as exc:
                    yield _ev(
                        "loop.abort",
                        run_id=run_id,
                        dimension="plan_revisions",
                        limit=float(exc.limit),
                        usage=float(exc.usage),
                        detail="plan revision budget exhausted",
                    )
                    final_state = "aborted"
                    break

                # Phase 6 — real replan: rebuild the plan with the Reflector's
                # failure context instead of just advancing the cursor.
                failure_context = _build_failure_context(step, outcome, verdict)
                new_plan = _plan_for(
                    cfg.task,
                    triage_result,
                    nlu_result.intent,
                    depth=depth,
                    user_need=user_need,
                    failure_context=failure_context,
                )
                yield _ev(
                    "loop.plan.revised",
                    run_id=run_id,
                    step_id=step.id,
                    reason=failure_context[:240],
                    plan_steps=[s.id for s in new_plan.steps],
                )
                try:
                    fsm.revise_plan(new_plan)
                except Exception as exc:
                    yield _ev(
                        "loop.abort",
                        run_id=run_id,
                        dimension="plan_revisions",
                        limit=float(budget_cfg.max_plan_revisions),
                        usage=float(fsm.plan_revisions),
                        detail=f"replan failed: {exc}",
                    )
                    final_state = "aborted"
                    break
                try:
                    fsm.transition(LoopStateName.STEP, reason="revise_plan: replanned")
                except Exception:
                    break
                continue
            if target == LoopStateName.ERROR:
                final_state = "aborted"
                break
            # AWAITING_USER — clarifier suspend is wired in 7.15.b. For now
            # we fall through to finalise so the user gets a partial answer.
            break
    finally:
        _wall_clock_exceeded.set()
        _watchdog_task.cancel()
        try:
            await _watchdog_task
        except asyncio.CancelledError:
            pass

    # 7. finalise — stitch step outputs into one answer.
    # LOOP-GAP-A: write a parent-level CRP audit record that links all child
    # step session_ids, so the full loop is one coherent compliance chain.
    try:
        from crp.security import (  # type: ignore[import-not-found]
            ComplianceAuditTrail as _LoopAT,
            ComplianceEventType as _LoopCET,
        )

        _loop_key = os.environ.get("CRP_COMPLY_JWT_SECRET", "dev").encode("utf-8")
        _loop_trail = _LoopAT(signing_key=_loop_key, session_id=cfg.session_id)
        _loop_trail.record(
            event_type=_LoopCET.DATA_PROCESSED,
            session_id=cfg.session_id,
            data={
                "event": "loop_complete",
                "run_id": run_id,
                "steps": [r.step_id for r in accumulated],
                "step_session_ids": [f"{cfg.session_id}:{r.step_id}" for r in accumulated],
                "final_state": final_state,
                "total_steps": len(accumulated),
            },
        )
    except Exception:
        logger.debug("LOOP parent audit trail record skipped (non-fatal)", exc_info=True)

    summary, citations, tool_log = _stitch_outputs(accumulated, cfg.task)

    # 6b. Citation validation (Round 8): ensure every [id] marker in the final
    # summary references a source returned by a tool in this run. Invalid
    # markers are stripped and a ``loop.citation.invalid`` event is emitted.
    validator = CitationValidator()
    for rec in accumulated:
        validator.register_citations(rec.citations)
    validation = validator.validate(summary, on_invalid="strip")
    if not validation.ok:
        logger.warning(
            "Round 8 citation validation failed for run %s: invalid=%s",
            run_id,
            validation.invalid_ids,
        )
        yield _ev(
            "loop.citation.invalid",
            run_id=run_id,
            step_id="final",
            invalid_ids=validation.invalid_ids,
            valid_ids=validation.valid_ids,
            surrogate_ids=validation.surrogate_ids,
            stripped=validation.stripped,
        )
        summary = validation.cleaned_text
        # Filter the citation list to only those that resolved.
        valid_set = set(validation.valid_ids)
        citations = [c for c in citations if _citation_in_set(c, valid_set)]

    # 7a. stream the summary as `loop.thought.delta` chunks for the chat
    # surface so the assistant bubble paints progressively. We chunk on
    # whitespace boundaries near ``final_chunk_chars`` to avoid splitting
    # markdown tokens (links, code spans). This is a deterministic,
    # cost-free progressive UX — native LLM token streaming through the
    # tool-call path is a follow-up sub-phase.
    if cfg.stream_final and summary and final_state == "ok":
        for chunk in _chunk_for_stream(summary, cfg.final_chunk_chars):
            yield _ev(
                "loop.thought.delta",
                run_id=run_id,
                step_id="final",
                text=chunk,
            )

    # 7b. Record the agent turn in the memory substrate and persist.
    try:
        memory.add_turn("agent", summary, topic_tags=["final"])
        memory.save()
    except Exception:
        logger.debug("memory final turn save failed", exc_info=True)

    yield _ev(
        "loop.final",
        run_id=run_id,
        artefacts=[],
        summary=summary,
        total_steps=meter.steps,
        citations=citations,
        cached=False,
        state=final_state,
    )

    # 8. cache (best-effort, only on clean ok)
    if cfg.cache_enabled and final_state == "ok" and citations:
        try:
            cache.put_answer(
                tenant_id=cfg.tenant_id,
                corpus_version=cfg.corpus_version,
                ckf_version=cfg.ckf_version,
                query=cfg.task,
                cached=CachedAnswer(
                    answer=summary,
                    citations=citations,
                    tool_log=tool_log,
                    reflector_verdict="ok",
                ),
            )
        except Exception:  # pragma: no cover - cache write must not crash the loop
            logger.debug("cache put failed", exc_info=True)

    # 9. CRP feedback signal — close the learning loop.
    if cfg.feedback_enabled and final_state == "ok":
        _fire_crp_feedback(cfg=cfg, summary=summary, citations=citations)


# ─────────────────────────────────────────────────────────────────────
# Step execution — delegate to ComplianceAgent
# ─────────────────────────────────────────────────────────────────────


@dataclass
class _StepRecord:
    """Per-step result kept by the runtime."""

    step_id: str
    intent: str
    status: str
    observation: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    clarifier: dict[str, Any] | None = None
    confidence: float | None = None
    budget_breach: dict[str, Any] | None = None


async def _execute_step(
    *,
    cfg: LoopRuntimeConfig,
    run_id: str,
    step: PlanStep,
    prior: list[_StepRecord],
    agent_builder: AgentBuilder,
    sink_send: Callable[[dict[str, Any]], None],
    extra_context: str | None = None,
    evidence_context: str = "",
    meter: LoopBudgetMeter | None = None,
    override_llm: Any | None = None,
    memory: CompliantMemory | None = None,
) -> _StepRecord:
    """Run one plan step by delegating to ComplianceAgent in a worker thread.

    The agent's emitted events (``tool_call``, ``tool_result``,
    ``llm_turn``) are translated to ``loop.*`` and queued onto
    *buffer* so the parent generator can yield them in order.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[dict[str, Any] | object] = asyncio.Queue(maxsize=512)
    SENTINEL = object()

    def _agent_emit(ev: dict[str, Any]) -> None:
        # Translate at emit time; the runtime never sees raw legacy events.
        translated = _translate_agent_event(ev, run_id=run_id, step_id=step.id)
        if translated is None:
            return
        events = translated if isinstance(translated, list) else [translated]
        for item in events:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, item)
            except RuntimeError:  # pragma: no cover - loop teardown
                pass

    # Prior context — fold prior step observations into the task brief
    # so the agent has continuity even when the plan has multiple steps.
    sub_task = _format_step_task(cfg.task, step, prior, evidence_context=evidence_context)
    extra_context = extra_context if extra_context is not None else cfg.extra_context

    agent = agent_builder(user_id=cfg.user_id, max_iters=cfg.max_iters_per_step)
    if override_llm is not None and hasattr(agent, "llm"):
        agent.llm = override_llm

    # Token-budget recorder for this step. Even if the agent is on the
    # direct-answer fast path, the LLM call still spends tokens.
    recorder = _TokenRecorder(meter) if meter is not None else None

    # CRPv5 intent-aware fast path: skip the full tool loop for simple
    # definitional questions. This avoids the legacy system prompt's
    # mandatory ``query_regulation`` round-trip.
    if step.tool_hint == "direct_answer":
        return await _execute_direct_answer_step(
            cfg=cfg,
            run_id=run_id,
            step=step,
            agent=agent,
            sink_send=sink_send,
            recorder=recorder,
        )

    agent.event_sink = _agent_emit
    if recorder is not None and hasattr(agent, "token_usage_callback"):
        agent.token_usage_callback = recorder

    def _runner() -> Any:
        run_kwargs: dict[str, Any] = {
            "task": sub_task,
            "system_id": "",
            "customer_id": cfg.tenant_id,
            "session_id": f"{cfg.session_id}:{step.id}",
            "extra_context": extra_context,
        }
        # Phase 6 — only pass memory to agents that accept it (legacy stubs may not).
        try:
            sig = inspect.signature(agent.run)
            if "memory" in sig.parameters:
                run_kwargs["memory"] = memory
        except Exception:
            pass
        try:
            return agent.run(**run_kwargs)
        except Exception as exc:
            logger.exception("step %s: agent.run raised", step.id)
            return exc
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, SENTINEL)

    fut = loop.run_in_executor(None, _runner)

    # Phase 6 — drain agent events with a bounded wait so a hung worker
    # cannot block the runtime forever. The whole step is capped by
    # ``cfg.step_timeout_s``; individual queue waits are short so we can
    # detect a completed future even when no sentinel arrives promptly.
    async def _drain_and_await() -> Any:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                if fut.done():
                    break
                continue
            if item is SENTINEL:
                break
            assert isinstance(item, dict)
            sink_send(item)
        return await fut

    try:
        result = await asyncio.wait_for(_drain_and_await(), timeout=cfg.step_timeout_s)
    except asyncio.TimeoutError:
        fut.cancel()
        agent.event_sink = None
        if recorder is not None and hasattr(agent, "token_usage_callback"):
            agent.token_usage_callback = None
        return _StepRecord(
            step_id=step.id,
            intent=step.intent,
            status="failed",
            observation="",
            error=f"Step timed out after {cfg.step_timeout_s}s",
        )

    agent.event_sink = None
    if recorder is not None and hasattr(agent, "token_usage_callback"):
        agent.token_usage_callback = None

    # Phase 6 — if the token budget breached inside the agent, surface it
    # as a failed step so the runtime can emit loop.abort and stop cleanly.
    if recorder is not None and recorder.breached is not None:
        exc = recorder.breached
        return _StepRecord(
            step_id=step.id,
            intent=step.intent,
            status="failed",
            observation="",
            error=f"BudgetExceeded: {exc.dimension} usage={exc.usage} limit={exc.limit}",
            budget_breach={
                "dimension": exc.dimension,
                "usage": exc.usage,
                "limit": exc.limit,
            },
        )

    if isinstance(result, AskUserSuspended):
        # Agent asked the user a question — capture the suspension so the
        # runtime can persist a resume token and emit ``loop.clarifier.ask``.
        return _StepRecord(
            step_id=step.id,
            intent=step.intent,
            status="awaiting_user",
            observation="",
            error=None,
            clarifier={
                "question": result.question,
                "slot_id": getattr(result, "slot_id", "") or "",
                "options": list(getattr(result, "options", None) or []),
                "resume_token": getattr(result, "resume_token", "") or "",
            },
        )

    if isinstance(result, Exception):
        return _StepRecord(
            step_id=step.id,
            intent=step.intent,
            status="failed",
            observation="",
            error=f"{type(result).__name__}: {result}",
        )

    final_text = str(getattr(result, "final_text", "") or "")
    citations = _extract_citations(result)
    confidence = getattr(result, "confidence", None)
    if confidence is not None:
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = None
    return _StepRecord(
        step_id=step.id,
        intent=step.intent,
        status="ok" if final_text else "failed",
        observation=final_text,
        citations=citations,
        tool_calls=[],  # agent already emitted these as events
        error=None if final_text else "agent returned empty answer",
        confidence=confidence,
    )


async def _execute_direct_answer_step(
    *,
    cfg: LoopRuntimeConfig,
    run_id: str,
    step: PlanStep,
    agent: Any,
    sink_send: Callable[[dict[str, Any]], None],
    recorder: _TokenRecorder | None = None,
) -> _StepRecord:
    """CRPv5 intent-aware fast path: answer definitional questions directly.

    This bypasses the legacy system prompt's mandatory ``query_regulation``
    round-trip for questions the NLU classifies as ``define``/``cite``. The
    answer is treated as a single step observation and stitched into the
    final summary like any other step result.
    """
    depth = (cfg.depth or "standard").lower()
    if depth == "brief":
        length = "Answer in 2-4 sentences with the key fact and a short rationale."
    elif depth == "thorough":
        length = "Answer with a detailed explanation (200-400 words), explaining the reasoning and citing any relevant articles or clauses from general knowledge."
    else:
        length = "Answer directly in a concise paragraph (80-150 words). Briefly explain the reasoning, not just the conclusion."
    system_prompt = (
        "You are a concise compliance assistant. "
        + length
        + " If the question asks for a specific regulatory citation, answer from "
        "general knowledge and note that the user can request a full retrieval if needed. "
        "Do not call tools."
    )
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
    ]
    if cfg.extra_context.strip():
        messages.append(
            {"role": "system", "content": f"Session context:\n{cfg.extra_context.strip()}"},
        )
    messages.append({"role": "user", "content": cfg.task})

    try:
        text = await asyncio.to_thread(agent.llm.chat, messages)
    except Exception as exc:
        logger.exception("direct answer step failed")
        return _StepRecord(
            step_id=step.id,
            intent=step.intent,
            status="failed",
            observation="",
            error=f"{type(exc).__name__}: {exc}",
        )

    text = str(text or "").strip()
    if recorder is not None:
        prompt_tokens = _approx_tokens(json.dumps(messages, default=str), chars_per_token=3.3)
        completion_tokens = _approx_tokens(text, chars_per_token=3.3)
        recorder(prompt_tokens + completion_tokens)
        if recorder.breached is not None:
            exc = recorder.breached
            return _StepRecord(
                step_id=step.id,
                intent=step.intent,
                status="failed",
                observation="",
                error=f"BudgetExceeded: {exc.dimension} usage={exc.usage} limit={exc.limit}",
                budget_breach={
                    "dimension": exc.dimension,
                    "usage": exc.usage,
                    "limit": exc.limit,
                },
            )
    if text:
        # Keep the reasoning tape non-empty for the user-visible timeline.
        sink_send(_ev("loop.thought.delta", run_id=run_id, step_id=step.id, text=text))
    return _StepRecord(
        step_id=step.id,
        intent=step.intent,
        status="ok" if text else "failed",
        observation=text,
        error=None if text else "direct answer returned empty",
    )


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _slots_to_extra_context(slots: dict[str, Any]) -> str:
    """Render populated NLU slots as extra context for the reasoning engine."""
    if not slots:
        return ""
    lines = ["## Extracted context from this turn"]
    mapping = {
        "regulation": "Regulation",
        "jurisdiction": "Jurisdiction",
        "system_type": "System type",
        "data_type": "Data processed",
        "purpose": "Purpose",
        "task_type": "Artefact/task type",
    }
    for key, label in mapping.items():
        value = slots.get(key)
        if value:
            lines.append(f"- {label}: {value}")
    return "\n".join(lines)


def _build_clarification_question(missing: list[str], *, user_need: UserNeed | None = None) -> str:
    """Fallback clarification question when the policy did not supply one.

    Uses the user-need model to ask one targeted question instead of a generic
    list of missing slots.
    """
    un = user_need or UserNeed()
    if un.intent_confidence < 0.65 and not missing:
        return (
            "I want to make sure I answer the right thing. Are you looking for a "
            "definition, a risk classification, a comparison, or help drafting an artefact?"
        )

    mapping: dict[str, str] = {
        "regulation": "Which regulation should I use (e.g., EU AI Act, GDPR, ISO 42001)?",
        "jurisdiction": "Which jurisdiction are you operating in?",
        "system_type": "What kind of AI system are you asking about?",
        "data_type": "What personal or sensitive data does the system process?",
        "purpose": "What is the intended purpose of the system?",
        "task_type": "What artefact should I produce (e.g., DPIA, risk assessment, gap report)?",
    }
    # If the user has signalled a format or audience, adapt the question.
    framing = ""
    if un.format != "prose":
        framing = f" I'll format the answer as a {un.format.replace('_', ' ')}."
    if un.audience != "unknown":
        framing += f" I'll tailor it for a {un.audience} audience."

    questions = [mapping.get(m, f"Could you tell me the {m}?") for m in missing]
    if questions:
        return " ".join(questions) + framing
    return "Could you provide a bit more detail?" + framing


def _build_failure_context(
    step: PlanStep,
    outcome: _StepRecord,
    verdict: ReflectorResult,
) -> str:
    """Compose a concise failure note for the replanner.

    The note includes the step that failed, any error or empty result,
    the Reflector's critique, and the evidence gathered so far. It is
    intentionally short so the heuristic planner can embed it in step
    intents without bloating the prompt.
    """
    parts = [
        f"Step {step.id} ({step.intent}) did not satisfy the success predicate.",
    ]
    if outcome.error:
        parts.append(f"Error: {outcome.error}")
    elif not outcome.observation.strip():
        parts.append("The step produced no usable observation.")
    if verdict.notes:
        parts.append(f"Reflector notes: {verdict.notes}")
    if verdict.plan_delta:
        parts.append(f"Suggested plan delta: {verdict.plan_delta}")
    return " ".join(parts)


def _safe_load_triage() -> Triage:
    try:
        return load_default_triage()
    except Exception:
        logger.warning("default triage YAML failed to load; using empty patterns")
        return Triage(patterns=[])


def _ev(event: str, **payload: Any) -> dict[str, Any]:
    """Build a typed event dict.

    The HTTP layer schema-validates ``loop.*`` events, so we keep the
    payload to JSON-safe primitives here.
    """
    out: dict[str, Any] = {"event": event, "ts": time.time()}
    out.update({k: v for k, v in payload.items() if v is not None})
    return out


def _stream_buffer_append(buffer: list[dict[str, Any]], ev: dict[str, Any]) -> None:
    buffer.append(ev)


def _tailored_intent(base: str, user_need: UserNeed | None) -> str:
    """Append format/audience/urgency cues to a step intent."""
    un = user_need or UserNeed()
    parts = [base.rstrip(".")]
    if un.audience and un.audience != "unknown":
        parts.append(f"for a {un.audience} audience")
    if un.format and un.format != "prose":
        parts.append(f"as a {un.format.replace('_', ' ')}")
    if un.urgency == "high":
        parts.append("(high urgency: prioritize speed)")
    return " ".join(parts) + "."


def _plan_for(
    task: str,
    triage: TriageResult,
    dialogue_intent: str = "unknown",
    *,
    depth: str = "standard",
    user_need: UserNeed | None = None,
    failure_context: str | None = None,
) -> Plan:
    """Heuristic planner — single source of truth for Lane B vs Lane C shape.

    Lane B (fast path): one step. Lane C: 2–3 steps based on intent.
    Web/freshness questions get a dedicated `web_search` tool hint so
    the agent is steered toward the open-web sidecar before falling
    back to the corpus.

    The ``depth`` slot (brief / standard / thorough) scales the plan so
    the agent never under-answers a "detailed" request or over-answers a
    "brief" one.

    ``failure_context`` is supplied during ``revise_plan`` so the new plan
    can carry the Reflector's critique (PHASE_7 §21 7.6).
    """
    if failure_context:
        task = f"{task}\n\n[Replan context: {failure_context}]"
    fresh = needs_fresh_web(task)
    jurisdiction = ((user_need.jurisdiction or "") if user_need else "").lower().strip()
    unsupported_jurisdiction = not _is_corpus_supported_jurisdiction(jurisdiction)
    # Any out-of-corpus jurisdiction must hit the web; the local RAG corpus
    # cannot answer it. We also keep the existing freshness heuristic.
    force_web = fresh or unsupported_jurisdiction
    web_tool = "web_research" if depth == "thorough" and force_web else "web_search"

    # Round 3: allow the structured NLU intent to guide planning when
    # deterministic triage is uncertain.
    effective_intent = triage.intent if triage.intent != "unknown" else dialogue_intent

    if triage.lane == "fast":
        # CRPv5 fast path: pure definitional / citation questions can be
        # answered directly without burning a tool call. The direct-answer
        # branch is gated by the NLU intent so we only skip retrieval when
        # the user is asking for an explanation, not a scoped assessment.
        # Freshness-sensitive or out-of-corpus questions always keep the
        # web/corpus path. A user who asks for a "brief" answer also gets
        # the direct lane.
        if (effective_intent in {"define", "cite"} and not force_web) or depth == "brief":
            return Plan(
                steps=(
                    PlanStep(
                        id="s1",
                        intent=_tailored_intent(task[:200], user_need),
                        tool_hint="direct_answer",
                        success_predicate="answer is concise and accurate",
                        phase=Phase.RESEARCH,
                    ),
                ),
                should_loop=False,
            )
        return Plan(
            steps=(
                PlanStep(
                    id="s1",
                    intent=_tailored_intent(task[:200], user_need),
                    tool_hint=web_tool if force_web else "rag_search",
                    success_predicate="answer cites at least one regulation chunk or web hit",
                    phase=Phase.RESEARCH,
                ),
            ),
            should_loop=False,
        )

    # Thorough requests upgrade a fast factual lookup into a researched answer.
    if depth == "thorough" and effective_intent in {"define", "cite", "unknown"}:
        return Plan(
            steps=(
                PlanStep(
                    id="s1",
                    intent=_tailored_intent(f"Research and ground: {task[:160]}", user_need),
                    tool_hint=web_tool if force_web else "rag_search",
                    phase=Phase.RESEARCH,
                ),
                PlanStep(
                    id="s2",
                    intent=_tailored_intent(
                        f"Synthesise a detailed answer: {task[:160]}", user_need
                    ),
                    tool_hint="rag_search",
                    phase=Phase.SYNTHESIS,
                ),
            ),
            should_loop=True,
        )

    if effective_intent in ("produce_artefact",):
        return Plan(
            steps=(
                PlanStep(
                    id="s1",
                    intent=_tailored_intent(f"Identify obligations for: {task[:160]}", user_need),
                    tool_hint=web_tool if force_web else "rag_search",
                    phase=Phase.RESEARCH,
                ),
                PlanStep(
                    id="s2",
                    intent=_tailored_intent(f"Draft the artefact for: {task[:160]}", user_need),
                    tool_hint="rag_search",
                    phase=Phase.SYNTHESIS,
                ),
            ),
            should_loop=True,
        )

    if effective_intent == "compare":
        return Plan(
            steps=(
                PlanStep(
                    id="s1",
                    intent=_tailored_intent(f"Gather position A in: {task[:160]}", user_need),
                    tool_hint="rag_search",
                    phase=Phase.RESEARCH,
                ),
                PlanStep(
                    id="s2",
                    intent=_tailored_intent(f"Gather position B in: {task[:160]}", user_need),
                    tool_hint=web_tool if force_web else "rag_search",
                    phase=Phase.RESEARCH,
                ),
                PlanStep(
                    id="s3",
                    intent=_tailored_intent(f"Compare and conclude: {task[:160]}", user_need),
                    tool_hint="rag_search",
                    phase=Phase.ANALYSIS,
                ),
            ),
            should_loop=True,
        )

    # default Lane C — single substantive step.
    return Plan(
        steps=(
            PlanStep(
                id="s1",
                intent=task[:200],
                tool_hint=web_tool if force_web else "rag_search",
                success_predicate="answer cites at least one regulation chunk or web hit",
                phase=Phase.RESEARCH,
            ),
        ),
        should_loop=True,
    )


# Heuristic markers that the user wants fresh / web-grounded answers.
# When any of these match the planner picks ``tool_hint="web_search"``
# and the system prompt's web-search guidance kicks in. Conservative on
# purpose — false positives waste a sidecar call but never block the
# corpus path because the agent is free to also call ``query_regulation``.
_FRESHNESS_PATTERNS = (
    "latest",
    "recent",
    "this year",
    "this month",
    "this week",
    "today",
    "yesterday",
    "news",
    "breaking",
    "current position",
    "current guidance",
    "who got fined",
    "enforcement action",
    "recent ruling",
    "recent judgment",
    "updated",
    "new opinion",
    "draft regulation",
    "proposed",
    "2025",
    "2026",
    # Out-of-corpus jurisdictions — the indexed corpus does not cover these
    # yet, so a web lookup is the only way to give a grounded answer.
    "australia",
    "australian",
    "canada",
    "canadian",
    "singapore",
    "singaporean",
    "japan",
    "japanese",
    "brazil",
    "brazilian",
    "india",
    "indian",
)

# Jurisdictions that currently have indexed regulation sources in the RAG
# corpus. Queries about other jurisdictions should be routed to the web.
_SUPPORTED_CORPUS_JURISDICTIONS = {
    "eu",
    "europe",
    "european union",
    "uk",
    "united kingdom",
    "great britain",
    "us",
    "usa",
    "united states",
    "america",
}


def _is_corpus_supported_jurisdiction(jurisdiction: str | None) -> bool:
    """True when we have indexed sources for the named jurisdiction."""
    if not jurisdiction:
        return True  # default to corpus path when unknown
    return jurisdiction.lower().strip() in _SUPPORTED_CORPUS_JURISDICTIONS


def needs_fresh_web(task: str) -> bool:
    """Cheap heuristic: does the task plausibly need fresh web hits?"""
    t = task.lower()
    return any(p in t for p in _FRESHNESS_PATTERNS)


def _format_step_task(
    original: str,
    step: PlanStep,
    prior: list[_StepRecord],
    evidence_context: str = "",
) -> str:
    """Compose the per-step sub-task fed to the underlying agent."""
    if not prior:
        base = f"{step.intent}\n\n(Original user query: {original})"
    else:
        prior_summary = "\n".join(
            f"- step {p.step_id}: {p.observation[:240]}" for p in prior if p.observation
        )
        base = (
            f"{step.intent}\n\n"
            f"(Original user query: {original})\n\n"
            f"Prior step observations:\n{prior_summary}"
        )

    if evidence_context:
        base = f"{evidence_context}\n\n{base}"

    # GAP 3 fix: enforce tool_hint from the planner. When the planner
    # signals that a step needs a specific tool (e.g. web_search for
    # freshness-sensitive queries), inject a CRP directive so the agent
    # actually calls that tool first instead of defaulting to rag_search.
    if step.tool_hint and step.tool_hint not in {"rag_search", "direct_answer", ""}:
        base = (
            f"[CRP DIRECTIVE: Your FIRST tool call for this step MUST be "
            f"`{step.tool_hint}`. Start there before using any other tool.]\n\n{base}"
        )
    return base


def _translate_agent_event(
    ev: dict[str, Any], *, run_id: str, step_id: str
) -> dict[str, Any] | list[dict[str, Any]] | None:
    """Map a legacy ComplianceAgent event to a typed ``loop.*`` event."""
    name = str(ev.get("event") or "")
    tool = str(ev.get("tool") or ev.get("name") or "unknown")
    is_web = tool in {"web_search", "web_research", "vendor_profile", "compare_documents"}
    if name == "tool_call":
        if is_web:
            args = ev.get("arguments") or ev.get("args") or {}
            return _ev(
                "loop.web.start",
                run_id=run_id,
                step_id=step_id,
                query=str(args.get("query") or args.get("goal") or args.get("vendor") or ""),
                backend="searxng",
                profile=str(args.get("profile") or "") or None,
                freshness=str(args.get("freshness") or "any"),
            )
        return _ev(
            "loop.tool.call",
            run_id=run_id,
            step_id=step_id,
            tool=tool,
            args=ev.get("arguments") or ev.get("args") or {},
        )
    if name == "tool_result":
        result = ev.get("result") or {}
        summary = ""
        web_hits: list[dict[str, Any]] = []
        blocked = 0
        latency_ms = 0.0
        if isinstance(result, dict):
            summary = str(result.get("summary") or result.get("text") or "")[:400]
            blocked = int(result.get("blocked") or 0)
            try:
                latency_ms = float(result.get("latency_ms") or 0.0)
            except (TypeError, ValueError):
                latency_ms = 0.0
            res_list = result.get("results") or result.get("hits") or []
            if isinstance(res_list, list):
                for r in res_list:
                    if not isinstance(r, dict):
                        continue
                    web_hits.append(
                        {
                            "domain": str(r.get("domain") or r.get("host") or ""),
                            "trust_tier": int(r.get("trust_tier") or 4),
                            "url": str(r.get("url") or ""),
                            "title": str(r.get("title") or ""),
                            "blocked": bool(r.get("blocked") or False),
                        }
                    )
        elif isinstance(result, str):
            summary = result[:400]
        if is_web:
            events: list[dict[str, Any]] = []
            if isinstance(result, dict):
                expansion = result.get("expansion") or {}
                sub_queries = expansion.get("sub_queries") or []
                if sub_queries:
                    events.append(
                        _ev(
                            "loop.web.expand",
                            run_id=run_id,
                            step_id=step_id,
                            goal=str(result.get("goal") or ""),
                            intent=str(result.get("intent") or "general"),
                            sub_queries=list(sub_queries),
                            strategy=str(expansion.get("strategy") or ""),
                        )
                    )
                rerank = result.get("rerank") or {}
                if "model" in rerank or "candidates_in" in rerank:
                    events.append(
                        _ev(
                            "loop.web.rerank",
                            run_id=run_id,
                            step_id=step_id,
                            model=str(rerank.get("model") or ""),
                            candidates_in=int(rerank.get("candidates_in") or 0),
                            candidates_out=int(rerank.get("candidates_out") or 0),
                            latency_ms=float(rerank.get("latency_ms") or 0.0),
                        )
                    )
                citations = result.get("citations") or []
                if isinstance(citations, list):
                    for c in citations:
                        if isinstance(c, dict):
                            events.append(
                                _ev(
                                    "loop.web.cite",
                                    run_id=run_id,
                                    step_id=step_id,
                                    citation_id=str(c.get("citation_id") or ""),
                                    source_id=str(c.get("source_id") or c.get("url") or ""),
                                    chunk_index=int(c.get("chunk_index") or 0),
                                    score=float(c.get("score") or 0.0),
                                    excerpt=str(c.get("excerpt") or "")[:400],
                                )
                            )
            events.append(
                _ev(
                    "loop.web.result",
                    run_id=run_id,
                    step_id=step_id,
                    backend="searxng",
                    hits=web_hits,
                    blocked=blocked,
                    latency_ms=latency_ms,
                )
            )
            return events if len(events) > 1 else events[0]
        return _ev(
            "loop.tool.result",
            run_id=run_id,
            step_id=step_id,
            tool=tool,
            summary=summary,
            citations=ev.get("citations") or [],
            error=ev.get("error"),
        )
    if name == "llm_turn":
        text = str(ev.get("content") or ev.get("text") or "")
        if text:
            return _ev(
                "loop.thought.delta",
                run_id=run_id,
                step_id=step_id,
                text=text,
            )
        # Tool-only turns do not stream text, so we synthesise a short
        # plain-language thought so the popup's "Thinking" label is never
        # empty.
        tool_calls = ev.get("tool_calls") or []
        if tool_calls:
            parts: list[str] = []
            for tc in tool_calls:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function") or {}
                tname = (
                    fn.get("name")
                    or tc.get("name")
                    or tc.get("tool")
                    or "a tool"
                )
                args = fn.get("arguments") if isinstance(fn.get("arguments"), dict) else tc.get("arguments") or {}
                if not isinstance(args, dict):
                    args = {}
                query = str(args.get("query") or args.get("goal") or args.get("vendor") or "")
                if tname in {"web_search", "web_research", "web_research_agent", "web_search_with_depth"}:
                    parts.append(f'Searching the web for "{query}"…' if query else "Searching the web…")
                elif tname == "query_regulation":
                    parts.append(f'Searching the regulation corpus for "{query}"…' if query else "Searching the regulation corpus…")
                elif tname == "consult_regulation_expert":
                    regulation = str(args.get("regulation") or "")
                    parts.append(f"Consulting the {regulation} expert…" if regulation else "Consulting a regulation expert…")
                else:
                    parts.append(f"Calling `{tname}`…")
            if parts:
                return _ev(
                    "loop.thought.delta",
                    run_id=run_id,
                    step_id=step_id,
                    text=" ".join(parts),
                )
        return None
    if name == "llm_token":
        # Per-token native streaming path (Phase 7.16). Each chunk is
        # forwarded as its own ``loop.thought.delta`` so the chat surface
        # paints the model's reasoning live.
        chunk = str(ev.get("chunk") or ev.get("text") or "")
        if not chunk:
            return None
        return _ev(
            "loop.thought.delta",
            run_id=run_id,
            step_id=step_id,
            text=chunk,
        )
    if name == "crp_pii_warning":
        return _ev(
            "loop.pii_warning",
            run_id=run_id,
            step_id=step_id,
            categories=ev.get("categories") or [],
            iter=ev.get("iter"),
            source=ev.get("source"),
        )
    # Drop CRP-internal events from the loop tape; they're audit-only.
    return None


def _to_step_outcome(step_id: str, rec: _StepRecord) -> Any:
    """Adapt a ``_StepRecord`` to the ``StepOutcome`` shape expected by Reflector."""
    from .step_runner import StepOutcome

    return StepOutcome(
        step_id=step_id,
        status=rec.status,
        observation=rec.observation,
        citations=rec.citations,
        tool_calls=rec.tool_calls,
        error=rec.error,
        confidence=rec.confidence,
    )


def _chunk_for_stream(text: str, target_size: int) -> list[str]:
    """Split ``text`` into chunks of ~``target_size`` chars on whitespace.

    The chunks are concatenation-equal to ``text`` (the frontend just
    appends them) so no information is lost. Splitting on whitespace
    avoids breaking markdown link/code tokens mid-character which would
    otherwise flicker the rendered HTML.
    """
    if target_size <= 0 or len(text) <= target_size:
        return [text] if text else []
    chunks: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        end = min(i + target_size, n)
        if end < n:
            # Walk forward to next whitespace, capped at +40 chars.
            j = end
            cap = min(end + 40, n)
            while j < cap and not text[j].isspace():
                j += 1
            end = j
        chunks.append(text[i:end])
        i = end
    return chunks


def _citation_in_set(citation: dict[str, Any], valid_set: set[str]) -> bool:
    """Return True if any identifier of *citation* is in *valid_set*."""
    for key in ("chunk_id", "fact_id", "id", "citation_id", "source_id"):
        value = citation.get(key)
        if value and str(value) in valid_set:
            return True
    url = citation.get("url")
    if url and _normalise_url(str(url)) in valid_set:
        return True
    return False


def _extract_citations(result: Any) -> list[dict[str, Any]]:
    """Pull citations from an AgentResult-like object, best-effort."""
    citations: list[dict[str, Any]] = []
    raw = getattr(result, "citations", None)
    if isinstance(raw, list):
        for c in raw:
            if isinstance(c, dict):
                citations.append(c)
            else:
                citations.append({"source": str(c)})
        return citations
    # Fall back to scanning the final text for [chunk_id] markers.
    text = str(getattr(result, "final_text", "") or "")
    for token in _CHUNK_REF_RE.findall(text):
        citations.append({"chunk_id": token})
    return citations


def _stitch_outputs(
    records: list[_StepRecord], original_task: str
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """Combine per-step outputs into one final answer + merged citations.

    Audit 6 §5 — drop near-duplicate step observations before synthesis so
    a loop that revised onto the same ground (or a model that repeated
    itself) doesn't produce a concatenation of redundant blocks. Two
    observations are treated as duplicates when their 6-gram word sets
    overlap by ≥ 80%; the first (earliest) wins.
    """
    if not records:
        return ("", [], [])
    if len(records) == 1:
        rec = records[0]
        return (rec.observation, rec.citations, rec.tool_calls)

    kept: list[_StepRecord] = []
    seen_ngram_sets: list[set[str]] = []
    for r in records:
        obs = (r.observation or "").strip()
        if not obs:
            continue
        ngrams = _obs_ngrams(obs)
        is_dup = False
        if ngrams:
            for prior in seen_ngram_sets:
                if not prior:
                    continue
                overlap = len(ngrams & prior) / len(ngrams)
                if overlap >= 0.80:
                    is_dup = True
                    break
        if is_dup:
            logger.debug("stitch: dropping near-duplicate observation for step %s", r.step_id)
            continue
        kept.append(r)
        seen_ngram_sets.append(ngrams)

    parts = [
        f"## Step {r.step_id}: {r.intent}\n\n{r.observation}".rstrip()
        for r in kept
        if r.observation
    ]
    summary = "\n\n".join(parts) if parts else ""
    seen: set[str] = set()
    merged_citations: list[dict[str, Any]] = []
    for r in records:
        for c in r.citations:
            key = json.dumps(c, sort_keys=True, default=str)
            if key not in seen:
                seen.add(key)
                merged_citations.append(c)
    merged_tool_calls: list[dict[str, Any]] = []
    for r in records:
        merged_tool_calls.extend(r.tool_calls)
    return (summary, merged_citations, merged_tool_calls)


def _obs_ngrams(text: str, n: int = 6) -> set[str]:
    """Word-level n-gram set for near-duplicate detection (Audit 6 §5)."""
    words = re.findall(r"\w+", text.lower())
    if len(words) < n:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i : i + n]) for i in range(len(words) - n + 1)}


def _audit_and_scan_cache_hit(*, cfg: LoopRuntimeConfig, run_id: str, cached: CachedAnswer) -> None:
    """CRP audit record + PII scan for cache-hit responses (LOOP-GAP-C fix).

    Ensures cached answers are not returned without a compliance audit record
    or PII check.  Best-effort — never raises.
    """
    try:
        from crp.security import (  # type: ignore[import-not-found]
            ComplianceAuditTrail as _CacheAT,
            ComplianceEventType as _CacheCET,
            PIIScanner as _CachePII,
        )

        _key = os.environ.get("CRP_COMPLY_JWT_SECRET", "dev").encode("utf-8")
        _trail = _CacheAT(signing_key=_key, session_id=cfg.session_id)
        pii_cats: list[str] = []
        answer = str(cached.answer or "")
        if answer:
            try:
                _pii = _CachePII().scan(answer)
                if getattr(_pii, "has_pii", False):
                    pii_cats = [str(c) for c in getattr(_pii, "pii_types_found", [])]
            except Exception:
                pass
        _trail.record(
            event_type=_CacheCET.DATA_PROCESSED,
            session_id=cfg.session_id,
            data={
                "event": "cache_hit_returned",
                "run_id": run_id,
                "user_id": cfg.user_id,
                "tenant_id": cfg.tenant_id,
                "answer_len": len(answer),
                "pii_in_cached_answer": bool(pii_cats),
                "pii_categories": pii_cats,
                "citations_count": len(cached.citations or []),
            },
        )
        if pii_cats:
            logger.warning(
                "PII detected in cached answer (user=%s tenant=%s categories=%s) — "
                "consider purging this cache entry",
                cfg.user_id,
                cfg.tenant_id,
                pii_cats,
            )
    except Exception:
        logger.debug("cache hit audit/PII scan skipped (non-fatal)", exc_info=True)


def _fire_crp_feedback(
    *, cfg: LoopRuntimeConfig, summary: str, citations: list[dict[str, Any]]
) -> None:
    """Best-effort CRP feedback signal so the reranker learns from the loop.

    For each corpus citation (chunk_id present) we send a ``boost`` signal
    to CRP's feedback loop via :func:`.crp_integration.crp_apply_feedback`.
    Web-only citations (url only, no chunk_id) are forwarded to the SearXNG
    sidecar via the web feedback client (GAP 5 fix).
    """
    if not citations:
        return
    try:
        from .crp_integration import crp_apply_feedback  # type: ignore[attr-defined]
    except Exception:
        return

    def _runner() -> None:
        try:
            from .llm import ComplianceLLM  # deferred to avoid circular import

            llm = ComplianceLLM.for_user(cfg.user_id)
            provider = getattr(llm, "provider", llm)
        except Exception:
            logger.debug("crp_feedback: could not get LLM provider", exc_info=True)
            return
        for citation in citations:
            fact_id = str(citation.get("chunk_id") or citation.get("id") or "").strip()
            if not fact_id:
                # Skip web-only citations — handled below via sidecar.
                continue
            try:
                crp_apply_feedback(
                    provider,
                    fact_id=fact_id,
                    signal="boost",
                    reason="cited_in_answer",
                )
            except Exception:
                logger.debug("crp feedback signal failed for %s", fact_id, exc_info=True)

        # ── GAP 5: Send feedback for web-sourced citations ─────────────
        # Citations that carry only a ``url`` (no chunk_id) come from
        # web_search / web_research tool calls.  Forward a ``useful``
        # signal to the SearXNG sidecar so its reranker learns which
        # results the LLM actually cited.  Best-effort; never raises.
        web_citations = [
            c for c in citations if not (c.get("chunk_id") or c.get("id")) and c.get("url")
        ]
        if web_citations:
            web_fb = None
            try:
                from .web_client import build_default_web_client  # type: ignore[attr-defined]

                web_fb = build_default_web_client()
            except Exception:
                logger.debug("web feedback client unavailable", exc_info=True)
            if web_fb is not None:
                for citation in web_citations:
                    url = str(citation.get("url", "")).strip()
                    if not url:
                        continue
                    intent = str(citation.get("intent") or citation.get("source_type") or "general")
                    try:
                        web_fb.feedback(
                            intent=intent,
                            engine="auto",
                            useful=True,
                            weight=1.0,
                            url=url,
                            query=cfg.task,
                        )
                    except Exception:
                        logger.debug("web feedback signal failed for %s", url, exc_info=True)

    threading.Thread(target=_runner, daemon=False, name="crp-feedback").start()


# Citation-marker regex matching tokens like [chunk_abc123] or [art:gdpr-6].
_CHUNK_REF_RE = re.compile(r"\[([A-Za-z][A-Za-z0-9_:.\-]{2,})\]")


__all__ = [
    "LoopRuntimeConfig",
    "run_loop_stream",
]
