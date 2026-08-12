# CRP Comply — CRPv5 Upgrade Report

> **Status:** Proposed · **Date:** 2026-07-01 · **Target protocol:** `crprotocol >= 5.x`
> **Author:** CRP core team · **Companion audits (existing, in this repo):**
> `MASTER_IMPLEMENTATION_ROADMAP.md`, `CRP_AUDIT_6_GAPS_AND_FIXES.md`,
> `AGENTIC_AI_AUDIT.md`, `MULTI_TURN_AGENT_AUDIT.md`, `CONVERSATIONAL_AI_AUDIT.md`,
> `CRP_COMPLY_REASSESSMENT.md`, `CRP_NATIVE_DISPATCH_ANALYSIS.md`.

---

## 0. Executive summary

CRP Comply today runs on a **bespoke CRPv4 ReAct loop** and is dependency-pinned to
`crprotocol[full]>=4.2.1,<5`. It re-implements — in application code — most of what
the **CRPv5 positioned agentic loop now provides natively**: operation planning,
tool orchestration, output continuation, clarification, PII/injection scanning,
CKF packing, and a message/state ledger.

CRPv5 (shipped in `crprotocol` 5.0.0 and the in-flight 5.1 line) adds the pieces the
existing Comply audits repeatedly flag as fragile:

- **`run_positioned` / `dispatch_positioned`** — the real positioned tool loop
  (SPEC-049/050): classify → position one operation at a time with only the 1–3
  tools it needs → typed CSO observations → bounded window.
- **Multi-turn state relay** (`prior_cso`) — verified fact carry-forward across turns.
- **Output continuation** (`max_continuation_windows`) — CompletionDetector-gated,
  validated to 10 windows / ~3.7k words on a local 8B.
- **Safety surface** — preventive-safety halts, oversight-gated capabilities, and
  the CLARIFY checkpoint bridge (verified 9/9 in `safety_checkpoint_test.py`).

**Goal of this upgrade:** retire the bespoke loop and re-base Comply on the CRPv5
positioned loop, with AI-safety and checkpoints as first-class, so Comply becomes a
**thin, correct CRPv5 consumer** instead of a partial re-implementation of the protocol.

---

## 1. Current-state audit (what Comply does today)

| Area | Today (CRPv4, bespoke) | File(s) |
|------|------------------------|---------|
| Dispatch | `CrpDispatcher.dispatch_turn/dispatch_native` wrap the v4 client; manual envelope budgeting | `agent/crp_dispatch.py` |
| Agent loop | Hand-rolled plan → step → stitch → clarify ReAct loop | `agent/loop_runtime.py` (`_plan_for`, `_stitch_outputs`, `_build_clarification_question`) |
| Orchestration | `ComplianceAgent.run` with `_run_via_crp_dispatch`, window continuation, tool-fact recording | `agent/orchestrator.py` |
| Protocol glue | Re-implements PII redaction, injection scan, MMR rerank, envelope packing, continuation, fact extraction, CKF, **and a bespoke `CrpMessageLedger`** | `agent/crp_integration.py` |
| Safety | `PolicyEnforcer` per session/tenant | `api/safety.py`, `api/checkpoint_routes.py` |
| Continuation | `continue_truncated` / `continue_truncated_answer` (manual) | `agent/crp_dispatch.py`, `agent/crp_integration.py` |

**Key problems (consistent with the existing audits):**
1. **Protocol re-implementation drift.** `crp_integration.py` re-implements CSO-like
   ledgering, continuation, and safety scanning that now exist — tested — in the
   protocol. This is the single biggest source of the "fragmented CRPv4" fragility.
2. **No positioned tool loop.** Tools are injected/looped in app code, not positioned
   by the protocol — so the model sees more than it should and windows grow.
3. **Multi-turn is bespoke.** `MULTI_TURN_AGENT_AUDIT.md` documents the hand-rolled
   ledger; CRPv5 `prior_cso` replaces it with a verified relay.
4. **Safety is a separate enforcer**, not the protocol's preventive-halt +
   oversight-checkpoint surface — so AI-safety coverage is inconsistent with the spec.
5. **Pinned `<5`** — cannot consume any CRPv5 capability until the bump.

---

## 2. Target architecture (CRPv5-native Comply)

```
HTTP request → ComplianceAgent.run
  → client.dispatch_positioned(
        user_request,
        fabric = <compliance TCF: corpus_search, web_search, regulation_lookup, evidence_write…>,
        executor = <compliance tool impls>,
        profile = CAPABLE_LOCAL | FRONTIER (per tenant model),
        policy = <PolicyContext from tenant safety profile>,
        oversight_required = {DESTRUCTIVE, MUTATING},     # gates evidence writes / actions
        clarify_handler = <checkpoint_inbox bridge>,       # human-in-the-loop
        prior_cso = <session CSO>,                          # multi-turn
        max_continuation_windows = N,                       # long compliance reports
    )
  → PositionedResult.text / .cso / .event_stream / .headers
  → evidence + audit from the CSO event stream (already HMAC-chained)
```

