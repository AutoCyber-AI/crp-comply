# CRP Usage Assessment — crp-comply

> **Purpose**: A comprehensive audit of how the CRP protocol and SDK are used across three operational areas. This document is read-only analysis — it identifies gaps, locations, and reasoning. No fixes are applied here.
>
> **Scope**: (1) The CRP Comply proxy + general application, (2) the language agent loop + web search (most critical), (3) LLM operations and the agentic AI ecosystem (2nd most critical).
>
> **Methodology**: Direct source-code reading of all integration points as of Phase 7.23.

---

## Legend

| Symbol | Meaning |
|--------|---------|
| ✅ | Fully integrated, correctly used |
| ⚠️ | Integrated but with a notable gap or fragility |
| ❌ | Critical gap — CRP should be active here but is absent or never executes |

---

## Area 1 — CRP Comply Proxy and General Application

**Files**: `src/crp_comply/proxy/interceptor.py`, `src/crp_comply/proxy/routes.py`

**Overall grade: EXCELLENT — one resilience gap, one masking gap**

### What is covered ✅

The proxy is the most CRP-saturated layer in the product. Every call routed through the compliance proxy endpoint runs the full 9-primitive pipeline without shortcuts:

| Primitive | CRP module | Location |
|-----------|------------|----------|
| PII detection (input) | `crp.security.PIIScanner` | `interceptor.py` `_scan_pii()` |
| Prompt injection detection | `crp.security.InjectionDetector` | `interceptor.py` `_scan_injection()` |
| Risk classification | `crp.security.RiskClassifier` | `interceptor.py` `_classify_risk()` |
| Consent verification | `crp.security.ConsentManager` | `interceptor.py` `_check_consent()` |
| GDPR Art. 30 processing record | `crp.security.ProcessingRecordKeeper` | `interceptor.py` `_record_processing()` |
| Erasure eligibility check | `crp.security.ErasureManager` | `interceptor.py` `_check_erasure()` |
| Retention policy enforcement | `crp.security.RetentionManager` | `interceptor.py` `_check_retention()` |
| Data lineage tracking | `crp.security.DataLineageTracker` | `interceptor.py` `_track_lineage()` |
| Decision provenance | `crp.provenance.DecisionProvenanceEngine` | `interceptor.py` `analyse_provenance()` |
| HMAC-chained audit trail | `crp.security.ComplianceAuditTrail` | `interceptor.py` `_record_audit()` |

The pipeline is: inbound PII scan → injection check → risk classify → consent verify → forward to upstream LLM → outbound PII scan → HMAC audit trail → GDPR Art. 30 record → lineage + provenance tagging.

### GAP 1 — Hard imports crash proxy if CRP is unavailable ⚠️

**Location**: `src/crp_comply/proxy/interceptor.py` lines 30–49

```python
from crp.security import PIIScanner, InjectionDetector, RiskClassifier, ...
from crp.provenance import DecisionProvenanceEngine, ProvenanceConfig
```

**Why**: These are bare module-level imports with no `try/except`. If the `crp` package is not installed, broken, or an incompatible version is deployed, the entire proxy module fails to import and every proxied request returns 500. The agent layer (`crp_integration.py`) wraps **every single CRP import** in `try/except` with graceful fallback. The proxy does not — it fails hard.

**What**: Any deployment where the `crp` package version changes (e.g., Railway rebuilds with a newer wheel that has a renamed internal API) will silently break all proxied compliance calls, not just the CRP-enhanced features.

---

### GAP 2 — Hallucination risk is silently masked when provenance unavailable ⚠️

**Location**: `src/crp_comply/proxy/interceptor.py` `analyse_provenance()` (~lines 155–190) and `grade_quality()` (~line 230)

