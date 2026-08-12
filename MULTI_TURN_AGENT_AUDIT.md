# CRP Comply — Multi-Turn Agent Architecture Audit

**Version:** Round 3 — Multi-turn interaction, regulatory research, and long-form reasoning reliability  
**Date:** 2026-06-21  
**Auditor:** Kimi Code CLI  
**Scope:** `src/crp_comply/agent/*`, `src/crp_comply/api/agent.py`, `services/crp-comply-search/`, `services/crp-comply-searxng/`, local-LLM worker path, and CRPv4 context/state primitives  
**Status:** Draft — companion to [`AGENTIC_AI_AUDIT.md`](AGENTIC_AI_AUDIT.md) (Round 1.1), [`LOCAL_AI_ENABLEMENT_AUDIT.md`](LOCAL_AI_ENABLEMENT_AUDIT.md) (Round 2), and [`CONVERSATIONAL_AI_AUDIT.md`](CONVERSATIONAL_AI_AUDIT.md) (Round 4)

---

## 1. Executive Summary

CRP Comply has two overlapping agent paths — a legacy per-turn ReAct loop (`ComplianceAgent.run()`) and a newer Phase-7 streaming loop (`loop_runtime.py`) — but neither is structured for long, multi-turn, regulation-cited research. The system can answer single-shot compliance questions and, with effort, produce short memos. It struggles to reliably execute the **research → analysis → synthesis → citation** cycle that complex deliverables (DPIAs, FRIAs, Annex IV technical documentation, cross-framework gap analyses) require.

The Round 3 audit finds that the biggest risks are not in any single component but in **how state moves across turns**:

1. **Per-step amnesia in Phase-7.** Each plan step spins a fresh `ComplianceAgent` with a new session id and a fresh `CrpMessageLedger`. Prior step observations are compressed to 240 characters, and the full evidence board is lost unless it happened to be relayed into the CKF.
2. **No explicit research phases.** The loop is generic ReAct: the LLM decides when to search, when to verify, and when to write. There is no planner that guarantees coverage of named frameworks, no analysis phase that reconciles conflicting sources, and no citation validator before the final answer is returned.
3. **CRPv4 context primitives remain unused for state.** `MultiHorizonContext`, `CognitiveStateObject`, `WindowDAG`, `ContinuationManager`, and `crp.envelope.construct` have zero references in the agent loop. Multi-turn memory is reconstructed from flat JSON message logs and heuristically scored history replay.
4. **Web research is architected but not operational.** SearXNG plugins that provide intent-aware routing and feedback-driven reranker are disabled. Agent-side feedback to the sidecar is either unwired or crashes on call. Web results are transient — they are not indexed, so the same source cannot be retrieved in a later turn.
5. **Local-LLM long turns are fragile.** Context-window math, tool-schema pruning, and continuation windows exist, but worker reconnects, lost `stream_end` frames, and silent streaming fallback can interrupt a long synthesis mid-turn. When that happens, the partially completed answer is not resumable because continuation state is not persisted across API calls.
6. **Citation quality is enforced by regex, not fact.** The Reflector counts uncited claim-like sentences but cannot verify that a cited `chunk_id` was actually returned by a tool. There is no final-answer citation validator, so hallucinated or mismatched citations can reach the user.
7. **Multi-turn flow is not designed as conversation.** There is no dialogue manager, no repair strategy, no incremental confirmation, and no explicit turn-taking policy beyond the LLM system prompt. These gaps are analysed from a conversational-AI perspective in [`CONVERSATIONAL_AI_AUDIT.md`](CONVERSATIONAL_AI_AUDIT.md).

A detailed analysis of the broader agentic-AI ecosystem is in [`AGENTIC_AI_AUDIT.md`](AGENTIC_AI_AUDIT.md); the local-LLM connection path is in [`LOCAL_AI_ENABLEMENT_AUDIT.md`](LOCAL_AI_ENABLEMENT_AUDIT.md). This report focuses on the multi-turn stack and closes the loop between those two earlier audits.

### Severity summary

| Severity | Count | Representative issues |
|----------|-------|----------------------|
| Critical | 3 | No explicit research/analysis/synthesis/citation phases; per-step amnesia in Phase-7; CRPv4 state primitives unused |
| High | 10 | No final citation validator; web feedback loops broken/disabled; continuation not resumable across API calls; plan revision is a counter not a replan; token budget not enforced in Phase-7; two loop implementations coexist; CRPv4 `ContinuationManager` / `envelope.construct` / `SafetyControlPlane` unused; aggressive folding loses clause text; ISO full text unavailable to LLM; local-worker long-turn fragility |
| Medium | 18 | Heuristic web triggers; no cross-source synthesis tool; CKF namespace collision for web hits; cache disabled by default in Phase-7; duplicate tool-call short-circuit forces premature finalization; reflector confidence path unused; clarification stores diverge; etc. |
| Low | 6 | Cosmetic docs, stale comments, naming inconsistencies |

