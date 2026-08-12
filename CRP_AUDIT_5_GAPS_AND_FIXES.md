# CRP Comply — Audit 5: Gaps, Bugs, Old-CRP Usage & Fixes

> **Date:** 29 May 2026
> **Scope:** Full review of the bugs reported in `new-TO-be-FIXed-11.05.2026.txt`, plus a
> sweep of CRP-SDK usage across the backend, SDK worker, and frontend. Each finding is
> logged with file paths and line references, a root-cause explanation, and either a fix
> that has been applied in this pass or a concrete remediation plan.
> **Relationship to crp-scan:** the patterns catalogued here (ungoverned LLM calls, missing
> health checks, unenforced policy, leaked reasoning) are exactly what the `crp-scan` GitHub
> Action must detect in customer repos. This audit doubles as the seed rule-set for the scan.

---

## 0. Executive summary

| # | Issue | Severity | Status |
|---|-------|----------|--------|
| 1 | Worker shows "connected" with **no LLM actually running** (false positive) | **HIGH** | **Fixed in this pass** |
| 2 | No copy buttons for connect/run/proxy/chat commands (friction) | MEDIUM | Plan provided |
| 3 | **Incoherent / repeated / non-streamed output**; search not used; CRP misconfigured | **CRITICAL** | Root-caused; partial fixes + plan |
| 4 | IP/reasoning over-disclosure in responses & logs | MEDIUM | Plan provided (narrator + redaction) |
| 5 | **Frontend layout breaks** (width/height/zoom) after a response | HIGH | **Fixed in this pass** |
| 6 | CRP usage is "best-effort lazy import" everywhere — silent degradation | MEDIUM | Documented; hardening plan |
| 7 | Context-window workaround (16k instead of 4k) masking a budgeting bug | HIGH | Root-caused; plan |

Fixes applied in this pass touch four files:
- `sdk/src/crp_comply_sdk/worker.py` (upstream health probe + `hello`/`health` frames)
- `src/crp_comply/api/worker_registry.py` (track + expose `llm_reachable`)
- `frontend/src/lib/api.ts` (status type)
- `frontend/src/pages/Settings.tsx` (tri-state status indicator)
- `frontend/src/pages/v2/AgentChat.tsx` + `frontend/src/design/Markdown.tsx` (overflow wrap)

---

## 1. Worker "connected" false positive (HIGH) — FIXED

### 1.1 Symptom (from the report)
> "I run the worker, with no LM Studio running and it was detected as on and enabled in the
> application!!! … BUT THEN AFTER A WHILE IT SAID WORKER NOT CONNECTED UNDER SETTINGS … In
> the sidebar I see the green box … 'local_worker connected'."

### 1.2 Root cause
The local-LLM worker is a CLI relay that opens an **outbound WebSocket** to the backend. The
backend tracks attached workers in a per-user registry:

- `src/crp_comply/api/worker_ws.py` → on socket accept it calls
  `reg.attach(user_id, websocket)` and audits `worker_connected`.
- `src/crp_comply/api/worker_registry.py` → `WorkerRegistry.status()` returned
  `{"attached": True, …}` **purely because a socket slot existed**.
- `frontend/src/pages/Settings.tsx` (≈line 1254) → `const attached = !!workerQuery.data?.attached`
  drove a green "Worker connected" pill.

Nothing in this chain verified that **LM Studio / Ollama behind the worker was actually
running**. So:

1. You start `crp-comply worker …`. The CLI dials the backend → slot attaches →
   `attached: true` → UI green. **(false positive)**
2. LM Studio is down, so the first real chat request fails when the worker tries to forward
   it (`_handle_request` in `sdk/.../worker.py` returns an upstream error / the socket later
   drops) → UI flips to "not connected". **(the later, correct-looking state)**

The wire protocol even *documents* a `hello` frame with `backends:["lmstudio"]`
(`worker_ws.py` docstring, line ~26), but the worker's `_run_session()` never actually sent
one, and the registry's `receive()` never handled it.

