# CRP Comply — Local AI Enablement Audit

**Version:** Round 1 — Local LLM connection reliability  
**Date:** 2026-06-21  
**Auditor:** Kimi Code CLI  
**Scope:** All paths that connect a locally-running LLM to CRP Comply: SDK worker, BYOK local direct, reverse tunnel, operator env autodetect, managed hosting.  
**Status:** Draft — Round 3 (Multi-turn agent architecture) and Round 4 (Conversational AI enablement) now incorporated. See [`MULTI_TURN_AGENT_AUDIT.md`](MULTI_TURN_AGENT_AUDIT.md) and [`CONVERSATIONAL_AI_AUDIT.md`](CONVERSATIONAL_AI_AUDIT.md) for the full analyses.

---

## 1. Executive Summary

This report is the Round 2 companion to [`AGENTIC_AI_AUDIT.md`](AGENTIC_AI_AUDIT.md) and [`MULTI_TURN_AGENT_AUDIT.md`](MULTI_TURN_AGENT_AUDIT.md). It documents local-AI enablement and the long-turn failure modes that matter for multi-turn reasoning.

CRP Comply has **three viable methods** for connecting a local LLM:

1. **BYOK — Local direct / reverse tunnel** (OpenAI-compatible HTTP endpoint)
2. **SDK worker relay** (WebSocket outbound from user machine to hosted backend)
3. **Operator env autodetect** (server-side `CRP_COMPLY_LLM_BASE_URL`)

The SDK worker relay is the strategically important path because it enables SaaS users to keep inference on their own hardware without firewall holes. **That path is broken in ways that exactly produce “worker shows connected, but the agent gets no response.”**

The root causes are not in the WebSocket transport itself, but in the **request/response lifecycle around it**:

- The backend dispatches to a worker whose upstream LLM is not actually reachable.
- Streaming chunk send failures never emit `stream_end`, so the backend waits until a 600-second timeout.
- The backend streaming queue drops chunks silently when full and has no watchdog for lost `stream_end` frames.
- `WorkerAdapter` silently falls back from streaming to blocking on any `RuntimeError`, doubling wait time and hiding the real failure.
- Cross-user request cancellation: when one worker disconnects, all pending requests across all users are cancelled.
- The provider test/diagnose endpoints do not understand `local_worker`, so the UI misleads users about whether local mode works.
- Documentation and configuration templates are out of sync with the code, causing users to install the wrong SDK package, set ignored env vars, and run non-existent CLI commands.
- **These local-LLM failures break real-time conversational turn-taking.** A chat agent requires rapid, reliable short turns; lost `stream_end`, silent streaming→blocking fallback, and non-resumable continuation make the chat surface feel frozen or unresponsive. See [`CONVERSATIONAL_AI_AUDIT.md`](CONVERSATIONAL_AI_AUDIT.md) for the conversational-AI perspective.

### Severity summary

| Severity | Count | Representative issues |
|----------|-------|----------------------|
| Critical | 2 | Backend dispatches to unreachable LLM; streaming hangs on lost `stream_end` |
| High | 9 | Cross-user cancellation, silent streaming fallback, queue drops, reconnect storm, docs omit `[worker]` extra, test/diagnose broken for local_worker |
| Medium | 14 | Parameter dropping, Ollama path bugs, no concurrency limit, no streaming size cap, half-open sockets, etc. |
| Low | 8 | Cosmetic docs, case-sensitive scheme, token heuristic, etc. |

---

## 2. Local AI Connection Methods

### Method A — BYOK Commercial Cloud (not local, included for completeness)
- **How:** User pastes OpenAI/Anthropic/DeepInfra API key in Settings.
- **Code:** `ProviderStore` → `ComplianceLLM.for_user()` → `OpenAIAdapter` / `AnthropicAdapter`.
- **Status:** Works; not the focus of this audit.

### Method B — BYOK Local Direct / Reverse Tunnel
- **How:** User exposes local LM Studio / Ollama / vLLM via an OpenAI-compatible HTTP endpoint and pastes the URL.
- **Code:** `ProviderStore` → `validate_local_llm_url()` → HTTP probe `/models` → `OpenAIAdapter`.
- **SaaS restriction:** Private/RFC1918/`.local`/`.internal` hosts are rejected unless `CRP_COMPLY_SELF_HOSTED=1` or the deployment is not detected as cloud (Railway/Fly/Render).
- **Status:** Works when the user can expose a public HTTPS URL or is self-hosting. UI/docs mismatches cause confusion.