---

## 2. Audit Scope & Methodology

### What was reviewed

- `src/crp_comply/agent/orchestrator.py` — legacy ReAct loop, message compaction, continuation, evidence priming
- `src/crp_comply/agent/loop_runtime.py`, `loop_state.py`, `loop_budget.py`, `reflector.py`, `clarifier.py`, `step_runner.py` — Phase-7 streaming loop
- `src/crp_comply/agent/crp_integration.py` — `CrpMessageLedger`, envelope packing, continuation stitching, feedback
- `src/crp_comply/agent/tools.py` — regulation, web, CKF, recipe, deterministic-classifier tools
- `src/crp_comply/agent/federated_fabric.py`, `ckf_corpus.py` — CKF layers
- `src/crp_comply/agent/copyright.py` — restricted-text surrogate handling
- `src/crp_comply/agent/web_client.py`, `src/crp_comply/sidecar_client.py` — sidecar client
- `src/crp_comply/api/agent.py` — session persistence, continue, clarify, finalize, feedback endpoints
- `services/crp-comply-search/` — search/research sidecar
- `services/crp-comply-searxng/` — SearXNG overlay with custom engines and plugins
- `src/crp_comply/agent/llm.py`, `worker_adapter.py`, `src/crp_comply/api/worker_registry.py`, `sdk/src/crp_comply_sdk/worker.py` — local-LLM long-turn behavior

### What it was compared against

- CRPv4 (`crprotocol` 4.0.0) context/state primitives: `MultiHorizonContext`, `CognitiveStateObject`, `WindowDAG`, `ContinuationManager`, `crp.envelope.construct`, `SafetyControlPlane`
- Round 1.1 findings in `AGENTIC_AI_AUDIT.md`
- Round 2 findings in `LOCAL_AI_ENABLEMENT_AUDIT.md`

### How evidence is cited

Findings cite file paths and, where meaningful, function names or line ranges from the source as it exists in the working tree.

---

## 3. Multi-Turn Architecture — As It Exists Today

```
User request
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  src/crp_comply/api/agent.py                                │
│  - JSON session file per (user, session_id)                 │
│  - Flat messages[] list                                     │
│  - _select_history_for_run() scores/trimmes history         │
│  - /clarify, /continue, /finalize, /feedback endpoints      │
└───────────────────────┬─────────────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  Phase-7 loop (loop_runtime.py)  —  opt-in via              │
│  POST /agent/loop/stream                                      │
│  1. triage                                                  │
│  2. cache lookup                                            │
│  3. heuristic planner (_plan_for) → 1-3 step Plan           │
│  4. For each step:                                          │
│       a. fresh ComplianceAgent (session_id:step_id)         │
│       b. run legacy ReAct loop (max 4 iters)                │
│       c. Reflector.evaluate()                               │
│       d. verdict ∈ {ok, retry, revise_plan, clarify, abort} │
│  5. _stitch_outputs() → loop.final                          │
└───────────────────────┬─────────────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  Legacy ComplianceAgent.run() (orchestrator.py)             │
│  1. PII redact / injection scan                             │
│  2. prime RAG + optional web evidence                       │
│  3. LOOP (max 8):                                           │
│       a. compact_messages_for_budget()                      │
│       b. ComplianceLLM.chat_with_tools()                    │
│       c. PolicyEnforcer.check()  ← custom PEP               │
│       d. execute tool → CrpMessageLedger.ingest             │
│  4. continue_truncated_answer()                             │
│  5. final answer                                            │
└─────────────────────────────────────────────────────────────┘
```

**The critical flaw:** continuity is reconstructed, not owned. Every turn rebuilds context from flat messages. The Phase-7 runtime delegates each step to a new agent instance, so the in-flight evidence board resets. CRPv4 primitives that were designed to hold persistent, structured, attributable state across turns are not used.

---

## 4. Findings by Theme

### 4.1 Multi-turn state & session persistence

#### MT1 — Phase-7 steps run inside isolated agent instances (Critical)