**Why**: When `DecisionProvenanceEngine` fails or returns no data, `analyse_provenance()` returns `{"hallucination_risk": "UNKNOWN", "grounding_score": 0.0, ...}`. The `grade_quality()` method then applies a `-5` penalty for "no provenance data". This is a small deduction on a scale that likely goes 0–100. A response that is entirely ungrounded (hallucinated) gets the same `-5` penalty as one that merely had a slow provenance pass.

**What**: Users trusting the quality score on the proxy response as a compliance signal may be misled. If the product is marketed as EU AI Act compliance tooling, a LLM output that bypasses grounding detection is not just a product quality issue — it's a compliance claim that cannot be substantiated.

---

## Area 2 — Language Agent Loop + Web Searches *(Most Critical)*

**Files**: `src/crp_comply/agent/loop_runtime.py`, `src/crp_comply/agent/orchestrator.py`, `src/crp_comply/agent/tools.py`, `src/crp_comply/agent/web_client.py`, `src/crp_comply/agent/crp_integration.py`

**Overall grade: GOOD FOUNDATION — two critical enforcement gaps, two signal gaps**

### What is covered ✅

The loop runtime and orchestrator implement a genuinely deep CRP integration:

- **Phase 7.22 always-on evidence priming** (`orchestrator.py` `_prime_task_evidence()`): Before the first LLM turn, RAG hits + SearXNG web hits are packed via `pack_hits_to_envelope()` → `crp.envelope.packer.pack_facts` with a fallback to naive truncation. The evidence primer is injected as a `role="system"` message stamped `name="crp_corpus_primer"` so the compaction pass can fold it intelligently later.
- **CrpMessageLedger per session** (`crp_integration.py` `CrpMessageLedger`): Every tool result is ingested into a `crp.state.WarmStateStore`-backed ledger. Facts are extraction-pipeline-structured, contradiction-checked against prior facts, stale facts are superseded, and the ledger is repacked into a budget-bounded Markdown digest before each LLM turn. This is a full CRP §22 warm-state loop.
- **`compact_messages_for_budget()`** (`crp_integration.py`): A 4-pass compaction algorithm (primer fold → tool result fold → assistant prose truncation → tail hard-clip) ensures the context window never overflows. The `crp_corpus_primer` can be evicted once 60% of the budget is consumed by live conversation — this is the correct CRP behaviour.
- **Injection scan** (`orchestrator.py` pre-dispatch): `scan_for_injection(user_task)` runs `crp.security.InjectionDetector` on the user's task text. HIGH risk → `AgentResult(state="error")` and no LLM call. This mirrors the proxy's injection gate.
- **Extraction pipeline on user task** (`orchestrator.py`): `extract_facts_from_text(user_task)` runs `crp.extraction.ExtractionPipeline` and stores structured facts into the CKF before the first LLM turn, so clarification/intent signals become first-class CKF nodes.
- **`query_regulation` CRP envelope** (`tools.py`): After RAG retrieval, hits are MMR-reranked → contradiction-detected → packed into a CRP envelope. Each hit becomes a `crp.extraction.Fact` when ingested into the ledger.
- **`crp_apply_feedback()`** (`crp_integration.py` line 1736): Well-implemented — uses `crp.Client.boost_fact` / `penalize_fact` / `reject_fact`. The feedback persists into the WarmStateStore so subsequent retrievals reflect the relevance adjustment.
- **`CrpEventBus`** (`crp_integration.py`): Wraps `crp.observability.events.EventEmitter` — CRP protocol events (extraction, envelope, budget, revision) are forwarded into the orchestrator's SSE pump and surfaced in the UI.

### GAP 3 — `tool_hint` in PlanStep is NEVER enforced ❌ *(Critical)*

**Location**: `src/crp_comply/agent/loop_runtime.py` `_plan_for()` lines 578–591 vs `_execute_step()` lines 445–510

**Why**: The loop planner calls `needs_fresh_web(task)` to detect freshness-sensitive queries (recent EDPB opinions, latest AI Act amendments, etc.) and sets `step.tool_hint = "web_search"` on the `PlanStep` dataclass. This is the mechanism by which the language-agent loop is supposed to steer the underlying `ComplianceAgent` toward web tools for time-sensitive questions.

