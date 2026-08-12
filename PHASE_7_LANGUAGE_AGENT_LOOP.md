# Phase 7 — The Language Agent Loop

> Plan only. No code.
>
> This document specifies the next architectural step for CRP Comply:
> turning the orchestrator from a single-shot question-answerer into a
> **language agent** — a self-relooping LLM that perceives its own
> outputs, plans, calls tools, asks smart clarifiers without breaking
> the loop, streams every token of its reasoning to the UI, and
> produces a deliverable.
>
> The grievance this fixes: today the user sends a query, the agent
> answers in one shot (or fails silently when the corpus is empty),
> and the UI has nothing to show in between. There is no visible
> "thinking", no visible tool use, no visible regulation deep-dive,
> no continuous feedback. Recipes exist but are wired as one-shot
> generators rather than as targets for the loop.

---

## 1. What we're building, in one paragraph

A **multi-turn autonomous reasoning loop** inside the compliance
agent. On every user query the agent:

1. **Plans** — emits a structured plan (steps, tools, recipe targets).
2. **Loops** — for each step, retrieves from the CKF, calls a tool,
   reflects on the output, and decides whether to continue, branch,
   or stop.
3. **Clarifies in-loop** — when a step needs information only the
   user has, it pauses with a *targeted* question, resumes on answer,
   and never restarts from scratch.
4. **Streams** — every token of every internal turn is pushed to the
   UI as a typed event, so the user watches the agent think, retrieve,
   call tools, and write the deliverable in real time.
5. **Produces** — the loop terminates with one or more recipe-backed
   artefacts, each stitched to the citations the loop actually used.

Conceptually this is the **language agent** pattern (AutoGPT,
ReAct, Reflexion, Voyager) adapted to a domain where every step
must cite a regulation and every artefact must round-trip to the
evidence binder.

---

## 2. Research summary — what the literature actually says

The user asked us to research multi-turn LLM operations of the
"language agent" / "self-relooping" nature. The relevant literature
clusters around six patterns. We adopt three; we explicitly reject
two; we hybridise one.

### 2.1 Adopted patterns

* **ReAct** *(Yao et al., 2023)* — interleave `Thought / Action /
  Observation` triples. The model emits a thought, picks a tool,
  reads the observation, and continues. This is the right backbone
  for compliance work because every Action maps cleanly onto a CKF
  retrieval mode or a recipe call. We adopt ReAct as the **primary
  step format**.

* **Reflexion** *(Shinn et al., 2023)* — after each step the model
  produces a short self-critique that becomes part of the next
  step's context. Critical for compliance: it lets the agent
  notice "I cited Article 6 but the user is a deployer not a
  provider — Article 16 applies". We adopt Reflexion as the
  **per-step critique pass**, gated to one critique per N steps to
  avoid token blow-up.

* **Plan-and-Solve** *(Wang et al., 2023)* — the model first emits
  a typed plan, then executes. Better than pure ReAct for tasks
  with a predictable shape (which compliance is). We adopt this
  for the **planning prologue** but allow the loop to revise the
  plan mid-flight (this is "Plan-and-Solve + revision", closer to
  Reflexion-Plan).

### 2.2 Rejected patterns

* **AutoGPT-style open-ended self-prompting.** Open recursion
  with no termination criterion is wrong for an audit-grade tool
  — it produces unbounded cost and unverifiable artefacts. We
  enforce a **hard step budget** and **per-recipe completion
  predicate**.

* **Tree-of-Thoughts** *(Yao et al., 2023)*. Tree search over
  reasoning branches is overkill for compliance: the right
  obligation is rarely ambiguous if the CKF is properly typed. We
  prefer linear ReAct + targeted retries.

### 2.3 Hybrid

* **Toolformer-style implicit tool calls** vs. **explicit tool
  calls**. We use **explicit, schema-validated tool calls** (OpenAI
  / Anthropic function-calling shape) because we need to log every
  tool invocation for the audit trail. But we ship a *fallback*
  parser that extracts implicit `[tool: query_regulation(...)]`
  patterns from raw text streams when the upstream model doesn't
  honour the function-calling schema (LM Studio, llama.cpp).

### 2.4 Reference points

| Concept | Source | What we take |
|---|---|---|
| Thought/Action/Observation | ReAct (Yao 2023) | step format |
| Self-critique loop | Reflexion (Shinn 2023) | per-step verifier |
| Typed plan first | Plan-and-Solve (Wang 2023) | prologue |
| Tool-use schema | OpenAI / Anthropic tool calling | wire format |
| Persistent reasoning across turns | Voyager (Wang 2023) | skill memory in CKF |
| Long-horizon multi-step | DeepSeek-R1, OpenAI o1 | reasoning-token budget |
| Streaming "thinking" UX | Anthropic Claude `thinking` blocks; ChatGPT o1 reasoning UI | event taxonomy |

---

## 3. The architecture (no code, but specific shapes)

### 3.1 The five-layer stack

```
┌──────────────────────────────────────────────────────────┐
│  UI layer (frontend/src/components/AgentRun.tsx)         │
│   typed event stream → live tape view, tool cards,       │
│   citation rail, clarifier modal (non-blocking)          │
└──────────────────────────────────────────────────────────┘
                       ▲ Server-Sent Events
┌──────────────────────────────────────────────────────────┐
│  Transport (api/agent.py)                                │
│   /agent/start_stream    /agent/continue_stream          │
│   /agent/loop_stream  ← NEW: pure-loop endpoint that     │
│                          reuses the session record       │
└──────────────────────────────────────────────────────────┘
                       ▲
┌──────────────────────────────────────────────────────────┐
│  Loop runtime (agent/loop.py — NEW)                      │
│   plan() → step() × N → finalise()                       │
│   emits LoopEvent stream, owns step budget,              │
│   owns clarifier suspension/resume                       │
└──────────────────────────────────────────────────────────┘
                       ▲
┌──────────────────────────────────────────────────────────┐
│  Orchestrator (agent/orchestrator.py)                    │
│   per-step LLM call with tool schema, ReAct prompt,      │
│   prior_messages replay, primer injection                │
└──────────────────────────────────────────────────────────┘
                       ▲
┌──────────────────────────────────────────────────────────┐
│  Tools                                                   │
│   query_regulation, pattern_query, graph_walk,           │
│   community_summary, temporal_query, recall_facts,       │
│   run_recipe (NEW),  ask_user (NEW),                     │
│   record_artefact (NEW)                                  │
└──────────────────────────────────────────────────────────┘
```

The new layer is **`agent/loop.py`**. It sits between the orchestrator
(which today does a single LLM call) and the API (which today wraps
that single call in SSE). The loop runtime is a finite state machine
over `LoopState`.

### 3.2 The loop state machine

```
                  ┌──────────┐
   user query ──▶ │ PLANNING │─── plan emitted ──▶ ┌──────┐
                  └──────────┘                     │ STEP │ ◀──┐
                                                   └───┬──┘    │
                                                       │       │
                  ┌──────────┐                         ▼       │
   user answer ──▶│ AWAITING │ ◀── ask_user ──┐  ┌─────────┐   │
                  │  USER    │                └──│ ACTING  │   │
                  └────┬─────┘                   └────┬────┘   │
                       │                              │        │
                       └──── resume ──────────────────┤        │
                                                      ▼        │
                                                  ┌────────┐   │
                                                  │REFLECT │───┘
                                                  └───┬────┘
                                                      │ done?
                                                      ▼
                                                  ┌────────┐
                                                  │FINALISE│ ──▶ artefacts
                                                  └────────┘
```

States:

* `PLANNING` — first LLM call. Output: typed plan
  `[{step_id, intent, target_recipe?, tool_hint, success_predicate}]`.
* `STEP` — pick the next not-done step.
* `ACTING` — LLM call with ReAct prompt + tool schema; streams tokens;
  ends in either a tool call or a text-only "I have enough info".