- **Location:** `src/crp_comply/agent/loop_runtime.py::_execute_step()` lines 468–569
- **Current behavior:** The runtime calls `agent_builder(user_id=..., max_iters=...)` once per step, passing `session_id=f"{cfg.session_id}:{step.id}"`. Each step therefore gets a fresh `ComplianceAgent`, a fresh `CrpMessageLedger`, and a fresh `WarmStateStore`.
- **Impact:** Cross-step state relies on `_format_step_task()` compressing prior observations to ~240 characters each. Full tool results, chunk IDs, contradiction verdicts, and confidence scores from earlier steps are not automatically available. A multi-step research task cannot reason over the complete evidence it gathered two steps ago unless the data was relayed into the CKF and then recalled.
- **CRPv4 equivalent:** `crp.Client.session` / `client.warm_store` / `client.dag`
- **Recommended fix:** Maintain one `crp.Client` per user session. Pass the same client/session into every step so that `warm_store`, `dag`, and `multi_horizon` context accumulate across steps.

#### MT2 — Legacy per-turn state is a flat message log, not structured memory (High)

- **Location:** `src/crp_comply/api/agent.py` session JSON; `_select_history_for_run()` lines 552–613
- **Current behavior:** Sessions are stored as JSON files containing a flat `messages: [{role, content, ts}]` list. On `/continue`, the API scores messages by recency/keyword overlap and replays up to 12 messages / 12,000 characters.
- **Impact:** Tool results are replayed as raw text, not as structured facts. Citation metadata, contradiction status, and source provenance are lost or diluted. The LLM sees conversation history but not an evidence board.
- **CRPv4 equivalent:** `CognitiveStateObject` + `WindowDAG`
- **Recommended fix:** Keep a structured session state object (claims, supporting chunks, contradictions, open gaps) outside the message list. Replay only what the model needs as narrative, while preserving the full evidence board for verification.

#### MT3 — Two clarification suspension mechanisms coexist (Medium)

- **Location:** `src/crp_comply/agent/orchestrator.py` (legacy `ClarificationNeeded`) and `src/crp_comply/agent/clarifier.py` / `loop_runtime.py` (`AskUserSuspended` + sqlite `awaiting_user.db`)
- **Current behavior:** The legacy path stores pending questions in the session JSON. The Phase-7 path stores them in a separate sqlite database with a resume token.
- **Impact:** UI and API consumers may see inconsistent state depending on which path produced the clarification. Resume logic is duplicated and could drift.
- **Recommended fix:** Consolidate on the Phase-7 `ClarifierStore` and expose a single resume endpoint. Remove the legacy in-session clarification state.

#### MT4 — Token budget is declared but not enforced in Phase-7 (High)

- **Location:** `src/crp_comply/agent/loop_budget.py` exposes `LoopBudgetMeter.record_tokens()`; `src/crp_comply/agent/loop_runtime.py` never calls it
- **Current behavior:** The runtime records steps, wall-clock, clarifiers, and plan revisions, but not prompt/completion tokens.
- **Impact:** Long multi-turn research can exceed the intended token budget without triggering `loop.abort`. This is especially dangerous with local LLMs where context windows are small and costs are operator-owned.
- **Recommended fix:** Plumb token counts from `ComplianceLLM` / `WorkerAdapter` back into `LoopBudgetMeter.record_tokens()` and emit `loop.budget_warning` before abort.

---

### 4.2 Research → analysis → synthesis → citation

#### MT5 — No explicit research phases; the loop is generic ReAct (Critical)

- **Location:** `src/crp_comply/agent/orchestrator.py::ComplianceAgent.run()`; `src/crp_comply/agent/loop_runtime.py::_plan_for()`
- **Current behavior:** The system prompt instructs the LLM to call `query_regulation`, then optionally broaden with CKF/web tools, and finally write an answer. The Phase-7 planner emits 1–3 steps with coarse `tool_hint`s (`rag_search`, `web_search`, `run_recipe`). There is no coverage guarantee for named frameworks, no analysis phase that reconciles sources, and no citation validator.
- **Impact:** Complex tasks depend on the LLM self-coordinating. Small or distracted models may stop after one query, miss cross-framework obligations, or synthesize before verifying.
- **CRPv4 equivalent:** `crp.stl` (Semantic Task Layer) RETRIEVE/ANALYSE/SYNTHESISE/VERIFY/REPORT
- **Recommended fix:** Introduce explicit loop phases (RESEARCH, ANALYZE, SYNTHESIZE, CITE) with phase-aware planner output. Gate phase transitions on coverage criteria (e.g. every claim supported or flagged as gap).

#### MT6 — Plan revision is a counter, not a true replan (High)

- **Location:** `src/crp_comply/agent/loop_runtime.py` lines 343–365; `src/crp_comply/agent/reflector.py::_retry_or_abort()` lines 220–255
- **Current behavior:** When the Reflector returns `revise_plan`, the runtime increments `plan_revisions` and simply advances to the next step. It does not regenerate the plan from the current evidence board.
- **Impact:** A bad initial plan cannot be corrected. The runtime will march through under-specified steps and produce a weak final answer.
- **Recommended fix:** Use an LLM-driven replanner that takes the current `EvidenceBoard`, uncovered claims, and contradictions as input and emits a revised plan. Bound revisions by budget, but make them substantive.

