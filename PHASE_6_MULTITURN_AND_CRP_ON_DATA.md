# Phase 6 — Multi-turn chat + per-deploy preprocessing + CRP-on-data

This phase ships three structural changes that close the gap between
"single-turn agent that answers one regulation question" and
"conversational compliance assistant with deep regulation grounding":

1. **Per-deployment corpus + index bootstrap** (replaces the
   `COPY corpus/_scraped/` Dockerfile step that broke when the
   directory was gitignored).
2. **Multi-turn chat history** (replaces the text-blob
   `extra_context` approach with a real `[{role, content}]` message
   replay, inspired by `wasa-ai-master/wasa_ai/chat/session_manager.py`).
3. **CRP-on-data → corpus CKF** (the new feature the user asked
   about: pre-extract structured Facts from the regulation corpus into
   a shared `ContextualKnowledgeFabric` so every tenant inherits a
   pre-compiled knowledge graph at deploy time, not just an embedded
   chunk index).

---

## 1. Per-deployment corpus bootstrap

### Problem

The Railway build was failing with:
```
failed to compute cache key: ... "/corpus/_scraped": not found
```
because the Dockerfile had a `COPY corpus/_scraped/ corpus/_scraped/`
step and `corpus/_scraped/` is gitignored — the directory simply
isn't present on Railway after `git clone`.

### Fix

* Removed the `COPY corpus/_scraped/` step from the Dockerfile.
* The FastAPI lifespan ([src/crp_comply/api/app.py](src/crp_comply/api/app.py))
  now runs a 3-stage corpus bootstrap **as a background task** so it
  never blocks the Railway healthcheck:
  1. If `data/rag_index/corpus.sqlite` already has chunks → noop.
  2. Else if `corpus/_scraped/*.json` exists → embed and index.
  3. Else → run the scrapers (`eurlex.scrape_eu_ai_act/gdpr/nis2`,
     `nist.scrape`, `intl.scrape`) to regenerate `corpus/_scraped/`,
     then embed and index.

Each scraper is best-effort — one failing source doesn't nuke the
whole corpus. The agent's `query_regulation` tool gracefully returns 0
hits with a retry hint while the index is still warming.

### Operator switches

| Variable | Default | Effect |
|----------|---------|--------|
| `CRP_COMPLY_RAG_BOOTSTRAP` | `true` | Master switch for the whole bootstrap flow. |
| `CRP_COMPLY_BOOTSTRAP_CKF` | `true` | Run `bootstrap_ckf_from_corpus` on first boot — includes auto-extraction if no JSONLs are present yet. |
| `CRP_COMPLY_DATA_DIR` | `data` | Where the RAG index, scraped corpus, and CKF dbs live. On Railway set this to `/app/data` (mounted volume) so everything persists across restarts. |
| `CRP_COMPLY_SCRAPED_DIR` | unset | Optional override that pins the scraped-JSON directory (otherwise auto-derived from `CRP_COMPLY_DATA_DIR`). |

### First-boot timing (rough)

| Phase | Time |
|-------|------|
| Scraping (11 sources, network-bound) | 3–8 min |
| Embedding 1574 chunks (sentence-transformers) | 1–3 min |
| Index commit + warm-up | < 30 s |

Subsequent boots see a populated `data/rag_index/` on the Railway
volume and skip straight to "RAG index ready: 1574 chunks".

---

## 2. Multi-turn chat history

### Problem

The previous `_prepare_continuation` flow concatenated the prior task,
prior final answer, and clarifications into a single text-blob system
message. The orchestrator's `run()` always built a fresh
`messages = [{system}, {user_task}]` array on every call. Result: the
LLM never saw the conversation as a conversation — it saw "here's a
ton of background prose, now answer this new question". Quality was
markedly worse on follow-up turns.

### Fix (inspired by wasa-ai's `ChatSessionManager`)

* Each session record now carries a structured
  `messages: list[{role, content, ts}]` array (initialized on
  `agent_start` / `agent_start_stream`, appended to on every
  `agent_continue*` and after every `_apply_result`).
* The API layer's new `_select_history_for_run` helper picks the
  relevant slice for each turn:
  * Always preserves the last `preserve_recent` (default 4) messages.
  * For older messages, scores by recency × keyword overlap with the
    new query × role weight, and takes the top-N within the token
    budget (default ~3000 tokens).
  * Char-budget tail-trims if the selection still overflows.
* `ComplianceAgent.run()` accepts a new `prior_messages` keyword. When
  present, it injects the messages between the system primers and the
  active user task, so the LLM sees a real chat thread.
* `_prepare_continuation` no longer re-packs the prior task/answer
  into the text context — it only carries forward authoritative
  clarifications (which must survive any history trim) and operator
  metadata.

### Trade-offs

* History is bounded to ~12 messages / 12 KB by default — long-running
  sessions get older turns trimmed via the relevance scorer.
* Authoritative clarifications continue to ride in `extra_context` so
  they can never be lost to scoring.
* Compatibility: orchestrator double-check via `inspect.signature` lets
  test doubles ignore `prior_messages`.

---

## 3. CRP-on-data → corpus CKF (`ckf_corpus.py`)

### The user's question

> "Can't the CRP be applied to the data itself? Then the CKF it
> builds gets off… is that maybe a feature we can develop on the
> CRP protocol — applying the CRP to data, so it's easily integrated
> into context, not just RAG or context injection."

