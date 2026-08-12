"""Compliance agent orchestrator.

This is the heart of Phase 4.2 — a tool-using agent loop that turns a user
task ("assess whether our system is high-risk under the EU AI Act") into a
structured compliance deliverable with auditable citations.

Key design properties (see ``LLM_INTELLIGENCE_DESIGN.md §3``):

1. **LLM never cites regulations from memory.** Every clause quote in the
   final output must come from a :func:`query_regulation` tool call made in
   the same session. The system prompt enforces this.
2. **Every turn is persisted.** The full message history, tool call arguments,
   tool results, and final verdict are written as :class:`crp.extraction.Fact`
   objects into a per-customer :class:`crp.ckf.ContextualKnowledgeFabric`,
   and (optionally) as a JSONL trace on disk.
3. **Async-pausable.** When the agent hits :class:`ClarificationNeeded`, it
   returns an :class:`AgentResult` with ``state='awaiting_clarification'`` and
   serialises the in-flight conversation so a later ``resume()`` call can
   continue.
"""

from __future__ import annotations

import json
import logging
import os
import time
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Literal, Sequence

from .citation_validator import CitationValidator
from .crp_dispatch import CrpDispatcher
from .crp_integration import (
    ContinuationOutcome,
    CrpDispatchOutcome,
    CrpMessageLedger,
    _approx_tokens,
    compact_messages_for_budget,
    continue_truncated_answer,
    crp_autoingest_message,
    extract_facts_from_text,
    fold_messages_with_ledger,
    pattern_query_ckf,
    redact_pii,
    scan_for_injection,
)
from .llm import ComplianceLLM
from .clarifier import ClarifierStore, make_resume_token
from .tools import ClarificationNeeded, ToolRegistry, ToolResult
from .mcp_permissions import (
    PermissionLevel,
    PolicyEnforcer,
    default_policies,
    strict_policies,
    financial_policies,
)

logger = logging.getLogger(__name__)


# Hard cap on clarification rounds per session — the design doc mandates a
# budget so the agent can't spin forever asking the user. Enforced in the
# orchestrator *and* at the API resume boundary (``api/agent.py``).
DEFAULT_CLARIFICATION_BUDGET = 6


def _extract_citations_from_payload(payload: Any) -> list[dict[str, Any]]:
    """Best-effort extraction of citation dicts from a tool result payload."""
    citations: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return citations
    for key in ("citations", "chunks", "hits", "facts", "sources"):
        entries = payload.get(key) or []
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict):
                citations.append(entry)
    # Some tools return a single result dict with a chunk_id.
    if not citations and any(k in payload for k in ("chunk_id", "fact_id", "id", "url")):
        citations.append(payload)
    return citations


# ---------------------------------------------------------------------------
# System prompt — frozen contract with the LLM
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a senior AI-compliance analyst (EU AI Act, GDPR, NIS2, ISO 42001, NIST AI RMF).

