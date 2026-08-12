# SLM Integration Research — Running CRP Comply on Small Local Models

> Status: research synthesis  
> Target: models with **< 15 B parameters**, especially the **8 B class** (e.g. Llama-3.1-8B, Qwen2.5-7B/8B, xLAM-2-8B, ToolACE-8B, watt-tool-8B) and smaller edge models (1–4 B).  
> Scope: CRP Comply agent loop, general CRP protocol usage, and pluggable SLM execution paths.  
> Companion document: [`LOCAL_8B_MODEL_ANALYSIS.md`](./LOCAL_8B_MODEL_ANALYSIS.md)

---

## 1. Executive Summary

The CRP Comply agent loop was designed around frontier models (Claude / GPT-4 class) that can ingest a long system prompt, 10+ tool schemas, conversation history, and reflection instructions in a single turn, then emit reliable tool calls. Small local language models (SLMs) in the 8 B class — even when the prompt physically fits in an 8 K context window — do not have the same **capability envelope**. They are slow at prompt-eval, easily fixate on one tool, produce malformed JSON arguments, and stall inside ReAct loops.

This document surveys academic and official/industry work from 2024–2026 on making SLMs efficient and correct inside agentic systems, then proposes concrete execution paths for CRP Comply and the CRP protocol. The core conclusion is:

> **Do not run the frontier agent loop unchanged on an SLM.** Instead, use capability tiers, aggressive context reduction, dynamic tool selection, grammar-constrained decoding, CRP-native chunking/continuation, and hybrid edge-cloud routing.

---

## 2. Deeper Problem Definition

### 2.1 Capability-envelope mismatch