### The answer: yes, and it's now a deploy-time pipeline

Instead of treating the regulation corpus as static text that the LLM
re-extracts structure from on every query, we apply the **full CRP
extraction pipeline** to the corpus once at deploy time and persist
the resulting structured Facts into a shared
`ContextualKnowledgeFabric` that lives alongside the per-tenant CKFs:

```
corpus/_scraped/*.json
        │
        │  crp.extraction.ExtractionPipeline
        │  (6-stage GLiNER + NLI + relationship graph)
        ▼
corpus/_scraped/facts/{source_id}.jsonl
        │
        │  bootstrap_ckf_from_corpus()
        ▼
data/ckf/__corpus__/ckf.db
        │
        ▼
  ContextualKnowledgeFabric
   ├── pattern_query    — "what does GDPR say about controllers?"
   ├── temporal_query   — "what changed between EU AI Act drafts?"
   ├── community_summary — "show me the GPAI obligation cluster"
   └── graph_walk       — "from Article 6 → cross-references"
```

### What this changes for the agent

* `_seed_prior_facts_primer` (orchestrator) now **always** queries the
  shared corpus CKF in addition to the per-tenant fabric. Brand-new
  tenants no longer start cold — they inherit the pre-extracted
  regulation graph and the LLM's first turn already has primed
  Facts to cite.
* The pre-loaded primer surfaces both layers separately so the LLM
  knows which facts are tenant-specific vs. regulation-derived.
* Existing `recall_facts`, `pattern_query`, `temporal_query`,
  `community_summary`, and `graph_walk` tools transparently see the
  expanded fact set when wired against the shared CKF (future work:
  expose a federated fabric wrapper so the existing tool calls
  automatically span both).

### Why decouple extraction from boot? (We don't anymore.)

GLiNER + NLI weights are ~1 GB and per-source extraction takes minutes.
The earlier design left this as an opt-in CI step. The current default
behaviour is:

* Lifespan starts → background task scrapes the regulation corpus.
* When scraping finishes, the same task triggers `bootstrap_ckf_from_corpus`.
* If `corpus/_scraped/facts/*.jsonl` is missing, the bootstrap **runs the
  extraction pipeline itself** — once, on the mounted volume.
* Results are persisted at `<DATA_DIR>/corpus_scraped/facts/*.jsonl` and
  the corpus CKF db at `<DATA_DIR>/ckf/__corpus__/ckf.db`. Subsequent
  boots are seconds, not minutes.

First-boot cold time: ~10–20 minutes total (scrape + embed + extract).
The agent is responsive throughout — the bootstrap is a background
asyncio task, not a blocker on `/health`. While the corpus is still
warming up, `query_regulation` returns 0 hits with a retry hint.

### Why not commit the JSONL into the repo?

Two reasons:
1. ISO source text is copyrighted. Committing extracted Facts would
   leak verbatim clause text into git history.
2. Facts are derivative — they should be regenerated when the
   underlying regulations or the extraction pipeline updates. Treating
   them as build artefacts (operator-controlled, volume-mounted)
   matches their lifecycle.

### Module surface

```python
# src/crp_comply/agent/ckf_corpus.py
get_corpus_ckf() -> ContextualKnowledgeFabric | None
bootstrap_ckf_from_corpus() -> int   # facts loaded
query_corpus_ckf(*, max_results=8, min_confidence=0.5) -> list[Fact]
```

The corpus CKF persists at `data/ckf/__corpus__/ckf.db`. Bootstrap is
idempotent — subsequent boots see `fact_count > 0` and skip the load.

---

## Files touched

* [Dockerfile](Dockerfile) — drop hard `COPY corpus/_scraped/`.
* [src/crp_comply/api/app.py](src/crp_comply/api/app.py#L130-L260) —
  3-stage background bootstrap (scrape → embed → optional CKF
  preload).
* [src/crp_comply/api/agent.py](src/crp_comply/api/agent.py) —
  `messages` array, `_select_history_for_run`, `_score_message`,
  `_append_user_message`, `_append_assistant_message`, slimmed
  `_prepare_continuation`, `prior_messages` propagation through
  `_run_agent_async` and `_stream_agent_run`, both continuation
  endpoints.
* [src/crp_comply/agent/orchestrator.py](src/crp_comply/agent/orchestrator.py) —
  `run()` accepts `prior_messages`, injects them as real chat turns;
  primer hybridised with shared corpus CKF.
* [src/crp_comply/agent/ckf_corpus.py](src/crp_comply/agent/ckf_corpus.py) —
  new module: corpus CKF singleton, `bootstrap_ckf_from_corpus`,
  `query_corpus_ckf`, JSONL fact loader.

## Tests

`455 passed, 4 skipped` — same baseline as Phase 5. No
behaviour-changing test was rewritten because:
* Multi-turn is opt-in via `prior_messages`; orchestrator still
  works without it (existing tests).
* CKF bootstrap is gated behind `CRP_COMPLY_BOOTSTRAP_CKF=false`
  default.
* Background scraping in lifespan is gated behind the existing
  `CRP_COMPLY_RAG_BOOTSTRAP` switch.

Follow-up tests (next phase): multi-turn replay assertions on
`agent_continue`, corpus CKF round-trip, and a bootstrap "scrape
empty → recover" smoke test that uses fixture HTTP fixtures instead
of hitting EUR-Lex live.
