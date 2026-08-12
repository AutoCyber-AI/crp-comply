# CRP Comply — Business Model & the "We Offer an LLM" Problem

> **The founder's concern:** *"We say we offer [an LLM connection] even though we don't.
> What can we do to upsell local LLM?"*
> **Short answer:** The honest position is strong — **CRP Comply is a compliance layer, not a
> model vendor** — but some current copy (especially the README "proxy" framing and the
> MARKETING.md "managed LLM tokens, 98% gross margin" line) **oversells a hosted model you
> don't really operate at scale.** Fix the copy to lead with *"bring/run your own model, $0
> inference"*, and turn **local LLM** from an apology into the **headline differentiator**:
> private, free, and audited. Then upsell *convenience* (managed tokens) and *assurance*
> (compliance, support, retention) — not the model itself.

---

## 1. What we actually sell (the truth, stated plainly)

CRP Comply does **not** ship or host a frontier model as its core product. Reality by tier:

| Tier | Inference reality |
|---|---|
| **Free** | **No LLM at all** for the core path — deterministic rule-based compliance (EU AI Act classifier, PII scan, recipes). Optional **local** Ollama/LM Studio for agent features at **$0/call**. |
| **Starter** | **BYOK only** — the customer supplies their OpenAI/Anthropic key (encrypted AES-256-GCM). We never host a model. |
| **Pro** | BYOK **or** optional **managed pass-through** to a shared Groq account (operator-funded, metered). Convenience, not a moat. |
| **Enterprise** | BYOK / customer Azure-OpenAI / Bedrock / self-hosted vLLM. The customer's infra. |

So the product is a **compliance control plane**: PII scanning, injection defence, EU AI Act
classification, audited reasoning, retention. The model is **plumbing the customer brings.**
That is a *defensible* and *honest* story — we just have to tell it that way.

---

## 2. Where the copy currently over-promises (fix these)

| Claim | File | Problem | Fix |
|---|---|---|---|
| "OpenAI-compatible **compliance proxy** … Forwarded to your configured LLM" | `README.md` | "proxy" implies we run inference; we forward to *your* model | Reframe: "compliance layer **in front of the model you choose** — local, BYOK, or managed." |
| "usage-metered **managed LLM tokens**. **98% gross margin** on managed tier" | `MARKETING.md` | Implies a hosted-model business that barely exists; 98% margin claim is fragile and off-message | Drop the margin claim; reframe managed tokens as an **optional convenience add-on**, not the business. |
| Tier feature "Local LLM connector" listed as a *feature among many* | `Pricing.tsx` | Buries the single best differentiator | **Lead** with it: "Runs on your own machine. $0 inference. Nothing leaves your network." |

**Principle:** never claim to *provide* a model. Claim to *make any model you run
compliant, private, and audit-ready.*

---

## 3. Turn "local LLM" into the headline (the upsell strategy)

Local LLM is not the weakness — it's the wedge. Three reasons it sells *better* than a hosted
model for this buyer (compliance/legal/risk):

1. **Data residency & privacy.** "Your prompts and documents never leave your machine/VPC."
   This is the #1 objection compliance buyers have about AI. We turn it into our default.
2. **$0 marginal cost.** "Run unlimited compliance checks for free on a model you already
   have." Removes price as a blocker to adoption.
3. **No vendor lock-in.** Swap Ollama ↔ LM Studio ↔ vLLM hot, no restart.

### The funnel
```
Free (local, $0)  →  Starter (BYOK + support/retention)  →  Pro (managed convenience)  →  Enterprise (assurance)
   land on privacy      pay for compliance value, not tokens     pay to NOT run infra        pay for SLA + audit
```

### Concrete upsell moves
- **One-command local onboarding.** Lead the Setup wizard's "Connect LLM" step with a big
  **"Run it locally (recommended, free, private)"** button →
  `curl -fsSL https://comply.crprotocol.io/install-local-llm.sh | sh`, model auto-detected.
  Make BYOK/managed the *secondary* options.
- **Hardware-aware model picker.** Detect RAM and recommend the model
  (`qwen2.5:3b` < 8GB, `llama3.1:8b` 8–16GB, … `llama3.3:70b` 64GB+) — already documented in
  `LOCAL_LLM_GUIDE.md`; surface it in-product.
- **"Local works, but do you want to not babysit it?"** Position **managed tokens** as paying
  to avoid running/scaling a local model — sell the *operational relief*, not the tokens.
- **Sell the layer, meter the convenience.** Pricing tiers should gate **compliance value**
  (PII categories, injection ML, audit retention, RBAC, SLA) — things we genuinely own — and
  treat managed inference as a metered add-on with transparent pass-through pricing.
- **Privacy badge.** "Local mode: 0 bytes leave your network" as a trust marker on the
  pricing/product pages and in the audit report output.

---

## 4. What to charge for (value we actually own)

Stop implying the model is the product. Charge for the **compliance moat**:

- **Coverage:** 7-category PII, 21+ injection patterns → ML-enhanced injection (Pro+).
- **Evidence:** audit retention (7 days → 90 days → 1 year → 7 years), signed audit trails,
  Annex IV draft generation, EU AI Act classification reports.
- **Governance:** RBAC, multi-tenant, region pinning, SLA (99.95% Cloud).
- **Convenience:** optional managed tokens for teams who won't run local.

This reframes every tier as "more compliance assurance," with inference as a swappable input.

---

## 5. Messaging rewrite (drop-in)

> **Old (overclaims):** "CRP Comply is an OpenAI-compatible compliance proxy — forwarded to
> your LLM, with managed LLM tokens at 98% margin."
>
> **New (honest + stronger):** "CRP Comply is the compliance layer for AI you already run.
> Point it at a model on your own machine (free, private), your own API key, or our optional
> managed tokens — and every call is PII-scanned, injection-checked, EU AI Act-classified, and
> audit-logged. **The model is yours. The compliance is ours.**"

---

## 6. Action checklist

- [ ] Rewrite `README.md` lead from "proxy/forwarder" → "compliance layer in front of your model."
- [ ] Remove the "98% gross margin / managed LLM tokens" framing from `MARKETING.md`; reposition managed tokens as an optional convenience add-on.
- [ ] Make **"Run locally — free & private"** the primary CTA in the Setup "Connect LLM" step.
- [ ] Add the hardware-aware model recommender into the in-product wizard.
- [ ] Add a "0 bytes leave your network" privacy badge to pricing/product + audit report.
- [ ] Re-tier the pricing copy around **compliance value**, not model access.
- [ ] Reconcile the price tables (see Payment Workflow Analysis G0) so copy matches Stripe.

---

*Licensed under the Elastic License 2.0 — see LICENSE.md for details.*
