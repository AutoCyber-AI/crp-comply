# CRP Comply — Master Implementation Roadmap

**Version:** 1.0 — 20-round phased execution plan  
**Date:** 2026-06-21  
**Author:** Kimi Code CLI  
**Scope:** All research documents, audits, skills, and codebase areas required to transform CRP Comply from a feature-rich but fragile compliance prototype into a production-ready, conversational, local-first AI governance platform.  
**Target test environment:** LM Studio at `http://192.168.0.6:1234` (OpenAI-compatible endpoints: `/v1/models`, `/v1/chat/completions`; native: `/api/v1/models`).

---

## 1. Executive Summary

This roadmap consolidates every research document, audit, and skill produced for CRP Comply and turns them into **20 executable implementation rounds**. Each round targets a narrow, well-defined set of sub-problems, references the source research, identifies the files to change, describes the implementation, defines validation criteria, and includes an **LM Studio test plan**.

The rounds are ordered to maximise **foundation-first** progress:

- **Rounds 1–5** fix the substrate: CRPv4 adoption, local-LLM reliability, dialogue/NLU architecture, memory model, and proxy security.
- **Rounds 6–10** harden the agent loop: budgets, clarifications, citations, web research, and multi-turn state.
- **Rounds 11–15** rebuild the product/UX surface: single Draft experience, onboarding, settings, recipes, and evidence UI.
- **Rounds 16–20** operationalise the business: billing, tiers, evals, continuous compliance, documentation, and launch readiness.

Every round must be implemented, validated with automated tests, and smoke-tested against the local LM Studio instance before the next round begins. The goal is not to ship everything at once, but to leave the codebase demonstrably better after each round.

---

## 2. How to Use This Roadmap

1. **Execute one round at a time.** Do not start round N+1 until round N passes its validation and LM Studio tests.
2. **Follow the per-round workflow:**
   - **Understand** the sub-problems and research references.
   - **Analyse** the current code and identify refactor/addition points.
   - **Implement** the changes minimally and cohesively.
   - **Validate** with unit/integration tests and static analysis.
   - **Test** with LM Studio using the provided test plan.
3. **Update tests.** Add or modify tests in `tests/` for every backend change. Add or update Vitest/Playwright tests for frontend changes where feasible.
4. **Cross-reference.** Use the cross-reference matrix in Section 24 to ensure every research finding is addressed.
5. **Document.** Update `AGENTS.md`, `README.md`, and relevant docs when behaviour changes.

---

## 3. Consolidated Problem Inventory

This inventory is synthesised from the staged audits (`AGENTIC_AI_AUDIT.md`, `LOCAL_AI_ENABLEMENT_AUDIT.md`, `MULTI_TURN_AGENT_AUDIT.md`, `CONVERSATIONAL_AI_AUDIT.md`), strategic reassessments, production-readiness reviews, security posture, UX redesign, monetisation analysis, and CRP audit series.

### 3.1 Agent / orchestration substrate

| ID | Problem | Source docs |
|----|---------|-------------|
| A1 | `ComplianceAgent.run()` is a bespoke ReAct loop that bypasses `crp.Client.dispatch*()` | AGENTIC_AI_AUDIT.md, CRP_AUDIT.md |
| A2 | CRPv4 primitives (`MultiHorizonContext`, `CognitiveStateObject`, `WindowDAG`, `ContinuationManager`, `SafetyControlPlane`) are unused | AGENTIC_AI_AUDIT.md, MULTI_TURN_AGENT_AUDIT.md, CONVERSATIONAL_AI_AUDIT.md |
| A3 | Per-step amnesia: Phase-7 spins a fresh `ComplianceAgent` per step with ~240-char observations | MULTI_TURN_AGENT_AUDIT.md |
| A4 | Token budget `LoopBudgetMeter.record_tokens()` is never called | MULTI_TURN_AGENT_AUDIT.md |
| A5 | Plan revision is a counter, not a real replan | MULTI_TURN_AGENT_AUDIT.md |
| A6 | Two clarification suspension mechanisms (`ClarificationNeeded` vs `AskUserSuspended`) | MULTI_TURN_AGENT_AUDIT.md, CONVERSATIONAL_AI_AUDIT.md |
| A7 | No final-answer citation validator in chat | MULTI_TURN_AGENT_AUDIT.md, CONVERSATIONAL_AI_AUDIT.md |
| A8 | `Reflector` confidence path unused; citation check is regex-only | MULTI_TURN_AGENT_AUDIT.md |
| A9 | Web-search feedback loops disabled/unwired | MULTI_TURN_AGENT_AUDIT.md |
| A10 | Research → analysis → synthesis → citation phases not explicit | MULTI_TURN_AGENT_AUDIT.md |

### 3.2 Conversational AI / NLU

| ID | Problem | Source docs |
|----|---------|-------------|
| C1 | No dialogue manager or dialogue policy | CONVERSATIONAL_AI_AUDIT.md |
| C2 | No structured NLU/entity/slot layer | CONVERSATIONAL_AI_AUDIT.md |
| C3 | Clarification is punitive, not collaborative | CONVERSATIONAL_AI_AUDIT.md |
| C4 | No repair or incremental confirmation strategy | CONVERSATIONAL_AI_AUDIT.md |
| C5 | No persona/tone policy or anthropomorphization guardrails | CONVERSATIONAL_AI_AUDIT.md, AGENTIC_AI_AUDIT.md |
| C6 | No cross-turn user model injected into agent loop | CONVERSATIONAL_AI_AUDIT.md |
| C7 | No coreference/ellipsis or sentiment detection | CONVERSATIONAL_AI_AUDIT.md |
| C8 | Recipe interviews approximate slot filling but have no runtime state machine | CONVERSATIONAL_AI_AUDIT.md |

### 3.3 Local LLM / BYOK / worker

| ID | Problem | Source docs |
|----|---------|-------------|
| L1 | Local-LLM context-window mismatch: code uses family max, not LM Studio `loaded_context_length` | LOCAL_AI_ENABLEMENT_AUDIT.md, CRP_AUDIT_6_GAPS_AND_FIXES.md |
| L2 | Lost `stream_end` frames cause streaming hangs | LOCAL_AI_ENABLEMENT_AUDIT.md |
| L3 | `WorkerAdapter` silently falls back from streaming to blocking | LOCAL_AI_ENABLEMENT_AUDIT.md |
| L4 | Cross-user request cancellation when worker disconnects | LOCAL_AI_ENABLEMENT_AUDIT.md |
| L5 | SDK worker reconnect storm | LOCAL_AI_ENABLEMENT_AUDIT.md |
| L6 | Provider test/diagnose endpoints do not understand `local_worker` | LOCAL_AI_ENABLEMENT_AUDIT.md |
| L7 | Documentation and configuration templates out of sync | LOCAL_AI_ENABLEMENT_AUDIT.md |
| L8 | Non-resumable continuation across API calls | MULTI_TURN_AGENT_AUDIT.md |
| L9 | BYOK modes not exposed clearly in onboarding/settings | BUSINESS_MODEL_LLM_UPSELL.md |

### 3.4 Proxy / security / multi-tenancy

| ID | Problem | Source docs |
|----|---------|-------------|
| S1 | `session_id="proxy"` shared across all users | CRP_COMPLY_REASSESSMENT.md |
| S2 | Consent is global, not per-user | CRP_COMPLY_REASSESSMENT.md |
| S3 | All processing records filed as `SECURITY_SCANNING` | CRP_COMPLY_REASSESSMENT.md |
| S4 | `logger` used before definition in degraded `ImportError` path | CRP_COMPLY_REASSESSMENT.md |
| S5 | CRP critical subsystems silently no-op if import fails | CRP_AUDIT_5_GAPS_AND_FIXES.md |
| S6 | Exposed secrets (CRP API key, PyPI token) in committed logs | CRP_AUDIT_6_GAPS_AND_FIXES.md |
| S7 | Reasoning/thinking tokens over-disclosed in UI/logs | CRP_AUDIT_5_GAPS_AND_FIXES.md |
| S8 | HMAC evidence signing; should migrate to Ed25519 | PRODUCT_SECURITY.md |
| S9 | No rate-limit token bucket beyond monthly quota | PRODUCT_SECURITY.md |
| S10 | Live Regulation CI has overly broad `contents: write` | PRODUCT_SECURITY.md |