* `REFLECT` — a short critique LLM call: "did the observation satisfy
  the success predicate? are we still on plan?". Can mutate the plan
  (insert/remove/reorder steps).
* `AWAITING_USER` — entered when the model emits the `ask_user` tool.
  The session is suspended in-place; the loop's local state is
  serialised; the UI surfaces a clarifier card; on user answer the
  loop resumes from exactly the same step with the answer fed in as
  the next observation. **No restart, no replan unless the answer
  contradicts an earlier assumption.**
* `FINALISE` — runs the bound recipe(s), writes artefact records,
  emits a `final` event with citations.

### 3.3 The event taxonomy (SSE)

The single most important deliverable of this phase. Every event has
`event:` (type), `data:` (JSON payload), `id:` (monotonic), and
`session_id`.

| `event:` | When | Payload |
|---|---|---|
| `loop.opened` | session bound | `{session_id, query, model}` |
| `loop.plan` | plan emitted | `{steps: [{id, intent, tool_hint}]}` |
| `loop.step.start` | step entered | `{step_id, intent, attempt}` |
| `loop.thought.delta` | per-token | `{step_id, text}` |
| `loop.tool.call` | tool dispatched | `{step_id, tool, args}` |
| `loop.tool.result` | tool returned | `{step_id, tool, summary, citations}` |
| `loop.reflection` | critique done | `{step_id, verdict, notes, plan_delta?}` |
| `loop.clarifier.ask` | `ask_user` fired | `{step_id, question, slot_id, options?}` |
| `loop.clarifier.answer` | user answered | `{slot_id, answer}` |
| `loop.step.end` | step closed | `{step_id, status: ok|skipped|failed}` |
| `loop.recipe.start` | recipe invoked | `{recipe_id, inputs}` |
| `loop.recipe.delta` | recipe emits chunks | `{recipe_id, kind, text}` |
| `loop.recipe.done` | recipe finished | `{recipe_id, artefact_id}` |
| `loop.final` | loop terminated | `{artefacts, summary, total_steps}` |
| `loop.error` | unrecoverable | `{message, step_id?}` |
| `loop.heartbeat` | every 5s when idle | `{state}` |

The **`loop.thought.delta`** stream is the answer to "WE NEED
CONTINUOUS DISPLAY OF WHAT THE AGENT IS DOING". It is the per-token
stream of the model's reasoning (same shape that ChatGPT o1 / Claude
"thinking" exposes), tagged with which step it belongs to.

### 3.4 The frontend tape

`frontend/src/components/AgentRun.tsx` (NEW) renders the events as a
**reasoning tape**:

```
┌────────────────────────────────────────────────────────┐
│ ▶ Plan (3 steps)                                       │
│   1. Identify obligations triggered by your role       │
│   2. Map them to your AI system metadata               │
│   3. Generate the Annex IV technical file              │
├────────────────────────────────────────────────────────┤
│ ◐ Step 1: Identifying obligations                  ⏱ 4s│
│   Thinking: "User is a deployer of a high-risk AI      │
│   system in the EU. Article 26 obligations apply..."   │
│                                                        │
│   ⚒ query_regulation(query="deployer high-risk")       │
│     → 12 facts from EU AI Act Articles 26, 27, 29      │
│   ⚒ graph_walk(seed="Article 26", depth=2)             │
│     → 3 cross-refs to Article 13, 14, Annex IV         │
│                                                        │
│   ✓ Reflection: "Coverage adequate. Moving to step 2." │
├────────────────────────────────────────────────────────┤
│ ⏸ Step 2: Mapping to your AI system                    │
│   ⚒ ask_user                                           │
│     ┌──────────────────────────────────────────────┐   │
│     │ Does your system process biometric data?     │   │
│     │   ○ Yes  ○ No  ○ Sometimes                   │   │
│     │                                              │   │
│     │   [ Answer and resume ]                      │   │
│     └──────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────┘
```

Key UX rules:

* The **clarifier modal is non-modal** — the rest of the tape stays
  visible and scrollable. Other steps that don't depend on the
  pending answer (parallel branches) can keep running.
* **Tool cards** are collapsible. Citations on the right rail are
  click-through to the EUR-Lex / official source.
* **Token-level streaming** uses CSS animation only on the latest
  delta to avoid layout thrash.
* On reconnect, the SSE endpoint **replays from `Last-Event-ID`** so
  refreshes don't lose the tape.

---

## 4. The loop's prompts (specification, not source)

### 4.1 Planner prompt

> System: "You are a compliance reasoning planner. Output a JSON
> plan with 1–6 steps. Each step has `intent`, `tool_hint` from
> {`query_regulation`, `pattern_query`, `graph_walk`,
> `community_summary`, `temporal_query`, `recall_facts`,
> `run_recipe`, `ask_user`, `none`}, an optional `target_recipe`
> from the recipe catalogue, and a `success_predicate` describing
> what evidence is sufficient to mark the step done. Do not produce
> the answer. Plan only."
>
> User: `<original query>`
>
> Primer: tenant CKF facts + corpus CKF facts (already in place).

### 4.2 Step (ACTING) prompt

> System: "You are executing step `<step_id>` of the plan
> `<plan>`. Use the ReAct format: emit one Thought, then either
> a tool call (preferred) or a final 'I have enough info'. Do not
> answer the original user question yet. Cite Facts by id."
>
> Conversation: prior steps' compressed `Thought + Tool result`
> tuples; max ~3000 tokens via the existing message scorer.
>
> Tools: full schema, only the `tool_hint` tool is recommended but
> the model may pick another.

### 4.3 Reflector prompt

> System: "Critique the latest Step. Did the tool result satisfy
> `success_predicate`? Should the plan be revised? Output JSON:
> `{verdict: ok|retry|skip|insert_step, notes, plan_delta?}`. Be
> terse — at most 80 tokens."

### 4.4 Finaliser prompt

> System: "Compose the final artefact using the recipe `<recipe_id>`
> and the Facts gathered in steps `<step_ids>`. Emit one section at
> a time so the UI can stream them. Cite every claim by Fact id."

---

## 5. Tools — what's new

### 5.1 `ask_user(question, slot_id, options?, schema?)`

The single most important new tool. It does **not** end the loop.
It:

1. Emits `loop.clarifier.ask`.
2. Snapshots `LoopState` to the session record.
3. Suspends the asyncio task with `asyncio.Future`.
4. The HTTP endpoint `/agent/clarifier_answer` resolves the future
   with the user's answer; the loop resumes.
5. The answer is appended to the step's observation buffer and the
   step **does not restart** — it continues from where it was.

The `slot_id` is reused if the same clarifier is asked twice across
steps so we don't double-prompt the user (idempotency on the user's
mental model).

### 5.2 `run_recipe(recipe_id, inputs)`

The bridge the user complained was missing. Recipes today are
isolated artefact generators; this tool **lets the loop pick a
recipe by id, hand it the gathered Facts, and stream its output
back as `loop.recipe.delta` events**. That is the connection
between "deep regulation dive" and "produces the deliverable".

The recipe registry already exists (`tests/test_batch7_recipes.py`).
We expose a `list_recipes()` introspection method for the planner.

### 5.3 `record_artefact(kind, content, citations)`

Persists the artefact into the existing reports store. Returns an
`artefact_id` the UI can link to.

### 5.4 Existing tools — minor surface change

* All tools must now accept and return a `step_id` for event
  tagging.
* All tools must emit `citations: [{fact_id, chunk_id, source_url}]`
  in their result so the citation rail can render.

---

## 6. Termination, budgets, and safety

A language agent without termination criteria is a runaway. The loop
enforces:

| Bound | Default | Why |
|---|---|---|
| Max steps | 12 | Empirically enough for any single recipe |
| Max LLM tokens / loop | 60,000 | Cost cap |
| Max wall-clock | 5 min | Operator-tunable |
| Max consecutive `retry` verdicts | 2 | Prevents thrash |
| Max `ask_user` per loop | 6 | UX limit — beyond this we batch |
| Plan revision limit | 3 | Prevents replan thrash |

