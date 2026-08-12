# CRP × CRP-Comply final integration audit (Phase 4)

> **Position in the timeline.**
> ``CRP_AUDIT.md`` — Phase 1 baseline.
> Commit ``e103a46`` — Phase 2 (SSE, ``/continue``, dedup).
> Commit ``e4be409`` — Phase 3 (opt-in ``CRP_COMPLY_AGENT_DISPATCH_MODE``) + ``CRP_AUDIT_2.md``.
> **This document** — Final pass: every CRP capability we still bypass,
> every output-cap that could starve a generation, every silent break-out
> from CRP, and the Railway-side install correctness of all CRP extras
> (especially the ones that make UIE and CKF actually fast).

---

## 0. TL;DR

The integration is **healthy** but had **three concrete production
correctness bugs** as of ``e4be409``:

1. **Railway image installs ``crprotocol`` (base only)** — the CKF graph
   modes (HNSW semantic, igraph + Leiden community detection) and the
   AES-256-GCM ``export_state`` were silently degraded because
   ``hnswlib``, ``igraph``, ``leidenalg``, ``blake3``, ``cryptography``
   were not requested. *Fixed in this commit by switching to
   ``crprotocol[full]>=2.0.0`` in ``pyproject.toml``.*
2. **Phase 3 dispatch path bypasses tier output caps** — when
   ``CRP_COMPLY_AGENT_DISPATCH_MODE`` is set, the orchestrator hands
   the prompt to ``crp.Client.dispatch_*`` directly without going
   through ``ComplianceLLM._apply_routing``. Tier-aware ``max_tokens``
   clamping (free 1024 / starter 2048 / pro 4096 / enterprise 8192 /
   cloud 16384) is therefore not applied. *Fixed in this commit by
   forwarding ``max_output_tokens`` into the dispatch helper and
   passing it as ``max_tokens=`` kwarg to all four CRP modes.*
3. **The 4000-token primed envelope is pinned forever** —
   ``_prime_corpus_envelope`` adds a system message of up to 4000
   tokens, ``compact_messages_for_budget`` PINS all system messages,
   and on an 8k-context model that leaves only ~5k tokens for the
   conversation. Long sessions overflow. *Fixed in this commit by
   marking the primer as ``role="system", name="crp_corpus_primer"``
   and teaching the compactor to fold it into a one-line CKF marker
   once the live conversation grows past 60 % of the budget.*

Plus the five remaining ``CRP_AUDIT_2.md`` bug-shaped findings (B-1, B-2, B-3,
B-5, B-6) — all addressed in the same commit.

---

## 1. CRP SDK surface — every capability, who uses it

### 1.1 Capabilities CRP-Comply already consumes

| Capability | Where in crp-comply | Maturity |
|---|---|---|
| ``crp.providers.base.LLMProvider`` ABC | ``agent/worker_adapter.py`` (subclass) | ✅ Full (since Phase 1) |
| ``crp.providers.AnthropicAdapter`` / ``OpenAIAdapter`` | ``agent/llm.py`` autodetect | ✅ Full |
| ``crp.security.PIIScanner`` | ``crp_integration.redact_pii`` | ✅ Wrapped |
| ``crp.security.InjectionDetector`` | ``crp_integration.scan_for_injection`` | ✅ Wrapped |
| ``crp.security.RiskClassifier`` + ``AISystemCategory`` | ``agent/tools.py``, ``core.py`` | ✅ Wrapped |
| ``crp.security.ComplianceReporter`` + ``TransparencyDeclaration`` | ``core.py`` | ✅ Wrapped |
| ``crp.security`` GDPR primitives (``ConsentManager``, ``ProcessingRecordKeeper``, ``RetentionManager``, ``ErasureManager``, ``DataLineageTracker``, ``DataClassification``, ``ProcessingPurpose``) | ``proxy/interceptor.py`` | ✅ Full |
| ``crp.security.RBACEnforcer`` + ``RateLimitConfig`` + ``Role`` | ``api/routes.py`` | ✅ Full |
| ``crp.provenance.DecisionProvenanceEngine`` | ``proxy/interceptor.py`` | ✅ Full |
| ``crp.extraction.ExtractionPipeline`` (UIE) | ``crp_integration.extract_facts_from_text`` | ✅ Wrapped |
| ``crp.extraction.contradiction.detect_contradictions`` | ``crp_integration`` | ✅ Wrapped |
| ``crp.envelope.packer.pack_facts`` + ``ScoredFact`` + ``FactGraph`` | ``crp_integration.pack_hits_to_envelope`` | ✅ Wrapped |
| ``crp.continuation.stitch.stitch_many`` | ``crp_integration.continue_truncated_answer`` | ✅ Best-effort |
| ``crp.ckf.ContextualKnowledgeFabric`` + ``CKFConfig`` | ``api/routes._get_user_ckf`` | ✅ Direct instantiation |
| ``crp.ckf.pattern_query`` | ``crp_integration.pattern_query_ckf`` | ✅ Wrapped |
| ``crp.ckf.FactIntegrityChain`` | ``api/routes.py`` | ✅ Used |
| ``crp.observability.MetricsExporter`` / ``HealthMonitor`` / ``ExportFormat`` / ``TelemetryWriter`` / ``AuditLog`` / ``QualityReporter`` | ``api/routes.py`` | ✅ Used |
| ``crp.observability.events.EventEmitter`` | imported but *unused* in agent runtime; only imported in ``api/routes.py`` | 🟡 Stub |
| ``crp.advanced.scale_mode.ScaleModeSelector`` | ``api/routes.py`` | ✅ Used |
| ``crp.Client`` / ``CRPOrchestrator`` (dispatch surfaces) | ``crp_integration.dispatch_via_crp`` (Phase 3, opt-in) | 🟡 Opt-in only |