#### MT7 — No final-answer citation validator (High)

- **Location:** `src/crp_comply/agent/orchestrator.py`; `src/crp_comply/agent/reflector.py`
- **Current behavior:** The Reflector checks step observations for uncited claim-like sentences. There is no equivalent check for the final answer emitted to the user. `run_recipe` refuses to persist a deliverable with zero citations, but free-form answers are not validated.
- **Impact:** Hallucinated `[chunk_id]` markers or citations to chunks that were never retrieved can reach the user. This is more likely on small local models that follow the citation format imperfectly.
- **Recommended fix:** Add a `validate_citations(final_text, evidence_board)` step before returning. Verify that each `[chunk_id]`/`[fact_id]`/`[web:...]` reference exists in the board. Flag uncited claims and loop back to RESEARCH if validation fails.

#### MT8 — Duplicate tool-call short-circuit can force premature finalization (Medium)

- **Location:** `src/crp_comply/agent/orchestrator.py` duplicate-call handling
- **Current behavior:** Identical `(tool, args)` calls are cached; on the third duplicate a hard user message is injected telling the agent to write the final answer now.
- **Impact:** If the model is looping because it genuinely lacks evidence (e.g. corpus returns zero hits), it is forced to finalize with a weak or hallucinated answer.
- **Recommended fix:** Distinguish “duplicate due to stubbornness” from “duplicate due to insufficient evidence.” If the same tool returns empty results repeatedly, transition to web search or ask the user rather than forcing finalization.

---

### 4.3 Regulatory grounding & corpus

#### MT9 — Corpus coverage is broad but static and may miss mid-week updates (Medium)

- **Location:** `corpus/`; `src/crp_comply/agent/live_regulation.py`; CI scraping schedule
- **Current behavior:** EU AI Act, GDPR, NIS2, ISO 42001/22989/23894, NIST AI RMF, OECD, Council of Europe, and UK AI White Paper are present. The corpus is rebuilt by CI; `live_regulation.py` diffs manifests but does not auto-update the production index.
- **Impact:** Users asking about very recent guidance may get stale or missing results unless the web sidecar is triggered.
- **Recommended fix:** Either auto-promote live diffs to the production index with operator approval, or prominently mark the corpus date in answers and widen web-priming triggers.

#### MT10 — ISO full text is surrogate-only in the LLM context (High)

- **Location:** `src/crp_comply/agent/copyright.py` lines 147–196
- **Current behavior:** For ISO/IEC and other restricted standards, the tool returns a surrogate preserving clause ID, title, and word count but not the body text.
- **Impact:** The model cannot quote or deeply reason over ISO clauses. It can cite clause IDs but must rely on training-data knowledge for the substance, which undermines the “never cite from memory” design goal for ISO-heavy deliverables.
- **Recommended fix:** License official ISO texts for runtime use, or integrate a clause-by-clause licensed summary layer. In the short term, flag ISO-derived claims as “(summary only — consult official text).”

#### MT11 — No cross-source synthesis / conflict-resolution tool (High)

- **Location:** `src/crp_comply/agent/crp_integration.py::detect_hit_contradictions()`; `src/crp_comply/agent/tools.py`
- **Current behavior:** Contradictions between RAG hits are detected and reported to the LLM, but there is no tool that explicitly reconciles corpus clauses with web guidance or flags supersession. The LLM must manually resolve conflicts.
- **Impact:** Answers may miss later-in-time guidance that supersedes the committed corpus, or may present conflicting obligations without resolution.
- **Recommended fix:** Add a `compare_sources(corpus_hits, web_hits)` analysis step that uses effective_date / superseded_by metadata and temporal reasoning to recommend which source governs.

#### MT12 — Aggressive folding loses clause text needed for precise citation (Medium)

- **Location:** `src/crp_comply/agent/crp_integration.py::compact_messages_for_budget()`; `fold_messages_with_ledger()`
- **Current behavior:** Older tool results and primers are folded to one-line markers to save tokens. The evidence ledger packs facts but truncates each to 600 characters.
- **Impact:** When the model needs to cite a precise article subsection, the exact text may have been folded away, forcing it to re-query or paraphrase from memory.
- **Recommended fix:** Pin full text for chunks that are referenced by pending claims. Fold only redundant commentary and older assistant prose.

---

### 4.4 Web search & sidecars

#### MT13 — Web research feedback loops are broken or disabled (High)

