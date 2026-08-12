# CRP Comply — Agentic AI Ecosystem Audit

**Version:** Round 1.1 — Agentic AI flaws + Local AI integration gaps  
**Date:** 2026-06-21  
**Auditor:** Kimi Code CLI  
**Scope:** `src/crp_comply/agent/*`, `src/crp_comply/proxy/*`, `src/crp_comply/api/agent.py`, `src/crp_comply/core.py`, local-worker/WebSocket relay, SDK worker, and their use of `crprotocol` (CRPv4)  
**Status:** Draft — Round 2 (Local AI enablement), Round 3 (Multi-turn agent architecture), and Round 4 (Conversational AI enablement) now incorporated. See [`LOCAL_AI_ENABLEMENT_AUDIT.md`](LOCAL_AI_ENABLEMENT_AUDIT.md), [`MULTI_TURN_AGENT_AUDIT.md`](MULTI_TURN_AGENT_AUDIT.md), and [`CONVERSATIONAL_AI_AUDIT.md`](CONVERSATIONAL_AI_AUDIT.md).

---

## 1. Executive Summary

CRP Comply markets itself as a protocol-level AI governance platform, yet its **agentic AI layer is largely a bespoke ReAct loop that re-implements capabilities CRPv4 already provides**. The product is "CRP-aware" but not "CRP-native." This creates architectural fragmentation, duplicated context-window logic, fragile provenance, and a **local-AI integration that is unreliable: the WebSocket worker connects, but responses are lost or hang due to request/response lifecycle bugs in the backend and SDK worker.**

A detailed analysis of the local-AI path is available in [`LOCAL_AI_ENABLEMENT_AUDIT.md`](LOCAL_AI_ENABLEMENT_AUDIT.md). The multi-turn interaction / long-form reasoning analysis is in [`MULTI_TURN_AGENT_AUDIT.md`](MULTI_TURN_AGENT_AUDIT.md).

### Top-level conclusions

1. **The agent loop bypasses CRP dispatch.** `ComplianceAgent.run()` manually builds messages, primes RAG, compacts context, calls `ComplianceLLM.chat_with_tools()`, parses tool calls, and stitches continuations. It should be delegating to `crp.Client.dispatch_with_tools()` or `crp.Client.dispatch_agentic()`.
2. **CRPv4 context-management primitives are almost unused.** `MultiHorizonContext`, `CognitiveStateObject`, `WindowDAG`, `ContinuationManager`, `crp.envelope.construct`, CDR/CDGR, and the 5-primitive storage engine are not referenced in the agent code.
3. **AI safety is home-grown and disconnected from CRP.** `mcp_permissions.PolicyEnforcer` implements a custom Policy Enforcement Point instead of using `crp.security.control_plane.SafetyControlPlane`. Checkpoints, safety budgets, and policy grammar are not wired into the agent loop.
4. **Provenance relies on LLM honesty.** Citations are regex-parsed `[chunk_id]` markers; the 13-stage DPE is not run on agent outputs.
5. **Local AI workers misuse the protocol.** `WorkerAdapter` forwards calls through a custom WebSocket relay rather than registering as a `crp.providers` adapter or routing through `crp.Client`. Worse, the backend dispatches to workers whose upstream LLM is not reachable, streaming `stream_end` frames can be lost, and the streaming queue drops chunks silently.
6. **SDK drift is silently tolerated.** The code imports `crp.provenance` and `crp.policy`, which do not exist in `crprotocol==4.0.0`; the proxy disables provenance silently when the import fails.
7. **The local-AI UX is broken by documentation drift.** Users are told to run non-existent CLI commands, install the SDK without the `[worker]` extra, and set env vars the code ignores.
8. **Multi-turn state is reconstructed, not owned.** The Phase-7 loop spins a fresh `ComplianceAgent` per step, so each step starts with a fresh ledger. Legacy `/continue` replays flat message history. CRPv4 `MultiHorizonContext`, `CognitiveStateObject`, `WindowDAG`, and `ContinuationManager` are still unused, leaving long-form reports without structured state or regrounding.
9. **Research → analysis → synthesis → citation is not enforced.** The loop relies on the system prompt to coordinate broad retrieval, verification, and answer generation. There is no explicit phase machine, no coverage planner, and no final-answer citation validator, so complex deliverables can stop early or cite hallucinated chunk IDs.
10. **Conversational AI is not a first-class concern.** There is no dialogue manager, no structured NLU/entity/slot layer, no repair or incremental confirmation strategy, and no persona/tone policy. The chat UI wraps a task loop; it does not own dialogue state. See the capstone analysis in [`CONVERSATIONAL_AI_AUDIT.md`](CONVERSATIONAL_AI_AUDIT.md).

### Severity summary

| Severity | Count | Examples |
|----------|-------|----------|
| Critical | 3 | SDK module drift silently disables provenance; agent loop bypasses CRP dispatch; backend dispatches to unreachable local LLM |
| High | 9 | Custom PEP vs SafetyControlPlane; no structured session state; fragmented audit; fragile citations; local worker bypass; streaming hangs on lost `stream_end`; cross-user request cancellation; silent streaming fallback; queue drops chunks; test/diagnose broken for local_worker |
| Medium | 22 | Manual compaction, manual continuation, custom MMR, feedback not using SDK, reconnect storm, parameter dropping, Ollama path bugs, etc. |
| Low | 8 | Continue/resume history trimming, wall-clock vs monotonic time, etc. |

---

## 2. Audit Scope & Methodology

### What was reviewed

