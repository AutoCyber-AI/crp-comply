# CRP Comply — Strategic Redesign & Monetisation

**Status:** Draft v1 — April 2026
**Author:** Constantinos Vidiniotis
**Purpose:** Reset product direction, fix monetisation, ship a logged-out funnel, ship LLM-powered intelligence without losing revenue.

---

## 1. What CRP Comply Actually Sells

**Not the proxy.**
**Not the LLM.**
**Not the audit logs.**

**We sell PROOF — tamper-evident, regulator-ready evidence that every LLM interaction in a company's AI system complied with the EU AI Act, GDPR, and equivalent regulations.**

The value is:
- Protection against fines up to **€35M or 7% of global annual revenue** (EU AI Act Art. 99)
- Protection against fines up to **€20M or 4% of global revenue** (GDPR Art. 83)
- A legally defensible audit trail in case of investigation
- The ability to answer "show me your AI governance" in due diligence, procurement, insurance
- Compliance-as-a-service for teams without a compliance officer

**This reframing matters** because it unlocks business model options the proxy-centric framing hid.

---

## 2. Current Monetisation — Honest Assessment

### What Exists
| Tier | Price | Problem |
|---|---|---|
| Free | $0/mo | 2 features given away. No login required. No quota limit. No funnel. |
| Pro | $149/mo | Flat fee regardless of volume. A 100-call/mo user pays same as a 10M-call/mo user. Leaves money on the table at the top AND prices out the bottom. |
| Enterprise | $699/mo | Arbitrary gap. No clear trigger to upgrade from Pro. |
| Cloud | $1,999/mo | Vague "managed service" — no crisp value delta. |

### What's Wrong
1. **No usage-based lever.** A compliance product's cost scales with the customer's AI traffic. Flat tiers misalign our revenue with the customer's actual risk surface.
2. **No funnel.** Anonymous users get the free tier — no signup pressure, no lead capture, no email.
3. **Feature gates disguise the real value.** We hide DPIA behind Pro — but DPIA is a 1-time generation task. The real recurring value is *every-call compliance*.
4. **Pricing page is buried inside the authenticated app.** Prospects never see it.
5. **No value proposition on the landing page.** There is no landing page.

### What Prospects Actually Buy
| Buyer | What they pay for | Budget tolerance |
|---|---|---|
| Solo AI builder / indie hacker | Proof they're not breaking the law. Something to show investors / procurement. | $20–50/mo |
| Growing AI startup (seed-Series A) | "Compliance ready" sticker. DPIA they can attach to contracts. | $100–300/mo |
| Regulated mid-market (fintech, healthtech) | Full audit trail, exportable reports for regulators. SSO. | $500–1,500/mo |
| Enterprise | Dedicated infrastructure, SLA, signed certificates, compliance officer relationship. | $3K–15K/mo |

---

## 3. Proposed New Pricing Model

**Core principle: usage-based included quota + overage, combined with capability tiers.**

| Tier | Price / month | Included audited calls | Overage | Who it's for |
|---|---|---|---|---|
| **Free / Self-Audit** | $0 | 100 calls | — (hard cap) | Evaluators, solo builders, funnel |
| **Starter** | **$29** | 5,000 calls | $0.008/call | Indie devs, early-stage AI products |
| **Professional** | **$149** | 50,000 calls | $0.005/call | Growing teams, regulated-adjacent |
| **Business** | **$499** | 250,000 calls | $0.003/call | Scale-ups, regulated industries |
| **Enterprise** | **From $1,999** | 1M+ calls custom | Negotiated | Banks, healthcare, large SaaS |
| **Cloud / On-Prem** | Custom | Unlimited | — | Air-gapped, regulated, annual contracts |

### Feature Distribution (not tier-locked — value-locked)

**Everyone gets (even Free):**
- Risk classification tool
- PII scanning on every call
- Prompt injection detection
- Audit log of every call (with tamper-evident chain)
- Basic compliance report generation

**Starter and up:**
- DPIA generation
- Transparency declarations
- Full compliance reports with article citations
- PDF export
- API key management
- Email support

**Professional and up:**
- **CRP-Amplified LLM Analysis** (hosted — we run Claude/GPT/Llama with CRP Protocol for richer reports)
- Technical documentation generator
- Evidence packs for regulators
- Data lineage tracking
- Multi-user (up to 5)

**Business and up:**
- SSO / SAML
- Custom compliance frameworks
- Art. 17 erasure workflows
- Art. 30 processing records
- Retention policy enforcement
- Dedicated hosted LLM tenancy
- 10+ users

**Enterprise:**
- Signed certificates (for regulator submission)
- SLA with credits
- Custom integrations
- Dedicated compliance advisor
- Quarterly compliance reviews
- White-label option

