# CRP × CRP-Comply integration audit — Phase 3 follow-up

> **Position in the timeline.** ``CRP_AUDIT.md`` was the Phase 1 baseline.
> Commit ``e103a46`` shipped Phase 2 (SSE streaming, ``/continue``,
> session-scoped chunk dedup). This document is the Phase 3 follow-up
> audit — **what we use now, what we still bypass, what is bug-shaped**.

## 0. TL;DR

After Phase 2 + Phase 3 we still **own a parallel agent loop** that
re-implements concerns CRP already ships: a tool registry, a context
budgeter, a continuation manager, a PII scanner, an injection scanner,
an extraction pipeline, a CKF facade, an event bus, a dispatch router.
The opt-in ``CRP_COMPLY_AGENT_DISPATCH_MODE`` switch from Phase 3 is the
**first** code path that lets a real CRP cognitive loop drive the run
end-to-end — but it is NOT the default, because our domain tools
(``query_regulation``, ``classify_ai_act_risk``, ``store_fact``, …)
have no equivalent inside CRP's ``CRP_CONTEXT_TOOLS``.

There are three honest bug-shaped issues left on the floor (§4).

---

## 1. Surface area inventory

### 1.1 What lives in ``crp-comply`` and SHOULD live there

| Area | Why it belongs here |
|---|---|
| Domain tools (``query_regulation``, ``classify_ai_act_risk``, ``conformity_assessment``, ``risk_register_lookup``, …) | Compliance-specific, not protocol-level. |
| Per-tenant CKF persistence path layout | We write the on-disk store; CRP defines the schema. |
| RAG corpus (BM25 + embeddings of regulations) | A specific retrieval substrate. |
| Recipe authoring | Vertical product feature. |
| Stripe metering, BYOK provider store, Clerk auth | Hosting-platform glue. |
| Session JSON layout under ``data/agent_sessions/`` | UI contract. |

### 1.2 What lives in ``crp-comply`` but DUPLICATES CRP

These are the integration debts the audit is about.

| In crp-comply | In CRP SDK | Status |
|---|---|---|
| ``ComplianceAgent.run`` tool loop in ``orchestrator.py`` (≈600 lines: tool dispatch, retry on length, clarification protocol, message budgeting) | ``crp.core.dispatch_router.CRPOrchestrator.dispatch_with_tools`` (pull-mode tool relay, 600+ lines, hardcoded to ``CRP_CONTEXT_TOOLS``) | **Bypassed.** Phase 3 added an opt-in switch but the default still runs ours. CRP's loop can't see our domain tools without an SDK extension. |
| ``compact_messages_for_budget`` in ``crp_integration.py`` | ``crp.envelope.packer.pack_facts`` + ``crp.envelope.scoring`` | **Partial.** Our compaction folds tool messages by character count; CRP's packer scores facts and budgets at token granularity. Equivalent for our purposes — but if we ever migrate to ``dispatch_with_tools`` the SDK does the budgeting natively and ours becomes dead code. |
| ``continue_truncated_answer`` (own naive stitcher fallback) | ``crp.continuation.stitch.stitch_many`` + ``crp.continuation.manager.ContinuationManager`` | **Lightly used.** We call ``stitch_many`` when present; full ``ContinuationManager`` (which tracks DAG nodes per window) is unused. |
| ``redact_pii`` wrapper | ``crp.security.PIIScanner`` | **Wrapped properly.** No duplication — we route through CRP. |
| ``scan_for_injection`` wrapper | ``crp.security.InjectionDetector`` | **Wrapped properly.** |
| ``extract_facts_from_text`` wrapper | ``crp.extraction.pipeline.ExtractionPipeline`` | **Wrapped properly.** |
| ``pack_hits_to_envelope`` wrapper | ``crp.envelope.packer.pack_facts`` | **Wrapped properly.** |
| ``WorkerAdapter`` LLM provider | ``crp.providers.base.LLMProvider`` ABC | **Implements correctly** since Phase 1 (``context_window_size``, ``count_tokens``, ``supports_tools``, ``generate_chat``, ``generate_chat_with_tools``). |
| Session-scoped chunk dedup (``self._seen_chunk_ids``) | ``crp.state.WarmStateStore`` would handle this natively if dispatch ran through CRP | **Local re-implementation.** Works, but only because the legacy loop is the default. The Phase 3 path doesn't need it because CRP's WarmStore already deduplicates on ``fact_id``. |