- `src/crp_comply/agent/orchestrator.py` — main agent loop
- `src/crp_comply/agent/crp_integration.py` — CRP bridge layer
- `src/crp_comply/agent/tools.py` — tool registry and CRP context tools
- `src/crp_comply/agent/llm.py` — `ComplianceLLM` and provider adapters
- `src/crp_comply/agent/loop_runtime.py`, `loop_state.py`, `loop_budget.py`, `step_runner.py`, `reflector.py`, `clarifier.py`, `triage.py` — Phase-7 loop runtime
- `src/crp_comply/agent/mcp_permissions.py` — custom PEP
- `src/crp_comply/agent/worker_adapter.py` — local worker integration
- `src/crp_comply/proxy/interceptor.py` — proxy safety layer
- `src/crp_comply/api/agent.py` — agent API endpoints
- `src/crp_comply/core.py` — product-level deliverables

### What it was compared against

CRPv4 (`crprotocol` 4.0.0) capabilities:
- `crp.Client` dispatch strategies: `dispatch`, `dispatch_with_tools`, `dispatch_agentic`, `dispatch_hierarchical`, `dispatch_progressive`, `dispatch_reflexive`, `dispatch_stream_augmented`
- Context envelope: `crp.envelope.construct`, `EnvelopeState`, `TaskIntent`
- Contextual Knowledge Fabric: `crp.ckf.ContextualKnowledgeFabric`
- Continuation: `crp.continuation.ContinuationManager`
- State/memory: `crp.state.MultiHorizonContext`, `crp.state.WarmStateStore`, `crp.state.CognitiveStateObject`
- Safety: `crp.security.control_plane.SafetyControlPlane`, `crp.security.checkpoint.Checkpoint`, `crp.security.safety_manifest.SafetyManifest`
- Policy: `crp.policy.SafetyPolicy`, `crp.policy.parse_policy`
- Provenance: `crp.provenance` (claimed but absent in 4.0.0)
- Providers: `crp.providers.LLMProvider`, `OpenAIAdapter`, `AnthropicAdapter`, etc.
- Headers/audit: `crp.headers`, `crp.security.ComplianceAuditTrail`

### How evidence is cited

Findings cite file paths and, where meaningful, function names or line-number ranges from the source as it exists in the working tree.

---

## 3. CRPv4 Capability Inventory — What Could Be Used

| Capability | CRPv4 Module | What It Would Give CRP Comply |
|------------|--------------|-------------------------------|
| Universal LLM entry | `crp.Client.dispatch*()` | Automatic envelope, continuation, DPE, audit, provider routing |
| Tool-mediated relay | `crp.Client.dispatch_with_tools()` | Native tool loop, pull-mode context, structured provenance |
| Agentic dispatch | `crp.Client.dispatch_agentic()` | Planning, reflection, safety budget, checkpoints |
| Context envelope | `crp.envelope.construct()` | Optimal fact selection within token budget |
| CDR | `crp.envelope.cdr` | Prevents stale repetition across windows |
| CDGR | `crp.ckf.graph_walk()` | Multi-hop connector facts |
| CKF | `crp.ckf.ContextualKnowledgeFabric` | Long-term structured memory per tenant |
| Continuation | `crp.continuation.ContinuationManager` | Long-form reports without truncation |
| Warm state | `crp.state.WarmStateStore` | Event-sourced facts, fast resume |
| Multi-horizon context | `crp.state.MultiHorizonContext` | Persistent / conversational / ephemeral tiers |
| Scratch buffer | `crp.state.ScratchBuffer` | Tool outputs as pointers, not raw JSON |
| Cognitive State Object | `crp.state.CognitiveStateObject` | Decisions, dependencies, invalidation |
| Semantic Task Layer | `crp.stl` | RETRIEVE/ANALYSE/SYNTHESISE/VERIFY/REPORT operations |
| Safety Control Plane | `crp.security.control_plane.SafetyControlPlane` | Unified safety registry + manifest |
| Safety policy grammar | `crp.policy` | CSP-style directives (`halt-on`, `require-grounding`) |
| Checkpoints | `crp.security.checkpoint` | Human-in-the-loop gates |
| DPE | `crp.provenance` (absent in 4.0.0) | 13-stage hallucination/grounding analysis |
| Provider adapters | `crp.providers` | Unified OpenAI/Anthropic/Ollama/local interface |
| Session token | `crp.security.session_token` | Stateless signed session relay |
| HMAC audit | `crp.security.ComplianceAuditTrail` / `crp_shared.audit` | Tamper-evident chain |

---

## 4. Current Usage Map — Where CRPv4 Is Actually Used

### 4.1 Active CRPv4 usage

| File | CRPv4 usage | Quality |
|------|-------------|---------|
| `src/crp_comply/agent/crp_integration.py` | `PIIScanner`, `InjectionDetector`, `detect_contradictions`, `pack_facts`, `stitch_many`, `WarmStateStore`, `ExtractionPipeline`, `dispatch_via_crp` | Best-effort wrappers with broad `except Exception` fallbacks |
| `src/crp_comply/agent/tools.py` | 5 CRP context tools (`crp_retrieve_context`, `crp_check_facts`, `crp_get_related_facts`, `crp_get_document_structure`, `crp_get_continuation_state`) | Partial / stub (`crp_get_continuation_state` returns `{}`) |
| `src/crp_comply/agent/orchestrator.py` | Optional `dispatch_via_crp()` path; `CrpMessageLedger`; message compaction | Mostly custom loop; CRP path is bypass |
| `src/crp_comply/agent/federated_fabric.py` | `ContextualKnowledgeFabric` | Used for corpus + tenant CKF fan-out |
| `src/crp_comply/agent/ckf_corpus.py` | `ExtractionPipeline` | Bootstraps shared regulation CKF |
| `src/crp_comply/agent/llm.py` | `crp.providers.OpenAIAdapter`, `AnthropicAdapter` | Direct provider calls, not through `crp.Client` |
| `src/crp_comply/proxy/interceptor.py` | `PIIScanner`, `InjectionDetector` (best-effort); tries `crp.provenance` (fails silently) | Provenance disabled when module missing |
| `src/crp_comply/core.py` | `crp.security.compliance.ComplianceReporter`, `RiskClassifier` | Used for product-level reports |
| `src/crp_comply/api/safety.py` | References `SafetyControlPlane` | Endpoint surface only, not wired to agent loop |
| `src/crp_comply/checkpoint_inbox.py` | References CRP checkpoints | Backend exists, no frontend resolution UI |