### 3.5 Frontend / UX

| ID | Problem | Source docs |
|----|---------|-------------|
| F1 | v1 and v2 routes/pages coexist; navigation confusion | UI_UX_REDESIGN.md, COMPLIANCE_MODEL_GAPS.md |
| F2 | Workspace + AgentChat are two parallel drafting surfaces | UI_UX_REDESIGN.md, COMPLIANCE_MODEL_GAPS.md |
| F3 | Settings page is 1,465-line monolith | UI_UX_REDESIGN.md |
| F4 | Developer preview routes exposed (`ReasoningTapePreview`, `GlobalAgentPanel`) | Direct code review |
| F5 | Onboarding profile not visibly used in agent chat | CONVERSATIONAL_AI_AUDIT.md, UX review |
| F6 | No progressive disclosure in recipe library | UI_UX_REDESIGN.md |
| F7 | No public marketing funnel (pricing buried) | REDESIGN_STRATEGY.md |
| F8 | Billing status/quota visibility missing | UI_UX_REDESIGN.md, USER_ACTIONS_REQUIRED.md |
| F9 | No `RequireMfa` wrapper for Clerk MFA | USER_ACTIONS_REQUIRED.md |
| F10 | Programme 8-state lifecycle not fully rendered | UI_UX_REDESIGN.md |

### 3.6 Backend / API / data

| ID | Problem | Source docs |
|----|---------|-------------|
| B1 | Flat session JSON instead of structured dialogue state | CONVERSATIONAL_AI_AUDIT.md |
| B2 | Model router exists but is not wired into orchestrator | COMPLIANCE_MODEL_GAPS.md |
| B3 | Token telemetry missing (input/output tokens, cost, latency) | COMPLIANCE_MODEL_GAPS.md |
| B4 | Evaluation suite too small (13 cases, target ≥20) | COMPLIANCE_MODEL_GAPS.md |
| B5 | Tier-feature matrix lacks fuzz coverage | COMPLIANCE_MODEL_GAPS.md |
| B6 | Continuous compliance engine (decide/explain) incomplete | CONTINUOUS_COMPLIANCE.md |
| B7 | Evidence substrate queryable but UI not first-class | COMPLIANCE_MODEL_ANALYSIS.md |
| B8 | Context-source provenance not tracked (protocol fix needed) | STRATEGIC_REASSESSMENT.md |
| B9 | ISO 42001 deliverables expansion incomplete | STRATEGIC_REASSESSMENT.md |
| B10 | Backup/restore drill not performed in production | PRODUCTION_READINESS.md |

### 3.7 Business / monetisation

| ID | Problem | Source docs |
|----|---------|-------------|
| M1 | Pricing mismatch across `STRIPE_MONETISATION.md`, `Pricing.tsx`, backend | PAYMENT_WORKFLOW_ANALYSIS.md |
| M2 | No webhook idempotency store | PAYMENT_WORKFLOW_ANALYSIS.md |
| M3 | Failed payment never revokes access (dunning gap) | PAYMENT_WORKFLOW_ANALYSIS.md |
| M4 | No dead-letter/reconciliation | PAYMENT_WORKFLOW_ANALYSIS.md |
| M5 | Immediate downgrade on cancellation | PAYMENT_WORKFLOW_ANALYSIS.md |
| M6 | Frontend assumes success before server confirms | PAYMENT_WORKFLOW_ANALYSIS.md |
| M7 | README/marketing overclaims “proxy/forwarder” and managed LLM margin | BUSINESS_MODEL_LLM_UPSELL.md |
| M8 | Enterprise delivery templates/legal docs missing | ENTERPRISE_DELIVERY_PLAYBOOK.md |
| M9 | Usage-based lever missing / flat pricing misaligned | REDESIGN_STRATEGY.md |
| M10 | Anonymous free tier gives away value without lead capture | REDESIGN_STRATEGY.md |

---
## 4. Implementation Rounds

---

### Round 1 — CRPv4 Adoption: Replace Bespoke ReAct Loop with `crp.Client` Dispatch

#### 1.1 Understand
The agent loop currently manually builds messages, primes RAG, compacts context, calls `ComplianceLLM.chat_with_tools()`, parses tool calls, and stitches continuations. CRPv4 already provides `crp.Client.dispatch_with_tools()`, `dispatch_agentic()`, `dispatch_stream_augmented()`, and envelope/continuation primitives. The bespoke loop re-implements capabilities that the protocol owns and creates provenance/audit gaps.

#### 1.2 Research references
- `AGENTIC_AI_AUDIT.md` §2 (CRPv4 capability inventory), §3 (agent loop bypasses CRP dispatch)
- `CRP_AUDIT.md` §2 (CRP SDK underutilization)
- `CRP_NATIVE_DISPATCH_ANALYSIS.md`

#### 1.3 Analyse current code
- `src/crp_comply/agent/orchestrator.py` — `ComplianceAgent.run()`, message building, tool parsing, continuation
- `src/crp_comply/agent/crp_integration.py` — `CrpMessageLedger`, envelope packing, folding
- `src/crp_comply/agent/llm.py` — `ComplianceLLM`, provider routing
- `src/crp_comply/agent/loop_runtime.py` — Phase-7 loop calls `ComplianceAgent` per step

#### 1.4 Implementation
1. Pin `crprotocol>=4.0.0` in `pyproject.toml` and fail fast on import in production (`CRP_COMPLY_ENVIRONMENT=production`).
2. Create `src/crp_comply/agent/crp_dispatch.py` with a `CrpDispatcher` wrapper around `crp.Client.dispatch_with_tools()`.
3. Refactor `ComplianceAgent.run()` to delegate the tool loop to `CrpDispatcher` while preserving the existing tool registry and audit hooks.
4. Migrate `compact_messages_for_budget()` to use `crp.envelope.compute_envelope_budget()` as the single source of truth.
5. Add a feature flag `CRP_DISPATCH_ENABLED` so the legacy loop can remain as fallback during transition.
6. Update `loop_runtime.py` to pass the full `DialogueContext`/`UserModel` into the dispatcher.

#### 1.5 Validation
- `tests/test_agent_orchestrator.py` must pass.
- New test `tests/test_agent_crp_dispatch.py` verifies dispatch produces identical tool calls and final answer as legacy loop on deterministic fixtures.
- Bandit/ruff clean.

#### 1.6 LM Studio test plan
1. Configure LM Studio with `llama3.1:8b` at `http://192.168.0.6:1234/v1`.
2. Start a new agent session: `POST /api/v1/agent/start` with task `"Classify a medical imaging triage system under EU AI Act Art. 6"`.
3. Verify the dispatcher calls `classify_ai_act_risk` and returns a structured result.
4. Verify final answer cites deterministic tool output, not hallucinated articles.
5. Stream the session and confirm `loop.tool.call` events are emitted.

---

### Round 2 — Local-LLM Context Detection and Streaming Lifecycle Hardening

#### 2.1 Understand
Local LLMs often load with a smaller context window than the model family maximum (e.g. Llama-3.1-8B family max 131k but LM Studio loaded at 4096). The current code uses the family max, causing `400 Context size exceeded`. Additionally, streaming hangs when `stream_end` is lost, and `WorkerAdapter` silently falls back to blocking mode.

#### 2.2 Research references
- `LOCAL_AI_ENABLEMENT_AUDIT.md` §3, §4
- `MULTI_TURN_AGENT_AUDIT.md` §5
- `CRP_AUDIT_6_GAPS_AND_FIXES.md` §2