Termination conditions:

1. All planned steps marked `ok` and finaliser produced an artefact.
2. Any budget exceeded → emit `loop.final` with `partial: true` and
   the artefacts produced so far.
3. Reflector verdict `skip` on the only remaining step.
4. Hard error from a tool that the reflector can't recover.

Every termination produces a `loop.final` event — the UI never has
to guess "is it still running?".

---

## 7. Persistence and resumability

### 7.1 What goes in the session record

```
{
  session_id, tenant_id, user_id,
  query, model, started_at,
  plan: [...],
  steps: [{step_id, status, thoughts, tool_calls, observations,
           reflections}],
  pending_clarifier: {slot_id, question, asked_at} | null,
  budget_used: {steps, tokens, wall_seconds},
  artefacts: [...],
  events_offset: <last SSE id>
}
```

### 7.2 Why this matters

The user can close the browser and come back. The loop, if still
running, keeps emitting events to the session bus; if suspended on
a clarifier, it stays suspended. On reconnect, the frontend opens
SSE with `Last-Event-ID` and replays from there.

### 7.3 Storage

Reuse the existing reports store under a new `agent_loops/` table.
No migration needed — additive.

---

## 8. Backwards compatibility

* The existing `/agent/start` and `/agent/start_stream` endpoints
  stay. They internally now run a **degenerate loop** (single step,
  no plan) so behaviour is unchanged for callers that don't opt in.
* The new behaviour is opted into via either:
  - `POST /agent/loop_stream` (new endpoint), or
  - `POST /agent/start_stream` with header `X-CRP-Loop: enabled`.
* All existing tests continue to pass (the orchestrator's
  `run(prior_messages=...)` signature is preserved).

---

## 9. Tests we will write (in Phase 7 implementation, not now)

1. **Plan emission test** — given a query, the planner emits valid
   JSON with at least one step.
2. **Loop happy path** — mock LLM emits plan → 2 steps → finalise;
   assert exactly the expected event sequence on SSE.
3. **Clarifier suspend/resume** — assert the loop state persists
   across `ask_user`, `clarifier_answer` resumes the same step.
4. **Budget enforcement** — assert `loop.final` with `partial: true`
   when step budget exhausted.
5. **Plan revision** — Reflector returns `insert_step`, assert the
   plan grows and the new step is executed before resumption.
6. **Recipe binding** — assert `run_recipe` events stream through
   the same SSE channel and the artefact is persisted.
7. **Citation propagation** — every tool result's citations end up
   in the final artefact's derivation manifest.
8. **SSE replay** — disconnect mid-loop, reconnect with
   `Last-Event-ID`, assert no duplicates and no gaps.

---

## 10. Phasing inside Phase 7

This is too large for a single PR. Subdivide:

| Sub-phase | Scope | Gate |
|---|---|---|
| 7.0 | Event taxonomy + new SSE skeleton (no loop logic) | All current tests still green |
| 7.1 | `LoopState` FSM + Planner step + degenerate single-step loop | Unit tests on FSM transitions |
| 7.2 | ReAct step prompt + tool dispatch + observation streaming | Replace single-shot orchestrator path |
| 7.3 | `ask_user` + suspend/resume + frontend clarifier card | E2E suspend test |
| 7.4 | Reflector + plan revision | Plan-revision unit test |
| 7.5 | `run_recipe` tool + recipe streaming | Round-trip artefact test |
| 7.6 | Frontend reasoning tape component | Visual QA against fixture event log |
| 7.7 | Budgets, replays, hardening | Soak test |

Each sub-phase is releasable; the system gracefully degrades to
the previous behaviour at every gate.

---

## 11. What we will *not* do in this phase

* No tree search / branching plans (rejected; see §2.2).
* No memory consolidation across loops into the *corpus* CKF —
  loops only write to the *tenant* CKF.
* No autonomous off-hours runs ("agent that runs while you sleep").
  Phase 8 territory; we keep Phase 7 user-driven.
* No multi-agent collaboration (one loop = one agent).

---

## 12. Why this directly answers the user's complaints

| Complaint | This phase's response |
|---|---|
| "I see only a failed RAG, no CKF anywhere" | The loop's first step *always* hits the CKF via `pattern_query`/`graph_walk`; the `loop.tool.call` event surfaces it. CKF visibility is built into the UX, not just a backend feature. |
| "Inability to provide long responses that show thinking" | `loop.thought.delta` streams every reasoning token. The tape view renders it live. |
| "Recipes seem disconnected" | `run_recipe` tool binds the loop's gathered Facts directly into recipe inputs. The reasoning tape shows the recipe streaming its sections. |
| "Smart clarifier without breaking the loop" | `ask_user` suspends in place; the loop resumes from the same step on answer. No restart, no context loss. |
| "Continuous display of what the agent is doing" | The 16-event taxonomy in §3.3 covers planning, thinking, tool calls, tool results, reflection, clarifiers, recipes, and termination — all streamed as SSE. |
| "Multi-turn LLM operations of the language-agent nature" | §2 maps directly onto ReAct + Reflexion + Plan-and-Solve, which is the canonical language-agent stack. |

---

## 13. Open questions for the user before we implement

1. **Reasoning visibility default.** Should `loop.thought.delta` be
   on by default for all tenants, or gated behind a "deep
   reasoning" toggle (some compliance officers may prefer to see
   only conclusions)? Default proposal: **on**, with a toggle to
   collapse.
2. **Clarifier UX.** Inline in the tape, or as a slide-over panel?
   Default proposal: **inline card** (less context-switching).
3. **Budget defaults.** §6's defaults err on the generous side. Are
   the cost implications acceptable, or should we tighten to 8
   steps / 30k tokens?
4. **Model split.** Should the Planner and Reflector use a smaller
   model than the Actor (cheaper, faster), or all the same model?
   Default proposal: **same model** for v1, split in v2 once we
   have routing telemetry.

These don't block writing the plan, but they will shape the first
PR.

---

## 14. The fast path — don't enter the loop unless you need to

The user's correct objection: a language agent that always runs the
full Plan → Step × N → Reflect → Finalise pipeline is wasteful and
slow for trivial queries. A great agent **knows when not to loop**.
This section bolts a two-tier fast/slow architecture onto §3.

### 14.1 What we steal from `wasa_ai-master`

We have two production-grade pieces sitting on disk that we should
port directly rather than reinvent:

| File | Surface | Reuse |
|---|---|---|
| `wasa_ai/core/orchestration/query_classifier.py` | `QueryClassifier.classify(query) -> QueryClassification` with `TRIVIAL / SIMPLE / MODERATE / COMPLEX / COMPREHENSIVE` levels via hybrid zero-shot NLI + keyword heuristics | The triage layer, retuned with compliance-domain keywords (`gdpr`, `dpia`, `annex iv`, `gpai`, `obligation`, `controller`, `processor`, etc.) and intent classes (`define`, `cite`, `assess`, `produce_artefact`, `audit_existing`). |
| `wasa_ai/core/intent/classifier.py` | `PatternMatch` — O(1) deterministic patterns before the LLM | First-line intent triage. Compliance has very stable surface forms (`"what does X say about Y"`, `"generate a DPIA for Z"`, `"am I in scope for W"`). Pattern hits skip the loop entirely. |
| `wasa_ai/chat/session_manager.py` | `MessageRelevanceScorer` (already partly ported in Phase 6) | Carry compliance-tuned high-value keywords (`finding`, `obligation`, `non-compliance`, `cite`, `article`) into our existing scorer. |
| `wasa_ai/llm/continuation_manager.py` | `CompletionChecker.check_completion()` with structural + task-requirement predicates | Inverted into our **Reflector** as the "is this step done?" oracle, so we don't always ask the LLM to self-critique. |
| `wasa_ai/rag/ddg_rate_limiter.py` | Process-wide DDG rate limiter | Drop-in for any DuckDuckGo path. |

What `wasa_ai` does **not** have and we therefore must add ourselves:

* **LLM response cache.** No `@lru_cache`/redis/semantic cache anywhere
  in their RAG pipeline. We will add one.

### 14.2 The five mechanisms — which we adopt and how

Mapping the user's six mechanisms onto our concrete plan:

| Mechanism | Decision | Implementation in CRP Comply |
|---|---|---|
| **1. Pre-loop query classification** | **Adopt** | New `agent/triage.py`. Combines wasa-ai's pattern matcher (O(1)) and complexity scorer. Emits `TriageResult { complexity, intent, confidence, fast_path_action }`. |
| **2. Caching / memoisation** | **Adopt (two layers)** | (a) **Exact-match cache** keyed by SHA-256 of `(query, tenant_id, corpus_version)`, sqlite-backed under `data/cache/agent_responses.db`. TTL = corpus version lifespan. (b) **Semantic cache** keyed by embedding similarity ≥ 0.92 against past answers — same query in different words returns the cached answer + a "similar to a question you asked X minutes ago" UX hint. |
| **3. Fast-path / two-tier** | **Adopt** | The **fast path** runs synchronously inside the request and returns sub-second. The **slow path** is the §3 loop. Triage decides which one. |
| **4. Early stopping** | **Adopt** | Reflector's `verdict: ok` after step 1 short-circuits to Finalise. Confidence threshold 0.85. Also: if the planner's first plan has ≤1 step, we skip the planner round-trip on the next similar query (planner cache). |
| **5. Intent and context awareness** | **Adopt** | The triage's intent classification + active session's `MessageRelevanceScorer` decide whether the query is a follow-up that just needs context replay vs. a fresh query that needs the full loop. |
| **6. Goal-planning phase as a router** | **Adopt** | Same idea as our Planner step, but with an explicit `should_loop: bool` field in the plan output. If `false`, the orchestrator returns the plan's preamble directly. |

### 14.3 The three lanes

```
                          ┌──────────────────────┐
  user query  ─────────▶  │   TRIAGE (sync, <50ms) │
                          └──────┬─────────┬─────┘
                                 │         │         │
              ┌──────────────────┘         │         └──────────────────┐
              ▼                            ▼                            ▼
     ╔════════════════╗          ╔════════════════════╗      ╔══════════════════╗
     ║ LANE A         ║          ║ LANE B             ║      ║ LANE C           ║
     ║ Cache Hit      ║          ║ Fast Path           ║      ║ Slow Path (Loop) ║
     ║ (exact/semantic)║          ║ (single-shot CKF +  ║      ║ Plan → Step×N    ║
     ║                ║          ║  primer LLM call)   ║      ║ → Reflect → Final║
     ║ <100 ms        ║          ║ 1–3 s              ║      ║ 5 s – 5 min      ║
     ╚════════════════╝          ╚════════════════════╝      ╚══════════════════╝
              │                            │                            │
              └────────────────────────────┴────────────────────────────┘
                                           ▼
                                  same SSE event taxonomy
                                  (so the UI is uniform)
```

**Lane selection rules:**

* **Lane A (Cache):** triage finds an exact-or-semantic cache hit
  with `corpus_version` still current and the tenant's CKF
  version unchanged since the cached answer.