### 4.2 CRPv4 usage that is missing entirely

| Capability | Evidence of absence |
|------------|---------------------|
| `crp.Client.dispatch_agentic` | `grep -r "dispatch_agentic" src/` → no agent-loop usage |
| `crp.Client.dispatch_with_tools` | Only `dispatch_via_crp` wrapper exists; not used as main loop |
| `MultiHorizonContext` | Zero references in `src/crp_comply` |
| `CognitiveStateObject` | Zero references |
| `WindowDAG` / `Client.dag` | Zero references |
| `ContinuationManager` | Only `crp.continuation.stitch.stitch_many` used directly |
| `crp.envelope.construct` | Custom compaction + custom MMR + `pack_facts` |
| `SafetyControlPlane` in agent loop | Used in `no_code.py` / checkpoint inbox, not in `orchestrator.py` |
| `crp.policy.parse_policy` | Zero references |
| `Checkpoint` in agent loop | Custom checkpoint implementation in `mcp_permissions.py` |

---

## 5. Agentic AI Ecosystem Architecture — As It Exists Today

```
┌─────────────────────────────────────────────────────────────┐
│  User request (web / API / SDK)                             │
└───────────────────────┬─────────────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  src/crp_comply/api/agent.py                                │
│  - Receives task + session_id                               │
│  - Loads JSON session file                                  │
│  - Selects/trimmes history manually                         │
└───────────────────────┬─────────────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  src/crp_comply/agent/orchestrator.py                       │
│  ComplianceAgent.run()                                      │
│  1. redact_pii()          ← CRP PIIScanner (best-effort)    │
│  2. scan_for_injection()  ← CRP InjectionDetector           │
│  3. build custom ToolRegistry                               │
│  4. prime RAG envelope (custom)                             │
│  5. seed CKF prior facts                                    │
│  6. LOOP (max 8):                                           │
│       a. compact_messages_for_budget()  ← custom folding    │
│       b. ComplianceLLM.chat_with_tools() ← raw provider     │
│       c. parse tool calls manually                          │
│       d. PolicyEnforcer.check()  ← custom PEP               │
│       e. execute tool                                       │
│       f. append result to messages                          │
│  7. continue_truncated_answer() ← stitch.stitch_many        │
│  8. output PII scan                                         │
│  9. audit close                                             │
└───────────────────────┬─────────────────────────────────────┘
                        ▼
┌─────────────────────────────────────────────────────────────┐
│  src/crp_comply/agent/llm.py                                │
│  ComplianceLLM                                              │
│  - Auto-detects provider from env                           │
│  - BYOK via per-user config                                 │
│  - Calls provider.generate_chat_with_tools() directly       │
│  - Manual streaming tool-call assembly                      │
│  - WorkerAdapter for local_worker bypasses CRP dispatch     │
└─────────────────────────────────────────────────────────────┘
```

**The critical flaw:** the LLM boundary is the only place CRP should intercept every call, yet CRP Comply calls the provider directly and then tries to apply CRP primitives afterwards. This is backwards.

---

## 6. Findings by Theme

### 6.1 Dispatch & Agent Loop

#### F1.1 — Custom ReAct loop duplicates CRP native dispatch (Critical)

- **Location:** `src/crp_comply/agent/orchestrator.py::ComplianceAgent.run()`
- **Evidence:** The function builds messages, primes RAG, compacts context, invokes `ComplianceLLM.chat_with_tools`, executes tools, and tracks budgets manually.
- **CRPv4 equivalent:** `crp.Client.dispatch_with_tools()` / `dispatch_agentic()`
- **Impact:** The team maintains its own context-window math, envelope compaction, loop policy, and tool-call parsing. Bugs in any of these silently degrade compliance output quality.
- **Recommended fix:** Migrate the production loop to `crp.Client.dispatch_with_tools` or `dispatch_agentic`. Register domain tools as CRP tool callbacks. Keep the legacy loop only as a thin fallback behind `CRP_COMPLY_USE_CRP_DISPATCH=0`.

#### F1.2 — Tool calling is custom, not CRP-native (High)

- **Location:** `src/crp_comply/agent/step_runner.py`, `src/crp_comply/agent/llm.py`
- **Evidence:** `ToolRegistry` is custom. `llm.py` manually reassembles streaming function-call argument fragments.
- **CRPv4 equivalent:** Tool schemas passed to `crp.Client.dispatch_with_tools()`
- **Impact:** CRP cannot apply pull-mode context relay, progressive disclosure, reflexive verification, or quality scoring to tool usage.
- **Recommended fix:** Pass tool definitions to CRP dispatch; remove manual JSON-schema validation and streaming assembly.

#### F1.3 — Advanced CRP dispatch modes unused (Medium)

- **Location:** `src/crp_comply/agent/*`
- **Evidence:** No references to `dispatch_hierarchical`, `dispatch_progressive`, `dispatch_reflexive`, `dispatch_intent`.
- **Impact:** Complex/multi-regulation tasks are handled by monolithic prompts instead of CRP’s map-reduce or progressive disclosure.
- **Recommended fix:** Route comprehensive queries to `dispatch_hierarchical` or `dispatch_progressive`.

