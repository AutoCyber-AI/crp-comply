# BYOK — Bring Your Own LLM (Modes, Setup, Security)

**Status:** Canonical customer-facing docs for all three BYOK integration modes.
**Audience:** Customers evaluating or using CRP Comply, especially those running local LLMs (LM Studio, Ollama) or their own OpenAI/Anthropic keys.
**Last updated:** 2026-04-23

> **TL;DR** — Our compliance agent needs an LLM. You can either (a) paste your LLM provider key into Settings, (b) expose your local LLM through a free tunnel, or (c) run a single command from our open-source SDK. **No CRP Comply code ever runs on your machine unless you explicitly choose Mode C, and even that code is 100% public on PyPI.**

---

## Table of contents

1. [Why BYOK exists](#why-byok-exists)
2. [Which mode should I use?](#which-mode-should-i-use)
3. [Mode A — Cloud LLM API keys (easiest)](#mode-a--cloud-llm-api-keys)
4. [Mode B — Local LLM via reverse tunnel (LM Studio, Ollama)](#mode-b--local-llm-via-reverse-tunnel)
5. [Mode C — Local LLM via our open-source worker (one command)](#mode-c--local-llm-via-our-open-source-worker)
6. [What CRP Comply sends / stores / never sees](#what-we-send-store-never-see)
7. [Security model](#security-model)
8. [Troubleshooting](#troubleshooting)
9. [FAQ](#faq)

---

## Why BYOK exists

Most compliance tools force you onto *their* LLM. That creates three problems:

1. **Data residency.** Your prompts and responses may contain customer PII, proprietary source code, or regulated health/financial data. Sending that to a US-based LLM can be illegal or contractually forbidden.
2. **Cost control.** Compliance reports can be generation-heavy. If you already pay for an OpenAI enterprise plan with pre-negotiated rates, or you run Llama on your own GPUs at marginal cost, you don't want to pay our LLM markup on top.
3. **Sovereignty.** Some regulators (German BaFin, UK FCA, EU AI Office for high-risk systems) expect you to retain full control of inference.

BYOK means you pick the LLM. We supply the **intelligence layer** — the agent, the regulation corpus, the CKF fact graph, the signed evidence packs — and call your LLM exactly as the agent needs it.

---

## Which mode should I use?

| If you… | Use |
|---|---|
| Already have an OpenAI / Anthropic / Azure / Groq / Together key | **Mode A** |
| Want to run LM Studio / Ollama on your laptop and have 2 minutes to spare | **Mode B** (Cloudflare Tunnel) |
| Want to run LM Studio / Ollama but don't want to set up any tunnels | **Mode C** (our pip worker — one command) |
| Want to run your LLM in your VPC / air-gapped / on-prem | **Mode B** (internal ingress) or **Mode C** (outbound WebSocket only) |
| Are on the Free tier | — (Free is rule-based only; BYOK not required) |
| Are on Pro tier and don't want to manage any of this | Use our hosted Groq + Claude, no BYOK |

---

## Mode A — Cloud LLM API keys

**1 minute setup.** Works for OpenAI, Anthropic, Azure OpenAI, Groq, Together.ai, Fireworks, and any OpenAI-compatible API.

### Setup

1. Sign in → **Settings → LLM Provider**
2. Pick your provider from the 5-tile grid (OpenAI, Anthropic, Azure, Groq, Together, Custom)
3. Paste your API key. For Azure, also paste the endpoint URL + deployment name.
4. Click **Test connection** — we call the provider's `/models` endpoint (or equivalent) to verify.
5. Save.

### What happens under the hood

- Your key is encrypted at rest using libsodium secretbox, with the encryption key derived from our server's `CRP_COMPLY_JWT_SECRET` environment variable.
- Keys are **never** logged, **never** displayed in plaintext after save, **never** included in support responses.
- When the agent needs an LLM call, our server decrypts the key in memory, makes an outbound HTTPS call to your provider, and discards the key from memory after the call completes.
- You can rotate the key any time: Settings → LLM Provider → Edit → Paste new key → Save.

### Which provider to pick

| Provider | Best for | Typical cost/report |
|---|---|---|
| **Groq (Llama 3.3 70B)** | Speed + cost | $0.003 |
| **OpenAI (gpt-4o-mini)** | Reliability + extraction | $0.005 |
| **OpenAI (gpt-4o)** | Highest quality | $0.08 |
| **Anthropic (Claude Haiku 3.5)** | Long narrative reports | $0.03 |
| **Anthropic (Claude Sonnet 3.5)** | Max quality | $0.12 |
| **Azure OpenAI** | Enterprise data residency / SOC 2 flow-through | same as OpenAI |
| **Together.ai** | Open-weights models with data deletion guarantees | $0.004 |

### Revocation

- Remove the key from Settings to stop all outbound calls immediately.
- Revoke the key at your provider's dashboard as a second layer (recommended for sensitive data).

---

## Mode B — Local LLM via reverse tunnel

Your LLM runs on your laptop (LM Studio, Ollama) or in your office (self-hosted vLLM). You expose the OpenAI-compatible endpoint over a free HTTPS tunnel. Our server calls that URL.

### Setup (Cloudflare Tunnel, recommended — free forever, no signup)

1. Install `cloudflared` once:
    - macOS: `brew install cloudflared`
    - Windows: `winget install --id Cloudflare.cloudflared`
    - Linux: `sudo apt install cloudflared` or the binary from https://github.com/cloudflare/cloudflared/releases
2. Start your local LLM (LM Studio → Developer → Local Server; or `ollama serve`)
3. Open a tunnel to it:
    ```
    cloudflared tunnel --url http://localhost:1234    # LM Studio
    cloudflared tunnel --url http://localhost:11434   # Ollama
    ```
4. Copy the HTTPS URL cloudflared prints (looks like `https://random-words.trycloudflare.com`).
5. In CRP Comply: **Settings → LLM Provider → LM Studio (via tunnel)** or **Ollama (via tunnel)**.
6. Paste the URL. Click **Test connection**. Save.

### Setup (Tailscale Funnel — free for personal)

1. Install Tailscale on the machine running the LLM.
2. Enable Funnel: `tailscale funnel 1234`
3. Use the `*.ts.net` URL shown.
4. Paste into Settings as above.

### Setup (ngrok — free tier, session-limited)

1. `ngrok http 1234`
2. Paste the `https://*.ngrok-free.app` URL into Settings.

### What our server sees

- Only the HTTPS URL you pasted.
- Standard OpenAI-compatible request payloads (model, messages, temperature, etc.).
- The responses your LLM generates.

### What we cannot see

- Your local machine's IP.
- Any other service on your laptop or network.
- Anything outside the single HTTPS endpoint you exposed.

### Keeping the tunnel up

- LM Studio + Cloudflare Tunnel works great for workstation-level compliance analysis.
- For production-scale, run `cloudflared` as a service (systemd on Linux, launchd on macOS, or Windows service via `nssm`). Tutorial linked in the docs sidebar.
- If the tunnel dies, our agent will get a connection error — the UI shows a retry button, nothing else breaks.

---

## Mode C — Local LLM via our open-source worker

For users who want local-LLM privacy but don't want to fiddle with tunnels. **One command and done.**

### Setup

1. Install our SDK (public on PyPI, source at https://github.com/crp-comply/crp-comply):
    ```
    pip install crp-comply-sdk
    ```
2. Run the worker:
    ```
    crp-comply worker --lmstudio http://localhost:1234 --api-key crp_...
    ```
    or
    ```
    crp-comply worker --ollama http://localhost:11434 --api-key crp_...
    ```
3. In CRP Comply: **Settings → LLM Provider → "Local via SDK worker"**. The status indicator turns green when your worker connects.
4. That's it — leave the worker running whenever you want the agent to work.

### What the worker does

Exactly one thing: opens a WebSocket to `wss://comply.crprotocol.io/api/v1/agent/worker` using your API key, and when the agent wants to run an LLM call, it:

1. Receives a JSON message: `{"request_id":"...","endpoint":"/v1/chat/completions","payload":{...}}`
2. Makes an HTTP call to your local LM Studio / Ollama endpoint.
3. Sends the response back: `{"request_id":"...","response":{...}}`

### Can I read the worker's source code?

Yes. It's ~100 lines of Python. Full source:

- On PyPI: https://pypi.org/project/crp-comply-sdk/
- On your machine after `pip install`: `site-packages/crp_comply_sdk/worker.py`
- Published under Apache-2.0

There is no hidden logic. No telemetry. No fetching of dynamic code. No sandboxing escapes. We designed it to be auditable in 15 minutes.

### What the worker does NOT do

- It does **not** execute anything our server sends other than HTTP calls to the local URL you specified.
- It does **not** read files, open network connections other than the WebSocket + the local LLM URL, or persist anything.
- It does **not** update itself — you control updates via `pip install --upgrade crp-comply-sdk`.
- It does **not** include our agent logic, prompts, or regulation corpus — those stay on our server.

### Why would I pick this over Mode B?

- No tunnel setup (no Cloudflare / Tailscale / ngrok account)
- Worker auto-reconnects on network blips
- Works through strict corporate firewalls that allow outbound HTTPS but block incoming tunnels
- Clean shutdown — just Ctrl+C the worker

### Why would I NOT pick this?

- You want zero CRP Comply code on your machine (then use Mode B)
- Your security team won't allow any third-party pip packages (then use Mode B)

---

## What we send, store, never see

### What we send to your LLM (every mode)

- System prompt (the agent's instructions — these are our IP, but they show up in your provider's logs)
- Retrieved regulation chunks (small, relevant snippets of public regulation text)
- Your free-text system descriptions (your IP)
- Facts the agent extracted from prior conversation (your data)
- Tool-call JSON schemas (our IP)
- The LLM's own prior messages in the conversation

### What we store on Railway (in all modes)

- Your API key (encrypted, per tier)
- The full agent conversation trace + LLM input/output (encrypted at rest, retained per your SOW / tier defaults)
- Generated reports + evidence packs
- Usage counters (for billing)

### What we never see

- Your cloud LLM provider account or usage outside of the calls the agent makes
- Anything on your local machine other than responses from the LLM URL you specified
- Your LLM provider key after decryption (held in memory for the call, discarded)
- Other services on your network (Mode B/C tunnels scope to one port)

---

## Security model

| Concern | Mitigation |
|---|---|
| Our server is compromised | Your encrypted key decryption requires both our runtime access and `CRP_COMPLY_JWT_SECRET`; compromise of the volume alone does not yield keys |
| Key leakage in logs | All logs pass a redaction filter that matches provider key formats (`<YOUR_API_KEY>`, `crp-...`, JWTs) |
| Replay of old requests | Every agent call uses a unique request_id; provider rate-limits catch replay anyway |
| Injection via user input → LLM | Tools-only emission — the LLM cannot produce a final classification without a deterministic tool call; system prompt explicitly treats user input as data, not instructions |
| Supply chain attack via SDK worker | Only source-available, published to PyPI with sigstore attestations; recommend you pin `crp-comply-sdk==X.Y.Z` |
| Tunnel exposes other services | Cloudflare Tunnel scopes to a single port; we cannot reach anything else |
| Agent exfiltrates data through LLM | All outbound agent → LLM traffic is logged in the evidence pack; regulator can audit |

### What you should do

- Rotate BYOK keys at least quarterly
- Use provider-level budget alerts (OpenAI, Anthropic, Groq all support them) — limits blast radius if a key leaks
- For Mode C, pin the SDK version in CI (`crp-comply-sdk==0.2.0`) and update deliberately
- Enable MFA on CRP Comply and on your LLM provider
- For regulated data, prefer Mode B (no third-party code on your side) or Mode A with Azure OpenAI / Enterprise Anthropic (data non-retention guarantees)

---

## Troubleshooting

### Mode A — "Invalid API key"

- Verify the key still works by calling your provider's `/models` endpoint directly with `curl`
- Check for trailing whitespace on paste
- Groq keys start with `gsk_`; OpenAI with `sk-`; Anthropic with `sk-ant-`
- Azure requires endpoint URL + deployment name, not just the key

### Mode B — "Tunnel not reachable"

- Visit the tunnel URL + `/v1/models` in your browser — should return JSON
- Check cloudflared is still running (Quick Tunnels time out after 24h — run as a service for production)
- Firewall / corporate VPN can block tunnel bootstrap — try from a personal network first

### Mode C — "Worker won't connect"

- Check your API key is correct (`crp-comply status` will verify)
- Verify outbound HTTPS + WebSocket (wss://) access to `comply.crprotocol.io`
- Check local LLM is actually running: `curl http://localhost:1234/v1/models`
- Update SDK: `pip install --upgrade crp-comply-sdk`

### The agent is very slow

- Local LLMs < 13B parameters often too weak for tool-calling — try ≥ 70B (quantized is fine)
- Groq is 10× faster than OpenAI for most tasks — consider for Mode A
- Increase tunnel capacity (Cloudflare Tunnel default is plenty; ngrok free is rate-limited)

### The agent gives wrong article citations

- Article IDs come from our deterministic lookup, not the LLM — if they're wrong, report it; this is a bug in our corpus, not your LLM
- If narrative text around citations is wrong, your LLM may be too small; try a 70B+ model

---

## FAQ

**Q: Does the agent work without an LLM?**
A: The Free tier runs rule-based risk classification, PII scan, and injection detection — no LLM. For actual narrative reports, DPIA, transparency declarations, you need an LLM (BYOK or our hosted).

**Q: Can I use different LLMs for different reports?**
A: Yes. Settings stores multiple providers; per-report you can choose which to use.

**Q: Can I use a fine-tuned model I hosted myself?**
A: Yes — if it exposes an OpenAI-compatible API, use Mode B. Point the tunnel at your model's endpoint.

**Q: Does the agent work offline?**
A: The agent calls our server for tools, RAG, and CKF. Our server is a hosted service — so no, not fully offline. If you need fully offline, that's the Enterprise air-gapped deployment (§4c of [Enterprise Delivery Playbook](ENTERPRISE_DELIVERY_PLAYBOOK.md)).

**Q: How do I delete all my BYOK data?**
A: Settings → LLM Provider → Remove. That clears the encrypted key immediately. For complete data deletion see Settings → Account → Delete All My Data (retention is then enforced per your DPA).

**Q: What if my LLM provider has an outage?**
A: Mode A users can pre-configure a fallback provider — the agent will retry on a different provider after 3 failures. Mode B/C users get an error and can retry.

**Q: What's the rate limit?**
A: None on our end for BYOK; your LLM provider's limits apply. For our hosted LLM path, tier quotas apply.

**Q: Is BYOK available on Free?**
A: No. Free tier is rule-based only. BYOK starts at Starter ($49/mo).

---

## See also

- [Volume persistence & data control](./VOLUME_PERSISTENCE.md)
- [Enterprise Delivery Playbook](../ENTERPRISE_DELIVERY_PLAYBOOK.md)
- [LLM Intelligence Design](../LLM_INTELLIGENCE_DESIGN.md) — technical architecture
- [PyPI: crp-comply-sdk](https://pypi.org/project/crp-comply-sdk/)
- Public GitHub: source of the SDK worker