### Why This Works
- **Funnel exists:** Free tier requires signup, captures email, gives hard-cap pressure.
- **Low friction entry:** $29 Starter lets indies buy without approval chains.
- **Revenue scales with value:** A high-traffic customer pays proportionally.
- **Clear upgrade triggers:** Hit quota → upgrade. Need SSO → Business. Need certificates → Enterprise.
- **No-code-change upsell:** Users can't bypass the quota — every audited call is metered.

---

## 4. LM Studio / Local LLM Strategy (Without Losing Revenue)

### The Problem
Railway can't reach `localhost:1234`. But **we want local-LLM users** because:
- They're security-conscious (often regulated industries = our buyers)
- They already pay zero per-inference (cost-sensitive, price-elastic to us)
- They're a growing segment (Llama 3, Mistral, DeepSeek on consumer GPUs)

### The Wrong Answer
"Publish an SDK so they can audit locally" — this gives away the core product.

### The Right Answer: SDK + Cloud Split

Ship **`crp-comply-sdk`** (Python + TypeScript). The SDK:

1. Wraps the user's LLM call (any provider, including local LM Studio)
2. Sends the **audit record** (prompt, response, metadata) to CRP Comply Cloud via their API key
3. CRP Comply Cloud:
   - **Counts it against their quota** (monetisation)
   - **Stores it in tamper-evident chain** (core value)
   - **Runs PII/injection scanning server-side** (value add)
   - **Feeds it into compliance reports** (core value)

```python
# User's code
from crp_comply import ComplyClient
from openai import OpenAI  # pointing at LM Studio

client = ComplyClient(api_key="crc_live_...")
llm = OpenAI(base_url="http://localhost:1234/v1", api_key="lm-studio")

with client.audit(system_id="my-chatbot", user_ref="user_123") as audit:
    response = llm.chat.completions.create(
        model="llama-3.1-70b",
        messages=[...]
    )
    audit.record(prompt=messages, response=response)
    # SDK automatically:
    # - hashes & signs the exchange
    # - POSTs to api.comply.crprotocol.io/v1/audits
    # - counts against quota
    # - returns if quota exceeded
```

**Monetisation intact because:**
- Every `audit.record()` is a billable event (counts toward their quota)
- Compliance reports can **only be generated from audits stored in CRP Comply Cloud**
- Regulators won't accept unsigned local logs — they need our chain
- Quota exceeded = SDK fails closed OR allows through in "unaudited" mode (clearly marked in reports)

**Bonus:** The SDK also becomes the recommended integration path for cloud LLMs (drop-in replacement for the proxy). Some users prefer SDK over proxy for latency reasons.

### The Three Integration Paths (all charge the same per-call)
1. **Proxy mode** — drop-in replacement for OpenAI base URL. Best for prototypes.
2. **SDK mode** — wrap your existing client code. Best for local LLMs or latency-sensitive apps.
3. **Webhook mode** — batch-post audit records from your own logs. Best for migrating existing systems.

---

## 5. LLM-Powered Report Intelligence (Monetised)

### The Problem
Current reports are rule-based. Same system category → similar output. Feels generic.

### The Fix: CRP-Amplified Compliance Analyst

Build `compliance_analyst.py` module that:
1. Ingests: user's system description (free text) + risk classification + audit stats
2. Retrieves: relevant EU AI Act articles, GDPR articles, ISO 42001 clauses (RAG over vendored text)
3. Uses **CRP Protocol** to structure multi-step reasoning (this is where we dogfood our own tech)
4. Generates: tailored analysis citing specific Annexes, articles, paragraphs

### Monetisation: Two Paths
**Path A — BYOK (Starter / Professional):**
- User provides their own LLM credentials (OpenAI, Anthropic, Azure, local via SDK)
- We run the CRP Protocol amplification layer + RAG
- User pays for their own inference
- **We charge for the analysis engine** (included in tier)

**Path B — Hosted LLM Intelligence (Professional / Business):**
- We run Claude 3.5 Sonnet / GPT-4o / Llama 70B on Bedrock
- CRP Protocol amplification runs against it
- User doesn't need to configure anything
- **Higher margin for us — we bundle inference cost into tier price**
- Professional gets shared capacity. Business gets dedicated tenancy.

### Differentiation Message
> *"CRP Comply is the only compliance platform that uses the Context Relay Protocol to amplify LLM reasoning for regulatory analysis. Our reports cite specific EU AI Act articles, Annex mappings, and GDPR cross-references because our analyst engine is itself CRP-powered."*

This is a real technical moat — competitors using vanilla LLM wrappers produce generic output. CRP Protocol gives us structured multi-step reasoning without the brittleness of chain-of-thought prompts.