#### F1.4 — Streaming tool-call assembly is manual (Medium)

- **Location:** `src/crp_comply/agent/llm.py`
- **Evidence:** Streaming function-call JSON chunks accumulated by hand.
- **Impact:** Fragile and bypasses CRP streaming abstractions.
- **Recommended fix:** Use `crp.Client.async_dispatch_stream` or provider adapter streaming support.

---

### 6.2 Context, Continuation & Envelope

#### F2.1 — Manual compaction instead of native envelope construction (High)

- **Location:** `src/crp_comply/agent/crp_integration.py::compact_messages_for_budget()`
- **Evidence:** Custom folding/clipping algorithm with pinned system/user/tail messages.
- **CRPv4 equivalent:** `crp.envelope.construct(task_intent, budget_tokens, EnvelopeState)`
- **Impact:** May clip system prompts or evidence in ways CRP’s native builder would avoid.
- **Recommended fix:** Build an `EnvelopeState` from session warm store / CKF and use `crp.envelope.construct`; use custom compaction only as a thin fallback.

#### F2.2 — Continuation uses low-level stitch, not ContinuationManager (Medium)

- **Location:** `src/crp_comply/agent/crp_integration.py::continue_truncated_answer()`
- **Evidence:** Calls `crp.continuation.stitch.stitch_many` directly.
- **CRPv4 equivalent:** `crp.continuation.ContinuationManager`
- **Impact:** Long outputs stitched heuristically without CRP’s structural gap analysis.
- **Recommended fix:** Replace manual continuation with `ContinuationManager`; implement `crp_get_continuation_state` against the manager’s state.

#### F2.3 — Envelope packing uses custom MMR before `pack_facts` (Medium)

- **Location:** `src/crp_comply/agent/crp_integration.py::pack_hits_to_envelope()`
- **Evidence:** Jaccard-based MMR rerank, then `crp.envelope.packer.pack_facts` with an empty `FactGraph`.
- **CRPv4 equivalent:** `crp.envelope.cdr_rank`, `score_facts`, `resolve_fact_authority`
- **Impact:** Diversity and authority scoring may not match CRP behavior.
- **Recommended fix:** Use CDR/score_facts and provide a real `FactGraph` to `pack_facts`.

#### F2.4 — CDR/CDGR not used (High)

- **Location:** `src/crp_comply/agent/rag_service.py` / `rag/`
- **Evidence:** RAG queries repeat the same query every window; no novelty-weighted ranking or graph-walk retrieval.
- **CRPv4 equivalent:** `crp.envelope.cdr`, `crp.ckf.graph_walk`
- **Impact:** Multi-window deliverables degrade; complex reasoning misses bridging facts.
- **Recommended fix:** Track covered facts per window and apply CDR; use graph-walk for multi-hop questions.

---

### 6.3 State, Memory & Session

#### F3.1 — No structured CRP session state (High)

- **Location:** `src/crp_comply/agent/orchestrator.py`, `src/crp_comply/api/agent.py`
- **Evidence:** No references to `crp.Client.session`, `MultiHorizonContext`, `CognitiveStateObject`, or `WindowDAG`.
- **Impact:** No structured cognitive state; multi-turn memory relies on ad-hoc message replay and custom `CrpMessageLedger`.
- **Recommended fix:** Adopt `Client.session` + `MultiHorizonContext` for turn blending; `CognitiveStateObject` + `WindowDAG` for facts/decisions/lineage.

#### F3.2 — CrpMessageLedger uses standalone WarmStateStore (Medium)

- **Location:** `src/crp_comply/agent/crp_integration.py::CrpMessageLedger`
- **Evidence:** Instantiates its own `WarmStateStore` instead of using the client-owned store.
- **Impact:** Facts in the ledger are not automatically visible to `Client.dispatch_*`, `Client.feedback`, or `Client.export_state`.
- **Recommended fix:** Share `client.warm_store` or synchronize ledger facts into it before dispatch/export.

#### F3.3 — Clarifier persistence is custom sqlite, not Client.resume (Medium)

- **Location:** `src/crp_comply/agent/clarifier.py`, `src/crp_comply/api/agent.py`
- **Evidence:** Suspended FSM snapshots stored in local sqlite.
- **CRPv4 equivalent:** `Client.resume(session_id, ...)`
- **Impact:** Resume only works within `crp-comply`; SDK cannot restore session state.
- **Recommended fix:** Persist only session ID + minimal state; use `Client.resume` on resumed turn.

#### F3.4 — Multi-horizon context and scratch buffer unused (High)

- **Location:** `src/crp_comply/agent/*`
- **Evidence:** Zero references to `MultiHorizonContext` / `ScratchBuffer`.
- **Impact:** Tool outputs pollute the knowledge base; large tool results blow up the prompt; no staleness detection.
- **Recommended fix:** Implement P/C/E tiers and use `ScratchBuffer` for tool outputs.

---

### 6.4 Safety, Policy & Checkpoints

#### F4.1 — PolicyEnforcer is home-grown, not SafetyControlPlane (High)

- **Location:** `src/crp_comply/agent/mcp_permissions.py`
- **Evidence:** Custom PEP with glob rules, ALLOW/DENY/CHECKPOINT/LOG actions, internal checkpoint queues.
- **CRPv4 equivalent:** `crp.security.control_plane.SafetyControlPlane` + `CustomSafetyRule` + `Checkpoint`
- **Impact:** Tool-call governance is decoupled from SDK safety surface; agent checkpoints are not CRP checkpoints.
- **Recommended fix:** Map `PolicyEnforcer` policies to `SafetyControlPlane` capabilities/rules; emit real `Checkpoint` objects; resolve via existing `checkpoint_inbox.py`.