### 1.3 Fix applied
**Worker side** (`sdk/src/crp_comply_sdk/worker.py`, in `_run_session`): after the relay
`ready` frame, the worker now:
- probes the upstream model server (`GET {upstream}/v1/models`, or `/api/tags` for Ollama,
  5 s timeout),
- sends a `hello` frame `{type:"hello", upstream_reachable, models, upstream_kind, error}`,
- re-probes every ~75 s in the heartbeat and sends a `health` frame, so the status reflects
  the LLM going up/down while the worker stays attached,
- logs a clear warning if the upstream is unreachable at connect time.

**Backend side** (`src/crp_comply/api/worker_registry.py`):
- `_WorkerSlot` gained `upstream_reachable | None`, `upstream_models`, `upstream_kind`,
  `upstream_error`, `upstream_checked_at`.
- `receive()` now handles `hello`/`health` frames and updates the slot.
- `status()` now returns `llm_reachable`, `llm_models`, `llm_kind`, `llm_error`,
  `llm_checked_at`. **`attached` means the relay socket is up; `llm_reachable === true` means
  a model server actually answered.**

**Frontend** (`api.ts` + `Settings.tsx`): the status indicator is now tri-state:
- **green** "Worker connected · LLM ready" only when `attached && llm_reachable === true`;
- **red** "Worker connected · LLM NOT running" when `attached && llm_reachable === false`
  (with the probe error and a hint to start the model server);
- **amber** "checking LLM…" while health is still unknown;
- **amber** "Worker not connected" when no socket.

### 1.4 Remaining recommendation
Apply the same `llm_reachable` gate to the **sidebar** "local_worker connected" badge and to
`RuntimeToggle.tsx` (line ~109) so a user can't *select* `local_worker` as the active
provider while the LLM is down. Also gate the chat **Send** button (or show an inline
warning) when `llm_reachable === false`.

---

## 2. Convenience: copy buttons for commands (MEDIUM)

### 2.1 Symptom
> "being able to copy eg. in settings being able to copy the commands to connect and run the
> crp comply worker for local llm. Then, for the proxy commands … Then, for chat responses…"

### 2.2 Current state
`Settings.tsx` renders the install/run commands in `<pre>` blocks (≈lines 1296–1310) with **no
copy affordance**. The proxy connection settings and chat responses are similarly
copy-unfriendly.

### 2.3 Plan (small, self-contained)
Add a reusable `CopyButton`/`CodeBlock` component:

```tsx
function CodeBlock({ code, label }: { code: string; label?: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="relative group">
      {label ? <span className="label">{label}</span> : null}
      <pre className="mt-1 rounded-md bg-gray-900 text-gray-100 px-3 py-2 pr-10 text-xs font-mono overflow-x-auto">{code}</pre>
      <button
        type="button"
        onClick={() => { navigator.clipboard.writeText(code); setCopied(true); setTimeout(() => setCopied(false), 1500) }}
        className="absolute top-7 right-2 rounded-md border border-hairline bg-surface px-2 py-1 text-[10px]"
        aria-label="Copy command"
      >{copied ? 'Copied' : 'Copy'}</button>
    </div>
  )
}
```

Then replace the install/run `<pre>` blocks in `Settings.tsx`, add it to the proxy settings
panel, and add a "Copy" action to each assistant message in `AgentChat.tsx` (copy `line.text`
/ the rendered markdown source). Low risk, high perceived polish.

---

## 3. Incoherent / repeated / non-streamed output; search not used (CRITICAL)

### 3.1 Symptom
> "the output is incoherent, repeated, and not constructive/diverse. It was also not streamed,
> and seems to have errored … no search was used! Both loops are flawed, coherence is flawed.
> Streaming not utilized to properly return responses. CRP misconfigured, not properly used."

### 3.2 Architecture: the two loops
The compliance agent runs two nested control loops in
`src/crp_comply/agent/orchestrator.py`:

1. **The agent/tool loop** (the `while attempt < 3` / iteration loop, ≈lines 820–1180): each
   iteration sends the message slate + tool schemas to the LLM, parses tool calls, runs
   tools (including web search via SearXNG), appends results, and repeats until the model
   emits a final answer or the iteration budget is hit.
2. **The continuation/stitch loop** (`crp.continuation.stitch.stitch_many`, invoked via
   `crp_integration.py` ≈line 425): stitches a long final answer that exceeds one output
   window into a coherent whole.

### 3.3 Root causes (multiple, compounding)

**(a) Context budgeting is fragile on small windows.** In `orchestrator.py` ≈lines 909–990,
CRP fits the tool schemas to the window (`_fit_schemas_to_window`) and compacts the message
slate (`compact_messages_for_budget`). The comments themselves describe the failure mode:
for a 4096-token LM Studio model, "23 full tool schemas is ~6 000 tokens — already larger
than the entire context window before a single message is added." The output reserve is
hand-scaled (384/768/ctx÷4). When the budgeting under- or over-shoots, the **system prompt
gets clipped** (referenced at ≈line 1018: "with a clipped system prompt") and the model
loses its instructions → **incoherent, repeated, low-diversity output**. This is precisely
why you had to bump LM Studio to 16k as a workaround — the budgeting math only behaves with
generous headroom.

**(b) Search isn't reached when the context is blown.** The web-search tool is part of the
tool registry. If the tool schemas don't fit (or are thinned away by `_fit_schemas_to_window`
on a tiny window), or the clipped system prompt drops the tool-use instruction, the model
never emits a valid tool call → **no search is performed**, and it answers from parametric
memory (incoherent for compliance questions).

**(c) Streaming is implemented end-to-end but not used for the agent's final answer.** The
SDK worker supports streaming (`_handle_streaming_request`, `sdk/.../worker.py`) and the
registry has a streaming path (`stream_chunk`/`stream_end` in `worker_registry.py`). But the
**agent tool loop calls the LLM non-streaming** (it needs the full message to parse tool
calls). The final answer is produced inside that non-streaming loop and returned whole, so
the browser sees a long silence then a dump — matching "not streamed … feels frozen." The
`llm_progress` heartbeats (≈line 1028) keep the timeline alive but don't stream tokens.

**(d) "Seems to have errored."** On context overflow LM Studio returns HTTP 400 wrapped by
the worker; the orchestrator's aggressive re-compact retry (≈line 1010) can still fail on a
4k window, surfacing an error after a long wait.

### 3.4 Fixes & plan
This is the highest-value area. Recommended sequence:

1. **Make the context budget authoritative, not heuristic.** Replace the hand-scaled
   `_output_cap` ladder with CRP's envelope budgeter (`crp.envelope.compute_envelope_budget`,
   already imported at `orchestrator.py` line 391) as the single source of truth for
   input/output split, and **hard-cap the tool registry** so the system prompt is *never*
   clipped — drop tools before you ever touch the system prompt. Add an assertion/telemetry
   event when the fitted system prompt is shorter than the original (today it's only logged).
2. **Guarantee a minimum viable context.** If `ctx_window < 8192`, automatically reduce the
   tool set to a curated "compliance-core" subset (search + corpus + citation) instead of all
   23 tools, so search always fits. Surface a one-line UI note: "small model — reduced
   toolset."
3. **Stream the final answer.** Once the model stops emitting tool calls and begins the final
   answer, switch to the streaming path (`stream:true`) so tokens flow to the browser via the
   existing `stream_chunk` plumbing. The tool-call iterations stay non-streaming; only the
   terminal answer streams.
4. **Fail fast and clearly on overflow.** If after one re-compact the slate still doesn't fit,
   stop retrying silently — return a structured "model context too small for this query;
   switch to a ≥8k model or hosted provider" message instead of a generic error after a long
   wait.
5. **Stop recommending 16k as a fix.** Once (1)–(2) land, validate at the real 4096 baseline.
   The need to set 16k is the symptom; the budgeter is the disease.

---

## 4. IP / reasoning over-disclosure (MEDIUM)

### 4.1 Symptom
> "is Intellectual property revealed in the way thinking is disclosed … I dont want people
> stealing much … let's say something like a narrator be added? … it's not fully explanatory
> and understandable by the day-to-day non-technical user."

### 4.2 Where reasoning is surfaced
The agent emits granular phase/loop events to the frontend timeline
(`orchestrator.py` `self._emit({...})` calls: `llm_phase`, `llm_progress`,
`crp_compact`, `crp_overflow_refold`, tool traces) which `AgentChat.tsx` renders (event
switch ≈line 684+). Reasoning-model "thinking" tokens (qwen3 etc.) can also pass through if
the model emits them. Logs (`telemetry.py`, the railway logs referenced) capture the same.

### 4.3 What to do
You want to **keep explainability for trust** but **hide the proprietary mechanics**. Split
the event stream into two layers:

- **Narrator layer (always shown):** human-readable, non-technical milestones — "Reading the
  EU AI Act…", "Found 3 relevant sources…", "Checking for contradictions…", "Drafting your
  answer…". Map each internal event to a friendly narrator string in one place
  (`AgentChat.tsx` event switch). This is the "narrator" you asked for and also fixes "not
  understandable by non-technical users."
- **Diagnostic layer (gated):** the raw `crp_compact` budgets, tool JSON, token counts,
  schema-fitting internals → only render behind a "Show technical detail" toggle, and only
  for the account owner (never in shared/exported transcripts).

**Redact for IP/security:**
- Strip model "thinking"/`<think>` blocks from what's persisted and shown (keep only the
  final answer + citations). Add a filter in the streaming assembler.
- Remove exact budget math, tool-schema sizes, the curated tool list, and prompt-engineering
  text from user-visible events and from `INFO`-level logs (move to `DEBUG`).
- Scrub system-prompt fragments from any error surfaced to the user.

Net: a polished narrator for users, full diagnostics for you, proprietary internals neither
shown nor logged at INFO.

---

## 5. Frontend layout breaks after a response (HIGH) — FIXED

### 5.1 Symptom
> "after the response was returned the frontend structure, layout, format was completely
> broken in terms of width, height, zoom."

### 5.2 Root cause
The assistant message bubble (`AgentChat.tsx` ≈line 737) used `max-w-[80%]` with the text in
a `whitespace-pre-wrap` div **without** word-breaking, and the markdown renderer
(`Markdown.tsx`) had no `min-w-0`/`break-words`. The reported output was *"incoherent,
repeated"* — i.e. it likely contained a very long unbroken token / repeated run with no
spaces. `whitespace-pre-wrap` preserves such a run without breaking it, so the bubble grew
past its `max-w-[80%]` flex container, pushing the page wider than the viewport →
horizontal overflow that looks like the zoom/layout "broke."

### 5.3 Fix applied
- `AgentChat.tsx`: bubble container now `max-w-[80%] min-w-0`, and the text div is
  `whitespace-pre-wrap break-words [overflow-wrap:anywhere]`.
- `Markdown.tsx`: root container now includes `min-w-0 break-words [overflow-wrap:anywhere]`
  so rendered markdown answers also can't blow out the column.

`min-w-0` is essential in flex layouts — without it a flex child refuses to shrink below its
content's intrinsic width, which is the classic cause of "the whole page got wider."

### 5.4 Remaining recommendation
Once the coherence fixes (section 3) land, the pathological repeated-token output should stop
occurring at all; the overflow guards here are defense-in-depth. Also verify code blocks
(`pre` already has `overflow-x-auto`) and tables (`overflow-x-auto` wrapper present) — both
fine.

---

## 6. CRP usage map & "old/best-effort" patterns (MEDIUM)