### Method C — SDK Worker Relay (strategic, problematic)
- **How:** User runs `crp-comply worker --lmstudio http://localhost:1234 --api-key <crp_...>` on their machine. The worker opens an outbound WebSocket to the hosted backend. The backend routes LLM requests through that socket.
- **Code:** `WorkerRegistry` / `worker_ws.py` / `WorkerAdapter`.
- **Status:** Connection succeeds; responses are lost or hang due to lifecycle bugs documented below.

### Method D — Operator Env Autodetect
- **How:** Operator sets `CRP_COMPLY_LLM_BASE_URL` + `CRP_COMPLY_LLM_API_KEY` on the server.
- **Code:** `ComplianceLLM._autodetect()`.
- **Status:** Works for operator-managed endpoints, but docs mention vars the code does not read.

### Method E — Managed / Hosted by CRP Comply
- **How:** Settings UI shows a “Hosted by CRP Comply” tile.
- **Code:** No backend implementation. `CRP_COMPLY_MANAGED_*`, `CRP_COMPLY_AZURE_*`, `CRP_COMPLY_BEDROCK_*` env vars are not referenced.
- **Status:** Not implemented; should be marked as placeholder.

---

## 3. Architecture — SDK Worker Relay

```
User machine                              Hosted backend
┌─────────────────────┐                  ┌─────────────────────────────┐
│  crp-comply worker  │ ──WSS──────────► │  /api/v1/agent/worker       │
│  (sdk worker)       │  Authorization   │  worker_ws.py               │
│                     │  Bearer <api_key>│  → auth.verify_api_key()    │
│                     │                  │  → WorkerRegistry.attach()  │
└──────────┬──────────┘                  └──────────────┬──────────────┘
           │                                            │
           │ probes local LLM                           │
           │ (/v1/models, /api/v0/models)               │
           │                                            │
           ▼                                            ▼
┌─────────────────────┐                  ┌─────────────────────────────┐
│  LM Studio / Ollama │ ◄──request────── │  Agent asks ComplianceLLM   │
│  localhost:1234     │  (over WS)       │  ComplianceLLM.for_user()   │
│  or localhost:11434 │                  │  → WorkerAdapter            │
│                     │ ──response─────► │  → WorkerRegistry.dispatch  │
└─────────────────────┘                  └─────────────────────────────┘
```

The architecture is sound: outbound WebSocket, per-user slot, no inbound firewall hole. The bugs are in the reliability of the dispatch/response loop.

---

## 4. Findings by Component

### 4.1 SDK Worker (`sdk/src/crp_comply_sdk/worker.py`)

#### W1 — Reconnect storm after clean disconnect or ready failure (High)
- **Location:** `run_worker()` lines 673–687
- **Current behavior:** On a clean return from `_run_session()`, backoff is reset to 1.0 and the loop immediately starts a new session with **no sleep**.
- **Failure:** If the relay rejects the API key, never sends `ready`, or closes the socket, the worker reconnects as fast as the event loop allows.
- **Symptom:** Worker appears connected in logs but is in a tight reconnect loop; relay rate limits; root cause masked.
- **Fix:** Always sleep `max(1.0, backoff)` before reconnecting. Reset backoff only after a successful `ready` frame.

#### W2 — Streaming chunk send failure aborts without `stream_end` (Critical)
- **Location:** `_handle_streaming_request()` lines 630–640
- **Current behavior:** If sending a `stream_chunk` frame raises, it logs a warning and returns.
- **Failure:** The backend issued a streaming request and is waiting for a terminating `stream_end` frame. That frame is never sent.
- **Symptom:** Agent request stays open; UI never sees completion or error; 600-second timeout.
- **Fix:** In the `except` block, call `_send_stream_end(error=f"failed to relay chunk: {exc}")` before returning.