#### F4.2 — Safety policy grammar not used (High)

- **Location:** `src/crp_comply/agent/*`
- **Evidence:** No references to `crp.policy.parse_policy` / `SafetyPolicy`.
- **Impact:** Safety is hard-coded in prompts and custom PEP instead of customer-configurable CSP-style directives.
- **Recommended fix:** Read `CRP-Safety-Policy` header / `CRP_COMPLY_SAFETY_POLICY` env and pass parsed policy to `crp.Client`.

#### F4.3 — PII / injection scanning not centrally enforced (Medium)

- **Location:** `src/crp_comply/agent/orchestrator.py`, `src/crp_comply/agent/worker_adapter.py`
- **Evidence:** Scans only user task; worker adapter scans only last tool message.
- **CRPv4 equivalent:** `SafetyControlPlane` capabilities or checkpoint triggers
- **Impact:** Tool results and assistant messages can carry injection/PII into the LLM context.
- **Recommended fix:** Register PII/injection scanning as `SafetyCapability` rules applied to every model input.

#### F4.4 — Risk classification not wired to safety plane (Medium)

- **Location:** `src/crp_comply/agent/tools.py::classify_ai_act_risk`
- **Evidence:** Returns verdict but does not trigger `SafetyControlPlane` coverage/checkpoint.
- **Recommended fix:** Feed `AIRiskLevel` results into `SafetyControlPlane.coverage` and trigger checkpoint for high/unacceptable risk.

#### F4.5 — Checkpoints lack frontend UI (Medium)

- **Location:** `src/crp_comply/checkpoint_inbox.py`, `src/crp_comply/api/checkpoint_routes.py`
- **Evidence:** Backend exists; no frontend approve/reject/edit UI.
- **Recommended fix:** Add Inbox notification type and resolution buttons.

---

### 6.5 Audit, Provenance & Attribution

#### F5.1 — Citations rely on LLM `[chunk_id]` markers (High)

- **Location:** `src/crp_comply/agent/reflector.py`, `src/crp_comply/agent/loop_runtime.py`
- **Evidence:** Regex-parsing observation text for `[chunk_id]` tags and regulation pinpoints.
- **CRPv4 equivalent:** `QualityReport` + `WindowDAG` lineage
- **Impact:** Citation integrity depends on LLM adherence to custom format; no SDK guarantee.
- **Recommended fix:** Use `QualityReport` from CRP dispatch and `WindowDAG` for structured attribution.

#### F5.2 — DPE not run on agent outputs (High)

- **Location:** `src/crp_comply/agent/orchestrator.py`, `src/crp_comply/proxy/interceptor.py`
- **Evidence:** `crp.provenance` imported in proxy but module absent in 4.0.0; no DPE in agent loop.
- **Impact:** No 13-stage hallucination/grounding analysis on deliverables.
- **Recommended fix:** Resolve SDK drift; run DPE after each dispatch; surface `QualityReport.grounding_pct` and `hallucination_risk`.

#### F5.3 — Audit trails fragmented (Medium)

- **Location:** `src/crp_comply/agent/orchestrator.py`, `src/crp_comply/core.py`, `src/crp_comply/proxy/interceptor.py`
- **Evidence:** Multiple `ComplianceAuditTrail` instances not cross-referenced by session ID.
- **Recommended fix:** One `ComplianceAuditTrail` per session across agent, proxy, and report generator.

#### F5.4 — HMAC chain verification incomplete (Medium)

- **Location:** `src/crp_comply/core.py::CRPComply._verify_trail_chain()`
- **Evidence:** Checks `previous_hash` linkage only.
- **CRPv4 equivalent:** `CognitiveStateObject.compute_hmac` / `extend_hmac_chain`
- **Recommended fix:** Compute and verify HMACs on audit records and CSO state.

---

### 6.6 Tooling & Feedback

#### F6.1 — CRP context tools partial / no-op (Medium)

- **Location:** `src/crp_comply/agent/tools.py`
- **Evidence:** `crp_get_continuation_state` returns `{}`; other tools are thin wrappers rather than using higher-level CRP APIs.
- **Recommended fix:** Implement against `client.ckf`, `client.warm_store`, and `ContinuationManager.state`.

#### F6.2 — Feedback routed to custom ledger + warm store, not Client.feedback (Medium)

- **Location:** `src/crp_comply/api/agent.py::agent_feedback`, `src/crp_comply/agent/crp_integration.py::crp_apply_feedback`
- **Evidence:** Appends JSONL and updates warm store directly.
- **CRPv4 equivalent:** `client.feedback`
- **Recommended fix:** Route feedback through `client.feedback`; keep JSONL as immutable audit copy.

#### F6.3 — Sealed export misses full loop state (Medium)

- **Location:** `src/crp_comply/agent/crp_integration.py::crp_export_state_bytes`
- **Evidence:** Pre-ingests task/answer/clarifications but not `CrpMessageLedger`, FSM snapshot, tool event log, or audit trail.
- **Recommended fix:** Synchronize ledger/FSM/audit into `client.warm_store` / `Client.session` before export.

---

### 6.7 Local Worker Integration

#### F7.1 — WorkerAdapter bypasses CRP dispatch (High)

- **Location:** `src/crp_comply/agent/worker_adapter.py`, `src/crp_comply/agent/llm.py::ComplianceLLM.for_user()`
- **Evidence:** Forwards calls via `WorkerRegistry.dispatch_from_sync`; not a `crp.providers` adapter.
- **Impact:** Local workers bypass CRP dispatch, continuation, DPE, and quality reporting.
- **Recommended fix:** Implement `crp.providers.LLMProvider` / `ChatProvider` for local workers, or route calls through `crp.Client` with a thin adapter.