#### 2.3 Analyse current code
- `src/crp_comply/agent/llm.py` — context-window sizing
- `src/crp_comply/agent/worker_adapter.py` — streaming/blocking fallback
- `src/crp_comply/api/worker_registry.py`, `worker_ws.py` — WebSocket lifecycle
- `sdk/src/crp_comply_sdk/worker.py` — SDK worker streaming
- `src/crp_comply/api/provider.py` — provider test/diagnose

#### 2.4 Implementation
1. Query LM Studio native `/api/v1/models` for `loaded_context_length` and cap adapter context to `min(family_max, loaded_context_length)`.
2. Expose `loaded_context_length` in SDK worker `hello`/`health` frames.
3. Add a watchdog in `worker_ws.py` for lost `stream_end`: if no frame for N seconds, emit synthetic `stream_end` and close request.
4. Remove silent streaming→blocking fallback in `WorkerAdapter`; raise explicit `LocalWorkerStreamingError` with actionable message.
5. Fix cross-user request cancellation: scope pending requests by `(user_id, worker_id)`.
6. Update `testProvider`/`diagnoseProvider` endpoints to handle `local_worker` scheme.
7. Add reconnect jitter and ping/keepalive to SDK worker.

#### 2.5 Validation
- `tests/test_worker_adapter.py` covers context cap, lost `stream_end`, and fallback behaviour.
- `tests/test_provider_local.py` verifies LM Studio probe.
- SDK worker tests pass.

#### 2.6 LM Studio test plan
1. Load `llama3.1:8b` in LM Studio with context length set to **4096**.
2. Set provider URL to `http://192.168.0.6:1234/v1` in Settings.
3. Run `POST /api/v1/agent/start` with a long task (>4k tokens of primer).
4. Confirm no `400 Context size exceeded`; confirm adapter resized to 4096.
5. Run 10 consecutive short turns; verify no streaming hangs and all complete within 30 s.
6. Abruptly unload the model mid-stream; confirm backend cancels only the current user's request and returns a clear error.

---

### Round 3 — Dialogue Manager and Structured NLU/Entity/Slot Layer

#### 3.1 Understand
CRP Comply has no dialogue manager. State is reconstructed from flat messages. There is no NLU beyond regex triage, no entity extraction, no slot filling, and no dialogue policy for repair/confirmation. This round introduces a lightweight but explicit dialogue layer.

#### 3.2 Research references
- `CONVERSATIONAL_AI_AUDIT.md` §4, §6
- `AGENTIC_AI_AUDIT.md` §3
- Recipe YAMLs in `src/crp_comply/recipes/builtin/`

#### 3.3 Analyse current code
- `src/crp_comply/agent/triage.py` — deterministic intent classifier
- `src/crp_comply/agent/intent_parser.py` — safety-policy parser
- `src/crp_comply/agent/clarifier.py` — suspension/resume persistence
- `src/crp_comply/agent/loop_state.py` — Phase-7 FSM
- `src/crp_comply/agent/loop_runtime.py` — runtime that drives the loop
- `src/crp_comply/api/onboarding.py` — profile extraction

#### 3.4 Implementation
1. Create `src/crp_comply/agent/nlu.py`:
   - `NluEngine` class
   - Intent classification (deterministic fast path + optional lightweight LLM fallback with confidence)
   - Entity extraction: regex gazetteers for regulation/jurisdiction + LLM NER for open-ended entities
   - `SlotBoard` keyed by recipe/task
   - Sentiment signal (keyword + LLM)
   - Basic coreference/ellipsis resolution using last-mentioned entity
2. Create `src/crp_comply/agent/dialogue.py`:
   - `DialogueStateTracker` with slots, dialogue acts, events
   - `DialoguePolicy` rule engine (ask, answer, confirm, repair, finalise, handoff)
   - `FormOrchestrator` to turn recipe `required_inputs` into a state machine
   - `UserModel` merging `OrgProfile`, session context, and slots
3. Wire `NluEngine` and `DialoguePolicy` into `loop_runtime.py` before the reasoning engine.
4. Keep deterministic triage as a fast path.

#### 3.5 Validation
- `tests/test_agent_nlu.py` — intent, entity, slot filling, sentiment, coreference fixtures.
- `tests/test_agent_dialogue.py` — policy transitions, form orchestration, event log replay.
- Triage tests still pass.

#### 3.6 LM Studio test plan
1. Start session with task `"Draft a DPIA for my HR hiring assistant"`.
2. In turn 2, answer `"It processes CVs and scores candidates in the EU"`.
3. Verify `NluEngine` extracts entities: `system_type=HR hiring assistant`, `data=CVs`, `jurisdiction=EU`, `purpose=scoring candidates`.
4. Verify `DialoguePolicy` fills slots and asks the next required question from the GDPR Art. 35 recipe.
5. In turn 3, answer vaguely `"maybe"`; verify policy enters repair and asks a disambiguating question.

---

### Round 4 — Memory Substrate: Adopt CRPv4 `MultiHorizonContext`, `CognitiveStateObject`, `WindowDAG`

#### 4.1 Understand
The agent reconstructs conversation from flat session JSON. CRPv4 provides tiered memory primitives that match the conversational-AI requirement: ephemeral input, session context, and persistent profile. This round migrates session storage to these primitives.

#### 4.2 Research references
- `AGENTIC_AI_AUDIT.md` §2
- `MULTI_TURN_AGENT_AUDIT.md` §3
- `CONVERSATIONAL_AI_AUDIT.md` §6.3.5

#### 4.3 Analyse current code
- `src/crp_comply/api/agent.py` — JSON session file persistence
- `src/crp_comply/agent/crp_integration.py` — `CrpMessageLedger`
- `src/crp_comply/db.py` — user/profile persistence
- `src/crp_comply/agent/loop_runtime.py` — how state is passed between steps

#### 4.4 Implementation
1. Introduce `src/crp_comply/agent/memory.py` as the adapter to CRPv4 primitives.
2. Create `CompliantMemory` class:
   - `input` tier: current turn
   - `context` tier: session slots, dialogue acts, evidence board
   - `profile` tier: `OrgProfile`, persistent preferences
3. Persist `MultiHorizonContext` to `{data_dir}/context/{user_id}/{session_id}.json`.
4. Use `CognitiveStateObject` to represent agent understanding (slots, intent, confidence, pending questions).
5. Use `WindowDAG` for compressed long-horizon recall across sessions.
6. Refactor `api/agent.py` session endpoints to read/write the new memory layer.
7. Provide migration path from old flat JSON sessions.

#### 4.5 Validation
- `tests/test_agent_memory.py` — round-trip context, profile, compressed recall.
- `tests/test_api_agent_sessions.py` — session create/read/continue with new memory.
- Migration test: old flat JSON loads and converts.

#### 4.6 LM Studio test plan
1. Start session, ask `"Classify my system"`, answer classification questions.
2. Start a **new** session with `"What about the UK instead of the EU?"`.
3. Verify `WindowDAG` recalls the prior system's type from the profile tier and only asks jurisdiction-related follow-ups.
4. Verify the agent does not re-ask questions already in `OrgProfile`.

---

### Round 5 — Proxy Multi-Tenancy, Consent, and Safety Control Plane

#### 5.1 Understand
The proxy uses a shared `session_id="proxy"` across all users, mixing audit trails. Consent is granted globally at init, not per-user. All processing records are filed under `SECURITY_SCANNING`. CRPv4 `SafetyControlPlane` is unused. This round fixes these production-critical security/compliance issues.

#### 5.2 Research references
- `CRP_COMPLY_REASSESSMENT.md` §2
- `AGENTIC_AI_AUDIT.md` §3
- `PRODUCT_SECURITY.md` §4

#### 5.3 Analyse current code
- `src/crp_comply/proxy/interceptor.py`
- `src/crp_comply/agent/mcp_permissions.py`
- `src/crp_comply/api/auth.py` — user identification