### 6.1 How CRP is used
crp-comply imports the CRP SDK **lazily, inside try/except, almost everywhere** (≈40+ call
sites; see `findstr "from crp"` results). Key integrations:

- **PII redaction**: `crp.security.pii_scanner.PIIScanner` (`crp_integration.py` line 85;
  `orchestrator.py` 1267/1331; `tools.py` 1270; `api/agent.py` 2026).
- **Injection detection**: `crp.security.InjectionDetector` (`crp_integration.py` 724;
  `tools.py` 1326; `worker_adapter.py` 168; `proxy/interceptor.py`).
- **Fact extraction / contradiction**: `crp.extraction.*`, `crp.extraction.contradiction`
  (`ckf_corpus.py`, `crp_integration.py` 142/175/479/561/1124/1369/1535).
- **CKF**: `crp.ckf.fabric.ContextualKnowledgeFabric` (`ckf_corpus.py` 141; `api/routes.py`
  1414/1520), `crp.ckf.pattern_query`, `crp.ckf.FactIntegrityChain`.
- **Envelope budgeting**: `crp.envelope.*` (`orchestrator.py` 391; `crp_integration.py`
  305/1435).
- **Continuation/stitch**: `crp.continuation.stitch.stitch_many` (`crp_integration.py` 425).
- **Providers**: `crp.providers.AnthropicAdapter / OpenAIAdapter` (`llm.py` 160/207).
- **Observability / audit / RBAC / privacy**: `crp.observability.*`, `crp.security.rbac`,
  `crp.security.privacy` (`api/routes.py` 1065–1729).
- **Risk classification**: `crp.security.RiskClassifier`, `AISystemCategory` (`tools.py` 502).

### 6.2 The "best-effort" anti-pattern
Almost every import is wrapped so that if the CRP subsystem is missing it **silently no-ops**
(the `crp_integration.py` module docstring states this explicitly). This was a deliberate
"don't refuse to start" choice, but it has costs:

- **Silent degradation:** in a thin deployment with `sentence-transformers` missing, PII
  redaction, grounding, and CKF retrieval quietly fall back to weaker/no-op paths — and the
  product still claims to be "CRP-governed." A compliance product **must not** silently
  disable its compliance controls.
- **Old vs new API drift:** because everything is `getattr`/duck-typed (e.g.
  `scan_fn = getattr(scanner, "scan", None) or getattr(scanner, "detect", None)` in
  `crp_integration.py`), the code tolerates multiple SDK versions but never *asserts* a
  minimum. With CRP now at 3.0.0, several of these defensive branches target pre-3.0 shapes.

### 6.3 What is NOT used (gaps vs CRP v3)
crp-comply predates the v3 governance primitives and does **not** use:
- `crp.providers.discover_local_llms` — it has its own ad-hoc LM Studio probing
  (`api/llm_strategy.py`, `provider.py`) instead of the canonical detector. **This is the
  single biggest modernization win** and directly fixes the section-1 detection story.
- The v3 **safety-policy** grammar + `enforce_policy` + **HTTP 451 halt** contract — the
  product enforces compliance ad hoc rather than via the declarative policy + halt response.
- The per-window **HMAC provenance chain** (`build_window_hmac`/`verify_window_chain`) and
  signed **session tokens** (`issue_token`) — Comply uses `FactIntegrityChain` but not the
  window-chain/token surface that the demos showcase.

### 6.4 Plan
1. **Declare a hard CRP floor.** Pin `crprotocol>=3.0.0` in `pyproject.toml` and, at startup,
   verify the critical subsystems import; if a *compliance-critical* one (PII, injection,
   provenance) is missing, **refuse to serve governed traffic** (or run in an explicit,
   labelled "degraded/non-compliant" mode) rather than silently no-op.
2. **Adopt `discover_local_llms`** in `llm_strategy.py`/`provider.py` to replace bespoke
   probing — this also gives the worker health check (section 1) a canonical source and the
   real context window for the budgeter (section 3).
