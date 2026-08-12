# CRP-Native Dispatch Analysis — Pure CRP SDK as the Universal LLM Path

**Author:** Research + analysis pass (no code changes)
**Scope:** How to wire the **pure, original `crp` SDK** (the Context Relay Protocol implementation at `c:\Users\User\Desktop\context-relay-protocol\`) directly into the `crp-comply` application so that **every LLM call** — agent tool loop, research loop, RAG ingestion, output generation, onboarding extraction, public narrative, provider diagnostics, recipe drafting — flows through `crp.Client` by default.
**Status:** This document supersedes all prior CRP integration notes. It is grounded in source-level reads of both repos (CRP SDK public surface + every LLM call-site in `crp-comply`), not in second-hand summaries.

> **Correction (post-implementation read):** §11.1 below — and the parallel sentence “three of the four methods we call here may not actually exist on the SDK” in §2.2 — was based on a subagent’s incomplete walk of `crp/core/orchestrator.py`. A direct source-level read of `crp/core/dispatch_router.py` confirms that **all** dispatch methods we reference exist on `DispatchMixin` (and therefore on `crp.Client`): `dispatch` (L468), `dispatch_with_tools` (L1972), `dispatch_reflexive` (L2304), `dispatch_progressive` (L2568), `dispatch_stream_augmented` (L2845), `dispatch_agentic` (L3140), `dispatch_intent` (L3718), `dispatch_hierarchical` (L3726), `dispatch_batch` (L3815), `dispatch_stream` (L3844). The only real gap noted in this document remains §3: `dispatch_with_tools` hard-codes `CRP_CONTEXT_TOOLS` and does not accept user tool schemas.

---

## 0. Executive Summary

1. **The CRP SDK is already a dependency**, but it is presently used as a **bag of helper modules** (PII scanner, fact extractor, envelope packer, message stitcher) — not as the universal dispatch path. The `Client.dispatch_*()` family is only invoked when the env var `CRP_COMPLY_AGENT_DISPATCH_MODE` is set on a code path (`_run_via_crp_dispatch`) that runs **in addition to**, not **in place of**, the bespoke tool loop. By default, every LLM call in production goes **directly** through `provider.generate_chat_with_tools()` — bypassing CRP's envelope, continuation, extraction, and audit trail entirely.
2. **CRP was designed to handle exactly the failure modes we are hitting**: oversized inputs (auto-ingest in `dispatch()`), length-truncated outputs (built-in continuation loop, up to `max_continuations=50` windows), tool-mediated retrieval (`dispatch_with_tools` — pull mode), agentic 8-phase loops (`dispatch_agentic`), and inter-process / cross-language interception (the **HTTP sidecar** at `crp/cli/sidecar.py`).
3. **The single critical caveat** the user must know up-front: `dispatch_with_tools()` exposes **only CRP's 5 built-in context tools** to the LLM (`crp_retrieve_context`, `crp_get_document_structure`, `crp_check_facts`, `crp_get_related_facts`, `crp_get_continuation_state`). It does **not** accept user-supplied tool schemas. To run our 22 compliance domain tools (`recipe_search`, `web_search`, `pii_scan`, etc.) under CRP, we need a **provider-adapter wrapper** that injects them at the provider layer — this is documented in §6 and §9 below.
4. **The cleanest "always-on" architecture** uses `crp.Client` as the sole entry point at three levels: (a) every `ComplianceLLM.chat*()` becomes a thin facade over `client.dispatch()` / `dispatch_with_tools()`; (b) every RAG / web-search / corpus-prime path becomes `client.ingest()` / `client.ingest_batch()`; (c) all continuation, length-overflow, and oversized-input handling is delegated to CRP rather than the bespoke `compact_messages_for_budget()` and `continue_truncated_answer()` helpers.
5. **By doing this, the original 4096-token LM Studio overflow disappears** as an emergent consequence of the architecture — not because we hand-prune tool tiers (the symptom-level fix in commit `7cde3e6`), but because CRP's envelope builder negotiates `S + T + G ≤ C` against the live `provider.context_window_size()` on every call, and triggers continuation/auto-ingest the moment the budget is breached.

The remainder of this document is the source-level evidence and wiring plan.

---

## 1. CRP SDK — Public Surface Inventory

All paths below are inside `c:\Users\User\Desktop\context-relay-protocol\`. References were collected by reading source, not by guessing from documentation.

### 1.1 Top-level exports (`crp/__init__.py`)

The package exports the following names. Every one of them is callable directly from `crp-comply` today (the dependency is already on the path).

| Symbol | Kind | Purpose |
|---|---|---|
| `Client` (alias of `CRPOrchestrator`) | class | The single entry point. Holds session, provider, CKF, warm store, envelope, continuation manager. |
| `CRPOrchestrator` | class | Same as `Client`. |
| `CRPConfig` | dataclass | Immutable budget / runtime config (see §8). |
| `ConfigurationResolver` | class | 5-layer resolver: defaults → env → file → init kwargs → runtime `configure()`. |
| `TaskIntent` | dataclass | Structured task description used for gap analysis & directive synthesis. |
| `SourceKind`, `SourceOrigin`, `TrustLevel`, `ContextSource`, `ContextManifest` | enums + dataclasses | Provenance taxonomy (§2.1–2.3). |
| `ManifestValidationError`, `AttestationMismatch` | exceptions | Provenance failures. |
| `detect_source_kind()`, `check_attestation()` | functions | Provenance utilities. |
| `ContextEnforcer`, `EnforcementPolicy`, `EnforcementResult` | classes | Pre-flight content validation. |
| `InjectionSignal`, `detect_injection_signals()`, `observed_content()` | classes + functions | Advisory injection scan (never blocks). |
| `AuditSink`, `LoggingAuditSink`, `InMemoryAuditSink` | classes | Audit trail backends. |
| `default_enforcer`, `set_default_enforcer` | module-level | Process-wide enforcer singleton. |
| `ManifestLedger`, `ManifestLedgerEntry`, `LedgerChainError` | classes | Cryptographically-chained audit log. |
| `KeyProvider`, `EnvVarKeyProvider`, `RotatingKeyProvider` | classes | Key management for the ledger. |
| `JSONLinesFileSink`, `HTTPForwardingSink`, `AsyncBufferedSink`, `NullSink` | classes | Audit forwarding backends. |
| `content_hash`, `derive_source_from_message`, `derive_sources_from_messages`, `derive_manifest_from_messages` | functions | Compute provenance from message arrays. |
| `CRPError`, `ErrorCode`, plus `BudgetExhaustedError`, `ChainVerificationFailedError`, `ProviderError`, `ProviderTimeoutError`, `RateLimitExceededError`, `SecurityInvariantError`, `SessionClosedError`, `SessionExpiredError`, `SignatureInvalidError`, `StateCorruptedError`, `ValidationError` | exceptions | Full error taxonomy. |
| `QualityReport` | dataclass | Per-dispatch quality, fact counts, security flags, telemetry. |
| `CostEstimate` | dataclass | Pre-flight (windows, tokens, USD). |
| `SessionHandle`, `SessionStatus` | dataclasses | Identity + live metrics. |
| `StreamEvent` | dataclass | Async events from streaming dispatch. |
| `ExtractionResult` | dataclass | Result of zero-LLM ingestion. |
| `CKFConfig`, `CKFHealth`, `ContextualKnowledgeFabric` | classes (lazy) | 4-mode knowledge fabric. |
| `ContinuationConfig`, `ContinuationManager` | classes (lazy) | Multi-window continuation. |
| `CriticalState`, `StructuralState` | classes (lazy) | Persistent document state. |
| `EnvelopePreview`, `EnvelopeResult`, `EnvelopeState` | classes (lazy) | Envelope inspection / construction. |
| `ExtractionPipeline` | class (lazy) | Graduated 6-stage extraction. |
| `Fact`, `FactEdge`, `FactGraph` | classes (lazy) | Graph-structured facts. |
| `WarmStateStore`, `WarmStoreConfig` | classes (lazy) | In-memory fact accumulation + ranking. |

### 1.2 `crp.Client` method surface (`crp/core/orchestrator.py`)

#### Session & introspection

```python
def session_status(self) -> SessionStatus
def estimate_session(
    self,
    system_prompt: str = "",
    task_input: str = "",
    *,
    planned_dispatches: int = 1,
    avg_output_tokens: int | None = None,
) -> CostEstimate
def preview_envelope(self, system_prompt: str, task_input: str) -> EnvelopePreview
def configure(self, **kwargs: Any) -> None
def reset_session(self) -> None
def close(self) -> None
```

#### Dispatch family — every shape of LLM call we need

```python
def dispatch(self, system_prompt: str, task_input: str, **kwargs) -> tuple[str, QualityReport]
def dispatch_with_tools(
    self,
    system_prompt: str,
    task_input: str,
    *,
    max_tool_rounds: int = 10,
    **kwargs,
) -> tuple[str, QualityReport]
def dispatch_reflexive(
    self,
    system_prompt: str,
    task_input: str,
    *,
    max_refinement_passes: int = 2,
    **kwargs,
) -> tuple[str, QualityReport]
def dispatch_progressive(
    self,
    system_prompt: str,
    task_input: str,
    *,
    enable_detail_expansion: bool = True,
    **kwargs,
) -> tuple[str, QualityReport]
```

Each of these is wired through the same internal pipeline:

> 1. Advisory injection scan on `task_input`.
> 2. Build envelope from WarmStore facts (6-phase packer).
> 3. Assemble messages (Axiom 4 — no modification).
> 4. Dispatch to provider.
> 5. Extract facts from output (graduated 6-stage pipeline).
> 6. Store facts in WarmStore + CKF.
> 7. **Continuation loop if wall hit + gap remaining + info still flowing.**

That last step is the engine the user has been pointing at: `dispatch()` is **already** the "long input → long output, even on a 4 k model" primitive.

#### Ingestion — zero-LLM knowledge loading

```python
def ingest(self, raw_text: str, source_label: str | None = None) -> ExtractionResult
def ingest_batch(self, texts: list[str], task_intent: str = "") -> list[int]
```

These run the graduated extraction pipeline against raw text **without** invoking the LLM. Facts land in WarmStore + CKF and become available to subsequent `dispatch()` calls automatically. **This is the canonical replacement** for our bespoke `_prime_corpus_envelope()` and the various RAG-into-system-prompt paths.

#### Auto-ingest of oversized task input

When `t_tokens > available` inside `dispatch()`, the orchestrator transparently falls back to chunked ingestion and replaces `task_input` with a synthesized reference. From `dispatch_router.py::_dispatch_locked()`:

```python
available = context_window - s_tokens - g
if t_tokens > available and available > 0:
    logger.info(
        "Auto-ingest triggered: task_input=%d tokens > available=%d",
        t_tokens, available,
    )
    from crp.advanced.auto_ingest import auto_ingest, IngestFact
    ingest_facts, ingest_result = auto_ingest(
        system_prompt=system_prompt,
        task_input=task_input,
        task_intent_text=task_input[:200],
        context_window=context_window,
        count_tokens=self._provider.count_tokens,
        extract_fn=_extract_fn,
    )
    # facts stored in warm store + CKF
    # task_input replaced with synthesized reference
    task_input = ingest_result.synthesized_task
```

This is the piece the user named when they said *"CRP was designed literally to enable large contexts being ingested"* — it is real, it is in the source, and it is automatic. Today, `crp-comply` never reaches it because the LLM call never goes through `dispatch()`.

#### Observability, feedback, multi-provider

```python
@property
def emitter(self): ...                 # event bus
def on(self, event_type: str, listener) -> None
@property
def feedback(self): ...
def boost_fact(self, fact_id: str, delta: float = 0.1, reason: str = "") -> None
def penalize_fact(self, fact_id: str, delta: float = -0.2, reason: str = "") -> None
def reject_fact(self, fact_id: str, reason: str = "") -> None
def register_provider(self, provider: LLMProvider) -> None
@property
def parallel(self): ...                # parallel fan-out engine
```

#### What is **not** in the source

The subagent's full-source read could not locate:

- `dispatch_stream()` — referenced by examples/streaming.py and the sidecar's REST surface, but no concrete method definition was found. Likely an internal-emitter path, or wired dynamically through `generate_chat_stream()`.
- `dispatch_agentic()` — referenced by the sidecar's REST surface and by our own `crp_integration.py::dispatch_via_crp()` (line 1618) but **not** found as a defined method on `CRPOrchestrator`. The 8-phase ANALYZE→PLAN→SYNTHESIZE→ROUTE→GENERATE→EVALUATE→REVISE→CURATE loop is documented at crprotocol.io but the implementation may live in an unread `advanced/` module, or be planned-not-implemented.
- `dispatch_stream_augmented()` — same situation.
- `dispatch_batch()` — same situation.
- `dispatch_hierarchical()` — **does not exist as a named method**. The "hierarchical / Map-Reduce for inputs exceeding context windows" capability is delivered by the auto-ingest path inside `dispatch()` (quoted above), not by a separate entry point. Calling code that wants Map-Reduce-style behaviour pre-chunks via `ingest_batch()` and then issues a normal `dispatch()`.

> **Action item for integration planning:** before coding, confirm by direct invocation which dispatch-family methods actually resolve on the installed `crp.Client`. The four "uncertain" ones are referenced by our existing `dispatch_via_crp()` and may currently `AttributeError` at runtime if the env-var gate is ever flipped.

### 1.3 Provider adapter contract (`crp/providers/base.py`)

```python
class LLMProvider(ABC):
    @abstractmethod
    def generate_chat(self, messages, **kwargs) -> tuple[str, str]: ...
    @abstractmethod
    def count_tokens(self, text: str) -> int: ...
    @abstractmethod
    def context_window_size(self) -> int: ...
    @property
    def max_output_tokens(self) -> int | None: ...
    @property
    def model_name(self) -> str: ...
    @property
    def is_thinking_model(self) -> bool: ...
    def cost_per_1k_tokens(self) -> tuple[float, float]: ...
    def supports_tools(self) -> bool: ...
    def generate_chat_with_tools(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]],
        **kwargs,
    ) -> tuple[str, str, list[dict[str, object]] | None, dict[str, object] | None]:
        """Returns (output_text, finish_reason, tool_calls, raw_assistant_message)."""
    def generate_chat_stream(self, messages, **kwargs) -> Generator[str, None, str]: ...