- The **CSO replaces `CrpMessageLedger`**; its `event_stream` replaces bespoke tracing.
- **Checkpoints** = CLARIFY operation + `oversight_required` → wired to the existing
  `checkpoint_inbox` / `checkpoint_routes` for approve/reject (the protocol already
  guarantees graceful fallback — Invariant 10).
- **AI safety** = protocol preventive-halt + injection/PII (the protocol's own
  detectors) surfaced in `CRP-*` headers, not a parallel enforcer.

---

## 3. Three-round upgrade plan

> **Status (2026-07-01):** Round 1 ✅ **DONE + gated** (commits `933f78c`, `7ac627d`).
> Round 2 ✅ **DONE + gated** (commit `8a3fcd5`, 10/10 battery pass). Round 3 not started.
> See `src/crp_comply/agent/positioned.py`, `orchestrator.py` (`run_positioned`,
> `_get_positioned_agent`), `tests/test_positioned_bridge.py`,
> `scripts/positioned_gate_check.py`. The legacy `.run()` ReAct loop is **untouched** —
> everything below is additive and opt-in via `ComplianceAgent.run_positioned()`.

### Round 1 — Re-base on CRPv5 dispatch (the spine) — ✅ DONE
**Goal:** Comply runs on `dispatch_positioned` for at least one real compliance flow.
1. ✅ Bumped dependency: `crprotocol[full]>=5.0,<6` in `pyproject.toml`.
2. ✅ Built the **Compliance Tool Capability Fabric**: `compliance_fabric_from_registry()`
   adapts the existing `agent/tools.py` `ToolRegistry` (`query_regulation`,
   `classify_ai_act_risk`, `recall_facts`, `lookup_annex`, `lookup_gdpr`,
   `search_iso42001`, `check_high_risk_criteria`, …) into TCF capability descriptors,
   offered on RETRIEVE/GENERATE/SYNTHESISE/ANALYSE so the model can never assert a
   citation it did not look up (Comply's core design property, preserved).
3. ✅ `PositionedComplianceAgent` + `ComplianceAgent.run_positioned()` — maps
   `PositionedResult` → the existing `AgentResult` shape (no API/schema break).
4. ✅ **Gate passed** on the real local 8B (`scripts/positioned_gate_check.py`):
   `state=done, tool_calls=1, facts_stored=1` — the model was forced to ground its
   classification in the deterministic `classify_ai_act_risk` tool.

### Round 2 — AI safety + checkpoints as first-class — ✅ DONE
**Goal:** every Comply run is governed by the protocol's safety surface.
1. ✅ `safety_profile_to_policy()` maps a tenant safety-profile dict (`blocked_tools`,
   `allowed_tools`, `blocked_safety_classes`, `data_residency`) to a `PolicyContext`,
   passed into every positioned dispatch via a **new, dedicated**
   `ComplianceAgent(crp_safety_profile=...)` constructor arg (kept separate from the
   pre-existing `profile`/`_profile` OrgProfile snapshot — different concept, not
   conflated).
2. ✅ `oversight_required` + `safety_overrides` (`compliance_fabric_from_registry`)
   gate any tool marked `destructive`/`mutating` (e.g. a future `submit_evidence`)
   behind approval — verified both directions: blocked without approval, executes
   after `ClarificationAction.ANSWER("approve")`.
3. ✅ `scan_task_safety()` runs the **protocol's own** `InjectionDetector` +
   `PIIScanner` on the task text (not app-level duplicates) and surfaces the result
   as `AgentResult.input_safety`.
4. ✅ CLARIFY never blocks the request: `make_collecting_clarify_handler()` answers
   inline when a resolver is supplied, else gracefully SKIPs (Invariant 10) and the
   open question is surfaced via `AgentResult.pending_clarifications` — no clarify
   is ever silently lost, and no request ever raises a raw error.
   **Honest scope note:** this is a *synchronous* in-process bridge, not the async
   webhook `checkpoint_inbox.py` / `SafetyControlPlane` mechanism (which pauses,
   persists, and resumes across separate HTTP requests via a human reviewer UI).
   Wiring the positioned loop to *that* mechanism — so a real reviewer approves a
   destructive tool call mid-run through the existing Inbox UI — is real remaining
   work, tracked for Round 3 alongside per-session CSO persistence (both need the
   same "pause an in-flight positioned run and resume later" capability).
5. ✅ **Gate passed**: `tests/test_positioned_bridge.py` — 10/10 (fabric registration,
   tool execution & grounding, oversight block, oversight approve, policy blocklist,
   CLARIFY skip, CLARIFY inline-answer, pending-clarifications surfaced, injection+PII
   flagged, end-to-end `run_positioned` gate).
6. ✅ **Carry-over items now DONE** (see Round 3 §0 below): the async checkpoint-inbox
   bridge and per-session CSO persistence both landed and are tested.

### Round 3 — Continuation, consolidation, evidence, validate — ✅ CORE DONE
**Goal:** long reports, dead code removed, evidence provable, ready to publish.
> **Status (2026-07-01):** commits `60b15ac`, `e2704cb`. 14/14 tests pass
> (`tests/test_positioned_bridge.py`). **Real local-8B verification**
> (`scripts/context_overflow_stress.py`): 6/6 multi-turn agentic turns completed with
> **zero context-overflow errors** — facts accumulated 1→6 via CSO relay, the final
> turn stressed 3 continuation windows, all against an 8196-token loaded window.
0. ✅ **DONE — the Round 2 carry-over, now closed:**
   - **`make_checkpoint_inbox_clarify_handler()`** — a REAL bridge to the async
     `checkpoint_inbox.py` / `SafetyControlPlane` mechanism. It registers a genuine
     `crp.security.checkpoint.Checkpoint` on the exact registry `resolve_checkpoint()`
     already resolves — an existing Inbox reviewer approving/rejecting through the
     current UI resolves this checkpoint too, no new endpoint needed. **Honest scope:**
     it *blocks the calling thread* for up to `timeout` seconds (a documented,
     accepted trade-off for a synchronous `run_positioned()` call — requires the API
     layer to run it off the event loop, exactly as the legacy `.run()` loop already
     does). Opt in via `ComplianceAgent.run_positioned(use_checkpoint_inbox=True)`;
     the default remains the fast, non-blocking Round 2 collector.
   - **Per-session CSO persistence** — `get_session_cso()` / `save_session_cso()`
     (module-level, in-memory store keyed by `session_id`). Verified with a test that
     constructs a **fresh** `ComplianceAgent` for a second "request" and confirms it
     still sees turn 1's facts. **Honest scope:** in-memory only — survives across
     HTTP requests within one running process, not across restarts. Full
     Postgres-backed persistence is separate, larger work per the auth/DB migration
     plan referenced in `AGENTS.md`; not attempted here.
1. ✅ **Root-caused and fixed the "LLM connection" gap the user asked about.**
   `model_call_from_compliance_llm` now runs every prompt through
   `crp.stl.guard_prompt_budget` (a new **protocol-level** fix — see
   `context-relay-protocol/CHANGELOG.md` — `provider_model_call` had a fixed
   `max_tokens=1024` with **zero check against the model's real context window**,
   despite every `LLMProvider` already implementing `context_window_size()` /
   `count_tokens()`). The guard caps `max_tokens` and, only if still necessary, trims
   the **oldest** prompt content (preserving the task instructions) so input, tool-call
   frames, continuation windows, and accumulated multi-turn CSO state can never overflow
   — verified for real against a genuinely tiny window (LM Studio's loaded 8196 tokens,
   not a model family's theoretical maximum) in `context_overflow_stress.py`.
   The Comply-side SDK worker (`sdk/src/crp_comply_sdk/worker.py`,
   `agent/worker_adapter.py`) was **audited and found already correct** — it already
   probes the real `loaded_context_length` per LM Studio's native API and divides it
   per `n_parallel` slot (citing the same root cause in its own docstring, "Audit 6
   §2"). The gap was that nothing **consumed** that correctly-reported number before
   calling the model on the *new* positioned path — now fixed.
2. ✅ `max_continuation_windows` verified for long compliance reports (turn 6 of the
   overflow stress test: 3 windows, 643-word answer, no truncation errors).
3. ✅ `export_positioned_evidence()` — an evidence pack from the CSO + Operation State
   Machine's event stream (already the audit trail) + an HMAC chain seal
   (`CognitiveStateObject.extend_hmac_chain`), mapping to EU AI Act / ISO 42001
   evidence needs without any new logging infrastructure.
4. ⏳ **Not attempted this round (honest gap):** deleting the redundant
   re-implementations in `crp_integration.py` (ledger, continuation, envelope packing,
   PII/injection duplicates) — this is a larger, riskier change (the legacy `.run()`
   loop still depends on them) that needs its own regression pass once the positioned
   path is the *default*, not just opt-in. Also not attempted: full regression on
   `data-round{2,3,4}-validation/` (needs the corpus/infra fixtures) and a Kimi-judged
   quality benchmark specific to Comply's compliance tasks (the protocol repo's own
   quality benchmark — local mean 5.81/10, Kimi mean ~8.4/10 — is a proxy, not
   Comply-specific evidence).
5. **Gate (publish trigger):** awaiting the user's own verification of Comply's actual
   behaviour (per their explicit request) before proceeding to publish.

---

## 4. Risks & invariants
- **Axiom 4:** no `CRP-*` header reaches the provider — keep Comply's proxy allowlist.
- **Checkpoints never leave the user with a raw error** — rely on the protocol's
  graceful fallback; keep a Comply-side default action.
- **Feature-flag the cutover** — legacy loop stays until Round 1 gate passes.
- **Quality watch:** the positioned loop's multi-turn follow-up can be terse on small
  models (observed 3.75/10 vs 8.25 single-op in the CRPv5 quality benchmark); Comply
  should set `depth`/frame expectations for report-grade answers.

---

*Companion: `wasa_ai-master/WASA_CRPV5_UPGRADE_REPORT.md` (built after Comply lands).*
