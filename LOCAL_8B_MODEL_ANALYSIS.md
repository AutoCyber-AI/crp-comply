# Local 8B Model Failure Analysis — CRP Comply Agent

**Date:** 2026-06-29  
**Model under test:** `meta-llama-3.1-8b-instruct` (Q4_K_M, LM Studio)  
**Context length:** 8 196 tokens  
**SDK:** `crp-comply-sdk` 0.4.2  
**Backend:** `crp-comply` 0.1.2 (built, not yet deployed to `comply.crprotocol.io`)  
**Test query:** *"Which capabilities satisfy GDPR?"*

---

## 1. Executive Summary

The worker → WebSocket → backend path is **healthy**. The 8 196-token context window **does** prevent the previous `400 Context size exceeded` error. However, the compliance agent still fails to produce an answer on an 8B parameter local model because the **agent loop, system prompt, and tool surface are sized for 70B+/frontier models**, not for 8B local inference.

The failure is **not** a WebSocket issue, a context-window issue, or a networking issue. It is a **capability-mismatch issue** between the agent’s current design and what an 8B model can reliably execute.

---

## 2. What We Observed

From the worker logs:

1. Worker connected and stayed connected.
2. Health probes (`GET /v1/models` + `GET /api/v0/models`) fired every **60 seconds** — exactly the designed heartbeat cadence (20s ping × 3 ticks). This is expected.
3. The first agent prompt contained **3 779 tokens** and took **116 seconds** of prompt eval.
4. The model returned a `recall_facts` tool call.
5. The second prompt contained **2 385 tokens** and took **78 seconds**.
6. The model returned another `recall_facts` call with slightly different, semantically empty arguments (`entity_type: "capability"`, `relationship_type: "satisfies"`).
7. The UI/browser stopped waiting around **81 %** of the second prompt eval.
8. No final answer was produced.

The repeated `recall_facts` calls are the key behavioral signal: the 8B model is **lost in the tool set** and is using retrieval as a safe fallback instead of producing a grounded answer.

---

## 3. Root-Cause Analysis

### 3.1 The prompt is too large for an 8B model to reason over

Measured from the current code base:

| Component | Size |
|-----------|------|
| System prompt (`SYSTEM_PROMPT`) | ~4 518 chars ≈ **1 291 tokens** |
| Full tool schemas (13 tools) | 8 280 chars ≈ **3 312–4 140 tokens** |
| Fitted tool schemas at 8K window | 13 tools ≈ **4 140 tokens** |
| Per-turn primers (`crp_evidence_primer`, `crp_session_context`, `crp_ckf_seed`) | several hundred tokens each |
| User query + prior-step observations | ~100–300 tokens |
| **Total first prompt** | **3 779 tokens** (observed) |

For an 8B model, consuming ~3 800 tokens of densely formatted system instructions + JSON tool schemas consumes most of its available "headroom" before any reasoning begins. The model has to:

- remember the long system contract,
- choose among 11+ tools,
- emit correctly shaped JSON arguments,
- follow multi-step instructions ("call `query_regulation` at least once", "widen the evidence base", "cite chunk_ids", "stop when you have enough evidence").

8B models can do **some** of these reliably; they cannot do **all** of them reliably in one call.

### 3.2 Too many tools are exposed at once

At an 8K context window the current `_fit_schemas_to_window()` fits **all 13 tools**, including no-code/demo tools (`plan_recipe`, `explain_nocode_capability`, `list_nocode_presets`, `get_nocode_preset`) and the CRP continuation tool (`crp_get_continuation_state`).

For the test query *"Which capabilities satisfy GDPR?"*, the relevant tools are:

- `query_regulation` / `query_regulation_packed`
- `lookup_gdpr`
- `web_search`
- `request_clarification`

The other 9 tools are noise to an 8B model. Each additional tool:

- increases the chance of selecting the wrong tool,
- increases the chance of hallucinating parameters,
- increases prompt eval time.

The schema fitter currently optimizes only for **token budget**, not for **model capability**. An 8K window can hold 13 tool schemas, but an 8B model cannot reliably choose among them.

### 3.3 The system prompt is written for a senior compliance analyst

`SYSTEM_PROMPT` is ~1 300 tokens of dense instructions:

- six numbered method rules,
- answer-quality rules,
- citation rules,
- explicit tool-use rules,
- prohibition rules ("do not invent chunk_ids", "do not paraphrase from memory", etc.).

Frontier models handle this well. 8B models tend to:

- latch onto the **most recent or most emphasized** rule,
- miss higher-priority rules (e.g., "call `query_regulation` at least once"),
- over-use a tool that was mentioned as an example (e.g., `recall_facts` was listed as one of several options, so the model keeps using it).

The observed repeated `recall_facts` calls are consistent with an 8B model fixating on one instruction fragment instead of synthesising the whole plan.

### 3.4 Streaming tool calls are unreliable with Llama 3.1 8B in LM Studio

The logs show tool arguments arriving **one token per SSE chunk**:

```
arguments: "{"
arguments: "\""
arguments: "entity"
arguments: "_type"
arguments: "\":"
...
```

LM Studio’s OpenAI-compatible endpoint is streaming the raw token sequence without constraining it to the tool schema. Two consequences:

1. **Latency:** each token adds a round-trip through the worker’s stream parser.
2. **Correctness:** the model can drift outside the JSON schema because there is no grammar/constrained decoding being applied.

LM Studio does support tool calling, but for 8B models it is far less robust than Ollama’s tool mode or vLLM’s guided decoding.

### 3.5 The agent loop is iterative and multi-turn by design

The current `ComplianceAgent` loop:

1. Triages the query.
2. Runs a planner.
3. Iterates up to `max_iters` calling tools.
4. Reflects on each step.
5. Optionally continues truncated answers.
6. Produces a final answer.