#### W3 — Documentation omits the `[worker]` extra (High)
- **Location:** `docs/BYOK_MODES.md:147`, `sdk/README.md:14`, `worker.py` docstring
- **Current behavior:** Docs say `pip install crp-comply-sdk`.
- **Failure:** `websockets` is missing; worker exits with `ImportError` before any connection.
- **Fix:** Update all docs to `pip install 'crp-comply-sdk[worker]'`.

#### W4 — No response-size cap on streaming path (Medium)
- **Location:** `_handle_streaming_request()` lines 598–663
- **Current behavior:** Non-streaming path enforces `MAX_RESPONSE_BYTES` (16 MB default). Streaming path does not.
- **Failure:** Misbehaving local model can stream unbounded data.
- **Fix:** Accumulate `total_streamed_bytes` and abort with `_send_stream_end(error="response size exceeded ...")` when over limit.

#### W5 — Streaming silently drops non-SSE / malformed lines (Medium)
- **Location:** `_handle_streaming_request()` lines 611–620
- **Current behavior:** Skips anything not starting with `data: ` and silently continues on JSON parse errors.
- **Failure:** Some local servers return JSON body or malformed SSE; stream ends empty with no error.
- **Fix:** Inspect `Content-Type`; if `application/json`, treat as non-streaming. Log malformed SSE at WARNING and emit error if zero deltas forwarded.

#### W6 — Unbounded concurrent request tasks (Medium)
- **Location:** `_run_session()` lines 465–481
- **Current behavior:** Every incoming `request` frame spawns an un-`await`ed `asyncio.create_task(...)`.
- **Failure:** Tasks accumulate without limit; FD/memory exhaustion; local LLM queue deepens.
- **Fix:** Add an `asyncio.Semaphore` (default 4–8) before creating handler tasks.

#### W7 — In-flight tasks not cancelled on disconnect (Medium)
- **Location:** `_run_session()` lines 342–494
- **Current behavior:** `finally` cancels only the heartbeat task.
- **Failure:** Long-running local LLM calls continue and try to send responses on a closed socket.
- **Fix:** Keep a `set[asyncio.Task]` of active request handlers; cancel and `await` them in `finally`.

#### W8 — OpenAI request parameters silently dropped (Medium)
- **Location:** `_handle_request()` lines 206–213; `_handle_streaming_request()` lines 535–542
- **Current behavior:** Only `tools`, `tool_choice`, `temperature`, `max_tokens`, `stream` forwarded.
- **Failure:** `top_p`, `presence_penalty`, `frequency_penalty`, `response_format`, `stop`, `seed`, `logit_bias` dropped. JSON-mode requests may fail.
- **Fix:** Forward a known-safe allow-list of OpenAI fields.

#### W9 — Ollama native endpoint paths malformed when base ends in `/v1` (Medium)
- **Location:** `_handle_request()` lines 221–225; `_handle_streaming_request()` lines 545–549
- **Current behavior:** `/v1` prefix is not stripped for Ollama native paths (`/api/chat`, `/api/generate`).
- **Failure:** URL becomes `http://localhost:11434/v1/api/chat` → 404.
- **Fix:** When `upstream_kind == "ollama"` and endpoint starts with `/api/`, compute URL without `/v1` suffix.

#### W10 — API key only accepted on command line (Medium)
- **Location:** `build_parser()` line 719, `main()` lines 772–777
- **Current behavior:** `--api-key` is `required=True`; no env-var fallback.
- **Failure:** Key visible in shell history, process lists, CI logs.
- **Fix:** Make `--api-key` optional; default to `os.environ.get("CRP_COMPLY_API_KEY")`.

#### W11 — Unexpected / error frames from relay swallowed (Medium)
- **Location:** `_run_session()` lines 330–338, 420–431
- **Current behavior:** If first frame is not `ready`, logs error and returns. Sending `hello` failure swallowed.
- **Failure:** Relay auth/rate-limit errors never surface; worker reconnects forever.
- **Fix:** Parse relay error frames; exit with non-zero code on auth errors instead of reconnecting forever.

#### W12 — Non-streaming path reads raw compressed bytes (Low)
- **Location:** `_handle_request()` lines 247–261
- **Current behavior:** Uses `resp.aiter_raw()` then `json.loads(raw)`.
- **Failure:** gzip/deflate content breaks parsing.
- **Fix:** Use `resp.aread()` or `resp.aiter_bytes()`.