---

## 6. UI/UX Redesign — Phased

### Phase 1 (IMMEDIATE): Public Funnel
- **Split routing**: `/` (public marketing) vs `/app/*` (authenticated)
- **Landing page** (`/`):
  - Hero: "AI systems get fined up to €35M. Here's how to prove you're compliant."
  - Problem statement (EU AI Act timeline, GDPR overlap, fine examples)
  - Value proposition (tamper-evident, article-cited, regulator-ready)
  - Free Risk Classifier CTA (the hook)
  - Pricing preview
  - Sign-up CTA
- **Free Risk Classifier** (`/free-assessment`):
  - Single text field: "Describe your AI system"
  - Plus optional: category dropdown, jurisdiction
  - Returns: Risk level (Prohibited / High / Limited / Minimal) + article citations + fine exposure estimate + CTA: "Generate full compliance pack — sign up free"
  - Anonymous-capable, rate-limited by IP (prevents abuse)
  - Results emailed if they provide email (lead capture)
- **Pricing page** (`/pricing`):
  - Public, SEO-friendly
  - New tier structure
  - FAQ section
  - Comparison table
  - Enterprise contact form

### Phase 2 (NEXT): Settings & Tier Visibility
- `/app/settings` page showing:
  - Current tier + subscription status
  - Quota usage bar ("12,450 / 50,000 calls used this month")
  - API keys (create/revoke/copy)
  - Stripe billing portal link
  - LLM provider configuration
  - Team members (if Business+)
  - Export data (Art. 15 / Art. 20 support — we practice what we preach)

### Phase 3 (AFTER REVENUE): Client SDK
- Publish `crp-comply` Python package to PyPI
- Publish `@crp-comply/sdk` to npm
- Docs site at `docs.comply.crprotocol.io`
- Quickstart: 5 lines of code to audit LM Studio

### Phase 4: Compliance Analyst (LLM-Powered Reports)
- Vendor EU AI Act text + GDPR + ISO 42001 (chunked, embedded)
- `compliance_analyst.py` module using CRP Protocol
- Toggle in report UI: "Generate with AI Analyst" (Starter = BYOK, Professional+ = hosted)
- Article citations rendered as hyperlinks in PDF output

### Phase 5: UI Polish
- Design system upgrade (typography scale, proper spacing, motion)
- Rich form inputs (multi-step wizards, contextual help)
- Report rendering with branded PDF export
- Dashboard visualizations (compliance score, risk trend, quota gauge)

---

## 7. Decision Log

| Decision | Rationale |
|---|---|
| Drop the $699 Enterprise tier, replace with $499 Business + $1999+ Enterprise | $699 was a pricing dead zone — too cheap for enterprise buyers, too expensive for mid-market. |
| Starter at $29 | Captures indie/solo market; removes "nothing between Free and $149" gap. |
| Usage quota on every tier (including Free hard cap) | Aligns revenue with customer's actual AI traffic; enforces upgrade pressure. |
| SDK, not just proxy | Supports local LLMs without bypassing monetisation. |
| CRP Protocol inside the compliance analyst | Real differentiation + dogfooding our own tech. |
| Free Risk Classifier as the funnel | Low commitment hook; instant perceived value; naturally triggers "what else do I need?" |
| Split routing (public vs app) | Fixes the biggest current UX failure: no front door. |

---

## 8. Revenue Model Math

**Year 1 conservative assumptions:**
- 500 free signups/mo from funnel (ads + organic)
- 3% convert to Starter → 15 Starters/mo × $29 = $435/mo → $5,220 ARR per monthly cohort
- 0.5% convert to Professional → 2.5/mo × $149 = $372/mo
- 2 Business deals in year 1 × $499 × 12 = $11,976 ARR
- 1 Enterprise deal year 1 × $2,000 × 12 = $24,000 ARR

**Year 1 exit ARR target:** ~$80K–120K
**Year 2 with 10× funnel volume and expansion revenue:** ~$500K–1M ARR

---

## 9. What We Are NOT Doing

- ❌ Free tier with unlimited calls (no pressure to upgrade)
- ❌ Open-source giveaway of the audit engine (that IS the product)
- ❌ Pure usage-based pricing (creates budget anxiety; flat included quota works better)
- ❌ Separate mobile app
- ❌ Multi-language UI (English only for v1)
- ❌ Building our own LLM (we amplify others' via CRP)

---

## 10. Success Metrics

- **North Star:** Audited calls per month (leading indicator of both usage and revenue)
- **Funnel:** Free Risk Classifier → Signup conversion rate
- **Activation:** First billable audited call within 7 days of signup
- **Expansion:** % of paid accounts upgrading tier within 6 months
- **Retention:** Monthly churn < 5%