Each iteration is a full LLM call. With the observed **~80–115 s per call**, three iterations already exceed **3–4 minutes**. Browser/SSE frontends typically time out or appear dead after 60–120 s without visible progress.

The loop assumes the model is fast enough and capable enough that iteration is cheap. For an 8B local model, iteration is **expensive and error-prone**.

### 3.6 There is no "weak model" adaptation path

The agent has one behavior regardless of:

- model parameter count,
- context length,
- local vs hosted,
- tool-call reliability.

There is no code path that says: *"If the model is ≤8B / local / slow, use a simpler single-shot retrieval-and-answer strategy."*

CRP the protocol is model-agnostic. The CRP Comply agent is currently **not** model-adaptive.

### 3.7 The deployed backend is still the previous image

The new `0.1.2` backend adds:

- 5-second `llm_progress` heartbeats to keep the UI alive during long local inference,
- a stale-slot guard so dead workers are evicted quickly,
- more conservative context budgeting.

Because the backend has not been redeployed yet, the UI receives none of these improvements, which makes the slow local model feel "completely stuck" even when the worker is still streaming.

---

## 4. Why an 8B Model Cannot Currently Operate the Agent

Combining the above:

| Requirement of current agent | 8B model reality |
|------------------------------|------------------|
| Parse and retain 1 300-token system prompt + 11 tool schemas | Marginal — consumes most reasoning budget. |
| Select the right tool from 11 options | Poor — fixates on one tool, repeats calls. |
| Emit valid JSON tool arguments in a streaming endpoint without grammar | Unreliable — token-by-token, easy to drift. |
| Execute a 3–4 turn ReAct loop with reflection | Too slow (~4 min+) and error-prone. |
| Produce cited, structured compliance answers | Weak — tends to omit citations or hallucinate chunk_ids. |
| Stay within UI attention span | No — prompt eval alone is >90 s. |

The result is that the agent **technically runs** but **does not complete a useful interaction**.

---

## 5. Recommendations to Make 8B Models Work

These are architectural/product changes, not band-aids.

### 5.1 Introduce a model-capability profile

Add a capability tier derived from the reported model context/identity or from an explicit setting:

- `FRONTIER` (Claude/GPT-4 class) — full iterative agent.
- `LOCAL_CAPABLE` (Qwen2.5-7B+, Mistral-7B+, etc.) — reduced tool set, blocking tool calls, no reflection.
- `LOCAL_SMALL` (≤8B, Llama-3.1-8B, etc.) — single-shot retrieval + answer, 3–4 tools only.

### 5.2 Dynamic tool selection

For a query classified as GDPR, expose only:

```
query_regulation
lookup_gdpr
web_search
request_clarification
```

For a simple onboarding/FAQ query, expose **zero tools** and answer directly from the system prompt + retrieved snippets.

### 5.3 Add a single-shot mode for local small models

A new code path that:

1. Classifies intent.
2. Retrieves the most relevant 2–3 regulation chunks.
3. Sends **one** LLM call with a shortened system prompt.
4. Returns the answer.

No ReAct loop, no reflection, no continuation.

### 5.4 Shorten the system prompt for weak models

Create `SYSTEM_PROMPT_LIGHT` (~300–400 tokens):

- One-sentence role.
- One instruction: "Use `query_regulation` to find clauses, then answer."
- Citation format.

### 5.5 Disable streaming tool calls for unreliable local endpoints

Respect `CRP_COMPLY_WORKER_STREAMING_TOOLS=0` and use blocking completions. Where possible, request JSON-mode or constrained decoding from the server.

### 5.6 Add loop and stall guards

- If the same tool is called with semantically equivalent arguments twice, force a final answer.
- If total wall time exceeds a configurable threshold (e.g., 90 s), return a partial/interim answer.
- If the model produces only tool calls for N turns without a final answer, fall back to a direct answer.

### 5.7 Frontend: longer SSE timeout + progress events

The `0.1.2` backend already emits `llm_progress` every 5 s. The frontend should:

- Keep the connection open for at least 300 s.
- Render progress events ("Thinking…", "Retrieving GDPR clauses…", etc.).

### 5.8 Test harness for local models

Create a CI-style benchmark that runs a fixed set of simple queries against a local LM Studio / Ollama instance and asserts:

- answer is returned within 120 s,
- no repeated identical tool calls,
- final answer is non-empty.

### 5.9 Reduce health-probe noise

Make the upstream re-probe interval configurable and default to every 6 heartbeats (120 s) instead of every 3 (60 s). Heartbeat pings still keep the WebSocket alive.

---

## 6. Immediate Workarounds Until Code Changes Land

1. **Use a larger local model.** `qwen2.5-7b-instruct` or `qwen3-4b` follow tool schemas noticeably better than Llama-3.1-8B.
2. **Use Ollama instead of LM Studio.** Ollama’s tool mode applies chat templates and grammar more reliably for small models.
3. **Set `CRP_COMPLY_AGENT_DISPATCH_MODE=plain` on the backend.** This bypasses the iterative compliance tool loop for simple Q&A. Not suitable for real compliance reports.
4. **Deploy the `0.1.2` backend.** The progress-heartbeat improvement alone makes the experience less "stuck."

---

## 7. Conclusion

CRP the protocol and the worker relay are **working as designed** with an 8B model. The problem is that the **compliance agent loop is not designed for 8B models**. To fulfill the product goal of "local 8B, no problems," the agent needs a **capability-adaptive mode** that trades some of the deep multi-tool reasoning for reliability and speed on small local LLMs.

The shortest path to a working demo is a **single-shot, intent-classified, reduced-tool agent mode** for local small models.
