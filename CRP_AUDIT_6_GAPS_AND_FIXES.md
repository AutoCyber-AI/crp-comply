# CRP Comply — Audit 6: Gaps, Fixes & Contextual Handoff Note

> **Date:** 31 May 2026
> **Author context:** Written from the `context-relay-protocol` repo while validating CRPv3
> against real workloads, immediately before switching primary work into **this** (`crp-comply`)
> repo. **This document is the handoff note** — read it first. It assumes no prior conversation
> context and records: (a) the exact bugs found this round and their root causes, (b) the fixes
> already applied (with file + line references), (c) the remaining work with concrete plans,
> and (d) how this connects to CRPv3 and the local-LLM streaming problem.
>
> **Companion docs:** `CRP_AUDIT_5_GAPS_AND_FIXES.md` (previous round — worker false-positive,
> layout, context-window workaround). This audit closes several items left "plan provided"
> there, and adds the **context-size root cause** that explains the local-LLM failures.

---

## 0. Executive summary

| # | Issue | Severity | Status |
|---|-------|----------|--------|
| 1 | `loop.abort` events **dropped as malformed** → UI shows "undefined used undefined of undefined" | **HIGH** | **Fixed this pass** |
| 2 | **Local-LLM context-size mismatch** → `400 Context size has been exceeded` → empty windows, retry-exhausted loops, no streaming | **CRITICAL** | **Root-caused; fix pattern provided + applied in CRP demo** |
| 3 | Thinking models (Qwen3, R1) emit empty visible content → 0-word output | HIGH | Root-caused; guidance + guard |
| 4 | Worker WebSocket "no close frame received or sent. Reconnecting" | MEDIUM | Root-caused; plan |
| 5 | Answer loops/repeats; "Reflection·revise_plan uncited claim(s) (retry exhausted)" | HIGH | Downstream of #2/#3; plan |
| 6 | Exposed secrets in committed logs (PyPI token, CRP API key) | **CRITICAL** | **Action required by user** |

**Fixes applied this pass touch four files:**
- `src/crp_comply/api/events.py` — `AbortPayload` gains a `detail` field.
- `src/crp_comply/agent/loop_runtime.py` — abort emitters pass `detail=` instead of overriding
  the machine `reason` literal.
- `frontend/src/lib/loopEvents.ts` — `AbortEvent` gains optional `detail`.
- `frontend/src/components/ReasoningTape.tsx` — renders the human `detail` when present.

---

## 1. `loop.abort` dropped as malformed (HIGH) — FIXED

### 1.1 Symptom (from the interface + railway logs)
- Railway: `dropping malformed loop event: loop.abort payload ... reason 'plan revision budget exhausted'`.
- Interface: the abort banner rendered **"Aborted · undefined used undefined of undefined"**.

### 1.2 Root cause
`AbortPayload` (in `src/crp_comply/api/events.py`) declares:

```python
reason: Literal["budget_exceeded"] = "budget_exceeded"
```

but the loop emitted free-form strings for `reason`:

- `src/crp_comply/agent/loop_runtime.py` (step-budget abort) → `reason=str(exc)`
- `src/crp_comply/agent/loop_runtime.py` (plan-revision abort) → `reason="plan revision budget exhausted"`

These strings fail Pydantic `Literal` validation at the HTTP schema layer, so the **entire
event is dropped** ("malformed loop event"). Because the event never reaches the client, the
frontend's `AbortEvent` fields (`dimension`, `usage`, `limit`) are `undefined` → the banner
prints "undefined used undefined of undefined".

### 1.3 Fix applied
- **`events.py`** — added an optional human field, keeping `reason` as a stable machine enum:
  ```python
  reason: Literal["budget_exceeded"] = "budget_exceeded"
  dimension: AbortDimension
  limit: float
  usage: float
  detail: str | None = None     # NEW: human-readable cause
  ```
- **`loop_runtime.py`** — both abort emitters now pass the human text via `detail=` and let
  `reason` default to the literal; the plan-revision abort also sets `dimension="plan_revisions"`
  explicitly so `usage`/`limit` are always populated.
