# Local LLM Guide — full privacy, unlimited context, zero cost

> **Why this guide exists.** crp‑comply is fully usable with **no
> hosted LLM at all**. Once you install a small model locally, every
> recipe, agent turn, contradiction check and Annex IV draft runs on
> your own machine — and CRP makes a 7B local model produce work that
> looks like a frontier model.

This guide walks through three install paths in order of effort —
**LM Studio (easiest GUI)**, **Ollama (one‑line CLI)**, and
**llama.cpp (rawest, smallest footprint)** — and shows how to plug
each into crp‑comply.

If you just want it to *work*, skip to [§4 One‑command bootstrap](#4-oneminuscommand-bootstrap-recommended).

---

## 1. Why local

| Advantage                          | Why it's true with CRP                                                                            |
| ---------------------------------- | ------------------------------------------------------------------------------------------------- |
| **Full privacy**                   | Prompts and outputs never leave the device. No SaaS log can ever contain your client's data.     |
| **Effectively unlimited context**  | CRP's envelope packer keeps the prompt small (4–8 k tokens for local) and **continuation** loops produce arbitrarily long output. Benchmark: **11.8× content multiplier** over 9 windows. |
| **Effectively unlimited generation** | Same — there is no API call cap. A 30‑page Annex IV is just more continuation windows.         |
| **Lower cost**                     | $0 marginal cost per call after one‑off install. The whole AUD $200/mo hosted budget collapses to electricity. |
| **No vendor risk**                 | Not affected by Groq / OpenAI / Anthropic pricing or outages.                                     |
| **Air‑gappable**                   | Works fully offline. Compliance bonus for special‑category data and EU AI Act high‑risk systems. |

CRP's six‑stage extraction (regex → statistical → GLiNER → UIE →
discourse → optional LLM) means **the local model is only used for
the bits it is good at** — drafting prose, comparing two facts,
writing JSON. Information extraction is done by smaller specialised
NLP models that run on CPU.

---

## 2. Hardware requirements

Pick the smallest model that fits comfortably in your free RAM and
leaves ~4 GB for the OS.

| Available RAM (free) | Quantised model                            | Disk  | Speed (M2/M3, CPU) | Use it for                               |
| -------------------- | ------------------------------------------ | ----- | ------------------ | ---------------------------------------- |
| < 8 GB               | `qwen2.5:3b-instruct-q4_K_M`               | 2 GB  | 30–40 tok/s        | Extraction + clarification only          |
| 8 GB – 16 GB         | `llama3.1:8b-instruct-q4_K_M` *(default)*  | 5 GB  | 15–25 tok/s        | Free / Starter sweet spot                |
| 16 GB – 32 GB        | `qwen2.5:14b-instruct-q4_K_M`              | 9 GB  | 10–18 tok/s        | Replaces hosted Scout 17B                |
| 32 GB – 64 GB        | `qwen2.5:32b-instruct-q4_K_M`              | 20 GB | 6–12 tok/s         | Replaces hosted Llama‑70B for drafting   |
| 64 GB+ or 24 GB GPU  | `llama3.3:70b-instruct-q4_K_M`             | 42 GB | 8–20 tok/s on GPU  | Drop‑in for hosted default               |

> **Apple Silicon note.** M‑series macs use unified memory: a 16 GB
> M2 happily runs 8B models, and a 36 GB M3 Pro happily runs 32B.
> Throughput is much better than the equivalent x86 CPU.
>
> **NVIDIA GPU note.** Any 8 GB+ consumer card via llama.cpp or
> Ollama will be 5–10× faster than CPU. 24 GB cards (3090, 4090)
> happily run 70B q4.

---

## 3. CRP optimisations for local mode (already wired)

When crp‑comply detects a local provider, the orchestrator
**automatically** switches to a local‑optimised CRP preset:

| CRP component                  | Hosted preset           | Local preset                 | Why                                        |
| ------------------------------ | ----------------------- | ---------------------------- | ------------------------------------------ |
| `EnvelopeBuilder` budget       | 32 k tokens             | 4 k–8 k tokens               | Small models prefer short windows          |
| `ContinuationManager` reground cadence | every 5 windows | **every 3 windows** | Re‑inject facts more often → less drift on small models. **Does NOT cap window count** — total length is task-driven. |
| Reranker idle‑unload           | 10 windows              | **4 windows**                | Free VRAM for the LLM                      |
| `LLMExtractor` (stage 6)       | enabled                 | **disabled**                 | Stages 1–5 already cover ~95%             |
| CKF mode default               | `semantic`              | `graph_walk + pattern_query` | No GPU embeddings needed                   |
| Reranker model                 | `bge-reranker-large`    | `bge-reranker-base`          | 3× faster, ~equivalent on short candidates |

You don't need to set any of these. They flip when
`CRP_COMPLY_PROVIDER` resolves to `ollama`, `lmstudio`, `llamacpp`
or `local`.

---

## 4. One‑command bootstrap *(recommended)*

The script detects your OS, RAM and GPU, picks the right model from
the table in §2, installs the right runtime, pulls the model, and
writes the config crp‑comply needs.

### 4.1 macOS / Linux

```bash
curl -fsSL https://comply.crprotocol.io/install-local-llm.sh | sh
```

Or run it from this repo:

```bash
sh scripts/install_local_llm.sh
```

### 4.2 Windows (PowerShell, run as user, not admin)

```powershell
iwr -useb https://comply.crprotocol.io/install-local-llm.ps1 | iex
```

Or from this repo:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_local_llm.ps1
```

### 4.3 What the script does

1. Detects platform (macOS / Linux / Windows), CPU arch, free RAM,
   GPU presence.
2. Picks the correct model tier from §2.
3. Installs **Ollama** (the easiest cross‑platform option). On macOS
   uses Homebrew; on Linux uses the official one‑line install; on
   Windows downloads the MSI.
4. `ollama pull <model>` and starts the daemon on
   `http://127.0.0.1:11434` as a background service.
5. Writes `~/.crp-comply/local-llm.json`:
   ```json
   {
     "provider": "ollama",
     "base_url": "http://127.0.0.1:11434",
     "model": "llama3.1:8b-instruct-q4_K_M",
     "context_window": 8192,
     "installed_at": "2026-05-01T10:14:00Z"
   }
   ```
6. Smoke‑tests with a one‑line prompt to confirm the daemon is up.

After it finishes, restart `crp-comply` (or just refresh the
**Settings → AI provider** page) and the **Local** card flips green.

---

## 5. Path A — LM Studio *(easiest GUI)*

Best for non‑technical users on a laptop.

1. Download from <https://lmstudio.ai/>, open the installer, drag
   to Applications / accept the Windows installer.
2. Open LM Studio → **Discover** → search `Llama 3.1 8B Instruct
   Q4_K_M` → click *Download*.
3. Switch to the **Developer** tab → enable **Start Server** →
   confirm port `1234`.
4. Tell crp‑comply where it is:

   ```bash
   export CRP_COMPLY_PROVIDER=lmstudio
   export LMSTUDIO_BASE_URL=http://127.0.0.1:1234/v1
   export LMSTUDIO_MODEL="llama-3.1-8b-instruct"
   ```

   On Windows in the GUI: **Settings → AI provider → Local** →
   *I already have LM Studio running* → fill in the URL and model.

LM Studio exposes an OpenAI‑compatible REST API, so it slots into the
same `OpenAIAdapter` we already ship.

---

## 6. Path B — Ollama *(best CLI, what the bootstrap uses)*

```bash
# macOS
brew install ollama

# Linux
curl -fsSL https://ollama.com/install.sh | sh

# Windows
winget install Ollama.Ollama
```

Pull a model and start the daemon (the daemon starts automatically
on macOS/Windows; on Linux run `ollama serve`):

```bash
ollama pull llama3.1:8b-instruct-q4_K_M
ollama run  llama3.1:8b-instruct-q4_K_M  # one-shot smoke test, then ctrl-D
```

Tell crp‑comply:

```bash
export CRP_COMPLY_PROVIDER=ollama
export OLLAMA_BASE_URL=http://127.0.0.1:11434
export OLLAMA_MODEL=llama3.1:8b-instruct-q4_K_M
```

> **Context window note.** Ollama defaults to 4 k. CRP can ask it
> for 32 k–128 k by setting `num_ctx` per request — already wired
> in `OllamaAdapter`. There is no Ollama‑side config to change.

---

## 7. Path C — llama.cpp *(power users, smallest footprint)*

```bash
# macOS / Linux
brew install llama.cpp        # mac
sudo apt install llama-cpp    # Ubuntu 24.04+
# Or build from source: https://github.com/ggerganov/llama.cpp
```

Download a GGUF quant (e.g. from Hugging Face
`bartowski/Llama-3.1-8B-Instruct-GGUF`):

```bash
curl -L -o llama-3.1-8b.gguf \
  https://huggingface.co/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF/resolve/main/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf
```

Start the OpenAI‑compatible server:

```bash
llama-server -m ./llama-3.1-8b.gguf -c 8192 --port 8080 --host 127.0.0.1
```

Tell crp‑comply:

```bash
export CRP_COMPLY_PROVIDER=llamacpp
export LLAMACPP_SERVER_URL=http://127.0.0.1:8080
export LLAMACPP_MODEL="llama-3.1-8b-instruct"
```

`LlamaCppAdapter` (already in CRP) speaks the OpenAI‑compatible
endpoint that `llama-server` exposes; no extra plumbing needed.

---

## 8. Verifying everything works

```bash
# Quick provider smoke test
crp-comply llm-probe

# Should print: provider=ollama  model=llama3.1:8b...  ok=true  rt_ms=...
```

Then run a recipe end‑to‑end:

```bash
crp-comply run-recipe annex_iv_technical_file --tenant demo --local
```

Watch the **Settings → Token & cost** panel: it should report
`provider=local cost=$0.00` for every call.

---

## 9. Troubleshooting

| Symptom                                              | Likely cause                            | Fix                                                  |
| ---------------------------------------------------- | --------------------------------------- | ---------------------------------------------------- |
| `Connection refused 127.0.0.1:11434`                 | Ollama daemon not running                | `ollama serve` (Linux) or restart the app (macOS/Win) |
| Output truncates after ~500 tokens                   | Server enforced its own max_tokens       | Pass higher `max_tokens` in env or use CRP continuation (it already does) |
| Throughput < 5 tok/s                                 | Model too big for RAM, swapping         | Drop one model size; check Activity Monitor / `htop` |
| Random JSON parse errors                             | Model not following format strictly      | CRP retries once; persistent failure → drop to a 14B+ model for that task |
| GPU not used                                         | Ollama compiled CPU‑only                | Reinstall via Homebrew/winget; or use llama.cpp built with `-DGGML_CUDA=on` |
| `model not found` after install                      | Pull never finished                     | `ollama list` to check; re‑run `ollama pull <model>` |

---

## 10. When local is *not* the right choice

* **Spiky workloads** — many users hit run‑recipe at the same minute.
  Local hardware will queue; Groq scales horizontally.
* **Sub‑second response demands** — chat UX where you want streaming
  tokens at 100+ tok/s. Groq is the only economical option here.
* **No willing local hardware** — < 8 GB free RAM, no GPU, no patience
  for ~15 tok/s. Use Hosted (Groq) or BYOK.

In any of those cases, leave `CRP_COMPLY_PROVIDER` unset and the app
falls back to Hosted (Groq) within the AUD $200 / month cap (see
[BUDGET_LLM_GUIDANCE.md](BUDGET_LLM_GUIDANCE.md)).

---

## 11. Related documents

* [BUDGET_LLM_GUIDANCE.md](BUDGET_LLM_GUIDANCE.md) — full economics
  & Groq routing matrix.
* [BYOK_MODES.md](BYOK_MODES.md) — bring‑your‑own OpenAI / Anthropic
  / Groq key.
* [LLM_HOSTING.md](LLM_HOSTING.md) — self‑hosted GPU box for
  Enterprise air‑gap.
