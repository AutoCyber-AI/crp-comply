# LM Studio logs tracking of chat operations

Living document. Append a new dated section at the top for each test run.
Cross-references the verbose LM Studio log file (`lm_studio_verbose_2.log`,
`lm_studio_verbose_3.log`, …) and the railway backend logs.

---

## 2026-05-06 ~16:30 — `lm_studio_verbose_4.log` (841 lines, abrupt cutoff)

### Test scenario (post Phase 7.21 commit `ace3ed4`)

Same EU AI Act prompt. Phase 7.21 had bumped the SDK worker timeout
120s→600s + added a heartbeat thread. Log #4 only contains **iter 1**
and stops cold after `Generated prediction` JSON at line 804 — there is
**no `Client disconnected` line**. Either the user stopped the run or
the hosted backend died silently after receiving iter-1's tool_call
response. SearXNG sidecar service shows healthy but **idle** — the 8B
model never invoked `web_search` despite system-prompt rule 5/6.

### What iter 1 actually did

`tool_call: query_regulation(query="EU AI Act compliance requirements", top_k="15")`

→ **88s of prompt-eval burned just to issue a tool call we could have
made deterministically up-front.**

### Root cause

Reliance on **prompting** to coax the 8B model into using corpus and
web tools. Even with explicit rules, the model defaults to the easiest
move (one `query_regulation` call) and ignores `web_search` entirely.
This is a **structural** problem, not a prompt-tuning problem.

### Phase 7.22 fix — embed retrieval in the loop, not the prompt

Implemented in `src/crp_comply/agent/orchestrator.py` (commit pending):

* **F-A: always-on RAG priming.** New `_prime_task_evidence(task)`
  runs unconditionally on every `run()` call (not just when
  `recipe_context` is supplied as Phase 7.19 did). It calls
  `self.rag._prime_corpus_envelope({"query": task[:300]})` to MMR-pack
  top corpus chunks via CRP into the system message slate **before
  iter 1 starts**.
* **F-B: deterministic web priming.** When the task contains a
  freshness marker (`needs_fresh_web` heuristic ported from
  `loop_runtime._FRESHNESS_PATTERNS`) AND `self.web_client` is wired,
  the agent calls `web_client.search(...)` and folds up to 5 hits into
  the same primer envelope as `[W1]…[W5]` blocks with URL + tier.
* **F-C: single CRP envelope.** Both RAG chunks and web hits are
  rendered into ONE `crp_evidence_primer` system message (CRP
  `pack_facts` semantics + per-chunk `chunk_id` for direct citation).
  Emits `crp_evidence_primed` trace event with `chunks` and
  `web_hits` counts.
* **F-D: wire web_client through.** `ComplianceAgent.__init__` now
  accepts `web_client` and `always_prime_evidence`; `_build_agent` in
  `api/agent.py` passes the existing sidecar client through.

### Effect

Iter 1's LLM call already sees the relevant clauses + (when fresh)
web evidence in its context — it can answer immediately instead of
spending 88s of prompt-eval to request a single `query_regulation`
tool call. **Eliminates one full round-trip per session** (≈ 88s on
this CPU-bound 8B deployment).

### Validation

* `767 passed, 4 skipped in 65.55s` — full pytest green.
* `tsc --noEmit` — frontend clean.

### Operator action — reinstall worker after `git pull`

```powershell
# 1. Stop the current worker (Ctrl-C in the worker terminal)

# 2. Pull and reinstall the SDK from this repo
cd c:\Users\User\Desktop\crp-comply
git pull
pip install --upgrade -e .\sdk

# 3. Start the worker with the new 600s timeout (default in 7.21+)
$env:CRP_COMPLY_WORKER_REQUEST_TIMEOUT_S = "600"
crp-comply worker `
    --lmstudio http://10.126.155.243:1234 `
    --api-key <YOUR_KEY> `
    --request-timeout 600 `
    -v