#### 5.4 Implementation
1. Move `logger = logging.getLogger(__name__)` before the `try: from crp...` import block.
2. Create per-request `ComplianceAuditTrail(session_id=request_id)` and `ProcessingRecordKeeper(session_id=request_id)` inside `intercept()`.
3. Add per-user consent lookup for `SECURITY_SCANNING`; refuse/degrade if not granted.
4. Infer processing purpose from request path/body (proxy chat vs DPIA vs classification) and pass to `ProcessingRecordKeeper`.
5. Replace custom `PolicyEnforcer` with `crp.security.control_plane.SafetyControlPlane` where available; keep fallback.
6. Add fail-fast in production if critical CRP subsystems (PII, injection, provenance) are missing.
7. Rotate any leaked secrets and add log file globs to `.gitignore`.

#### 5.5 Validation
- `tests/test_proxy_tenant_isolation.py` — two users' requests do not share session_id or audit chain.
- `tests/test_proxy_consent.py` — unconsented user is refused/degraded.
- `tests/test_security_primitives.py` updated for `SafetyControlPlane`.

#### 5.6 LM Studio test plan
1. Configure proxy to route to LM Studio.
2. Send two proxied chat requests from two different test users.
3. Verify each request gets a distinct `X-CRP-Comply-Record-ID` and distinct audit file under `data/reports/{user_id}/`.
4. Verify a request without `SECURITY_SCANNING` consent returns 403 or runs in degraded no-scan mode.
5. Verify `ProcessingRecordKeeper` entries are tagged with purpose `CHAT_COMPLETION`, not `SECURITY_SCANNING`.

---
### Round 6 — Phase-7 Loop Hardening: Token Budgets, Continuation, Plan Revision

> **Status:** COMPLETED — validation passed, all acceptance criteria met.

#### 6.1 Understand
The Phase-7 loop has declared budgets and continuation support, but `LoopBudgetMeter.record_tokens()` is never called, continuation is not resumable across API calls, and plan revision is a counter rather than a real replan. This round makes the loop robust.

#### 6.2 Research references
- `MULTI_TURN_AGENT_AUDIT.md` §3
- `LOCAL_AI_ENABLEMENT_AUDIT.md` §4
- `PHASE_7_LANGUAGE_AGENT_LOOP.md`

#### 6.3 Analyse current code
- `src/crp_comply/agent/loop_runtime.py`
- `src/crp_comply/agent/loop_state.py`
- `src/crp_comply/agent/loop_budget.py`
- `src/crp_comply/agent/orchestrator.py` — `continue_truncated_answer()`
- `src/crp_comply/api/agent.py` — `/continue` endpoint

#### 6.4 Implementation
1. Wire `LoopBudgetMeter.record_tokens()` into every LLM call in `loop_runtime.py` and `orchestrator.py`.
2. Enforce per-step and per-session token budgets; emit `loop.budget.exceeded` SSE event with actionable options (switch to local, buy credits, reduce scope).
3. Persist continuation state (partial answer, remaining plan, envelope) in the memory layer so `/continue` can resume across API calls and server restarts.
4. Replace counter-based plan revision with actual replan: on `revise_plan` verdict, re-run `_plan_for()` with failure context.
5. Add wall-clock timeout watchdog (5 min default) that gracefully finalises with what is known.
6. Implement auto-fallback to local LLM on hosted token quota exceeded.

#### 6.5 Validation
- `tests/test_loop_budget.py` — budget recording, exceedance, fallback.
- `tests/test_loop_continuation.py` — resume across API calls.
- `tests/test_loop_replan.py` — real replan on failure context.

#### 6.6 LM Studio test plan
1. Start a session requiring a long synthesis (e.g. Annex IV draft for a high-risk system).
2. Set a deliberately low token budget (e.g. 2k tokens).
3. Verify the loop emits `loop.budget.warning` and then `loop.budget.exceeded`.
4. Choose "continue with local LLM" option; verify continuation resumes from the partial answer using LM Studio.
5. Verify final answer is stitched correctly.

---

### Round 7 — Clarification System Unification, Repair, and Incremental Confirmation

#### 7.1 Understand
There are two clarification stores (`ClarificationNeeded` in session JSON and `AskUserSuspended` in `ClarifierStore`). Clarification is punitive (system prompt tells model to avoid asking) and there is no repair or incremental confirmation. This round unifies and humanises the clarification flow.

#### 7.2 Research references
- `CONVERSATIONAL_AI_AUDIT.md` §4, §6
- `MULTI_TURN_AGENT_AUDIT.md` §3
- `src/crp_comply/recipes/builtin/gdpr_art_35_dpia.yaml`

#### 7.3 Analyse current code
- `src/crp_comply/agent/clarifier.py`
- `src/crp_comply/agent/orchestrator.py` — legacy `request_clarification`
- `src/crp_comply/agent/tools.py` — clarification tools
- `src/crp_comply/api/agent.py` — `/clarify` endpoint
- `frontend/src/pages/v2/AgentChat.tsx` — `ClarifierCard`

#### 7.4 Implementation
1. Unify clarification state into the `DialogueStateTracker` (Round 3).
2. Deprecate legacy `ClarificationNeeded`; migrate `ClarifierStore` to be a persistence adapter for the tracker.
3. Add `DialoguePolicy` rules: ask when confidence < threshold or slot missing; confirm when multiple slots filled; repair when user answer is vague or contradicts prior facts.
4. Add response composer templates for:
   - Incremental confirmation: "Before I continue, I understood X. Is that right?"
   - Repair: "I'm not sure I understood. Did you mean A or B?"
   - Probing: "To determine Y, I need to know Z."
5. Update `AgentChat.tsx` to render confirmation buttons and repair options.
6. Remove the punitive "do not ask unless genuinely missing" instruction from `SYSTEM_PROMPT`; replace with collaborative probing guidance.

#### 7.5 Validation
- `tests/test_agent_clarifier.py` — unified state, resume, answer.
- `tests/test_agent_dialogue.py` — confirm/repair transitions.
- Frontend: clarify/confirm/repair interaction tests.

#### 7.6 LM Studio test plan
1. Start session: `"Draft a DPIA"`.
2. Agent asks: "Does the system process personal data?"
3. Answer: `"yes, employee CVs"`.
4. Verify agent confirms: "I understood the system processes employee CVs. Is that correct?" with Yes/No buttons.
5. Click No; verify agent enters repair: "Did you mean the system processes other data, or that it does not process personal data?"
6. Continue and complete the DPIA draft.

---

### Round 8 — Citation Validation and Evidence Grounding

#### 8.1 Understand
The system demands `[chunk_id]` citations and the `Reflector` checks for uncited claim-like sentences, but there is no final-answer validator that verifies a cited `chunk_id` was actually returned by a tool. Hallucinated or mismatched citations can reach the user.

#### 8.2 Research references
- `MULTI_TURN_AGENT_AUDIT.md` §3
- `CONVERSATIONAL_AI_AUDIT.md` §4.5
- `AGENTIC_AI_AUDIT.md` §3

#### 8.3 Analyse current code
- `src/crp_comply/agent/reflector.py`
- `src/crp_comply/agent/orchestrator.py` — final answer generation
- `src/crp_comply/agent/tools.py` — `query_regulation` and web tools
- `src/crp_comply/agent/crp_integration.py` — envelope packing

#### 8.4 Implementation
1. Create `src/crp_comply/agent/citation_validator.py`:
   - Build a registry of valid citation IDs from tool results in the current session (chunk_id, fact_id, web URL, CKF fact_id).
   - Extract `[...]` citation markers from final text.
   - Flag invalid citations and either strip them or retry the answer generation.
   - Validate surrogate chunks are correctly marked.