- **`frontend/src/lib/loopEvents.ts`** — `AbortEvent` gains `detail?: string | null`.
- **`frontend/src/components/ReasoningTape.tsx`** — shows `Loop stopped: {detail}` when present,
  otherwise the generic budget message, always followed by `(used {usage} of {limit})`.

### 1.4 Follow-up (not yet done)
- Add a unit test asserting `AbortPayload(**emitted).model_validate(...)` passes for both
  emitters. There is a parallel correct builder, `make_abort_payload()` in
  `src/crp_comply/agent/loop_budget.py`, that already uses `reason="budget_exceeded"`; consider
  routing all aborts through it to prevent regressions.

---

## 2. Local-LLM context-size mismatch (CRITICAL) — ROOT CAUSE of "streaming broken with local LLMs"

### 2.1 Symptom
- Worker log: LM Studio reachable (HTTP 200s) yet sessions error and reconnect; answers don't
  stream and come back repetitive/incoherent.
- Reproduced deterministically in the CRP repo: the first dispatch window returns
  `finish_reason=error, output_chars=0`; the raw server body is:

  ```
  BadRequestError: 400 - {'error': 'Context size has been exceeded.'}
  ```

### 2.2 Root cause (verified)
CRP's provider adapter **auto-discovers a model family's theoretical max context**, not the
context the local server actually loaded. Verified against LM Studio:

| Model | CRP auto-discovered | LM Studio **loaded_context_length** |
|---|---|---|
| qwen3-4b | 40960 | (model not loaded) max 40960 |
| qwen2.5-7b-instruct | 32768 | **4096** |
| meta-llama-3.1-8b-instruct | 131072 | **4096** |

CRP budgets its envelope against the discovered max (e.g. 40960) and packs continuation
context accordingly. The local server only has **4096** tokens loaded, so the very first
window overflows and the server returns `400 Context size has been exceeded`. The adapter
swallows the error and returns `("", "error")`, so:
- the window produces **0 chars**,
- extraction finds **0 facts**,
- the reflector cannot ground any claim → `revise_plan uncited claim(s): N (retry exhausted)`,
- the loop concatenates redundant step outputs → **repetitive, non-streamed answer**.

So the "streaming/repetition" bug is **downstream of a context-budget mismatch**, not a
streaming-transport bug.

### 2.3 Fix pattern (applied in the CRP demo; port into crp-comply)
LM Studio exposes the real loaded window via its **native REST API** — query it and cap CRP's
context to it:

```
GET {server_root}/api/v0/models   →  data[].loaded_context_length
```

Reference implementation (Python) is in the CRP repo at
`examples/crp_demos/long_context_document.py` → `_detect_server_context()`. It (1) reads
`loaded_context_length` from `/api/v0/models`, and (2) falls back to a cheap binary-search of
the chat endpoint when the native API is unavailable (e.g. Ollama → use `/api/show` /
`num_ctx`). After detection: `adapter._context_size = detected`.

**Where to apply in crp-comply:**
- `sdk/src/crp_comply_sdk/worker.py` — when the worker probes upstream (the `_probe_upstream`
  added in Audit 5), also fetch `loaded_context_length` and include it in the `hello`/`health`
  frame.
- `src/crp_comply/api/worker_registry.py` — store `llm_context_length` on the `_WorkerSlot`
  and expose it in `status()`.
- Wherever the backend builds the CRP adapter for a worker-backed model, set the adapter's
  context size to `min(family_max, loaded_context_length)`.