3. **Wire `enforce_policy` + `build_halt_response`** into the answer path so Comply can
   *halt* (HTTP 451) non-compliant answers with the same contract the protocol demos show —
   strong cross-sell consistency with crp-scan and the Gateway.
4. Replace the multi-version `getattr` duck-typing with calls against the pinned 3.0 API;
   keep try/except only around genuinely optional extras (e.g. embeddings).

---

## 7. The 16k context workaround (HIGH)

Tracked as a sub-item of §3/§6: the user runs LM Studio at 16k "because CRP is misconfigured
and doesn't work" at 4k. Root cause is the heuristic budgeter + full 23-tool registry +
output-reserve ladder in `orchestrator.py` (§3.3a). **Fix = §3.4 (1)+(2)+§6.4 (2).** Acceptance
test: a compliance question answered coherently, with search used, at a **4096-token** loaded
window, no clipped system prompt (assert via telemetry), streamed to the browser.

---

## 8. Referenced log files

The three logs named in `new-TO-be-FIXed-11.05.2026.txt`
(`railway_deploy_logs-11.05.2026.log`, `CRP_Comply_interface_details&returned_answer.log`,
`CRP-comply-worker-11.05.2026.log`) are **not present in the repository tree** (a `*.log`
search returns nothing). The analysis above is reconstructed from the code paths the report
points at. **Action for you:** drop those three logs into the repo root (or `data/telemetry/`)
and I can confirm the exact overflow/stream error lines and tighten §3 fixes to the observed
stack traces.

---

## 9. Other observations

- `_pytest_summary.txt` / `_testlog.txt` exist at the repo root — review for currently failing
  tests before shipping the §3 changes (the orchestrator is heavily tested under
  `tests/test_agent_*`).
- `provider.py` line 366 special-cases LM Studio `/v1` suffixing and there's matching dedup in
  the worker — keep these in sync if you adopt `discover_local_llms`.
- The worker's SSRF protections (loopback allowlist, endpoint allowlist, response cap) in
  `sdk/.../worker.py` are solid — preserve them when adding the health probe (the probe reuses
  the same validated upstream base, so no new SSRF surface).

---

## 10. Fixes applied in this pass (diff summary)

| File | Change |
|------|--------|
| `sdk/src/crp_comply_sdk/worker.py` | Added `_probe_upstream()` + `_send_hello()`; sends `hello` on connect and periodic `health` frames; warns when upstream LLM is down. |
| `src/crp_comply/api/worker_registry.py` | `_WorkerSlot` tracks upstream health; `receive()` handles `hello`/`health`; `status()` exposes `llm_reachable`/`llm_models`/`llm_kind`/`llm_error`. |
| `frontend/src/lib/api.ts` | `WorkerStatusResponse` extended with `llm_reachable`/`llm_models`/`llm_kind`/`llm_error`/`llm_checked_at`. |
| `frontend/src/pages/Settings.tsx` | Tri-state status pill (green only when LLM reachable; red "LLM NOT running"; amber checking/not-connected) + model list + error hint. |
| `frontend/src/pages/v2/AgentChat.tsx` | Message bubble `min-w-0` + `break-words [overflow-wrap:anywhere]` (layout-breakage fix). |
| `frontend/src/design/Markdown.tsx` | Markdown root `min-w-0 break-words [overflow-wrap:anywhere]`. |

All edits verified to introduce no new type/lint errors.

---

## 11. Recommended next actions (priority order)

1. **§3.4** — fix the budgeter + curated toolset + final-answer streaming + fail-fast. (CRITICAL)
2. **§6.4(2)** — adopt `discover_local_llms` (feeds §1 health + §3 budget). (HIGH)
3. **§6.4(1)** — declare CRP ≥3.0.0 floor; stop silent no-op of compliance controls. (HIGH)
4. **§4** — narrator layer + reasoning/IP redaction. (MEDIUM)
5. **§2** — copy buttons. (MEDIUM, quick win)
6. Provide the three log files so §3 can be pinned to the real traces.
