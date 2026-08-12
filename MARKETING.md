# CRP Comply — Market Brief

**One-liner:** *The compliance engineering platform for AI builders —
turn the EU AI Act, ISO 42001 and the GDPR from a legal liability into
a one-click signed evidence pack.*

**Status:** Investor / partner / design-partner facing.
**Last updated:** 2026-04-27.
**Author:** Constantinos Vidiniotis, AutoCyber AI Pty Ltd.

---

## Executive summary (one page)

| | |
|---|---|
| **What** | Compliance-engineering SaaS that turns AI regulations into signed, regulator-grade evidence packs in 30 minutes instead of 4–9 months. |
| **Why now** | EU AI Act enforcement starts **2 Aug 2026** with fines up to **7 % of global turnover**. ISO 42001 is becoming a procurement gate in enterprise RFPs. ~15–40k high-risk EU AI systems in scope, almost none are ready. |
| **For whom** | AI product builders (10–500 engineers) and the GRC/legal/security functions in regulated industries who buy from them. |
| **How (the moat)** | (1) Canonical regulation corpus, re-ingested every release, every output cites article + clause. (2) Tamper-evident Merkle evidence chain. (3) Bring-your-own-key by default — we never see prompts, so we sell into banks, hospitals, defence. None of the incumbents (OneTrust / Drata / Vanta / Credo / Fairly / Holistic) have all three. |
| **Business model** | $0 Free → $49 Starter → $499 Scale → Enterprise (custom). Revenue is subscription + optional managed-LLM convenience add-ons. BYOK / local-LLM is the default, so customers control their own inference cost. |
| **Today** | Production at `comply.crprotocol.io`. 30 deliverable recipes shipped, 450 backend tests passing, full Article 28 DPA published, security headers + AES-256-GCM at-rest, BYOK Modes A/B/C operational. |
| **Ask** | Seed conversations sized for 18-month runway to AI Act enforcement + first 10 Enterprise logos; or 3 Enterprise design-partner slots at preferential pricing. |

---

## 1. The problem

> AI regulation moved from "coming soon" to "shipping fines" in 18 months.

| Regulation | Status | Maximum penalty |
|---|---|---|
| **EU AI Act** | High-risk obligations enforce **2 Aug 2026** | **7% of global turnover** or €35M |
| **ISO/IEC 42001** | First AI Management System standard; enterprise procurement now requires it | Lost deals (no fine, but a hard gate) |
| **GDPR Art. 35 (DPIA) for AI** | EDPB Guidelines 4/2024 — every consequential AI system needs a DPIA | **4% global turnover** or €20M |
| **NIS2** | In force; AI systems in critical sectors must show resilience evidence | €10M or 2% turnover |
| **UK AI Bill** | Expected 2026; existing UK GDPR + ICO enforcement already active | £17.5M or 4% turnover |
| **US — Colorado AI Act, NYC Local Law 144, EEOC** | Already enforcing | Civil penalties + class action exposure |

**Today's pain point for AI builders:**
- A typical mid-market AI product company has **0–1 compliance hires** and **5–50 engineers**.
- A single ISO 42001 readiness engagement runs **€80–250k** with a Big Four firm and takes **4–9 months**.
- A DPIA + Annex IV technical-documentation pack costs **€20–60k** per AI system per year.
- The work is highly repetitive (the same regulations apply to every AI system), but every consultant re-does it from scratch.

**Result:** AI teams ship without compliance, then panic in Q3 2026 when EU enforcement starts. We solve that.

---

## 2. The solution

CRP Comply is a **compliance-engineering platform** — not a checklist tool, not a GRC dashboard, not a chatbot. It produces **deterministic, signed, regulator-grade artefacts** from a 30-minute structured interview.

Three primitives no competitor has all of:

1. **Canonical regulation corpus** — full text of EU AI Act, GDPR, ISO 22989/23894/42001, NIST AI RMF (Core + GenAI), NIS2, OECD AI Principles, CoE AI Convention, UK White Paper. Re-ingested on every release; every output cites the exact article and clause.
2. **Tamper-evident evidence chain** — every fact extracted, every clarification answer, every artefact draft is hashed into a Merkle chain (`data/audit/`). Auditors get cryptographic proof of *when* you knew *what*.
3. **BYOK by default** — customers bring their own LLM key (OpenAI / Anthropic / Azure / Bedrock / local Llama). We never see prompts in cleartext, which means we can sell into regulated industries (banks, hospitals, defence) where competitors can't.

On top of those three, we ship **30 deliverable recipes** (DPIA, FRIA, ISO 42001 SoA, NIST RMF Profile, Annex IV Tech Docs, Risk Register, RoPA, Incident Response, Transparency Notices, GPAI Tech Docs, …) and an agentic interview that asks only what's needed.

---

## 3. Market & timing

**Why now:** The EU AI Act compliance cliff hits **August 2026**. Every provider and deployer of a "high-risk" AI system in the EEA must have:
- Risk management system (Art. 9)
- Data governance evidence (Art. 10)
- Technical documentation (Art. 11 + Annex IV)
- Logging and monitoring (Art. 12 + 19)
- Transparency to deployers (Art. 13)
- Human oversight (Art. 14)
- Conformity declaration + CE mark (Art. 47–48)

There are an estimated **15,000–40,000** EU-touching AI products that fall under "high-risk" (CV-screening tools, credit-scoring, medical-device AI, education assessment, law-enforcement support, critical-infrastructure control, biometric ID). Few of them are ready.

**TAM:** Every AI provider/deployer in EEA + UK + AU + sectors of US (Colorado, NYC, finance, healthcare). We model **$8.5B by 2028** for AI-specific GRC spend (sub-segment of the $58B GRC market).

**SAM:** Mid-market AI builders (10–500 engineers) who can't afford Big Four but have to comply. ~12,000 companies globally. ARPU floor $599/mo Enterprise → **$86M ARR ceiling at 1% penetration.**

**SOM (12-month):** 250 paying tenants across Starter ($49) and Scale ($499) → **~$780k ARR**, plus 5–10 Enterprise design partners at $1.5–5k/mo → **+$120k ARR**. Defensibility comes from canonical-corpus updates and recipe expansion network effects, not lock-in.

---

## 4. Differentiators

| Capability | CRP Comply | Big Four consulting | OneTrust / Drata | "AI compliance" startups |
|---|---|---|---|---|
| Regulator-grade output | ✅ Cited, signed | ✅ Bespoke | ⚠️ Templates | ❌ Mostly chat |
| Cryptographic audit chain | ✅ Built in | ❌ Word docs | ❌ Logs only | ❌ |
| BYOK / data-sovereign | ✅ Default | ✅ (manual) | ⚠️ SaaS only | ❌ Vendor LLM |
| Time to first artefact | **30 min** | 4–9 months | Days–weeks | Hours |
| Marginal cost per artefact | **$2–25** | $20k–60k | $0 (DIY effort) | $50+ |
| AI Act / ISO 42001 / NIST RMF coverage | ✅ All three | ✅ For €€€€ | ⚠️ AI Act partial | ⚠️ Usually one |
| Open-source SDK + worker | ✅ Apache-licensed parts | ❌ | ❌ | ❌ |

---

## 5. Tech stack & integrations

CRP Comply is built on (and integrates with — *not* a marketing partnership unless explicitly noted):