2. Wire validator into `orchestrator.py` and `loop_runtime.py` before final answer is returned/streamed.
3. Enhance `Reflector` to receive actual confidence values from the runtime.
4. Add `loop.citation.invalid` SSE event so the UI can show a warning.
5. Add per-paragraph provenance tagging for long deliverables.

#### 8.5 Validation
- `tests/test_citation_validator.py` — valid, invalid, missing, surrogate cases.
- `tests/test_reflector.py` — confidence-aware verdicts.
- Eval case: agent given a tool result with chunk `A`; final answer citing `B` must be flagged.

#### 8.6 LM Studio test plan
1. Start session: `"What does EU AI Act Art. 6 say about high-risk systems?"`.
2. Agent uses `query_regulation` and returns chunks `eu_ai_act_art_6_001`, `eu_ai_act_art_6_002`.
3. Manually introduce a final answer that cites `eu_ai_act_art_6_999`.
4. Verify validator flags invalid citation and retries or emits `loop.citation.invalid`.
5. Verify final streamed answer only contains valid chunk IDs.

---

### Round 9 — Web Search Sidecars and Feedback Loops

#### 9.1 Understand
Web search is architected but not fully operational. SearXNG plugins with intent-aware routing and feedback-driven reranker are disabled. Agent-side feedback to the sidecar is unwired or crashes. Web results are transient.

#### 9.2 Research references
- `MULTI_TURN_AGENT_AUDIT.md` §3
- `docs/RAILWAY_SEARCH_SIDECAR.md`
- `services/crp-comply-search/`, `services/crp-comply-searxng/`

#### 9.3 Analyse current code
- `src/crp_comply/agent/web_client.py`
- `src/crp_comply/sidecar_client.py`
- `src/crp_comply/agent/loop_runtime.py` — web feedback firing
- `services/crp-comply-search/main.py`
- `services/crp-comply-searxng/`

#### 9.4 Implementation
1. Enable `allow_feedback=True` in sidecar client configuration.
2. Fix agent-side feedback wiring so `web_fb.feedback()` does not crash.
3. Finish `services/crp-comply-searxng/` intelligence layer: query expander, cross-encoder reranker, chunk citer.
4. Add new tools: `vendor_profile`, `compare_documents`.
5. Index web results into CKF so the same source can be retrieved in later turns.
6. Wire feedback-driven reranker learning loop.
7. Add trust-tier YAML profiles and UI pills for web results.

#### 9.5 Validation
- `tests/test_web_feedback.py` — feedback round-trip.
- `tests/test_sidecar_search.py` — intent-aware routing.
- `services/crp-comply-searxng/tests/` pass.

#### 9.6 LM Studio test plan
1. Start session: `"What are the latest EDPB guidelines on AI and GDPR?"`.
2. Verify agent triggers web search and receives results with trust-tier pills.
3. Verify `loop.web.result` events include source URL and fetch time.
4. In a follow-up turn, ask "Summarise the same source"; verify CKF recall returns the indexed web result.
5. Submit feedback "useful" on a web result; verify sidecar reranker updates.

---

### Round 10 — Multi-Turn State, Reflection, and Research Phases

#### 10.1 Understand
The loop is generic ReAct; there are no explicit research → analysis → synthesis → citation phases. The Reflector runs per step but does not guarantee cross-turn coherence. This round structures long-form reasoning.

#### 10.2 Research references
- `MULTI_TURN_AGENT_AUDIT.md` §3
- `PHASE_7_LANGUAGE_AGENT_LOOP.md`
- `LLM_INTELLIGENCE_DESIGN.md`

#### 10.3 Analyse current code
- `src/crp_comply/agent/loop_runtime.py` — `_plan_for()`, `_execute_step()`, `_stitch_outputs()`
- `src/crp_comply/agent/reflector.py`
- `src/crp_comply/agent/orchestrator.py` — evidence priming

#### 10.4 Implementation
1. Introduce explicit phase types: `RESEARCH`, `ANALYSIS`, `SYNTHESIS`, `CITATION`, `REVIEW`.
2. Extend `PlanStep` with `phase` and `success_predicate`.
3. Refactor `_plan_for()` to generate phase-aware plans for complex tasks.
4. Add `EvidenceBoard` working memory that accumulates facts across research steps.
5. Enhance `Reflector` to evaluate phase outcomes (coverage, consistency, citation density).
6. Add `loop.phase.complete` SSE events so the UI shows progress.
7. Ensure cross-turn coherence by priming each step with the `EvidenceBoard` and `CognitiveStateObject`.

#### 10.5 Validation
- `tests/test_loop_phases.py` — phase plan generation and transitions.
- `tests/test_evidence_board.py` — fact accumulation and retrieval.
- Eval case: Annex IV draft must show research → analysis → synthesis → citation phases.

#### 10.6 LM Studio test plan
1. Start session: `"Draft a full Annex IV technical file for a high-risk credit scoring AI"`.
2. Verify the plan includes explicit phases: research (regulation query), analysis (risk class), synthesis (draft sections), citation (validate chunk IDs), review.
3. Verify `loop.phase.complete` events are streamed after each phase.
4. Verify final document cites only valid chunks and covers Annex IV required sections.

---
### Round 11 — Frontend v1/v2 Collapse: Single Draft Surface

#### 11.1 Understand
The frontend currently has two parallel drafting surfaces: `Workspace.tsx` (legacy) and `AgentChat.tsx` (Phase-7). This confuses users and duplicates state. The redesign specifies a single `Draft` surface driven by `/api/v1/drafts`.

#### 11.2 Research references
- `UI_UX_REDESIGN.md` §9, §11
- `COMPLIANCE_MODEL_GAPS.md` B1
- `REDESIGN_STRATEGY.md` §6

#### 11.3 Analyse current code
- `frontend/src/pages/v2/Draft.tsx`
- `frontend/src/pages/v2/Workspace.tsx`
- `frontend/src/pages/v2/AgentChat.tsx`
- `frontend/src/App.tsx` — route definitions
- `src/crp_comply/api/draft_sessions.py` — drafts bridge

#### 11.4 Implementation
1. Make `Draft.tsx` the canonical drafting surface.
2. Remove or archive `Workspace.tsx` routes; redirect `/app/workspace/*` → `/app/draft?mode=chat&session=...`.
3. Move reusable chat components from `AgentChat.tsx` into `components/agent/`: `ClarifierCard`, `ReasoningTape`, `CitationChip`.
4. Update `Draft.tsx` to consume the Phase-7 SSE stream and the new `DialogueStateTracker` state.
5. Wire "Save to vault" to `POST /drafts/{id}/report`.
6. Clean up `App.tsx` route tree and remove dev-only routes (`ReasoningTapePreview`, `GlobalAgentPanel`) from production builds.

#### 11.5 Validation
- `npx tsc -b` clean.
- Vitest/Playwright: user can start a draft, see streaming, answer a clarification, and save to vault.
- No broken links from old `/app/workspace` URLs.

#### 11.6 LM Studio test plan
1. Navigate to `/app/draft`.
2. Enter task in composer and submit.
3. Verify streaming reasoning tape appears.
4. When a clarification is asked, answer via the inline card.
5. Click "Save to vault"; verify report appears in `/app/vault`.
6. Repeat with LM Studio as the configured provider.

---

### Round 12 — Onboarding and Cross-Turn User Model Integration

#### 12.1 Understand
Onboarding captures a rich `OrgProfile`, but it is not injected into the agent chat loop. The agent re-asks questions that the onboarding already answered. This round makes the user model conversationally active.

#### 12.2 Research references
- `CONVERSATIONAL_AI_AUDIT.md` §4.1, §6.3.3
- `UI_UX_REDESIGN.md` §11.3
- `src/crp_comply/api/onboarding.py`

#### 12.3 Analyse current code
- `frontend/src/pages/v2/Onboarding.tsx`
- `src/crp_comply/api/onboarding.py`
- `src/crp_comply/db.py` — profile storage
- `src/crp_comply/agent/dialogue.py` (Round 3)