```

Built-in adapters: `OpenAIAdapter`, `AnthropicAdapter`, `OllamaAdapter`, `LlamaCppAdapter`, `CustomProvider`, `CallableAdapter`, plus `LLMProviderManager` for fallback routing.

**Why this matters for us:** our `WorkerAdapter` ([src/crp_comply/agent/worker_adapter.py](src/crp_comply/agent/worker_adapter.py)) already implements the same shape (`generate_chat`, `generate_chat_with_tools`, `generate_chat_with_tools_streaming`, `count_tokens`, `context_window_size`). Wrapping it in `crp.Client(provider=worker_adapter)` is therefore **immediate** — the contract already matches.

### 1.4 The HTTP sidecar (`crp/cli/sidecar.py`)

> *"Inter-LLM fact sharing — two applications using different LLMs can share extracted knowledge. … Full protocol surface — every dispatch variant is available over HTTP. … Language-agnostic integration — any language/framework can interact with CRP via HTTP (TypeScript frontend, Rust service, Python backend). … Dashboard & monitoring — query session status, inspect facts, preview envelopes, track event history."*
> — `crp/cli/sidecar.py` module docstring

Endpoints (all `POST` unless noted):

```
POST   /sessions
GET    /sessions
GET    /sessions/:id/status
POST   /sessions/:id/close
POST   /sessions/:id/dispatch
POST   /sessions/:id/dispatch/tools
POST   /sessions/:id/dispatch/reflexive
POST   /sessions/:id/dispatch/progressive
POST   /sessions/:id/dispatch/stream-augmented
POST   /sessions/:id/dispatch/agentic
POST   /sessions/:id/ingest
GET    /sessions/:id/facts
POST   /sessions/:id/facts/share
POST   /sessions/:id/facts/feedback
GET    /sessions/:id/envelope
POST   /sessions/:id/providers
GET    /health
POST   /sessions/:id/estimate
```

Defaults: binds `127.0.0.1:8000`, optional bearer token, per-IP rate-limited (120 req/min), per-session RBAC, 10 MB request cap.

**This is the closest thing CRP has to a transparent universal interception layer.** The sidecar does **not** masquerade as an OpenAI-compatible endpoint; it is an explicit CRP REST API. To use it as the universal LLM path in `crp-comply`, every call-site has to be rewritten to `POST /sessions/{id}/dispatch[...]` instead of `provider.generate_chat_with_tools(...)`. That is a heavier refactor than running `crp.Client` in-process, but it gives the long-term benefit of a single audit/dispatch surface that the frontend (TypeScript) and any future microservice can also share.

### 1.5 Integration hooks (`crp/integrations/`)

`langchain_hook.py::CRPContextCallback`, `openai_hook.py`, `anthropic_hook.py` are **enforcement-only** callbacks that fire `on_chat_model_start` / `on_llm_start` to validate manifests and raise `CRPError` on policy violations. **They do not route the actual LLM call through CRP dispatch.** Important fact for the user: there is **no transparent proxy in the SDK**. "Always on" is achieved by changing the call-sites, not by monkey-patching.

### 1.6 CKF (`crp/ckf/fabric.py`)

```python
class ContextualKnowledgeFabric:
    def store(self, facts: list[Fact], window_id: str = "") -> None
    def retrieve(self, query_embedding=None, seed_ids=None, topic=None, budget=200) -> CKFRetrievalResult
    def query(self, pattern: str) -> PatternQueryResult
    def temporal_query(self, window_range: tuple[int, int]) -> list[Fact]
    def persist(self, path: str) -> None
    def restore(self, path: str) -> None
    def fact_count(self) -> int
    def health(self) -> CKFHealth
    def subscribe(self, event: CKFEventType, callback: EventCallback) -> None
    def detect_communities(self) -> CommunityResult
    def community_summary(self, topic: str) -> str