A model can have a 128 K context window and still fail at multi-step tool use. Recent work repeatedly finds that open 7–8 B instruction models do not reliably engage in autonomous multi-step tool calling, even after parser/tokenizer fixes [[Cross-Turn Intent-Aware KV Cache Pruning, 2026](https://arxiv.org/html/2606.09916v1)]. The CRP Comply loop requires:

- understanding 13+ tools,
- following a 1,300-token system prompt,
- emitting JSON tool calls,
- reasoning over retrieved regulation text,
- self-correcting after reflection.

That combination is above the reliable operating envelope of an unmodified 8 B model.

### 2.2 Context-budget math is worse than it looks

With the current Comply system prompt (~4,500 chars ≈ 1,300 tokens) and 13 tool schemas (~4,100 tokens), an 8 K window leaves roughly **500–600 tokens** for user input, conversation history, and retrieved evidence [[LOCAL_8B_MODEL_ANALYSIS.md](./LOCAL_8B_MODEL_ANALYSIS.md)]. The prompt is not just large; it is **cognitively overloaded** for a small model.

### 2.3 Tool-schema overload

Small models suffer from:

- **Eager invocation** — calling tools for greetings.
- **Wrong tool selection** — picking a search tool when an add-to-cart tool is needed.
- **Malformed arguments** — missing or invalid parameters.
- **Ignored tool responses** — failing to react to returned results [[Docker local-LLM tool-calling evaluation, 2025](https://www.docker.com/blog/local-llm-tool-calling-a-practical-evaluation/)].

These are not transient bugs; they are symptoms of trying to fit too many in-context skills into too small a model.

### 2.4 Prefill latency and KV-cache pressure

Prompt-eval for Llama-3.1-8B at 8 K context is ~90–115 s on local hardware [[LOCAL_8B_MODEL_ANALYSIS.md](./LOCAL_8B_MODEL_ANALYSIS.md)]. Each turn recomputes the system prompt and tool schemas. Long-context attention is quadratic; the KV cache grows linearly and, in dense attention, dominates memory and decode cost.

### 2.5 Format adherence

Tool calls require strict JSON. Small models emit valid JSON only some of the time. Constrained decoding can enforce schema validity, but not every local server exposes it cleanly, and tool-name selection still depends on the model’s reasoning.

### 2.6 Quantization degrades agentic and long-context performance unevenly

- 8-bit quantization is nearly lossless (~0.8 % drop) on average.
- 4-bit methods can cause substantial losses, especially on long-context retrieval (up to 59 % in some configurations) and on reasoning/numerical tasks [[Mekala et al., EMNLP 2025](https://aclanthology.org/2025.emnlp-main.479.pdf)].
- BNB-NF4 (the default in HuggingFace / vLLM) is particularly fragile.
- ACBench reports 4-bit quantization preserves workflow generation and tool use (1–3 % drop) but degrades real-world tasks by 10–15 % [[ICML 2025](https://icml.cc/virtual/2025/poster/43871)].

> **Implication:** a Q4_K_M 8 B model may run, but its compliance-reasoning accuracy can collapse.

---

## 3. Research Findings by Category

### 3.1 Efficient inference and serving for SLMs

#### Quantization

- **GGUF / Q4_K_M**, **AWQ**, **GPTQ**, **FP8**, and mixed-precision schemes are the practical options.
- FP8 and INT8 preserve accuracy far better than INT4 for long-context and reasoning tasks.
- A 2026 NVIDIA paper recommends **NVFP4 for prefilling and BF16 for decoding** to keep agentic performance while accelerating the compute-heavy prefill phase [[Quantized Prefilling, Precise Decoding, 2026](https://arxiv.org/html/2605.20315v1)].

#### Serving frameworks

| Framework | Notes for CRP Comply |
|-----------|----------------------|
| **llama.cpp / LM Studio** | GGUF, grammar-constrained decoding, KV-cache quantization, slot-based prefix caching, speculative decoding. |
| **Ollama** | OpenAI-compatible API, structured outputs via JSON schema (since v0.5), LoRA adapters in Modelfile. |
| **vLLM** | PagedAttention, automatic prefix caching, guided decoding / structured outputs via XGrammar/Outlines, high throughput. |
| **SGLang** | RadixAttention for prefix sharing, jump-forward decoding for structured generation. |
| **MLX / MLX-LM** | Apple-silicon optimized, supports KV-cache quantization and speculative decoding. |

#### Prompt / prefix caching

- **llama.cpp** supports slot-based KV reuse; identical prompts reuse cached state, partial matches reuse the shared prefix [[llama.cpp KV-cache tutorial](https://github.com/ggml-org/llama.cpp/discussions/13606)].
- **vLLM** implements automatic prefix caching (APC) with Merkle-tree block hashing [[Feather, 2026](https://arxiv.org/html/2605.06046v1)].
- **SGLang** uses RadixAttention for hierarchical prefix sharing.
- **LMCache** is an emerging engine-independent KV-cache layer with tiered storage, non-prefix reuse, and cross-engine sharing [[LMCache docs](https://docs.lmcache.ai/)].

> CRP Comply should keep the system prompt and selected tool set **static within a session** so that prefix caching eliminates repeated prefill work.

#### Speculative decoding

- LM Studio added speculative decoding in v0.3.10, reporting 1.5–3× speedups with a small draft model [[LM Studio blog](https://lmstudio.ai/blog/lmstudio-v0.3.10)].
- On-device, the "multi-token tax" can eat the gains: verifying 2 tokens may take 1.86× longer than one token [[Agent-X, 2026](https://arxiv.org/html/2605.10380v1)].
- Best suited when a well-aligned draft model is available; not a universal fix for 8 B agents.

#### Context extension

- **YaRN**, **LongLoRA**, **LongRoPE**, and **ABF** can extend pretrained RoPE models to 64 K–2 M tokens with continued pretraining or fine-tuning [[LongLoRA paper](https://proceedings.iclr.cc/paper_files/paper/2024/file/211ab571cc9f3802afa6ffff52ae3e5b-Paper-Conference.pdf)] [[LongRoPE / YaRN survey](https://arxiv.org/html/2510.23081v1)].
- Longer context does not fix reasoning quality; for SLMs, **retrieval + chunking is usually more efficient than filling the window**.

#### Sparse attention / KV eviction

- **StreamingLLM**, **H2O**, **SnapKV**, **PyramidKV**, **DuoAttention**, **RazorAttention**, and **Recycled Attention** reduce KV-cache size and attention cost.
- These methods improve perplexity and local decoding speed but often degrade long-context synthesis and needle-in-haystack recall [[Recycled Attention, ICLR 2025](https://openreview.net/pdf?id=8qYuxV4lRu)].
- They are complementary, not a replacement for RAG/chunking in compliance tasks.

#### Alternative architectures: Mamba / RWKV / SSMs

- **Mamba** and **RWKV** offer linear-time inference and constant-memory states, attractive for very long contexts on edge devices [[Mamba/RWKV survey](https://blog.gopenai.com/deep-dive-into-mamba-rwkv-and-state-space-models-b45d5e6a38c9)].
- However, they lag Transformers on retrieval-style copying, in-context learning, and tool use [[Achilles’ Heel of Mamba, 2025](https://arxiv.org/html/2509.17514v1)].
- **Hybrid models** (Jamba, Zamba, RWKV-X) combine attention and recurrent layers; these are promising but immature for function calling.

### 3.2 Tool use and function calling for small models

#### Fine-tuned small models

| Model family | Size | Purpose |
|--------------|------|---------|
| **xLAM-2-fc-r** | 1 B / 3 B / 8 B | Salesforce Large Action Models; top of BFCL v3 leaderboard; strong multi-turn function calling [[xLAM repo](https://github.com/SalesforceAIResearch/xlam)]. |
| **ToolACE-2-8B** | 8 B | Strong single- and multi-turn tool use; competitive with larger models [[ToolACE paper](https://arxiv.org/html/2409.00920v2)]. |
| **Hammer-2.1** | 1.5 B / 3 B / 7 B | Function-masking tuned, good generalization across benchmarks. |
| **watt-tool-8B** | 8 B | Specialized tool-calling model. |
| **Octopus v2** | 2 B | On-device function calling with functional tokens; claimed >95 % accuracy on device APIs [[Octopus v2 paper](https://arxiv.org/abs/2404.01744)]. |
| **TinyAgent** | small | Edge function calling with LoRA, RAG-based ICL, DAG planning [[TinyAgent paper](https://arxiv.org/abs/2409.00608)]. |
| **Gorilla / Gorilla-V2** | 7 B | API-grounded tool use with retrieval. |

> **Key insight:** fine-tuning a 2–3 B model for a narrow tool space can outperform a general 8 B model. Juniper (Gemma-2-2B fine-tuned for function calling) beat Llama-3.1-8B on an internal benchmark and on BFCL simple/multiple tasks [[Juniper blog](https://www.ridgerun.ai/post/introducing-juniper-fine-tuned-small-local-model-for-function-calling)].

#### Constrained decoding / structured outputs

- **XGrammar-2** (used by vLLM and SGLang) enforces dynamic tool-calling grammars. On BFCL, XGrammar-2 raises Llama-3.2-3B correct-call rate from 33 % to 77.75 % and schema validity to 100 % [[XGrammar-2 paper](https://arxiv.org/html/2601.04426v3)].
- **Ollama** supports JSON schema structured outputs via GBNF grammars since v0.5 [[Ollama docs](https://docs.ollama.com/capabilities/structured-outputs)].
- **LM Studio** uses llama.cpp grammar support and can run speculative decoding.
- For CRP Comply, constrained decoding should be **mandatory for tool calls on SLMs**.

#### Dynamic / retrieved tool selection

- **Less-is-More** uses a small embedding model to retrieve only relevant tools instead of injecting the full tool set; works without fine-tuning the LLM [[Less-is-More paper](https://arxiv.org/html/2411.15399v1)].
- **TinyAgent** uses a transformer-based classifier for tool selection.
- **RAG-based tool search** (e.g. Gorilla, ToolLLM) retrieves relevant APIs from a large catalog.

> **Implication:** CRP Comply should not send all 13 tools to an 8 B model. It should select a small subset (≤ 5) conditioned on the user intent.

#### Fine-tuning recipes

- LoRA / QLoRA on 1 K–100 K task-specific examples is the dominant pattern for SLM agents [[Small Language Models for Agentic AI, 2026](https://futureagi.com/blog/small-language-models-agentic-ai-2025/)].
- Unsloth and HuggingFace PEFT are the standard toolchains; QLoRA lets a 7 B model fit on a 24 GB consumer GPU.
- Synthetic trajectory generation (Explorer → Actor → Tracker) can create training data for tool-use fine-tuning at low cost [[PaperGuide, 2025](https://arxiv.org/html/2601.12988v1)].

### 3.3 Routing, cascading, and hybrid SLM/LLM execution

- **FrugalGPT** queries a cheap model first and escalates to expensive models only if quality is insufficient [[Chen et al., 2024](https://arxiv.org/abs/2401.07878)].
- **HybridLLM** trains a difficulty classifier to route between small and large models.
- **RouteLLM**, **RouterDC**, **GraphRouter**, **BEST-Route**, **MasRouter** learn query-model compatibility embeddings or confidence scores to route in one shot.
- **Cascade routing** dynamically selects the next model at each step, balancing cost and quality [[Dynamic Model Routing survey, 2026](https://arxiv.org/html/2603.04445v2)].
- **Token-level routing** (e.g. R2R, CITER) sends only critical tokens to the large model.

> **Implication:** CRP Gateway should support a **capability router** that can run an SLM locally, evaluate confidence/quality, and escalate to a frontier model when the query or intermediate result exceeds the local model’s tier.

### 3.4 Context management and RAG

- **RAG remains the most practical way to give an SLM access to large corpora.** Agentic RAG systems (SelfRAG, FLARE, SPD-RAG) interleave retrieval and generation; SPD-RAG reaches 85 % of full-context quality at 38 % of the cost on a 250 K-token benchmark [[SPD-RAG, 2026](https://arxiv.org/pdf/2603.08329)].
- **Prompt compression** (LLMLingua, LongLLMLingua, LLMLingua-2, SelectiveContext) can shrink prompts by 2–20×, but compression overhead can dominate if not matched to hardware; lossy compression also hurts auditability.
- **Context distillation / memory tokens** (Gist tokens, RMT, ICAE, 500×Compressor) compress context into latent tokens but require training or fine-tuning.
- **CRP already has chunking primitives**: continuation, CSO, CDR, CDGR. These should be used explicitly instead of expecting the model to read a giant prompt.

### 3.5 Multi-agent decomposition

- Decompose compliance tasks into specialized agents: **intent router**, **retriever**, **extractor**, **reasoner**, **verifier**.
- Each agent can run the smallest model that reliably handles its sub-task; only the reasoner/verifier needs a larger model [[Small Language Models for Agentic AI, 2026](https://futureagi.com/blog/small-language-models-agentic-ai-2025/)].
- CRP Comply can use the CRP protocol to pass **CSO state** between agents instead of concatenating all history into one prompt.

---

## 4. Proposed CRP Comply SLM Execution Paths

### 4.1 Capability tiers

Introduce a `model_tier` field in the worker/SDK/config layer:

| Tier | Typical models | Loop style |
|------|----------------|------------|
| `FRONTIER` | Claude 3.5/4, GPT-4o/o3, DeepSeek-V3 | Full ReAct + reflection + all tools |
| `LOCAL_CAPABLE` | Qwen2.5-14B, xLAM-2-8B, ToolACE-8B, Llama-3.1-8B with grammar | Reduced ReAct; retrieved tool subset; optional verifier |
| `LOCAL_SMALL` | Qwen2.5-3B/7B, Llama-3.2-3B, Phi-4-mini, xLAM-1B/3B | Single-shot or planner-actor; ≤ 5 tools; constrained decoding; heavy CRP chunking |

The worker should advertise its tier via the existing health/status frame, and the backend should select a runtime path accordingly.

### 4.2 `LOCAL_SMALL` path (the primary 8 B target)

For models that fit the prompt but cannot reliably run the full loop:

1. **Pre-select evidence with CRP CDR/CDGR** before invoking the model. The model receives only the retrieved facts, not the full corpus.
2. **Select a dynamic tool subset** (≤ 5 tools) using an embedding retriever over tool descriptions conditioned on the user query.
3. **Shorten the system prompt** for weak models; remove reflection instructions and keep only the task + safety guardrails.
4. **Use constrained decoding** for all tool calls. Prefer servers that expose JSON schema / grammar (vLLM, SGLang, Ollama, llama.cpp). LM Studio support depends on its grammar pipeline.
5. **Prefer single-shot retrieval → answer** when the task is answerable from retrieved facts. Avoid multi-turn ReAct.
6. **If a loop is required**, enforce:
   - max identical calls = 2,
   - max wall-clock time per turn,
   - forced final-answer fallback,
   - no streaming tool-call parsing (wait for full JSON).
7. **Keep the system prompt + tool subset static** so prefix caching can skip repeated prefill.
8. **Use 8-bit quantization** when VRAM allows; otherwise evaluate Q4_K_M/AWQ on compliance-specific benchmarks before deployment.
9. **Chunk long documents via CRP continuation/CSO** instead of increasing context length.

### 4.3 `LOCAL_CAPABLE` path

- Use the full tool set only when the query is complex.
- Enable a **lightweight planner-actor** loop (plan once, execute tools, synthesize).
- Add a **verifier step** using a slightly larger local model or the same model with a different prompt.
- Use constrained decoding for all structured outputs.

### 4.4 `FRONTIER` path

- Keep the existing loop as the quality baseline.
- Use SLM-generated drafts only as an optional latency optimization, not as the primary reasoning path for high-risk compliance answers.

### 4.5 CRP protocol integration points

- **Capability advertisement:** extend the worker health frame with `model_tier`, `supports_structured_output`, `quantization`, `context_window`, and `effective_context_per_slot`.
- **Session token:** carry the selected tool-subset hash and model tier so that downstream CRP components can reason about provenance and replay conditions.
- **Continuation / CSO:** use CRP continuation to split long regulation texts into chunks processed by the SLM; the CSO carries forward still-valid facts, avoiding the need to keep the whole text in context.
- **Gateway routing:** CRP Gateway can route simple queries to a local SLM and escalate complex ones to a frontier model, using the same CRP header contract.
- **Safety control plane:** safety rules (halt, oversight, audit) run **above** the model layer and apply identically across tiers.

### 4.6 Deployment architecture options

| Option | Pattern | Best for |
|--------|---------|----------|
| **A. SLM-only edge** | Local model handles scoped Q&A; no cloud calls. | Air-gapped, low-risk, simple queries. |
| **B. Hybrid edge-cloud** | SLM fast-path; CRP Gateway escalates uncertain/complex queries to frontier models. | Balanced cost, latency, and quality. |
| **C. SLM router + frontier worker** | Small model classifies intent and drafts tool calls; frontier model verifies/executes. | When local model can plan but not reliably execute. |

---

## 5. Implementation Roadmap

### Short term (1–2 weeks)

- [ ] Detect and advertise `model_tier` from worker health data.
- [ ] Implement **dynamic tool selection** in the Comply agent: embed tool descriptions and retrieve top-K per query.
- [ ] Add **constrained decoding wrapper** that translates tool schemas to JSON schema / grammar when the upstream server supports it.
- [ ] Harden loop guards: duplicate-call detection, per-turn timeout, final-answer fallback.
- [ ] Frontend: extend SSE timeout and render `llm_progress` heartbeats (already in 0.1.2 backend; needs deploy).
- [ ] Document recommended local server settings (context length, quantization, grammar).

### Medium term (2–6 weeks)

- [ ] Add first-class support for a fine-tuned tool model such as **xLAM-2-8B** or **ToolACE-8B** as a `LOCAL_CAPABLE` default.
- [ ] Build a **CRP Gateway routing module** for hybrid edge-cloud execution.
- [ ] Implement **prompt-caching hints**: keep system prompt + selected tools at the start of every message list; avoid reordering evidence.
- [ ] Create a **local-model benchmark harness** using the compliance Q&A corpus; measure accuracy, latency, and token budget by tier.
- [ ] Evaluate **8-bit vs 4-bit** quantization on compliance-specific reasoning tasks (not just perplexity).

### Long term (6+ weeks)

- [ ] Fine-tune a small CRP Comply specialist model with LoRA/QLoRA on synthetic compliance trajectories.
- [ ] Evaluate **hybrid attention / state-space models** (Mamba, RWKV-X, Jamba) for long-context retrieval-only tasks.
- [ ] Integrate **advanced KV-cache management** (LMCache, sparse KV eviction) behind a CRP storage backend.
- [ ] Contribute a CRP-level **capability router** spec so other CRP products (Gateway, Scan) can reuse the same tier model.

---

## 6. Risks and Open Questions

1. **Quantization and compliance reasoning:** 4-bit models may pass JSON-format tests while failing subtle regulatory reasoning. Compliance tasks need their own quantization benchmark.
2. **Constrained decoding availability:** Not all local servers expose JSON-schema grammars cleanly. The SDK may need per-server adapters (vLLM, SGLang, Ollama, LM Studio, llama.cpp).
3. **Tool fine-tuning cost:** Curating verifiable compliance tool-use trajectories is non-trivial; synthetic generation must be validated against real regulation text.
4. **Mamba/RWKV maturity:** These architectures are not yet reliable for function calling; keep them research-only.
5. **User expectations:** An SLM path will be slower and less capable than the frontier path. The UI must communicate tier limitations and provide escalation affordances.

---

## 7. References

### Tool use / function calling for small models

- Docker, *Local LLM Tool Calling: A Practical Evaluation*, 2025 — https://www.docker.com/blog/local-llm-tool-calling-a-practical-evaluation/
- Salesforce AI Research, *xLAM: Large Action Models*, 2024–2025 — https://github.com/SalesforceAIResearch/xlam
- Liu et al., *ToolACE: Winning the Points of LLM Function Calling*, 2024 — https://arxiv.org/html/2409.00920v2
- Chen & Li, *Octopus v2: On-Device Language Model for Super Agent*, 2024 — https://arxiv.org/abs/2404.01744
- Erdogan et al., *TinyAgent: Function Calling at the Edge*, 2024 — https://arxiv.org/abs/2409.00608
- RidgeRun, *Juniper: Fine-Tuned Small Local Model for Function Calling*, 2025 — https://www.ridgerun.ai/post/introducing-juniper-fine-tuned-small-local-model-for-function-calling
- Qin et al., *ToolLLM: Facilitating Large Language Models to Master 16000+ APIs*, 2024 — https://arxiv.org/abs/2307.16778

### Constrained decoding / structured outputs

- Dong et al., *XGrammar: Flexible and Efficient Structured Generation* — https://arxiv.org/html/2411.15100v3
- *XGrammar-2: Efficient Dynamic Structured Generation Engine for Agentic LLMs*, 2025 — https://arxiv.org/html/2601.04426v3
- Ollama, *Structured Outputs* — https://docs.ollama.com/capabilities/structured-outputs
- Daniel Clayton, *How Does Ollama’s Structured Outputs Work?*, 2024 — https://blog.danielclayton.co.uk/posts/ollama-structured-outputs/
- Willard & Louf, *Outlines*, 2023 — https://github.com/dottxt-ai/outlines

### Routing, cascading, SLM/LLM collaboration

- Chen et al., *FrugalGPT*, 2024 — https://arxiv.org/abs/2401.07878
- Ong et al., *RouteLLM*, 2025 — https://arxiv.org/abs/2406.18665
- Ding et al., *HybridLLM*, 2024 — https://arxiv.org/abs/2404.12732
- *Dynamic Model Routing and Cascading for Efficient LLM Inference: A Survey*, 2026 — https://arxiv.org/html/2603.04445v2
- *A Survey on Collaborating Small and Large Language Models*, 2025 — https://arxiv.org/html/2510.13890v2

### Efficient inference, KV cache, and long context

- Xiao et al., *StreamingLLM*, 2024 — https://arxiv.org/abs/2309.17453
- Zhang et al., *H2O: Heavy-Hitter Oracle*, 2023 — https://arxiv.org/abs/2306.14048
- Xiao et al., *DuoAttention*, 2025 — https://arxiv.org/abs/2410.10819
- Chen et al., *LongLoRA*, ICLR 2024 — https://proceedings.iclr.cc/paper_files/paper/2024/file/211ab571cc9f3802afa6ffff52ae3e5b-Paper-Conference.pdf
- *Extending LLM Context Window Beyond 2 Million Tokens* — https://raw.githubusercontent.com/mlresearch/v235/main/assets/ding24i/ding24i.pdf
- *Mamba / RWKV / State-Space Models survey*, 2025 — https://blog.gopenai.com/deep-dive-into-mamba-rwkv-and-state-space-models-b45d5e6a38c9
- LMCache docs — https://docs.lmcache.ai/
- vLLM automatic prefix caching discussion — https://blog.squeezebits.com/vllm-vs-tensorrtllm-12-automatic-prefix-caching-38189
- llama.cpp KV-cache reuse tutorial — https://github.com/ggml-org/llama.cpp/discussions/13606

### Speculative decoding

- Leviathan et al., *Fast Inference from Transformers via Speculative Decoding*, 2023 — https://arxiv.org/abs/2211.17192
- LM Studio, *Speculative Decoding*, 2025 — https://lmstudio.ai/blog/lmstudio-v0.3.10
- *Agent-X: Full Pipeline Acceleration of On-device AI Agents*, 2026 — https://arxiv.org/html/2605.10380v1

### Quantization and agentic accuracy

- Mekala et al., *Does Quantization Affect Models’ Performance on Long-Context Tasks?*, EMNLP 2025 — https://aclanthology.org/2025.emnlp-main.479.pdf
- *Quantized Prefilling, Precise Decoding for Agentic LLMs*, 2026 — https://arxiv.org/html/2605.20315v1
- *Can Compressed LLMs Truly Act? An Empirical Evaluation of Agentic Capabilities in LLM Compression* (ACBench), ICML 2025 — https://icml.cc/virtual/2025/poster/43871

### RAG, context compression, and agentic decomposition

- Asai et al., *Self-RAG*, 2023 — https://arxiv.org/abs/2310.11511
- Jiang et al., *FLARE*, 2023 — https://arxiv.org/abs/2305.06983
- *SPD-RAG: Recursive Synthesis over Long Documents*, 2026 — https://arxiv.org/pdf/2603.08329
- Jiang et al., *LLMLingua*, 2023 — https://arxiv.org/abs/2310.05736
- Pan et al., *LLMLingua-2*, 2024 — https://arxiv.org/abs/2403.12968
- Mu et al., *Gist Tokens*, 2024 — https://arxiv.org/abs/2404.01704
- *Small Language Models for Agentic AI*, 2026 — https://futureagi.com/blog/small-language-models-agentic-ai-2025/

### CRP/CRP Comply internal

- `LOCAL_8B_MODEL_ANALYSIS.md` in this repo.
- CRP v4 specs in `context-relay-protocol/SPECS_5_06_2026_CRP_v4/`.

---

*Last updated: 2026-06-26*