- **Location:** `services/crp-comply-searxng/settings.yml` lines 75–85; `src/crp_comply/agent/orchestrator.py` `_collect_web_feedback` / `_flush_web_feedback`; `src/crp_comply/agent/loop_runtime.py` lines 999–1070
- **Current behavior:** The SearXNG CRP Query Router and Learning Reranker plugins are commented out in the shipped config. `_build_agent()` never passes `web_feedback_client` to `ComplianceAgent`, so orchestrator feedback is never flushed. The loop-runtime feedback call passes `url=` to a method that does not accept it, raising `TypeError`.
- **Impact:** The learning reranker cannot improve result quality. The sidecar cannot learn which engines/intents produce useful citations.
- **Recommended fix:** Enable the plugins in `settings.yml` (or remove them and the dead code). Wire `web_feedback_client` correctly. Fix the feedback call signature and include engine provenance in `SearchHit`.

#### MT14 — Web results are transient and not indexed for later turns (Medium)

- **Location:** `src/crp_comply/agent/orchestrator.py::_prime_task_evidence()`; `src/crp_comply/agent/web_client.py`
- **Current behavior:** Fetched web pages exist only as tool results in the current turn. They are not added to the RAG index, so later turns cannot `query_regulation` over them.
- **Impact:** The same live source must be re-fetched if a follow-up question needs it, increasing latency and rate-limit risk.
- **Recommended fix:** Maintain a transient `web_corpus` index (or CKF layer) for fetched pages, keyed by URL hash and freshness, so later turns can retrieve them via the same RAG interface.

#### MT15 — Web triggering is freshness-gated only (Medium)

- **Location:** `src/crp_comply/agent/loop_runtime.py::needs_fresh_web()` lines 678–681; `src/crp_comply/agent/orchestrator.py::_task_needs_fresh_web()`
- **Current behavior:** Web priming/planner only steers toward web search when the task contains hard-coded freshness markers (`latest`, `2026`, `enforcement action`, etc.).
- **Impact:** Questions that need current public context but lack those keywords may skip web search and rely on a potentially stale corpus.
- **Recommended fix:** Run a low-budget web priming pass for all free-form research tasks, or expand the trigger set to include applicability/scoping questions where regulator guidance has likely evolved.

#### MT16 — Premium search backends are stubs (Medium)

- **Location:** `services/crp-comply-search/src/crp_comply_search/backends.py` lines 574–640
- **Current behavior:** `BraveBackend` and `TavilyBackend` raise `NotImplementedError` even when enabled.
- **Impact:** Production relies on DuckDuckGo or operator-hosted SearXNG, both of which have reliability/rate-limit constraints.
- **Recommended fix:** Implement the backends or remove the stub code and docs that imply availability.

---

### 4.5 Local-LLM long-turn reliability

#### MT17 — Local-worker context overflow and continuation are not resumable (High)

- **Location:** `src/crp_comply/agent/llm.py`; `src/crp_comply/agent/worker_adapter.py`; `src/crp_comply/agent/crp_integration.py::continue_truncated_answer()`
- **Current behavior:** The system scales context-window reserve, prunes tool schemas, and compacts messages for small local models. Continuation supports up to 4 windows / 40,000 characters. If the worker disconnects or a `stream_end` frame is lost mid-continuation, the partially completed answer is not persisted.
- **Impact:** Long deliverables on local LLMs can fail partway through, and the user must restart from the original prompt rather than continuing from the last completed window.
- **Cross-reference:** See [`LOCAL_AI_ENABLEMENT_AUDIT.md`](LOCAL_AI_ENABLEMENT_AUDIT.md) W2, R1, R5 for root causes.
- **Recommended fix:** Persist continuation state (completed windows + pending claims) in the session after each window. Resume from the last completed window on worker reconnect.

#### MT18 — Small-context models lose deterministic compliance tools (High)

- **Location:** `src/crp_comply/agent/orchestrator.py::_fit_schemas_to_window()`
- **Current behavior:** When the available context is small (~4k–8k), Tier-2/3 tools are dropped or thinned. This can remove `classify_ai_act_risk`, `check_dpia_required`, `estimate_fine_exposure`, and scoped lookup tools.
- **Impact:** A 4k local model answering an AI Act applicability question may lose the deterministic classifier and be forced to rely solely on RAG retrieval.
- **Recommended fix:** Use hierarchical tool selection (first pick domain, then pick tool) so the full schema list is never loaded at once. Always preserve the deterministic compliance tools as Tier-0.

#### MT19 — Worker streaming fallback hides real failures (Medium)