### 1.3 What CRP exposes that we still don't touch

These are unused capabilities in the SDK that we could light up next.

| Capability | Module | Why we'd use it |
|---|---|---|
| ``dispatch_agentic`` | ``crp.core.dispatch_router`` | **Phase 3 wired but opt-in.** §22 8-phase cognitive loop (analyse → plan → synthesise → route → generate → evaluate → revise → curate). Default path is still our loop. |
| ``dispatch_stream_augmented`` | same | **Phase 3 wired but opt-in.** Sentence-by-sentence injection of WarmStore facts mid-generation. Needs WarmStore pre-seeded with regulation chunks to be useful — currently we don't pre-seed in the Phase 3 path. |
| ``dispatch_with_tools`` | same | **Phase 3 wired but opt-in.** Pull-mode context relay. Limited to ``CRP_CONTEXT_TOOLS`` so it can't host our domain tools. |
| ``dispatch_progressive`` / ``dispatch_hierarchical`` / ``dispatch_reflexive`` | same | Different relay strategies. Untouched. |
| ``ingest`` / ``ingest_batch`` | ``CRPOrchestrator`` | **Untouched in agent runtime.** Only called inside the Phase 3 ``dispatch_via_crp`` helper as optional pre-ingest, currently never invoked because callers don't pass ``pre_ingest=``. |
| ``preview_envelope`` | same | Lets a UI show the user what's about to be packed before dispatch. We could surface this in the SSE stream as an ``envelope_preview`` event. **Untouched.** |
| ``boost_fact`` / ``penalize_fact`` / ``reject_fact`` | ``CRPOrchestrator.feedback`` | Per-fact RLHF surface — when a citation in our final answer is wrong, we could ``penalize_fact`` so the next session deprioritises it. **Untouched.** |
| ``WarmStateStore`` direct API | ``crp.state.warm_store`` | Cross-session knowledge. We currently use the per-tenant CKF for that, but WarmStore is the working set the dispatch router actually consults. **Untouched.** |
| ``ContextualKnowledgeFabric`` (``CKFConfig``) | ``crp.ckf.fabric`` | We instantiate this per-user via ``api/routes._get_user_ckf`` and feed it tool-derived facts. Reads via our own ``recall_facts`` tool, not via ``client.ckf.query``. |
| ``ComplianceAuditTrail`` | ``crp.observability`` | The SDK ships an audit trail of every dispatch with hashes + RBAC decisions. We don't read it; we keep our own JSONL traces under ``data/agent_traces/``. |
| ``HumanOversightController`` | ``crp.advanced`` | Workflow primitive for "must-human-approve" gates. Could power a "send for legal review" button. **Untouched.** |
| ``ConsentManager`` / ``RetentionManager`` / ``DataLineageTracker`` / ``ProcessingRecordKeeper`` | same | GDPR Article 30 record-keeping primitives. We re-implement parts of this in our own ``data_room`` layer. **Untouched at the CRP boundary.** |
| ``RiskClassifier`` | same | A generic risk classifier shipped with CRP. We have our own EU AI Act classifier in ``crp_comply/risk/``. **Different domain — keep ours.** |
| ``CrpFacilitator`` | ``crp.core.facilitator`` | The LLM-driven decision-maker that powers ``dispatch_agentic``. Reachable directly for "ask the LLM to pick a tool" scenarios. **Untouched.** |
| ``async_dispatch`` / ``async_dispatch_stream`` / ``async_ingest`` | ``CRPOrchestrator`` | Native asyncio variants. Our SSE endpoint runs the sync ``run`` in a thread; using async would let us drop the queue + executor bridge. |
| ``register_provider`` | same | Multi-provider routing (cost-aware fallback). Phase 1 added env-fallback DEEPINFRA→GROQ→TOGETHER→OPENROUTER→OPENAI but did so *outside* CRP. CRP's own router would be cleaner. |
| ``export_state`` | same | Sealed bundle of session state (DAG + envelope + warm store) for replay. Could power "share this conversation" or "export for audit". **Untouched.** |

---

## 2. The Phase 3 opt-in path — what works, what doesn't

The new ``CRP_COMPLY_AGENT_DISPATCH_MODE`` env-var routes ``ComplianceAgent.run`` straight to ``crp.Client.dispatch_*``.