- Surface a warning in Settings when `loaded_context_length < 8192` ("Increase your local
  model's context to 8k+ for long-form answers").

### 2.4 Note on the Audit-5 "16k workaround"
Audit 5 item #7 flagged a "context-window workaround (16k instead of 4k) masking a budgeting
bug." This is the same defect from the other direction: hardcoding 16k overshoots a 4k-loaded
model. Replacing the hardcode with **detected** `loaded_context_length` resolves both.

---

## 3. Thinking models emit empty visible content (HIGH)

### 3.1 Symptom
With `qwen3-4b` (a reasoning model), windows return empty `content` and
`finish_reason=length`; the document ends up 0 words even when no 400 occurs.

### 3.2 Root cause
Reasoning models put output in `reasoning_content` and spend the token budget on `<think>`.
The CRP adapter (`crp/providers/openai.py::generate_chat`) already detects this and returns
`("", "length")` so continuation proceeds — but if **every** window is pure reasoning, the
final document is empty.

### 3.3 Guidance / guard
- For long-form generation, **prefer non-thinking instruct models** (qwen2.5-7b-instruct,
  llama-3.1-8b-instruct). The CRP demo now defaults to `qwen2.5-7b-instruct`.
- For reasoning models, raise per-window `max_tokens` (≥1536) so the model has budget left for
  visible content after thinking, and strip `<think>…</think>` (the demo's `_strip_thinking`).
- In crp-comply: detect reasoning models (presence of `reasoning_content` on first call) and
  either bump `max_tokens` or warn the operator.

---

## 4. Worker WebSocket close-frame churn (MEDIUM)

### 4.1 Symptom
Worker log: `no close frame received or sent. Reconnecting`.

### 4.2 Likely cause & plan
The upstream 400 (item #2) aborts the in-flight request mid-stream; the relay tears down the
socket without a clean close handshake, so the client library logs the missing close frame and
reconnects. Fixing item #2 removes most occurrences. Additionally:
- Add an explicit `await ws.close(code=1000)` on request-handler exit paths in
  `sdk/src/crp_comply_sdk/worker.py`.
- Add a WebSocket ping/keepalive (`ping_interval`/`ping_timeout`) so idle sockets don't drop.
- Treat upstream 4xx as a *handled request error* (send an error frame to the client) rather
  than letting it bubble and kill the socket.

---

## 5. Loop repetition / retry-exhausted answers (HIGH)

Downstream of #2 and #3. Once windows produce real content (context sized correctly + a
non-thinking model), grounding succeeds and the reflector stops exhausting retries. Remaining
hardening:
- Cap `max_plan_revisions` and on exhaustion **finalise with the best partial answer**, not a
  concatenation of redundant step outputs (`src/crp_comply/agent/loop_state.py`,
  `reflector.py`).
- De-duplicate step outputs before final synthesis (n-gram overlap check — see the repetition
  detector in `examples/crp_demos/long_context_document.py`: `_ngram_repetition`,
  `_duplicate_sentence_ratio`).

---

## 6. Exposed secrets (CRITICAL) — USER ACTION REQUIRED

The worker log attachment committed to this repo contained a live **CRP Comply API key**
(`crp_kf4...`) and a **PyPI token** appeared in an earlier round. **Revoke and rotate both
now**, and add the log file globs to `.gitignore`. Scrub from git history if already pushed
(`git filter-repo` / BFG). Do not push until rotated.

---

## 7. CRPv3 validation status (why we can swap repos)

A long-context acceptance demo was added in the CRP repo:
`examples/crp_demos/long_context_document.py`. It drives a local model through CRP's
continuation/stitch engine to produce a single 10k-word technical document, then checks:
- words ≥ 10,000, headings ≥ 20, has conclusion,
- **6-gram repetition < 1%**, duplicate-sentence ratio < 2%,
and writes human-readable deliverables (`document.md`, `document.html`) plus a CRP provenance
sidecar (`crp_provenance.json`). The earlier failure was **not** a CRP quality regression — it
was the context-size mismatch in §2. With detected context + a non-thinking model, CRP stitches
clean, non-repetitive long-form output. This is the green light to continue Gateway work.

---

## 8. Quick-start for the next session (no prior context)

1. **Rotate the leaked secrets in §6 first.**
2. Backend abort fix is in `events.py` + `loop_runtime.py`; run the agent loop tests.
3. Port the **context detection** (§2.3) from
   `context-relay-protocol/examples/crp_demos/long_context_document.py::_detect_server_context`
   into `worker.py` + `worker_registry.py`, then set the CRP adapter context to the detected
   value wherever a worker-backed model is dispatched.
4. Prefer non-thinking instruct models for generation (§3); warn on reasoning models and on
   `loaded_context_length < 8192`.
5. Add the worker close/keepalive hardening (§4).
6. Re-run the failing scenario from the interface log (the EU AI Act question) and confirm:
   streamed, non-repetitive, grounded, with a clean `loop.abort` banner if a budget is hit.

---

*Licensed under the Elastic License 2.0 — see LICENSE.md for details.*