- **Hosting:** Railway (production app); Cloudflare (CDN + WAF + R2 backups).
- **Auth:** [Clerk](https://clerk.com) — SSO, MFA, organisations. We are evaluating Clerk Pro for organisation-level B2B features.
- **Payments & metered billing:** [Stripe](https://stripe.com) — Subscriptions API + Billing Meter API for usage-based pricing.
- **Database / persistence:** filesystem-first (JSONL + SQLite) by design — survives any hosting move; Cloudflare R2 for nightly DR backups (60-day rolling).
- **LLM providers (BYOK / Managed):** OpenAI, Anthropic, Azure OpenAI Services, AWS Bedrock, Groq, Together.ai, Fireworks, plus self-hosted vLLM / Ollama / LM Studio for sovereign deployments. See [LLM_HOSTING.md](docs/LLM_HOSTING.md).
- **Embeddings & RAG:** Sentence-Transformers + custom hybrid retriever over canonical corpus.
- **Underlying intelligence layer:** [CRP Protocol](https://crprotocol.io) (open core; AutoCyber AI proprietary extensions).

> **A note on the word "partner":** in this document we use *"built on", "integrates with", and "powered by"*. We do not claim a marketing partnership with any of the above unless we have a counter-signed partner agreement. Where we are a member of an official developer programme (e.g. Stripe Verified Partner Program, Microsoft for Startups), we will say so explicitly once the enrolment is confirmed.

---

## 6. Product surface

- **Web app** — `comply.crprotocol.io`, React + Tailwind, deployed on Railway.
- **REST API** — FastAPI; OpenAPI 3.1 spec auto-generated.
- **Python SDK** — `pip install crp-comply-sdk` (open source, Apache-2.0).
- **CLI worker** — `crp-comply worker --lmstudio …` for air-gapped inference (BYOK Mode C).
- **Compliance Reports + Vault** — every artefact PDF-rendered, hashed, and stored in customer-controlled storage.

Backend test suite: **450 tests passing**. Security: bandit clean (0 medium/high), CSP + HSTS + COOP/CORP headers shipped, AES-256-GCM at-rest encryption for BYOK keys.

---

## 7. Pricing

| Tier | Price | Who it's for | LLM | Headline limits |
|---|---|---|---|---|
| **Free** | $0 | Try the engine, rule-based assessment | Local / BYOK | 1 system, 100 calls/mo |
| **Starter** | **$49 / mo** | Solo founder, single AI product | Local / BYOK (Mode A/B/C) | 1 user, 5 reports/mo |
| **Scale** | **$499 / mo** | 5–50-engineer AI company | Local / BYOK / optional managed | 10 users, 50 reports/mo |
| **Enterprise** | **Custom** | Regulated industry, EU residency | Managed dedicated *or* self-host | Custom quota; custom DPA |

Add-ons: usage-based metering for optional managed-LLM tokens via Stripe Billing Meter; per-Compliance-Report overages above tier limits. Managed tokens are a convenience add-on — most customers run BYOK or local LLMs at their own cost.

---

## 8. Traction & validation

- **30 deliverable recipes** spanning EU AI Act (10), GDPR (2), ISO 42001 (8), NIST AI RMF (1), and supporting docs (9).
- **13 deterministic eval cases** with CI-enforced ≥95% pass rate.
- **450 backend tests** — full coverage of agent orchestration, RAG, scrapers, audit chain, billing, and tenant isolation.
- **Full Article 28 GDPR DPA** shipped at `/dpa` — SCC Module 2, UK Addendum B1.0, Swiss FADP, Australian APP 8 references included.
- **Production-ready security posture** — HSTS, CSP, COOP/CORP, X-Frame-Options=DENY, AES-256-GCM at-rest, tamper-evident audit chain.

---

## 9. Roadmap (next 90 days)

1. **Frontend draft surface collapse** — merge AgentChat + Workspace into a single Draft.tsx (Gap 2 UI).
2. **Eval suite expansion** to ≥20 cases across all four regulations.
3. **Streaming SSE** to make the agent feel real-time.
4. **Long-poll worker** for SDK Mode C completion.
5. **Stripe Billing Meter live cutover** for Pro and Enterprise tiers.
6. **First Enterprise design partner** — target a regulated AI provider in EU / UK.

---

## 10. The ask (for investors / design partners)

- **Investors:** This is a regulatory-cliff timing play with capital-efficient unit economics (subscriptions + optional managed-LLM add-ons; local/BYOK inference keeps COGS low), enterprise moat (cryptographic evidence chain + canonical corpus + BYOK), and capital efficiency (single founder shipped the full stack). We are open to seed conversations sized around 18-month runway to AI Act enforcement + 10 Enterprise logos.
- **Design partners:** Three Enterprise slots open at preferential pricing in exchange for case study, integration feedback, and one quarterly call. Best fit: regulated-industry AI builders (fintech, health-tech, EdTech) with ≥1 high-risk EU AI Act system.
- **Channel partners:** Big Four / boutique consultancies who want to keep the strategic advisory work but offload artefact production. We white-label.

**Contact:** [contact@crprotocol.io](mailto:contact@crprotocol.io) · [comply.crprotocol.io](https://comply.crprotocol.io)

---

## 11. Buyer personas

We sell to **four** distinct buyers. The same artefact (e.g. a DPIA) is procured for four different reasons:

### 11.1 The CISO at a regulated AI customer
- **Pain:** vendor onboarding sends 80-question security questionnaires; 15 of those questions are now AI-specific (model documentation, training-data lineage, red-team results, human oversight). Every "no" extends the sales cycle by 6–12 weeks.
- **Buying trigger:** vendor's CISO blocks an AI-supplier deal because Annex IV evidence is missing.
- **Wins on:** *"Drop a CRP Comply Annex IV pack into the vendor questionnaire and unblock the deal in a day."*
- **Champions:** Head of Vendor Risk, third-party-risk-management (TPRM) lead.

### 11.2 The DPO at the AI builder
- **Pain:** EDPB Guidelines 4/2024 effectively require a DPIA for every consequential AI system. Their team of 1–3 DPOs cannot personally write 12 DPIAs in a quarter.
- **Buying trigger:** the engineering team asks "do we need a DPIA for this?" for the fourth model in two months.
- **Wins on:** the canonical-corpus + clarification-interview pattern — the DPO reviews and signs rather than drafts.
- **Champions:** internal Privacy Counsel, compliance manager.

### 11.3 The Head of AI / VP Engineering
- **Pain:** the AI Act puts the engineering team on the hook for technical documentation, logging, and post-market monitoring. They have no GRC budget and no template library. Each model release is a fire drill.
- **Buying trigger:** product leadership commits to ship a high-risk AI feature in the EEA before Aug 2026.
- **Wins on:** SDK + CLI worker — ergonomically close to where engineers already live (CI/CD, GitHub).
- **Champions:** ML platform lead, AI safety engineer.

### 11.4 The GRC manager / Internal Audit
- **Pain:** ISO 42001 is showing up in customer security questionnaires. They need a Statement of Applicability, AI risk register, and management-review evidence. Their existing GRC tool (Drata / Vanta / Hyperproof) doesn't cover AI controls.
- **Buying trigger:** an enterprise customer asks for ISO 42001 certification within 12 months.
- **Wins on:** SoA + risk register + control-evidence mapping in a regulator-friendly format.
- **Champions:** Internal Audit, GRC tooling owner.

---

## 12. Competitive deep-dive (feature × competitor matrix)

> Updated 2026-04. Sources: vendor public docs, public pricing pages, public investor decks. We do not name design partners or quote private benchmarks.

### 12.1 The full landscape

| Vendor | Category | AI-Act coverage | ISO 42001 SoA | NIST AI RMF | DPIA grounded in EDPB | BYOK | Cryptographic audit chain | Open SDK | Pricing entry |
|---|---|---|---|---|---|---|---|---|---|
| **CRP Comply** | AI-native compliance engineering | ✅ All Annex IV | ✅ | ✅ Core + GenAI | ✅ Cited to clause | ✅ Default | ✅ Merkle chain | ✅ Apache-2.0 | $49 |
| **OneTrust AI Governance** | GRC suite extension | ⚠️ Templates | ⚠️ Mapping only | ⚠️ Crosswalk | ❌ Generic | ❌ | ❌ | ❌ | $$$$ enterprise |
| **Drata AI Governance** | SOC2 → AI extension | ⚠️ Partial | ⚠️ Beta | ⚠️ Crosswalk | ❌ | ❌ | ❌ | ⚠️ Connectors | $$$ |
| **Vanta** | SOC2/ISO trust centre | ❌ Roadmap | ⚠️ Beta | ❌ | ❌ | ❌ | ❌ | ⚠️ API | $$$ |
| **Credo AI** | AI governance hub | ✅ Library | ⚠️ | ✅ | ❌ | ❌ | ❌ | ❌ | $$$$ |
| **Fairly AI** | Model-risk dashboard | ⚠️ | ❌ | ⚠️ | ❌ | ❌ | ❌ | ❌ | $$$ |
| **Holistic AI** | AI risk & assurance | ✅ | ⚠️ | ✅ | ⚠️ | ❌ | ❌ | ❌ | $$$$ |
| **Big Four (Deloitte, PwC, EY, KPMG)** | Bespoke advisory | ✅ Custom | ✅ Custom | ✅ Custom | ✅ Custom | ✅ Manual | ❌ | ❌ | €80–250k engagement |

### 12.2 Where we win against each

| Competitor | Their strength | Our wedge |
|---|---|---|
| **OneTrust** | Existing GRC footprint, procurement relationships | Faster time-to-artefact (30 min vs. weeks), cited-to-clause output, BYOK for regulated industries. We deliberately do **not** try to replace privacy-rights workflow — we slot underneath. |
| **Drata / Vanta** | Engineer-friendly automation for SOC2/ISO 27001 | They were not built around regulation text; their AI module is a control-mapping crosswalk. We ship the actual artefact. We are a "fits next to Drata" play, not a "rip-and-replace". |
| **Credo / Fairly / Holistic** | AI-native, often academic provenance | None ship a tamper-evident evidence chain or BYOK by default; pricing is enterprise-only ($60k+). We undercut on TTV and price floor. |
| **Big Four** | Trust, regulatory relationships, custom work | They lose money on artefact production. We white-label the artefacts so they keep the strategic advisory margin and offload the repeatable work. **Channel play, not competitor.** |

### 12.3 What we do *not* do

- We do not replace SOC2 / ISO 27001 automation (Drata / Vanta own that — we integrate).
- We do not do model monitoring / drift detection (Fiddler / Arize / WhyLabs own that).
- We do not do data discovery / DSAR fulfilment (BigID / OneTrust DSAR own that).
- We do not give legal advice. Every artefact carries a "review by qualified counsel" notice.

---

## 13. ROI model (worked example)

> Below is a public, reproducible model — every input is conservative.

### 13.1 Cost of non-compliance

A mid-market AI company (€50M revenue, single high-risk EU AI system, 25 engineers):

| Risk | Probability (12-month) | Impact | Expected loss |
|---|---|---|---|
| Lost enterprise deal because Annex IV pack missing | 40 % | €350k ACV × 12-week delay → 25 % churn risk | €87.5k |
| GDPR fine for missing/inadequate DPIA on AI processing | 5 % | 1.5 % of global turnover (mid-band Art. 83) | €37.5k |
| AI Act fine post-Aug 2026 (high-risk non-conformity) | 8 % | 3 % of global turnover (mid-band Art. 99) | €120k |
| Internal audit / Big Four readiness gap-fill | 60 % | €120k engagement | €72k |
| **Total expected annualised loss** | | | **€317k / year** |

### 13.2 Cost of CRP Comply Pro

- License: $199/mo × 12 = **~€2.2k / year**
- BYOK LLM cost (15 reports, ~€1.5 each): **~€22 / year**
- Internal time to review/sign artefacts: 4 hours per artefact × 15 = 60h × €120/h = **€7.2k / year**
- **Total: ~€9.4k / year**

### 13.3 ROI

`(€317k − €9.4k) / €9.4k = 32× return on year-one Pro spend.`
Even ignoring fines (probability-weighted), the **vendor-questionnaire deal-unblock alone (€87.5k expected)** justifies the cost ~9× over.

---

## 14. Go-to-market

### 14.1 Channel strategy

| Channel | Motion | Status |
|---|---|---|
| **Self-serve PLG** | Free tier → Starter ($49) auto-conversion driven by content + SEO + the "Free Risk Check" funnel at `/free-assessment` | Live |
| **Inbound from Big Four & boutique consultancies** | White-labelled artefact production behind their advisory; we power the "factory floor" | In design |
| **Enterprise direct (founder-led)** | Outbound to 200 named accounts (high-risk EU AI providers), 3 design-partner slots open | In progress |
| **Marketplaces** | Listed in Stripe App marketplace, AWS Marketplace, Microsoft Azure Marketplace (post-MVP, target Q3) | Planned |
| **Partner integrations** | Drata, Vanta, OneTrust connectors that pull SOC2/ISO27001 evidence and map it onto AI Act + ISO 42001 | Planned |

### 14.2 Phased GTM

1. **Phase 1 — Design partners (now → 90 days)**: 3 enterprise logos at preferential pricing in exchange for case study + product feedback. Founder-led sales.
2. **Phase 2 — Mid-market self-serve (Q3)**: scale Scale tier through SEO content, free-assessment funnel, partner referrals. Target 250 paying tenants.
3. **Phase 3 — Enterprise expansion (Q4 → Aug 2026)**: scale Enterprise via Big Four channel + AWS/Azure marketplaces. Target 25 logos before AI Act enforcement.
4. **Phase 4 — Post-enforcement (Aug 2026 →)**: capture the inbound demand spike, expand to UK / AU / Canada / sectoral US (Colorado, NYC).

### 14.3 Content & SEO plan

- **Pillar pages**: "EU AI Act compliance guide", "ISO 42001 readiness checklist", "DPIA for AI systems", "Annex IV technical documentation template".
- **Comparison pages**: "vs. OneTrust", "vs. Drata", "vs. Big Four".
- **Free tools**: Risk Check (`/free-assessment`), DPIA template generator, Annex IV outline generator.
- **Distribution**: LinkedIn (founder-led), GRC Engineering Slack, AI Safety Newsletter, MLOps Community.

---

## 15. KPIs and targets

| KPI | Definition | Year-1 target | Year-2 target |
|---|---|---|---|
| **MRR** | recurring revenue at month-end | $32k | $250k |
| **Logos** | unique paying tenants | 250 | 1,500 |
| **Enterprise logos** | tenants ≥ $599/mo | 10 | 50 |
| **CAC (blended)** | sales+marketing spend / new logos | ≤ $300 self-serve, ≤ $4k enterprise | ≤ $500 / ≤ $6k |
| **Payback period** | months to recoup CAC | ≤ 4 self-serve, ≤ 12 enterprise | ≤ 3 / ≤ 9 |
| **NRR** | net revenue retention | ≥ 110 % | ≥ 120 % |
| **Gross margin** | % of revenue after COGS (LLM + hosting) | ≥ 88 % blended | ≥ 90 % |
| **TTV (time to value)** | sign-up → first signed artefact | ≤ 30 min | ≤ 15 min |
| **Activation** | % of free signups that produce ≥ 1 artefact | ≥ 35 % | ≥ 50 % |
| **Eval pass rate** | CI deterministic eval suite | ≥ 95 % | ≥ 98 % |
| **Mean cost per managed report** | OPEX / managed-tier reports | ≤ $4 | ≤ $2 |

---

## 16. Risk matrix

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **EU enforcement delays past Aug 2026** | Low–Medium | Medium (slows demand spike) | Already shipping into ISO 42001 + GDPR demand; UK / AU / US Colorado timelines independent |
| **OneTrust / Drata ship a competing AI module** | High | Medium | Move fast on tamper-evident chain + canonical-corpus depth; channel via consultancies; lean into BYOK angle they cannot match without rearchitecture |
| **Hyperscaler bundling (Azure, AWS, Google)** | Medium | High | Position as data-sovereign / BYOK alternative; integrate as marketplace listing rather than fight; multi-LLM routing keeps us unbundled |
| **LLM provider regression breaks deterministic outputs** | Medium | Medium | CI eval suite (≥95 % pass) gates every release; multi-provider routing + pinned model versions; we cite to clause not to LLM output |
| **Regulator publishes a free template that obviates need** | Low | Medium | Paying customers buy the *signed evidence chain* + *update cadence* + *integration*, not the template itself |
| **Single-founder bus factor** | Medium | High | Open-source SDK + worker means customers can self-serve indefinitely; documentation-first; runbooks under `docs/` |
| **Cloud / hosting outage** | Low | Medium | Filesystem-first persistence + Cloudflare R2 nightly DR backups (60-day rolling); 1-day recovery target |
| **Hallucination in agent output** | Medium (technical) | High (reputational) | All deliverable recipes are deterministic; agent path is opt-in and clearly badged "draft, requires review"; cited-to-clause output |

---

## 17. Investor FAQ

**Q: Why not just use ChatGPT / Claude with a system prompt?**
A: Two reasons. (1) An LLM cannot produce a *cited, tamper-evident* artefact a regulator will accept; the canonical corpus + Merkle chain are the moat, not the LLM. (2) Regulated buyers (banks, hospitals, defence) cannot ship prompts containing personal data to OpenAI. BYOK Mode C lets them run inference on-prem.

**Q: Isn't this a feature, not a company?**
A: The wedge is feature-shaped. The company-shape comes from (a) recurring update cadence — every regulation revision triggers re-ingest + recipe update; (b) cryptographic continuity — once you start your evidence chain with us, switching cost is real; (c) channel — Big Four cannot price-match self-serve.

**Q: What stops OneTrust from copying this?**
A: Architecture. OneTrust is a multi-tenant SaaS built on a centralised database; BYOK + canonical-corpus + Merkle chain require a different design. They will eventually ship a marketing answer; they will not ship a technical answer in the AI Act enforcement window.

**Q: What is the unit economics on the managed LLM tier?**
A: Managed LLM tokens are an optional convenience add-on, not the core margin engine. Median report consumes ~30k input + 4k output tokens. At commodity-routed pricing (Anthropic Haiku / OpenAI 4o-mini class), that is ~$0.05 per report. Most customers run BYOK or local LLMs at their own cost, which keeps platform COGS low and makes the local-first tier economically attractive.

**Q: How defensible is the canonical corpus?**
A: The text itself is public. The defensibility is in (1) the ingestion pipeline (`src/crp_comply/agent/scrapers/`) — re-runs on every regulation revision; (2) the chunk-level provenance (every quote carries `regulation:article:paragraph:line`); (3) the recipe library that *uses* the corpus. Anyone can copy the corpus once; nobody can replicate the recipe library overnight.

**Q: Why is this not a services company?**
A: Because the unit economics of services scale linearly with headcount. The platform shape is what lets a single founder serve 250 tenants in year 1.

---

## 18. Appendix A — Regulation timeline (2024–2027)

| Date | Event | Artefact triggered |
|---|---|---|
| 2024-08-01 | EU AI Act enters into force | (preparation) |
| 2024-12-01 | EDPB Guidelines 4/2024 (DPIA + AI) finalised | DPIA refresh |
| 2025-02-02 | EU AI Act prohibitions + AI literacy obligations apply | AI literacy programme |
| 2025-08-02 | GPAI obligations apply | GPAI technical documentation |
| 2025-12-31 | ISO/IEC 42001:2023 widely cited in enterprise RFPs | SoA + risk register |
| **2026-08-02** | **EU AI Act high-risk obligations apply** | **Annex IV pack, FRIA, conformity declaration, CE mark** |
| 2026-Q3 | UK AI Bill expected to begin parliamentary process | UK FRIA equivalent |
| 2026-Q4 | NIS2 enforcement maturity hits AI-in-critical-sectors | Resilience evidence |
| 2027-08-02 | EU AI Act regulators-of-providers fully resourced | Continuous monitoring |
| 2027-Q4 | First wave of AI Act fines published | Reactive demand spike |

## 19. Appendix B — Case-study templates

We will use a consistent case-study format once design partners agree to be named. Each case study captures:

- **Customer profile**: industry, size, regulatory exposure.
- **Trigger event**: what made compliance urgent (failed audit, blocked deal, new product launch).
- **Before**: time, cost, evidence quality of their previous approach.
- **After**: time, cost, evidence quality with CRP Comply.
- **Quote**: 1–2 sentences from the buyer (CISO / DPO / Head of AI).
- **Artefacts produced**: list with page counts.
- **Outcome**: deal closed, audit passed, fine avoided.

Until design partners agree to be named, we publish only **anonymised** case studies and cite the artefact metrics only.

## 20. Appendix C — Brand & voice

- **Voice**: precise, regulator-literate, engineering-first. We sound like a senior compliance engineer, not a marketing department.
- **Forbidden words**: "revolutionary", "AI-powered" (for our own product — it's compliance software that *integrates* AI), "synergy", "leverage" (as a verb), "best-of-breed".
- **Required disclosures**: every artefact carries the line *"This document is a draft prepared by an automated tool; review by qualified counsel is required before reliance."*
- **Visual identity**: Inter typeface; CRP black `#0B0B0C` + CRP white; minimalist, document-first; **no stock photography of robots / circuit boards / glowing brains**.
- **Logo**: CRP scales mark on black square. Used on `/`, `/docs`, all artefact PDF cover pages.
- **Partner-language rule (repeated for emphasis)**: never "partnered with" Clerk / Stripe / Microsoft / AWS / Anthropic / OpenAI unless we have a counter-signed marketing partnership. Use "built on", "integrates with", "powered by". When enrolled in a public developer programme, name the programme exactly (e.g. "member, Microsoft for Startups").

## 21. Appendix D — Compliance posture of CRP Comply itself

Because we sell *to* compliance buyers, our own posture is a sales asset:

| Control | Status |
|---|---|
| Article 28 GDPR DPA | ✅ Published `/dpa`, signed countersigned form available |
| Standard Contractual Clauses (Module 2) | ✅ Annex 1 of DPA |
| UK IDTA / Addendum B1.0 | ✅ Annex 2 of DPA |
| Swiss FADP supplement | ✅ Annex 3 of DPA |
| Subprocessor list | ✅ Public at `/subprocessors` (planned), versioned |
| Security headers (HSTS, CSP, COOP/CORP, X-Frame-Options) | ✅ Shipped |
| AES-256-GCM at-rest encryption (BYOK keys, evidence vault) | ✅ Shipped |
| Tamper-evident audit chain | ✅ Shipped (`data/audit/` Merkle log) |
| Tenant isolation tests | ✅ `tests/test_batch10_tenant_isolation.py` |
| Backend test suite | ✅ 450 passing |
| Bandit security scan | ✅ 0 issues across all severities |
| Ruff lint | ✅ Clean |
| pip-audit | ✅ Tracked, transitive CVE pins documented |
| SOC 2 Type II | 🟡 Year-1 target |
| ISO 27001 | 🟡 Year-2 target |
| ISO 42001 (eat our own dog food) | 🟡 Year-1 target |

---

> **Fin.** This brief is a living document. Anything that drifts more than 30 days out of date should be flagged in a PR titled `marketing-refresh`.