### 2.1 Working

* All four CRP modes wire through correctly: ``agentic``, ``with_tools``, ``stream_augmented``, ``plain``.
* PII redaction still runs before the prompt crosses the SDK boundary.
* The SSE event sink fires ``crp_dispatch_start`` and ``crp_dispatch_end`` so the browser sees life-signs.
* Errors caught and surfaced as ``AgentResult(state="error")``.

### 2.2 Broken / limited

* **No domain tools.** ``dispatch_with_tools`` is hardcoded to ``CRP_CONTEXT_TOOLS``. The model in CRP-native mode CANNOT call ``query_regulation``, ``classify_ai_act_risk``, ``store_fact``, ``recall_facts`` or any of our 15+ tools. It only has ``recall_facts``, ``search_warm_store``, ``query_ckf``-style CRP context tools. **For most compliance tasks this gives a much weaker answer.**
* **No pre-seed.** We don't pre-ingest anything into the SDK's WarmStore before calling ``dispatch_agentic``, so the agentic 8-phase loop runs on an empty knowledge base. The Phase 3 helper accepts a ``pre_ingest=`` parameter but the orchestrator currently passes nothing.
* **No clarification protocol.** Our agent's main differentiator is the Socratic clarification flow. CRP's dispatch loops never raise ``ClarificationNeeded``, so a CRP-native session is single-shot.
* **No CKF write-back.** Tool-derived facts get persisted into the per-tenant CKF in the legacy path. The Phase 3 path produces no facts (no tools fire), so the user's evidence pack stays empty.

The opt-in switch is therefore best understood as an **A/B test rig**, not a production replacement. Setting it on a session for "free-form Q&A about EU AI Act Article 6" will work; setting it for "produce a DPIA" will not.

---

## 3. What changed in Phases 1-3

### Phase 1 (``bcdd0a5``)
* Drop reactive ``_dispatch_with_shrink`` retry hack.
* Add ``WorkerAdapter.context_window_size()``, ``count_tokens``, ``supports_tools``.
* Add ``compact_messages_for_budget`` and call it BEFORE every LLM round-trip.
* Simplify ``SYSTEM_PROMPT`` from 50 lines → 7 lines (tools come via OpenAI tools schema, not the prompt).
* Sidebar delete button. Sqlite ``check_same_thread=False`` + ``RLock``.
* DEEPINFRA / GROQ / TOGETHER / OPENROUTER / OPENAI env fallback chain.

### Phase 2 (``e103a46``)
* SSE endpoints: ``POST /agent/start/stream``, ``/agent/{id}/clarify/stream``, ``/agent/{id}/continue/stream``.
* ``POST /agent/{id}/continue`` for follow-up turns on closed (``done``/``max_iters``/``error``) sessions, preserving ``session_id`` and folding prior task + final + clarifications into ``extra_context``.
* ``ComplianceAgent.event_sink`` callback wired through ``_trace`` so every orchestrator event reaches the browser as it happens.
* Session-scoped retrieval dedup: ``self._seen_chunk_ids`` rewrites duplicate hits as one-line CRP markers across iterations.
* ``frontend/src/lib/api.ts`` SSE parser (since browser ``EventSource`` is GET-only); ``AgentChat.tsx`` renders a live progress ticker; follow-up message on a closed session now continues the same session_id instead of forking.

### Phase 3 (this commit)
* ``crp_integration.dispatch_via_crp(provider, *, system_prompt, task, mode)`` wraps the four ``crp.Client.dispatch_*`` variants.
* ``ComplianceAgent.run`` short-circuits to ``_run_via_crp_dispatch`` when ``CRP_COMPLY_AGENT_DISPATCH_MODE`` is set.
* Trace events ``crp_dispatch_start`` / ``crp_dispatch_end`` flow through the SSE sink.
* No regression — 455 / 459 tests pass, 4 skipped (unchanged).

---

## 4. Bug-shaped findings

### B-1. Stream-augmented mode dispatches against an empty WarmStore

``dispatch_stream_augmented`` only injects facts that already live in the WarmStore. Our Phase 3 wrapper supports a ``pre_ingest=`` parameter but the orchestrator never passes one, so this mode degrades to a plain stream. **Fix candidate:** when ``recipe_context`` is set, pre-seed via ``client.ingest_batch`` of the same chunks ``_prime_corpus_envelope`` already retrieves.