#### F7.2 — Backend dispatches without checking upstream LLM reachability (Critical)

- **Location:** `src/crp_comply/api/worker_registry.py::dispatch()` lines 161–207
- **Evidence:** `dispatch()` does not consult `slot.upstream_reachable` before sending the request frame.
- **Impact:** The worker WebSocket is attached (green status dot), but the upstream LM Studio / Ollama process is down or unloaded. The backend sends the request anyway and waits up to 600 seconds.
- **Symptom:** Exact “connection works, no response” failure.
- **Recommended fix:** Fail fast with `WorkerOfflineError("Local LLM is not reachable")` when `slot.upstream_reachable is False`.

#### F7.3 — `detach()` cancels pending futures for all users (High)

- **Location:** `src/crp_comply/api/worker_registry.py::detach()` lines 133–157
- **Evidence:** `_pending` is keyed only by `request_id`; `detach()` iterates the entire map and fails every future.
- **Impact:** When one user’s worker disconnects, every other user’s in-flight local-worker request is cancelled.
- **Recommended fix:** Store `(user_id, future)` in `_pending` and scope cancellation to the disconnecting user.

#### F7.4 — Streaming response can hang forever on lost `stream_end` (High)

- **Location:** `sdk/src/crp_comply_sdk/worker.py::_handle_streaming_request()` lines 630–640; `src/crp_comply/api/worker_registry.py::dispatch_streaming_from_sync()` lines 392–420
- **Evidence:** If the SDK worker fails to send a `stream_chunk`, it returns without emitting `stream_end`. The backend queue has no watchdog, so it waits the full timeout.
- **Impact:** Agent request appears to hang; UI never sees completion or error.
- **Recommended fix:** Worker must emit `stream_end(error=...)` before returning. Backend must add a watchdog that injects a synthetic error after timeout.

#### F7.5 — Streaming queue drops chunks silently when full (High)

- **Location:** `src/crp_comply/api/worker_registry.py::receive()` lines 256–271
- **Evidence:** `put_nowait` raises `queue.Full`; the chunk is dropped and a TODO is logged.
- **Impact:** Response tokens are lost; if the dropped frame was `stream_end`, the caller waits until timeout.
- **Recommended fix:** Implement back-pressure (pause upstream read until queue drains) or use blocking `put()` with a timeout and propagate `WorkerError`.

#### F7.6 — WorkerAdapter silently falls back from streaming to blocking (High)

- **Location:** `src/crp_comply/agent/worker_adapter.py::generate_chat_with_tools_streaming()` lines 240–287
- **Evidence:** Catches **any** `RuntimeError` and falls back to a blocking call.
- **Impact:** A timeout or worker error triggers a second blocking dispatch, doubling the wait and hiding the real failure from the UI.
- **Recommended fix:** Only fall back for explicit “streaming not supported” / protocol errors. Surface `WorkerTimeoutError` / `WorkerOfflineError` immediately.

#### F7.7 — Reconnect storm after clean disconnect (High)

- **Location:** `sdk/src/crp_comply_sdk/worker.py::run_worker()` lines 673–687
- **Evidence:** On clean return from `_run_session()`, backoff is reset to 1.0 and the loop reconnects with **no sleep**.
- **Impact:** If the relay rejects the API key or closes the socket, the worker hammers the backend.
- **Recommended fix:** Always sleep `max(1.0, backoff)` before reconnecting; reset backoff only after successful `ready` frame.

#### F7.8 — Provider test/diagnose endpoints do not understand `local_worker` (High)

- **Location:** `src/crp_comply/api/provider.py::test_provider()` lines 433–511; `provider_diagnose()` lines 582–720
- **Evidence:** `test_provider()` tries an HTTP `GET` to `base_url + "/models"` where `base_url` is a `ws://` placeholder. `provider_diagnose()` runs a generic probe via `ComplianceLLM.chat()`.
- **Impact:** The Settings “Test connection” button fails even when the worker is healthy; users cannot distinguish socket/upstream/model failures.
- **Recommended fix:** Detect `local_worker` in both endpoints and call `WorkerRegistry.status()` plus a small chat probe dispatch.

#### F7.9 — SDK install docs omit `[worker]` extra (High)

- **Location:** `docs/BYOK_MODES.md:147`, `sdk/README.md:14`, `worker.py` docstring
- **Evidence:** Documentation says `pip install crp-comply-sdk`.
- **Impact:** `websockets` is missing; worker exits with `ImportError` before any connection is attempted.
- **Recommended fix:** Update all docs to `pip install 'crp-comply-sdk[worker]'`.

#### F7.10 — OpenAI request parameters dropped (Medium)

- **Location:** `src/crp_comply/agent/worker_adapter.py::generate_chat_with_tools()` lines 212–238; `sdk/src/crp_comply_sdk/worker.py::_handle_request()` lines 206–213
- **Evidence:** Only `tools`, `tool_choice`, `temperature`, `max_tokens`, `stream` are forwarded.
- **Impact:** `top_p`, `presence_penalty`, `frequency_penalty`, `response_format`, `stop`, `seed`, `logit_bias` are dropped; JSON-mode requests may fail.
- **Recommended fix:** Forward a known-safe allow-list of OpenAI fields.

#### F7.11 — Ollama native paths malformed when base ends in `/v1` (Medium)

- **Location:** `sdk/src/crp_comply_sdk/worker.py::_handle_request()` lines 221–225
- **Evidence:** `/v1` prefix is not stripped for Ollama native paths (`/api/chat`, `/api/generate`).
- **Impact:** URL becomes `http://localhost:11434/v1/api/chat` → 404.
- **Recommended fix:** Special-case Ollama native paths to remove the `/v1` suffix.