#### W13 — No unit tests for worker (Low/Medium)
- **Location:** `sdk/tests/test_client.py` only
- **Current behavior:** No tests for WebSocket connection, probing, streaming, reconnection, error paths.
- **Fix:** Add `sdk/tests/test_worker.py` with mocked `websockets` and `httpx`.

---

### 4.2 Backend Worker Registry (`src/crp_comply/api/worker_registry.py`)

#### R1 — Backend dispatches without checking upstream reachability (Critical)
- **Location:** `dispatch()` lines 161–207
- **Current behavior:** Does not consult `slot.upstream_reachable` before sending request.
- **Failure:** Worker socket attached and status shows green, but upstream LLM is down. Request sent anyway and hangs until 600-second timeout.
- **Symptom:** Exact “connection succeeds, response missing” scenario.
- **Fix:** Fail fast with `WorkerOfflineError("Local LLM is not reachable")` when `slot.upstream_reachable is False`.

#### R2 — `detach()` cancels all pending futures globally (High)
- **Location:** `detach()` lines 133–157
- **Current behavior:** Iterates `self._pending` and fails every pending future with `WorkerOfflineError`, regardless of user.
- **Failure:** If user A’s worker disconnects, user B’s in-flight request is cancelled.
- **Fix:** Store `(user_id, future)` in `_pending`; in `detach()`, only cancel futures belonging to the disconnecting user.

#### R3 — Streaming queue drops chunks silently when full (High)
- **Location:** `receive()` lines 256–271
- **Current behavior:** `put_nowait` raises `queue.Full`; chunk dropped; TODO logged.
- **Failure:** Tokens lost; incomplete response. If dropped item was `stream_end` or error, caller waits until timeout.
- **Fix:** Implement back-pressure: pause upstream read until queue drains, or use `put()` with timeout and propagate `WorkerError`.

#### R4 — No watchdog for lost `stream_end` (High)
- **Location:** `dispatch_streaming_from_sync()` lines 392–420
- **Current behavior:** If worker never sends `stream_end`, queue object held until 600-second timeout.
- **Failure:** Memory leak; many hung streaming requests.
- **Fix:** Add a watchdog task that injects synthetic `_error` after timeout so caller returns and resources freed.

#### R5 — Streaming fallback in WorkerAdapter hides real failures (High)
- **Location:** `src/crp_comply/agent/worker_adapter.py::generate_chat_with_tools_streaming()` lines 240–287
- **Current behavior:** Catches **any** `RuntimeError` and silently falls back to blocking call.
- **Failure:** Timeout or worker error causes second blocking dispatch, doubling wait and obscuring root cause.
- **Fix:** Only fall back for “streaming not supported” / protocol errors. Surface `WorkerTimeoutError` / `WorkerOfflineError` immediately.

#### R6 — `_pending` has no size cap (Medium)
- **Location:** `_pending` line 92
- **Current behavior:** No cap; misbehaving worker + fast retries cause unbounded memory growth.
- **Fix:** Add per-user max-in-flight limit (e.g. 5) and reject new dispatches with `WorkerBusyError`.

#### R7 — `dispatch_from_sync()` raises confusing error when no loop (Medium)
- **Location:** `dispatch_from_sync()` lines 315–335
- **Current behavior:** If `_loop is None`, raises “registry is not attached to a running event loop yet”.
- **Failure:** First request on fresh replica fails with confusing message instead of “no worker connected”.
- **Fix:** Raise user-facing “no worker connected” or capture running loop lazily.

#### R8 — `last_seen_at` mixes wall-clock and monotonic time (Low)
- **Location:** `dispatch()` lines 198–206
- **Current behavior:** `time.time()` for `last_seen_at`; rate-limit uses `time.monotonic()`.
- **Fix:** Use `time.monotonic()` consistently.

#### R9 — No server-side half-open detection (Medium)
- **Location:** `worker_ws.py` / `worker_registry.py`
- **Current behavior:** Backend only detects disconnect when `receive_json()` raises.
- **Failure:** Zombie/half-open socket can remain in `_slots` until next send.
- **Fix:** If `last_seen_at` older than 90 s, proactively close socket and detach slot.

