"""CRPv5 positioned-loop bridge for the compliance agent (Rounds 1-2).

Re-bases CRP Comply on the CRPv5 positioned tool loop (SPEC-049/050) instead of the
bespoke ReAct loop. It adapts the existing :class:`~crp_comply.agent.tools.ToolRegistry`
into a CRP Tool Capability Fabric + executor, and exposes
:class:`PositionedComplianceAgent`, which drives ``run_positioned`` and relays the
Cognitive State Object across turns.

Positioning, not injection: the model is placed on one compliance operation at a time
with only the 1–3 tools it needs — never the whole catalogue. Tool results become typed
CSO observations, so the model can never quote a regulation it did not look up.

See ``CRPV5_UPGRADE_REPORT.md`` for the full three-round plan.
  Round 1 (spine): dispatch via ``run_positioned``; multi-turn relay and output
    continuation activate automatically once the installed ``crprotocol`` exposes
    ``prior_cso``/``max_continuation_windows`` (detected at runtime via ``_RP_PARAMS``).
  Round 2 (safety + checkpoints, THIS FILE): tenant safety profile -> ``PolicyContext``;
    ``safety_class`` overrides so evidence-writing/mutating tools can be marked and
    gated behind ``oversight_required``; protocol injection/PII pre-flight on the task
    text (replaces the app-level duplicates in ``crp_integration.py``); a CLARIFY
    handler that never blocks the request — it answers when a resolver is supplied,
    or gracefully collects the open question for later human review (Invariant 10).
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Callable

from crp.security.clarify import ClarificationAction, ClarificationResolution
from crp.stl import guard_prompt_budget, run_positioned
from crp.tools import CapabilityExecutor, CapabilityProfile, ToolCapabilityFabric
from crp.tools.capability_fabric import PolicyContext
from crp.tools.descriptor import SafetyClass

from crp_comply.agent.tools import ToolRegistry

logger = logging.getLogger(__name__)

ModelCall = Callable[[str, "dict[str, Any] | None"], str]


def model_call_from_compliance_llm(llm: Any, **chat_kwargs: Any) -> ModelCall:
    """Adapt a ``ComplianceLLM`` facade into a positioned-loop ``model_call``.

    Reuses ``ComplianceLLM.chat()`` (the existing provider plumbing — routing,
    context-window probing, max_tokens defaults) so the positioned path never needs
    its own HTTP client. The structured-output ``schema`` is advisory: the frame
    prompt already instructs the model to emit JSON and the loop's own tool-call
    parser (``crp.stl.tool_positioner.parse_tool_call``) is tolerant of prose/fences.

    **Context-overflow guard (fixes the "LLM connection" gap):** every prompt is run
    through the protocol's :func:`crp.stl.guard_prompt_budget`, using
    ``llm.context_window_size()`` — which already probes the REAL loaded context
    window (e.g. LM Studio's actual 8192, not a model family's theoretical 128K, see
    ``ComplianceLLM._probe_context_window``). This is what prevents overflow on input,
    tool-call frames, continuation windows, and accumulated multi-turn CSO state — the
    prompt is trimmed (oldest context first, task instructions preserved) and the
    requested ``max_tokens`` is capped, whatever model is actually connected.
    """

    def model_call(prompt: str, schema: dict[str, Any] | None) -> str:  # noqa: ARG001
        try:
            context_window = int(llm.context_window_size())
        except Exception:  # noqa: BLE001
            context_window = 8192
        requested_max_tokens = int(
            chat_kwargs.get("max_tokens", getattr(llm, "default_max_tokens", 2048))
        )
        safe_prompt, safe_max_tokens = guard_prompt_budget(
            prompt,
            context_window=context_window,
            requested_max_tokens=requested_max_tokens,
        )
        call_kwargs = {**chat_kwargs, "max_tokens": safe_max_tokens}
        return llm.chat([{"role": "user", "content": safe_prompt}], **call_kwargs)

    return model_call


# Which STL operations each compliance tool can serve. Compliance tools are offered
# broadly (including GENERATE/SYNTHESISE) so the model can ALWAYS ground a citation —
# the core design property: never assert a regulation from parametric knowledge.
_RETRIEVAL_OPS = ["RETRIEVE", "GENERATE", "SYNTHESISE", "ANALYSE"]
_ANALYSIS_OPS = ["ANALYSE", "VERIFY", "GENERATE", "SYNTHESISE"]
_OPERATION_MAP: dict[str, list[str]] = {
    "query_regulation": _RETRIEVAL_OPS,
    "query_regulation_packed": _RETRIEVAL_OPS,
    "recall_facts": _RETRIEVAL_OPS,
    "lookup_annex": _RETRIEVAL_OPS,
    "lookup_gdpr": _RETRIEVAL_OPS,
    "search_iso42001": _RETRIEVAL_OPS,
    "classify_ai_act_risk": _ANALYSIS_OPS,
    "check_high_risk_criteria": _ANALYSIS_OPS,
}

# request_clarification is not a fabric tool — it maps to the CLARIFY operation /
# checkpoint handler (wired in Round 2).
_EXCLUDED = {"request_clarification"}

# run_positioned kwargs available in the installed crprotocol (5.0 vs 5.1+).
_RP_PARAMS = set(inspect.signature(run_positioned).parameters)


def _ops_for(name: str) -> list[str]:
    return _OPERATION_MAP.get(name, _RETRIEVAL_OPS)


def compliance_fabric_from_registry(
    registry: ToolRegistry,
    *,
    safety_overrides: dict[str, SafetyClass] | None = None,
) -> tuple[ToolCapabilityFabric, CapabilityExecutor]:
    """Adapt a compliance ``ToolRegistry`` into a CRP Tool Capability Fabric + executor.

    ``safety_overrides`` marks specific tools (by name) as ``destructive`` or
    ``mutating`` (e.g. a future ``evidence_write`` / ``submit_report`` tool) so
    Round 2's ``oversight_required`` gate can hold them for human approval before
    execution. Tools not listed default to ``read-only`` (true for the v0 lookup
    tools — ``query_regulation``, ``classify_ai_act_risk``, etc.).
    """
    overrides = safety_overrides or {}
    tcf = ToolCapabilityFabric()
    ex = CapabilityExecutor()
    for tool in registry._tools.values():  # noqa: SLF001 — internal accessor by design
        if tool.name in _EXCLUDED:
            continue
        safety_class = overrides.get(tool.name, SafetyClass.READ_ONLY)
        tcf.register_dict(
            {
                "capability_id": tool.name,
                "kind": "tool",
                "version": "1.0.0",
                "operation_types": _ops_for(tool.name),
                "serves_intents": [tool.name, *tool.name.split("_")],
                "input_schema": tool.parameters or {"type": "object", "properties": {}},
                "output_schema": {"type": "object"},
                "produces_facts": True,
                "cost_profile": {
                    "tokens": 40,
                    "latency_ms": 50,
                    "safety_class": safety_class.value,
                },
                "metadata": {"description": tool.description},
            }
        )
        # Tool.handler(args) -> dict maps directly to a capability implementation.
        ex.register_impl(tool.name, tool.handler)
    return tcf, ex


def safety_profile_to_policy(profile: dict[str, Any] | None) -> PolicyContext | None:
    """Map a tenant safety profile dict to a CRP ``PolicyContext`` (Round 2).

    Recognised keys (all optional): ``blocked_tools`` (list[str] -> blocklist),
    ``allowed_tools`` (list[str] -> allowlist), ``blocked_safety_classes``
    (list[str] of ``read-only``/``mutating``/``destructive``), ``data_residency``
    (e.g. ``"EU"``). Returns ``None`` for an empty/absent profile (no constraint).
    """
    if not profile:
        return None
    blocked_classes = {SafetyClass(c) for c in profile.get("blocked_safety_classes", []) if c}
    return PolicyContext(
        blocked_safety_classes=blocked_classes,
        data_residency=str(profile.get("data_residency", "")),
        allowlist=set(profile["allowed_tools"]) if profile.get("allowed_tools") else None,
        blocklist=set(profile.get("blocked_tools", [])),
    )


def make_collecting_clarify_handler(
    resolver: Callable[[str], str | None] | None = None,
) -> tuple[Callable[[Any], ClarificationResolution], list[str]]:
    """Build a CLARIFY handler that never blocks the request (Round 2).

    If ``resolver(question) -> answer`` is supplied and returns a non-empty string,
    the handler answers immediately. Otherwise it degrades to SKIP — the loop
    proceeds best-effort (Invariant 10) — and the question is appended to the
    returned ``pending`` list so the caller can surface it to a human afterwards
    (e.g. as a follow-up clarification prompt), instead of it being silently lost.
    """
    pending: list[str] = []

    def handler(request: Any) -> ClarificationResolution:
        question = getattr(request, "question", "") or ""
        if resolver is not None:
            answer = resolver(question)
            if answer:
                return ClarificationResolution(action=ClarificationAction.ANSWER, answer=answer)
        pending.append(question)
        return ClarificationResolution(action=ClarificationAction.SKIP, answer="")

    return handler, pending


def scan_task_safety(task: str) -> dict[str, Any]:
    """Run the PROTOCOL's injection + PII detectors on the task text (Round 2).

    Replaces the app-level duplicates in ``crp_integration.py`` (``scan_for_injection``,
    ``redact_pii``) with the same detectors the rest of CRPv5 uses, so Comply's safety
    signal is consistent with the protocol's own governance surface.
    """
    from crp.security.injection import InjectionDetector
    from crp.security.privacy import PIIScanner

    injection = InjectionDetector().scan(task)
    pii = PIIScanner().scan(task)
    return {
        "injection_flagged": injection.has_flags,
        "injection_confidence": injection.highest_confidence,
        "pii_detected": pii.has_pii,
        "pii_types": sorted(pii.pii_types_found),
    }


def make_checkpoint_inbox_clarify_handler(
    *,
    tenant_id: str = "",
    session_id: str = "",
    timeout: int = 300,
) -> Callable[[Any], ClarificationResolution]:
    """Bridge CLARIFY/oversight requests to the REAL async Inbox UI (Round 3).

    Round 2 shipped a synchronous, non-blocking collector (see
    ``make_collecting_clarify_handler``) — fast, but a human reviewer never actually
    sees the request until after the fact. This is the carried-over Round 3 item: it
    registers a real :class:`crp.security.checkpoint.Checkpoint` on the SAME
    ``SafetyControlPlane`` registry that ``crp_comply.checkpoint_inbox.resolve_checkpoint``
    already resolves — so an existing Inbox reviewer approving/rejecting a checkpoint
    through the current UI/webhook resolves *this* one too, no new endpoint needed.

    **Scope, honestly stated:** this handler *blocks the calling thread* for up to
    ``timeout`` seconds waiting for a human to resolve the checkpoint via the Inbox.
    That is an accepted trade-off for a synchronous ``run_positioned()`` call — it
    requires the API layer to run the request off the main event loop (e.g. FastAPI's
    thread-pool via ``run_in_threadpool``/``anyio.to_thread``), which Comply's API
    already does for the legacy blocking `.run()` loop. It is **not** a resume-later
    architecture (the request holds a worker thread the whole time); that remains
    future work if reviewer response times regularly exceed the timeout budget.

    On timeout or if the checkpoint machinery is unavailable, degrades to SKIP
    (Invariant 10) — the request never raises a raw error.
    """
    import asyncio

    from crp.security.checkpoint import Checkpoint, CheckpointTrigger
    from crp.security.control_plane import get_default_control_plane

    def handler(request: Any) -> ClarificationResolution:
        question = getattr(request, "question", "") or ""
        try:
            scp = get_default_control_plane()
            cp = Checkpoint(
                trigger=CheckpointTrigger.ALWAYS,
                timeout=timeout,
                context={
                    "question": question,
                    "tenant_id": tenant_id,
                    "session_id": session_id,
                    "reason": getattr(request, "reason", ""),
                    "operation_type": getattr(request, "operation_type", ""),
                },
            )
            scp._checkpoints[cp.checkpoint_id] = cp  # noqa: SLF001 — same registry checkpoint_inbox.py uses
            resolution = asyncio.run(cp.wait_for_resolution())
        except Exception:  # noqa: BLE001
            logger.warning("Checkpoint-inbox bridge unavailable; degrading to SKIP", exc_info=True)
            return ClarificationResolution(action=ClarificationAction.SKIP, answer="")

        if resolution.action.value == "approve":
            return ClarificationResolution(
                action=ClarificationAction.ANSWER,
                answer=resolution.edited_output or "approve",
            )
        if resolution.action.value == "edit" and resolution.edited_output:
            return ClarificationResolution(
                action=ClarificationAction.ANSWER, answer=resolution.edited_output
            )
        return ClarificationResolution(action=ClarificationAction.SKIP, answer="")

    return handler


# Per-session CSO persistence (Round 3 carry-over). In-memory only — survives across
# HTTP requests within one running process, not across restarts (full Postgres-backed
# persistence is tracked separately per the auth/DB migration plan in AGENTS.md). Keyed
# by session_id so a multi-turn conversation relays state even when each HTTP request
# constructs a fresh `ComplianceAgent`.
_SESSION_CSO_STORE: dict[str, Any] = {}


def get_session_cso(session_id: str) -> Any:
    """Return the persisted CSO for ``session_id``, or ``None`` if this is a new session."""
    return _SESSION_CSO_STORE.get(session_id) if session_id else None


def save_session_cso(session_id: str, cso: Any) -> None:
    """Persist ``cso`` for ``session_id`` so the next request on this session relays it."""
    if session_id:
        _SESSION_CSO_STORE[session_id] = cso


def clear_session_cso(session_id: str) -> None:
    """Drop persisted state for ``session_id`` (e.g. on explicit session reset)."""
    _SESSION_CSO_STORE.pop(session_id, None)


def export_positioned_evidence(result: Any, *, hmac_key: bytes | None = None) -> dict[str, Any]:
    """Build an evidence pack from a positioned-loop result (Round 3).

    Maps EU AI Act / ISO 42001 evidence needs onto what the CSO + Operation State
    Machine already track natively — every tool-grounded fact, the full operation
    event stream (already the audit trail — no separate logging needed), and an
    HMAC chain link if ``hmac_key`` is supplied (``CognitiveStateObject.extend_hmac_chain``,
    SPEC-011). Intended to back Comply's evidence-pack export endpoints.
    """
    cso = result.cso
    if hmac_key and not cso.cso_hmac:
        cso.extend_hmac_chain(cso.prior_cso_hash, hmac_key)
    return {
        "final_text": result.text,
        "operations": list(result.operations),
        "halted": result.halted,
        "continuation_windows": getattr(result, "continuation_windows", 1) or 1,
        "tool_grounded_facts": [
            {
                "statement": f.statement,
                "provenance": f.provenance.value,
                "window_origin": f.window_origin,
            }
            for f in cso.established_facts
            if not f.invalidated
        ],
        "tool_observations": list(cso.tool_observations),
        "event_stream": list(result.event_stream),
        "headers": dict(result.headers),
        "cso_hmac": cso.cso_hmac,
        "prior_cso_hash": cso.prior_cso_hash,
    }


class PositionedComplianceAgent:
    """CRPv5-native compliance agent — the positioned-loop replacement for the ReAct loop."""

    def __init__(
        self,
        registry: ToolRegistry,
        model_call: ModelCall,
        *,
        profile: CapabilityProfile = CapabilityProfile.CAPABLE_LOCAL,
        safety_overrides: dict[str, SafetyClass] | None = None,
        safety_profile: dict[str, Any] | None = None,
    ) -> None:
        self.fabric, self.executor = compliance_fabric_from_registry(
            registry, safety_overrides=safety_overrides
        )
        self.model_call = model_call
        self.profile = profile
        self.policy = safety_profile_to_policy(safety_profile)
        self._cso: Any = None

    def run(
        self,
        task: str,
        *,
        clarify_handler: Any = None,
        context_facts: list[str] | None = None,
        max_continuation_windows: int = 1,
        oversight_required: Any = None,
        policy: PolicyContext | None = None,
    ) -> Any:
        """Run one compliance task through the positioned loop; relay CSO across turns."""
        kwargs: dict[str, Any] = {
            "fabric": self.fabric,
            "executor": self.executor,
            "profile": self.profile,
            "clarify_handler": clarify_handler,
            "context_facts": context_facts,
            "policy": policy or self.policy,
            # 5.1+ features — passed only if the installed crprotocol supports them.
            "prior_cso": self._cso,
            "max_continuation_windows": max_continuation_windows,
            "oversight_required": oversight_required,
        }
        supported = {k: v for k, v in kwargs.items() if k in _RP_PARAMS}
        result = run_positioned(task, self.model_call, **supported)
        if "prior_cso" in _RP_PARAMS:
            self._cso = result.cso
        return result

    def reset(self) -> None:
        """Clear multi-turn state."""
        self._cso = None