#### F7.12 — `local_worker` config saved even if no worker attached (Medium)

- **Location:** `src/crp_comply/api/provider.py::configure_provider()` lines 315–334
- **Evidence:** Config persisted regardless of `WorkerRegistry.is_attached(user_id)`.
- **Impact:** User selects SDK relay with no worker running; first agent call times out.
- **Recommended fix:** Return a warning or 422 if `local_worker` is selected and no worker is currently attached.

#### F7.13 — Worker streaming / tool-call parsing fragility (Medium)

- **Location:** `src/crp_comply/agent/worker_adapter.py::_parse_completion()` lines 312–333
- **Evidence:** `arguments` left as a JSON string; concatenates `name` across chunks with `+=`.
- **Impact:** Orchestrator may crash on malformed arguments; duplicated tool names on split chunks.
- **Recommended fix:** Parse `arguments` with `json.loads` inside `_parse_completion`; overwrite `name` rather than concatenate.

#### F7.14 — Local AI documentation drift (High)

- **Location:** `docs/LOCAL_LLM_GUIDE.md`, `docs/BUDGET_LLM_GUIDANCE.md`, `docs/BYOK_MODES.md`
- **Evidence:** Guide references env vars the code does not read (`CRP_COMPLY_PROVIDER`, `LMSTUDIO_BASE_URL`, `OLLAMA_BASE_URL`) and CLI commands that do not exist (`crp-comply llm-probe`, `crp-comply run-recipe --local`).
- **Impact:** Users follow docs and get silent failures or “No such command” errors.
- **Recommended fix:** Rewrite docs to match actual env vars (`CRP_COMPLY_LLM_BASE_URL`, `CRP_COMPLY_LLM_API_KEY`, `CRP_COMPLY_LLM_MODEL`) and actual commands/API endpoints.

---

## 7. Severity-Prioritised Gap Matrix

| ID | Finding | Severity | Effort | Owner area |
|----|---------|----------|--------|------------|
| F1.1 | Custom ReAct loop bypasses CRP dispatch | Critical | High | Agent |
| A1 | SDK drift: `crp.provenance`/`crp.policy` absent | Critical | Medium | Proxy/Agent |
| F7.2 | Backend dispatches to unreachable local LLM | Critical | Low | Worker/API |
| F4.1 | Custom PEP vs SafetyControlPlane | High | High | Agent/Safety |
| F3.1 | No structured CRP session state | High | High | Agent/API |
| F5.1 | Citations rely on LLM markers | High | Medium | Agent/Frontend |
| F7.1 | Local worker bypasses CRP dispatch | High | Medium | Agent/SDK |
| F7.3 | `detach()` cancels all users' pending futures | High | Low | Worker/API |
| F7.4 | Streaming hangs on lost `stream_end` | High | Medium | Worker/SDK |
| F7.5 | Streaming queue drops chunks silently | High | Medium | Worker/API |
| F7.6 | WorkerAdapter silently falls back from streaming | High | Low | Agent/SDK |
| F7.7 | SDK worker reconnect storm | High | Low | SDK |
| F7.8 | Provider test/diagnose broken for `local_worker` | High | Medium | API/Frontend |
| F7.9 | SDK install docs omit `[worker]` extra | High | Low | Docs |
| F7.14 | Local AI documentation drift | High | Medium | Docs |
| F5.2 | DPE not run on outputs | High | Medium | Agent/Proxy |
| F2.4 | CDR/CDGR not used | High | Medium | Agent/RAG |
| F2.1 | Manual compaction vs envelope construct | High | Medium | Agent |
| F4.2 | Safety policy grammar unused | High | Low | Agent/Safety |
| F1.2 | Custom tool loop | High | Medium | Agent |
| F3.4 | Multi-horizon / scratch buffer unused | High | Medium | Agent |
| MT1 | Phase-7 steps run in isolated agent instances | Critical | High | Agent runtime |
| MT5 | No explicit research/analysis/synthesis/citation phases | Critical | High | Agent runtime |
| MT7 | No final-answer citation validator | High | Medium | Agent output |
| MT11 | No cross-source synthesis / conflict resolution | High | Medium | Research tools |
| MT13 | Web research feedback loops broken/disabled | High | Low/Medium | Sidecars / Agent |
| MT17 | Local-worker long-turn continuation not resumable | High | Medium | Worker / API |
| F7.10 | OpenAI parameters dropped on worker path | Medium | Low | SDK/Agent |
| F7.11 | Ollama native paths malformed | Medium | Low | SDK |
| F7.12 | `local_worker` config saved without worker attached | Medium | Low | API/Frontend |
| F7.13 | Worker tool-call parsing fragility | Medium | Low | Agent/SDK |
| F5.3 | Fragmented audit trails | Medium | Medium | Core/Agent/Proxy |
| F5.4 | HMAC verification incomplete | Medium | Low | Core |
| F2.2 | Manual continuation | Medium | Medium | Agent |
| F2.3 | Custom MMR / empty FactGraph | Medium | Low | Agent |
| F3.2 | Standalone WarmStateStore | Medium | Low | Agent |
| F3.3 | Clarifier not using Client.resume | Medium | Medium | Agent/API |
| F4.3 | PII/injection scanning incomplete | Medium | Low | Agent |
| F4.4 | Risk classifier not wired to safety plane | Medium | Low | Agent |
| F4.5 | Checkpoints lack frontend UI | Medium | Medium | Frontend/API |
| F6.1 | CRP context tools partial/no-op | Medium | Medium | Agent |
| F6.2 | Feedback not using Client.feedback | Medium | Low | Agent/API |
| F6.3 | Sealed export incomplete | Medium | Low | Agent |
| F1.3 | Advanced dispatch modes unused | Medium | Low | Agent |
| F1.4 | Manual streaming assembly | Medium | Low | Agent |

