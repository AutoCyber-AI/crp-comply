# LLM Hosting — Operator Setup Guide for Tiers 1–4

**Audience:** CRP Comply operators (you) deciding which LLM backends
to enable for each pricing tier, and how to provision them.

**Companion docs:**
- [BYOK_MODES.md](BYOK_MODES.md) — customer-facing BYOK explainer.
- [../STRIPE_MONETISATION.md](../STRIPE_MONETISATION.md) — how usage rolls
  into the Stripe Billing meter.
- [../DPA.tsx](../frontend/src/pages/DPA.tsx) — sub-processor list (Annex 3).
  Any *managed* LLM you enable for customers must be added here.

> **TL;DR** — Free / Starter are BYOK-only. Pro and Enterprise can
> additionally route through *managed* endpoints we operate. Every
> managed LLM provider must (a) sign our DPA, (b) appear in DPA Annex 3,
> (c) have a region matching the customer's data-residency election.

---

## 1. Tier matrix

| Tier | Price/mo | LLM mode | Default model | Token budget | Notes |
|---|---|---|---|---|---|
| **Free** | $0 | None (rule-based only) | — | 0 | No agent, no LLM. Compliance via deterministic primitives + recipes. |
| **Starter** | $49 | BYOK only (Mode A/B/C) | Customer-supplied | Customer-funded | We never see the key beyond AES-256-GCM encrypted storage. |
| **Pro** | $199 | BYOK *or* Managed Pass-Through | `gpt-4o-mini` (managed) / `claude-haiku-3.5` | 5M tokens/mo included; metered above | Pass-through routes via shared OpenAI/Anthropic accounts; per-tenant rate-limited. |
| **Enterprise** | $599+ | BYOK *or* Managed Dedicated | `gpt-4o` / `claude-sonnet-4` / `claude-opus-4` (region-pinned) | Negotiated; ≥ 50M tokens/mo | Choice of Azure OpenAI Services, AWS Bedrock, or self-hosted vLLM/Ollama. |

---

## 2. The four hosting modes

### 2.1 BYOK (Bring Your Own Key) — all tiers

Customer pastes their own provider key in **Settings → LLM Provider**.
We encrypt it at rest with `CRP_COMPLY_BYOK_KEY` (AES-256-GCM, key
derived per-tenant via HKDF), decrypt only in-memory at call time, and
never log or persist the cleartext.

**Operator action:** none beyond setting `CRP_COMPLY_BYOK_KEY` (32-byte
base64) in Railway env vars. **Required for Starter+.**

**No DPA addition needed** — the customer has their own contract with
the provider; we are not the data exporter.

### 2.2 Managed Pass-Through — Pro tier

We operate a shared account at one or more cloud LLM providers.
Customer requests are forwarded with our key, rate-limited per tenant,
metered to Stripe via `comply_proxy_requests` event.

**Operator action:**

```bash
# Railway env vars
CRP_COMPLY_MANAGED_OPENAI_KEY=sk-proj-...        # Pro shared key
CRP_COMPLY_MANAGED_ANTHROPIC_KEY=sk-ant-api03-...
CRP_COMPLY_MANAGED_DEFAULT_PROVIDER=openai
CRP_COMPLY_MANAGED_DEFAULT_MODEL=gpt-4o-mini
CRP_COMPLY_MANAGED_TENANT_RPM=60                 # per-tenant rate limit
CRP_COMPLY_MANAGED_TENANT_TPM=200000             # tokens/min
```

**DPA action required:** OpenAI and Anthropic become **sub-processors**.
They are listed in `frontend/src/pages/DPA.tsx` Annex 3. Confirm
both have signed their standard DPAs (links: OpenAI DPA at
<https://openai.com/policies/data-processing-addendum/>; Anthropic DPA
on request via <enterprise@anthropic.com>).

**Region selection:** OpenAI honours `OpenAI-Beta: data-residency=eu`
header for EU-only routing — set `CRP_COMPLY_MANAGED_OPENAI_REGION=eu`
to enable. Anthropic offers EU residency via AWS Bedrock only (see 2.3).

### 2.3 Managed Dedicated — Enterprise tier

Per-customer dedicated endpoint provisioned in their chosen region.
Three supported back-ends:

#### (a) Azure OpenAI Services

```bash
# Per-customer env-var prefix CRP_COMPLY_AZURE_<TENANT_SLUG>_*
CRP_COMPLY_AZURE_ACME_ENDPOINT=https://acme-eu.openai.azure.com/
CRP_COMPLY_AZURE_ACME_KEY=...
CRP_COMPLY_AZURE_ACME_DEPLOYMENT=gpt-4o-acme
CRP_COMPLY_AZURE_ACME_API_VERSION=2025-04-01-preview
CRP_COMPLY_AZURE_ACME_REGION=swedencentral        # or francecentral
```

Setup runbook:
1. Customer signs Microsoft EA / pay-as-you-go subscription in their tenant.
2. We deploy Azure OpenAI resource in their chosen region (Sweden Central
   for EU data sovereignty; UK South for UK).
3. Quota request via Microsoft (5–10 business days).
4. Endpoint registered in admin UI (`Admin → Tenants → {slug} → LLM`).

DPA: Microsoft Online Services DPA covers Azure OpenAI; add
"Microsoft Azure OpenAI Services (region: ...)" to DPA Annex 3.

#### (b) AWS Bedrock

```bash
CRP_COMPLY_BEDROCK_ACME_REGION=eu-west-3          # Paris
CRP_COMPLY_BEDROCK_ACME_ACCESS_KEY=AKIA...
CRP_COMPLY_BEDROCK_ACME_SECRET_KEY=...
CRP_COMPLY_BEDROCK_ACME_MODEL_ID=anthropic.claude-sonnet-4-20251022-v2:0
```