#### R10 — Late responses dropped after timeout (Medium)
- **Location:** `dispatch()` lines 198–207
- **Current behavior:** After `asyncio.wait_for` times out, future popped. Response arriving microseconds later is dropped.
- **Fix:** Keep a small bounded orphan cache for a few seconds; log late responses.

---

### 4.3 WorkerAdapter (`src/crp_comply/agent/worker_adapter.py`)

#### A1 — All worker errors become generic `RuntimeError` (High)
- **Location:** `_dispatch()` / `_dispatch_streaming()` lines 102–172
- **Current behavior:** `WorkerOfflineError`, `WorkerTimeoutError`, `WorkerError` wrapped in `RuntimeError`.
- **Failure:** UI cannot distinguish “not connected”, “LLM unreachable”, “model not found”, “timeout”.
- **Fix:** Return structured errors with a `code` field and propagate through agent API.

#### A2 — `count_tokens()` uses fixed 3.3 chars/token heuristic (Medium)
- **Location:** `count_tokens()` lines 95–98
- **Current behavior:** Rough heuristic regardless of actual tokenizer.
- **Failure:** Context-window budgeting off by 30–50% for some models; prompts may overflow.
- **Fix:** Accept per-model tokenizer/token-count endpoint from worker; at minimum use worker-reported `model_context` to clamp.

#### A3 — `context_window_size()` guesses when worker offline (Low)
- **Location:** `context_window_size()` lines 49–90
- **Current behavior:** Falls back to `CRP_COMPLY_WORKER_CONTEXT_TOKENS` or 4096 when no worker attached.
- **Failure:** Agent packs messages using guessed window, then fails later.
- **Fix:** Return `None` or raise when no worker attached so caller fails fast.

#### A4 — `_parse_completion()` returns `arguments` as JSON string (Low)
- **Location:** `_parse_completion()` lines 312–333
- **Current behavior:** `arguments` left as string.
- **Failure:** Orchestrator may call `json.loads` and crash on malformed string.
- **Fix:** Parse with `json.loads` inside `_parse_completion`, fall back to `{"raw": ...}`.

#### A5 — Only scans last tool message for injection (Medium)
- **Location:** `_scan_outbound_messages()` lines 176–210
- **Current behavior:** Scans only the last tool message, only first 2000 chars.
- **Failure:** Earlier tool messages and assistant messages not scanned.
- **Fix:** Scan all messages before dispatch; integrate with `SafetyControlPlane`.

---

### 4.4 Provider Configuration & UI (`src/crp_comply/api/provider.py`, frontend)

#### P1 — `POST /llm/test` treats `local_worker` as HTTP provider (High)
- **Location:** `test_provider()` lines 433–511
- **Current behavior:** Tries HTTP `GET` to `base_url + "/models"` where `base_url` is `ws://relay/...`.
- **Failure:** Test connection button fails with invalid URL even when worker is healthy.
- **Fix:** Detect `local_worker` in `test_provider()`; call registry status + small probe dispatch.

#### P2 — Provider status returns `configured=True` even if worker offline (Medium)
- **Location:** `provider_status()` lines 514–579
- **Current behavior:** Returns configured for `local_worker` regardless of attachment/reachability.
- **Failure:** UI enables agent button; run times out.
- **Fix:** Combine provider config with `get_worker_registry().status(user_id)` and include `worker_attached` / `llm_reachable` flags.

#### P3 — `provider_diagnose()` not local-worker-aware (Medium)
- **Location:** `provider_diagnose()` lines 582–720
- **Current behavior:** Runs `_probe()` via `ComplianceLLM.chat()`; generic `RuntimeError` if worker offline.
- **Failure:** User cannot tell if issue is socket, upstream LLM, or model name.
- **Fix:** Explicitly check registry attachment and upstream reachability; return structured diagnosis.

#### P4 — `local_worker` config saved even if no worker attached (Medium)
- **Location:** `configure_provider()` lines 315–334
- **Current behavior:** Persists config regardless of `is_attached()`.
- **Failure:** User can configure local mode with no worker running; first agent call times out.
- **Fix:** Return warning/422 if `local_worker` selected and no worker attached, or require successful status first.