#### 12.4 Implementation
1. Promote `OrgProfile` fields into the `UserModel` (Round 3) at session start.
2. Pre-fill `SlotBoard` with onboarding answers so the agent skips already-known questions.
3. Add a "What you owe" panel in onboarding/on dashboard that recommends recipes based on profile.
4. Expose `UserModel` in the agent context panel so users see what the agent knows.
5. Allow users to edit `UserModel` from Settings; changes apply to new sessions.
6. Add `recommend_recipes()` backend endpoint used by onboarding and dashboard.

#### 12.5 Validation
- `tests/test_onboarding.py` — profile extraction and recommendation.
- `tests/test_user_model.py` — profile → slot pre-fill.
- Frontend: onboarding completion leads to dashboard with recommended recipes.

#### 12.6 LM Studio test plan
1. Complete onboarding as a "Provider of high-risk biometric identification in EU".
2. Start a new agent session: `"What do I need to comply with?"`.
3. Verify agent does not ask "Are you a provider or deployer?" or "What is your jurisdiction?" because onboarding answered them.
4. Verify agent recommends Annex IV, DPIA, and human oversight documentation.

---

### Round 13 — Settings Refactor and LLM Connection UX

#### 13.1 Understand
Settings is a 1,465-line monolith. The LLM connection flow is buried and does not lead with the local-first differentiator. The business analysis recommends making "Run locally — free & private" the primary CTA.

#### 13.2 Research references
- `UI_UX_REDESIGN.md` §9.3
- `BUSINESS_MODEL_LLM_UPSELL.md` §3
- `docs/LOCAL_LLM_GUIDE.md`
- `docs/BYOK_MODES.md`

#### 13.3 Analyse current code
- `frontend/src/pages/Settings.tsx`
- `src/crp_comply/api/provider.py`
- `scripts/install_local_llm.sh`, `.ps1`

#### 13.4 Implementation
1. Split `Settings.tsx` into sub-components: `SubscriptionPanel`, `CreditPanel`, `StoragePanel`, `LlmPanel`, `ApiKeysPanel`, `IntegrationsPanel`.
2. Redesign `LlmPanel`:
   - Primary CTA: "Run locally (recommended, free, private)" with hardware-aware model picker.
   - Secondary CTAs: BYOK cloud key, managed tokens.
   - Inline model detection from LM Studio/Ollama.
   - Test connection button with clear diagnostics.
3. Surface provider status and last error in UI.
4. Add "0 bytes leave your network" privacy badge when local provider is active.
5. Update `install_local_llm.sh` to match current SDK/worker CLI.
6. Add server-side endpoint to detect loaded context length from LM Studio.

#### 13.5 Validation
- `npx tsc -b` clean.
- Playwright: settings page loads, local LLM CTA visible, provider test returns success.
- Backend tests for context-length detection.

#### 13.6 LM Studio test plan
1. Open `/app/settings`.
2. Click "Run locally".
3. Enter `http://192.168.0.6:1234` and click "Detect".
4. Verify UI shows loaded model, context length, and "0 bytes leave your network" badge.
5. Click "Test connection"; verify success toast.
6. Send one agent turn; verify request routes to LM Studio.

---

### Round 14 — Recipe Library Completion and Quality

#### 14.1 Understand
Recipe coverage is broad but quality varies. Some v1 must-haves are disputed across documents. Recipes are single-shot form fills, but real compliance interviews require multi-sitting, multi-stakeholder input. The form orchestrator from Round 3 enables structured recipe execution.

#### 14.2 Research references
- `RECIPE_COVERAGE_TRACKER.md`
- `COMPLIANCE_MODEL_GAPS.md` B3
- `STRATEGIC_REASSESSMENT.md` §1
- Recipe YAMLs in `src/crp_comply/recipes/builtin/`

#### 14.3 Analyse current code
- `src/crp_comply/recipes/loader.py`
- `src/crp_comply/recipes/executor.py`
- `src/crp_comply/recipes/human_inputs.py`
- `src/crp_comply/recipes/derivation.py`
- `frontend/src/pages/v2/RecipeLibrary.tsx`

#### 14.4 Implementation
1. Physically verify all v1 must-have recipes exist and load: FRIA, SoA, ISO 42001 AI risk assessment, NIST AI RMF Profile.
2. Add missing recipes from `STRATEGIC_REASSESSMENT.md`: `context_analysis.md`, `ai_policy.md`, `ai_strategy.md`, risk register, risk treatment plan, AI impact assessment, competence matrix, documented information register, internal audit programme, management review minutes, CAPA register.
3. Integrate recipes with `FormOrchestrator` (Round 3) for multi-turn interviews.
4. Add save/resume for partially completed recipe interviews.
5. Improve recipe library UI: filter by framework, risk class, actor role; show tier locks.
6. Add recipe quality tests that assert each recipe declares required inputs, output artefacts, and citations.

#### 14.5 Validation
- `tests/test_recipes_load.py` — all builtin recipes load and validate schema.
- `tests/test_recipe_interview.py` — multi-turn recipe interview save/resume.
- `tests/test_recipe_coverage.py` — v1 must-haves present.

#### 14.6 LM Studio test plan
1. Navigate to `/app/recipes`.
2. Select "GDPR Art. 35 DPIA".
3. Start interview; answer a few questions.
4. Reload page; verify interview resumes at the same question.
5. Complete interview; verify DPIA draft is generated and cites GDPR articles.
6. Repeat with "EU AI Act Art. 27 FRIA" if available.

---

### Round 15 — Evidence Pack Viewer, Audit Log, and Provenance UI

#### 15.1 Understand
Evidence packs are generated and signed, but the UI for viewing them is fragmented. Audit logs and provenance pills are not first-class. Regulator-ready bundles need a clear viewer.

#### 15.2 Research references
- `UI_UX_REDESIGN.md` §Wave D
- `COMPLIANCE_MODEL_GAPS.md` B13, B15, B17
- `PRODUCTION_READINESS.md` §1

#### 15.3 Analyse current code
- `src/crp_comply/core.py` — evidence pack generation
- `src/crp_comply/api/reports.py`
- `src/crp_comply/recipes/derivation.py` — `DerivationManifest`
- `frontend/src/pages/v2/Evidence.tsx`
- `frontend/src/pages/v2/Vault.tsx`
- `frontend/src/components/ReasoningTape.tsx`

#### 15.4 Implementation
1. Build `/app/evidence` tree view: regulations → artefacts → versions → hash/signer/status.
2. Add bulk export (ZIP, PDF, signed bundle) actions.
3. Add `/app/audit-log` append-only timeline with signed-provenance viewer.
4. Render provenance pills in report cards (model, prompt hash, citation IDs).
5. Add live staleness badge on report cards when corpus has changed.
6. Add per-user CKF export endpoint for GDPR Art. 20 portability.
7. Migrate evidence signing from HMAC to Ed25519 with public key at `/.well-known/crp-comply-evidence-key.pub`.

#### 15.5 Validation
- `tests/test_evidence_pack.py` — generation, signing, verification.
- `tests/test_audit_log.py` — immutable timeline.
- Frontend: evidence viewer renders tree, export works.

#### 15.6 LM Studio test plan
1. Generate an Annex IV draft via agent using LM Studio.
2. Go to `/app/evidence`.
3. Verify the new report appears with model info, prompt hash, and citation pill.
4. Click "Export signed bundle"; verify ZIP contains report + derivation manifest + signature.
5. Verify signature using the well-known public key endpoint.
6. Change corpus mock timestamp to simulate regulation update; verify staleness badge appears.

---
### Round 16 — Stripe Billing Hardening and Pricing Alignment

#### 16.1 Understand
The Stripe integration has operational gaps: pricing mismatch across docs/code, no webhook idempotency, no dead-letter reconciliation, failed payment never revokes access, immediate downgrade on cancellation, and frontend assumes success before server confirms.