However, `_execute_step()` passes only `step.intent` as a plain sub-task string to `ComplianceAgent.run()`. The `step.tool_hint` field is **never read**. The `ComplianceAgent` selects tools purely via LLM reasoning over the full `ToolRegistry`. On a small (8B) local model that has already seen corpus results, it may call `query_regulation` first, get stale results, and only call `web_search` in round 2 or 3.

**What**: 
- For freshness-sensitive queries (the exact type CRP/regulatory-tech products serve), the tool execution order is non-deterministic on small models.
- Each redundant round trip is 85–120 seconds on a local CPU LLM. A 2-round detour for a "What did EDPB say last month?" query means a 3+ minute wait for an answer that should arrive in 90 seconds.
- The `tool_hint` field exists, is computed, and is correctly set — but the routing contract is silently broken at the execution boundary.

---

### GAP 4 — `dispatch_via_crp` NEVER runs in production ❌ *(Critical)*

**Location**: `src/crp_comply/agent/orchestrator.py` lines ~330–345

```python
crp_mode = os.environ.get("CRP_COMPLY_AGENT_DISPATCH_MODE", "")
if crp_mode:
    return await _run_via_crp_dispatch(...)
```

**Why**: The `dispatch_via_crp()` function in `crp_integration.py` is a fully-implemented, event-wired adapter over CRP's native `dispatch_agentic` / `dispatch_with_tools` / `dispatch_stream_augmented` / `dispatch_plain` modes — the §22 8-phase cognitive loop (analyse → plan → synthesise → route → generate → evaluate → revise → curate). This is the headline CRP feature.

However, `CRP_COMPLY_AGENT_DISPATCH_MODE` defaults to `""` (empty string) and is not set in `railway.toml`, `docker-compose.yml`, or the production environment. The `if crp_mode:` guard means it **never executes** unless an operator explicitly sets this env var.

**What**: 
- The CRP native dispatch loop (which includes CRP-side retrieval, reranking, quality evaluation, and revision rounds) is never used in any user session in production.
- The product's bespoke ReAct tool loop in `orchestrator.py` is doing the work that CRP's §22 loop is designed to handle natively — but with less quality enforcement (no revision rounds, no CRP quality report, no `human_oversight_required` events).
- This is a first-class CRP compliance gap: the product is not actually using CRP's agentic dispatch.

---

### GAP 5 — Feedback loop fires on corpus citations only, not web search hits ⚠️

**Location**: `src/crp_comply/agent/loop_runtime.py` line ~417 (`_extract_citations()`) vs `orchestrator.py` `_prime_task_evidence()` web hit pipeline

**Why**: After a successful agent run, `_fire_crp_feedback()` calls `crp_apply_feedback(provider, fact_id=..., signal="boost")` for each corpus citation in the final answer. This teaches CRP's WarmStateStore to prioritise the clauses that actually appeared in answers.

However, **web search hits from `_prime_task_evidence()`** are formatted via `_format_web_hits()` and injected into the evidence primer, but they are never tracked. The SearXNG `feedback()` API (accessible via `web_client.feedback()`) exists in `web_client.py` but is never called after a successful answer. The web search utility signal is completely absent from the feedback loop.

**What**: 
- SearXNG's learning loop (custom engine ranking, query reformulation) never receives "this web result was useful" signals.
- Over time, irrelevant web results continue to appear in the evidence primer at the same frequency as useful ones, degrading evidence quality without any self-correction mechanism.

---

### GAP 6 — `crp_apply_feedback` receives provider but loop constructs it per-feedback-call ⚠️

**Location**: `src/crp_comply/agent/loop_runtime.py` `_fire_crp_feedback()` line ~863, `crp_integration.py` `crp_apply_feedback()` line 1736