#### P5 — Model name not validated against worker-reported models (Medium)
- **Location:** `configure_provider()` lines 315–334
- **Current behavior:** Does not validate requested `model` against `slot.upstream_models`.
- **Failure:** User saves model name local LLM does not serve; first request returns 404-style error surfaced as timeout.
- **Fix:** If worker attached, compare `req.model` against `slot.upstream_models` and warn/reject unknown models.

#### P6 — RuntimeToggle uses wrong anchor IDs (Low)
- **Location:** `frontend/src/components/RuntimeToggle.tsx` → `Settings.tsx`
- **Current behavior:** Navigates to `#ai-provider` / `#sdk-worker`, but `Settings.tsx` uses `#llm` and inner card `id="byok"`.
- **Fix:** Update anchors to match actual element IDs.

#### P7 — “Hosted by CRP Comply” tile has no backend (Medium)
- **Location:** `frontend/src/pages/Settings.tsx`
- **Current behavior:** UI tile shown; no implementation.
- **Fix:** Mark as placeholder or remove until `CRP_COMPLY_MANAGED_*` / Azure / Bedrock code exists.

---

### 4.5 Documentation & Configuration

#### D1 — `docs/LOCAL_LLM_GUIDE.md` references ignored env vars (High)
- **Current behavior:** Mentions `CRP_COMPLY_PROVIDER`, `LMSTUDIO_BASE_URL`, `OLLAMA_BASE_URL`, `LLAMACPP_SERVER_URL`.
- **Code reality:** No code reads these vars.
- **Fix:** Rewrite to use `CRP_COMPLY_LLM_BASE_URL`, `CRP_COMPLY_LLM_API_KEY`, `CRP_COMPLY_LLM_MODEL`.

#### D2 — `docs/LOCAL_LLM_GUIDE.md` references non-existent CLI commands (High)
- **Current behavior:** Mentions `crp-comply llm-probe` and `crp-comply run-recipe --local`.
- **Code reality:** `crp-comply` entry point maps to `worker:main`; only `worker` subcommand exists.
- **Fix:** Replace with actual commands/API endpoints.

#### D3 — `docs/BUDGET_LLM_GUIDANCE.md` Groq setup is wrong (Medium)
- **Current behavior:** Says set `CRP_COMPLY_PROVIDER=groq` and `GROQ_API_KEY`.
- **Code reality:** `_autodetect()` needs `CRP_COMPLY_LLM_BASE_URL=https://api.groq.com/openai/v1` plus a key.
- **Fix:** Add base URL requirement.

#### D4 — `docs/BYOK_MODES.md` Mode C omits `[worker]` extra (High)
- **Fix:** `pip install 'crp-comply-sdk[worker]'`.

#### D5 — `docs/LLM_HOSTING.md` managed hosting not implemented (Medium)
- **Fix:** Mark sections as “not yet implemented” until code exists.

#### D6 — `.env.example`, `railway.toml`, `docker-compose.yml` missing active LLM vars (Medium)
- **Fix:** Add `CRP_COMPLY_LLM_BASE_URL`, `CRP_COMPLY_LLM_API_KEY`, `CRP_COMPLY_LLM_MODEL`, `CRP_COMPLY_WORKER_TIMEOUT_S`, worker env vars, with examples.

---

## 5. Root-Cause Cheat Sheet: “Connection Works, But No Response”

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Green dot, every chat hangs | W2 / R3 / R4 — `stream_chunk` send failure or lost `stream_end`; queue drops/full | Emit error `stream_end`; add queue watchdog/back-pressure. |
| Green dot, responses empty | W5 — malformed/non-SSE lines silently skipped; or W8 — `response_format` dropped | Detect JSON vs SSE; forward full OpenAI parameter allow-list. |
| Worker reconnects continuously | W1 — tight reconnect loop after clean disconnect | Sleep before reconnect; surface relay errors. |
| Worker exits immediately | W3 — `websockets` not installed | Update docs to `[worker]` extra. |
| Ollama returns 404 | W9 — `/v1` prefix not stripped for `/api/*` native paths | Special-case Ollama native paths. |
| Model ignores parameters | W8 — parameters dropped | Forward full allow-list. |
| Chat hangs after model lists OK | R1 — backend dispatches to worker whose LLM is unreachable | Fail fast on `upstream_reachable is False`. |
| One user’s disconnect cancels another’s request | R2 — `_pending` not scoped by user | Scope pending futures by user. |
| Streaming fallback hides error | R5 — WorkerAdapter catches any RuntimeError | Only fall back for protocol errors. |
| Test connection always fails for SDK relay | P1 — `POST /llm/test` not local-worker-aware | Implement local-worker-aware test. |
| UI says configured but run times out | P2 — status ignores worker attachment | Combine config + registry status. |