METHOD — follow this loop on EVERY user question:

  1. Call `query_regulation` AT LEAST ONCE before producing any final answer.
     Use a focused natural-language query that re-uses the user's terminology
     (e.g. "conformity assessment", "high-risk AI system", "data subject rights").
  2. If the first call returns 0 hits, retry `query_regulation` with a different
     phrasing or synonym BEFORE giving up. Try at least 2 different queries.
     Examples of synonyms to try: "conformity assessment" \u2192 "Article 43",
     "CE marking", "third-party assessment body", "notified body".
  3. If the user names a specific regulation ("EU AI Act", "GDPR", "NIS2",
     "ISO 42001", "NIST AI RMF", "DORA", "UK AI Act", "HIPAA", "SOC 2"),
     assume it and prefer `consult_regulation_expert` for that framework
     before a generic `query_regulation`. Do NOT call `request_clarification`
     to ask which regulation \u2014 search the corpus instead.
  4. Ask the user for missing facts about THEIR system / context when you
     cannot proceed without them. Be collaborative: explain why the answer is
     needed, suggest a sensible default assumption, and ask one focused
     question at a time. When you have enough information, briefly confirm
     your understanding before writing the final answer. If the user corrects
     a detail, accept the correction and continue; do not be defensive.
     Never use clarification to ask the user to re-state a regulation question.
  5. Use `web_search` (and `web_research` for deeper sweeps) when the user
     asks about RECENT events, regulator decisions, or guidance the corpus
     does not cover (e.g. "latest EDPB opinion on…", "who got fined this
     year for…", "current ICO position on…"). Also use it when the corpus
     returns 0 hits across two queries AND the question is plausibly
     answerable from public sources. Pass intent='regulation_text' for
     primary law, 'case_law' for judgments, 'guidance' for supervisor
     publications, 'enforcement' for fines, 'news' for time-sensitive items.
     Always cite the URL and quote a short passage when relying on web hits.
  6. WIDEN the evidence base — do NOT stop after a single `query_regulation`
     call. After the first useful hit, ALSO call at least one of:
       * `crp_retrieve_context` — unified retrieval from BOTH the regulation
         corpus AND the customer knowledge fabric. Use this as your FIRST
         broad-sweep tool for any multi-aspect question;
       * `crp_check_facts` — verify a specific claim BEFORE asserting it.
         Use this for article numbers, fine amounts, deadlines, and any
         specific obligation to prevent hallucinated citations;
       * `crp_get_related_facts` — graph-walk the CKF for connector facts
         that bridge disconnected topics. Use when the question spans
         multiple articles or frameworks;
       * `recall_facts` — replays facts the user previously volunteered or
         the agent established earlier in the session;
       * `pattern_query_ckf` — pattern-matches the customer fabric for
         relevant entities (regulations, controls, risks) when the
         question is about applicability.
     For AI-Act questions specifically, ALSO call `classify_ai_act_risk`
     or `check_high_risk_criteria` when the user asks "what are the
     requirements" or "is X high-risk" — the deterministic verdict is the
     citation the report needs.
     When drafting a structured deliverable (DPIA, Annex IV, FRIA), call
     `crp_get_document_structure` FIRST to get the regulator-expected
     section outline, then ground each section with `query_regulation`.

ANSWER QUALITY:

  * Produce a comprehensive, structured answer. Use Markdown headings, bullets,
    and numbered lists. Aim for 400\u20131,200 words for substantive questions;
    for simpler questions still give a complete paragraph (150\u2013300 words)
    with the reasoning explicit. Do NOT be terse.
  * Cite EVERY substantive claim with the corresponding `chunk_id` from
    `query_regulation` results, formatted as [chunk_id]. If a section is
    drawn from training-data knowledge rather than retrieved chunks, mark
    it explicitly with "(model-only \u2014 verify against the official text)".
  * Never claim "no hits" or "the regulation does not specify X" without
    showing the queries you tried. If you tried 2+ queries and got nothing,
    say so explicitly and answer from training-data knowledge with the
    "(model-only)" caveat.
  * Do NOT paraphrase from memory when retrieved chunks are available \u2014
    quote the relevant clause briefly, then explain.

Do not invent tool names. Do not invent chunk_ids. When you have enough
evidence, stop calling tools and write the final answer.
"""


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


AgentState = Literal["done", "awaiting_clarification", "max_iters", "error"]


@dataclass
class AgentResult:
    state: AgentState
    final_text: str = ""
    pending_question: str = ""
    pending_context: str = ""
    iterations: int = 0
    tool_calls: int = 0
    facts_stored: int = 0
    session_id: str = ""
    trace_path: str = ""
    error: str = ""
    # Clarification + privacy telemetry (CRP integration).
    clarifications_used: int = 0
    clarification_budget: int = DEFAULT_CLARIFICATION_BUDGET
    pii_redactions: int = 0
    continuation_windows: int = 1
    continuation_reason: str = ""
    # BATCH 5 — clarification UX metadata surfaced to the UI.
    pending_priority: str = ""
    pending_skippable: bool = False
    pending_fact_key: str = ""
    # Round 7 — unified ClarifierStore resume token.
    resume_token: str = ""
    pending_action: str = "probe"  # probe | confirm | repair
    # Round 8 — runtime confidence signal for Reflector.
    confidence: float | None = None
    # PEP — Policy Enforcement Point state
    enforcer_state: dict[str, Any] = field(default_factory=dict)
    # CRPv5 Round 2 — questions the positioned CLARIFY operation raised but could not
    # answer inline (graceful SKIP, Invariant 10); surfaced for human follow-up instead
    # of being silently lost. Also Round 2: protocol injection/PII pre-flight on input.
    pending_clarifications: list[str] = field(default_factory=list)
    input_safety: dict[str, Any] = field(default_factory=dict)
    # Round 12 — reasoning tape surfaced to the UI.
    reasoning_tape: list[dict[str, Any]] = field(default_factory=list)
    experts_invoked: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "final_text": self.final_text,
            "pending_question": self.pending_question,
            "pending_context": self.pending_context,
            "iterations": self.iterations,
            "tool_calls": self.tool_calls,
            "facts_stored": self.facts_stored,
            "session_id": self.session_id,
            "trace_path": self.trace_path,
            "error": self.error,
            "clarifications_used": self.clarifications_used,
            "clarification_budget": self.clarification_budget,
            "pii_redactions": self.pii_redactions,
            "continuation_windows": self.continuation_windows,
            "continuation_reason": self.continuation_reason,
            "pending_priority": self.pending_priority,
            "pending_skippable": self.pending_skippable,
            "pending_fact_key": self.pending_fact_key,
            "resume_token": self.resume_token,
            "pending_action": self.pending_action,
            "confidence": self.confidence,
            "enforcer_state": self.enforcer_state,
            "pending_clarifications": self.pending_clarifications,
            "input_safety": self.input_safety,
            "reasoning_tape": self.reasoning_tape,
            "experts_invoked": self.experts_invoked,
        }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class ComplianceAgent:
    """Tool-using compliance agent.

    Parameters
    ----------
    llm:
        A :class:`ComplianceLLM` facade.
    fabric:
        A :class:`crp.ckf.ContextualKnowledgeFabric` (or any object with
        compatible ``.store()`` and ``.fact_count()`` methods). Pass ``None``
        to run stateless.
    tools:
        The :class:`ToolRegistry` the agent is allowed to call. Typically
        built via :func:`crp_comply.agent.tools.default_registry`.
    max_iters:
        Hard cap on LLM↔tool round-trips per :meth:`run` call.
    trace_dir:
        If set, write a JSONL trace of every turn to
        ``{trace_dir}/{session_id}.jsonl``.
    """

    def __init__(
        self,
        llm: ComplianceLLM,
        fabric: Any,
        tools: ToolRegistry,
        *,
        max_iters: int = 8,
        trace_dir: str | Path | None = None,
        system_prompt: str | None = None,
        max_clarifications: int = DEFAULT_CLARIFICATION_BUDGET,
        redact_pii_pre_llm: bool = True,
        continue_on_length: bool = True,
        max_continuation_windows: int = 4,
        rag: Any | None = None,
        prime_budget_tokens: int = 4000,
        seed_intelligence: bool = True,
        web_feedback_client: Any | None = None,
        web_client: Any | None = None,
        always_prime_evidence: bool = True,
        profile: dict[str, Any] | None = None,
        crp_safety_profile: dict[str, Any] | None = None,
        slm_extra: dict[str, Any] | None = None,
        token_usage_callback: Callable[[int], None] | None = None,
    ) -> None:
        if len(tools) == 0:
            raise ValueError("ComplianceAgent requires at least one tool")
        self.llm = llm
        self.fabric = fabric
        self.tools = tools
        self.max_iters = max(1, int(max_iters))
        self.trace_dir = Path(trace_dir) if trace_dir else None
        if self.trace_dir:
            self.trace_dir.mkdir(parents=True, exist_ok=True)
        self.system_prompt = (system_prompt or SYSTEM_PROMPT).strip()
        self.max_clarifications = max(0, int(max_clarifications))
        self.redact_pii_pre_llm = bool(redact_pii_pre_llm)
        self.continue_on_length = bool(continue_on_length)
        self.max_continuation_windows = max(1, int(max_continuation_windows))
        # CRP context priming: when a RAG service is wired and the
        # caller supplies ``recipe_context`` to ``run()``, the agent
        # pre-packs the relevant regulatory chunks into the system
        # context BEFORE the first LLM turn. This is the
        # "place the LLM in such a state to constantly be able to
        # reference context" property called out in the analysis —
        # the agent no longer starts cold and discovers the regulation
        # via tool calls; it begins each drafting session with a
        # CRP-packed envelope of the most relevant clauses already in
        # its working memory and only calls ``query_regulation`` when
        # it needs to expand or disambiguate.
        self.rag = rag
        self.prime_budget_tokens = max(0, int(prime_budget_tokens))
        # Phase 7.22 — web sidecar reference. When set AND the user's
        # task looks freshness-sensitive (or no recipe_context is
        # given), we run a web_search BEFORE the first LLM turn and
        # fold the hits into the same CRP-packed primer envelope used
        # for corpus chunks. This embeds web_search into the loop
        # itself — the model no longer has to discover via prompting
        # that a tool is appropriate; the evidence is already in its
        # working memory.
        self.web_client = web_client
        # When True (default), every ``run()`` call without an
        # explicit ``recipe_context`` still primes the LLM with
        # CRP-packed RAG hits derived from the user's task. This
        # eliminates the wasted iter-1 ``query_regulation`` round-trip
        # observed in lm_studio_verbose_4.log (88s prompt-eval just to
        # decide to call a tool).
        self.always_prime_evidence = bool(always_prime_evidence)
        # Whether to run agent-side CRP intelligence seeding
        # (extraction + pattern_query + injection scan) on each
        # ``run()`` call. Tests can pass ``seed_intelligence=False`` to
        # avoid loading the sentence-transformer model in the hot path.
        self.seed_intelligence = bool(seed_intelligence)
        # Optional live event sink — when set, every trace event is
        # *also* delivered to the callback synchronously so the SSE
        # streaming endpoint can push it to the browser as it happens.
        # The callback signature is ``(event: dict) -> None`` and any
        # exceptions raised inside it are swallowed (best-effort).
        self.event_sink: Callable[[dict[str, Any]], None] | None = None
        # Policy Enforcement Point (PEP) — tool call gating
        self.enforcer: PolicyEnforcer | None = None
        self.enforcer_mode: str = (
            os.environ.get("CRP_COMPLY_ENFORCER_MODE", "default").strip().lower()
        )
        # Session-scoped retrieval dedup: chunk_ids the LLM has already
        # been shown in this session. When a tool returns one of these
        # again we replace its body with a one-line CRP marker so the
        # envelope stays lean across iterations.
        self._seen_chunk_ids: set[str] = set()
        # Per-session persistent dedup: seen chunks survive across
        # ``run`` / ``resume`` / ``continue`` calls on the same
        # ``session_id``. See CRP_AUDIT_3 §0 B-6.
        self._session_seen_chunk_ids: dict[str, set[str]] = {}
        # 7.15 — closes the SearXNG learning loop. Best-effort: any
        # object exposing ``feedback(intent=..., engine=..., useful=...)``
        # works (typically :mod:`crp_comply.sidecar_client`).
        self.web_feedback_client = web_feedback_client
        # Per-user dispatch mode override. Empty string means "use the env var
        # or default iterative loop". Populated by _build_agent() from the
        # stored provider config so users can choose their dispatch mode via
        # the Settings UI without touching Railway env vars.
        self.dispatch_mode_override: str = ""
        # Round 1 — CRP dispatcher facade. Lazy-initialised so tests and
        # minimal installs don't pay the cost unless the feature flag is on.
        self._crp_dispatcher: CrpDispatcher | None = None
        # Round 12 — tenant OrgProfile snapshot so the agent does not re-ask
        # facts the user already supplied during onboarding.
        self._profile: dict[str, Any] = dict(profile or {})
        # CRPv5 Round 2 — tenant SAFETY profile (distinct from the OrgProfile above):
        # blocked_tools / allowed_tools / blocked_safety_classes / data_residency.
        # Mapped to a CRP ``PolicyContext`` for the positioned dispatch path only
        # (see ``crp_comply.agent.positioned.safety_profile_to_policy``).
        self._crp_safety_profile: dict[str, Any] = dict(crp_safety_profile or {})
        self._slm_extra: dict[str, Any] = dict(slm_extra or {})
        if self._slm_extra.get("warning"):
            logger.warning("SLM profile warning: %s", self._slm_extra["warning"])
        # Phase 6 — token-budget telemetry. The runtime wires a callback
        # here so every LLM call contributes to the session budget.
        self.token_usage_callback: Callable[[int], None] | None = token_usage_callback

    def set_profile(self, profile: dict[str, Any] | None) -> None:
        """Replace the session's OrgProfile snapshot."""
        self._profile = dict(profile or {})

    def _report_token_usage(self, n: int) -> None:
        """Emit the token count for the last LLM call to the runtime meter.

        The callback is best-effort: a raised exception must not abort the
        agent loop. The runtime's callback captures budget breaches and
        surfaces them at the end of the step instead.
        """
        if self.token_usage_callback is None:
            return
        try:
            self.token_usage_callback(max(0, int(n)))
        except Exception:
            logger.debug("token_usage_callback raised; continuing", exc_info=True)

    def _count_turn_tokens(
        self,
        messages: list[dict[str, object]],
        turn_text: str,
        tool_calls: Sequence[dict[str, Any]],
    ) -> int:
        """Approximate prompt + completion tokens for one LLM turn."""
        prompt_text = json.dumps(messages, default=str)
        completion_text = (turn_text or "") + json.dumps(list(tool_calls), default=str)
        return _approx_tokens(prompt_text, chars_per_token=3.3) + _approx_tokens(
            completion_text, chars_per_token=3.3
        )

    def _profile_context(self) -> str:
        """Render the OrgProfile as authoritative extra context for the LLM."""
        if not self._profile:
            return ""
        lines = ["## Organisation profile (authoritative — do not re-ask)", ""]
        for key, value in self._profile.items():
            if key in {"onboarded_at", "updated_at", "tenant_id"}:
                continue
            if isinstance(value, list):
                value = ", ".join(str(v) for v in value)
            lines.append(f"- {key}: {value}")
        return "\n".join(lines)

    def _get_crp_dispatcher(self) -> CrpDispatcher:
        if self._crp_dispatcher is None:
            provider = getattr(self.llm, "provider", None) or self.llm
            self._crp_dispatcher = CrpDispatcher(
                provider=provider,
                system_prompt=self.system_prompt,
                event_sink=self.event_sink,
            )
        return self._crp_dispatcher

    def _init_enforcer(self, session_id: str, tenant_id: str = "") -> PolicyEnforcer:
        """Initialise the Policy Enforcement Point for this session.

        Mode is controlled by ``CRP_COMPLY_ENFORCER_MODE`` env var:
        ``default`` | ``strict`` | ``financial`` | ``off``.
        """
        mode = self.enforcer_mode
        if mode == "off":
            policies = []
        elif mode == "strict":
            policies = strict_policies()
        elif mode == "financial":
            policies = financial_policies()
        else:
            policies = default_policies()

        def _on_checkpoint(cp: Any) -> None:
            if self.event_sink is not None:
                try:
                    self.event_sink(
                        {
                            "type": "checkpoint.created",
                            "checkpoint_id": cp.checkpoint_id,
                            "tool_name": cp.tool_name,
                            "reason": cp.reason,
                            "session_id": cp.session_id,
                        }
                    )
                except Exception:
                    pass

        enforcer = PolicyEnforcer(
            policies=policies,
            safety_budget_start=1.0,
            on_checkpoint=_on_checkpoint,
            tenant_id=tenant_id,
            session_id=session_id,
        )
        self.enforcer = enforcer
        return enforcer

    # ------------------------------------------------------------------ positioned (CRPv5, Rounds 1-2)

    def _get_positioned_agent(self) -> Any:
        """Lazily build the CRPv5 positioned-loop agent (feature-flagged, additive).

        Round 1 of ``CRPV5_UPGRADE_REPORT.md``: re-bases dispatch on
        ``run_positioned`` (SPEC-049/050) via a Tool Capability Fabric built from
        this agent's existing :class:`ToolRegistry`. The legacy :meth:`run` loop is
        untouched — this is an additive path, opt in via :meth:`run_positioned`.

        Round 2: the tenant's ``crp_safety_profile`` (set at construction, distinct
        from the OrgProfile) is mapped to a ``PolicyContext`` so blocklists /
        allowlists / safety-class limits apply to every positioned dispatch,
        consistent with the legacy ``PolicyEnforcer`` path.
        """
        cached = getattr(self, "_positioned_agent", None)
        if cached is not None:
            return cached
        from crp_comply.agent.positioned import (
            PositionedComplianceAgent,
            model_call_from_compliance_llm,
        )
        from crp.tools import CapabilityProfile

        agent = PositionedComplianceAgent(
            self.tools,
            model_call_from_compliance_llm(self.llm),
            profile=CapabilityProfile.CAPABLE_LOCAL,
            safety_profile=self._crp_safety_profile or None,
        )
        self._positioned_agent = agent
        return agent

    def run_positioned(
        self,
        task: str,
        *,
        session_id: str = "",
        clarify_handler: Any = None,
        clarify_resolver: Any = None,
        use_checkpoint_inbox: bool = False,
        oversight_required: Any = None,
        max_continuation_windows: int = 1,
    ) -> AgentResult:
        """CRPv5 positioned-loop dispatch (opt-in). Returns the same ``AgentResult``
        shape as :meth:`run` so callers (API routes, CLI) can adopt it without a
        response-schema change. See ``CRPV5_UPGRADE_REPORT.md`` Rounds 1-3.

        Round 2 additions (all additive, non-breaking):
          * ``input_safety`` — the task text is scanned with the PROTOCOL's own
            injection + PII detectors (not the app-level duplicates) before dispatch.
          * CLARIFY never blocks by default: if ``clarify_handler`` is not supplied
            and ``use_checkpoint_inbox`` is ``False``, a non-blocking collecting
            handler is used — ``clarify_resolver(question) -> answer`` answers inline
            when possible, otherwise the question is gracefully skipped (Invariant 10)
            and surfaced via ``pending_clarifications``.
          * ``oversight_required`` gates any tool registered with a matching
            ``safety_class`` (see ``PositionedComplianceAgent(safety_overrides=...)``)
            behind the same clarify/oversight bridge — no destructive/mutating
            compliance action (e.g. a future evidence-write tool) executes silently.

        Round 3 additions:
          * ``session_id`` now RELAYS the CSO across separate calls to
            ``run_positioned`` even if this is a fresh ``ComplianceAgent`` instance
            (e.g. a new instance built per HTTP request) — state is looked up/saved
            in the module-level session store keyed by ``session_id``.
          * ``use_checkpoint_inbox=True`` bridges CLARIFY/oversight requests to the
            REAL async Inbox checkpoint mechanism (blocking wait, see
            ``make_checkpoint_inbox_clarify_handler`` for the honest scope note)
            instead of the fast non-blocking collector.
        """
        from crp_comply.agent.positioned import (
            get_session_cso,
            make_checkpoint_inbox_clarify_handler,
            make_collecting_clarify_handler,
            save_session_cso,
            scan_task_safety,
        )

        input_safety = scan_task_safety(task)

        pending: list[str] = []
        handler = clarify_handler
        if handler is None:
            if use_checkpoint_inbox:
                handler = make_checkpoint_inbox_clarify_handler(session_id=session_id)
            else:
                handler, pending = make_collecting_clarify_handler(clarify_resolver)

        agent = self._get_positioned_agent()
        # Round 3: relay CSO across requests via the session store, even when `agent`
        # is a freshly-constructed instance whose own in-process `_cso` is empty.
        if session_id:
            persisted = get_session_cso(session_id)
            if persisted is not None and agent._cso is None:  # noqa: SLF001
                agent._cso = persisted  # noqa: SLF001

        result = agent.run(
            task,
            clarify_handler=handler,
            oversight_required=oversight_required,
            max_continuation_windows=max_continuation_windows,
        )
        if session_id:
            save_session_cso(session_id, result.cso)
        state: AgentState = "error" if result.halted else "done"
        return AgentResult(
            state=state,
            final_text=result.text,
            iterations=len(result.operations),
            tool_calls=result.observation_count,
            facts_stored=len(result.cso.established_facts),
            session_id=session_id,
            continuation_windows=getattr(result, "continuation_windows", 1) or 1,
            error=result.headers.get("CRP-Agent-Operation-State", "") if result.halted else "",
            enforcer_state={
                "crp_agent_operation_plan": result.headers.get("CRP-Agent-Operation-Plan", "")
            },
            pending_clarifications=pending,
            input_safety=input_safety,
        )

    # ------------------------------------------------------------------ run

    def run(
        self,
        task: str,
        *,
        system_id: str = "",
        customer_id: str = "",
        session_id: str | None = None,
        extra_context: str = "",
        clarifications_used: int = 0,
        recipe_context: dict[str, Any] | None = None,
        prior_messages: list[dict[str, Any]] | None = None,
        memory: Any | None = None,
    ) -> AgentResult:
        """Execute the agent loop for ``task`` and return an :class:`AgentResult`.

        ``clarifications_used`` is the number of clarification rounds that
        have already been spent on this session in prior ``resume()`` calls;
        the orchestrator adds one more if the LLM raises another
        :class:`ClarificationNeeded` and the running total is below
        ``self.max_clarifications``. Once the budget is exhausted the
        orchestrator suppresses further clarifications and nudges the LLM
        to produce a best-effort final answer instead.
        """

        session_id = session_id or str(uuid.uuid4())
        # Phase 6 — memory handle so continuation state can persist across calls.
        self._memory = memory
        trace_path = self._trace_path(session_id)

        # Round 12 — capture a lightweight reasoning tape and the set of
        # regulation experts consulted, so the UI can show *how* the answer
        # was built and which frameworks were invoked.
        reasoning_tape: list[dict[str, Any]] = []
        experts_invoked: set[str] = set()
        original_sink = self.event_sink

        def _recording_sink(ev: dict[str, Any]) -> None:
            if original_sink is not None:
                try:
                    original_sink(ev)
                except Exception:  # pragma: no cover - never break run() on UI sink
                    pass
            evt = ev.get("event") if isinstance(ev, dict) else None
            if evt in {"llm_token", "llm_progress"}:
                return
            reasoning_tape.append(dict(ev))
            if evt == "tool_call":
                name = ev.get("tool") or ev.get("name") or ""
                if name == "consult_regulation_expert":
                    args = ev.get("args") or {}
                    reg = args.get("regulation") if isinstance(args, dict) else None
                    if reg:
                        experts_invoked.add(str(reg))
            elif evt == "tool_result":
                name = ev.get("tool") or ev.get("name") or ""
                if name == "consult_regulation_expert":
                    payload = ev.get("payload") or {}
                    reg = payload.get("regulation") if isinstance(payload, dict) else None
                    if reg:
                        experts_invoked.add(str(reg))

        self.event_sink = _recording_sink

        # Round 12 — fold the OrgProfile into extra_context so the LLM sees the
        # tenant's structural facts without re-asking them.
        profile_ctx = self._profile_context()
        if profile_ctx:
            if extra_context.strip():
                extra_context = f"{profile_ctx}\n\n{extra_context}"
            else:
                extra_context = profile_ctx

        # ── Phase 4 — Policy Enforcement Point initialisation ─────
        enforcer = self._init_enforcer(session_id=session_id, tenant_id=customer_id)

        # ── Phase 3 — opt-in CRP-native dispatch path ─────────────
        # When ``CRP_COMPLY_AGENT_DISPATCH_MODE`` is set to one of
        # ``agentic | with_tools | stream_augmented | plain``, we bypass
        # the bespoke tool loop and delegate the whole task to
        # ``crp.Client.dispatch_*``. The default (legacy) keeps our
        # iterative tool-using loop because that's the path our
        # domain tools (``query_regulation``, ``classify_ai_act_risk``,
        # ``store_fact``, …) plug into. The CRP-native path is best
        # for "free-form Q&A" sessions where the model just needs a
        # short factual answer with light retrieval.
        crp_mode = (
            self.dispatch_mode_override.strip().lower()
            or os.environ.get("CRP_COMPLY_AGENT_DISPATCH_MODE", "").strip().lower()
        )
        if crp_mode in {"agentic", "with_tools", "stream_augmented", "plain"}:
            # Phase 6: CRP-native dispatch does not accept a prior message
            # history array. Falling back to the legacy loop keeps multi-turn
            # continuity instead of silently dropping the conversation.
            if prior_messages:
                self._trace(
                    trace_path,
                    {
                        "event": "crp_dispatch_history_fallback",
                        "mode": crp_mode,
                        "reason": "prior_messages present but CRP dispatch does not accept history",
                        "prior_messages": len(prior_messages),
                    },
                )
            else:
                return self._run_via_crp_dispatch(
                    mode=crp_mode,
                    task=task,
                    system_id=system_id,
                    customer_id=customer_id,
                    session_id=session_id,
                    extra_context=extra_context,
                    recipe_context=recipe_context,
                )
        window_id = self._window_id(
            customer_id=customer_id, system_id=system_id, session_id=session_id
        )

        # LLM-GAP-C: DataLineageTracker for key data crossings. Initialised
        # here so the seeded-facts branch below can record the user-task
        # boundary before the CRP audit trail is set up.
        _lineage: Any | None = None

        # Hydrate per-session retrieval-dedup set so chunks already
        # surfaced in a prior ``run``/``resume``/``continue`` on this
        # same ``session_id`` are NOT re-injected into context, but a
        # fresh ``session_id`` starts cold. Persistent cross-call dedup
        # is the SSE / continue endpoint's job; we just give it a stable
        # bucket per session.
        self._seen_chunk_ids = self._session_seen_chunk_ids.setdefault(session_id, set())

        # Pre-LLM PII redaction (CRP design §3 — no raw PII crosses the
        # LLM boundary by default). Keeps the original text for the CKF
        # fact write so auditors still see what the customer actually sent.
        pii_redactions = 0
        safe_task = task
        safe_context = extra_context
        if self.redact_pii_pre_llm:
            r_task = redact_pii(task)
            safe_task = r_task.text
            pii_redactions += r_task.count
            if extra_context.strip():
                r_ctx = redact_pii(extra_context)
                safe_context = r_ctx.text
                pii_redactions += r_ctx.count

        clarifications_used = max(0, int(clarifications_used))
        budget_exhausted = clarifications_used >= self.max_clarifications

        # ── CRP-native envelope sizing (Axiom 2: E = C − S − T − G) ──
        # We do NOT clip after the fact and we do NOT skip context
        # because the carrier is small. Instead we use the protocol's
        # own envelope-budget formula and *relay*: whatever fits
        # in-context goes in-context; everything else is ingested
        # into the fabric/CKF so the LLM pulls it on demand via
        # ``recall_facts``/``pattern_query_ckf``/``query_regulation``.
        # That is the CRP design — multiple envelopes, multiple
        # relays, one continuation chain — rather than a single
        # crammed system message.
        try:
            from crp.envelope import compute_envelope_budget, estimate_tokens
        except Exception:  # pragma: no cover - SDK is a hard dep

            def compute_envelope_budget(  # type: ignore[no-redef]
                context_window: int,
                system_tokens: int,
                task_tokens: int,
                generation_reserve: int | None = None,
                max_output_tokens: int | None = None,
            ) -> int:
                g = max_output_tokens or generation_reserve or min(context_window // 4, 16384)
                return max(0, context_window - system_tokens - task_tokens - g)

            def estimate_tokens(text: str, chars_per_token: float = 3.3) -> int:  # type: ignore[no-redef]
                if not text:
                    return 0
                return max(1, int(len(text) / chars_per_token + 0.5))

        try:
            if hasattr(self.llm, "context_window_size"):
                _carrier_window = int(self.llm.context_window_size())
            else:
                _provider = getattr(self.llm, "provider", None)
                _carrier_window = (
                    int(_provider.context_window_size())
                    if _provider is not None and hasattr(_provider, "context_window_size")
                    else int(os.environ.get("CRP_COMPLY_CTX_WINDOW", "8192"))
                )
        except Exception:
            _carrier_window = int(os.environ.get("CRP_COMPLY_CTX_WINDOW", "8192"))
        # Output reserve G — generation room for the answer/tool-call.
        # Small carriers get a small G because per-iteration tool-call
        # arguments are tiny and ``continue_truncated_answer`` (the
        # CRP continuation-stitch) handles answers longer than one
        # window when the upstream returns ``finish_reason="length"``.
        if _carrier_window <= 4096:
            _output_window = 384
        elif _carrier_window <= 8192:
            _output_window = 768
        else:
            _output_window = min(
                int(getattr(self.llm, "default_max_tokens", 2048)),
                _carrier_window // 4,
            )
        # Tier-1 tool-schema cost rolls into S (system overhead). We
        # use a conservative constant rather than running the full
        # ``_fit_schemas_to_window`` here because the goal is to size
        # the envelope, not the schemas.
        _tier1_tool_cost = 1300
        _system_tokens = estimate_tokens(self.system_prompt) + _tier1_tool_cost
        _task_tokens = estimate_tokens(safe_task) + estimate_tokens(safe_context)
        # Axiom 2 — protocol-native envelope budget.
        _E_max = compute_envelope_budget(
            context_window=_carrier_window,
            system_tokens=_system_tokens,
            task_tokens=_task_tokens,
            max_output_tokens=_output_window,
        )
        # Safety margin for tokeniser drift (the estimator is calibrated
        # but the upstream may differ by a few %).
        _E_max = max(0, _E_max - 128)
        # Running residual the priming branches share. Each branch
        # consumes from this pool; what doesn't fit is *relayed* to
        # the fabric/CKF so the LLM can still reach it via tools.
        _envelope_remaining = min(int(self.prime_budget_tokens), _E_max)

        def _relay_chunks_to_ckf(
            chunks: list[dict[str, Any]],
            *,
            category: str,
            relay_window_id: str,
        ) -> int:
            """Ingest primer chunks into the fabric so they're recallable.

            CRP relay primitive: when in-context space is exhausted,
            we don't drop the content — we make it pullable. The LLM
            reaches it on the next turn via ``recall_facts`` /
            ``pattern_query_ckf`` / ``query_regulation``. This is what
            the protocol calls "more envelopes, more relays".
            """
            if self.fabric is None or not chunks:
                return 0
            stored = 0
            for ch in chunks:
                txt = (ch.get("text") or "").strip()
                if not txt:
                    continue
                meta: dict[str, Any] = {
                    "session_id": session_id,
                    "relay": True,
                    "chunk_id": ch.get("chunk_id") or "",
                    "source_id": ch.get("source_id") or "",
                    "article_id": ch.get("article_id") or "",
                    "title": ch.get("title") or "",
                }
                stored += self._store_fact(
                    window_id=relay_window_id,
                    text=txt[:2000],
                    category=category,
                    metadata=meta,
                )
            return stored

        messages: list[dict[str, object]] = [
            {"role": "system", "content": self.system_prompt},
        ]
        # CRP context priming — see ``__init__`` docstring. We compute
        # the packed envelope here (once per ``run``) so the LLM's very
        # first turn can already cite the relevant articles. Failures
        # are logged and swallowed: a cold start is functional, just
        # less efficient (more `query_regulation` round-trips).
        primed_chunks: list[dict[str, Any]] = []
        _relayed_corpus = 0
        _corpus_in_context = False
        if recipe_context and self.rag is not None and self.prime_budget_tokens > 0:
            # CRP-native: ask the corpus envelope helper for a budget
            # that fits the residual envelope. If the residual is 0
            # we still fetch (small) so we can RELAY into the CKF.
            _corpus_budget = max(
                _envelope_remaining,
                min(int(self.prime_budget_tokens), 1500),
            )
            _ctx = dict(recipe_context)
            _ctx["budget_tokens"] = _corpus_budget
            try:
                primed_chunks = self._prime_corpus_envelope(_ctx)
            except Exception:  # pragma: no cover - defensive
                logger.exception("CRP context priming failed; continuing cold")
                primed_chunks = []
            if primed_chunks:
                primer = self._format_primed_envelope(primed_chunks, recipe_context)
                primer_tokens = estimate_tokens(primer)
                if primer_tokens <= _envelope_remaining:
                    # Fits in-context — push as a system primer.
                    messages.append(
                        {
                            "role": "system",
                            "name": "crp_corpus_primer",
                            "content": primer,
                        }
                    )
                    _envelope_remaining -= primer_tokens
                    _corpus_in_context = True
                    self._trace(
                        trace_path,
                        {
                            "event": "crp_context_primed",
                            "chunks": len(primed_chunks),
                            "primer_tokens": primer_tokens,
                            "envelope_remaining": _envelope_remaining,
                            "regulation": (recipe_context or {}).get("regulation", ""),
                        },
                    )
                else:
                    # Doesn't fit — RELAY into CKF so the LLM can pull
                    # via ``query_regulation`` / ``recall_facts``.
                    _relayed_corpus = _relay_chunks_to_ckf(
                        primed_chunks,
                        category="agent.primer.corpus_relay",
                        relay_window_id=window_id,
                    )
                    self._trace(
                        trace_path,
                        {
                            "event": "crp_context_relayed_to_ckf",
                            "chunks": len(primed_chunks),
                            "primer_tokens": primer_tokens,
                            "envelope_remaining": _envelope_remaining,
                            "facts_relayed": _relayed_corpus,
                        },
                    )
        # Phase 7.22 — always-on evidence priming for free-form Q&A.
        # When no ``recipe_context`` is supplied (the FE chat path),
        # we still pre-pack RAG + (optionally) web hits derived from
        # the user's task. This cuts the LLM round-trip count by 1
        # because iter-1 no longer has to call ``query_regulation``
        # just to discover the relevant clauses. CRP folds the combined
        # envelope so it never blows the context window. Best-effort:
        # any failure logs and continues cold.
        if (
            not _corpus_in_context
            and not primed_chunks
            and self.always_prime_evidence
            and self.rag is not None
            and self.prime_budget_tokens > 0
            and (safe_task or "").strip()
        ):
            web_hits: list[dict[str, Any]] = []
            try:
                primed_chunks, web_hits = self._prime_task_evidence(
                    task=safe_task, trace_path=trace_path
                )
            except Exception:  # pragma: no cover - defensive
                logger.exception("task evidence priming failed; continuing cold")
                primed_chunks, web_hits = [], []
            if primed_chunks or web_hits:
                primer_ctx: dict[str, Any] = {
                    "query": safe_task[:300],
                    "regulation": "",
                }
                primer = self._format_primed_envelope(primed_chunks, primer_ctx)
                if web_hits:
                    primer += "\n\n" + self._format_web_hits(web_hits)
                primer_tokens = estimate_tokens(primer)
                if primer_tokens <= _envelope_remaining:
                    messages.append(
                        {
                            "role": "system",
                            "name": "crp_evidence_primer",
                            "content": primer,
                        }
                    )
                    _envelope_remaining -= primer_tokens
                    self._trace(
                        trace_path,
                        {
                            "event": "crp_evidence_primed",
                            "chunks": len(primed_chunks),
                            "web_hits": len(web_hits),
                            "primer_tokens": primer_tokens,
                            "envelope_remaining": _envelope_remaining,
                        },
                    )
                else:
                    # CRP relay — push to fabric so the model can pull.
                    relayed = _relay_chunks_to_ckf(
                        primed_chunks,
                        category="agent.primer.evidence_relay",
                        relay_window_id=window_id,
                    )
                    # Web hits get relayed as compact text facts too —
                    # the model can recall_facts on them next turn.
                    if web_hits and self.fabric is not None:
                        web_chunks = [
                            {
                                "text": (
                                    f"[web evidence] {h.get('title', '')} "
                                    f"({h.get('url', '')}): "
                                    f"{(h.get('snippet') or '')[:600]}"
                                ),
                                "chunk_id": f"web:{h.get('url', '')[:80]}",
                                "source_id": h.get("domain", "web"),
                                "title": h.get("title", ""),
                            }
                            for h in web_hits
                        ]
                        relayed += _relay_chunks_to_ckf(
                            web_chunks,
                            category="agent.primer.evidence_relay",
                            relay_window_id=window_id,
                        )
                    self._trace(
                        trace_path,
                        {
                            "event": "crp_evidence_relayed_to_ckf",
                            "chunks": len(primed_chunks),
                            "web_hits": len(web_hits),
                            "primer_tokens": primer_tokens,
                            "envelope_remaining": _envelope_remaining,
                            "facts_relayed": relayed,
                        },
                    )
        if budget_exhausted:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Clarification budget is exhausted for this session. "
                        "Do NOT call request_clarification. Produce a final, "
                        "cited answer with the information already gathered "
                        "and clearly flag any residual assumptions."
                    ),
                }
            )
        if safe_context.strip():
            messages.append(
                {
                    "role": "system",
                    "name": "crp_session_context",
                    "content": f"Session context:\n{safe_context.strip()}",
                }
            )
        # Phase 6 \u2014 multi-turn message history. The API layer hands
        # us the prior `[{role, content}]` array for this session
        # (already relevance-scored + token-budgeted). Replay them as
        # real chat turns so the LLM sees the conversation as a
        # conversation, not as a text-blob system message.
        if prior_messages:
            for m in prior_messages:
                role = (m.get("role") or "").strip().lower()
                content = (m.get("content") or "").strip()
                if not content or role not in {"user", "assistant"}:
                    continue
                if self.redact_pii_pre_llm:
                    try:
                        content = redact_pii(content).text
                    except Exception:
                        pass
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": safe_task})

        # ── B9 CRP-amplification: agent-side intelligence seeding ──────
        # Closes COMPLIANCE_MODEL_GAPS §B9.1–B9.3:
        #   1. InjectionDetector scan on user task (mirrors proxy stack
        #      so self-hosted agent calls still get the 21-pattern +
        #      optional ML protection).
        #   2. ExtractionPipeline run over the user task to emit
        #      structured Facts straight into the CKF before the LLM
        #      sees the message — auditors get a typed view of what the
        #      user actually said, and the agent's recall_facts tool can
        #      hit them in subsequent turns.
        #   3. Proactive pattern_query against the CKF for any prior
        #      compliance facts already on file for this customer/system,
        #      surfaced as a primer system message so the LLM doesn't
        #      have to discover them via tool calls.
        # All three are best-effort; any failure logs and continues.
        injection_blocked = False
        # SAFETY-NOTE: scan_for_injection only scans the user task, not
        # tool results or assistant messages. A compromised tool result
        # (e.g. a malicious web page returned by web_search) could inject
        # instructions into the conversation. The proper fix is to scan
        # EVERY message before it enters the LLM context — scheduled for
        # the AI safety hardening run.
        if self.seed_intelligence:
            try:
                inj = scan_for_injection(safe_task)
                if inj.risk != "NONE":
                    self._trace(
                        trace_path,
                        {
                            "event": "injection_scan",
                            "risk": inj.risk,
                            "confidence": inj.confidence,
                            "flags": inj.flags,
                        },
                    )
                if inj.risk == "HIGH":
                    injection_blocked = True
            except Exception:  # pragma: no cover - never break session on scan
                logger.debug("agent-side injection scan failed", exc_info=True)

        if injection_blocked:
            # Don't echo the suspicious text back to the LLM. Return
            # an explicit refusal so callers can surface a clear error.
            return AgentResult(
                state="error",
                error=(
                    "input rejected: prompt-injection risk HIGH (blocked by CRP InjectionDetector)"
                ),
                iterations=0,
                tool_calls=0,
                facts_stored=0,
                session_id=session_id,
                trace_path=str(trace_path) if trace_path else "",
                pii_redactions=pii_redactions,
                reasoning_tape=list(reasoning_tape),
                experts_invoked=sorted(experts_invoked),
            )

        seeded_facts = 0
        if self.seed_intelligence and len(safe_task.strip()) >= 20:
            try:
                extracted = extract_facts_from_text(
                    safe_task,
                    source_window_id=window_id,
                    category="agent.user_task",
                )
                if extracted.facts and self.fabric is not None:
                    try:
                        self.fabric.store(extracted.facts, window_id=window_id)
                        seeded_facts = len(extracted.facts)
                    except Exception:
                        logger.debug("CKF store of extracted task facts failed", exc_info=True)
                if seeded_facts:
                    self._trace(
                        trace_path,
                        {
                            "event": "user_task_extracted",
                            "facts": seeded_facts,
                            "contradictions": len(extracted.contradictions),
                            "quality_issues": len(extracted.quality_issues),
                        },
                    )
                    # LLM-GAP-C boundary 1: user task → CKF facts
                    if _lineage is not None:
                        try:
                            _lineage.record(
                                data_id=window_id,
                                origin="user_task",
                                source_label=f"user:{customer_id}",
                                classification=None,
                            )
                        except Exception:
                            pass
            except Exception:  # pragma: no cover - defensive
                logger.debug("ExtractionPipeline on user task failed", exc_info=True)

        if self.seed_intelligence:
            try:
                seed = self._seed_prior_facts_primer(window_id=window_id)
                if seed:
                    seed_tokens = estimate_tokens(seed["primer"])
                    if seed_tokens <= _envelope_remaining:
                        messages.append(
                            {
                                "role": "system",
                                "name": "crp_ckf_seed",
                                "content": seed["primer"],
                            }
                        )
                        _envelope_remaining -= seed_tokens
                        self._trace(
                            trace_path,
                            {
                                "event": "ckf_facts_seeded",
                                "facts": seed["count"],
                                "primer_tokens": seed_tokens,
                                "envelope_remaining": _envelope_remaining,
                            },
                        )
                    else:
                        # The CKF-seed primer is already drawn FROM the
                        # CKF — when it doesn't fit in-context the
                        # facts are still reachable via ``recall_facts``
                        # / ``pattern_query_ckf``. No re-ingest needed.
                        self._trace(
                            trace_path,
                            {
                                "event": "crp_ckf_seed_relayed",
                                "facts": seed["count"],
                                "primer_tokens": seed_tokens,
                                "envelope_remaining": _envelope_remaining,
                                "note": "facts already in CKF — pull via recall_facts",
                            },
                        )
            except Exception:  # pragma: no cover - defensive
                logger.debug("CKF pattern_query seed failed", exc_info=True)

        self._trace(
            trace_path,
            {
                "event": "session_start",
                "ts": time.time(),
                "session_id": session_id,
                "customer_id": customer_id,
                "system_id": system_id,
                "task": task,
                "tools": self.tools.names(),
            },
        )
        if enforcer is not None:
            self._trace(
                trace_path,
                {
                    "event": "pep_init",
                    "mode": self.enforcer_mode,
                    "policies": len(enforcer.policies),
                    "safety_budget": enforcer.safety_budget,
                },
            )
        # CRP envelope-budget trace (Axiom 2: E = C − S − T − G).
        # Reports what the protocol formula computed and how much of
        # E was consumed by in-context primers. The remainder goes to
        # the live message slate; primer overflow has been relayed
        # into the CKF (see ``crp_*_relayed_to_ckf`` events).
        self._trace(
            trace_path,
            {
                "event": "crp_envelope_budget",
                "ctx_window_C": _carrier_window,
                "system_tokens_S": _system_tokens,
                "task_tokens_T": _task_tokens,
                "generation_reserve_G": _output_window,
                "envelope_max_E": _E_max,
                "envelope_remaining": _envelope_remaining,
                "envelope_used": max(0, _E_max - _envelope_remaining),
            },
        )

        total_tool_calls = 0
        facts_stored = 0
        tool_schemas = self.tools.schemas()
        # Round 8 — citation registry for the final answer validator.
        citation_validator = CitationValidator()
        # 7.15 — buffer of (intent, engine) pairs from web tool calls,
        # flushed to the SearXNG learning reranker at end-of-run.
        web_feedback_buffer: list[tuple[str, str]] = []
        # 7.17 — guard against tool-call loops where a small model
        # keeps re-issuing essentially the same query (LM Studio /
        # Llama-3.1-8B does this often). We canonicalise (tool, args)
        # and short-circuit a repeat call with a strong "you already
        # have this — finalise now" nudge so the loop converges.
        seen_calls: dict[tuple[str, str], dict[str, Any]] = {}

        # 7.19 — CRP message ledger. Every tool result is extracted,
        # supersession-checked, and warm-stored as ``Fact`` objects.
        # Before each LLM call we *rebuild* the message slate from a
        # CRP envelope-packed digest of these facts, so the prompt is
        # never larger than ``budget_tokens`` even after dozens of
        # tool calls. This is the protocol's "massive context
        # processing" guarantee applied to the live agentic loop.
        ledger = CrpMessageLedger(max_facts=4000)

        # ORCH-GAP-A: create the audit trail ONCE per session so the HMAC chain
        # stays continuous across all iterations (not broken/reset each iter).
        _crp_trail: Any | None = None
        _crp_pr: Any | None = None
        try:
            from crp.security import (  # type: ignore[import-not-found]
                ComplianceAuditTrail as _CrpAT,
                ComplianceEventType as _CET_INIT,
                DataLineageTracker as _DLT,
                ProcessingRecordKeeper as _CrpPR,
            )

            _hmac_key = os.environ.get("CRP_COMPLY_JWT_SECRET", "dev").encode("utf-8")
            _crp_trail = _CrpAT(signing_key=_hmac_key, session_id=session_id)
            _crp_pr = _CrpPR(session_id=session_id)
            _lineage = _DLT()
            _crp_trail.record(
                event_type=_CET_INIT.DATA_PROCESSED,
                session_id=session_id,
                data={
                    "event": "session_start",
                    "task_len": len(safe_task),
                    "tools": len(tool_schemas),
                },
            )
        except Exception:
            logger.debug("CRP audit trail init skipped (non-fatal)", exc_info=True)

        for iter_idx in range(1, self.max_iters + 1):
            # CRP envelope rebuild — pack the warm-store fact ledger
            # into a single Markdown digest sized to fit the budget,
            # and fold every older bulk tool-result body into a
            # one-line pointer. The most recent two tool messages stay
            # verbatim because the model is actively reasoning about
            # them; everything older is now in the ledger.
            try:
                if hasattr(self.llm, "context_window_size"):
                    ctx_window = int(self.llm.context_window_size())
                else:
                    provider = getattr(self.llm, "provider", None)
                    ctx_window = (
                        int(provider.context_window_size())
                        if provider is not None and hasattr(provider, "context_window_size")
                        else int(os.environ.get("CRP_COMPLY_CTX_WINDOW", "8192"))
                    )
                ledger_budget = max(512, int(0.35 * ctx_window))
                if ledger.fact_count > 0:
                    digest = ledger.pack_envelope(
                        task=safe_task,
                        budget_tokens=ledger_budget,
                        chars_per_token=2.5,
                    )
                    if digest.get("text"):
                        messages, folded = fold_messages_with_ledger(
                            messages,
                            ledger_text=str(digest["text"]),
                            keep_last=2,
                        )
                        if folded:
                            self._trace(
                                trace_path,
                                {
                                    "event": "crp_envelope_rebuild",
                                    "iter": iter_idx,
                                    "facts_packed": digest["facts_packed"],
                                    "envelope_tokens": digest["total_tokens"],
                                    "dropped": digest["dropped"],
                                    "supersessions": digest["supersessions"],
                                    "messages_folded": folded,
                                    "budget_tokens": ledger_budget,
                                },
                            )
            except Exception:  # pragma: no cover
                logger.debug("CRP envelope rebuild skipped", exc_info=True)

            # CRP input-context window: proactively fold older tool
            # results so the prompt always fits within the model's real
            # context window (LM Studio's 8k Llama, hosted 128k Claude,
            # whatever). This is the protocol's "never overflow"
            # guarantee applied at the agent layer \u2014 we never let the
            # call go out at a size we know the upstream will reject.
            #
            # Safe fallback values — overwritten inside the try-block below.
            # Without these, a compaction error (however unlikely) would cause
            # NameError when the LLM call below tries to read these variables.
            fitted_schemas: list[dict[str, Any]] = tool_schemas
            _effective_max_tokens: int = int(getattr(self.llm, "default_max_tokens", 2048))
            budget: int = max(
                1024,
                int(os.environ.get("CRP_COMPLY_CTX_WINDOW", "8192")) // 2,
            )
            try:
                if hasattr(self.llm, "context_window_size"):
                    ctx_window = int(self.llm.context_window_size())
                else:
                    provider = getattr(self.llm, "provider", None)
                    ctx_window = (
                        int(provider.context_window_size())
                        if provider is not None and hasattr(provider, "context_window_size")
                        else int(os.environ.get("CRP_COMPLY_CTX_WINDOW", "8192"))
                    )
                # 7.22 — CRP tool-schema fitting: prune/thin the schema list
                # so it never exceeds the available context on its own.
                # For a 4096-token LM Studio model, 23 full tool schemas is
                # ~6 000 tokens — already larger than the entire context
                # window before a single message is added.
                # CRP output-reserve scaling: on tiny windows (LM Studio's
                # 4096-token Llama-3.1-8B), reserving 25% of the window for
                # output (= 1024 tokens) leaves no room for the system
                # prompt + primers + user task once tool schemas are also
                # accounted for. Tool-call iterations only emit ~50–100
                # tokens of arguments anyway; the 1024-token reserve was
                # sized for the FINAL answer, but the continuation-stitch
                # path (``continue_truncated_answer``) already handles
                # answers longer than one window. So scale the reserve to
                # the window: 384 on 4 K, 768 on 8 K, 25 % thereafter. This
                # is what frees enough budget for the real ~1300-token
                # system prompt to ride through uncompacted on a 4 K model.
                if ctx_window <= 4096:
                    _output_cap = 384
                elif ctx_window <= 8192:
                    _output_cap = 768
                else:
                    _output_cap = ctx_window // 4
                # Budget the system prompt with the same conservative
                # heuristic used for messages (3.5 chars/tok) plus a small
                # safety margin. The hard-coded 800-token reserve from v3
                # under-estimated the real ~1370-token system prompt and
                # caused 400 "Context size exceeded" on 4 K local models.
                _system_prompt_reserve = _approx_tokens(SYSTEM_PROMPT, chars_per_token=3.5) + 200
                fitted_schemas = _fit_schemas_to_window(
                    tool_schemas,
                    ctx_window=ctx_window,
                    output_reserve=_output_cap,
                    system_prompt_reserve=_system_prompt_reserve,
                    chars_per_token=2.0,
                )
                _effective_max_tokens = min(
                    int(getattr(self.llm, "default_max_tokens", 2048)),
                    max(256, _output_cap),
                )
                _tool_json_len = len(json.dumps(fitted_schemas))
                # JSON tool schemas are token-dense; 2.0 chars/tok is a
                # safer estimate than the prose heuristic.
                _tool_schema_tokens = max(500, int(_tool_json_len / 2.0))
                reserve = _effective_max_tokens + _tool_schema_tokens + int(0.15 * ctx_window)
                budget = max(1024, ctx_window - reserve)
                # Small windows cannot afford to keep 4 full turns verbatim.
                # Scale keep_last so the live tail + system prompt + task still
                # has room inside the computed budget.
                _keep_last = 4
                if ctx_window <= 4096:
                    _keep_last = 2
                elif ctx_window <= 8192:
                    _keep_last = 3
                messages, compact_stats = compact_messages_for_budget(
                    messages,
                    budget_tokens=budget,
                    # Conservative prose estimate (3.5 chars/tok) prevents
                    # the 2.5 heuristic from under-counting English text and
                    # overflowing local LLMs.
                    chars_per_token=3.5,
                    keep_last=_keep_last,
                )
                if not compact_stats.get("skipped"):
                    self._trace(
                        trace_path,
                        {
                            "event": "crp_compact",
                            "iter": iter_idx,
                            **compact_stats,
                            "budget_tokens": budget,
                            "context_window": ctx_window,
                        },
                    )
                    logger.info(
                        "CRP compaction iter=%d before=%d after=%d folded=%d budget=%d",
                        iter_idx,
                        compact_stats.get("before", 0),
                        compact_stats.get("after", 0),
                        compact_stats.get("folded", 0),
                        budget,
                    )
            except Exception:  # pragma: no cover - never fail dispatch on compact
                logger.debug("CRP compaction skipped (non-fatal)", exc_info=True)

            # 7.18 — CRP-bounded LLM call. We attempt the call, and if
            # the upstream rejects it because of context overflow we
            # *aggressively re-compact* under a harsher budget (40% of
            # the window) and try again. CRP's promise is that the
            # protocol never lets a request leave the agent at a size
            # the upstream cannot accept. Up to two retries is enough
            # in practice — every retry halves the budget; if we still
            # cannot fit, the message slate truly cannot serve the
            # task and we raise the original error.
            # ── GAP 8 / ORCH-GAP-A: per-iteration audit event on the shared chain ──
            # The trail was created once before the loop; just record each iteration.
            if _crp_trail is not None:
                try:
                    from crp.security import ComplianceEventType as _CET_INIT  # type: ignore[import-not-found]

                    _crp_trail.record(
                        event_type=_CET_INIT.DATA_PROCESSED,
                        session_id=session_id,
                        data={
                            "iter": iter_idx,
                            "task_len": len(safe_task),
                            "tools": len(tool_schemas),
                        },
                    )
                except Exception:
                    logger.debug("CRP iter audit record skipped (non-fatal)", exc_info=True)

            turn = None
            llm_exc: Exception | None = None
            attempt = 0
            crp_retry_budget = budget
            while attempt < 3 and turn is None:
                attempt += 1
                # 7.20 — emit phase events so the frontend timeline stays
                # alive even when the upstream provider is in the long
                # prompt-eval phase (LM Studio CPU: ~100s on a 7k-token
                # prompt). Without these events the UI sees only the
                # 10s SSE heartbeat between tool calls and feels frozen.
                self._emit(
                    {
                        "event": "llm_phase",
                        "iter": iter_idx,
                        "attempt": attempt,
                        "phase": "prompt_send",
                        "messages": len(messages),
                        "tools": len(tool_schemas),
                    }
                )
                _llm_t0 = time.time()
                # Heartbeat ticker — emits ``llm_progress`` every 5s while
                # the upstream is busy so the FE timeline shows continuous
                # activity during the ~85s CPU prompt-eval. Without this
                # the user sees a single ``prompt_send`` event then dead
                # silence until ``received`` arrives ~90s later.
                _hb_stop = threading.Event()
                _hb_iter = iter_idx
                _hb_attempt = attempt
                _hb_t0 = _llm_t0

                def _heartbeat() -> None:
                    tick = 0
                    while not _hb_stop.wait(5.0):
                        tick += 1
                        try:
                            self._emit(
                                {
                                    "event": "llm_progress",
                                    "iter": _hb_iter,
                                    "attempt": _hb_attempt,
                                    "phase": "waiting_upstream",
                                    "elapsed_ms": int((time.time() - _hb_t0) * 1000),
                                    "tick": tick,
                                }
                            )
                        except Exception:  # pragma: no cover
                            logger.debug("llm_progress emit failed", exc_info=True)

                _hb_thread = threading.Thread(
                    target=_heartbeat, name="crp-llm-heartbeat", daemon=True
                )
                _hb_thread.start()
                try:
                    if self.event_sink is not None and hasattr(
                        self.llm, "chat_with_tools_streaming"
                    ):
                        iter_for_emit = iter_idx

                        def _on_text_delta(chunk: str, _i: int = iter_for_emit) -> None:
                            try:
                                self._emit(
                                    {
                                        "event": "llm_token",
                                        "iter": _i,
                                        "chunk": chunk,
                                    }
                                )
                            except Exception:  # pragma: no cover
                                logger.debug("llm_token emit failed", exc_info=True)

                        turn = self.llm.chat_with_tools_streaming(
                            messages=messages,
                            tools=fitted_schemas,
                            on_text_delta=_on_text_delta,
                            max_tokens=_effective_max_tokens,
                        )
                    else:
                        turn = self.llm.chat_with_tools(
                            messages=messages,
                            tools=fitted_schemas,
                            max_tokens=_effective_max_tokens,
                        )
                except Exception as exc:
                    llm_exc = exc
                    msg_lc = str(exc).lower()
                    is_ctx_overflow = any(
                        n in msg_lc
                        for n in (
                            "context size",
                            "context length",
                            "context window",
                            "exceeds the available context",
                            "maximum context length",
                            "too many tokens",
                            "prompt is too long",
                            # LM Studio wraps context-overflow HTTP 400
                            # responses as "Channel Error" at the SDK
                            # level rather than surfacing the raw message.
                            "channel error",
                        )
                    )
                    if not is_ctx_overflow or attempt >= 3:
                        break
                    # CRP harsh re-fold: halve the budget, run the
                    # full compactor again (it will now also fold
                    # tail tool results — see compact_messages_for_budget
                    # third pass), and retry.
                    crp_retry_budget = max(512, int(crp_retry_budget * 0.5))
                    self._trace(
                        trace_path,
                        {
                            "event": "crp_overflow_refold",
                            "iter": iter_idx,
                            "attempt": attempt,
                            "new_budget": crp_retry_budget,
                            "error": str(exc)[:200],
                        },
                    )
                    logger.warning(
                        "CRP refold (iter=%d attempt=%d budget=%d) due to: %s",
                        iter_idx,
                        attempt,
                        crp_retry_budget,
                        exc,
                    )
                    try:
                        messages, refold_stats = compact_messages_for_budget(
                            messages,
                            budget_tokens=crp_retry_budget,
                            chars_per_token=3.5,
                            keep_last=2,
                        )
                        self._trace(
                            trace_path,
                            {
                                "event": "crp_compact",
                                "iter": iter_idx,
                                "phase": "refold",
                                **refold_stats,
                                "budget_tokens": crp_retry_budget,
                            },
                        )
                    except Exception:
                        logger.debug("CRP refold failed", exc_info=True)
                finally:
                    # Always stop the heartbeat ticker — failure paths
                    # (timeout, context overflow, refold) must not leak
                    # the watcher thread into the next attempt.
                    _hb_stop.set()

            if turn is None:
                # All CRP retries exhausted.
                exc = llm_exc or RuntimeError("LLM call failed (no exception captured)")
                exc_str = str(exc)
                # Produce a user-friendly message for the most common
                # failure: the local LLM worker (LM Studio / Ollama) has
                # disconnected. This happens when the worker's WebSocket
                # to the relay drops (NAT timeout, reconnecting in 60s)
                # while Railway is processing tool results between LLM
                # calls. We surface this explicitly so operators can
                # see the cause without digging into tracebacks.
                _worker_offline = (
                    "worker is not connected" in exc_str.lower()
                    or "worker did not respond" in exc_str.lower()
                    or "workeroffline" in type(exc).__name__.lower()
                )
                if _worker_offline:
                    friendly = (
                        "Local LLM worker disconnected mid-session (WebSocket "
                        "NAT timeout). The worker is reconnecting — try again "
                        "in ~60 s, or restart the worker with: "
                        "`crp-comply worker --lmstudio http://localhost:1234`"
                    )
                    logger.warning(
                        "Worker offline at iter %s after %d CRP attempt(s): %s",
                        iter_idx,
                        attempt,
                        exc_str[:200],
                    )
                else:
                    # Use logger.error (not .exception) — we are NOT inside
                    # an except block here, so logger.exception would log
                    # "NoneType: None" as the exc_info which is misleading.
                    logger.error(
                        "LLM call failed at iter %s after %d CRP attempt(s): %s",
                        iter_idx,
                        attempt,
                        exc_str[:300],
                    )
                    friendly = f"{type(exc).__name__}: {exc_str}"
                self._trace(
                    trace_path,
                    {
                        "event": "llm_error",
                        "iter": iter_idx,
                        "error": exc_str[:300],
                        "worker_offline": _worker_offline,
                        "crp_attempts": attempt,
                    },
                )
                return AgentResult(
                    state="error",
                    error=friendly,
                    iterations=iter_idx - 1,
                    tool_calls=total_tool_calls,
                    facts_stored=facts_stored,
                    session_id=session_id,
                    trace_path=str(trace_path) if trace_path else "",
                    enforcer_state=self._enforcer_state(),
                    reasoning_tape=list(reasoning_tape),
                    experts_invoked=sorted(experts_invoked),
                )

            self._trace(
                trace_path,
                {
                    "event": "llm_turn",
                    "iter": iter_idx,
                    "finish_reason": turn.finish_reason,
                    "text_len": len(turn.text or ""),
                    "tool_calls": [self._summarise_tool_call(tc) for tc in turn.tool_calls],
                },
            )
            # 7.20 — phase event so the UI knows the upstream answered
            # and the agent is now interpreting the turn.
            self._emit(
                {
                    "event": "llm_phase",
                    "iter": iter_idx,
                    "phase": "received",
                    "elapsed_ms": int((time.time() - _llm_t0) * 1000),
                    "finish_reason": turn.finish_reason,
                    "text_len": len(turn.text or ""),
                    "tool_calls": len(turn.tool_calls or []),
                }
            )

            # Phase 6 — contribute this turn's token spend to the runtime budget.
            self._report_token_usage(self._count_turn_tokens(messages, turn.text, turn.tool_calls))

            # Terminal case — model produced a final text answer.
            if not turn.wants_tools:
                final_text = turn.text or ""
                cont_windows = 1
                cont_reason = "single_window"
                # Continuation wrap: if the provider truncated the answer
                # because of output-token limits, request more windows
                # and stitch them together (CRP continuation.stitch).
                if (
                    self.continue_on_length
                    and final_text
                    and (turn.finish_reason or "").lower() == "length"
                ):
                    # Phase 6 — resumable continuation state. The on_window
                    # hook persists partial windows after each continuation
                    # so /continue can resume even if the server restarts.
                    _continue_fn = self._continue_window(
                        messages,
                        system_prompt=self.system_prompt,
                        task_input=safe_task,
                    )
                    _max_chars = 40_000

                    def _on_window(windows: list[str]) -> None:
                        self._save_continuation_state(
                            base_messages=messages,
                            task_input=safe_task,
                            windows=windows,
                            max_windows=self.max_continuation_windows,
                            max_total_chars=_max_chars,
                        )

                    # Seed the initial partial answer before any continuation.
                    _on_window([final_text])

                    # Round 1 — use CRP ContinuationManager when the feature
                    # flag is enabled (default on). Falls back to the legacy
                    # hand-rolled stitch if CRP is unavailable.
                    if os.environ.get("CRP_COMPLY_USE_CRP_CONTINUATION", "1") == "1":
                        try:
                            _cm_outcome = self._get_crp_dispatcher().continue_truncated(
                                final_text,
                                continue_fn=_continue_fn,
                                max_windows=self.max_continuation_windows,
                            )
                            outcome = ContinuationOutcome(
                                final_text=_cm_outcome["final_text"],
                                windows=_cm_outcome["windows"],
                                termination_reason=_cm_outcome["termination_reason"],
                                stitched=_cm_outcome["stitched"],
                            )
                        except Exception:
                            logger.debug(
                                "CRP continuation failed; falling back to legacy", exc_info=True
                            )
                            outcome = continue_truncated_answer(
                                final_text,
                                continue_fn=_continue_fn,
                                max_windows=self.max_continuation_windows,
                                on_window=_on_window,
                            )
                    else:
                        outcome = continue_truncated_answer(
                            final_text,
                            continue_fn=_continue_fn,
                            max_windows=self.max_continuation_windows,
                            on_window=_on_window,
                        )
                    # Continuation is complete — clear the resumable state.
                    if self._memory is not None:
                        try:
                            self._memory.clear_continuation_state()
                        except Exception:
                            logger.debug("continuation state clear failed", exc_info=True)
                    final_text = outcome.final_text or final_text
                    cont_windows = outcome.windows
                    cont_reason = outcome.termination_reason
                    self._trace(
                        trace_path,
                        {
                            "event": "continuation",
                            "windows": cont_windows,
                            "reason": cont_reason,
                            "stitched": outcome.stitched,
                        },
                    )
                facts_stored += self._record_final_fact(
                    window_id=window_id,
                    task=task,
                    final_text=final_text,
                    session_id=session_id,
                )
                # ── GAP 8: CRP output PII scan + audit record ────────────
                # Scan the LLM's final answer for PII before it leaves the
                # agent boundary (mirrors the proxy's input scanner on
                # egress). Also close the audit trail record for this iter.
                try:
                    if final_text:
                        from crp.security import PIIScanner  # type: ignore[import-not-found]

                        _out_pii = PIIScanner().scan(final_text)
                        if getattr(_out_pii, "has_pii", False):
                            self._trace(
                                trace_path,
                                {
                                    "event": "output_pii_detected",
                                    "categories": [
                                        str(c) for c in getattr(_out_pii, "pii_types_found", [])
                                    ],
                                },
                            )
                            self._emit(
                                {
                                    "event": "crp_pii_warning",
                                    "iter": iter_idx,
                                    "categories": [
                                        str(c) for c in getattr(_out_pii, "pii_types_found", [])
                                    ],
                                }
                            )
                    if _crp_trail is not None:
                        from crp.security import ComplianceEventType as _CET  # type: ignore[import-not-found]

                        _crp_trail.record(
                            event_type=_CET.DATA_PROCESSED,
                            session_id=session_id,
                            data={"event": "answer_complete", "text_len": len(final_text)},
                        )
                    if _crp_pr is not None:
                        try:
                            _crp_pr.record_output(output_len=len(final_text))
                        except Exception:
                            pass
                except Exception:
                    logger.debug("CRP output audit failed (non-fatal)", exc_info=True)
                self._flush_web_feedback(web_feedback_buffer, trace_path=trace_path)
                # LLM-GAP-C boundary 3: final answer leaving the agent boundary
                if _lineage is not None:
                    try:
                        _lineage.record(
                            data_id=session_id,
                            origin="agent_output",
                            source_label="agent",
                            classification=None,
                        )
                    except Exception:
                        pass
                self._trace(
                    trace_path, {"event": "session_end", "state": "done", "iterations": iter_idx}
                )
                # Round 8 — validate citations in the final answer. Invalid
                # markers are stripped before the answer leaves the agent.
                _validation = citation_validator.validate(final_text, on_invalid="strip")
                if not _validation.ok:
                    self._trace(
                        trace_path,
                        {
                            "event": "citation_invalid",
                            "invalid_ids": _validation.invalid_ids,
                            "valid_ids": _validation.valid_ids,
                        },
                    )
                    final_text = _validation.cleaned_text
                return AgentResult(
                    state="done",
                    final_text=final_text,
                    iterations=iter_idx,
                    tool_calls=total_tool_calls,
                    facts_stored=facts_stored,
                    session_id=session_id,
                    trace_path=str(trace_path) if trace_path else "",
                    clarifications_used=clarifications_used,
                    clarification_budget=self.max_clarifications,
                    pii_redactions=pii_redactions,
                    continuation_windows=cont_windows,
                    continuation_reason=cont_reason,
                    confidence=0.9 if _validation.ok else 0.5,
                    enforcer_state=self._enforcer_state(),
                    reasoning_tape=list(reasoning_tape),
                    experts_invoked=sorted(experts_invoked),
                )

            # Tool-calling case — append the assistant's raw message (required
            # by OpenAI tool protocol), then every tool response.
            # ORCH-GAP-B: PII-scan the intermediate thinking text before it is
            # recycled into the next iteration's context window.
            if turn.text:
                try:
                    from crp.security import PIIScanner as _InterimPII  # type: ignore[import-not-found]

                    _interim_result = _InterimPII().scan(turn.text)
                    if getattr(_interim_result, "has_pii", False):
                        _categories = [
                            str(c) for c in getattr(_interim_result, "pii_types_found", [])
                        ]
                        self._trace(
                            trace_path,
                            {
                                "event": "intermediate_pii_detected",
                                "iter": iter_idx,
                                "categories": _categories,
                            },
                        )
                        self._emit(
                            {
                                "event": "crp_pii_warning",
                                "iter": iter_idx,
                                "source": "intermediate_text",
                                "categories": _categories,
                            }
                        )
                except Exception:
                    logger.debug("intermediate PII scan skipped (non-fatal)", exc_info=True)
            if turn.raw_assistant_message is not None:
                messages.append(turn.raw_assistant_message)
            else:
                # Fallback shape for providers that didn't hand back raw_msg.
                messages.append(
                    {
                        "role": "assistant",
                        "content": turn.text or "",
                        "tool_calls": turn.tool_calls,
                    }
                )

            for call in turn.tool_calls:
                total_tool_calls += 1
                call_id, name, args = _unpack_tool_call(call)
                self._trace(
                    trace_path,
                    {
                        "event": "tool_call",
                        "iter": iter_idx,
                        "tool": name,
                        "call_id": call_id,
                        "arguments": args,
                    },
                )

                # 7.17 — duplicate tool-call short-circuit. We canonicalise
                # the (tool, args) into a string key and remember the
                # *result* of the first call. A repeat returns the cached
                # payload plus a hard "do not repeat — finalise" nudge so
                # the LLM stops looping and produces an answer.
                try:
                    args_key = json.dumps(
                        args if isinstance(args, dict) else {"_": args},
                        sort_keys=True,
                        default=str,
                    )
                except Exception:
                    args_key = repr(args)
                dup_key = (name, args_key)
                seen = seen_calls.get(dup_key)
                if seen is not None:
                    duplicate_count = int(seen.get("count", 1)) + 1
                    seen["count"] = duplicate_count
                    self._trace(
                        trace_path,
                        {
                            "event": "tool_call_deduped",
                            "tool": name,
                            "call_id": call_id,
                            "occurrence": duplicate_count,
                        },
                    )
                    nudge = (
                        "DUPLICATE CALL DETECTED. You already invoked "
                        f"`{name}` with these exact arguments — see the "
                        "earlier tool result above. Do NOT call this tool "
                        "again with the same arguments. Either (a) call a "
                        "different tool, (b) refine the arguments "
                        "materially, or (c) stop calling tools and write "
                        "the final answer using the evidence you already "
                        "have."
                    )
                    cached_payload = dict(seen.get("payload") or {})
                    cached_payload["_duplicate_call_warning"] = nudge
                    cached_payload["_duplicate_occurrence"] = duplicate_count
                    duplicate_result = ToolResult(tool_name=name, ok=True, payload=cached_payload)
                    messages.append(duplicate_result.as_tool_message(call_id))
                    # On the *third* duplicate call we force-stop tooling
                    # and steer the model to finalise.
                    if duplicate_count >= 3:
                        messages.append(
                            {
                                "role": "user",
                                "content": (
                                    "STOP. You have called the same tool with "
                                    "the same arguments three times. Write the "
                                    "final answer now using the tool results "
                                    "already in this conversation."
                                ),
                            }
                        )
                    continue

                # ── Policy Enforcement Point (PEP) gate ─────────────
                # Every tool call flows through the enforcer before execution.
                # DENY → blocked with explanation
                # CHECKPOINT → paused for human approval
                # LOG → allowed but audited
                # ALLOW → normal execution
                if self.enforcer is not None:
                    decision = self.enforcer.check_tool_call(
                        name,
                        args,
                        context={
                            "iter": iter_idx,
                            "session_id": session_id,
                        },
                    )
                    if decision.action == PermissionLevel.DENY:
                        self._trace(
                            trace_path,
                            {
                                "event": "pep_denied",
                                "tool": name,
                                "reason": decision.reason,
                                "budget_remaining": decision.safety_budget_remaining,
                            },
                        )
                        denied_result = ToolResult(
                            tool_name=name,
                            ok=False,
                            error=f"POLICY DENIED: {decision.reason}. "
                            f"This tool call violates the configured safety policy. "
                            f"Try a different tool or approach.",
                        )
                        messages.append(denied_result.as_tool_message(call_id))
                        continue
                    if decision.action == PermissionLevel.CHECKPOINT:
                        self._trace(
                            trace_path,
                            {
                                "event": "pep_checkpoint",
                                "tool": name,
                                "reason": decision.reason,
                                "checkpoint_id": decision.checkpoint_context.get("checkpoint_id"),
                                "budget_remaining": decision.safety_budget_remaining,
                            },
                        )
                        _cp_id = decision.checkpoint_context.get("checkpoint_id", "unknown")
                        checkpoint_result = ToolResult(
                            tool_name=name,
                            ok=False,
                            error=(
                                f"CHECKPOINT REQUIRED: {decision.reason}. "
                                f"A human reviewer must approve this tool call before it executes. "
                                f"Checkpoint ID: {_cp_id}."
                            ),
                        )
                        messages.append(checkpoint_result.as_tool_message(call_id))
                        continue
                    if decision.action == PermissionLevel.LOG:
                        self._trace(
                            trace_path,
                            {
                                "event": "pep_logged",
                                "tool": name,
                                "reason": decision.reason,
                                "budget_remaining": decision.safety_budget_remaining,
                            },
                        )
                    # ALLOW falls through to normal execution

                try:
                    result = self.tools.invoke(name, args)
                except ClarificationNeeded as clar:
                    # Enforce the clarification budget. If the caller has
                    # already used all their rounds, don't pause the
                    # session — convert the request into a tool result
                    # that tells the LLM to finalise with what it has.
                    if clarifications_used + 1 > self.max_clarifications:
                        self._trace(
                            trace_path,
                            {
                                "event": "clarification_suppressed",
                                "reason": "budget_exhausted",
                                "question": clar.question,
                            },
                        )
                        suppressed = ToolResult(
                            ok=True,
                            payload={
                                "note": (
                                    "Clarification budget exhausted. Produce "
                                    "a final answer now using the evidence "
                                    "already gathered; flag residual "
                                    "assumptions explicitly."
                                ),
                                "question_that_was_blocked": clar.question,
                            },
                        )
                        messages.append(suppressed.as_tool_message(call_id))
                        continue
                    clarifications_used += 1
                    self._trace(
                        trace_path,
                        {
                            "event": "clarification_needed",
                            "question": clar.question,
                            "context": clar.context,
                            "clarifications_used": clarifications_used,
                            "budget": self.max_clarifications,
                        },
                    )
                    # Round 7: persist the suspension through ClarifierStore so
                    # the legacy and Phase-7 paths share the same resume surface.
                    resume_token = make_resume_token()
                    slot_id = str(getattr(clar, "fact_key", "") or "")
                    try:
                        ClarifierStore().suspend(
                            resume_token=resume_token,
                            session_id=session_id,
                            run_id=session_id,
                            tenant_id=customer_id or "anonymous",
                            slot_id=slot_id,
                            question=clar.question,
                            options=None,
                            snapshot={
                                "task": task,
                                "context": clar.context,
                                "clarifications_used": clarifications_used,
                            },
                        )
                    except Exception:
                        logger.exception("legacy clarifier suspend failed")
                    facts_stored += self._record_clarification_fact(
                        window_id=window_id,
                        question=clar.question,
                        session_id=session_id,
                    )
                    return AgentResult(
                        state="awaiting_clarification",
                        pending_question=clar.question,
                        pending_context=clar.context,
                        iterations=iter_idx,
                        tool_calls=total_tool_calls,
                        facts_stored=facts_stored,
                        session_id=session_id,
                        trace_path=str(trace_path) if trace_path else "",
                        clarifications_used=clarifications_used,
                        clarification_budget=self.max_clarifications,
                        pii_redactions=pii_redactions,
                        pending_priority=getattr(clar, "priority", "medium"),
                        pending_skippable=bool(getattr(clar, "skippable", False)),
                        pending_fact_key=slot_id,
                        resume_token=resume_token,
                        pending_action="probe",
                        enforcer_state=self._enforcer_state(),
                        reasoning_tape=list(reasoning_tape),
                        experts_invoked=sorted(experts_invoked),
                    )

                self._trace(
                    trace_path,
                    {
                        "event": "tool_result",
                        "tool": name,
                        "call_id": call_id,
                        "ok": result.ok,
                        "payload_keys": sorted(result.payload.keys()) if result.ok else [],
                        "error": result.error,
                    },
                )
                if result.ok:
                    self._dedup_chunks_in_payload(result.payload, trace_path=trace_path)
                _tool_msg = result.as_tool_message(call_id)
                # CRP input-context guarantee: if this single tool result
                # is itself larger than the model's context window can
                # comfortably tolerate (a real failure mode on small
                # local models like LM Studio's 4096-token Llama), run
                # CRP auto-ingest over it BEFORE it lands in
                # ``messages``. The bulky JSON body is replaced with a
                # short synthesised summary; the extracted Facts are
                # pushed into the session warm store so the next
                # envelope rebuild surfaces them. See ``crp_integration.
                # crp_autoingest_message`` for the full contract.
                #
                # Skip autoingest for tool results that the CRP
                # envelope packer ALREADY packed (``crp_envelope`` key
                # in the payload). Those results have a hard token
                # budget from ``pack_hits_to_envelope`` and are never
                # truly enormous — running ExtractionPipeline on top
                # would only add CPU overhead (sentence-transformers,
                # no max_length → very slow on CPU) without benefit.
                # The compaction's third pass handles them if they
                # still need trimming. Auto-ingest is reserved for
                # genuinely unconstrained tool outputs (web_research,
                # run_recipe, etc.).
                _is_crp_packed = bool(
                    result.ok
                    and isinstance(result.payload, dict)
                    and result.payload.get("crp_envelope")
                )
                try:
                    _provider_for_ai = getattr(self.llm, "provider", None)
                    _ctx_window_for_ai = (
                        int(_provider_for_ai.context_window_size())
                        if _provider_for_ai is not None
                        and hasattr(_provider_for_ai, "context_window_size")
                        else int(os.environ.get("CRP_COMPLY_CTX_WINDOW", "8192"))
                    )
                    # Threshold: skip auto_ingest unless the result is
                    # genuinely huge — larger than half the context
                    # window. Smaller results are handled by the
                    # compaction's hard-clip (third pass). The old
                    # ctx//4 threshold caused auto_ingest to fire on
                    # every query_regulation call on 4096-window
                    # models, running ExtractionPipeline with no
                    # max_length and hanging the agent for minutes.
                    _ai_threshold = int(
                        os.environ.get(
                            "CRP_COMPLY_AUTOINGEST_THRESHOLD_TOKENS",
                            str(max(2000, _ctx_window_for_ai // 2)),
                        )
                    )
                    _warm_store_for_ai = getattr(ledger, "_store", None)
                    if not _is_crp_packed:
                        _tool_msg, _ai_stats = crp_autoingest_message(
                            _tool_msg,
                            warm_store=_warm_store_for_ai,
                            context_window=_ctx_window_for_ai,
                            threshold_tokens=_ai_threshold,
                            task_intent=safe_task[:300],
                            tool_name=name,
                        )
                        if not _ai_stats.get("skipped"):
                            self._trace(
                                trace_path,
                                {
                                    "event": "crp_autoingest",
                                    "iter": iter_idx,
                                    "tool": name,
                                    "call_id": call_id,
                                    **_ai_stats,
                                },
                            )
                except Exception:
                    logger.debug("crp_autoingest_message failed", exc_info=True)
                messages.append(_tool_msg)
                # Remember the call so a future duplicate can short-circuit.
                seen_calls[dup_key] = {
                    "count": 1,
                    "payload": dict(result.payload) if result.ok else {},
                }
                # CRP message ledger — extract structured Facts from the
                # tool payload, run supersession against prior facts, and
                # store in the session warm store. The next iteration's
                # envelope rebuild will pull from this ledger.
                if result.ok:
                    try:
                        added = ledger.ingest_tool_result(
                            name,
                            result.payload,
                            call_id=call_id,
                            window_id=window_id,
                        )
                        if added:
                            self._trace(
                                trace_path,
                                {
                                    "event": "crp_ledger_ingest",
                                    "tool": name,
                                    "call_id": call_id,
                                    "facts_added": added,
                                    "fact_count": ledger.fact_count,
                                    "supersessions": ledger.supersessions,
                                },
                            )
                            # Round 8 — register tool-returned citations so
                            # the final-answer validator knows what is valid.
                            citation_validator.register_citations(
                                _extract_citations_from_payload(result.payload)
                            )
                            # LLM-GAP-C boundary 2: tool result → ledger
                            if _lineage is not None:
                                try:
                                    _lineage.record(
                                        data_id=f"tool:{call_id}",
                                        origin="tool_result",
                                        source_label=name,
                                        classification=None,
                                    )
                                except Exception:
                                    pass
                    except Exception:  # pragma: no cover
                        logger.debug("ledger ingest failed", exc_info=True)
                facts_stored += self._record_tool_fact(
                    window_id=window_id,
                    tool=name,
                    args=args,
                    result=result,
                    session_id=session_id,
                )
                # 7.15 — accumulate web learning signals.
                if result.ok and name in (
                    "web_search",
                    "web_research",
                    "vendor_profile",
                ):
                    self._collect_web_feedback(
                        name,
                        args,
                        result.payload,
                        web_feedback_buffer,
                    )

        # Exhausted iteration budget.
        self._trace(
            trace_path, {"event": "session_end", "state": "max_iters", "iterations": self.max_iters}
        )
        return AgentResult(
            state="max_iters",
            final_text="",
            iterations=self.max_iters,
            tool_calls=total_tool_calls,
            facts_stored=facts_stored,
            session_id=session_id,
            trace_path=str(trace_path) if trace_path else "",
            clarifications_used=clarifications_used,
            clarification_budget=self.max_clarifications,
            pii_redactions=pii_redactions,
            enforcer_state=self._enforcer_state(),
            reasoning_tape=list(reasoning_tape),
            experts_invoked=sorted(experts_invoked),
        )

    # --------------------------------------------------------- continuation

    def _save_continuation_state(
        self,
        *,
        base_messages: list[dict[str, object]],
        task_input: str,
        windows: list[str],
        max_windows: int,
        max_total_chars: int,
    ) -> None:
        """Persist partial continuation windows to the memory substrate.

        Phase 6 — makes ``/continue`` resumable across API calls and server
        restarts. If no memory handle is available, this is a no-op.
        """
        if self._memory is None:
            return
        try:
            self._memory.save_continuation_state(
                {
                    "partial_answer": "\n\n".join(windows) if windows else "",
                    "windows": list(windows),
                    "envelope": [dict(m) for m in base_messages],
                    "task_input": task_input,
                    "remaining_windows": max(0, max_windows - len(windows)),
                    "max_total_chars": max_total_chars,
                    "session_id": getattr(self._memory, "session_id", ""),
                }
            )
        except Exception:
            logger.debug("continuation state save failed", exc_info=True)

    def _continue_window(
        self,
        base_messages: list[dict[str, object]],
        system_prompt: str | None = None,
        task_input: str | None = None,
    ):
        """Return a callback suitable for :func:`continue_truncated_answer`.

        The callback issues a plain (tool-less) chat turn asking the LLM
        to continue from where the last window stopped.  Instead of carrying
        the entire accumulated conversation (which quickly overflows small
        local-model contexts), we build a fresh bounded window containing:
        the system prompt, a compact task reference, the prior output, and a
        CRP continuation directive.  This realizes "a new full window per
        continuation" rather than an ever-growing message list.
        """

        def _cb(last_window: str) -> tuple[str, str | None]:
            # Derive a compact task reference from the original task or message list.
            task_ref = task_input
            if not task_ref and base_messages:
                # Use the last user message before any assistant/tool content.
                for m in reversed(base_messages):
                    if m.get("role") == "user" and isinstance(m.get("content"), str):
                        task_ref = m["content"]
                        break
            if not task_ref:
                task_ref = "Continue the previous response."
            # Truncate very long task references so the window stays bounded.
            if isinstance(task_ref, str) and len(task_ref) > 1200:
                task_ref = task_ref[:1200] + "\n...[prior context summarized above]"

            sys_ref = system_prompt
            if not sys_ref and base_messages:
                for m in base_messages:
                    if m.get("role") == "system" and isinstance(m.get("content"), str):
                        sys_ref = m["content"]
                        break

            msgs: list[dict[str, object]] = []
            if sys_ref:
                msgs.append({"role": "system", "content": sys_ref})
            msgs.extend(
                [
                    {
                        "role": "user",
                        "content": (
                            f"=== ORIGINAL TASK ===\n{task_ref}\n\n"
                            "=== CONTINUATION DIRECTIVE ===\n"
                            "Your previous answer was truncated by the provider token limit. "
                            "Continue exactly where you stopped. Do not repeat prior content. "
                            "Do not restart. Finish the deliverable."
                        ),
                    },
                    {"role": "assistant", "content": last_window},
                    {
                        "role": "user",
                        "content": (
                            "[CONTINUE] Pick up from the end of the previous text and "
                            "produce the next part of the answer."
                        ),
                    },
                ]
            )
            try:
                turn = self.llm.chat_with_tools(messages=msgs, tools=[])
            except Exception:  # pragma: no cover - defensive
                return ("", "error")
            # Phase 6 — continuation windows also count toward the token budget.
            self._report_token_usage(self._count_turn_tokens(msgs, turn.text, turn.tool_calls))
            return (turn.text or "", (turn.finish_reason or "").lower() or None)

        return _cb

    # -------------------------------------------------------------- helpers

    def _enforcer_state(self) -> dict[str, Any]:
        """Return the current PEP state, or empty dict if not initialised."""
        if self.enforcer is None:
            return {}
        try:
            return self.enforcer.to_dict()
        except Exception:
            return {}

    def _trace_path(self, session_id: str) -> Path | None:
        if not self.trace_dir:
            return None
        return self.trace_dir / f"{session_id}.jsonl"

    def _prime_corpus_envelope(self, recipe_context: dict[str, Any]) -> list[dict[str, Any]]:
        """Run a CRP-packed RAG query for the drafting topic.

        ``recipe_context`` keys (all optional except one of ``query`` /
        ``topic_keywords``):

        * ``query`` (str) — explicit retrieval query
        * ``topic_keywords`` (list[str]) — joined into a query if
          ``query`` is absent
        * ``regulation`` (str) — purely informational; surfaced in the
          primer message so the LLM knows which regime it is drafting
          against
        * ``source_filter`` (list[str]) — restrict retrieval to a
          subset of corpora (e.g. ``["eu_ai_act"]``)
        * ``budget_tokens`` (int) — override the agent default
        """

        query = str(recipe_context.get("query") or "").strip()
        if not query:
            kws = recipe_context.get("topic_keywords") or []
            if isinstance(kws, str):
                kws = [kws]
            query = " ".join(str(k).strip() for k in kws if str(k).strip())
        if not query:
            return []
        budget = int(recipe_context.get("budget_tokens") or self.prime_budget_tokens)
        if budget <= 0:
            return []
        source_filter = recipe_context.get("source_filter") or None
        if isinstance(source_filter, str):
            source_filter = [source_filter]

        # ``RagService.query_packed`` runs MMR + CRP envelope packing so
        # we get diversity-aware, budget-bounded chunks. If the RAG
        # service in this deployment does not expose ``query_packed``
        # (e.g. test stubs), fall back to plain ``query``.
        if hasattr(self.rag, "query_packed"):
            result = self.rag.query_packed(
                query,
                top_k=20,
                source_filter=source_filter,
                budget_tokens=budget,
                diversity_lambda=0.7,
            )
            packed = result.get("packed") or []
        else:  # pragma: no cover - tested path is query_packed
            hits = self.rag.query(query, top_k=10, source_filter=source_filter)
            packed = [
                {
                    "chunk_id": h.get("chunk_id"),
                    "text": h.get("text"),
                    "source_id": h.get("source_id"),
                    "title": h.get("title"),
                    "article_id": h.get("article_id"),
                    "score": h.get("score"),
                }
                for h in hits
            ]
        return list(packed)

    # Freshness markers — keep aligned with loop_runtime._FRESHNESS_PATTERNS.
    _FRESH_MARKERS = (
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
    )

    def _task_needs_fresh_web(self, task: str) -> bool:
        t = (task or "").lower()
        return any(p in t for p in self._FRESH_MARKERS)

    def _prime_task_evidence(
        self, *, task: str, trace_path: Path | None
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Pre-pull RAG (+ optionally web) hits for the user's task.

        Embeds retrieval into the loop itself so the LLM does not have
        to spend an entire 90-second iteration just to call
        ``query_regulation`` and discover the obvious. Returns
        ``(rag_chunks, web_hits)`` — either may be empty on failure.
        """
        query = (task or "").strip()
        if not query:
            return [], []
        rag_chunks: list[dict[str, Any]] = []
        try:
            rag_chunks = self._prime_corpus_envelope({"query": query[:300]})
        except Exception:
            logger.debug("RAG priming failed", exc_info=True)
            rag_chunks = []

        web_hits: list[dict[str, Any]] = []
        if self.web_client is not None and self._task_needs_fresh_web(query):
            try:
                resp = self.web_client.search(
                    query[:300],
                    intent="general",
                    freshness="month",
                    max_results=5,
                    fetch_full_text=False,
                )
                results = resp.get("results") if isinstance(resp, dict) else None
                if isinstance(results, list):
                    for r in results[:5]:
                        if not isinstance(r, dict):
                            continue
                        web_hits.append(
                            {
                                "url": str(r.get("url") or ""),
                                "title": str(r.get("title") or ""),
                                "snippet": str(r.get("snippet") or r.get("content") or "")[:600],
                                "domain": str(r.get("domain") or r.get("host") or ""),
                                "trust_tier": int(r.get("trust_tier") or 4),
                            }
                        )
            except Exception:
                logger.debug("web priming failed", exc_info=True)
                web_hits = []
        return rag_chunks, web_hits

    @staticmethod
    def _format_web_hits(web_hits: list[dict[str, Any]]) -> str:
        """Render web hits as a citation-ready system message block.

        Format mirrors the corpus primer so the LLM treats them with
        the same retrieval semantics — quote, cite URL, do not invent.
        """
        if not web_hits:
            return ""
        lines = [
            "Pre-loaded web evidence for this question "
            "(intent-aware SearXNG sidecar — already in your working memory; "
            "cite the URL when you rely on a passage):",
        ]
        for i, h in enumerate(web_hits, 1):
            url = h.get("url") or ""
            title = h.get("title") or url
            snippet = (h.get("snippet") or "").strip()
            domain = h.get("domain") or ""
            tier = h.get("trust_tier") or 4
            lines.append(
                f"[W{i}] {title}\n  url: {url}\n  domain: {domain} (tier {tier})"
                + (f"\n  excerpt: {snippet}" if snippet else "")
            )
        return "\n\n".join(lines)

    def _seed_prior_facts_primer(self, *, window_id: str) -> dict[str, Any] | None:
        """Run a proactive ``pattern_query`` against the customer CKF.

        Closes COMPLIANCE_MODEL_GAPS §B9.3: the agent should not wait
        for the LLM to call ``recall_facts`` before learning what is
        already known about the customer/system. Here we issue a
        broad ``pattern_query`` for prior agent facts and surface the
        top results as a primer system message so the model starts
        with grounded context.

        Returns ``{"primer": <text>, "count": <n>}`` or ``None`` when
        no prior facts exist or CRP is unavailable.
        """

        # Phase 6 \u2014 always try the shared corpus CKF first so that
        # brand-new tenants (no per-user facts yet) still get a
        # regulation-grounded primer.
        try:
            from .ckf_corpus import query_corpus_ckf

            corpus_facts = query_corpus_ckf(max_results=4, min_confidence=0.6)
        except Exception:
            corpus_facts = []

        if self.fabric is None:
            scoped: list[Any] = []
        else:
            # Cheap pre-flight: skip the per-user query if the fabric
            # reports no facts yet (avoids loading the
            # sentence-transformer model on cold start for fresh
            # customers).
            try:
                fc = getattr(self.fabric, "fact_count", None)
                user_count = int(fc()) if callable(fc) else 0
            except Exception:
                user_count = 0

            scoped = []
            if user_count > 0:
                try:
                    res = pattern_query_ckf(
                        self.fabric,
                        entity_type=None,
                        relationship_type=None,
                        min_confidence=0.5,
                        max_results=8,
                    )
                except Exception:
                    res = {}
                facts = res.get("facts") or []
                for f in facts:
                    wid = getattr(f, "source_window_id", None) or (
                        f.get("source_window_id") if isinstance(f, dict) else None
                    )
                    if not wid or window_id.startswith(str(wid)) or str(wid).startswith(window_id):
                        scoped.append(f)
                if not scoped and facts:
                    scoped = list(facts)[:8]

        if not scoped and not corpus_facts:
            return None
        lines: list[str] = [
            "Pre-loaded customer knowledge [source:tenant] (CKF pattern_query \u2014 these "
            "are facts already on file from prior sessions; consult "
            "before calling request_clarification):"
        ]
        for i, f in enumerate(scoped[:8], 1):
            text = getattr(f, "text", None) or (f.get("text") if isinstance(f, dict) else "")
            cat = getattr(f, "category", None) or (f.get("category") if isinstance(f, dict) else "")
            text = (str(text) or "").strip().replace("\n", " ")
            if len(text) > 280:
                text = text[:280].rstrip() + "\u2026"
            label = f" [{cat}]" if cat else ""
            lines.append(f"  {i}.{label} [source:tenant] {text}")
        if corpus_facts:
            lines.append("")
            lines.append(
                "Pre-loaded regulation knowledge [source:corpus] (corpus CKF \u2014 facts "
                "extracted from EU AI Act / GDPR / NIST AI RMF / ISO at "
                "deploy time; cite the underlying article via "
                "query_regulation if you use these):"
            )
            for j, f in enumerate(corpus_facts, 1):
                text = getattr(f, "text", None) or (f.get("text") if isinstance(f, dict) else "")
                cat = getattr(f, "category", None) or (
                    f.get("category") if isinstance(f, dict) else ""
                )
                text = (str(text) or "").strip().replace("\n", " ")
                if len(text) > 280:
                    text = text[:280].rstrip() + "\u2026"
                label = f" [{cat}]" if cat else ""
                lines.append(f"  C{j}.{label} [source:corpus] {text}")
        return {"primer": "\n".join(lines), "count": len(scoped) + len(corpus_facts)}

    @staticmethod
    def _format_primed_envelope(
        chunks: list[dict[str, Any]], recipe_context: dict[str, Any]
    ) -> str:
        """Render the packed envelope as a system message.

        We include ``chunk_id`` next to each clause so the LLM can cite
        without an extra round-trip; ``query_regulation`` remains the
        canonical lookup if it needs more or wants to disambiguate.
        """

        regulation = str(recipe_context.get("regulation") or "").strip()
        header_parts = [
            "Pre-loaded regulatory context for this drafting session "
            "(CRP-packed envelope — already in your working memory; "
            "you may cite these chunk_ids directly without re-querying)."
        ]
        if regulation:
            header_parts.append(f"Primary regime: {regulation}.")
        header_parts.append(f"Chunks: {len(chunks)}.")
        body_lines: list[str] = []
        for i, ch in enumerate(chunks, 1):
            chunk_id = ch.get("chunk_id") or f"primed:{i}"
            text = (ch.get("text") or "").strip()
            if len(text) > 1200:
                text = text[:1200].rstrip() + " …[truncated]"
            article = ch.get("article_id") or ""
            title = ch.get("title") or ""
            label = " — ".join(p for p in (article, title) if p) or chunk_id
            body_lines.append(f"[{i}] chunk_id={chunk_id} · {label}\n{text}")
        return " ".join(header_parts) + "\n\n" + "\n\n".join(body_lines)

    def _trace(self, path: Path | None, event: dict[str, Any]) -> None:
        # Live event sink (used by the SSE streaming endpoint) — fire
        # before the disk write so a slow filesystem can't stall the
        # browser update. Errors raised by the sink are swallowed.
        sink = self.event_sink
        if sink is not None:
            try:
                sink(event)
            except Exception:  # pragma: no cover - never break run() on UI sink
                logger.debug("event_sink raised; ignoring", exc_info=True)
        if path is None:
            return
        try:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, default=str, ensure_ascii=False))
                fh.write("\n")
        except OSError:  # pragma: no cover - trace is best-effort
            logger.warning("failed to append trace to %s", path, exc_info=True)

    def _emit(self, event: dict[str, Any]) -> None:
        """Sink-only event (no disk trace).

        Fast-path for high-volume signals (per-token streaming, phase
        markers) where appending to the disk trace would dominate
        wall-clock. We swallow any sink exception so the agent loop
        keeps running even if the SSE writer dies.
        """
        sink = self.event_sink
        if sink is None:
            return
        try:
            sink(event)
        except Exception:  # pragma: no cover - never break run() on UI sink
            logger.debug("event_sink raised; ignoring", exc_info=True)

    @staticmethod
    def _window_id(*, customer_id: str, system_id: str, session_id: str) -> str:
        parts = [p for p in (customer_id.strip(), system_id.strip(), session_id) if p]
        return "/".join(parts) if parts else session_id

    @staticmethod
    def _summarise_tool_call(call: dict[str, object]) -> dict[str, object]:
        _, name, args = _unpack_tool_call(call)
        return {"name": name, "arg_keys": sorted(args.keys())}

    def _run_via_crp_dispatch(
        self,
        *,
        mode: str,
        task: str,
        system_id: str,
        customer_id: str,
        session_id: str,
        extra_context: str,
        recipe_context: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Phase 3 — delegate the whole task to ``crp.Client.dispatch_*``.

        Bypasses the bespoke tool loop entirely. PII redaction, the
        live event-sink, the per-tier output-token cap, and pre-seeding
        of the CRP WarmStore from our RAG corpus are all still
        respected. Tool-mediated CKF facts that the legacy loop records
        are not produced here because no tools fire.
        """
        trace_path = self._trace_path(session_id)
        full_task = (
            task if not extra_context.strip() else (f"{extra_context.strip()}\n\nTask:\n{task}")
        )
        if self.redact_pii_pre_llm:
            r = redact_pii(full_task)
            full_task = r.text

        # B-2 — emit a "research mode — clarifications disabled" trace
        # so the UI can warn the user when a deliverable that normally
        # needs Socratic Q&A is being run via the CRP-native path.
        recipe_needs_qna = bool(
            (recipe_context or {}).get("requires_clarification")
            or (recipe_context or {}).get("recipe_id")
        )
        if recipe_needs_qna:
            self._trace(
                trace_path,
                {
                    "event": "crp_dispatch_research_mode",
                    "mode": mode,
                    "warning": (
                        "Running a deliverable recipe via CRP-native dispatch — "
                        "clarification protocol and domain tools are disabled. "
                        "For full fidelity, unset CRP_COMPLY_AGENT_DISPATCH_MODE."
                    ),
                },
            )

        # B-1 — pre-seed the CRP WarmStore from our RAG corpus so the
        # §22 cognitive loop and ``dispatch_stream_augmented`` have
        # something to retrieve. Without this, ``stream_augmented``
        # degrades to a plain stream.
        pre_ingest: list[dict[str, Any]] | None = None
        if recipe_context and self.rag is not None and self.prime_budget_tokens > 0:
            try:
                primed_chunks = self._prime_corpus_envelope(recipe_context)
                if primed_chunks:
                    pre_ingest = [
                        {
                            "text": str(c.get("text") or ""),
                            "source": str(c.get("source_id") or "corpus"),
                        }
                        for c in primed_chunks
                        if c.get("text")
                    ]
                    self._trace(
                        trace_path,
                        {
                            "event": "crp_dispatch_pre_ingest",
                            "chunks": len(pre_ingest),
                        },
                    )
            except Exception:
                logger.exception("CRP pre-ingest priming failed; continuing cold")

        # Forward the per-tier output-token cap so CRP's dispatch
        # honours it. ComplianceLLM clamps via ``_apply_routing`` only
        # when the call goes through ``chat_with_tools`` — the Phase 3
        # path bypasses that, so we re-apply the cap here. The
        # ``ComplianceLLM`` carries ``default_max_tokens`` after
        # ``_apply_routing`` was last called for this session.
        max_output_tokens = int(getattr(self.llm, "default_max_tokens", 2048))

        self._trace(
            trace_path,
            {
                "event": "crp_dispatch_start",
                "mode": mode,
                "session_id": session_id,
                "max_output_tokens": max_output_tokens,
                "pre_ingest_chunks": len(pre_ingest or []),
            },
        )

        # LLM-GAP-A: CRP audit trail for the native dispatch path (no per-iter loop here)
        _dispatch_trail: Any | None = None
        _dispatch_pr: Any | None = None
        try:
            from crp.security import (  # type: ignore[import-not-found]
                ComplianceAuditTrail as _DispAT,
                ComplianceEventType as _DispCET,
                ProcessingRecordKeeper as _DispPR,
            )

            _d_key = os.environ.get("CRP_COMPLY_JWT_SECRET", "dev").encode("utf-8")
            _dispatch_trail = _DispAT(signing_key=_d_key, session_id=session_id)
            _dispatch_pr = _DispPR(session_id=session_id)
            _dispatch_trail.record(
                event_type=_DispCET.DATA_PROCESSED,
                session_id=session_id,
                data={"event": "dispatch_start", "mode": mode, "task_len": len(full_task)},
            )
        except Exception:
            logger.debug("CRP dispatch audit trail init skipped (non-fatal)", exc_info=True)

        # Round 1 — route CRP-native dispatch through the dispatcher facade
        # so all CRP client lifecycle lives in one place.
        _crp_outcome = self._get_crp_dispatcher().dispatch_native(
            full_task,
            mode=mode,
            max_output_tokens=max_output_tokens,
            pre_ingest=pre_ingest,
        )
        outcome = CrpDispatchOutcome(
            output=_crp_outcome.get("output", ""),
            mode=_crp_outcome.get("mode", mode),
            error=_crp_outcome.get("error") or None,
            quality=_crp_outcome.get("quality"),
        )

        self._trace(
            trace_path,
            {
                "event": "crp_dispatch_end",
                "mode": mode,
                "ok": not outcome.error,
                "error": outcome.error,
                "output_chars": len(outcome.output),
            },
        )

        if _dispatch_trail is not None:
            try:
                from crp.security import ComplianceEventType as _DispCET  # type: ignore[import-not-found]

                _dispatch_trail.record(
                    event_type=_DispCET.DATA_PROCESSED,
                    session_id=session_id,
                    data={
                        "event": "dispatch_end",
                        "mode": mode,
                        "ok": not outcome.error,
                        "output_chars": len(outcome.output),
                        "pii_redactions": r.count if self.redact_pii_pre_llm else 0,
                    },
                )
            except Exception:
                logger.debug("CRP dispatch audit trail close skipped (non-fatal)", exc_info=True)
        # Record processing for GDPR Art. 30
        if _dispatch_pr is not None:
            try:
                _dispatch_pr.record_output(output_len=len(outcome.output))
            except Exception:
                logger.debug("CRP dispatch processing record skipped (non-fatal)", exc_info=True)

        if outcome.error:
            return AgentResult(
                state="error",
                error=outcome.error,
                iterations=1,
                tool_calls=0,
                facts_stored=0,
                session_id=session_id,
                trace_path=str(trace_path) if trace_path else "",
                enforcer_state=self._enforcer_state(),
            )

        return AgentResult(
            state="done",
            final_text=outcome.output,
            iterations=1,
            tool_calls=0,
            facts_stored=0,
            session_id=session_id,
            trace_path=str(trace_path) if trace_path else "",
            enforcer_state=self._enforcer_state(),
        )

    def _dedup_chunks_in_payload(
        self,
        payload: dict[str, Any],
        *,
        trace_path: Path | None,
    ) -> None:
        """Mark already-seen regulation chunks so the envelope stays lean.

        The LLM has limited working memory; re-injecting the full text of
        a clause it has already received this session bloats the prompt
        and contributes to context-overflow. We track ``chunk_id`` across
        all tool calls in this :meth:`run` and, when a tool returns an
        already-seen chunk, replace its ``text`` field with a one-line
        marker pointing to the prior reference. Score, title, source_id
        and clause id are preserved so the LLM can still cite it.
        """
        if not isinstance(payload, dict):
            return
        hits = payload.get("hits")
        if not isinstance(hits, list):
            return
        deduped = 0
        for h in hits:
            if not isinstance(h, dict):
                continue
            cid = h.get("chunk_id")
            if not isinstance(cid, str) or not cid:
                continue
            if cid in self._seen_chunk_ids:
                if h.get("text"):
                    h["text"] = (
                        f"[CRP-dedup: chunk_id={cid} already in context this "
                        "session — see earlier tool result]"
                    )
                    h["dedup"] = True
                    deduped += 1
            else:
                self._seen_chunk_ids.add(cid)
        if deduped:
            self._trace(
                trace_path,
                {
                    "event": "crp_dedup",
                    "chunks_deduped": deduped,
                    "session_seen_total": len(self._seen_chunk_ids),
                },
            )

    # ---------------------------------------------------------- fact writes

    def _record_tool_fact(
        self,
        *,
        window_id: str,
        tool: str,
        args: dict[str, Any],
        result: ToolResult,
        session_id: str,
    ) -> int:
        if self.fabric is None:
            return 0
        text = self._summarise_tool_text(tool, args, result)
        return self._store_fact(
            window_id=window_id,
            text=text,
            category=f"agent.tool.{tool}",
            metadata={
                "tool": tool,
                "ok": result.ok,
                "error": result.error or "",
                "session_id": session_id,
            },
        )

    def _record_final_fact(
        self,
        *,
        window_id: str,
        task: str,
        final_text: str,
        session_id: str,
    ) -> int:
        if self.fabric is None:
            return 0
        return self._store_fact(
            window_id=window_id,
            text=f"[final] task='{task[:180]}' -> {final_text[:800]}",
            category="agent.final",
            metadata={"session_id": session_id},
        )

    # ----------------------------------------------------- 7.15 web feedback

    def _collect_web_feedback(
        self,
        tool_name: str,
        args: dict[str, Any],
        payload: dict[str, Any],
        buffer: list[tuple[str, str]],
    ) -> None:
        """Record (intent, engine) signals for the SearXNG learning loop."""
        if self.web_feedback_client is None:
            return
        intent = (
            (args.get("intent") if isinstance(args, dict) else None)
            or payload.get("intent")
            or "general"
        )
        # Pull engines from any standard "results" list shape.
        engines: set[str] = set()
        results = payload.get("results") or []
        if isinstance(results, list):
            for hit in results:
                if isinstance(hit, dict):
                    eng = hit.get("engine") or hit.get("source")
                    if isinstance(eng, str) and eng:
                        engines.add(eng)
        # Vendor profile uses bucketed shape.
        for bucket in (
            (payload.get("buckets") or {}).values()
            if isinstance(payload.get("buckets"), dict)
            else []
        ):
            if not isinstance(bucket, list):
                continue
            for hit in bucket:
                if isinstance(hit, dict):
                    eng = hit.get("engine") or hit.get("source")
                    if isinstance(eng, str) and eng:
                        engines.add(eng)
        for eng in engines:
            buffer.append((str(intent), str(eng)))

    def _flush_web_feedback(
        self,
        buffer: list[tuple[str, str]],
        *,
        trace_path: Path | None,
    ) -> None:
        if not buffer or self.web_feedback_client is None:
            return
        sent = 0
        for intent, engine in buffer:
            try:
                self.web_feedback_client.feedback(
                    intent=intent,
                    engine=engine,
                    useful=True,
                    weight=1.0,
                )
                sent += 1
            except Exception:  # noqa: BLE001 — best-effort
                continue
        self._trace(
            trace_path,
            {
                "event": "web_feedback_flushed",
                "candidates": len(buffer),
                "sent": sent,
            },
        )

    def _record_clarification_fact(
        self,
        *,
        window_id: str,
        question: str,
        session_id: str,
    ) -> int:
        if self.fabric is None:
            return 0
        return self._store_fact(
            window_id=window_id,
            text=f"[clarification pending] {question}",
            category="agent.clarification",
            metadata={"session_id": session_id},
        )

    def _store_fact(
        self,
        *,
        window_id: str,
        text: str,
        category: str,
        metadata: dict[str, Any],
    ) -> int:
        try:
            from crp.extraction import Fact
        except Exception:  # pragma: no cover - CRP always present in prod
            return 0
        try:
            fact = Fact(
                id=str(uuid.uuid4()),
                text=text[:2000],
                category=category,
                source_window_id=window_id,
                confidence=0.9,
                extraction_stage="agent",
                created_at=time.time(),
                metadata=dict(metadata),
            )
            self.fabric.store([fact], window_id=window_id)
            return 1
        except Exception:  # pragma: no cover - never fail the session on CKF write errors
            logger.warning("CKF store failed", exc_info=True)
            return 0

    @staticmethod
    def _summarise_tool_text(tool: str, args: dict[str, Any], result: ToolResult) -> str:
        if not result.ok:
            return f"[tool:{tool}] FAILED args={_short_json(args)} error={result.error}"
        if tool == "query_regulation":
            hits = result.payload.get("hits") or []
            return f"[tool:{tool}] query='{args.get('query', '')[:120]}' -> {len(hits)} hits"
        if tool == "classify_ai_act_risk":
            return (
                f"[tool:{tool}] purpose='{args.get('intended_purpose', '')[:120]}' "
                f"-> risk_level={result.payload.get('risk_level')}"
            )
        if tool == "recall_facts":
            n = len(result.payload.get("pattern_matches") or [])
            return f"[tool:{tool}] filter={_short_json(args)} -> {n} matches"
        return f"[tool:{tool}] args={_short_json(args)} -> ok"


# ---------------------------------------------------------------------------
# Tool call unpacking — tolerate both OpenAI and Anthropic shapes
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# CRP tool-schema fitting for small-context models
# ---------------------------------------------------------------------------
# For a 4096-token LM Studio model the 23-tool registry JSON is ~15 000 chars
# (~6 000 tokens) — larger than the entire context window before any user
# message is added. CRP's "never overflow" guarantee must cover the tool
# dimension too.  _fit_schemas_to_window() prunes/thins the schema list so
# the JSON passed to each LLM call never exceeds the available token budget.
#
# Tier 1 — always sent: the model cannot function without retrieval /
#   clarification / web-search primitives.
# Tier 2 — sent when they fit: deterministic compliance checks & lookups.
# Tier 3 — everything else (advanced helpers, recipe tools): dropped first.

_TOOL_TIER_1: frozenset[str] = frozenset(
    {
        "query_regulation",
        "query_regulation_packed",
        "web_search",
        "recall_facts",
        "request_clarification",
    }
)

_TOOL_TIER_2: frozenset[str] = frozenset(
    {
        "classify_ai_act_risk",
        "check_high_risk_criteria",
        "lookup_annex",
        "lookup_gdpr",
        "search_iso42001",
        "check_dpia_required",
        "check_dpo_required",
        "estimate_fine_exposure",
        "run_pii_scan",
        "run_injection_check",
    }
)


def _fit_schemas_to_window(
    schemas: list[dict[str, Any]],
    ctx_window: int,
    chars_per_token: float = 2.5,
    output_reserve: int | None = None,
    system_prompt_reserve: int = 800,
) -> list[dict[str, Any]]:
    """Return a pruned/thinned copy of *schemas* that fits the available
    tool-schema token budget for this context window.

    Strategy (applied in order until we fit):

    1. Full list fits → return as-is.
    2. Drop Tier-3 tools (advanced helpers; not needed for baseline compliance).
    3. Strip ``description`` fields from Tier-2 tools to reclaim tokens.
    4. Drop Tier-2 tools one by one (smallest first).
    5. Tier-1 tools are always kept even if still over budget.
    """
    if output_reserve is None:
        # Default: cap at 25% of the context window.  2048 on a 4096-token
        # model leaves only 2048 tokens for the entire prompt+tools which is
        # impossible with the full tool registry.
        output_reserve = max(256, ctx_window // 4)

    # Available tokens for tool schemas = context minus output reserve,
    # system-prompt headroom, and a 15% tokeniser-drift safety margin.
    available = max(512, int((ctx_window - output_reserve - system_prompt_reserve) * 0.70))

    def _tok(s: list[dict[str, Any]]) -> int:
        return max(1, int(len(json.dumps(s)) / chars_per_token))

    # Phase 1: full list fits.
    if _tok(schemas) <= available:
        return schemas

    tier1 = [s for s in schemas if s.get("function", {}).get("name") in _TOOL_TIER_1]
    tier2 = [s for s in schemas if s.get("function", {}).get("name") in _TOOL_TIER_2]

    # Phase 2: drop Tier 3 (anything not in Tier 1 or Tier 2).
    tier3_names = [
        s.get("function", {}).get("name")
        for s in schemas
        if s.get("function", {}).get("name") not in _TOOL_TIER_1
        and s.get("function", {}).get("name") not in _TOOL_TIER_2
    ]
    combined = tier1 + tier2
    if _tok(combined) <= available:
        if tier3_names:
            logger.info(
                "CRP tool-fitting: dropped Tier-3 tools for %d-token window: %s",
                ctx_window,
                tier3_names,
            )
        return combined

    # Phase 3: strip descriptions from Tier 2 to reclaim tokens.
    def _strip_desc(schema: dict[str, Any]) -> dict[str, Any]:
        fn = schema.get("function")
        if not isinstance(fn, dict):
            return schema
        fn2 = {k: v for k, v in fn.items() if k != "description"}
        return {**schema, "function": fn2}

    tier2_thin = [_strip_desc(s) for s in tier2]
    combined_thin = tier1 + tier2_thin
    if _tok(combined_thin) <= available:
        logger.info(
            "CRP tool-fitting: stripped Tier-2 descriptions for %d-token window",
            ctx_window,
        )
        return combined_thin

    # Phase 4: drop Tier-2 tools one by one (keep the smallest first so
    # we retain the most tools possible).
    tier2_sorted = sorted(
        tier2_thin,
        key=lambda s: len(json.dumps(s)),
    )
    kept: list[dict[str, Any]] = list(tier1)
    for schema in tier2_sorted:
        candidate = kept + [schema]
        if _tok(candidate) <= available:
            kept = candidate
    if len(kept) > len(tier1):
        logger.info(
            "CRP tool-fitting: kept %d/%d Tier-2 tools for %d-token window",
            len(kept) - len(tier1),
            len(tier2),
            ctx_window,
        )
    else:
        logger.warning(
            "CRP tool-fitting: context window %d too small for any Tier-2 tools; "
            "sending Tier-1 only (%d tools)",
            ctx_window,
            len(tier1),
        )
    return kept


def _unpack_tool_call(call: dict[str, object]) -> tuple[str, str, dict[str, Any]]:
    """Normalise a tool-call dict from either provider.

    OpenAI shape::
        {"id": "...", "type": "function",
         "function": {"name": "...", "arguments": "{...}" or {...}}}

    Anthropic shape (as normalised by the CRP adapter)::
        {"id": "...", "name": "...", "input": {...}}  or equivalent.
    """
    call_id = str(call.get("id") or "")
    # Prefer "function" envelope (OpenAI)
    fn = call.get("function")
    if isinstance(fn, dict):
        name = str(fn.get("name") or "")
        raw_args = fn.get("arguments")
    else:
        name = str(call.get("name") or "")
        raw_args = call.get("input") or call.get("arguments")

    if isinstance(raw_args, str):
        try:
            args = json.loads(raw_args) if raw_args else {}
        except json.JSONDecodeError:
            args = {"_raw": raw_args}
    elif isinstance(raw_args, dict):
        args = raw_args
    else:
        args = {}
    return call_id, name, args


def _short_json(obj: Any, limit: int = 160) -> str:
    try:
        s = json.dumps(obj, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        s = str(obj)
    if len(s) > limit:
        s = s[: limit - 1] + "…"
    return s


__all__ = ["ComplianceAgent", "AgentResult", "AgentState", "SYSTEM_PROMPT"]