**Why**: The `crp_apply_feedback` function creates a `crp.Client(provider=provider)` and calls `.close()` in a `finally` block — this is one `crp.Client` instantiation per feedback signal. A session with 10 cited clauses creates 10 `crp.Client` instances sequentially (in a daemon thread). Each `Client` init may involve warm store state loading.

**What**: Not a correctness bug — the feedback **does** reach CRP correctly. But the per-signal Client construction creates overhead in sessions with many citations. The loop runtime has no provider reference cached in the feedback closure, so this is the correct pattern given the current architecture. It is noted as a sub-optimal pattern for future optimisation.

---

## Area 3 — LLM Operations and the Agentic AI Ecosystem *(2nd Most Critical)*

**Files**: `src/crp_comply/agent/llm.py`, `src/crp_comply/agent/worker_adapter.py`, `src/crp_comply/agent/orchestrator.py`, `src/crp_comply/proxy/routes.py`

**Overall grade: FUNCTIONAL — streaming gap, major audit coverage gap, unhelpful failure mode**

### What is covered ✅

- **`ComplianceLLM.for_user()`** correctly reads `provider_configs.json` and routes to `WorkerAdapter` (local SDK relay), `OpenAIAdapter`, or `AnthropicAdapter` from `crp.providers`. The CRP provider abstraction is used as intended.
- **`_autodetect()`** provides a fallback via environment variables (`CRP_COMPLY_LLM_BASE_URL`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) when no user config is stored.
- **`chat_with_tools()`** / **`chat_with_tools_streaming()`**: The orchestrator uses the CRP provider abstraction's `chat_with_tools` method — the orchestrator itself is not aware of which underlying LLM is called.
- **Any LLM plugged in**: `ComplianceLLM.for_user()` supports any OpenAI-compatible endpoint (Ollama, LM Studio, vLLM, custom) via `OpenAIAdapter` with a configurable `base_url`. The product correctly inherits CRP's provider-agnostic design.

### GAP 7 — WorkerAdapter (local LM Studio via SDK relay) has NO token streaming ❌ *(Most Impactful for Local Users)*

**Location**: `src/crp_comply/agent/llm.py` `supports_streaming_tools()` lines ~280–295, `src/crp_comply/agent/worker_adapter.py`

```python
def supports_streaming_tools(self) -> bool:
    prov = self._provider
    if prov.__class__.__name__ == "OpenAIAdapter":
        return hasattr(getattr(prov, "_client", None), "chat")
    return False  # WorkerAdapter, AnthropicAdapter → no streaming
```

**Why**: `supports_streaming_tools()` only returns `True` for `OpenAIAdapter`. The `WorkerAdapter` (which is the primary path for local LM Studio users connecting via the `crp-comply-sdk`) always returns `False`. This triggers the fallback path in the orchestrator: blocking `chat_with_tools()` call → single `on_text_delta(full_text)` call after the entire response is ready → the UI receives the final answer as a single chunk.

**What**: 
- For a local 8B model on CPU taking 85–120 seconds, the user sees "Thinking…" for the full duration with no progressive output — exactly the UX problem the streaming architecture was designed to solve.
- The SDK worker (`sdk/src/`) uses a future-based request/response pattern in `worker_registry.py`. Extending it to an async-generator pattern for streaming is architecturally feasible but not yet implemented.
- Any LLM plugged in via `local_worker` mode (the default for SDK users) cannot get streaming. This affects the most important user segment — on-premise / self-hosted deployments.

---

### GAP 8 — Local LLM calls bypass the CRP proxy audit trail entirely ❌ *(Critical for Compliance Claims)*

**Location**: Architectural gap between `src/crp_comply/proxy/routes.py` (proxy path) and `src/crp_comply/agent/orchestrator.py` `_call_llm()` (direct path)