- **Location:** `src/crp_comply/agent/worker_adapter.py::generate_chat_with_tools_streaming()`
- **Current behavior:** On any `RuntimeError`, the adapter silently falls back from streaming to a blocking call.
- **Impact:** A worker that is struggling but still connected will cause long blocking waits instead of surfacing the error. This is especially painful during multi-turn research where streaming progress events are expected.
- **Cross-reference:** [`LOCAL_AI_ENABLEMENT_AUDIT.md`](LOCAL_AI_ENABLEMENT_AUDIT.md) R5.
- **Recommended fix:** Only fall back for protocol-level errors, not worker-unreachable or context-overflow errors. Surface structured error codes to the UI.

#### MT20 — Reflector confidence path is wired but never fires (Medium)

- **Location:** `src/crp_comply/agent/reflector.py` lines 199–213; `src/crp_comply/agent/loop_runtime.py` never passes `confidence`
- **Current behavior:** The Reflector will emit `clarify_first` if `confidence < 0.6`, but the runtime never passes a confidence value.
- **Impact:** A valuable automatic clarification trigger is dormant.
- **Recommended fix:** Have `ComplianceLLM` / providers expose a per-turn confidence signal (or derive it from logprobs/response metadata) and pass it to `Reflector.evaluate()`.

---

### 4.6 CRPv4 integration for multi-turn state

#### MT21 — Legacy loop bypasses `crp.Client` entirely (Critical)

- **Location:** `src/crp_comply/agent/llm.py::ComplianceLLM.chat_with_tools()`; `src/crp_comply/agent/orchestrator.py::ComplianceAgent.run()`
- **Current behavior:** `ComplianceLLM` calls the raw `crp.providers` adapter directly. The orchestrator manually builds messages, compacts context, parses tool calls, and stitches continuations.
- **Impact:** CRPv4 session, ledger, DAG, safety, and continuation primitives cannot observe or manage the call.
- **Cross-reference:** [`AGENTIC_AI_AUDIT.md`](AGENTIC_AI_AUDIT.md) F1.1, F1.2.
- **Recommended fix:** Route the legacy loop through `crp.Client.dispatch_with_tools()` / `dispatch_agentic()`. Keep the custom loop behind a feature flag during migration.

#### MT22 — Native CRP dispatch path discards session state (High)

- **Location:** `src/crp_comply/agent/crp_integration.py::dispatch_via_crp()` lines 1763–1909; `src/crp_comply/agent/orchestrator.py::_run_via_crp_dispatch()`
- **Current behavior:** The optional CRP-native path creates a fresh `crp.Client` per call, dispatches, and closes it. `client.session`, `client.warm_store`, and `client.dag` are discarded.
- **Impact:** Even the “CRP-native” path does not retain multi-turn state.
- **Recommended fix:** Create one `crp.Client` per session and reuse it across calls. Persist the client’s session/export state in the session record.

#### MT23 — `ContinuationManager`, `MultiHorizonContext`, `CognitiveStateObject`, `WindowDAG` unused (High)

- **Location:** Confirmed zero references in `src/crp_comply`
- **Current behavior:** Continuation uses only `crp.continuation.stitch.stitch_many`. Context compaction is hand-rolled. State is flat messages.
- **Impact:** Long-form reports lack regrounding between windows, structured invalidation, and decision lineage.
- **Cross-reference:** [`AGENTIC_AI_AUDIT.md`](AGENTIC_AI_AUDIT.md) §4.2.
- **Recommended fix:** Adopt `ContinuationManager` for long deliverables; use `MultiHorizonContext` + `CognitiveStateObject` + `WindowDAG` for session state.

#### MT24 — `SafetyControlPlane` not used in the agent loop (High)

- **Location:** `src/crp_comply/agent/mcp_permissions.py` custom `PolicyEnforcer`; `src/crp_comply/api/safety.py`
- **Current behavior:** The agent loop uses a custom policy enforcer. `SafetyControlPlane` is referenced only in gateway/org dashboard and checkpoint inbox code.
- **Impact:** Safety policy, checkpoints, and capability registry are siloed from the loop. High-risk classifier verdicts do not feed back into safety coverage.
- **Cross-reference:** [`AGENTIC_AI_AUDIT.md`](AGENTIC_AI_AUDIT.md) F4.1, F4.2.
- **Recommended fix:** Replace `PolicyEnforcer` with `SafetyControlPlane`. Map existing policies to capabilities / `CustomSafetyRule` and emit real `Checkpoint` objects.

---

## 5. Research → Analysis → Synthesis → Citation Gap Analysis

