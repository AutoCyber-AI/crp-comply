# CRP Utilisation Audit — Context, Streaming, Tools & UX

**Date**: 2026-05-04
**Trigger**: User reported `WorkerError: upstream 400: Context size has been exceeded`
propagating as an opaque `RuntimeError`, plus four chat-UX defects.

---

## TL;DR

CRP-Comply is currently using **~10% of the CRP SDK's actual capability**.
The fact that we ever surface a "Context size has been exceeded" error to the
user is, as the user correctly pointed out, an architectural failure: CRP
exists precisely to make any LLM appear unbounded.

This document audits what CRP actually offers, what we use, what we
re-implement badly, and the phased plan to fix it.

---

## 1. CRP SDK capabilities (verified by inspecting the installed package)

`crp.Client` is `crp.core.orchestrator.CRPOrchestrator`. Public methods:

| Method | Purpose | We use it? |
|---|---|---|
| `dispatch()` | Push-model: build envelope from `WarmStateStore` facts under the model's real budget, run prompt, extract facts back, **continuation loop** if length wall hit | ❌ no |
| `dispatch_with_tools()` | Pull-model: LLM requests context on demand via CRP's built-in context-relay tools backed by WarmStore + CKF | ❌ no |
| `dispatch_stream()` | Yields `StreamEvent` (token / extraction / done) — real streaming | ❌ no |
| `dispatch_agentic()` | Full §22 cognitive loop (analyse → plan → synthesize → route → generate → evaluate → revise → curate) | ❌ no |
| `dispatch_progressive()` / `dispatch_hierarchical()` / `dispatch_reflexive()` | Specialist generation modes | ❌ no |
| `ingest()` / `ingest_batch()` | Push raw text into WarmStore + CKF without any LLM call | ❌ no |
| `preview_envelope()` | Inspect what would be packed before sending | ❌ no |
| `boost_fact()` / `penalize_fact()` / `reject_fact()` | User feedback on fact relevance | ❌ no |

Subsystems `crp.Client` wires up that we currently re-implement (badly):

* **`crp.envelope.packer.pack_facts`** — 6-phase budget-aware fact packing.
  We invoke this once for RAG result packing (`pack_hits_to_envelope`) but
  **never for conversation history**. The "shrink messages on 400" hack
  added in commit `0aca680` was a symptom of this gap.
* **`crp.continuation.manager.ContinuationManager`** — 3-way termination,
  gap analysis, stitching for unbounded output. We use the lightweight
  `continue_truncated_answer` shim only (output side, length-based).
* **`crp.state.warm_store.WarmStateStore`** — persistent in-memory fact
  ranking with aging. Our agent maintains its own message list instead.
* **`crp.ckf.fabric.ContextualKnowledgeFabric`** — 4-mode retrieval (exact,
  semantic, pattern, structural). We have a thin facts-store with linear
  recall.
* **`crp.providers.LlamaCppAdapter` / `OllamaAdapter`** — first-class local
  providers with `count_tokens` + `context_window_size`. We instead route
  LM Studio through `WorkerAdapter` and never told CRP the real context.

---

## 2. The "Context size exceeded" failure path (ROOT CAUSE)

```
ComplianceAgent.start()
 → builds messages = [system, user, ...tool round-trips...]  ← grows each iter
 → ComplianceLLM.chat_with_tools(messages, tools)
 → WorkerAdapter.generate_chat_with_tools(messages, ...)     ← raw passthrough
 → WebSocket → SDK worker → POST /v1/chat/completions
 → LM Studio (Llama-3.1-8B, 8k context):
     "error": "Context size has been exceeded"
 → WorkerError → RuntimeError  ← user sees this
```

Nowhere in this chain does anything ask the model "what's your real
context window?", consult `crp.envelope.packer`, or compact the
conversation. CRP is loaded but bypassed.

### What I tried in `0aca680` (and reverted in this commit)

A `WorkerAdapter._dispatch_with_shrink` retry loop that evicted the oldest
non-pinned message after a 400. That is **not CRP** — it's reactive,
greedy, message-level eviction, the exact opposite of the protocol. The
user was right to call it bullshit. It's been removed.

### What this commit does instead