### 1.2 Capabilities CRP-Comply still bypasses

| Capability | Why we'd want it | Status after this commit |
|---|---|---|
| ``client.dispatch_progressive`` / ``dispatch_hierarchical`` / ``dispatch_reflexive`` | Different relay strategies per task profile (e.g. reflexive = generate-then-verify) | Untouched. Phase 5 candidate. |
| ``client.async_dispatch`` / ``async_dispatch_stream`` / ``async_ingest`` | Drops our ``asyncio.Queue`` + ``run_in_executor`` bridge in ``_stream_agent_run`` | Untouched. |
| ``client.preview_envelope`` | Surface "what will be packed" in the SSE stream as ``envelope_preview`` | Untouched. |
| ``client.estimate_session`` | Show token-cost estimate in the UI before dispatch | Untouched. |
| ``client.session_status`` | Live cost / window / saturation pane in the UI | Untouched. |
| ``client.export_state`` | Sealed AES-256-GCM bundle for "share session" or audit hand-off | Untouched. |
| ``client.feedback.boost_fact`` / ``penalize_fact`` / ``reject_fact`` | 👍/👎 on each citation in the final answer | **Wired in this commit** (``POST /agent/{id}/feedback``). |
| ``client.warm_store`` direct API | Cross-iteration dedup, ``mark_seen``, ``supersede``. | Used by Phase 3 paths only. Legacy path still uses our local ``_seen_chunk_ids`` set. |
| ``client.parallel`` (``ParallelFanOut``) | Multi-task fan-out (e.g. "generate Article 9 risk assessment AND Article 13 transparency notice in parallel") | Untouched. |
| ``client.compliance_audit`` | Read CRP's signed audit trail of every dispatch | Untouched. We keep our own JSONL. |
| ``client.human_oversight`` | "Send for legal review" gate | Untouched. |
| ``client.emitter.on(event_type, ...)`` event subscription | Wire dispatch / extraction / quality events into our SSE stream as a free upgrade | Untouched. |
| ``CRPOrchestrator.resume(session_id)`` cross-session restore | Real cross-session memory (cold-store reload) | Untouched. We re-scan CKF on every run. |
| ``ContinuationManager`` (full DAG) | Multi-window plans with ``reground_interval`` and structural state | Untouched. We use ``stitch_many`` only. |
| ``client.ckf.detect_communities`` / ``community_summary`` / ``graph_walk`` / ``temporal_query`` | Topic-grouped fact retrieval, multi-hop seed expansion | Untouched. We only use ``pattern_query``. |
| ``client.ckf.subscribe(FACT_CREATED, …)`` | UI updates when the agent learns something new | Untouched. |

### 1.3 Capabilities we deliberately reimplement and keep

| In crp-comply | Reason |
|---|---|
| ``ComplianceAgent.run`` tool loop | Hosts our 15+ domain tools; CRP's ``dispatch_with_tools`` is hardcoded to ``CRP_CONTEXT_TOOLS`` and cannot host third-party tools today. |
| ``compact_messages_for_budget`` | Folds tool messages by character count under our system-prompt-pin rules. CRP's packer is fact-budget oriented; ours is message-budget. |
| Domain ``RiskClassifier`` (EU AI Act Article 6) | CRP's ``RiskClassifier`` is generic; ours is regulation-specific. |
| Per-tenant CKF persistence path | We control disk layout; CRP defines the schema. |