| Phase | What exists | What is missing | Risk |
|-------|-------------|-----------------|------|
| **Research** | `query_regulation`, `query_regulation_packed`, `crp_retrieve_context`, `web_search`, `web_research` | No coverage planner; no guarantee that named frameworks are searched; no query history dedup | Gaps in regulatory coverage; repeated queries waste budget |
| **Analysis** | `detect_hit_contradictions`, `crp_check_facts` | No cross-source reconciliation tool; no temporal supersession logic; no structured evidence board | Conflicts unresolved; stale guidance may be preferred |
| **Synthesis** | LLM writes final answer with system-prompt citation rules | No pinned citation index; no preservation of full clause text across compaction | Citations may be weak or missing; exact quotes lost |
| **Citation** | Reflector regex check on step observations; `run_recipe` zero-citation guard | No final-answer validator; no verification that cited IDs exist in retrieved results | Hallucinated/mismatched citations reach users |

The system prompt is the only guarantee that the model will execute all four phases. Prompts are necessary but not sufficient for high-stakes compliance output.

---

## 6. Severity-Prioritised Findings Register

| ID | Finding | Severity | Effort | Owner |
|----|---------|----------|--------|-------|
| MT1 | Phase-7 steps run inside isolated agent instances | Critical | High | Agent runtime |
| MT5 | No explicit research/analysis/synthesis/citation phases | Critical | High | Agent runtime / Planner |
| MT21 | Legacy loop bypasses `crp.Client` entirely | Critical | High | Agent LLM layer |
| MT2 | Legacy per-turn state is flat message log | High | High | API / Agent state |
| MT6 | Plan revision is a counter, not a replan | High | Medium | Loop runtime |
| MT7 | No final-answer citation validator | High | Medium | Agent output |
| MT10 | ISO full text surrogate-only in LLM context | High | Medium/Legal | Corpus / Legal |
| MT11 | No cross-source synthesis / conflict resolution | High | Medium | Research tools |
| MT13 | Web research feedback loops broken/disabled | High | Low/Medium | Sidecars / Agent |
| MT17 | Local-worker long-turn continuation not resumable | High | Medium | Worker / API |
| MT18 | Small-context models lose deterministic tools | High | Medium | Tool registry |
| MT22 | Native CRP dispatch discards session state | High | High | CRP integration |
| MT23 | `ContinuationManager` / `MultiHorizonContext` / `WindowDAG` unused | High | High | CRP integration |
| MT24 | `SafetyControlPlane` not used in agent loop | High | High | Safety layer |
| MT3 | Two clarification mechanisms coexist | Medium | Medium | API / Clarifier |
| MT4 | Token budget not enforced in Phase-7 | Medium | Low | Loop runtime |
| MT8 | Duplicate-call short-circuit forces premature finalization | Medium | Low | Orchestrator |
| MT9 | Corpus static; may miss mid-week updates | Medium | Medium | Ingest pipeline |
| MT12 | Aggressive folding loses clause text | Medium | Medium | Compaction |
| MT14 | Web results transient, not indexed | Medium | Medium | Sidecars / CKF |
| MT15 | Web triggering freshness-gated only | Medium | Low | Planner / Orchestrator |
| MT16 | Premium search backends are stubs | Medium | Medium | Search sidecar |
| MT19 | Worker streaming fallback hides failures | Medium | Low | Worker adapter |
| MT20 | Reflector confidence path never fires | Medium | Low | Reflector / LLM |

---

## 7. Recommendations

### Short term (1–2 weeks)

1. **Persist continuation state across API calls.** After each continuation window, write completed windows and pending claims to the session record so a worker reconnect or `/continue` can resume rather than restart.
2. **Fix web feedback wiring.** Either enable the SearXNG CRP plugins and wire `web_feedback_client` correctly, or remove the dead code paths so the architecture does not mislead maintainers.
3. **Add a final-answer citation validator.** Before returning `loop.final`, verify that every `[chunk_id]` / `[fact_id]` / `[web:...]` reference in the answer exists in the step evidence board. If not, transition back to research.
4. **Enforce token budget in Phase-7.** Plumb token counts from `ComplianceLLM` / `WorkerAdapter` into `LoopBudgetMeter.record_tokens()`.
5. **Make deterministic compliance tools Tier-0.** Ensure `classify_ai_act_risk`, `check_dpia_required`, `check_high_risk_criteria`, etc. are never dropped by `_fit_schemas_to_window()`.
6. **Fire the Reflector confidence path.** Pass a confidence signal from the LLM/provider layer to `Reflector.evaluate()`.
7. **Consolidate clarification storage.** Drop the legacy session-JSON clarification state and use `ClarifierStore` for all suspensions.

### Medium term (1–2 months)