* **Lane B (Fast Path):** triage classifies as `TRIVIAL` or
  `SIMPLE`, OR a deterministic pattern matched (e.g. "cite Article
  6 GDPR"), OR the intent is `define` / `cite` and the CKF has a
  high-confidence single-fact answer (`pattern_query` returns one
  Fact with `confidence ≥ 0.9`).
* **Lane C (Slow Path):** everything else — `MODERATE`,
  `COMPLEX`, `COMPREHENSIVE`, or any intent that targets a recipe
  (`produce_artefact`, `audit_existing`).

**Even Lane A and Lane B emit the same event taxonomy** so the UI
doesn't branch — see §14.6.

### 14.4 The compliance-tuned classifier

The planner's first system message asks for a structured plan
*including* `should_loop`. But before we even reach the planner LLM,
the triage runs:

1. **Pattern pass** (O(1)). About 30 hand-curated patterns:
   - `r"(what|how|where) does (the )?(gdpr|eu ai act|nis2|...) (say about|define|treat) ..."` → `intent=define`, `complexity=SIMPLE`
   - `r"(cite|reference|find) (article|annex|recital) \d+"` → `intent=cite`, `complexity=TRIVIAL`
   - `r"(generate|produce|draft) (a |the )?(dpia|annex iv|conformity declaration|risk assessment)"` → `intent=produce_artefact`, `complexity=COMPREHENSIVE`
   - `r"am i (in scope|subject to|covered by) ..."` → `intent=scoping`, `complexity=MODERATE`
2. **Complexity heuristics** if no pattern matched:
   - Query length, count of distinct regulation references, presence
     of comparison words ("vs", "versus", "difference between"),
     conjunctions, multi-clause structure.
3. **Intent classifier** (lightweight, a CPU-bound TextClassifier or
   even keyword frequency). 6 intents: `define`, `cite`, `scope`,
   `compare`, `produce_artefact`, `audit_existing`.
4. **Confidence calibration.** If neither pattern nor heuristic is
   confident, default to `slow_path` (safe fallback).

### 14.5 The cache layer — exact + semantic

| Layer | Key | Backing | TTL |
|---|---|---|---|
| Exact | sha256(`tenant_id` + `corpus_version` + `ckf_version` + normalised(`query`)) | sqlite under `data/cache/` | invalidated on corpus or tenant CKF version bump |
| Semantic | embedding of `query`, retrieved via cosine ≥ 0.92 over the same scope | reuses the existing sqlite-vss index | same |
| Plan cache | sha256(`tenant_id` + `query_intent` + `query_complexity_bucket`) → cached plan skeleton | sqlite | 24 h |

Cache writes happen on `loop.final` for any answer with at least one
citation and reflector verdict `ok`. Cache reads happen in triage,
**before** planner. UX: when Lane A fires, the SSE stream emits
`loop.cache.hit` and renders a small "answered from cache · 17 min
ago · same regulation version" banner so the user trusts the
shortcut. **Always include a "Re-run from scratch" button** so the
user can force the slow path.

### 14.6 Uniform UX across all three lanes

This is where the trust signal lives. The user's complaint was
"continuous display of what the agent is doing". Even on Lane A
(cache hit) we should still show the **provenance trail**:

```
✓ Triage: 12 ms — recognised pattern "define GDPR term"
✓ Cache: hit (semantic, 0.94 similarity to "what does GDPR mean by controller?")
✓ Citations preserved: GDPR Article 4(7), Recital 79
> [answer streamed]
[Re-run from scratch] [Why this answer?]
```

For Lane B:

```
✓ Triage: 18 ms — TRIVIAL · intent=cite
✓ CKF query: 2 facts, both confidence ≥ 0.95
> [answer streamed in one LLM call with the facts as context]
```

For Lane C: the full Phase 7 reasoning tape from §3.4.

---

## 15. CKF integration — the loop must *use* the graph, not just have it

The loop's value collapses if the model ignores the CKF. We make
that impossible by structurally biasing the prompts and making the
CKF the **primary observation surface**.

### 15.1 Five concrete bindings

1. **Primer injection** (already in Phase 6). The system primer
   carries the top-K corpus CKF facts most relevant to the query
   (selected by semantic match before the loop starts). This is
   the agent's *lemma stack* — facts it can cite without a tool
   call.
2. **`tool_hint` bias.** The Planner system prompt mandates: *"For
   any step whose `intent` references a regulation, the
   `tool_hint` MUST be one of `pattern_query`, `graph_walk`,
   `community_summary`, or `temporal_query` — not `web_search` —
   unless the regulation is not in the corpus."* The CKF goes
   first, the web is a fallback.
3. **CKF coverage check at termination.** The Reflector's success
   predicate explicitly includes: *"Every claim about a regulation
   is backed by a CKF Fact id."* Reflector verdict can return
   `retry` if a step produced uncited claims.
4. **`recall_facts` as default observation.** Every step's
   observation buffer is automatically prefixed with the latest
   `recall_facts(query=<step_intent>, max=5)` results. The model
   doesn't have to remember to call it — it's pre-fetched.
5. **Citation-first generation.** The Finaliser's prompt forces a
   *citations array* before any prose: `[{fact_id, fact_text,
   chunk_id, source_url}, ...]`. The artefact body must reference
   these by id. This makes uncited claims structurally impossible
   to emit.

### 15.2 Federated fabric wrapper

Today the orchestrator queries the per-tenant CKF and the corpus
CKF separately. We wrap both behind a single `FederatedFabric`
class that:

* Routes `pattern_query` / `graph_walk` / `community_summary` to
  both fabrics in parallel.
* Tags each returned Fact with its origin (`scope: corpus | tenant`).
* De-duplicates on `fact.id`.
* Surfaces them with a `provenance: {origin, source_id, chunk_id, source_url}` block per Fact.

This way the existing tools stay unchanged — they see one fabric.
The UI surfaces both layers in the citation rail.

### 15.3 The CKF telemetry the UI shows

Per-step events surface CKF activity so the user *sees* the graph
working:

```
⚒ pattern_query("controller obligations under GDPR")
  ├─ corpus CKF: 8 facts (Articles 5, 6, 24, 28, 32, Recitals 71, 74, 79)
  └─ tenant  CKF: 1 fact (your DPIA from 2026-03)
⚒ graph_walk(seed="GDPR Art 24", depth=2)
  └─ 14 cross-refs traversed → 6 unique facts cited
```

This is the proof signal. Compliance officers see the agent
*walking the regulation graph*, not "asking ChatGPT".

---

## 16. Web search — when CKF is silent

The CKF covers the regulations we've shipped. It cannot answer:

* "What did the EDPB publish *yesterday*?"
* "Is there an enforcement action against [company] under DSA?"
* "What's the latest CJEU ruling on legitimate interest?"
* "Has the EU AI Act delegated act on biometric categorisation
  been adopted yet?"

These are **the** questions where compliance officers lose nights.
We need a web search tool — but we need it to be opinionated,
trust-scored, and audit-grade.

### 16.1 What we already have on disk

We have **two** production-grade web-search implementations sitting
in adjacent repos:

| Source | Path | Provider | Trust scoring | Reusable? |
|---|---|---|---|---|
| `AutoBlog Strapi` | `services/web_search_service.py` | DuckDuckGo + BeautifulSoup full-page fetch | Yes — Tier 1: NIST/NVD/CISA/OWASP/MITRE/CertOrg; Tier 2: vendors; blocked: social media. Domain trust 0.0–1.0. | **Yes — port directly.** Already exposes `POST /research { topic, depth }` and `POST /search { q, n }`. |
| `wasa_ai-master` | `wasa_ai/rag/dynamic_web_rag.py` + `ddg_rate_limiter.py` | DuckDuckGo + SearxNG with security-domain trust scoring | Yes | Lighter; we'd take the rate limiter and the SearxNG fallback path. |

The AutoBlog service is the closer fit — it already trust-tiers
official authority domains and full-page-fetches the result, which
is exactly what compliance work needs.

### 16.2 Build vs. buy — revised decision

**Decision (May 2026): ship the local DDG sidecar as the *only* MVP
backend; defer Brave and Tavily until economics demand them.**

Rationale:

* Three swappable backends sound flexible but cost engineering time
  (one credential path, one rate-limit policy, one quota dashboard,
  one billing surface) we don't have yet. **Two unfinished backends
  are worse than one finished one.**
* The local DDG sidecar costs **$0** beyond Railway compute and
  ships zero queries to a third party. That is the strongest
  compliance signal we can give an auditor *today*.
* Brave and Tavily both bill ~$5 per 1k requests. We have neither
  the request volume nor the LTV per tenant to justify recurring
  search spend pre-revenue. Once we cross either of these triggers
  we revisit:
  * **Volume trigger:** sustained > 5k web-search calls/day across
    the fleet (the point where our DDG sidecar starts hitting
    rate-limit pain even with the wasa-ai rate limiter).
  * **Quality trigger:** measurable accuracy gap on a shared eval
    set — i.e. the Reflector verdict is `retry` more than 12% of
    the time on web-search-driven steps because DDG ranking is too
    weak.
  * **Customer trigger:** an Enterprise tenant asks for an SLA we
    can only meet with a paid backend.

Concrete plan:

| Backend | Status | When |
|---|---|---|
| **`local`** (AutoBlog DDG port + custom trust-tiering) | **DEFAULT, MVP** | Phase 7.8 |
| `brave` (with `crp-comply-official` and `crp-comply-news` Goggles) | **DEFERRED** behind `BraveBackend` stub | When volume/quality/customer trigger hits |
| `tavily` (`/search` + `/research`) | **DEFERRED** behind `TavilyBackend` stub | Same |
| `exa` | not pursued | — |

We still implement the `WebSearchBackend` interface as a Protocol
and ship the two paid backends as **stubs that raise
`NotImplementedError` with a clear message and a config flag to
flip them on once credentials are provisioned**. This keeps the
substitution path warm without paying the deferred-cost tax now.

Selection: `CRP_COMPLY_WEBSEARCH_BACKEND=local` (default).
`brave` / `tavily` log a startup error if the relevant API key is
missing rather than silently degrading.

### 16.3 The `web_search` tool surface

```
web_search(
  query: str,
  intent: "regulation_text" | "enforcement" | "guidance" | "news" | "case_law",
  max_results: int = 6,
  goggle: str | None = None,   # Brave Goggle id, e.g. "official-eu-regs"
  freshness: "any" | "day" | "week" | "month" = "any",
) -> SearchResult
```

Returns:

```
{
  results: [
    {
      title, url, snippet, full_text?,
      domain, trust_tier: 1|2|3|4,
      published_at?, fetched_at, content_hash,
      citation_id  // assigned for the audit trail
    }
  ],
  query, backend, latency_ms, quota_remaining
}
```

### 16.4 Trust-tier configuration (the local equivalent of Goggles)

Brave's hosted "Goggles" let you upload a custom reranking profile.
The local DDG sidecar gets the same accuracy lever a different way:
the trust-tier table itself is a versioned, git-tracked YAML file
the customer can read and audit.

`crp-comply-search/profiles/crp_comply_official.yaml`:

```yaml
name: crp-comply-official
version: 1
tiers:
  1:  # T1 — official authorities (boost)
    weight: 1.0
    domains:
      - eur-lex.europa.eu
      - ec.europa.eu
      - edpb.europa.eu
      - ico.org.uk
      - cnil.fr
      - garanteprivacy.it
      - aepd.es
      - bfdi.bund.de
      - nist.gov
      - iso.org
      - gov.uk
      - cisa.gov
      - ncsc.gov.uk
  2:  # T2 — vendor primary docs (mid)
    weight: 0.85
    domains: [microsoft.com/legal, openai.com/policies, anthropic.com/legal]
  3:  # T3 — reputable analysis (low boost)
    weight: 0.75
    domains: [arxiv.org, github.com/eu-ai-act]
blocked:
    - reddit.com
    - twitter.com
    - x.com
    - medium.com
    - substack.com
    - facebook.com
    - linkedin.com
```

A second profile `crp_comply_news.yaml` boosts Reuters / Bloomberg
/ FT / Lawfare / JDSupra / Lexology for the `news` and
`enforcement` intents.

Why this beats hosted Goggles for our MVP:

* **Auditable.** The customer sees the exact ranking policy in our
  git repo. There is no opaque hosted config.
* **Free.** No per-query cost.
* **Customisable per tenant.** Enterprise tenants can fork the
  profile (e.g. add their internal counsel's blog as T2).

When we eventually flip on Brave we ship the same two profiles
*also* as Brave Goggles — the YAML is the source of truth, the
Goggle is generated from it.

### 16.5 Web search inside the loop — when does it fire?

Triage and the planner decide. The web tool is **only available**
to a step when one of:

1. The CKF returned 0 facts above confidence threshold for this
   query.
2. The query intent is `news`, `enforcement`, or `freshness > 0`.
3. The Reflector verdict on a previous step was `retry` due to
   stale information.
4. The user explicitly asks for "latest" / "recent" / a date in the
   future.

This keeps the loop CKF-first and prevents the agent from hitting
the web on every trivial question.

### 16.6 Audit trail for web sources

Every web result that lands in an artefact is recorded as:

```
{
  source_id: "web:<sha256(url)>",
  url, title, domain, trust_tier, fetched_at,
  content_hash,         // SHA-256 of the fetched body
  search_backend, search_query, goggle?,
  raw_text_blob_id      // pointer to the cached body in data/cache/web_pages/
}
```

This means: a year later, the auditor can replay the exact bytes
the agent reasoned against, even if the page has moved or been
edited. The cached body is signed into the existing evidence
binder via the `derivation_manifest` we already ship.

### 16.7 Streaming UX for web search

Web search is the slowest tool in the kit (200ms – 4s). The SSE
stream shows it explicitly:

```
⚒ web_search(query="EDPB binding decision article 65 2026", goggle=crp-comply-official)
  ⏳ querying brave...                           [180ms]
  📥 6 results, fetching top 3 full pages...     [1.2s]
  ✓ trusted: edpb.europa.eu (T1)                 0.95
  ✓ trusted: ec.europa.eu   (T1)                 0.95
  ⓘ skipped: reddit.com    (blocked)
  ✓ result hash 7f3a... cached for audit
```

That tape is the trust signal: **the user sees the web search
running, sees which sources made the cut, sees which were blocked,
and sees that the bytes are cached for audit**.

---

## 17. Hosting decision — sidecar service or in-process?

Both AutoBlog's research agent and our future web tool can run
either way:

| Mode | Pros | Cons |
|---|---|---|
| **In-process** (just Python imports + httpx) | Zero network hop, simpler ops, single process | Heavy deps (BeautifulSoup, lxml, GLiNER for the extraction pipeline) bloat the main image; one slow scrape blocks the FastAPI loop |
| **Railway sidecar service** | Heavy deps isolated, can scale/restart independently, can be shared across tenants, can be replaced without redeploying the main app | More moving parts, internal HTTP latency (~5ms) |

**Recommendation:**

* **Web search:** **sidecar**. Spin a small FastAPI service
  (`crp-comply-search`) on Railway that wraps the local DDG +
  trust-tier engine behind a single `POST /search` and `POST
  /research` endpoint. The `BraveBackend` and `TavilyBackend`
  classes ship as deferred stubs (see §16.2). The main API talks
  to the sidecar over Railway's private network. This isolates
  the heavy fetch + parse path so a slow scrape never blocks the
  FastAPI request loop.
* **CKF extraction pipeline:** **in-process** for now (Phase 6) —
  it only runs once per deploy onto the volume, so isolation buys
  us nothing. If/when we move to per-tenant extraction (Phase 9?),
  promote it to a sidecar.

The sidecar also unlocks an **operations dashboard** — hit rate
per trust tier, blocked-domain count, average trust score per
query, p95 fetch latency. Once we add Brave/Tavily, the dashboard
shows quota remaining per backend. That's another compliance
signal we can put on the Product page.

---

## 18. Updated phasing

Section §10's sub-phases now expand to (revised May 2026 to ship the
local DDG sidecar as the only MVP web backend; §21 contains the full
no-bypass checklist for each row):

| Sub-phase | Scope | Gate |
|---|---|---|
| 7.0 | Event taxonomy + new SSE skeleton | All current tests still green |
| **7.1** | **Triage layer (port wasa-ai pattern matcher + complexity scorer)** | Triage unit tests, lane selection deterministic for fixture queries |
| **7.2** | **Cache layer (exact + semantic + plan cache)** | Round-trip tests, version-bump invalidation test |
| 7.3 | `LoopState` FSM + Planner step + degenerate single-step loop | Unit tests on FSM transitions |
| 7.4 | ReAct step + tool dispatch + observation streaming | Replace single-shot path |
| 7.5 | `ask_user` + suspend/resume + frontend clarifier card | E2E suspend test |
| 7.6 | Reflector + plan revision + CKF coverage check (§15.1.3) | Plan-revision unit test, "uncited claim ⇒ retry" test |
| **7.7** | **`FederatedFabric` wrapper + CKF telemetry events** | Tenant + corpus facts visible per step |
| **7.8** | **Web search sidecar `crp-comply-search` (local DDG + trust-tier engine + AutoBlog port). `BraveBackend`/`TavilyBackend` shipped as `NotImplementedError` stubs.** | Health + 1k req/day soak test on local backend; stub backends raise on construction with clear msg |
| **7.9** | **Trust-tier YAML profiles `crp_comply_official` + `crp_comply_news` (the local equivalent of Brave Goggles)** | Profiles rank EUR-Lex above Wikipedia for the fixture query set |
| 7.10 | `run_recipe` tool + recipe streaming | Round-trip artefact test |
| 7.11 | Frontend reasoning tape + lane banners + trust-tier pills | Visual QA against fixture event log |
| 7.12 | Budgets, replays, hardening | Soak test |
| 7.13 *(deferred)* | `BraveBackend` activation + Goggle generation from YAML | Triggered by volume / quality / customer trigger from §16.2 |
| 7.14 *(deferred)* | `TavilyBackend` activation | Same |

---

## 19. The full event taxonomy (updated)

Adding to §3.3:

| `event:` | When | Payload |
|---|---|---|
| `loop.triage` | triage finished | `{complexity, intent, confidence, lane, reasoning}` |
| `loop.cache.hit` | Lane A fired | `{key_kind: exact|semantic, similarity?, age_seconds, citations}` |
| `loop.cache.miss` | nothing in cache | `{key_kind, lookup_ms}` |
| `loop.web.start` | web tool dispatched | `{query, backend, goggle?, freshness}` |
| `loop.web.result` | web tool returned | `{hits, blocked, trust_tiers, latency_ms, quota_remaining}` |
| `loop.ckf.query` | any CKF tool fired | `{mode, scope: corpus|tenant|federated, hits, top_confidence}` |

Total: 22 typed events. The frontend tape renders all of them with
icons and colour coding so the user gets a continuous, legible
demonstration that the system is actively triaging, caching,
searching, walking the graph, planning, calling tools, reflecting,
and producing.

---

## 20. Why this answers the latest user complaints

| Complaint | Response in this section |
|---|---|
| "Trivial queries shouldn't enter a long loop" | §14: three lanes, triage selects, cache short-circuits in <100 ms. |
| "Is any of this in wasa-ai?" | §14.1: yes — `query_classifier`, `intent.classifier`, `MessageRelevanceScorer`, `continuation_manager`, `ddg_rate_limiter`. We port directly. |
| "Cache?" | §14.5: exact + semantic + plan caches, sqlite-backed, version-aware invalidation. wasa-ai does NOT have this — we're adding the missing piece. |
| "Loop must integrate with regulations knowledge" | §15: five structural bindings between the loop and the CKF. Reflector enforces "every claim cites a Fact". |
| "Web search? AutoBlog has one. wasa-ai too." | §16: ship the local AutoBlog-style DDG sidecar as the only MVP backend; trust-tier YAML profiles replace Brave Goggles for now; Brave + Tavily deferred behind stubs until volume / quality / customer trigger fires. |
| "Host as Railway service or no?" | §17: yes for web search (sidecar isolates the heavy fetch path); no for CKF extraction (one-shot per deploy). |
| "Display events to prove the system is thinking, reasoning, searching, planning, tool calling, auditing" | §14.6 + §15.3 + §16.7 + §19: 22-event SSE taxonomy, with explicit `loop.triage` / `loop.cache.hit` / `loop.web.result` / `loop.ckf.query` so every lane and every tool emits a visible signal. |
| "Three swappable backends sounds like overhead" | §16.2 (revised): correct. MVP is local-only. Brave/Tavily ship as `NotImplementedError` stubs gated by env so the substitution path stays warm without paying the deferred-cost tax now. |
| "No bypasses — make it flawless" | §21: per-sub-phase no-bypass checklists with explicit anti-patterns we will refuse to ship. |

---

## 21. No-bypass checklists per sub-phase

Each sub-phase below has three sections:

* **Done means** — the affirmative deliverables.
* **No bypass** — anti-patterns the reviewer (us) must reject.
* **Verify with** — the exact command or assertion that proves it.

### 7.0 — Event taxonomy + SSE skeleton

**Done means:**
- [ ] `crp_comply.api.events` module defines all 22 event types from §3.3 + §19 as a `Literal[...]` type, exported.
- [ ] Existing `/agent/run` SSE endpoint emits the new events at the same offsets it already emits today (none of the current events change shape).
- [ ] A new `tests/test_loop_events.py` asserts every event type appears in at least one fixture run, and that every emitted event validates against a Pydantic schema.

**No bypass:**
- ❌ Do not introduce free-form string event names alongside the typed enum. Every event must come from the enum.
- ❌ Do not skip the schema validation in tests under the excuse "the field is optional". An optional field is a `Field(default=None)`, not absent.
- ❌ Do not break the existing single-shot SSE shape; this is purely additive.

**Verify with:** `pytest tests/test_loop_events.py -q` green; `git grep "loop\\." src/crp_comply/api/agent.py` shows every enum member used at least once.

---

### 7.1 — Triage layer

**Done means:**
- [ ] `crp_comply/agent/triage.py` ports `wasa_ai.core.intent.classifier.PatternMatch` and `wasa_ai.core.orchestration.query_classifier.QueryClassifier`.
- [ ] Compliance-tuned pattern set (≥ 30 patterns from §14.4) checked into `agent/triage_patterns.yaml`.
- [ ] `Triage.classify(query) -> TriageResult` runs ≤ 50 ms p95 on CPU.
- [ ] Lane selection is deterministic: same query → same lane every time.
- [ ] `loop.triage` event emitted with `complexity`, `intent`, `confidence`, `lane`, `reasoning`.

**No bypass:**
- ❌ Do not let triage default to `slow_path` for unknown queries silently — emit `loop.triage` with `confidence=low, lane=slow_path, reasoning=fallback` so the UI shows the explicit fallback.
- ❌ Do not call the LLM inside the triage path. Triage is CPU-only.
- ❌ Do not concatenate user input into a regex without escaping; pattern set must be static at module-load.

**Verify with:** golden-file test with 50 fixture queries each tagged with expected lane; mismatch fails the test.

---

### 7.2 — Cache layer

**Done means:**
- [ ] `crp_comply/agent/cache.py` implements three caches (`exact`, `semantic`, `plan`) backed by sqlite at `data/cache/agent_responses.db`.
- [ ] Cache key includes `tenant_id`, `corpus_version`, `ckf_version`. Bumping any of these invalidates the entry.
- [ ] Cache writes only occur on `loop.final` with reflector verdict `ok` and ≥ 1 citation.
- [ ] Semantic similarity threshold ≥ 0.92 cosine (configurable via `CRP_COMPLY_CACHE_SIM_THRESHOLD`).
- [ ] `loop.cache.hit` carries `key_kind`, `similarity?`, `age_seconds`, `citations`.
- [ ] UI shows a "Re-run from scratch" button that bypasses cache.

**No bypass:**
- ❌ Do not cache uncited answers. A cached answer with no citations is unprovable.
- ❌ Do not cross tenants. Tenant ID is the first key field — assert in tests.
- ❌ Do not silently re-use a cached answer when the corpus version has bumped. Bump = invalidate.
- ❌ Do not cache LLM streaming chunks (only the final assembled answer + citations + tool log).

**Verify with:** `tests/test_agent_cache.py` covers (a) hit/miss roundtrip, (b) tenant isolation, (c) corpus-version bump invalidation, (d) "Re-run from scratch" header forces miss.

---

### 7.3 — `LoopState` FSM + Planner

**Done means:**
- [ ] `crp_comply/agent/loop_state.py` defines the FSM from §3 (PLANNING → STEP → ACTING → REFLECT → AWAITING_USER → FINALISE) as a typed dataclass with explicit `transition()` method.
- [ ] Invalid transitions raise `LoopStateError`; nothing is implicitly allowed.
- [ ] Planner emits a structured plan (`{steps: [...], should_loop: bool}`); when `should_loop=false` the orchestrator runs a degenerate single-step loop and returns.
- [ ] Backwards compat: existing `/agent/run` callers that don't request the loop see the degenerate single-step path.

**No bypass:**
- ❌ Do not allow free-form state strings. State is an enum.
- ❌ Do not skip the FSM in "fast" code paths — Lane B (fast path) still goes through `PLANNING(should_loop=false) → STEP → FINALISE` so it emits the same events.
- ❌ Do not let the planner emit zero steps. Minimum is one.

**Verify with:** `tests/test_loop_fsm.py` enumerates all valid + invalid transitions; invalid ones raise.

---

### 7.4 — ReAct step + tool dispatch

**Done means:**
- [ ] Each step emits `loop.step.start`, then `loop.thought`, then ≥ 1 `loop.tool.start` / `loop.tool.result` pair, then `loop.observation`, then `loop.step.end`.
- [ ] Tool registry is a typed dict keyed by tool name → handler. Unknown tools fail fast.
- [ ] Observation buffer auto-prefixes `recall_facts(query=step.intent, max=5)` results (§15.1.4).

**No bypass:**
- ❌ Do not allow the model to invoke a tool not in the registry. JSON-schema-validate every tool call.
- ❌ Do not swallow tool errors silently; emit `loop.tool.error` and let the reflector see it.
- ❌ Do not skip the recall-facts pre-fetch even when the step is "obvious" — the fact log is the audit trail.

**Verify with:** `tests/test_loop_step.py` runs a fixture step with three tools; asserts event order and that `recall_facts` always prefixes the observation.

---

### 7.5 — `ask_user` + suspend / resume

**Done means:**
- [ ] `ask_user(question, options?, context?)` is a first-class tool. Calling it transitions the FSM to `AWAITING_USER` and persists the loop state.
- [ ] SSE stream emits `loop.ask_user` with the question and a `resume_token`.
- [ ] Frontend renders a clarifier card; on submit, POST to `/agent/resume/{resume_token}` continues the loop with `Last-Event-ID` semantics.
- [ ] Loop budget excludes time spent in `AWAITING_USER`.

**No bypass:**
- ❌ Do not write the awaiting-user state only in memory. Persist to sqlite so a server restart resumes correctly.
- ❌ Do not let the model fabricate the answer when it could ask. Reflector verdict `clarify_first` is mandatory if confidence < 0.6 on any user-facing claim.
- ❌ Do not allow more than 6 clarifiers per loop (budget; §13).

**Verify with:** E2E test that suspends, kills the worker, restarts it, and the loop resumes from the same step.

---

### 7.6 — Reflector + plan revision + CKF coverage check

**Done means:**
- [ ] Reflector returns one of `{ok, retry, revise_plan, clarify_first, abort}`.
- [ ] CKF coverage check (§15.1.3): every claim in the step output must reference a `fact_id`. Uncited claim → `retry`.
- [ ] Plan revision allowed up to 3 times per loop (§13).

**No bypass:**
- ❌ Do not let `ok` pass when uncited claims exist. The check is structural, not advisory.
- ❌ Do not allow infinite plan revision; budget enforced.
- ❌ Do not skip reflection on Lane B (fast path) — even single-step runs reflect.

**Verify with:** `tests/test_reflector.py` includes a fixture with a known uncited claim and asserts verdict = `retry`.

---

### 7.7 — `FederatedFabric` wrapper + CKF telemetry

**Done means:**
- [ ] `crp_comply/agent/federated_fabric.py` wraps both per-tenant CKF and corpus CKF, fans out queries in parallel, dedupes on `fact.id`, tags each fact with `scope: corpus | tenant`.
- [ ] Every CKF tool emits `loop.ckf.query` with `mode`, `scope`, `hits`, `top_confidence`.
- [ ] UI citation rail shows both layers with a tenant/corpus pill.

**No bypass:**
- ❌ Do not cross-pollute CKF data between tenants. Tenant ID is required on every query.
- ❌ Do not silently fall back to corpus-only when tenant CKF is empty — log it as `loop.ckf.query` with `scope=corpus, hits=N` so the UI shows it.
- ❌ Do not skip the dedupe — duplicate facts inflate apparent confidence.

**Verify with:** `tests/test_federated_fabric.py` with a fixture tenant + corpus pair; asserts dedupe + scope tagging + parallelism (mock latency).

---

### 7.8 — Web search sidecar `crp-comply-search`

**Done means:**
- [ ] New service at `services/crp-comply-search/` (FastAPI, separate Dockerfile, separate Railway service).
- [ ] `WebSearchBackend` Protocol with `search(...)` and `research(...)`.
- [ ] `LocalDDGBackend` ported from AutoBlog: DDG search via `duckduckgo-search`, per-result full-page fetch via httpx + BeautifulSoup, applies the trust-tier YAML.
- [ ] `BraveBackend` and `TavilyBackend` exist as classes that raise `NotImplementedError("backend deferred — see PHASE_7 §16.2")` from `__init__` if instantiated without `CRP_COMPLY_ENABLE_BRAVE=1` / `CRP_COMPLY_ENABLE_TAVILY=1`.
- [ ] `crp-comply-search` exposes `POST /search`, `POST /research`, `GET /health`, `GET /metrics`.
- [ ] Main API talks to sidecar over Railway private network; URL via `CRP_COMPLY_SEARCH_URL`.
- [ ] DDG rate limiter from `wasa_ai.rag.ddg_rate_limiter` ported (1.2 s min delay).
- [ ] Every result audit-trailed with `content_hash` + `raw_text_blob_id` (§16.6).
- [ ] `loop.web.start` / `loop.web.result` events fired around every call.

**No bypass:**
- ❌ Do not inline the sidecar back into the main app "for simplicity". The whole point is isolation.
- ❌ Do not skip the trust-tier filter. A T4 / blocked domain result must never reach the LLM.
- ❌ Do not skip the content hash. Every byte the LLM sees must be replayable from local cache.
- ❌ Do not let the sidecar leak the tenant's full query in URL params — POST body only.
- ❌ Do not let `BraveBackend` / `TavilyBackend` silently fall back to local. If a tenant requested Brave and didn't enable the env, fail loud at startup.

**Verify with:** sidecar soak test (1k req/day for one day); `tests/test_search_sidecar.py` covers (a) trust-tier filter blocks reddit, (b) content_hash is stable, (c) Brave/Tavily backends raise `NotImplementedError` by default.

---

### 7.9 — Trust-tier YAML profiles

**Done means:**
- [ ] `services/crp-comply-search/profiles/crp_comply_official.yaml` and `crp_comply_news.yaml` checked in.
- [ ] Profiles loaded at sidecar startup with schema validation.
- [ ] A fixture eval runs ten compliance queries through `LocalDDGBackend` with `crp_comply_official` and asserts EUR-Lex / EDPB / NIST / ICO appear above Wikipedia / Reddit in the top-5 every time.

**No bypass:**
- ❌ Do not hard-code the trust tiers in Python. They live in YAML so customers can audit and fork.
- ❌ Do not silently skip a malformed profile — fail to start.
- ❌ Do not allow profile changes at request time (no user-supplied profile parameters); profiles are server-side config only.

**Verify with:** `tests/test_search_profiles.py` ranking eval.

---

### 7.10 — `run_recipe` tool

**Done means:**
- [ ] `run_recipe(recipe_id, params)` is a tool that delegates to existing recipe machinery and streams artefact chunks back as `loop.recipe.chunk` events.
- [ ] Final artefact recorded via `record_artefact` tool with citations carried through.

**No bypass:**
- ❌ Do not let `run_recipe` produce an artefact with zero citations.
- ❌ Do not bypass the existing recipe permission / scope checks just because the loop is calling it.

**Verify with:** existing recipe tests still pass; new `tests/test_loop_run_recipe.py` round-trip.

---

### 7.11 — Frontend reasoning tape

**Done means:**
- [ ] React component renders all 22 event types with consistent icons and colour coding.
- [ ] Lane banner at top: "Cache hit · 17 min ago", "Fast path · 1.2 s", or "Reasoning loop · step 3 of 5".
- [ ] Tool calls render with their args + result preview + duration.
- [ ] CKF queries show scope pill (corpus / tenant) and top-fact preview.
- [ ] Web search results show domain + trust tier pill + cached-bytes link.
- [ ] Clarifier card matches §3.4 mockup.
- [ ] Reasoning tape is keyboard-accessible and screen-reader-friendly.

**No bypass:**
- ❌ Do not collapse or hide the reasoning tape by default — visibility is the trust signal.
- ❌ Do not strip events from the SSE stream client-side. Every emitted event must render somewhere.
- ❌ Do not show "Thinking…" placeholders without a backing event. Every visible state corresponds to a real event.

**Verify with:** Storybook fixtures for each event type; visual QA against §3.4 mockup.

---

### 7.12 — Budgets, replays, hardening

**Done means:**
- [ ] Budget enforcement: 12 steps, 60k tokens, 5 min wall-clock, 6 clarifiers, 3 plan revisions. Exceeding any → `loop.abort` with reason.
- [ ] Replay endpoint: `GET /agent/runs/{run_id}/replay` returns the full event log so any past loop can be re-rendered exactly.
- [ ] All events persist to `data/telemetry/loop_runs/{run_id}.jsonl`.
- [ ] Soak test: 50 concurrent loops over an hour, no leaks, no orphaned awaiting-user states.
- [ ] OWASP review of new endpoints: `POST /agent/resume/{token}` resume token is single-use, expires in 24 h, scoped to the originating tenant.

**No bypass:**
- ❌ Do not allow a budget override via request parameters. Budgets are server-side config.
- ❌ Do not let the resume token be reused. One token, one resume.
- ❌ Do not store the loop event log in plaintext if it contains tenant-confidential observations. Wrap in the existing tenant encryption envelope.

**Verify with:** soak test green; `tests/test_loop_budgets.py` covers each ceiling; `tests/test_loop_resume_security.py` covers token expiry + tenant scoping + single-use.

---

### 7.13 / 7.14 — Brave + Tavily activation (deferred)

These are **deferred** and not part of MVP. The checklist exists so
that *when* a trigger fires (volume, quality, customer) we know the
exact bar:

**Done means (when activated):**
- [ ] `CRP_COMPLY_ENABLE_BRAVE=1` (or `_TAVILY=1`) flips the corresponding backend from `NotImplementedError` to live.
- [ ] API key from `BRAVE_API_KEY` / `TAVILY_API_KEY` env, never logged.
- [ ] The same trust-tier YAML profiles are converted to Brave Goggles automatically (`scripts/yaml_to_goggle.py`).
- [ ] Per-tenant override: `tenant.search_backend = "brave"` selects Brave for that tenant only.
- [ ] Quota dashboard surfaces `quota_remaining` from each backend.

**No bypass (when activated):**
- ❌ Do not put the API key in any logged event. `loop.web.start` carries `backend=brave` only, never the key.
- ❌ Do not silently fall back to local on Brave 5xx — emit `loop.tool.error` and let the reflector decide whether to retry on local.
- ❌ Do not bill a tenant for Brave/Tavily without an explicit per-tenant flag (avoid surprise billing).

**Verify with:** integration test against Brave/Tavily sandbox; chaos test simulating 5xx.