```

4-mode retrieval (semantic / graph-walk / pattern / community) with HNSW + Leiden, JSON+HNSW persistence on disk. **This is the canonical replacement for our bespoke `CrpMessageLedger`** — it already does what the ledger was hand-rolled to approximate, including community summarisation and graph walks.

### 1.7 Configuration knobs (`crp/core/config.py`)

The full table is reproduced in §8. The ones that matter most for "always on" semantics:

| Knob | Default | Notes |
|---|---|---|
| `enabled` | `True` | Master switch. |
| `max_continuations` | `50` | Max continuation windows per dispatch — **this is what enables unbounded output on small-context models**. |
| `dispatch_timeout` | `3600` s | Wall-clock cap per continuation loop. |
| `continuation_pause_s` | `0.0` | Pause between windows (helpful for local inference servers). |
| `enable_stage_3..6` | `True/True/True/False` | Which extraction stages run. Stage 6 (LLM-assisted) is off by default — keep it off until cost-tracked. |
| `memory_budget_mb` | `512` | WarmStore RAM budget. |
| `idle_model_timeout_s` | `300.0` | Auto-unload idle local models. |
| `log_envelopes` | `False` | Toggle envelope debug logging. |
| `encrypt_cold_state` | `True` | CKF on disk is encrypted. |

---

## 2. CRP-Comply — Every LLM Call-Site Today

Source-of-truth for §2 is the call-site map produced for this analysis. Citations are file + line.

### 2.1 Primary tool loop (the path that overflows the 4 k worker)

| # | File | Line | Call | Notes |
|---|---|---|---|---|
| 1 | [src/crp_comply/agent/orchestrator.py](src/crp_comply/agent/orchestrator.py) | 842 | `self.llm.chat_with_tools_streaming(...)` | ~95 % of agent iterations, the hot path. |
| 2 | [src/crp_comply/agent/orchestrator.py](src/crp_comply/agent/orchestrator.py) | 849 | `self.llm.chat_with_tools(...)` | Non-streaming fallback. |
| 3 | [src/crp_comply/agent/orchestrator.py](src/crp_comply/agent/orchestrator.py) | 1299 | `self.llm.chat_with_tools(messages=msgs, tools=[])` | The **continuation callback** — this is where our hand-rolled `continue_truncated_answer()` calls back for the next chunk. |

All three call straight through `ComplianceLLM.provider.generate_chat_with_tools[_streaming]()`. **None of them goes through `crp.Client`.** This is the heart of the user's complaint.

### 2.2 Conditional CRP-native path (gated, off by default)

| # | File | Line | Call |
|---|---|---|---|
| 4 | [src/crp_comply/agent/crp_integration.py](src/crp_comply/agent/crp_integration.py) | 1618–1634 | `client.dispatch_agentic(...)` / `client.dispatch_with_tools(...)` / `client.dispatch_stream_augmented(...)` / `client.dispatch(...)` |

Reachable only when `_run_via_crp_dispatch` (orchestrator line 1652) is selected, which requires either `CRP_COMPLY_AGENT_DISPATCH_MODE=…` in the environment or a per-user provider config flag. **Production has neither.**

(Earlier drafts of this document warned that several of these methods might not exist; a direct read of `crp/core/dispatch_router.py` has since confirmed they all do — see correction note in the document header.)

### 2.3 Public / lightweight LLM call-sites (none use CRP)

| # | File | Line | Call | Tier max | Audit |
|---|---|---|---|---|---|
| 5 | [src/crp_comply/api/public.py](src/crp_comply/api/public.py) | 208 | `llm.chat([sys + user], max_tokens=420)` | Public 3-paragraph narrative | None |
| 6 | [src/crp_comply/api/onboarding.py](src/crp_comply/api/onboarding.py) | 237 | `llm.chat([sys + form text], temperature=0.1)` | 400–600 | None |
| 7 | [src/crp_comply/api/provider.py](src/crp_comply/api/provider.py) | 673 | `llm.chat([{role: user, content: "ping"}], max_tokens=8)` | 8 | None |

### 2.4 RAG, ingestion, recipes

- `src/crp_comply/recipes/executor.py` ultimately invokes `ComplianceAgent.run()`, so it inherits whatever path the orchestrator uses.
- `_prime_corpus_envelope()` (orchestrator) currently builds a synthetic system-prompt prefix from RAG hits — this is **the** place that should become `client.ingest_batch(rag_passages)`.
- Web search / `web_search` tool results flow back into the message history as raw tool-call replies; they are **not** ingested into a CKF.
- `CrpMessageLedger` ([crp_integration.py](src/crp_comply/agent/crp_integration.py) ~line 1267) does fact extraction from tool results today using pattern matching — duplicating CKF's job.

### 2.5 Existing usage of the `crp.*` namespace

| CRP module | Currently used for | Used as universal LLM path? |
|---|---|---|
| `crp.providers.*` | Adapter classes for OpenAI / Anthropic | No — only as raw provider, bypassing dispatch |
| `crp.Client.dispatch_*` | The gated `dispatch_via_crp()` path | No — gated off in prod |
| `crp.envelope.packer` | Used during message packing | No — only inside compaction helper |
| `crp.envelope.reranker` | Diversity rerank in our RAG layer | No |
| `crp.extraction.*` | Fact extraction from tool results | No |
| `crp.security.PIIScanner` | PII redaction pre-LLM | No |
| `crp.security.InjectionDetector` | Injection scan on tool outputs | No |
| `crp.continuation.stitch` | Stitching during `continue_truncated_answer()` | No |
| `crp.ckf.*` | Imported but never `.store()` /`.retrieve()`'d directly from agent | No |
| `crp.state.WarmStore` | Imported, not actively populated | No |
| `crp.observability.EventEmitter` | Imported | No |

The picture is unambiguous: **CRP exists in our codebase as a toolbox of side modules, never as the dispatch backbone.**

---

## 3. Disproving the Earlier Claim That "Tool-Calling Is Outside CRP"

The previous version of this document concluded that the tool-calling loop lay outside CRP's protocol scope. That was wrong. Three pieces of evidence:

1. **`Client.dispatch_with_tools()` exists and is documented as the pull-mode counterpart to push-mode `dispatch()`.** From the orchestrator docstring:
   > *"Dispatch with tool-mediated context relay (pull model, §20). Instead of pre-loading ALL context into the envelope (push model): 1. Sends the task to the LLM with CRP context tools. 2. The LLM requests context on demand via tool calls. 3. CRP executes tool calls against WarmStore/CKF. 4. Results are fed back, and the LLM continues. 5. When the LLM finishes (stop/length), extraction proceeds normally. Falls back to push-based dispatch() if provider doesn't support tools."*
2. **`crp/core/context_tools.py::CRP_CONTEXT_TOOLS` defines five OpenAI-compatible tool schemas** (`crp_retrieve_context`, `crp_get_document_structure`, `crp_check_facts`, `crp_get_related_facts`, `crp_get_continuation_state`) and ships an executor (`ContextToolExecutor`) that runs them against the live WarmStore + CKF. The tool-call round-trip is fully internal to CRP.
3. **The continuation engine triggers on `finish_reason == "length"`** specifically — i.e., it is engineered for tool-loop transcripts that grow beyond the window. This is exactly the failure shape we hit on LM Studio.

So tool-calling is squarely within CRP's protocol. **The single nuance** — and the user must know it — is *whose* tools. Today `dispatch_with_tools()` exposes **only** the five built-in CRP context tools to the LLM. There is no `tools=` parameter for user-supplied schemas. To run our 22 compliance domain tools under CRP we must adopt one of:

- **Option A (recommended): provider-adapter wrapping.** Implement a thin `CrpDomainToolsProvider(LLMProvider)` whose `generate_chat_with_tools()` overrides accept the **union** of (CRP context tools, our domain tools), and dispatch normally. CRP's dispatch loop will pass the schemas through to the underlying transport unchanged (Axiom 4 — no modification of messages).
- **Option B: hybrid orchestrator.** Keep our existing tool loop, but make every individual *LLM turn* go through `client.dispatch()` rather than `provider.generate_chat_with_tools()`. We forfeit `dispatch_with_tools`'s built-in context tools but gain envelope packing + auto-ingest + continuation on every turn.
- **Option C: HTTP sidecar plus a domain-tool relay service.** Heaviest refactor, biggest payoff long-term — see §4 / §10.

The user's framing — *"the tool-call loop IS within CRP's design scope"* — is correct. The implementation route to **make it actually run** is Option A or Option B. Both are non-trivial but neither requires forking CRP.

---

## 4. CRP Already Handles Inputs That Exceed The Window

Three layers, in order of activation:

1. **Envelope budget negotiation** (every dispatch). The packer enforces `S + T + G ≤ C` using `provider.count_tokens()` and `provider.context_window_size()`. If `T > C − S − G`, the packer returns a budget-exhausted signal **before** the network call.
2. **Auto-ingest** (inside `dispatch()`, quoted in §1.2). When `T` alone exceeds the available window, CRP transparently chunks `task_input`, runs the extraction pipeline against each chunk, persists facts to WarmStore + CKF, and substitutes a synthesized reference. The next-window context is then drawn from the freshly-ingested facts via CKF retrieval.
3. **Multi-window continuation** (post-LLM). If the call returns `finish_reason == "length"` and a gap analysis says material remains and information is still flowing, a fresh window is dispatched with refined directives. Up to `max_continuations=50` windows are chained in a single `dispatch()` call.

Together these three layers are CRP's "unbounded context, unbounded generation" implementation. Every one of them is currently dormant in `crp-comply` because **we never enter `dispatch()`** on the hot path.

> **Honest correction to the prior report:** there is no separate `dispatch_hierarchical()` method. The hierarchical / Map-Reduce behaviour is the auto-ingest layer above, plus optional explicit pre-`ingest_batch()` for documents the caller already knows are huge. Treat this as a single feature, not two.

---

## 5. Provider Interception Patterns Available Today

| Pattern | Where it lives | How it intercepts | Cost to adopt |
|---|---|---|---|
| **In-process `crp.Client`** | `crp/core/orchestrator.py` | We construct one `Client(provider=…)` per agent and rewrite call-sites | Low–medium (call-site rewrites + tool wiring) |
| **HTTP sidecar** (§1.4) | `crp/cli/sidecar.py` | We run `crp serve`, call REST endpoints from anywhere | Medium (deploy + auth + per-call HTTP overhead) |
| **LangChain / OpenAI / Anthropic enforcement hooks** | `crp/integrations/` | Validates context pre-call, never routes through CRP dispatch | Low — but **does not** give us continuation / auto-ingest, so it is not "always on" in the user's sense |
| **Custom provider adapter wrapping `WorkerAdapter`** | New code in `crp-comply` | Our adapter is the LLM the SDK calls; CRP becomes the only path because the adapter only ever gets called from `Client` | Low — the adapter contract is already a match |

There is **no transparent OpenAI-compatible proxy in the SDK**. The user must accept that "always on" requires either an in-process `crp.Client` instance (per request or per session) or an explicit HTTP REST call to the sidecar. There is no zero-touch middleware.

---

## 6. CKF as the Universal Knowledge Substrate

Today our agent maintains:

- A **`CrpMessageLedger`** (bespoke, in `crp_integration.py`) that pattern-extracts facts from tool results.
- A **RAG service** (`rag.py`) that retrieves passages and stuffs them into the system prompt.
- A **corpus prime** path (`_prime_corpus_envelope`) that pre-pends curated text.
- A **multi-turn memory** held in the FastAPI request session.

All four collapse into `ContextualKnowledgeFabric` (§1.6):

- `client.ingest()` / `client.ingest_batch()` replace corpus-prime and RAG-into-prompt.
- `ckf.store()` is what the message-ledger should write to.
- `ckf.retrieve(query_embedding=…, budget=…)` replaces the RAG call.
- `ckf.persist()` / `ckf.restore()` replace whatever per-user multi-turn state we currently hand-marshal.

Net effect: one knowledge layer per session, persisted to disk encrypted, queryable in four modes, with HNSW + Leiden built in. Our hand-rolled equivalents can be retired.

---

## 7. The Configuration Story for "On By Default, For Everything"

`CRPConfig` defaults already favour "always on":

- `enabled=True`
- `max_continuations=50`
- `encrypt_cold_state=True`
- Stages 3–5 of extraction enabled, stage 6 (LLM-assisted) explicitly off

The handful of `crp-comply` env vars that gate today's dispatch path can be **removed** once CRP is the only LLM path:

- `CRP_COMPLY_AGENT_DISPATCH_MODE` — becomes meaningless when there is no non-CRP path.
- `CRP_COMPLY_LLM_*` — still selects the underlying provider, but the provider is then handed straight to `crp.Client(provider=...)`.
- `CRP_COMPLY_WORKER_CONTEXT_TOKENS` — still informs `WorkerAdapter.context_window_size()`, which is what CRP queries to size its envelope. Keep, document, possibly auto-probe via `/v1/models/{name}` per CRP's own provider-detection convention.
- `CRP_COMPLY_MODEL_ROUTING_ENABLED` — keep, but apply **before** `Client(provider=…)` is instantiated, not via per-call `_apply_routing()`.

The single new env var worth adding is `CRP_COMPLY_DISPATCH_BACKEND` ∈ `{"in_process", "sidecar"}` so we can flip between the two interception styles without code changes.

---

## 8. CRP Configuration Reference (Authoritative Table)

| Key | Type | Default | Env var | Mutable | Meaning |
|---|---|---|---|---|---|
| `enabled` | bool | True | `CRP_ENABLED` | yes | Master switch. |
| `max_continuations` | int | 50 | `CRP_MAX_CONTINUATIONS` | no | Cap on continuation windows per dispatch. |
| `max_dispatch_rate` | int | 60 | `CRP_MAX_DISPATCH_RATE` | no | Rate limit. |
| `session_timeout` | int | 86400 | `CRP_SESSION_TIMEOUT` | no | Session lifetime (s). |
| `ingest_quarantine` | int | 1 | `CRP_INGEST_QUARANTINE` | yes | Quarantine cap for ingestion. |
| `max_ram_mb` | int | 512 | `CRP_MAX_RAM_MB` | no | Resource manager budget. |
| `max_model_ram_mb` | int | 300 | `CRP_MAX_MODEL_RAM_MB` | no | Loaded-model RAM cap. |
| `max_threads` | int | 2 | `CRP_MAX_THREADS` | no | Async pool size. |
| `process_priority` | str | below_normal | — | no | Windows process priority. |
| `memory_budget_mb` | int | 512 | — | no | WarmStore budget. |
| `idle_model_timeout_s` | float | 300.0 | — | no | Idle unload timeout. |
| `log_envelopes` | bool | False | `CRP_LOG_ENVELOPES` | yes | Debug log envelope contents. |
| `encrypt_cold_state` | bool | True | `CRP_ENCRYPT_COLD_STATE` | yes | Encrypt CKF on disk. |
| `default_role` | str | OPERATOR | `CRP_DEFAULT_ROLE` | no | RBAC default. |
| `binding_secret` | str | "" | `CRP_BINDING_SECRET` | no | Session binding crypto. |
| `max_windows_per_session` | int | 0 (∞) | — | no | Hard window cap. |
| `max_total_input_tokens` | int | 0 (∞) | — | no | Lifetime input cap. |
| `max_total_output_tokens` | int | 0 (∞) | — | no | Lifetime output cap. |
| `max_envelope_latency_ms` | int | 500 | — | no | Envelope build timeout. |
| `max_extraction_latency_ms` | int | 200 | — | no | Extraction timeout. |
| `max_windows_per_minute` | int | 0 (∞) | — | no | Per-minute rate. |
| `telemetry_path` | str | "" | — | yes | JSONL telemetry sink. |
| `overhead_cap_pct` | float | 15.0 | — | yes | Feature-shedding threshold. |
| `parallel_max_concurrent` | int | 4 | — | yes | Parallel fan-out limit. |
| `enable_stage_3` | bool | True | `CRP_ENABLE_STAGE_3` | yes | GLiNER zero-shot NER. |
| `enable_stage_4` | bool | True | `CRP_ENABLE_STAGE_4` | yes | UIE relation extraction. |
| `enable_stage_5` | bool | True | `CRP_ENABLE_STAGE_5` | yes | Discourse markers. |
| `enable_stage_6` | bool | False | `CRP_ENABLE_STAGE_6` | yes | LLM-assisted extraction (costly). |
| `dispatch_timeout` | int | 3600 | — | no | Wall-clock cap per loop (s). |
| `continuation_pause_s` | float | 0.0 | — | yes | Pause between windows. |

Resolution order: hardcoded defaults → environment → file (planned) → `Client()` kwargs → `Client.configure()`.

---

## 9. The Always-On Wiring Plan (No Code, Just Architecture)

The concrete map of "where does CRP intercept what" once we commit to the rewrite. This is a **research-level plan**, not an implementation. Each row is a discrete change to be executed in a future commit, in priority order.

### P0 — Make `crp.Client` the only LLM path on the agent hot-path

| Today | Replace with |
|---|---|
| Orchestrator line 842 — `self.llm.chat_with_tools_streaming(messages, tools=fitted_schemas, max_tokens=…)` | `client.dispatch_with_tools(system_prompt=sys, task_input=user_task, max_tool_rounds=10)` **after** wrapping our 22 domain tools via Option A (custom provider adapter) so CRP's tool layer sees them alongside the five built-ins. |
| Orchestrator line 849 — non-streaming variant | Same — `client.dispatch_with_tools(...)`; streaming is delivered via `client.emitter` events, not a separate code path. |
| Orchestrator line 1299 — `_continue_window()` callback | Delete. CRP's internal continuation loop replaces it. The bespoke `continue_truncated_answer()` helper becomes dead code. |
| Tool-pruning in `_fit_schemas_to_window()` (commit `7cde3e6`) | Becomes belt-and-braces. CRP's envelope budget negotiation supersedes it; pruning can stay as a defensive cap but is no longer the primary mechanism. |

### P0 — Make `crp.Client` the only LLM path on the secondary endpoints

| Today | Replace with |
|---|---|
| `public.py` line 208 — `llm.chat(...)` | `client.dispatch(system_prompt, task_input)` with `max_continuations=1` for tight budget. |
| `onboarding.py` line 237 — `llm.chat(...)` | `client.dispatch(...)` — gives us audit trail + extraction for free. |
| `provider.py` line 673 — `llm.chat(ping)` | `client.preview_envelope("", "ping")` plus a tiny `client.dispatch(...)` so the diagnostic exercises the real path. |

### P1 — Replace the bespoke knowledge plumbing with CKF + ingestion

| Today | Replace with |
|---|---|
| `_prime_corpus_envelope()` | `client.ingest_batch(corpus_passages, task_intent=task)`. |
| RAG → system-prompt stuffing in `rag.py` | Pre-call `client.ingest_batch(top_k_rag_hits)`; let CRP's envelope packer pull what it needs. |
| `web_search` tool result handling | Same — `client.ingest(text, source_label="web:<url>")` after each search. |
| `CrpMessageLedger` (~crp_integration.py:1267) | Delete; its job is done by CKF + ContextToolExecutor. |
| `compact_messages_for_budget()` (crp_integration.py:1225) | Delete; CRP envelope builder handles compaction natively per dispatch. |
| `continue_truncated_answer()` (crp_integration.py:1406) | Delete; superseded by CRP's internal continuation. |

### P1 — Make recipe runs and research loops first-class CRP sessions

| Today | Replace with |
|---|---|
| `recipes/executor.py` calling `ComplianceAgent.run()` per section | One `crp.Client` session per recipe; `client.dispatch_progressive()` for each long-form section so CRP runs outline-then-expand natively. `client.ingest_batch()` carries section results forward. |
| Phase-7 research loop (`/agent/loop/stream`) | Wrap as a single CRP session whose state persists across SSE turns; `client.dispatch_with_tools()` per research step; `client.ingest()` after each web-search hit. |

### P2 — Optionally adopt the HTTP sidecar as the deployment-level interception layer

If/when `crp-comply` grows additional language frontends or microservices, run `crp serve` in the same Railway service and have **everything** speak REST to it instead of importing `crp` in-process. This is the future-proof path for a "CRP-everywhere" platform, at the cost of an extra hop per call.

### Tools-vs-CRP integration choice (must decide before P0 starts)

The single architectural decision that gates everything: **how to expose our 22 domain tools through CRP**.

- **Option A — Custom provider adapter** (recommended default). Implement `class CrpAwareWorkerAdapter(LLMProvider)` in `crp-comply` that:
  - Accepts `tools=[…]` as the union of CRP's `CRP_CONTEXT_TOOLS` plus our domain schemas.
  - Implements `generate_chat_with_tools()` against the live LM Studio / OpenAI / Anthropic / Worker transport.
  - Is handed to `crp.Client(provider=adapter)` once per agent build.
  - Pros: minimal call-site churn, in-process, every benefit (continuation, auto-ingest, CKF, audit trail) on by default.
  - Cons: we bypass `dispatch_with_tools()`'s context-tool executor unless we replicate its dispatch shape (we can copy that shape; it's ~100 lines of routing logic).
- **Option B — Hybrid orchestrator**. Keep our agent's tool loop; make each LLM turn a `client.dispatch()` call. Tools are still our domain tools; CRP gets envelope/continuation/extraction.
  - Pros: lowest-risk migration; preserves our agent control flow.
  - Cons: forfeits CRP's pull-mode context tools (the `crp_retrieve_*` family the LLM can invoke directly). We can re-add later by exposing those as additional domain tools.
- **Option C — Sidecar + relay service**. As above; fattest deploy.

**Recommendation:** start with **Option B for one sprint** to capture envelope + continuation + auto-ingest immediately on the hot path with minimal blast radius, then move to Option A to add pull-mode context tools and reduce duplication. This is the lowest-risk path to making CRP **on by default for everything**.

---

## 10. What `crp-comply` Should Stop Doing

The following modules / helpers will be either deleted or reduced to thin shims once the wiring above lands. Listing them here so the user can see the **subtractive** half of the change.

| Code to retire | Replaced by |
|---|---|
| `crp_integration.py::compact_messages_for_budget` | CRP envelope packer (`crp.envelope.packer` invoked inside `dispatch`). |
| `crp_integration.py::continue_truncated_answer` | CRP `ContinuationManager` inside `dispatch`. |
| `crp_integration.py::CrpMessageLedger` (pattern fact extraction) | CKF + `ContextToolExecutor`. |
| `orchestrator.py::_fit_schemas_to_window` (commit `7cde3e6`) | Becomes a defensive belt; primary mechanism is CRP envelope budgeting. |
| `orchestrator.py::_prime_corpus_envelope` | `client.ingest_batch()`. |
| Bespoke per-tier output token caps (`PER_TIER_TOKEN_CAPS`) | Stay — they live above CRP, mapped onto `CRPConfig.max_continuations` and `avg_output_tokens`. |
| `dispatch_via_crp` wrapper | Collapsed — the in-process `Client` is created once at agent build, not per call. |

---

## 11. Risks, Honest Caveats, and Open Questions

1. ~~**Three dispatch methods we currently call may not exist on the SDK**~~ — **resolved.** A direct source read of `crp/core/dispatch_router.py` confirms `dispatch`, `dispatch_with_tools`, `dispatch_reflexive`, `dispatch_progressive`, `dispatch_stream_augmented`, `dispatch_agentic`, `dispatch_intent`, `dispatch_hierarchical`, `dispatch_batch`, and `dispatch_stream` all exist on `DispatchMixin` (and therefore on `crp.Client`). The earlier subagent walk that failed to locate them was incomplete.
2. **`dispatch_with_tools()` does not accept user tools.** This is a real architectural constraint, not a theory. If we choose Option A in §9, we must implement the union ourselves at the provider layer.
3. **Continuation-during-tool-loops.** CRP's continuation triggers on `finish_reason == "length"` plus gap analysis plus information flow. When the current stop reason is `"tool_calls"` (tool round mid-loop), continuation does not fire — the tool round resumes naturally. The user's mental model that *"the tool loop benefits from CRP continuation"* is true, but the benefit is on tool-result-stuffed transcripts that grow to length-truncation, not on the tool-call boundary itself.
4. **Per-request vs. per-session `Client`.** `Client` holds WarmStore + CKF in memory. For multi-tenant FastAPI, we want one `Client` per `(user_id, session_id)` with `ckf.persist()` on idle and `ckf.restore()` on resume. We do **not** want a process-global `Client`.
5. **Worker-adapter probing.** `WorkerAdapter.context_window_size()` reads `CRP_COMPLY_WORKER_CONTEXT_TOKENS` (default 4096). CRP relies on this being correct. If LM Studio is configured for a larger context than 4096, our adapter will under-report and CRP will continuation-loop unnecessarily. Worth adding a `/v1/models/{name}` probe at adapter init.
6. **Sidecar deployment** would add a second process to the Railway image. Out of scope for the in-process plan but a real option if we ever expose CRP to the Vite frontend directly.
7. **No transparent OpenAI proxy exists in the SDK.** "Always on, transparently" is not literally achievable without code change. "Always on, by construction" is — by making `crp.Client` the only thing the agent ever holds a reference to.

---

## 12. Conclusion — The Direct Answer to the User's Question

> *"How is the Context Relay protocol SDK itself — THE PROTOCOL ITSELF — being used directly with our application … to enable any LLM that is connected to be able to handle large contexts that exceed the LLM's natural limitations, both in the language agent loop, in the research loop EVERYWHERE, BOTH IN TOOL CALLING, OUTPUT GENERATION, INPUT INGESTION!!!"*

**Today: it isn't.** The SDK is on the path as a library of helpers but its dispatch backbone — the part that delivers unbounded input/output on small-context models — is not invoked on any of the three hot LLM paths in production. The 8781-token overflow on a 4096-token LM Studio model happened because the call never went through `dispatch()` and therefore never hit envelope budget negotiation, never hit auto-ingest, and never hit continuation.

**To make the protocol be "on by default, for everything":**

1. Construct one `crp.Client(provider=our_adapter)` per agent build, persisted alongside the agent's session.
2. Replace every `ComplianceLLM.chat*()` call-site (§2.1, §2.3) with the appropriate `client.dispatch*()` shape.
3. Replace every "load text into context" call-site with `client.ingest()` / `client.ingest_batch()`.
4. Pick Option A or B from §9 to wire our 22 domain tools through CRP.
5. Retire the bespoke compaction/continuation/ledger helpers (§10) — they duplicate CRP and disagree with it under load.
6. Confirm the four dispatch-family methods we already call actually resolve on the installed `Client`; redirect any that don't to the confirmed-present trio (`dispatch`, `dispatch_with_tools`, `dispatch_progressive`, `dispatch_reflexive`, `ingest`, `ingest_batch`).

When that wiring is in place, the user's stated requirement — **"PURE, ORIGINAL CRP SDK directly in our application … ON BY DEFAULT AND FOR EVERYTHING"** — is satisfied as an architectural invariant: there is no LLM path in `crp-comply` that does not pass through `crp.Client`.