### B-2. CRP-native path silently drops the clarification budget

``ClarificationNeeded`` is a domain protocol the SDK doesn't know about. In CRP-native mode the agent will never ask the user a follow-up — it just hallucinates the missing facts. Either gate the env var to a "mode=research" UI affordance, or fall back to the legacy loop when ``recipe_context`` indicates a deliverable that requires Q/A.

### B-3. Phase 2 ``/continue`` extends ``extra_context`` without bound

Each follow-up turn appends ``Earlier question: …\nEarlier answer: …`` to ``extra_context``. After 3-4 turns this exceeds the model's context, even with ``compact_messages_for_budget`` doing its job, because the COMPACTOR runs on ``messages`` (system + tool + user) not on ``extra_context`` (which is one big system note). **Fix candidate:** route follow-ups into a new ``messages`` slot (role=user, content=prior turn) that the compactor can fold, or summarise prior turns via ``client.ingest`` once they're more than 2 turns old.

### B-4. Compact-then-call still misses prompt growth from primed envelope

``_prime_corpus_envelope`` adds a system message of up to ``prime_budget_tokens`` (default 4000) at the start of every run. ``compact_messages_for_budget`` PINS all system messages, so this 4000-token primer is never compacted. On a 8k-context model that leaves only 4192 tokens for the entire conversation, including the system_prompt, user task, and tool round-trips. On long sessions this guarantees overflow. **Fix candidate:** treat the primed envelope as foldable (replace with a marker pointing at the per-tenant CKF) once primary context grows past a threshold, OR drop the primer after iteration 2 since the LLM has by then fetched the relevant clauses via ``query_regulation``.

### B-5. SSE clients lose ``done`` payload on slow networks

The ``done`` SSE frame carries the full ``AgentSessionState``. On networks where the SSE parser misses the trailing ``\n\n`` before the connection closes, the frontend silently drops the final state and the UI is stuck on "Thinking…". **Fix candidate:** the frontend already has a ``catch`` in ``onSubmit`` — add an ``await agentGet(session_id)`` in ``finally`` so the UI always reconciles, and add a "stream timed out — reconnect" path.

### B-6. ``_seen_chunk_ids`` resets every ``run()`` call

The dedup set is reset at the top of ``run``. So inside a single ``run`` the dedup works, but across resumes (clarify → run again, continue → run again) every chunk is re-presented from scratch. **Fix candidate:** persist ``seen_chunk_ids`` into the session record and re-hydrate on each ``run`` for the same ``session_id``.

---

## 5. Recommended Phase 4

In priority order:

1. **B-4 then B-3** — these are the two bugs that actively break long sessions on small models. High user impact.
2. **B-6** — cheap; fixes cross-iteration dedup that we just added.
3. **Pre-seed ``dispatch_stream_augmented``** (B-1) and surface ``mode=research`` toggle in the AgentChat UI (gate B-2).
4. **B-5** — defensive. Add the ``finally``-block reconcile.
5. **Wire ``boost_fact`` / ``penalize_fact``** as a 👍 / 👎 button on each citation in the final answer. Closes the SDK's RLHF surface.
6. **Adopt ``async_dispatch`` and ``async_dispatch_stream``** to drop the asyncio.Queue bridge in ``_stream_agent_run``. Pure cleanup but reduces a 30-line custom executor to ``async for`` over the SDK.
7. **Consider extending ``CRP_CONTEXT_TOOLS``** with our domain tools by sub-classing ``ContextToolExecutor`` so ``dispatch_with_tools`` becomes a real production path. This is the "true Phase 4" — it eliminates ``ComplianceAgent.run``'s tool loop entirely.

---

## 6. Production posture

* **Default agent path.** Legacy tool loop. Hardened in Phases 1-2. Keep.
* **Opt-in Phase 3 path.** Available for benchmarking and short-Q&A scenarios. Document with a warning that domain tools and clarifications are disabled.
* **Tests.** 455 / 459 pass, 4 skipped (unchanged from baseline). No new test was added for Phase 3 because the env-var path is exercised by integration only — followup PR should add a unit test that monkeypatches ``dispatch_via_crp`` and verifies the orchestrator short-circuits.

---

*Generated automatically as part of the Phase 3 commit. Update this
file alongside any future change that adds or removes a CRP boundary.*