---

## 6. Severity-Prioritised Recommendations

### Immediate (P0 — before local-worker production usage)

1. **R1:** Fail fast in `WorkerRegistry.dispatch()` when `slot.upstream_reachable is False`.
2. **R2:** Scope `_pending` by user in `WorkerRegistry.detach()`.
3. **W2:** Worker must emit `stream_end` with error on chunk send failure.
4. **R3/R4:** Add queue back-pressure / watchdog for lost `stream_end`.
5. **R5:** Stop indiscriminate streaming fallback in `WorkerAdapter`.
6. **P1:** Make `POST /llm/test` local-worker-aware.
7. **W3:** Update all install docs to `pip install 'crp-comply-sdk[worker]'`.

### Short-term (P1)

8. **W1:** Fix reconnect storm.
9. **W6/W7:** Bound concurrency and cancel in-flight tasks on disconnect.
10. **W8:** Forward full OpenAI parameter allow-list.
11. **W5:** Improve SSE robustness (Content-Type detection, malformed-line handling).
12. **W9:** Fix Ollama native path de-duplication.
13. **W10:** Support `CRP_COMPLY_API_KEY` env var.
14. **R6:** Add per-user max-in-flight limit.
15. **R9:** Add server-side half-open detection.
16. **P2/P3:** Combine provider status/diagnose with registry state.
17. **A1:** Structured error codes from WorkerAdapter to UI.

### Polish / hardening (P2)

18. **W4:** Streaming response-size cap.
19. **A2:** Better token counting (use worker-reported context or tokenizer endpoint).
20. **A4:** Parse tool-call arguments as dict.
21. **W12:** Use `resp.aread()` for non-streaming path.
22. **W13:** Add worker unit tests.
23. **D1–D6:** Rewrite docs and configuration templates to match code.
24. **P4/P5:** Validate worker attachment and model name at configuration time.
25. **A5:** Scan all messages, not just last tool message.

---

## 7. Multi-Turn / Long-Turn Local-AI Issues

The detailed multi-turn analysis is in [`MULTI_TURN_AGENT_AUDIT.md`](MULTI_TURN_AGENT_AUDIT.md). This section records the local-AI-specific long-turn issues that interact with multi-turn reliability:

### L7.1 — Long-turn continuation is not resumable across worker disconnects

- **Location:** `src/crp_comply/agent/crp_integration.py::continue_truncated_answer()`; `src/crp_comply/agent/worker_adapter.py`
- **Current behavior:** Continuation supports up to 4 windows / 40,000 characters, but completed windows are not persisted after each window. If the worker disconnects or a `stream_end` frame is lost mid-continuation, the partially completed answer is lost.
- **Impact:** Users running long deliverables (DPIA, FRIA, Annex IV tech docs) on local LLMs may see a hang or truncation and must restart from the original prompt.
- **Fix:** Persist completed continuation windows and pending claims to the session record after each window; resume from the last completed window on worker reconnect.

### L7.2 — Small-context local models lose deterministic compliance tools

- **Location:** `src/crp_comply/agent/orchestrator.py::_fit_schemas_to_window()`
- **Current behavior:** Tool schemas are pruned or thinned when the context window is small. Tier-2/3 tools (including deterministic classifiers like `classify_ai_act_risk`, `check_dpia_required`, `estimate_fine_exposure`) can be dropped.
- **Impact:** A 4k local model answering AI Act applicability questions may have to rely solely on retrieval, weakening citation quality and accuracy.
- **Fix:** Treat deterministic compliance tools as Tier-0 (never drop), or switch to hierarchical tool selection so the full schema list is never loaded at once.