#### 16.2 Research references
- `PAYMENT_WORKFLOW_ANALYSIS.md`
- `STRIPE_MONETISATION.md`
- `MARKETING.md`
- `REDESIGN_STRATEGY.md` §2

#### 16.3 Analyse current code
- `src/crp_comply/api/billing.py` or stripe module
- `frontend/src/pages/Pricing.tsx`
- `frontend/src/pages/Settings.tsx` — subscription section
- `.env.example` — Stripe price IDs

#### 16.4 Implementation
1. Reconcile canonical price table across `STRIPE_MONETISATION.md`, `Pricing.tsx`, backend `PRICE_TO_TIER`, and `.env.example`.
2. Implement webhook idempotency store (`stripe_event.id` dedupe) and idempotent credit grants.
3. Add `past_due` state handling on `invoice.payment_failed` with soft-limiting.
4. Add nightly Stripe ↔ DB reconciliation job + webhook receipt audit table.
5. Honour `cancel_at_period_end` instead of immediate downgrade.
6. Update success page to poll `GET /api/v1/billing/status` before showing "active".
7. Send post-activation onboarding email.
8. Remove "98% gross margin" and "managed LLM tokens" overclaim from marketing.

#### 16.5 Validation
- `tests/test_billing_webhooks.py` — idempotency, dunning, cancellation.
- `tests/test_billing_reconciliation.py` — nightly job.
- Playwright: checkout success page polls and shows correct tier.

#### 16.6 LM Studio test plan
1. Complete a Stripe checkout for Starter tier (test mode).
2. Verify backend records entitlement and `/api/v1/billing/status` returns Starter.
3. Redeliver the same `checkout.session.completed` webhook; verify no double grant.
4. Simulate `invoice.payment_failed`; verify user enters `past_due` and agent endpoints return 402 with upgrade prompt.
5. Cancel subscription; verify access continues until period end.

---

### Round 17 — Tier-Feature Matrix, Auth Coverage, and Quota Visibility

#### 17.1 Understand
The `SDK_FEATURE_MATRIX` exists but lacks test coverage asserting every endpoint denies out-of-tier access. Users cannot see current tier or quota usage in the UI.

#### 17.2 Research references
- `COMPLIANCE_MODEL_GAPS.md` B11
- `UI_UX_REDESIGN.md` §6.2
- `PRODUCT_SECURITY.md` §1

#### 17.3 Analyse current code
- `src/crp_comply/api/deps.py` — `_require_feature_or_403`, `meter_call`
- `src/crp_comply/api/sdk.py` — `SDK_FEATURE_MATRIX`
- `src/crp_comply/api/usage.py`
- `frontend/src/pages/Settings.tsx`

#### 17.4 Implementation
1. Add fuzz coverage in `tests/test_auth.py` walking every endpoint × every tier.
2. Add `GET /api/v1/billing/status` implementation if missing; include current tier, quota used/remaining, overage, renewal date.
3. Add tier badge and quota progress bar to app shell/header.
4. Add billing action required banner subscribing to `invoice.payment_action_required` notifications.
5. Add per-minute token bucket rate limit beyond monthly quota.
6. Ensure all `/agent/*` endpoints correctly gate on `agent_intelligence` feature.

#### 17.5 Validation
- `tests/test_auth.py` endpoint × tier matrix passes.
- `tests/test_rate_limit.py` — token bucket.
- Frontend: badge and banner render correctly.

#### 17.6 LM Studio test plan
1. Create a Free-tier test user.
2. Exhaust 100-call quota via proxy calls to LM Studio.
3. Verify 402 response with quota-exceeded message.
4. Verify UI shows "100/100 calls used" badge.
5. Upgrade to Starter via Stripe test; verify quota resets and agent endpoints work.

---

### Round 18 — Evaluation Suite Expansion and CI/CD Hardening

#### 18.1 Understand
The evaluation suite has only 13 deterministic cases; target is ≥20 covering EU AI Act, GDPR, ISO 42001, NIST AI RMF. CI lacks live-LLM smoke tests and frontend Vitest coverage.

#### 18.2 Research references
- `COMPLIANCE_MODEL_GAPS.md` B2
- `PRODUCTION_READINESS.md` §1
- `CRP_AUDIT_6_GAPS_AND_FIXES.md`

#### 18.3 Analyse current code
- `tests/` directory
- `.github/workflows/ci.yml`
- `src/crp_comply/agent/eval.py` if exists

#### 18.4 Implementation
1. Expand eval suite to 20+ YAML cases across frameworks.
2. Add CI gate: eval pass rate ≥95%.
3. Add optional live-LLM smoke test job against LM Studio (`http://192.168.0.6:1234`) in CI.
4. Add frontend Vitest tests for critical components (Onboarding, Draft, Settings panels).
5. Add `pip-audit` and `bandit` to CI if not already present.
6. Harden Live Regulation CI: replace broad `contents: write` with deploy key scoped to `corpus/**`.
7. Add scraper rate-limit delays to avoid tripping regulator WAFs.

#### 18.5 Validation
- `pytest tests/eval/` passes at ≥95%.
- CI green on Python 3.10–3.13 matrix.
- Vitest passes for added frontend components.

#### 18.6 LM Studio test plan
1. Run eval harness locally with LM Studio provider.
2. Verify all 20 cases complete and score ≥95%.
3. Inspect failed cases; adjust prompts or tool thresholds.
4. Run live-LLM smoke test in CI mode against LM Studio.

---

### Round 19 — Continuous Compliance Engine

#### 19.1 Understand
The continuous compliance engine has observation and evidence upload, but the "decide" (compliance graph + `compliance_audit()`) and "explain" (narrated gap report renderer) phases are incomplete.

#### 19.2 Research references
- `CONTINUOUS_COMPLIANCE.md`
- `COMPLIANCE_MODEL_ANALYSIS.md` §4.4
- `STRATEGIC_REASSESSMENT.md` §1

#### 19.3 Analyse current code
- `src/crp_comply/programme/lifecycle.py`
- `src/crp_comply/compliance_graph.py` if exists
- `src/crp_comply/scheduler.py` if exists

#### 19.4 Implementation
1. Implement verdict-rule graph: obligations → evidence → verdict (compliant/partial/non-compliant/not-assessed).
2. Implement `compliance_audit()` scheduler that re-runs binders on a schedule and on corpus change.
3. Build narrated gap report renderer: human-readable explanation of each non-compliant obligation with remediation path.
4. Integrate with evidence substrate query layer so verdicts are evidence-backed.
5. Add notification dispatcher for re-review alerts.
6. Add remediation ticket creation with owner, due date, and evidence checklist.
7. Expose continuous compliance dashboard in frontend.

#### 19.5 Validation
- `tests/test_compliance_graph.py` — rule evaluation.
- `tests/test_continuous_audit.py` — schedule trigger, gap report.
- Frontend: dashboard shows compliance drift.

#### 19.6 LM Studio test plan
1. Create a system profile and generate an initial evidence pack.
2. Simulate a corpus change that affects one obligation.
3. Trigger continuous audit.
4. Verify notification appears and gap report identifies the changed obligation.
5. Verify remediation ticket is created with due date.

---

### Round 20 — Documentation, Marketing Copy, and Launch Readiness

#### 20.1 Understand
The product currently oversells managed LLM capabilities and buries the local-first differentiator. Documentation and legal templates for Enterprise are incomplete. Launch readiness requires a final sweep across copy, docs, and operational runbooks.

#### 20.2 Research references
- `BUSINESS_MODEL_LLM_UPSELL.md`
- `REDESIGN_STRATEGY.md` §6
- `ENTERPRISE_DELIVERY_PLAYBOOK.md`
- `PRODUCTION_READINESS.md` §6
- `USER_ACTIONS_REQUIRED.md`

#### 20.3 Analyse current code
- `README.md`
- `MARKETING.md`
- `frontend/src/pages/Landing.tsx`
- `frontend/src/pages/Pricing.tsx`
- `frontend/src/pages/Product.tsx`
- `docs/`