Supported regions for Claude family: `us-east-1`, `us-west-2`,
`eu-central-1` (Frankfurt), `eu-west-3` (Paris), `ap-southeast-1`
(Singapore), `ap-northeast-1` (Tokyo).

DPA: AWS Service Terms + AWS DPA cover Bedrock; add "Amazon Web
Services Bedrock — Anthropic Claude (region: ...)" to DPA Annex 3.

#### (c) Self-hosted (vLLM / Ollama on Hetzner / OVHcloud / Scaleway)

For air-gapped / EU-sovereign customers who cannot use US hyperscalers.

```bash
CRP_COMPLY_SELFHOST_ACME_BASE_URL=https://llm.acme.internal/v1
CRP_COMPLY_SELFHOST_ACME_KEY=...                  # bearer token
CRP_COMPLY_SELFHOST_ACME_MODEL=llama-3.3-70b-instruct
```

Reference deployments we have validated:
- **Hetzner GEX44** (€241/mo) with NVIDIA RTX 6000 Ada — runs
  Llama-3.3-70B at ~25 tok/s, ample for one Enterprise tenant.
- **OVHcloud Public Cloud GPU L4** (€1.50/h) — burst capacity.
- **Scaleway H100 PCIe** (€2.40/h) — Paris, ISO 27001 + SecNumCloud.

DPA: hosting provider becomes a sub-processor; we provision dedicated
nodes per customer (no shared inference).

---

## 3. Default model per tier (recommended)

| Tier | Drafting / reasoning | Embeddings | Fallback |
|---|---|---|---|
| Starter (BYOK) | Customer-chosen | `text-embedding-3-small` | none |
| Pro (managed) | `gpt-4o-mini` | `text-embedding-3-small` | `claude-haiku-3.5` |
| Enterprise (managed) | `gpt-4o` or `claude-sonnet-4` | `text-embedding-3-large` | `claude-opus-4` (escalation) |
| Enterprise (self-host) | `llama-3.3-70b-instruct` | `bge-large-en-v1.5` | — |

**Why these picks:**
- `gpt-4o-mini` — best $/quality at Pro scale; long context (128k);
  OpenAI honours EU residency.
- `claude-sonnet-4` — best at structured legal drafting (DPIAs, SoAs);
  available in Bedrock EU regions.
- `claude-opus-4` — reserved for escalation (long FRIA / Annex IV docs);
  premium pricing makes it Enterprise-only.
- `llama-3.3-70b-instruct` — best open-weight model for
  air-gapped / sovereign deployments.

---

## 4. Cost guidance

Assumes the agent makes ~3 LLM calls per draft, average 8k input + 2k
output tokens per call. One typical Compliance Report = ~30k input +
8k output total.

| Tier | Typical user/mo workload | Est. token spend | Provider cost (GPT-4o-mini) |
|---|---|---|---|
| Starter | 5 reports | 200k tokens | ~$0.10 (paid by customer) |
| Pro | 50 reports + chat | 5M tokens | ~$2.50 (covered by $199 plan) |
| Enterprise | 500 reports + audit logs | 50M tokens | ~$25 (covered by $599+ plan) |
| Enterprise (self-host) | 500 reports | 50M tokens | ~$0 marginal (fixed €241/mo node) |

Margin per tier: Pro ~98%; Enterprise ~95%. Self-host eliminates LLM
COGS entirely after the fixed node cost is recouped.

---

## 5. Provisioning checklist (per Enterprise tenant)

- [ ] Customer DPA signed (counter-signed PDF in `data/legal/`).
- [ ] LLM region chosen and documented in customer record.
- [ ] Managed endpoint provisioned (Azure / Bedrock / self-host).
- [ ] Sub-processor entry added to `frontend/src/pages/DPA.tsx` Annex 3
      (or noted as BYOK-direct if customer brings their own).
- [ ] Env vars set in Railway (`CRP_COMPLY_AZURE_<SLUG>_*` etc.).
- [ ] `Admin → Tenants → {slug} → LLM` shows green status indicator.
- [ ] Test draft generated end-to-end and signed in evidence chain.
- [ ] Sub-processor change-notice email sent to existing customers
      (30-day notice period per DPA §6.3) **only if** the new provider
      affects more than this one tenant.

---

## 6. Telemetry & cost attribution

Every LLM call records:
- `provider` (openai / anthropic / azure / bedrock / selfhost)
- `model`
- `input_tokens` / `output_tokens`
- `cost_usd` (computed from per-model price table in
  `src/crp_comply/api/usage.py`)
- `tenant_id`
- `latency_ms`
- `endpoint` (which agent tool triggered the call)

Surfaced in:
- `Admin → Usage` dashboard (per-tenant, per-model rollups)
- Stripe Billing meter (`comply_proxy_requests`) for managed tiers
- Tamper-evident hash chain (`data/audit/llm_calls.jsonl`) for SOC 2 evidence

---

## 7. Quick reference — switching a tenant from BYOK to Managed

```bash
# 1. Set the managed key for the provider
railway variables set CRP_COMPLY_MANAGED_OPENAI_KEY=sk-proj-...

# 2. Update the tenant record
crp-comply tenant update <slug> --llm-mode managed --provider openai \
    --model gpt-4o-mini --monthly-budget-usd 50

# 3. Confirm the change ran
crp-comply tenant show <slug> | grep llm
```

A change-of-mode emits a `tenant.llm_changed` audit event captured in
the evidence chain.