8. **Introduce explicit loop phases and an `EvidenceBoard`.** Add RESEARCH → ANALYZE → SYNTHESIZE → CITE phases. Maintain a structured claim/chunk/contradiction board across steps that compaction cannot destroy.
9. **Implement a coverage-driven planner.** For complex tasks, the planner should emit sub-questions, assign framework/source filters, and guarantee that EU AI Act, GDPR, NIS2, ISO 42001, and NIST are covered where relevant.
10. **Add cross-source reconciliation.** Build a `compare_sources` analysis step that uses effective_date/superseded_by metadata and temporal reasoning to resolve conflicts between corpus and web sources.
11. **Index fetched web pages into a transient corpus.** Store full-text web pages in a `web_corpus` index so later turns can retrieve them via `query_regulation`.
12. **Implement true LLM-driven replanning.** When `revise_plan` fires, regenerate the plan from the current evidence board, not just advance the cursor.
13. **Wire `SafetyControlPlane` into the agent loop.** Replace `PolicyEnforcer` with CRP safety capabilities and emit real checkpoints for high-risk/unacceptable risk classifications.
14. **Improve local-LLM error surfacing.** Stop silent streaming fallback; return structured error codes (worker offline, context overflow, upstream unreachable) to the UI.

### Long term (2–3 months)

15. **Migrate the agent loop to `crp.Client`.** Create one `crp.Client` per session; route LLM calls, context packing, continuation, and safety through it. Use `dispatch_agentic` for complex tasks and `dispatch_with_tools` for simpler ones.
16. **Adopt CRPv4 state primitives.** Use `MultiHorizonContext` for persistent/conversational/ephemeral tiers, `CognitiveStateObject` for decisions and dependencies, `WindowDAG` for fact lineage, and `ContinuationManager` for long-form reports.
17. **Replace regex citation checks with structured provenance.** Use `WindowDAG` lineage and, when available, `DecisionProvenanceEngine` to validate that every claim is grounded in retrieved facts.
18. **License or build a clause-level ISO reasoning layer.** Until official texts are available at runtime, ISO-derived answers should be clearly marked as summary-only.
19. **Add Redis-backed worker registry and session state** for multi-replica SaaS deployments, so worker attachment and continuation state survive backend restarts.

---

## 8. Cross-References

- [`AGENTIC_AI_AUDIT.md`](AGENTIC_AI_AUDIT.md) — Round 1.1: agentic-AI ecosystem flaws, CRPv4 capability inventory, custom ReAct loop, custom PEP, SDK drift.
- [`LOCAL_AI_ENABLEMENT_AUDIT.md`](LOCAL_AI_ENABLEMENT_AUDIT.md) — Round 2: SDK worker/backend reliability, “connection works, no response,” BYOK modes, documentation drift.

These three reports form a single staged narrative:
- Round 1.1 asked “Is the agentic layer CRP-native and safe?”
- Round 2 asked “Can local LLMs actually connect and return answers?”
- Round 3 asks “Can the agent sustain long, regulation-cited, multi-turn reasoning on those connections?”

---

## 9. Appendices

### Appendix A — Files referenced

- `src/crp_comply/agent/orchestrator.py`
- `src/crp_comply/agent/loop_runtime.py`
- `src/crp_comply/agent/loop_state.py`
- `src/crp_comply/agent/loop_budget.py`
- `src/crp_comply/agent/reflector.py`
- `src/crp_comply/agent/clarifier.py`
- `src/crp_comply/agent/step_runner.py`
- `src/crp_comply/agent/crp_integration.py`
- `src/crp_comply/agent/tools.py`
- `src/crp_comply/agent/federated_fabric.py`
- `src/crp_comply/agent/ckf_corpus.py`
- `src/crp_comply/agent/copyright.py`
- `src/crp_comply/agent/web_client.py`
- `src/crp_comply/agent/sidecar_client.py`
- `src/crp_comply/agent/llm.py`
- `src/crp_comply/agent/worker_adapter.py`
- `src/crp_comply/api/agent.py`
- `src/crp_comply/api/worker_registry.py`
- `services/crp-comply-search/src/crp_comply_search/app.py`
- `services/crp-comply-search/src/crp_comply_search/backends.py`
- `services/crp-comply-search/src/crp_comply_search/profiles.py`
- `services/crp-comply-searxng/settings.yml`
- `services/crp-comply-searxng/plugins/query_router.py`
- `services/crp-comply-searxng/plugins/learning_reranker.py`
- `sdk/src/crp_comply_sdk/worker.py`

### Appendix B — Related skills

- `crp-v4-protocol-reference`
- `crp-v4-agentic-ecosystem`
- `crp-v4-ai-safety`
- `crp-v4-context-management`
- `crp-v4-capability-map`
- `crp-comply-codebase`