---

## 8. Recommendations

### Short term (1–2 weeks)

1. **Pin `crprotocol` to a known-good version** and remove or vendor references to `crp.provenance` / `crp.policy` that do not exist in that version. Document the canonical CRPv4 surface.
2. **Add structured logging** wherever CRP primitives fall back to no-ops; stop silently degrading.
3. **Implement a `CRPComplyLLM` wrapper** that delegates to `crp.Client.dispatch_with_tools()` behind a feature flag.
4. **Surface `QualityReport` in the agent API** (`/api/v1/agent/*`) and frontend (`AgentChat`) — grounding %, hallucination risk, safety flags.
5. **Add checkpoint resolution UI** in the Inbox page.
6. **Fix local-worker dispatch reliability:** fail fast when upstream LLM is unreachable; scope `_pending` by user; emit `stream_end(error=...)` on worker send failure; add queue watchdog/back-pressure.
7. **Fix SDK worker reconnect storm** and update install docs to `pip install 'crp-comply-sdk[worker]'`.
8. **Make provider test/diagnose local-worker-aware** so the Settings UI reports accurate status.

### Medium term (1–2 months)

9. **Migrate the production agent loop to CRP-native dispatch**, registering domain tools with CRP.
10. **Replace custom PEP with `SafetyControlPlane`**; parse `CRP-Safety-Policy` from header/env.
11. **Adopt `MultiHorizonContext` + `CognitiveStateObject` + `WindowDAG`** for session state and lineage.
12. **Use `ContinuationManager` for long deliverables** and `crp.envelope.construct` for envelope building.
13. **Unify audit trail** under one session-scoped `ComplianceAuditTrail` and verify HMACs.
14. **Implement a CRP provider adapter for local workers** so local AI participates in dispatch/continuation/DPE; route local-worker calls through `crp.Client`.
15. **Rewrite local-AI docs** to match actual env vars, commands, and the SDK `[worker]` extra.

### Long term (2–3 months)

16. **Adopt CDR/CDGR** in the RAG path and the 5-primitive storage lifecycle.
17. **Use STL** to decompose complex compliance tasks into retriever/analyser/synthesiser operations.
18. **Replace regex citation checks** with structured fact-level provenance from `WindowDAG`.
19. **Add Redis-backed worker registry** for multi-replica SaaS deployments.

---

## 9. Round 3 — Multi-Turn Interaction / Feedback Loops

The detailed multi-turn agent architecture analysis is now in [`MULTI_TURN_AGENT_AUDIT.md`](MULTI_TURN_AGENT_AUDIT.md). Key Round 3 findings include:

- **Per-step amnesia in Phase-7.** Each plan step runs inside a fresh `ComplianceAgent` with a fresh `CrpMessageLedger`, so cross-step reasoning relies on heavily compressed prior observations.
- **No explicit research → analysis → synthesis → citation phases.** The loop is generic ReAct with no coverage planner, no cross-source reconciliation tool, and no final-answer citation validator.
- **CRPv4 state primitives remain unused.** `MultiHorizonContext`, `CognitiveStateObject`, `WindowDAG`, `ContinuationManager`, and `crp.envelope.construct` are not referenced in the agent loop.
- **Web research feedback loops are broken or disabled.** SearXNG CRP plugins are commented out; agent-side feedback is either unwired or crashes on call; web results are transient and not indexed for later turns.
- **Local-LLM long turns are fragile.** Continuation state is not persisted across API calls, small-context models can lose deterministic compliance tools, and worker streaming fallback hides real failures.

See [`MULTI_TURN_AGENT_AUDIT.md`](MULTI_TURN_AGENT_AUDIT.md) for the full findings register and recommendations.

---

## Appendix C — Cross-reference

- [`LOCAL_AI_ENABLEMENT_AUDIT.md`](LOCAL_AI_ENABLEMENT_AUDIT.md) — detailed local LLM connection methods, SDK worker/backend reliability flaws, documentation drift, and root-cause analysis for “connection works, no response.”
- [`MULTI_TURN_AGENT_AUDIT.md`](MULTI_TURN_AGENT_AUDIT.md) — Round 3 multi-turn agent architecture, research→analysis→synthesis→citation gaps, web-search sidecar integration, and local-LLM long-turn reliability.

---

## Appendix A — Files to read when acting on this audit

- `src/crp_comply/agent/orchestrator.py`
- `src/crp_comply/agent/crp_integration.py`
- `src/crp_comply/agent/tools.py`
- `src/crp_comply/agent/llm.py`
- `src/crp_comply/agent/loop_runtime.py`
- `src/crp_comply/agent/mcp_permissions.py`
- `src/crp_comply/agent/worker_adapter.py`
- `src/crp_comply/proxy/interceptor.py`
- `src/crp_comply/api/agent.py`
- `src/crp_comply/core.py`
- `src/crp_comply/checkpoint_inbox.py`
- `sdk/src/crp_comply_sdk/worker.py`
- `src/crp_comply/api/worker_registry.py`
- `src/crp_comply/api/worker_ws.py`
- `src/crp_comply/api/provider.py`
- `src/crp_comply/api/llm_security.py`
- `docs/BYOK_MODES.md`
- `docs/LOCAL_LLM_GUIDE.md`
- `docs/BUDGET_LLM_GUIDANCE.md`
- `MULTI_TURN_AGENT_AUDIT.md`

## Appendix B — Related skills

- `crp-v4-protocol-reference`
- `crp-v4-agentic-ecosystem`
- `crp-v4-ai-safety`
- `crp-v4-context-management`
- `crp-v4-capability-map`
- `crp-comply-codebase`