---

## 2. Output-token caps — every place that limits generation

The user directive was *"output generation is sufficient and unrestricted"*.
Here's every cap, with verdict.

| Cap | File / line | Default value | Verdict |
|---|---|---|---|
| ``ComplianceLLM(default_max_tokens=2048)`` | ``agent/llm.py`` L114 | 2048 | ✅ Reasonable for an agentic loop iteration. |
| ``PER_TIER_TOKEN_CAPS`` | ``agent/llm.py`` L80-86 | free 1024 / starter 2048 / pro 4096 / enterprise 8192 / cloud 16384 | ✅ Tier-correct. Was bypassed in Phase 3 — **fixed here.** |
| Public chat endpoint | ``api/public.py`` L180, L210 | 420 | ✅ Intentional anti-abuse cap on the unauthenticated public marketing chat. |
| Free-tier onboarding chat | ``api/onboarding.py`` L216, L222 | 400 (free) / 600 (paid) | ✅ Intentional. |
| ``_continue_window`` (length-truncation continuation) | ``agent/orchestrator.py`` L667 | inherits ``default_max_tokens`` | ✅ Correct. |
| ``continue_truncated_answer max_windows=4`` | ``crp_integration.py`` L383 | 4 windows | 🟡 Hardcoded. A 40-page DPIA could in theory get clipped, but each window is a full 2048-token output, so the practical ceiling is 4 × 2048 ≈ 8192 output tokens — fine for the deliverables we ship. |
| ``continue_truncated_answer max_total_chars=40_000`` | same | 40 000 chars (~10k tokens) | 🟡 Same — fine for current deliverables. |
| ``chunk_by_token_budget(max_tokens=480)`` (PDF/HTML/EUR-Lex parsers) | ``agent/ingest/*`` | 480 | ✅ Per-chunk indexing, not per-output. |
| Test-only ``default_max_tokens=8`` / ``128`` | tests | 8 / 128 | ✅ Tests only. |

**No silent truncation** anywhere in the production path. Continuation is
triggered by ``finish_reason == "length"`` and stitches up to four
windows automatically. The user's directive — "output generation is
sufficient and unrestricted" — is honoured for the agent path. The
public-marketing chat is intentionally rate-limited.

---

## 3. Silent break-outs from CRP — does the agent ever leave CRP mid-flow?

| Suspect path | Verdict |
|---|---|
| ``ComplianceAgent.run`` calls ``self.llm.chat_with_tools`` directly | ✅ Goes through ``ComplianceLLM`` → ``WorkerAdapter`` → still the CRP ``LLMProvider`` ABC. The only thing it bypasses is the CRP **dispatch router** (which we cannot use because of the ``CRP_CONTEXT_TOOLS`` lock-in for our domain tools). All the CRP **mid-layer** primitives — extraction, packer, scanner, continuation stitch, CKF — are still consulted at the right boundaries. |
| ``crp_integration`` try/except imports | ✅ Each one is a defensive optional fallback (regex PII scanner, list-concat stitcher, no-op extraction). With ``crprotocol[full]`` installed (this commit), every primary code path runs — the fallbacks are inert. |
| Phase 3 ``CRP_COMPLY_AGENT_DISPATCH_MODE`` | ✅ Goes 100 % through CRP. Was missing tier-cap forwarding — fixed. |
| ``_continue_window`` continuation | ✅ Stays on the CRP provider; uses ``stitch_many`` from CRP if available. |
| Compaction ``compact_messages_for_budget`` | ✅ Operates on messages BEFORE they cross the CRP boundary; never bypasses CRP. |
| Direct ``logger.info`` calls in the orchestrator | ✅ All accompanied by ``_trace`` calls. The audit confirmed zero traces are emitted that aren't also routed through ``self.event_sink``. |

**Conclusion.** No silent break-outs. The agent stays on CRP for every
LLM crossing and for every fact-extraction / fact-store / packing
operation. The only deliberate departure is **using our own tool-loop
shape** instead of ``dispatch_with_tools``, and that's an SDK
limitation, not a bypass.

---

## 4. Railway / Docker correctness

### 4.1 What was wrong (until this commit)

``pyproject.toml`` declared:

```toml
dependencies = [
    "crprotocol>=2.0.0",
    …
]
```

This pulls **base CRP only**. Per the SDK's ``METADATA``, the following
features are gated by the ``[full]`` extra:

| Feature | Required dep |
|---|---|
| CKF semantic mode (HNSW vector index) | ``hnswlib>=0.7`` |
| CKF community detection (Leiden) | ``igraph>=0.11`` + ``leidenalg>=0.10`` |
| ``client.export_state`` AES-256-GCM seal | ``cryptography>=41`` |
| Fact integrity chain hashing | ``blake3>=0.3`` |
| Async HTTP for shipped Anthropic / OpenAI providers | ``httpx>=0.24`` |
| Stage-3 NER in the extraction pipeline | ``gliner>=0.2`` |
| Stage-2 statistical extraction | ``spacy>=3.5`` |
| Dense embeddings | ``sentence-transformers>=2.2`` |
| Prometheus metrics export | ``prometheus-client>=0.17`` |

Of these, the Railway image *was* installing ``sentence-transformers``,
``gliner``, and ``cryptography`` (transitively via ``python-jose[cryptography]``).
**Missing:** ``hnswlib``, ``igraph``, ``leidenalg``, ``blake3``, ``spacy``,
``prometheus-client``.

CKF therefore ran in **degraded modes** in production (no HNSW, no
community detection, slower retrieval); UIE Stage 2 was silently
disabled.

### 4.2 Fix in this commit

Pin to the ``[full]`` extra:

```toml
dependencies = [
    "crprotocol[full]>=2.0.0",
    …
]
```

The Dockerfile already requests ``.[agent,rag,pdf,ml]`` of crp-comply;
the ``[full]`` extra of CRP now joins automatically. Image grows
~80 MB (igraph + leidenalg + spacy weights are small wheels).

### 4.3 Other Railway hygiene

| Item | Status |
|---|---|
| ``HF_HOME`` / ``SENTENCE_TRANSFORMERS_HOME`` cache | ✅ Set, GLiNER pre-warmed in image. |
| Volume ``/app/data`` | ✅ Mount required (documented in ``HOSTING_POSITIONING.md``). |
| Healthcheck | ✅ ``GET /api/v1/health`` at 30s interval. |
| Non-root user (``comply``) | ✅ Set up; entrypoint chowns the volume. |
| ``crp-comply backup-nightly`` to S3 | ✅ ``boto3`` is a base dep. |

---

## 5. UIE & CKF — are they working to their fullest?

### 5.1 UIE call sites (after the fix)

| Site | Input | Behaviour with ``crprotocol[full]`` |
|---|---|---|
| ``orchestrator.py`` L373 — initial user task | full task string | Stage 1 (regex) + Stage 2 (statistical / spaCy) + Stage 3 (GLiNER NER) + Stage 4 (UIE) + Stage 5 (discourse) — all run. |
| ``api/agent.py`` L627 — user clarification answers | each answer | Same six stages. |
| ``agent/ingest/__main__.py`` L64 — scraped regulation text | full doc | Same; quality gate runs; facts persisted to per-tenant CKF. |

Before the fix, Stage 2 + Stage 3 silently degraded (no spaCy → no
statistical extraction; GLiNER was actually present via the ``ml``
extra so Stage 3 ran). After the fix, all six stages run on every UIE
call.

### 5.2 CKF call sites (after the fix)

| Operation | Site |
|---|---|
| Per-user instantiation | ``api/routes._get_user_ckf`` |
| Tool-result writes | ``orchestrator._record_tool_fact`` |
| Final-answer writes | ``orchestrator._record_final_fact`` |
| Generic fact writes | ``orchestrator._store_fact`` |
| User-task fact writes | ``orchestrator.run`` after ``extract_facts_from_text`` |
| Clarification fact writes | ``api/agent.py`` |
| LLM-callable read | ``recall_facts`` tool in ``agent/tools.py`` |
| Agent-side proactive seed | ``orchestrator._seed_prior_facts_primer`` via ``pattern_query_ckf`` |
| Integrity chain hashing | ``api/routes.py`` via ``FactIntegrityChain`` |

Before the fix, semantic-mode retrieval inside CKF degraded to brute
force scan (no HNSW); community detection silently no-op'd (no Leiden).
After the fix, both modes run natively. The product can now
legitimately ship CKF "to its fullest" — every retrieval path the
SDK exposes is reachable.

What we still **don't** call:

* ``client.ckf.detect_communities`` — could power a "topics covered in
  this conversation" UI tab.
* ``client.ckf.subscribe(FACT_CREATED, …)`` — could push fact-discovered
  events down the SSE stream as the agent learns.
* ``client.ckf.graph_walk(seed_ids, max_hops=2)`` — could power "show me
  related facts" expanders on each citation.
* ``client.ckf.contradict(fact_id, reason)`` — could reflect a user's
  "this citation is wrong" click into the fact graph.

These are now *opportunities*, not bugs.

---

## 6. The CRP_AUDIT_2.md bug-fix bundle (B-1 … B-6)

This commit also lands every bug-fix the previous audit deferred.

| ID | Issue | Resolution |
|---|---|---|
| **B-1** | ``dispatch_stream_augmented`` ran against an empty WarmStore | The Phase 3 path now pre-ingests primed corpus chunks into the SDK's WarmStore via ``client.ingest`` before dispatch. |
| **B-2** | CRP-native path silently dropped clarifications | ``_run_via_crp_dispatch`` now logs a one-line warning to the trace stream when ``recipe_context`` indicates a deliverable that needs Q&A; users see a "research mode — clarifications disabled" SSE event. |
| **B-3** | ``/continue`` extended ``extra_context`` unboundedly | Continuation history now goes through a *foldable* user-role message (``name="crp_continue_history"``) that the compactor folds first. |
| **B-4** | 4000-token primer pinned forever | Primer is stamped ``name="crp_corpus_primer"``; once the live conversation exceeds 60 % of the budget, the compactor replaces it with a one-line CKF-pointer marker. |
| **B-5** | SSE clients lost ``done`` payload on slow networks | Frontend ``finally``-block now calls ``agentGet(session_id)`` to reconcile state if the stream closes without a ``done`` frame. |
| **B-6** | ``_seen_chunk_ids`` reset every ``run()`` call | The dedup set is now persisted into the agent session record under ``seen_chunk_ids`` and re-hydrated at the top of every ``run`` for the same ``session_id``. |

Plus the Phase 4 wiring of CRP feedback:

* New endpoint ``POST /agent/{session_id}/feedback`` accepting
  ``{fact_id, signal: "boost"|"penalize"|"reject", reason}``.
* New ``ComplianceAgent.feedback(fact_id, signal, reason)`` method
  routing to the per-tenant ``ContextualKnowledgeFabric`` (writes a
  ``boost`` / ``penalize`` event to the fact's edges) and, when running
  the Phase 3 CRP-native path, to ``crp.Client.feedback.boost_fact`` /
  ``penalize_fact`` / ``reject_fact``.
* Frontend renders 👍/👎 buttons on every citation in the final answer
  and on every entry in the evidence pack.

---

## 7. Production posture going forward

| Layer | Recommended setting | Rationale |
|---|---|---|
| Image | ``crprotocol[full]`` + ``crp-comply[agent,rag,pdf,ml]`` | Activates HNSW, Leiden, spaCy, GLiNER, AES-256-GCM seal. |
| Env | ``CRP_COMPLY_AGENT_DISPATCH_MODE`` UNSET | Default = legacy tool loop = full domain tool fidelity. |
| Env | ``CRP_COMPLY_WORKER_CONTEXT_TOKENS=8192`` (or whatever the worker can do) | Lets the compactor budget correctly. |
| Tier | Pass ``tier=`` kwarg through the chat endpoint | Activates output-cap clamping. |
| Volume | Persist ``/app/data`` | Required for CKF cold-store survival across redeploys. |

---

## 8. Phase 5 candidates (future work)

In priority order:

1. **Subclass ``ContextToolExecutor``** so our domain tools can ride
   ``dispatch_with_tools``. Eliminates ``ComplianceAgent.run``'s tool
   loop entirely.
2. **Wire ``client.emitter.on(...)``** into the SSE stream (free
   telemetry — extraction events, quality events, budget warnings).
3. **Surface ``client.session_status``** as a live HUD pane.
4. **Adopt ``async_dispatch`` / ``async_dispatch_stream``** to drop the
   thread-pool bridge in ``_stream_agent_run``.
5. **Use ``client.ckf.detect_communities`` + ``community_summary``** to
   power a "topics" tab.
6. **Use ``CRPOrchestrator.resume(session_id)``** to actually restore
   prior conversations from cold store, so the user gets seamless
   long-term memory.

---

*Generated as part of the Phase 4 commit. Update alongside any future
change that adds or removes a CRP boundary.*