### L7.3 — Worker streaming fallback hides real failures

- **Location:** `src/crp_comply/agent/worker_adapter.py::generate_chat_with_tools_streaming()`
- **Current behavior:** On any `RuntimeError`, the adapter silently falls back from streaming to a blocking call.
- **Impact:** A worker that is struggling but still connected causes long blocking waits instead of surfacing the error. This is especially painful during multi-turn research where streaming progress events are expected.
- **Fix:** Only fall back for protocol-level errors; surface structured error codes (worker offline, context overflow, upstream unreachable) to the UI.

### L7.4 — Token budget is not enforced in the Phase-7 loop

- **Location:** `src/crp_comply/agent/loop_budget.py::LoopBudgetMeter.record_tokens()`; `src/crp_comply/agent/loop_runtime.py`
- **Current behavior:** The Phase-7 runtime records steps, wall-clock, clarifiers, and plan revisions, but not prompt/completion tokens.
- **Impact:** Long multi-turn research on a local LLM can exceed the intended token/context budget without aborting, increasing latency and risk of context-overflow failures.
- **Fix:** Plumb token counts from `ComplianceLLM` / `WorkerAdapter` back into `LoopBudgetMeter.record_tokens()`.

### L7.5 — Reflector confidence path is wired but never fires

- **Location:** `src/crp_comply/agent/reflector.py` lines 199–213; `src/crp_comply/agent/loop_runtime.py`
- **Current behavior:** The Reflector can emit `clarify_first` when confidence is below 0.6, but the runtime never passes a confidence value.
- **Impact:** A valuable automatic clarification trigger is dormant, which matters on local models that may be less calibrated.
- **Fix:** Derive or expose a per-turn confidence signal from the local LLM response metadata and pass it to `Reflector.evaluate()`.

### L7.6 — `CrpMessageLedger` facts do not survive across Phase-7 steps

- **Location:** `src/crp_comply/agent/loop_runtime.py::_execute_step()`; `src/crp_comply/agent/orchestrator.py::ComplianceAgent.run()`
- **Current behavior:** Each Phase-7 step spins a fresh `ComplianceAgent` with a fresh `CrpMessageLedger`/`WarmStateStore`.
- **Impact:** Facts extracted in one step are not automatically available in the next unless they are relayed into the CKF and recalled. Local-worker latency makes this re-fetch expensive.
- **Fix:** Maintain one CRP session/client per user session and reuse its warm store across steps.

---

## 8. Multi-Turn Cross-Reference

- [`MULTI_TURN_AGENT_AUDIT.md`](MULTI_TURN_AGENT_AUDIT.md) — Round 3 report covering Phase-7 loop state, research→analysis→synthesis→citation gaps, web-search sidecar integration, CRPv4 context/state primitive gaps, and full recommendations.

---

## Appendix A — Files referenced

- `sdk/src/crp_comply_sdk/worker.py`
- `sdk/src/crp_comply_sdk/_client.py`
- `sdk/pyproject.toml`
- `sdk/README.md`
- `src/crp_comply/api/worker_registry.py`
- `src/crp_comply/api/worker_ws.py`
- `src/crp_comply/agent/worker_adapter.py`
- `src/crp_comply/agent/llm.py`
- `src/crp_comply/api/provider.py`
- `src/crp_comply/api/llm_security.py`
- `frontend/src/pages/Settings.tsx`
- `frontend/src/components/RuntimeToggle.tsx`
- `frontend/src/lib/api.ts`
- `docs/BYOK_MODES.md`
- `docs/LOCAL_LLM_GUIDE.md`
- `docs/BUDGET_LLM_GUIDANCE.md`
- `docs/LLM_HOSTING.md`
- `.env.example`
- `railway.toml`
- `docker-compose.yml`
- `MULTI_TURN_AGENT_AUDIT.md`

## Appendix B — Related skills

- `crp-v4-protocol-reference`
- `crp-v4-agentic-ecosystem`
- `crp-v4-ai-safety`
- `crp-v4-context-management`
- `crp-v4-capability-map`
- `crp-comply-codebase`