1. **`compact_messages_for_budget(messages, budget_tokens, ...)`** in
   `crp_integration.py`. Proactively, before each `chat_with_tools` call:
   - pin system, first user, last 4 turns
   - replace older `tool` results with one-line CRP-fold markers that keep
     the assistant→tool message structure valid (so the OpenAI tool
     protocol doesn't break) while reclaiming ~all of their tokens
   - secondarily truncate older assistant prose
   - returns `(new_messages, stats)` for telemetry

2. **`WorkerAdapter.context_window_size()`** — returns
   `CRP_COMPLY_WORKER_CONTEXT_TOKENS` env var, default 8192. This tells
   CRP-Comply the truth about LM Studio's loaded model so the budget
   formula in step 1 is honest.

3. **Tool-loop integration** — `ComplianceAgent._run_to_completion` now
   computes `budget = ctx_window − default_max_tokens − 500` and calls
   `compact_messages_for_budget` *before every iteration*. The 400 should
   never fire because we never let the prompt exceed the model's
   declared window in the first place.

### Phase 2 (not in this commit)

Replace the hand-rolled tool loop in `agent/orchestrator.py` with
`crp.Client.dispatch_with_tools` end-to-end, registering our domain
tools (`query_regulation`, `classify_ai_act_risk`, etc.) into CRP's tool
registry alongside `CRP_CONTEXT_TOOLS`. This delegates **all** envelope
+ continuation + extraction logic to CRP.

---

## 3. Chat agent UX defects (acknowledged, plan)

| Defect | Current state | Fix |
|---|---|---|
| **No streaming** | `agentStart` blocks until full response | Phase 2: SSE endpoint `GET /agent/{id}/stream` powered by `crp.Client.dispatch_stream`, frontend `EventSource` consumer in `AgentChat.tsx`. |
| **Formatting breaks after 1 response** | Each follow-up message starts a fresh session because `onSubmit` checks `session.state === 'done'` and forks. Markdown is fine; what breaks is *conversational continuity*. | Phase 2: a real follow-up endpoint `POST /agent/{id}/continue` that re-opens a closed session and reuses its CKF. |
| **No delete option** | `DELETE /agent/{session_id}` exists in `api/agent.py` but the sidebar has no UI for it | **This commit**: trash icon on each sidebar row + `agentDelete` API call. |
| **System prompt too long** | 50 lines of numbered rules — Llama-3.1-8B was hallucinating tool names like `check_high_risk_criteria` because it skimmed past the schemas | **This commit**: cut to 7 lines. Tools are injected by the runtime via the OpenAI `tools` parameter — the system prompt does not need to list them. |

---

## 4. Phase plan

### Phase 1 (this commit — shipped)
- [x] Drop the worker-layer `_dispatch_with_shrink` hack
- [x] Add `WorkerAdapter.context_window_size()` (env-overridable)
- [x] Add `compact_messages_for_budget` using CRP envelope-style folding
- [x] Wire compaction into the agent's tool loop (every iteration)
- [x] Simplify `SYSTEM_PROMPT` from 50 lines → 7 lines
- [x] Surface a delete button on the AgentChat sidebar

### Phase 2 (this commit — shipped)
- [x] SSE streaming endpoints (`/agent/start/stream`,
      `/agent/{id}/clarify/stream`, `/agent/{id}/continue/stream`)
      — orchestrator emits trace events through an
      ``event_sink`` callback that the API layer pipes into a
      ``text/event-stream`` response. Frontend ``AgentChat.tsx``
      drains it with a fetch-based SSE parser and renders a
      live progress ticker.
- [x] ``POST /agent/{id}/continue`` for follow-up turns on closed
      sessions — same ``session_id`` is preserved; the prior task,
      final answer and clarifications are folded into
      ``extra_context`` so the LLM sees full conversation history.
- [x] Session-scoped retrieval dedup — orchestrator tracks
      ``chunk_id``s already shown to the LLM this run and replaces
      duplicate hit bodies with one-line CRP markers, keeping the
      envelope lean across iterations.
- [ ] **Deferred to Phase 3** — replacing the bespoke tool loop
      with ``crp.Client.dispatch_with_tools``: CRP's
      ``dispatch_with_tools`` hard-codes ``CRP_CONTEXT_TOOLS``;
      passing custom domain tools needs an SDK extension that
      belongs in the protocol pivot below.

### Phase 3 (the protocol pivot)
- [ ] Adopt `dispatch_agentic` for the production agent path so CRP's §22
      cognitive loop drives reasoning instead of our hand-rolled iteration
- [ ] Use `dispatch_stream_augmented` for the chat surface so token
      streaming and fact extraction happen in one pass

---

## 5. Configuration matrix

| Env var | Effect | Default |
|---|---|---|
| `CRP_COMPLY_WORKER_CONTEXT_TOKENS` | Honest context size of the model loaded in LM Studio. CRP folds older messages so prompts always fit. | `8192` |
| `CRP_COMPLY_LLM_BASE_URL` | OpenAI-compat upstream | unset |
| `CRP_COMPLY_LLM_API_KEY` | API key for the upstream above | unset (falls back to `DEEPINFRA_API_KEY` / `GROQ_API_KEY` / `TOGETHER_API_KEY` / `OPENROUTER_API_KEY` / `OPENAI_API_KEY`) |
| `CRP_COMPLY_LLM_MODEL` | Model name | `llama-3.3-70b-versatile` |
| `CRP_COMPLY_PUBLIC_LLM_DISABLED` | Force the free risk classifier to skip the LLM narrative | `0` |