#### 20.4 Implementation
1. Rewrite `README.md` lead: "CRP Comply is the compliance layer for AI you already run. The model is yours. The compliance is ours."
2. Update `Landing.tsx`, `Pricing.tsx`, `Product.tsx` to lead with local-first, privacy, and $0 inference.
3. Remove "98% gross margin" and "managed LLM tokens" overclaims.
4. Add "0 bytes leave your network" privacy badge to pricing, product, and audit report output.
5. Reconcile Stripe price IDs and marketing prices.
6. Build Enterprise delivery templates under `enterprise/templates/` (NDA, DPA, MSA, SOW).
7. Complete launch checklist from `PRODUCTION_READINESS.md` §6 and `USER_ACTIONS_REQUIRED.md`.
8. Perform backup/restore drill in production-like environment and record RTO.
9. Update `AGENTS.md` with new architecture and testing conventions.
10. Publish updated docs and run final end-to-end smoke test.

#### 20.5 Validation
- Marketing copy review passes: no claim to host/provide a frontier model.
- Enterprise templates present and reviewed.
- Launch checklist complete.
- Backup/restore drill documented.

#### 20.6 LM Studio test plan
1. Run full end-to-end smoke test:
   - Sign up → complete onboarding → connect local LM Studio → run risk classifier → start DPIA interview → generate report → export evidence pack.
2. Verify every step completes without errors.
3. Verify all LLM calls route to `http://192.168.0.6:1234`.
4. Verify no data leaves the network (privacy badge active).
5. Verify exported evidence pack is signed and verifiable.

---
## 5. Cross-Reference Matrix: Research Documents → Rounds

This matrix ensures every major research document and skill is addressed by at least one round.

| Document / Skill | Rounds that consume it |
|------------------|------------------------|
| `AGENTIC_AI_AUDIT.md` | R1, R2, R4, R5, R8, R18 |
| `LOCAL_AI_ENABLEMENT_AUDIT.md` | R2, R6, R13, R18, R20 |
| `MULTI_TURN_AGENT_AUDIT.md` | R1, R3, R4, R6, R7, R8, R10, R18 |
| `CONVERSATIONAL_AI_AUDIT.md` | R3, R4, R7, R12, R14, R20 |
| `STRATEGIC_REASSESSMENT.md` | R5, R14, R19, R20 |
| `CRP_COMPLY_REASSESSMENT.md` | R1, R5, R18 |
| `CRP_NATIVE_DISPATCH_ANALYSIS.md` | R1 |
| `CRP_USAGE_ASSESSMENT.md` | R1, R4 |
| `PRODUCTION_READINESS.md` | R5, R15, R18, R20 |
| `PRODUCT_SECURITY.md` | R5, R17, R18 |
| `COMPLIANCE_MODEL_GAPS.md` | R5, R10, R11, R14, R17, R18, R19 |
| `COMPLIANCE_MODEL_ANALYSIS.md` | R10, R14, R15, R19 |
| `CONTINUOUS_COMPLIANCE.md` | R19 |
| `UI_UX_REDESIGN.md` | R11, R12, R13, R15, R17 |
| `REDESIGN_STRATEGY.md` | R11, R16, R20 |
| `USER_ACTIONS_REQUIRED.md` | R5, R13, R17, R20 |
| `HANDOFF.md` | R20 |
| `STRIPE_MONETISATION.md` | R16, R17 |
| `MARKETING.md` | R16, R20 |
| `ENTERPRISE_DELIVERY_PLAYBOOK.md` | R20 |
| `docs/PAYMENT_WORKFLOW_ANALYSIS.md` | R16 |
| `docs/BUSINESS_MODEL_LLM_UPSELL.md` | R13, R16, R20 |
| `docs/CRP_MONETISATION_PLAN.md` | R16 |
| `LLM_INTELLIGENCE_DESIGN.md` | R1, R10 |
| `PHASE_7_LANGUAGE_AGENT_LOOP.md` | R6, R10 |
| `PHASE_7_STATUS.md` | R6, R9, R10 |
| `PHASE_6_MULTITURN_AND_CRP_ON_DATA.md` | R4, R6 |
| `docs/LOCAL_LLM_GUIDE.md` | R2, R13 |
| `docs/BYOK_MODES.md` | R2, R13 |
| `docs/LLM_HOSTING.md` | R2, R13, R16 |
| `docs/BUDGET_LLM_GUIDANCE.md` | R6 |
| `CRP_AUDIT.md` | R1, R2 |
| `CRP_AUDIT_2.md` | R1, R5 |
| `CRP_AUDIT_3.md` | R2, R5 |
| `CRP_AUDIT_4.md` | R5, R8 |
| `CRP_AUDIT_5_GAPS_AND_FIXES.md` | R5, R8, R18 |
| `CRP_AUDIT_6_GAPS_AND_FIXES.md` | R2, R5, R18 |
| `RECIPE_COVERAGE_TRACKER.md` | R14 |
| `docs/BACKUP_AND_RESTORE.md` | R20 |
| `docs/VOLUME_PERSISTENCE.md` | R20 |
| `docs/RAILWAY_SEARCH_SIDECAR.md` | R9 |
| `use-railway` skill | R9, R20 |
| `skill-creator` skill | Skill authoring |

---

## 6. Definition of Done for Each Round

A round is complete when **all** of the following are true:

1. **Implementation merged.** All code changes are committed and the working tree is clean.
2. **Tests green.** New tests pass; existing tests still pass; no regressions.
3. **Static analysis clean.** `ruff`, `bandit`, `pip-audit` (where applicable), and frontend TypeScript compiler pass.
4. **LM Studio smoke test passed.** The round's LM Studio test plan executed successfully against `http://192.168.0.6:1234`.
5. **Documentation updated.** `AGENTS.md`, `README.md`, or relevant docs reflect behaviour changes.
6. **Skill checklist updated.** The skill file's round checklist is marked complete.

---

## 7. Regression Test Strategy

After every round, run the following regression suite:

```bash
# Backend
cd /c/Users/User/Desktop/crp-comply
python -m pytest tests/ -q --tb=short
ruff check src tests
bandit -r src
pip-audit

# Frontend
cd frontend
npm run typecheck
npm run lint
npm run test:unit

# Live-LLM smoke
cd /c/Users/User/Desktop/crp-comply
python -m pytest tests/smoke/test_lm_studio.py -v
```

If any regression suite fails, the round is not complete.

---

## 8. LM Studio Test Harness Reference

All LM Studio tests assume the server is running at `http://192.168.0.6:1234` with an OpenAI-compatible endpoint.

### Quick health check

```bash
curl http://192.168.0.6:1234/v1/models
```

### Sample chat completion

```bash
curl http://192.168.0.6:1234/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "loaded-model-name",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 100
  }'
```

### Native context-length query

```bash
curl http://192.168.0.6:1234/api/v1/models
```

Look for `loaded_context_length` in the response.

### Environment variables for local testing

```bash
export CRP_COMPLY_LLM_BASE_URL=http://192.168.0.6:1234/v1
export CRP_COMPLY_LLM_API_KEY=lm-studio-no-key-needed
export CRP_COMPLY_LLM_MODEL=loaded-model-name
```

---

## 9. Final Review Checklist

Before this roadmap is considered final:

- [ ] All 20 rounds have Understand/Analyse/Implement/Validate/LM Studio Test sections.
- [ ] Every research document in the inventory is referenced.
- [ ] Every skill (`use-railway`, `skill-creator`) is referenced or used.
- [ ] Every problem inventory item maps to at least one round.
- [ ] LM Studio endpoint details are correct (`http://192.168.0.6:1234`).
- [ ] The companion skill file exists and matches this roadmap.
- [ ] A human review has confirmed the round ordering makes sense.

---

*End of roadmap.*
