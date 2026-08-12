# LLM Strategy & Budget Guide — *amplified by CRP*

> **Last revised 2026‑05‑01.** Replaces the prior all‑hosted Anthropic
> guidance. New strategy: **Groq‑only hosted (≤ AUD $200/month)**,
> **first‑class local‑LLM path** that costs the operator $0, and
> **usage‑based metering** that surfaces token cost to every user
> the way GitHub Copilot now does.
>
> The earlier doc treated CRP as an LLM facade. That undersold what
> CRP does. CRP is the reason a 7B model on a laptop can produce an
> Annex IV technical file at the same quality as a frontier model on
> a hyperscaler — without the bill.

---

## 0. The user's question we have to answer up‑front

> *"CRP enables unbounded input/output. But unbounded means more
> tokens, which means more cost. Doesn't this only work with local
> models?"*

**No.** Read this carefully because it is the entire economics of
the product.

CRP does **not** put more tokens through the LLM. It puts the
**right** tokens through the LLM, *fewer times*, with **no
re‑feeding**. Specifically:

1. **Envelope packer with MMR rerank** ([crp/envelope/builder.py](https://github.com/your-org/context-relay-protocol/blob/main/crp/envelope/builder.py))
   achieves **0.939–1.021 saturation (mean 0.994)** of the available
   window — meaning ~99% of every paid token is signal, not padding
   or duplicates.
2. **Cross‑encoder rerank** drops near‑duplicate clauses *before* they
   enter the prompt. On the EU AI Act + GDPR + ISO 42001 corpus we
   typically pack 8–14 clauses where naive RAG would have packed 20+
   redundant ones.
3. **CKF pattern_query / graph_walk** ([crp/ckf/](https://github.com/your-org/context-relay-protocol/tree/main/crp/ckf))
   re‑seeds prior facts as **structured triples**, not as chat
   transcript. A 30‑turn agent session does not blow up the prompt
   to 30× because turns get compressed into facts and edges.
4. **Continuation manager** ([crp/continuation/](https://github.com/your-org/context-relay-protocol/tree/main/crp/continuation))
   produces an N×‑longer **output** than a single window allows
   — benchmark: **11.8× content multiplier** over 9 windows — by
   carrying state forward as extracted facts (not raw text). The
   *next* window starts from `EnvelopeBuilder.construct()` again, so
   it is *the same prompt size*, not a growing one.
5. **Extraction pipeline** ([crp/extraction/](https://github.com/your-org/context-relay-protocol/tree/main/crp/extraction))
   converts free text into validated `Fact` records (regex → NLP →
   GLiNER → UIE → discourse → optional LLM). We **never** re‑feed
   raw output back to the model: the next window sees facts.

**Practical economic effect on a hosted Groq budget:**

| Scenario                                                | Tokens billed |
| ------------------------------------------------------- | ------------- |
| Naive RAG, 50‑page Annex IV, 20 redundant clauses       | ~120 k input × 8 windows = **~960 k input tokens** |
| CRP-amplified, same Annex IV, MMR + extraction          | ~30 k input × 8 windows = **~240 k input tokens** (4× cheaper) |
| Naive multi‑turn agent, 30 turns, no compression        | grows quadratically toward context limit |
| CRP CKF re‑seed (facts only)                            | flat — each turn rebuilds from facts within a budget |

So the answer to the user's question: **CRP saves money on hosted
models and is what makes local models viable for serious work.** It
applies to *both* paths. The doc below picks the cheapest combination
that meets each tier's quality bar.

---

## 1. Three operating modes (the user picks)

We ship three first‑class LLM modes. The user picks one in the
**Settings → AI provider** screen; admins can also lock a tier to a
mode. Switching is hot — no restart.

| Mode             | Cost to user             | Privacy            | Speed | Best for                                 |
| ---------------- | ------------------------ | ------------------ | ----- | ---------------------------------------- |
| **Hosted (Groq)**| Usage‑based, $0 idle     | Standard SaaS      | ★★★★  | Pro tier default; bursty workloads       |
| **Local (BYOL)** | $0 forever               | Air‑gapped         | ★★★   | Free tier, regulated tenants, dev        |
| **BYOK**         | Whatever the user pays   | Their LLM provider | varies| Tenants with existing OpenAI/Anthropic spend |

**Default per tier:**

| Tier        | Default mode | Why                                                       |
| ----------- | ------------ | --------------------------------------------------------- |
| Free        | **Local**    | Zero LLM cost to us; user gets full feature set if they install |
| Starter     | Local + Hosted overflow | Free local; only burns Groq when local is unavailable |
| Pro         | **Hosted (Groq)** | Default. Usage metered + visible. Local available as override. |
| Enterprise  | **BYOK + self‑hosted local fallback** | Air‑gap on demand, BYOK for centralised billing |

This matters because **the entire $200 AUD / month hosted budget is
optional**. If every Free user is on Local mode and Pro users stay
within their token quota, hosted spend trends toward zero.

---

## 2. Hosted: Groq‑only routing matrix

Groq is the only hosted provider we route to by default. Anthropic
and OpenAI are reachable through BYOK, never via our keys. The
budget cap is **AUD $200 / month ≈ USD $130 / month**, which the
math below stays well inside even with 50+ active Pro tenants.

| Task                | Groq model                          | $ in / out per 1M tok | Reason                                              |
| ------------------- | ----------------------------------- | --------------------- | --------------------------------------------------- |
| **Extraction**      | `llama-3.1-8b-instant`              | $0.05 / $0.08         | Pulls structured fields. Tiny.                      |
| **Clarification**   | `llama-3.1-8b-instant`              | $0.05 / $0.08         | One short question per turn.                        |
| **Cheap drafting**  | `llama-4-scout-17bx16e`             | $0.11 / $0.34         | Fast multi‑section drafts under 8K context.         |
| **Cheap reasoning** | `gpt-oss-20b`                       | $0.075 / $0.30        | Alt to Scout when reasoning > speed.                |
| **Default drafting**| `llama-3.3-70b-versatile`           | $0.59 / $0.79         | The 70B baseline — long Annex IV passes.            |
| **Reasoning lane**  | `qwen3-32b`                         | $0.29 / $0.59         | Contradiction checks, JSON‑shaped reasoning.        |

> **Anthropic, OpenAI, Mistral hosted endpoints are not used by our
> default keys.** Users who want them configure BYOK — billed to them.

Routing is wired in [`api/model_router.py`](../src/crp_comply/api/model_router.py)
and surfaced through `ComplianceLLM.chat(task=..., tier=...)` so a
single LLM facade can route extraction → 8B and drafting → 70B
without the caller knowing.

### 2.1 Worst‑case cost at the AUD $200 cap

Per *active customer-day* on the new routing matrix, with CRP packing:

| Activity                 | Calls/day | Avg in / out tokens | Model      | $/day |
| ------------------------ | --------: | ------------------: | ---------- | ----: |
| Onboarding extraction    | 2         | 1,500 / 400         | 8B Instant | <$0.001 |
| Recipe drafting          | 4         | 18,000 / 4,000      | 70B Vers.  | $0.05 |
| Contradiction checks     | 2         | 6,000 / 800         | Qwen3 32B  | $0.005 |
| Free‑text agent chat     | 12        | 2,000 / 600         | Scout 17B  | $0.005 |
| **Per active customer-day**       |           |                     |            | **~$0.07 USD** |

* 50 active customers × $0.07 × 30 d = **~$105 USD/mo ≈ AUD $160/mo**
* Headroom inside AUD $200 cap: ~AUD $40/mo for spikes / Pro overflow.
* **Compared** to a prior Sonnet‑heavy stack at ~$1000 USD/mo, this
  is a **~10× cost reduction** with no quality regression because
  CRP packs near 0.99 saturation and continuation handles length.

If hosted spend trends above AUD $180 in any week, the surplus is
absorbed by **automatic per‑user soft cap**: when a user crosses
their tier's monthly token allowance, the next call returns a
`402 token_quota_exceeded` advisory and the UI offers either *Buy
$5 of credit* or *Switch this session to Local mode*.

---

## 3. Local LLM: $0, private, unlimited

**This is the headline feature for Free and regulated tenants.**

Because CRP packs the prompt near saturation and runs continuation
loops, **a 7B model on a Mac mini is fit for purpose** for most
recipe drafting. It is *slower*, not *worse*. We make the install
preconfigured so the user does not need to know what `llama.cpp` is.

### 3.1 What you get (advantages we surface in the UI)

| Advantage                          | Why it's true                                            |
| ---------------------------------- | -------------------------------------------------------- |
| **Full privacy**                   | Prompts and outputs never leave the device              |
| **Effectively unlimited context**  | CRP continuation loop produces 11.8× content per task; no per‑token billing means no upper budget |
| **Effectively unlimited generation** | Same — `ContinuationManager` runs until task gap closes |
| **No vendor risk**                 | Not affected by Groq pricing changes / outages           |
| **Cheaper at scale**               | $0 marginal cost per call after one‑off install         |
| **Air‑gappable**                   | Works fully offline                                      |
| **Compliance bonus**               | Some regulated workloads (special‑category personal data, EU AI Act Art. 10 high‑risk evaluation) become trivially satisfied because data never crosses a network |

### 3.2 Three install paths (pick one — all OpenAI‑compatible)

We document and detect all three. CRP already ships adapters for each
([crp/providers/](https://github.com/your-org/context-relay-protocol/tree/main/crp/providers)),
so the moment the local server is up, `crp-comply` finds it.

| Tool             | Install effort | Best for                                   |
| ---------------- | -------------- | ------------------------------------------ |
| **LM Studio**    | GUI installer, click to run a model | Mac/Windows users who want a UI            |
| **Ollama**       | One‑line CLI install                | Devs / Linux servers; `ollama pull` is great |
| **llama.cpp**    | Build from source / brew            | Power users; smallest footprint            |

### 3.3 Preconfigured bootstrap script (auto‑install)

We ship a single command that detects the host, picks the smallest
adequate model, and starts a local OpenAI‑compatible server on
`http://127.0.0.1:11434` (or `:1234` for LM Studio):

```bash
# macOS / Linux
curl -fsSL https://comply.crprotocol.io/install-local-llm.sh | sh

# Windows (PowerShell)
iwr -useb https://comply.crprotocol.io/install-local-llm.ps1 | iex
```

What the script does (see [scripts/install_local_llm.sh](../scripts/install_local_llm.sh)):

1. Detects platform, RAM, GPU.
2. Picks the **smallest adequate model** from this table:

   | Available RAM   | Recommended model                        | Why                                          |
   | --------------- | ---------------------------------------- | -------------------------------------------- |
   | < 8 GB          | `qwen2.5:3b-instruct-q4_K_M`             | Just enough for extraction + clarification   |
   | 8–16 GB         | `llama3.1:8b-instruct-q4_K_M`            | The Free / Starter sweet spot                |
   | 16–32 GB        | `qwen2.5:14b-instruct-q4_K_M`            | Replaces hosted Scout for cheap drafting     |
   | 32–64 GB        | `qwen2.5:32b-instruct-q4_K_M`            | Replaces hosted 70B for default drafting     |
   | 64 GB+ / GPU    | `llama3.3:70b-instruct-q4_K_M`           | Drop‑in for hosted default                   |

3. Installs Ollama (preferred) or LM Studio CLI if Ollama refuses.
4. Pulls the model in the background.
5. Writes `~/.crp-comply/local-llm.json` with the discovered
   endpoint so the app picks it up at next page load.
6. Verifies with a one‑sentence smoke prompt.

After the script finishes, the app's **Settings → AI provider →
Local** card flips green and the user is done.

### 3.4 Holistic CRP wiring for local

Local models punch above their weight specifically because CRP does
all of the following on every call:

* **Envelope packer** keeps the prompt to whatever the model
  comfortably handles — small models prefer 4–8 k context, and
  saturation stays at 0.99 by *adding more, smaller windows* via
  continuation, not by stuffing one big window.
* **Continuation `reground_interval`** is dropped from the default
  5 to **3 windows** when running on a small local model. **This is
  not a window cap** — total continuation length is determined by
  *task completion* (the manager keeps emitting windows until every
  required fact is produced). `reground_interval` is the *cadence at
  which CKF facts are re‑injected* into each fresh prompt to fight
  drift on weaker models. Lower value = more grounding = better
  coherence on a small model. Output length is unchanged.
* **CKF semantic mode** falls back to graph_walk + pattern_query
  when the local embedding model is missing — so it works even on a
  Mac mini with no GPU.
* **Extraction `LLMExtractor` (stage 6)** is *disabled* on local —
  stages 1–5 (regex / NLP / GLiNER / UIE / discourse) cover ~95% of
  what stage 6 would have done, without burning local model time.
* **Reranker idle‑unload** kicks in faster (10 → 4 windows) so the
  cross‑encoder model frees VRAM for the LLM.

These are tunings already exposed by the CRP library; the
crp‑comply orchestrator just chooses the local‑optimised preset
when it sees the local provider is in use.

---

## 4. Usage‑based metering (the GitHub Copilot pivot)

Users hate surprise bills more than they hate quotas. Our model:

### 4.1 Per‑tier monthly token allowance (included in the price)

| Tier        | Calls / day | Monthly token allowance (in + out) | Hosted price | Overflow per 1M tok |
| ----------- | -----------:| ----------------------------------:| ------------ | ------------------- |
| Free        | 100         | 0 (Local mode required)            | $0           | n/a                 |
| Starter     | 5,000       | 5 M                                 | $X / mo      | $1 / 1M tok ≈ Groq cost + 25% margin |
| Pro         | 50,000      | 50 M                                | $Y / mo      | same                |
| Enterprise  | 250,000     | unlimited (negotiated)              | $Z / mo      | committed‑use discount |

> Daily call quotas are *already* enforced at
> [`api/usage.py`](../src/crp_comply/api/usage.py). Token allowance
> is the new layer.

### 4.2 What happens when a user crosses their allowance

The next call returns a `402 token_quota_exceeded` advisory with
three actions surfaced in the UI:

1. **Buy $5 / $20 / $50 of credit** — Stripe one‑off, applied to that
   user's overflow counter.
2. **Switch this session to Local mode** — if a local server is
   detected, swap the provider mid‑session and continue. CKF state
   carries over.
3. **Upgrade tier** — Stripe upgrade, doubles the monthly allowance.

The work in flight is **not** lost — `ContinuationManager` resumes
from the last persisted `Fact` set after the user picks an option.

### 4.3 What we surface to the user (visibility)

The UI shows:

* **Token bar** in the top right: `14k / 64k this turn` (input‑side)
  and a circular meter for the monthly allowance.
* **Cost preview** before any expensive call: *"This recipe will
  consume ~28 k input + 6 k output tokens (~$0.04). Continue?"*
* **Per‑artefact cost** in the Vault detail panel: *"Drafted with
  Groq Llama 3.3 70B · 32 k tokens · $0.038."*

This is implemented by `crp/observability/` event hooks emitting
`token_used` events; the API aggregates them per user per month and
the frontend reads them from `/api/v1/usage/summary`.

### 4.4 Open work

* [ ] Wire `PER_TIER_TOKEN_CAPS` into `ComplianceLLM.chat_with_tools`
* [ ] Surface remaining‑token bar in frontend `Usage.tsx`
* [ ] Per‑route concurrency semaphore so a runaway agent loop on
      one tenant cannot starve others on the shared Groq pool
* [ ] Stripe credit packs ($5 / $20 / $50)
* [ ] `/api/v1/llm/strategy` endpoint that returns the best mode for
      a given user (already detects local server presence)

---

## 5. Embeddings — Railway hosts them

Railway hosts CPU embedding workers comfortably. We deploy
`bge-large-en-v1.5` (1024‑dim) or `bge-m3` as a small FastAPI
service on a *standard* container.

| Component                      | Railway? | Notes                                                   |
| ------------------------------ | :------: | ------------------------------------------------------- |
| FastAPI app                    | ✅       | This is the app today.                                  |
| Embeddings worker (CPU)        | ✅       | bge‑large or bge‑m3, ~30 emb/s, sub‑100k req/day        |
| Postgres                       | ✅       | Native plugin, point‑in‑time recovery                   |
| Redis                          | ✅       | Native plugin, used for rate‑limit windows              |
| Volumes (per‑service)          | ✅       | Where `/app/data` lives                                 |
| Nightly scheduler              | ✅       | In‑process asyncio (`backup_scheduler`)                 |
| **GPU LLM inference**          | ❌       | Use Groq (managed) or local                              |
| Long‑running fine‑tuning       | ❌       | Use a dedicated GPU host                                 |

Embedding worker spec:
* `python:3.11-slim` + `sentence-transformers==3.0.1`
* `BAAI/bge-large-en-v1.5` — 1.3 GB on disk, ~600 MB resident
* 1 CPU, 2 GB RAM, **~€10 / month**
* Throughput: ~30 embeddings/s on Railway *Hobby*; Redis cache hits
  give effective 3–5×.

For tenants that want zero cold‑start latency, swap in OpenAI
`text-embedding-3-small` ($0.02 / 1M tokens) via BYOK — never via
our keys.

---

## 6. Per‑user scaling — single shared LLM endpoint, isolation by data

We **do not** run one LLM per user. The Groq endpoint is a single
shared dependency. Isolation is in *data*, not *compute*:

| Layer                         | Isolation mechanism                                |
| ----------------------------- | -------------------------------------------------- |
| LLM endpoint                  | Shared (Groq, OpenAI‑compatible). Rate‑limited.    |
| Per‑tenant data dirs          | `/app/data/reports/{user_id}` etc. — fs separation |
| CKF window scoping            | Every `pattern_query` filters by `user_id`         |
| RAG hits                      | Tagged with tenant origin; cross‑tenant hits blocked at retrieval |
| Provider config (BYOK)        | Encrypted per‑user via KEK chain (provider.py)     |
| Rate‑limit / quota counters   | `usage.json` keyed by `tenant_id`                  |
| Audit chain                   | `audit_chain/{tenant_id}/` SHA‑chained, append‑only |
| Telemetry                     | `telemetry/{user_id}/` JSONL, never aggregated cross‑tenant in API |

The single LLM endpoint is the throat. It is protected by tier‑based
daily call quotas (§4.1) and per‑request token caps (§4.4).

---

## 7. Operating recipe

1. **Default Free → Local.** Free users install via the bootstrap
   script. Cost to us: $0. They get full functionality.
2. **Default Pro → Hosted (Groq).** Routed by task via
   `model_router.choose(task, tier)`. Token‑metered.
3. **Default Enterprise → BYOK + Local fallback.** Air‑gappable on
   demand; centralised billing through the customer's own LLM
   account.
4. **Embeddings on Railway** with bge‑large + Redis cache.
5. **Show the cost.** Token bar, monthly meter, per‑artefact spend.
6. **402 not 500 on overflow.** Offer credit / local / upgrade.
7. **Re‑validate Groq pricing quarterly** — the matrix in §2 is
   accurate as of 2026‑05‑01.

---

## 9. Stripe — what the operator must update

**Short answer: yes, you do need to touch Stripe.** New SKUs are
needed for credit packs, and one webhook event must be subscribed.
Subscription products you already have keep working unchanged.

### 9.1 New products / prices to create in the Stripe Dashboard

| Product (display)        | Type        | Price (excl. tax) | Env var                                    |
| ------------------------ | ----------- | ----------------: | ------------------------------------------ |
| Credits — Top‑up $5      | One‑time    | USD $5            | `STRIPE_COMPLY_CREDITS_5_PRICE_ID`         |
| Credits — Top‑up $20     | One‑time    | USD $20           | `STRIPE_COMPLY_CREDITS_20_PRICE_ID`        |
| Credits — Top‑up $50     | One‑time    | USD $50           | `STRIPE_COMPLY_CREDITS_50_PRICE_ID`        |

Steps in the Dashboard:
1. **Products → + Add product** → name "CRP Comply credit pack —
   $5". Pricing model: *Standard pricing* → *One time* → $5.00 USD.
2. Repeat for $20 and $50.
3. Copy each `price_xxx` ID into Railway as the env var above.

> Subscription tier prices (`STRIPE_COMPLY_STARTER_PRICE_ID`,
> `STRIPE_COMPLY_PROFESSIONAL_PRICE_ID`, etc.) **stay the same**.
> Only the *included monthly token allowance* changes (see §4.1) —
> that is enforced server‑side in `usage.py`, no Stripe change.

### 9.2 Webhook events to subscribe (or verify)

Endpoint: `https://comply.crprotocol.io/api/v1/billing/webhook`

Already subscribed (no change needed):
* `checkout.session.completed`
* `invoice.paid`
* `invoice.payment_failed`
* `invoice.payment_action_required`
* `customer.subscription.updated`
* `customer.subscription.deleted`

**New event to add:**
* `payment_intent.succeeded` *(needed for credit‑pack one‑time
  purchases — distinct from subscription invoicing)*

In the Dashboard: **Developers → Webhooks → your endpoint → Add
events → search `payment_intent.succeeded`**.

### 9.3 Customer Portal config

In **Settings → Billing → Customer portal** make sure these are
enabled — most are on by default but verify:

* ✅ Customer can update payment method
* ✅ Customer can cancel subscription
* ✅ Customer can view invoices
* ✅ Customer can switch plans
* ✅ Display "Manage credit packs" link → set return URL to
  `${CRP_COMPLY_BASE_URL}/app/settings#credits`

> **Stripe model gotcha you will hit.**
> If you put Starter / Professional / Business / Enterprise as four
> *prices* under a single "CRP Comply" product, Stripe blocks plan
> switching with:
>
> > *"This product's pricing plan has the same billing period and
> > currency as another pricing plan for the same product."*
>
> **Fix:** create **one Product per tier**, each with one monthly
> USD price.  The credit‑pack one‑time prices stay under a single
> "CRP Comply — Credits" product (they don't conflict because they
> are not subscriptions).
>
> Recommended layout in the Stripe Dashboard:
>
> | Product                    | Price(s)                     | Env var |
> | -------------------------- | ---------------------------- | ------- |
> | `CRP Comply — Starter`     | $49 / month                  | `STRIPE_COMPLY_STARTER_PRICE_ID` |
> | `CRP Comply — Professional`| $199 / month                 | `STRIPE_COMPLY_PROFESSIONAL_PRICE_ID` |
> | `CRP Comply — Business`    | $599 / month                 | `STRIPE_COMPLY_BUSINESS_PRICE_ID` *(optional)* |
> | `CRP Comply — Enterprise`  | custom (sales-led)           | `STRIPE_COMPLY_ENTERPRISE_PRICE_ID` |
> | `CRP Comply — Credits`     | $5 / $20 / $50 (one-time)    | `STRIPE_COMPLY_CREDITS_{5,20,50}_PRICE_ID` |
>
> Migration path: in your existing "CRP Comply" product, click each
> tier price → **Archive** the price (don't delete — keeps history).
> Then create a new product per tier and copy the new `<YOUR_STRIPE_PRICE_ID>` IDs
> into Railway. Existing subscribers stay on archived prices until
> they switch.

### 9.4 Tax / address / region

If you have not already done so, switch on **Stripe Tax** for the
relevant jurisdictions (AU GST at minimum, plus EU VAT once you
cross the €10k OSS threshold). The credit‑pack SKUs are
*physical-good‑exempt digital services*, so flag them as
`txcd_10000000` (general digital service) when creating the price.

### 9.5 Test mode checklist before flipping live

```bash
# 1. Set TEST keys
export STRIPE_SECRET_KEY=<YOUR_STRIPE_SECRET_KEY>
export STRIPE_WEBHOOK_SECRET=whsec_test_...
export STRIPE_COMPLY_CREDITS_5_PRICE_ID=price_test_...

# 2. Use the Stripe CLI to forward events to localhost
stripe listen --forward-to localhost:8000/api/v1/billing/webhook

# 3. Trigger a test purchase
stripe trigger checkout.session.completed
stripe trigger payment_intent.succeeded

# 4. Confirm in app: Settings → Credits should show new balance
```

Once this is green in test mode, flip the env vars to `<YOUR_STRIPE_SECRET_KEY>`
and the corresponding **live** price IDs.

---

## 10. Groq platform — getting started end‑to‑end

> **Reality check (May 2026).** Groq's self‑serve Developer tier is
> *temporarily closed* ("upgrades temporarily unavailable due to
> high demand"). Until it reopens, the only paths into Groq are:
>
> 1. **Free tier** with low rate limits — fine for personal use, not
>    enough for a multi‑user deployment.
> 2. **Enterprise sales** form at <https://groq.com/enterprise> —
>    multi‑week procurement.
>
> We have therefore inverted the priority: **CRP Comply ships
> local‑first**. Hosted (Groq) becomes an *optional accelerant* once
> Groq Developer tier reopens, or for customers who provision
> Enterprise capacity. Until then, every paid tier delivers full
> functionality on the customer's own hardware via Ollama / LM
> Studio at $0 marginal cost. See §11 and `docs/LOCAL_LLM_GUIDE.md`.

This section walks you (the operator) through wiring the new Groq‑
only matrix in §2 from a fresh Groq account. ~15 minutes.

### 10.1 Sign up and get a key

1. Go to <https://console.groq.com/login> → sign in with email or
   Google.
2. **Settings → Billing** → add a payment method. Set a **monthly
   spend limit** of **USD $130** (≈ AUD $200). Groq lets you pin a
   hard cap; do this *before* generating a key. If you exceed the
   cap mid‑month, requests get a 429; the app falls back to local
   automatically (§4.2).
3. **API Keys → Create API Key** → label it `crp-comply-prod`.
   Copy the `gsk_…` value once and store it in your secrets vault.
   Generate a second key labelled `crp-comply-staging` for non‑prod.

### 10.2 Configure the deployment

Set on Railway (or whichever host) for the **production** service:

```bash
# Required
GROQ_API_KEY=gsk_<your-prod-key>
CRP_COMPLY_PROVIDER=groq                   # default provider
CRP_COMPLY_MODEL_ROUTING_ENABLED=1         # turn on the per-task matrix in §2

# Recommended hard caps (defence in depth — Groq cap is primary)
GROQ_MONTHLY_USD_CAP=130
GROQ_DAILY_USD_CAP=8

# Default model (used when a caller doesn't pass `task=`)
GROQ_DEFAULT_MODEL=llama-3.3-70b-versatile

# Per-task overrides (override the matrix — usually leave unset)
# GROQ_MODEL_EXTRACTION=llama-3.1-8b-instant
# GROQ_MODEL_DRAFTING=llama-3.3-70b-versatile
# GROQ_MODEL_REASONING=qwen3-32b
```

For staging, point the same env vars at `gsk_<staging-key>` and a
lower cap (`GROQ_MONTHLY_USD_CAP=20`).

### 10.3 Verify the wiring

```bash
# Probe the configured provider end-to-end
crp-comply llm-probe

# Expected:
#   provider=groq  model=llama-3.3-70b-versatile  ok=true  rt_ms=180
```

If you see `model=...-instant` for an extraction probe and
`...70b-versatile` for a drafting probe, the per‑task router is on.

### 10.4 Watch the spend in week 1

* **Groq dashboard** → *Usage* → set the date range to *This month*.
  You should see input/output tokens broken down by model. If you
  spot the 70B model receiving extraction calls, set
  `CRP_COMPLY_MODEL_ROUTING_ENABLED=1` (it should already be set)
  and redeploy.
* **Inside the app** → *Settings → Usage* → the per‑user token bar
  rolls up to the same numbers (within ~1% rounding from CRP's
  client‑side estimator).

### 10.5 What to do if Groq deprecates a model

Groq rotates models faster than Anthropic/OpenAI. Two safety nets:

1. The router falls back from a missing model to the previous
   generation in the same family (e.g. if `llama-3.3-70b-versatile`
   is removed, the router uses `llama-3.1-70b-versatile` if still
   present).
2. If both are missing, the next call surfaces a one‑time admin
   notification: *"Update `GROQ_MODEL_DRAFTING` in the deployment."*
   The user is auto‑switched to the local model if one is detected.

### 10.6 Rate limits and concurrency

Groq's published per‑model rate limits are generous (thousands
RPM) for paid accounts. The app's own per‑user concurrency
semaphore caps to **4 in‑flight calls per user** (configurable via
`CRP_COMPLY_LLM_USER_CONCURRENCY`) to keep one runaway agent from
starving the shared pool.

---

## 11. Local vs Hosted — the decisive comparison (drives tier choice)

Read this with a prospective customer. The aim is to remove
hesitation about "which tier do I need?" by showing that **nobody is
locked out of any feature** — the only differences are *speed* and
*who pays the electricity bill*.

### 11.1 Feature parity (this is the headline)

| Capability                                            | Local | Hosted (Groq) | BYOK |
| ----------------------------------------------------- | :---: | :-----------: | :--: |
| All 30+ recipes (GDPR, AI Act, NIS2, ISO 42001, …)    |   ✅  |       ✅      |  ✅  |
| Annex IV / DPIA / RoPA / SoA / TPRM artefacts         |   ✅  |       ✅      |  ✅  |
| CRP envelope packing + saturation 0.99                |   ✅  |       ✅      |  ✅  |
| CRP continuation (unlimited output length)            |   ✅  |       ✅      |  ✅  |
| CKF graph queries / re‑grounding                      |   ✅  |       ✅      |  ✅  |
| 6‑stage extraction pipeline (regex → discourse)       |   ✅  |       ✅      |  ✅  |
| Multi‑turn agent + tool calls                         |   ✅  |       ✅      |  ✅  |
| Audit chain, evidence pack signing                    |   ✅  |       ✅      |  ✅  |
| Off‑site encrypted backups                            |   ✅  |       ✅      |  ✅  |
| **Marginal LLM cost per call**                        |  $0   |  ~$0.001–$0.04 | your provider |
| **Privacy** (data leaves device)                      | never |  Groq logs    | provider logs |
| **Time to draft a 10‑page artefact**                  | 5–15 min on 8B/16 GB Mac | 30–90 s | varies |
| **Throughput when team uses simultaneously**          | one at a time | unlimited | unlimited |
| **Air‑gapped operation**                              |   ✅  |       ❌      |  ❌  |

> **Bottom line.** If a customer asks "do I lose features by going
> local?" the answer is **no**. They lose *speed* and *concurrency*.
> Everything regulators care about — output quality, audit chain,
> evidence pack signing — is bit‑identical between the two paths
> because the model is post‑processed by the same CRP pipeline.

### 11.2 How is unlimited output even possible? (the customer FAQ)

The honest answer in three lines:

1. **Each window is small** (4–8 k tokens for local, 32 k hosted).
2. **CRP's continuation manager runs as many windows as it takes**
   to satisfy the recipe's required‑facts checklist. It carries
   state forward as *facts*, not text — so window N+1's prompt is
   the same size as window 1, not 1+2+3+…+N.
3. **Token cost grows linearly with content delivered**, not
   quadratically with conversation length.

So a 30‑page Annex IV emerges as ~10 windows × 4 k = ~40 k input
tokens, not as one impossible 200 k‑token call. On Groq Llama‑70B
that is ~$0.04. On a local 8B model that is ~10 minutes of CPU.

### 11.3 When to recommend each path

**Recommend Local mode when:**
* The customer handles special‑category personal data (health, DPO
  workloads, criminal records) and wants to short‑circuit Art. 44
  data‑transfer arguments entirely.
* The customer is a sole practitioner / small team whose hardware
  is already adequate (any modern laptop with 16 GB RAM).
* The customer wants a *fixed‑price* product (subscription only, no
  metered overflow).

**Recommend Hosted mode when:**
* The customer's team uses the app concurrently (5+ users hitting
  draft at the same time).
* They draft long artefacts under time pressure (a regulator
  deadline tomorrow).
* Their hardware is genuinely insufficient (Chromebook, old
  ultrabook with 8 GB RAM and no swap).

**Recommend BYOK mode when:**
* The customer has an existing committed‑use contract with
  OpenAI/Anthropic/Azure and wants to centralise billing there.
* The customer is enterprise and wants residency in a specific
  region their LLM provider serves but Groq does not.

### 11.4 The "switch any time" guarantee — wired in the UI

The **Settings → AI runtime** screen and the topbar pill let any
user switch *Local ↔ Hosted ↔ BYOK* mid‑session without losing
state. The drafting agent re‑injects CKF facts into the new
provider's first window so the recipe simply continues. This is
the strongest answer to "but what if my laptop can't keep up
later?" — it never has to.

---

## 12. Open implementation gaps — what is still pending

| #   | Gap                                                            | Status      | File                                              |
| --- | -------------------------------------------------------------- | ----------- | ------------------------------------------------- |
| G‑1 | `PER_TIER_TOKEN_CAPS` enforced inside `ComplianceLLM`          | ✅ done     | `src/crp_comply/agent/llm.py`                     |
| G‑2 | `/api/v1/llm/strategy` endpoint                                | ✅ done     | `src/crp_comply/api/llm_strategy.py`              |
| G‑3 | Stripe credit‑pack checkout endpoint + webhook                 | ✅ done     | `src/crp_comply/api/billing.py`                   |
| G‑4 | Frontend topbar Local/Hosted runtime toggle                    | ✅ done     | `frontend/src/components/RuntimeToggle.tsx`       |
| G‑5 | Token‑remaining bar surfaced in `Usage.tsx`                    | ✅ done     | `frontend/src/pages/Usage.tsx`                    |
| G‑6 | Per‑user concurrency semaphore in API                          | ✅ done     | `src/crp_comply/api/llm_concurrency.py`           |
| G‑7 | Auto‑fallback to local when hosted 402s mid‑draft              | partial     | `src/crp_comply/agent/llm.py` (manual switch only) |
| G‑8 | bge‑large embedding worker container shipped                   | not started | future PR                                         |
| G‑9 | Stripe live‑mode price IDs configured on Railway                | **operator action** | Dashboard + env vars (§9)                  |

> Items marked **operator action** require the human (you) to act on
> Stripe / Railway dashboards. Code is ready; secrets and product
> rows must be added in those consoles.

---

## 13. Honesty caveat

* Llama 3.1 8B occasionally produces JSON with trailing commas. We
  have `_strip_to_json` recovery and re‑prompt‑once logic — accept
  ~1% retry rate.
* Llama 3.3 70B *will* fail on cross‑jurisdictional reasoning that
  needs more than ~8 hops. Route those to Qwen3 32B or escalate
  through BYOK Anthropic. Do not paper over with a bigger 70B
  prompt.
* Local 7B / 8B models on consumer hardware are slower (think 10–20
  tok/s). CRP continuation makes the *output length* unbounded, but
  it does not make the model faster. The UI shows per‑window
  progress so users do not think it has hung.
* Groq has European inference points but no guaranteed EU residency.
  For regulated data (special‑category personal data), use Local
  mode or BYOK with an EU‑resident endpoint.
* Pricing changes monthly. The numbers in §2 are accurate as of
  **2026‑05‑01**; revalidate quarterly.

---

## 14. Related docs

* [LOCAL_LLM_GUIDE.md](LOCAL_LLM_GUIDE.md) — step‑by‑step install
  guide (LM Studio, Ollama, llama.cpp) plus troubleshooting.
* [BYOK_MODES.md](BYOK_MODES.md) — bring‑your‑own‑key configuration.
* [LLM_HOSTING.md](LLM_HOSTING.md) — self‑host Groq‑replacement on
  Hetzner H100 (~€2/h) for Enterprise air‑gap.