```

The new banner should show `request_timeout_s=600.0`. With Phase 7.22
priming in effect the very first LM Studio request already contains
`crp_evidence_primer` as a 4th system message before the user turn.

---

## 2026-05-06 15:45–15:52 — `lm_studio_verbose_3.log` (3226 lines)

### Test scenario (post Phase 7.20 commit `abc6793`)

Same prompt as before. Phase 7.20 had bumped the **hosted-side** dispatch
timeouts (`worker_adapter.py`, `worker_registry.py`) from 120s → 600s and
added Clerk-auth gating + `llm_phase` events.

Symptom now: **iter 1–3 succeeded** (CKF-class tool finally invoked!),
**iter 4 (final answer) cut off at exactly 120.0s**, "TypeError: network
error" again, no answer rendered, but LM Studio's log shows the answer
*was* being generated and reached **374 tokens** before the connection
was killed.

### Per-iteration timing

| Iter | Request received | Prompt tokens | Prompt eval | Generation | Outcome |
|---|---|---|---|---|---|
| 1 | 15:45:56 | 6440 | 84.1s | 3.5s (32 tok) | tool_call: `query_regulation(query="EU AI Act compliance requirements and application scope", top_k="10")` |
| 2 | 15:47:28 | 6284 | 81.4s | tool_call: `query_regulation(query="EU AI Act Article 6 risk classification…", top_k="8")` |
| 3 | 15:48:55 | 6445 | 82.9s | tool_call: **`classify_ai_act_risk(...)` ✅** *(Phase 7.20 system-prompt nudge worked — model finally reached for a CKF / deterministic tool)* |
| 4 | 15:50:28 | ? | ~88s | streaming text | **CLIENT DISCONNECTED at 15:52:28 = exactly 120.0s** while LM Studio was at "Accumulated 374 tokens", actively streaming the final markdown answer (see line 3185). Generation cancelled, response lost. |

### Smoking gun

Line 3185:
```
[2026-05-06 15:52:28][INFO][LM STUDIO SERVER] Client disconnected. Stopping generation...
```

Wall-clock from iter-4 chat-completion request start to the disconnect:

> 15:52:28 − 15:50:28 = **120.000s exactly**

That is **not** the hosted-side dispatch timeout (we already bumped that
to 600s in Phase 7.20). The 120s ceiling comes from the **SDK worker
running on the user's LAN** — `WorkerConfig.request_timeout_s = 120.0`
in [`sdk/src/crp_comply_sdk/worker.py`](sdk/src/crp_comply_sdk/worker.py#L107),
applied to the **`httpx_client.post(... , timeout=cfg.request_timeout_s)`**
call to LM Studio at line 227.

Phase 7.20 fixed the wrong layer. The relay → worker hop now waits
600s, but the worker → LM Studio hop still drops the read at 120s.

### Other findings from this log

1. **Web search NEVER invoked.** Across 4 iterations the model called
   `query_regulation` ×2, `classify_ai_act_risk` ×1, then attempted a
   final answer. SearXNG was never asked even one question. The
   `searxng_railway_service.log` snapshot the user pasted confirms the
   service has been *idle* since 14:00 (only Redis health-checks and
   one external HTTPS GET to `wikidata`/`commons` from an unrelated
   engine init at 04:10). This is a model-quality issue, not a
   plumbing issue — Llama 3.1 8B does not pick `web_search` even when
   the system prompt explicitly nudges it (see
   `orchestrator.py` SYSTEM_PROMPT rules 5–6).

2. **CRP envelope works.** All 4 chat-completion requests fit inside
   the 8192 ctx (peak 6445 tokens), no `crp_overflow_refold` events.
   The Phase 7.19 ledger is silently doing its job.

3. **The "Asking to truncate to max_length" warning** in Railway is
   from the HuggingFace tokenizer used for token-count estimation
   inside the corpus indexer — harmless, model has no
   `model_max_length` set in its config. *(Cosmetic only.)*

4. **No `llm_phase` events visible to the user** — the FE
   `formatStreamEvent()` had no case for `llm_phase` so they fell
   through to the default `· llm_phase` text and looked like noise.
   Worse, between `prompt_send` and `received` (88s of CPU
   prompt-eval) the only activity reaching the FE was the SSE `:ping`
   comment every 20s, which is invisible. *User's complaint "While
   prompt processing nothing happens" is dead-on accurate.*

### Root causes (RC) for this round

| ID | Cause | Layer | Fix |
|---|---|---|---|
| RC-A | `WorkerConfig.request_timeout_s = 120.0` kills LM Studio mid-generation | SDK worker (user LAN) | bump default → 600s, add env var + CLI flag (so users can re-run their existing worker without code edits) |
| RC-B | No periodic activity event during the 88s prompt-eval | Orchestrator | spawn a heartbeat thread that emits `llm_progress` every 5s with `elapsed_ms` |
| RC-C | FE silently dropped `llm_phase` to default text | Frontend | explicit cases for `llm_phase` (`prompt_send` → "sending prompt", `received` → "model replied in Xs") and `llm_progress` ("thinking (Ns elapsed)"); suppress `llm_token` from the line ticker |
| RC-D | Web search never invoked even with prompt nudge | Model behaviour | not fixable in 8B model — accept until larger model wired in |

### Fixes applied (Phase 7.21)

| ID | File | Change |
|---|---|---|
| F-A | `sdk/src/crp_comply_sdk/worker.py` | `request_timeout_s` default 120 → 600; new `--request-timeout` CLI flag; reads `CRP_COMPLY_WORKER_REQUEST_TIMEOUT_S` env var |
| F-B | `src/crp_comply/agent/orchestrator.py` | wraps the LLM call with a `threading.Event`-driven heartbeat that emits `llm_progress` events every 5s; `finally` block guarantees the watcher dies on every exit path |
| F-C | `frontend/src/pages/v2/AgentChat.tsx` | `formatStreamEvent` handles `llm_phase` (with elapsed-ms label) + `llm_progress` (rolling "thinking Ns" counter) + `crp_overflow_refold`; `llm_token` returns `""` and is filtered from the ticker |

### Action required from operator

After the next deploy, **the SDK worker must be restarted** for the new
default to take effect — either pull the new SDK and re-run, OR set the
env var on the existing install:

```powershell
$env:CRP_COMPLY_WORKER_REQUEST_TIMEOUT_S = "600"
crp-comply worker --lmstudio http://10.126.155.243:1234 --api-key …
```

### Expected outcome on next test run

* No 120-second cliff — iter 4 completes the full ~250 t @ 5 t/s ≈ 50s
  generation cleanly.
* FE shows continuous activity: every 5s a "thinking 5s / 10s / 15s …"
  line is appended to the live ticker during prompt-eval.
* Phase events render as readable English ("sending prompt to model",
  "model replied in 87.6s (1 tool call)").
* Final answer reaches the bubble.

---

## 2026-05-06 13:38–13:44 — `lm_studio_verbose_2.log` (2658 lines)

### Test scenario

User-side: opened the app, asked
> *"What is the EU AI act about. What are its requirements? Why was it
> created? what was the gap that needed to be filled? what does it consist
> of? what does it require for high risk systems to run in compliance with
> it?!"*

LLM: LM Studio @ `10.126.155.243:1234`, model `meta-llama-3.1-8b-instruct`,
context window **8192**, ~67 t/s prompt eval / ~5 t/s generation (CPU).

Symptom seen by user: **TypeError: network error** in railway log
(`LLM call failed at iter 3 after 1 CRP attempts / NoneType: None`),
no answer reached the frontend.

### Per-iteration timing

| Iter | Request received | Prompt tokens | Prompt eval | Generation | Result |
|---|---|---|---|---|---|
| 1 | 13:38:58 | ~5485 | ~80.7s | ~22s (132 tok) | tool_call: `query_regulation(query="EU AI act summary", top_k=8)` ✅ |
| 2 | 13:40:45 | ~6529 | ~98.9s | ~7.2s  (32 tok) | tool_call: `query_regulation(query="EU AI act high risk systems compliance requirements", top_k=8)` ✅ |
| 3 | 13:42:32 | ~7719 | ~98s    | ~22s, **client disconnect at 13:44:32** | partial text "Based on the tool responses, here is the final answer:\n\n**EU AI Act Overview**\n\nThe EU AI Act is a regulation aimed at ensuring the safe and transparent development of artificial intelligence (AI) systems. The act sets out various requirements for AI system developers, including the need for transparency, accountability, and security.\n\n**High-Risk" — never delivered, finish_reason=`stop` only because LM Studio finalised after the disconnect |

Total iter-3 wall time before disconnect: **120.0s exactly** (13:42:32 → 13:44:32).

### Root cause analysis

**RC-1 (PRIMARY) — 120-second hard timeout on the worker WS dispatch.**
File: `src/crp_comply/agent/worker_adapter.py` line 70
(`_dispatch(payload, timeout: float = 120.0)`).
`generate_chat_with_tools` does NOT pass a longer timeout, so every call
to a local LM Studio worker gets a flat 120s budget. Iter 3 prompt eval
alone is 98s on this hardware, leaving only 22s for generation — far
shorter than the ~60–90s a 600-token answer needs at 5 t/s.
The asyncio future raises `WorkerTimeoutError`, the `dispatch_from_sync`
thread `future.result(timeout=125)` propagates a `TimeoutError`, and
because the WebSocket layer also drops the in-flight request, the SDK
worker observes the upstream connection as broken and raises a network
error which surfaces as `TypeError: network error` to the agent.

**RC-2 (PRIMARY) — non-streaming worker path.**
`WorkerAdapter` sends `stream:false` (no `stream` key, OpenAI default).
The full chat-completion response only arrives after generation finishes,
so:
* the backend cannot forward incremental tokens to the SSE stream;
* the frontend has no way to receive `llm_token` events;
* there is no in-flight signal during the 98-second prompt-processing
  phase, so the SSE stream emits only the 10s heartbeat (Phase 7.18r1)
  and the user sees a frozen UI;
* `ComplianceLLM.supports_streaming_tools()` only returns True for
  `OpenAIAdapter`, so even when `event_sink` is set the orchestrator
  silently falls back to the blocking `chat_with_tools` for worker-routed
  LLMs.

**RC-3 (HIGH) — frontend has no visibility into prompt-processing.**
LM Studio emits `Prompt processing progress: 8.0%, 16.0%, …` lines but
those don't cross the WS boundary; the UI sees zero events for ~100s
between tool dispatches. The user explicitly said: *"While prompt
processing nothing happens. While tool calling nothing happens."*

**RC-4 (HIGH) — settings + chat-history disappear after app
close/reopen until Settings → SDK Worker page is visited.**
Frontend bug. The settings store loads provider config lazily on the
Settings page mount; chat history visibility is gated on the `worker`
status query that only fires after the user revisits Settings. Until
that fetch happens, the chat list and the LLM-config UI both render
their empty fallback. Needs to: (a) hydrate provider config eagerly in
`main.tsx` / app bootstrap; (b) decouple chat-history visibility from
worker readiness.

**RC-5 (MEDIUM) — model only ever called `query_regulation`.**
Across 3 iterations the model never called `crp_ckf_graph_walk`,
`crp_ckf_communities`, `recall_facts`, `pattern_query_ckf`,
`classify_ai_act_risk`, `check_high_risk_criteria`, `web_search`. The
system prompt does not strongly nudge the model to use the CKF graph
walk, fact recall, or the risk classifier when the question is about
the AI Act. Llama-3.1-8B's tool-selection bias is "first useful tool";
without explicit guidance it sticks with `query_regulation`. The CKF
ledger and recipe tooling we built are effectively dead.

**RC-6 (MEDIUM) — duplicate-tool-call dedupe was correct (it converged
to a single useful query) but the model also tried to emit two tool
calls in one turn (line 825: `Failed to parse tool call: Extra content
after end of tool call`). LM Studio's parser only kept the first; this
silently dropped a `request_clarification` call. Not currently a
blocker but it confirms the model is improvising.

**RC-7 (LOW) — stats fields on the third response are zeros.**
LM Studio's logged final response shows
`prompt_tokens=0, completion_tokens=0, total_tokens=0`. This is because
the slot was cancelled by the client disconnect and LM Studio finalised
the partial state after the fact. Confirms RC-1: our side hung up,
not LM Studio's.

### What the CRP layer did right (no regressions in this run)

* `crp_compact` ran on every iteration; no overflow recorded in the
  trace before the network error.
* `chunk:` Fact ids in the new ledger guarantee that re-fetched
  regulation chunks dedupe rather than pile up in the warm store.
* No `send_error: request exceeds context size` lines anywhere in this
  log — last round's overflow fix held.

### Fix plan applied this round

| ID | Fix | File |
|----|-----|------|
| F-1 | `WorkerAdapter` exposes `stream:true` and a token callback; backend forwards SSE chunks from the SDK worker over the WS as `{"type":"chunk",…}` frames so `on_text_delta` fires per-token. | `src/crp_comply/agent/worker_adapter.py`, `src/crp_comply/api/worker_registry.py`, `sdk/src/crp_comply_sdk/worker.py` |
| F-2 | Bump worker dispatch timeout from 120s to 600s and make it env-overridable (`CRP_COMPLY_WORKER_TIMEOUT_S`). Stream-keyed dispatches use no hard timeout — they live as long as chunks keep flowing. | `worker_adapter.py`, `worker_registry.py` |
| F-3 | `ComplianceLLM.supports_streaming_tools()` returns True for `WorkerAdapter` too. Streaming path emits `llm_phase` events (`upload`, `prompt_processing`, `generating`, `tool_dispatch`) so the frontend timeline shows continuous activity. | `src/crp_comply/agent/llm.py`, `src/crp_comply/agent/orchestrator.py` |
| F-4 | System-prompt nudge: when the user question is about a specific regulation, mandate at least one of `crp_ckf_graph_walk` / `recall_facts` after the first `query_regulation` to widen evidence. Mandate `classify_ai_act_risk` whenever the AI Act is mentioned. | `src/crp_comply/agent/orchestrator.py` system prompt |
| F-5 | Frontend: hydrate provider config + chat history list at app boot, not only on Settings/SDK worker page mount. | `frontend/src/main.tsx`, `frontend/src/store/*` |

### Next-run verification checklist

* [ ] Iter-3 generation completes (no client disconnect at +120s).
* [ ] Frontend timeline shows phase events between tool calls.
* [ ] Frontend receives streamed `llm_token` events (visible mid-generation).
* [ ] Final answer renders to the chat panel.
* [ ] Closing & reopening the app preserves provider config and chat history.
* [ ] At least 2 distinct tools fire per run (e.g. `query_regulation` +
      `classify_ai_act_risk` or `crp_ckf_graph_walk`).
* [ ] No `send_error` / `exceeds context size` lines in the LM Studio log.

---