**Why**: The proxy's `ComplianceAuditTrail`, `ProcessingRecordKeeper`, `DataLineageTracker`, and `DecisionProvenanceEngine` only run when a call is routed through the CRP proxy HTTP endpoint. The agent loop's `ComplianceLLM.for_user()` calls the LLM provider **directly** — either via `WorkerAdapter` (WebSocket → LM Studio), or via `OpenAIAdapter`/`AnthropicAdapter` with their native SDKs. These calls never touch the proxy.

The agent layer does run `scan_for_injection()` and `extract_facts_from_text()` before the LLM call, but:

| Proxy capability | Present in agent loop? |
|------------------|------------------------|
| HMAC-chained `ComplianceAuditTrail` | ❌ No |
| GDPR Art. 30 `ProcessingRecordKeeper` | ❌ No |
| `DataLineageTracker` | ❌ No |
| `DecisionProvenanceEngine` (hallucination risk) | ❌ No |
| `InjectionDetector` | ✅ Yes (`scan_for_injection`) |
| `PIIScanner` on output | ❌ No |
| `RiskClassifier` on output | ❌ No |

**What**: 
- If a customer uses CRP Comply to produce an EU AI Act compliance report using a local LLM (the marketed self-hosted use-case), none of the LLM calls are in the HMAC-chained audit trail. The compliance evidence is therefore structurally incomplete.
- The product cannot truthfully claim Art. 13/14 GDPR or EU AI Act Art. 12 logging for locally-routed LLM calls without adding agent-layer equivalents of these primitives.
- This is the single most significant compliance gap in the product.

---

### GAP 9 — `RuntimeError: No LLM provider configured` is not user-surfaced ⚠️

**Location**: `src/crp_comply/agent/llm.py` `_autodetect()` line ~220

```python
raise RuntimeError("No LLM provider configured — set CRP_COMPLY_LLM_BASE_URL ...")
```

**Why**: When `ComplianceLLM.for_user()` falls back to `_autodetect()` and no provider environment variable is set, a `RuntimeError` propagates up through `_build_agent()` → `agent_loop_stream()`. This returns a raw 500 HTTP error to the client.

**What**: The user sees an unstructured server error instead of a clear message like: "No LLM provider is configured. Go to Settings → LLM Provider to connect your model." This is a usability gap but also a security consideration — raw `RuntimeError` messages may leak configuration details in certain deployment environments.

---

### GAP 10 — No UI surface for `CRP_COMPLY_AGENT_DISPATCH_MODE` ⚠️

**Location**: `src/crp_comply/agent/orchestrator.py` line ~330, `frontend/src/pages/Settings.tsx`

**Why**: The Settings page exposes LLM provider selection (relay, local, commercial) but has no concept of "CRP dispatch mode". The `agentic`, `with_tools`, `stream_augmented`, and `plain` modes in `dispatch_via_crp()` are only accessible by setting an environment variable in Railway or the Docker environment — not by any in-product UI.

**What**: 
- End users and operators cannot activate the CRP native dispatch path without infrastructure access.
- The product's most powerful CRP integration point (§22 agentic loop) is functionally invisible to users.
- This also means the CRP native dispatch path has never been exercised in production by any real user session — it has no observability, no telemetry, and no feedback signal.

---

## Summary Table

| # | Area | Gap | Severity | Location | Status |
|---|------|-----|----------|----------|--------|
| 1 | Proxy | Hard CRP imports — no graceful degradation | ⚠️ Resilience | `proxy/interceptor.py` L30–49 | ✅ **Fixed** (commit `dbfb9e3`) — all proxy CRP imports wrapped in try/except with graceful degradation |
| 2 | Proxy | Provenance failure silently masks hallucination risk | ⚠️ Correctness | `proxy/interceptor.py` `analyse_provenance()` | ✅ **Fixed** (commit `dbfb9e3`) — `UNKNOWN` hallucination risk now applies `-20` penalty instead of `-5` |
| 3 | Agent Loop | `tool_hint` computed but never enforced in `_execute_step` | ❌ Critical | `loop_runtime.py` L578–591, L445–510 | ✅ **Fixed** (commit `dbfb9e3`) — `tool_hint` injected as CRP DIRECTIVE at iter-0 system message to steer tool selection |
| 4 | Agent Loop | `dispatch_via_crp` never executes — env var not set | ❌ Critical | `orchestrator.py` L330–345 | ✅ **Fixed** — `CRP_COMPLY_AGENT_DISPATCH_MODE` documented in `railway.toml`; per-user override via Settings UI (GAP 10); default keeps iterative domain-tool loop (compliance reports require it) |
| 5 | Agent Loop | Web search hits excluded from CRP feedback signal | ⚠️ Signal | `loop_runtime.py` L417, `web_client.py` | ✅ **Fixed** — `_fire_crp_feedback()` now calls `web_client.feedback(useful=True, url=...)` for all web-sourced citations after successful runs |
| 6 | Agent Loop | Per-signal `crp.Client` construction in feedback thread | ⚠️ Efficiency | `loop_runtime.py` L863, `crp_integration.py` L1736 | ➡️ Accepted as-is — feedback runs in a daemon thread; no correctness issue |
| 7 | LLM Ops | `WorkerAdapter` has no token streaming — blocks 85–120s | ❌ Critical UX | `llm.py` L280–295, `worker_adapter.py` | ✅ **Fixed** (commit `dbfb9e3`) — `WorkerAdapter` now uses async generator streaming via `dispatch_streaming_from_sync` queue; `supports_streaming_tools()` returns `True` |
| 8 | LLM Ops | Local/BYOK LLM calls bypass proxy audit trail entirely | ❌ Critical Compliance | `proxy/routes.py` vs `orchestrator.py` | ✅ **Fixed** — `ComplianceAuditTrail` + `ProcessingRecordKeeper` + `PIIScanner` applied per iteration in `orchestrator.py`; CRP audit trail now covers every direct LLM call |
| 9 | LLM Ops | `RuntimeError` on unconfigured provider not user-surfaced | ⚠️ UX | `llm.py` L220 | ✅ **Already handled** — `_build_agent()` raises `HTTPException(503)` with actionable detail; `agent_loop_stream()` catches it and emits `loop.error` SSE; `ReasoningTape.tsx` renders the error message in red |
| 10 | LLM Ops | No UI for CRP dispatch mode — §22 loop never activated | ⚠️ Feature gap | `orchestrator.py` L330, `Settings.tsx` | ✅ **Fixed** — Settings page `LLMProviderConfig` section now includes CRP dispatch mode dropdown (Default / Agentic / With Tools / Stream Augmented / Plain); persisted server-side per user in `provider_configs.json`; applied via `agent.dispatch_mode_override` in `_build_agent()` |

---

## Priority Order for Addressing

1. **GAP 8** (audit trail bypass) — ✅ Fixed
2. **GAP 4** (dispatch_via_crp never runs) — ✅ Fixed
3. **GAP 7** (no streaming on WorkerAdapter) — ✅ Fixed (commit `dbfb9e3`)
4. **GAP 3** (tool_hint not enforced) — ✅ Fixed (commit `dbfb9e3`)
5. **GAP 1** (hard proxy imports) — ✅ Fixed (commit `dbfb9e3`)
6. **GAP 5** (web feedback signal missing) — ✅ Fixed
7. **GAP 2** (hallucination masking) — ✅ Fixed (commit `dbfb9e3`)
8. **GAP 9** (RuntimeError not surfaced) — ✅ Already handled
9. **GAP 10** (no dispatch mode UI) — ✅ Fixed
10. **GAP 6** (per-signal Client construction) — ➡️ Accepted

---

*Document created: Phase 7.23 — read-only analysis.*  
*All gaps fixed: Phase 7.24 — commits `dbfb9e3` (GAPs 1/2/3/7) + current commit (GAPs 4/5/8/9/10).*
