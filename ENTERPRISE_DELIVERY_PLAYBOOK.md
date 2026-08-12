# Enterprise Delivery Playbook

**Status:** Design — repeatable workflow for Enterprise-tier customer engagements
**Created:** 2026-04-23
**Owner:** Constantinos Vidiniotis
**Scope:** The operational runbook for every Enterprise deal, from first call through annual renewal.

---

## 0. Why this document exists

Enterprise ≠ scaled-up Pro. An Enterprise customer (regulated industry, >1000 employees, annual contract, custom requirements) needs:

- A named point of contact
- A security + data-protection review **we** have to pass, not the other way round
- Procurement, DPA, MSA, SOW paperwork
- A custom-configured deployment (sometimes on their VPC)
- A rollout plan with compliance milestones
- An SLA
- Quarterly reviews

**Without a repeatable playbook, every Enterprise deal becomes a snowflake project that burns margin and consultant hours.** This document exists to prevent that — the engagement is bespoke to the customer's regulations, but the *process* is the same every time.

Target: any Enterprise deal should take ≤ 4 weeks from first call to production go-live, with ≤ 40 hours of our time.

---

## 1. The Enterprise Customer Profile

We qualify as Enterprise if the customer meets **two or more** of:

- Regulated industry (financial services, healthcare, government, defence, critical infrastructure)
- >1,000 employees OR >€100M revenue
- Needs SSO / SAML / SCIM
- Needs dedicated tenancy (not shared infra)
- Needs data residency in a specific region (EU, UK, CH, US-only)
- Needs on-prem / air-gapped deployment
- Needs regulator-facing signed certificates / audited evidence packs with their logo
- Subject to SOC 2 / ISO 27001 procurement requirements
- Must sign a Master Services Agreement + Data Processing Agreement
- Annual contract value > €20k

Below that threshold: route to Business tier self-serve.

---

## 2. The Six-Stage Workflow

```
┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
│ 1. QUAL  │─▶│ 2. SCOPE │─▶│ 3. SECURITY │─▶│ 4. DEPLOY│─▶│ 5. GO-LIVE │─▶│ 6. RENEW │
│  1 call  │   │  1 week  │   │    1 week   │   │  1-2 wks │   │  ongoing  │   │ annual   │
└──────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘
```

### Stage 1 — Qualification (day 0, single call, ≤ 60 min)

**Goal:** decide in one call whether to continue.

**Pre-call:** prospect fills out `enterprise-intake.md` form (§3 below).

**Call agenda (60 min):**
- 10 min — what they do, what AI systems they run, volumes
- 10 min — their regulatory pressures (EU AI Act bucket, GDPR, sector-specific)
- 10 min — current pain (fines threat, audit coming up, investor/board ask)
- 10 min — we demo the agent on one of their use-cases live
- 10 min — procurement realities (DPA, MSA, SOC 2, timelines)
- 10 min — pricing anchor, next-step agreement

**Qualify OUT if:**
- They want white-label resale (different product, defer)
- They want us to indemnify them for compliance outcomes (we won't — we're a tool)
- They need <2 week deployment with no procurement (probably not serious)
- Budget is < €25k/yr (route to Business self-serve)

**Qualify IN deliverables:**
- Signed mutual NDA (template in `legal/nda.md`)
- Intake form completed
- Scoped pricing ballpark in writing (range, not final)
- Named champion on their side + named security contact
- Agreed 4-week target go-live date

### Stage 2 — Scoping (week 1)

**Goal:** write a Statement of Work the customer will sign.

**Inputs:**
- Intake form (§3)
- One 90-min technical discovery call

**Discovery call agenda:**
- Systems inventory — how many AI systems, their risk classifications, data types
- Deployment target — shared cloud (Railway) / dedicated cloud / their VPC / air-gap
- SSO requirements — Okta / Azure AD / Google / SAML generic
- Data residency — EU, UK, US-only, country-specific
- Regulation packs needed — beyond v1 defaults (EU AI Act + GDPR + ISO 42001 + NIST AI RMF + OECD + CoE + UK + EDPB), do they need NIS2, US state laws, Singapore, China, sector-specific?
- Custom evidence-pack branding (logo, sign-off officer names, document control)
- Integration points — SIEM webhooks, ticketing system, data lineage tools
- Report volume — monthly agent reports, evidence packs expected
- LLM posture — hosted by us / BYOK / air-gapped self-hosted
- SLA requirements — uptime %, response times, escalation path

**Deliverables from scoping (≤ 5 business days after discovery call):**
- **Statement of Work (SOW)** using `templates/sow-template.md`:
  - Scope of deployment
  - Regulation packs included
  - Number of user seats
  - Monthly agent report quota
  - SLA terms
  - Custom work (if any — e.g. a sector-specific prompt pack)
  - Onboarding milestones + dates
  - Pricing (annual upfront)
  - Renewal terms + price-lock
- **Price quote** attached
- **Draft DPA** (Data Processing Agreement) using `legal/dpa-template.md`
- **Draft MSA** (Master Services Agreement) using `legal/msa-template.md`

### Stage 3 — Security & Legal Review (week 2, parallel track)

**Goal:** get through their procurement gauntlet without losing momentum.

**Typical requests we must answer fast:**

| Their ask | Our answer |
|---|---|
| SOC 2 Type II report | In progress (roadmap item). Interim: security whitepaper + Trust Center |
| ISO 27001 certificate | Committed on roadmap; mutual reliance on underlying platforms (Railway, AWS) |
| Penetration test report | Annual third-party pen test summary (action: schedule one if not done) |
| Subprocessors list | Maintained at `/trust/subprocessors` — Railway, Clerk, Stripe, Groq, Anthropic, OpenAI, Cloudflare |
| DPIA on our product | Template DPIA (we eat our own dog food) at `/trust/crp-comply-dpia.pdf` |
| Insurance — cyber liability | Minimum €2M cyber liability policy (action: confirm/buy) |
| Data flow diagram | Published at `/trust/data-flow-diagram.pdf` |
| Incident response plan | Published at `/trust/incident-response.md` |
| Data deletion SLA | 30 days from request (matches our DPA) |
| Vendor security questionnaire (VSQ / SIG Lite) | Pre-filled response in `trust/sig-lite-response.xlsx` — update per customer |

**Our internal checklist before Stage 3 passes:**
- [ ] DPA signed (Art. 28 GDPR-compliant, our template or their paper accepted)
- [ ] MSA signed (our template with carve-outs for compliance tool disclaimers)
- [ ] Purchase Order received
- [ ] Invoice sent (Net-30 or upfront annual)
- [ ] Payment received OR contractually due date on calendar
- [ ] Security questionnaire responses archived
- [ ] Customer's security team contact captured for any ongoing requests

**Exit criteria:** executed MSA + DPA + PO, payment scheduled or received.

### Stage 4 — Deployment (weeks 2-3, parallel with Stage 3)

**Goal:** stand up a production environment meeting their SOW.

Deployment mode decides the playbook branch:

#### 4a. Dedicated Cloud (most common — 70% of Enterprise)

Railway dedicated project (not the shared multi-tenant one). Benefits: isolated volume, isolated DB, regional placement.

Steps:
1. New Railway project: `crp-comply-{customer-slug}`
2. Clone our deployment from `railway-template.toml`
3. Region: customer-specified (EU = `eu-west1` via Railway's EU region; US = `us-west1`)
4. Volume: 25 GB baseline, auto-expand
5. Env vars from customer-specific template (DPO name, branding, quotas, regulation packs)
6. Custom subdomain: `{customer-slug}.comply.crprotocol.io` — TLS via Cloudflare
7. Optionally: bring-your-own-domain (`compliance.{customer}.com` via CNAME)
8. Clerk tenant: dedicated Clerk application with their SSO provider wired
9. Regulation corpus: pull their requested packs from `corpus/` versioned indexes
10. Run deployment smoke tests (`scripts/enterprise-smoke-test.sh` — 30 checks)

#### 4b. Customer VPC / their AWS account (some financial services, healthcare)

We ship a Docker image + Terraform module. Their infra team deploys.

Steps:
1. Generate `enterprise-vpc-deploy/` starter kit — Terraform for AWS/Azure/GCP, Dockerfile, env-var spec
2. Joint deployment call (us + their DevOps) — typically 90 min
3. Health check from our monitoring endpoint into their deployment (outbound-only webhook so no inbound from us)
4. License key installed — disables / enables features per SOW
5. Their infra team owns uptime; we own the software + updates via signed container image updates

#### 4c. Air-gapped on-prem (rare, government / defence)

Full offline install. Customer downloads signed tarball, installs inside their secure zone.

Steps:
1. Build signed offline-install bundle (includes regulation corpus snapshot)
2. USB / courier delivery of initial bundle + quarterly update bundles
3. Their BYOK LLM (typically their own fine-tune on isolated GPUs)
4. No telemetry back to us; annual in-person audit check-in

### Stage 5 — Go-Live + Onboarding (week 3-4)

**Goal:** move them from "deployed" to "producing value in production".

**Onboarding week:**

- **Day 1:** SSO wiring + admin user creation + tier unlocks live
- **Day 2:** Training webinar #1 — product walkthrough, agent-first compliance flow (90 min for their compliance team)
- **Day 3:** Training webinar #2 — admin console, user management, reports + evidence packs (60 min for their IT / security team)
- **Day 4-5:** Live-drive — run 3–5 of their actual systems through the agent, produce signed evidence packs they can send to their board
- **Day 5 end-of-week:** go-live review call, signed-off success criteria

**Success criteria template (in SOW):**
- [ ] SSO working for ≥ 10 users
- [ ] 3 of customer's AI systems have completed agent-generated reports
- [ ] At least 1 signed evidence pack delivered and verified via the CRP signature check tool
- [ ] Admin console usable by their admin without our assistance
- [ ] Monitoring + alerts configured to their on-call channel
- [ ] Runbook delivered to their team (customer-specific, generated from template)

### Stage 6 — Ongoing + Renewal

**Cadence:**

| Frequency | Activity |
|---|---|
| Weekly (first month) | Slack/email check-in, 15 min |
| Monthly | Usage review + tier optimization |
| Quarterly | Business review — compliance posture trend, upcoming regulation changes affecting them, feature requests |
| Annually | Renewal negotiation, SOW revision, price review |

**Renewal triggers (start ≥ 60 days before term end):**
- Usage tier moved up or down
- New regulation packs they need
- SSO or integration changes
- Pricing review (CPI + feature expansion)
- Multi-year lock for discount

**Save-the-deal playbook** (renewal at risk):
- Executive sponsor call within 48h
- Offer free 90-day pilot of the next tier up or an Enterprise-exclusive feature
- Propose payment terms flexibility (quarterly vs annual)
- Worst case: offer discounted bridge contract to preserve relationship

---

## 3. Templates (build these once, reuse forever)

Create these under `enterprise/templates/`:

| File | Purpose | Who fills |
|---|---|---|
| `enterprise-intake.md` | Prospect self-serve pre-call form | Prospect |
| `discovery-agenda.md` | 90-min scoping call agenda | Us |
| `sow-template.md` | Statement of Work | Us + customer |
| `msa-template.md` | Master Services Agreement | Legal (outsource first 3, template after) |
| `dpa-template.md` | Data Processing Agreement (Art. 28 GDPR) | Legal |
| `nda-template.md` | Mutual NDA | Us |
| `sig-lite-response.xlsx` | Pre-filled security questionnaire | Us (update per customer) |
| `trust-center-one-pager.pdf` | Summary security + compliance posture | Us (refresh quarterly) |
| `enterprise-kickoff-deck.pdf` | Slide deck for Stage 5 Day 1 | Us |
| `runbook-template.md` | Customer-specific runbook we leave them | Us |
| `onboarding-checklist.md` | 5-day go-live checklist | Us |
| `renewal-health-score.xlsx` | Customer health scorecard | Us, monthly |

Every template should take ≤ 1 hour to customize per deal. If one takes longer, automate the customization.

---

## 4. Enterprise Pricing Framework

**Floor:** €25,000/yr. Below that, push to Business tier.

**Calculator:**
```
base_platform_fee              = €20,000/yr
+ seats × €100/user/yr         (unlimited seats on the highest plans)
+ monthly_reports × €0.50      (first 1000 included, overage after)
+ regulation_packs × €3,000/yr (beyond the 8-pack v1 default)
+ deployment_mode_surcharge    (dedicated cloud: +€10k/yr, VPC: +€25k/yr, air-gap: +€75k/yr)
+ custom_integration           (per-deal scope, minimum €15k)
+ SLA uplift                   (99.9% standard; 99.95% +€8k/yr; 99.99% custom)
= annual_subscription_fee

Optional add-ons:
+ Live Regulation Feed (early-warning advisory of reg changes)  = €12k/yr
+ Quarterly compliance officer consultation (4 × 2h)            = €10k/yr
+ White-label signed evidence packs                             = €6k/yr
```

**Typical outcomes:**
- Financial services mid-market: €60–120k/yr
- Healthcare AI startup: €40–80k/yr
- Large bank / insurer: €150–400k/yr
- Government / defence on-prem: €300k–1M/yr

**Always:**
- Annual contracts, upfront payment preferred (30-60 day invoice OK)
- 3-year deals get 15% discount + price-lock
- Auto-renew with 60-day cancellation notice
- Carve-out: 30-day termination for cause (their regulatory disaster, not our outage)

---

## 5. Our Delivery Team (what roles, when)

Right now team = you. As volume grows, this is the split:

| Role | When to hire | What they do |
|---|---|---|
| **Solution Architect** (you, initially) | year 1 | Stages 1-2, sign-offs on 4-5 |
| **Customer Success Manager** | after 5 Enterprise customers | Stage 6, renewal, expansion |
| **Security & Compliance Officer** | after first SOC 2 audit | Stage 3 paperwork, security questionnaires, trust center |
| **Implementation Engineer** | after 8 Enterprise customers | Stage 4 deployment, especially VPC/on-prem |
| **Regulation Analyst** | after 15 Enterprise customers | Runs Live Regulation CI curation (§15), writes sector packs |

Until headcount exists: **you run Stages 1-2, outsource legal (Stage 3), use a trusted DevOps contractor for Stage 4 non-Railway deployments, do Stage 5 personally for the first 3 customers (it builds the runbook), systematize from 4 onwards.**

---

## 6. What I (the Enterprise customer) get vs Business

| Feature | Business €599 | Enterprise (from €25k) |
|---|---|---|
| Seats | 10 | Unlimited |
| Monthly agent reports | 200 | 1,000+ (customizable) |
| LLM provider | hosted + BYOK | hosted + BYOK + dedicated tenancy |
| Model quality | Claude Haiku 3.5 | Claude Sonnet 3.5 + fine-tune path |
| Regulation packs | 8-pack v1 | All packs including NIS2, US state laws, sector-specific |
| Live Regulation Feed | — | ✅ |
| SSO | — | ✅ SAML + SCIM |
| Data residency | EU shared | EU / US / UK / custom |
| Deployment | shared Railway | dedicated cloud / VPC / air-gap |
| Subdomain / custom domain | — | ✅ |
| White-label evidence packs | — | ✅ |
| Signed evidence packs with named compliance officer | — | ✅ |
| Integrations (SIEM, ticketing) | — | ✅ |
| SLA | 99% best-effort | 99.9% / 99.95% contractual + credits |
| Support | email | Slack shared channel + named CSM + quarterly reviews |
| Custom regulation advisory | — | ✅ (add-on) |
| Quarterly compliance consultation | — | ✅ (add-on) |
| Contract | monthly | annual, 1-3 year |

---

## 7. Risks specific to Enterprise deals

| Risk | Mitigation |
|---|---|
| Customer wants us to accept unlimited liability | MSA caps liability at 12 months fees. Non-negotiable. |
| Regulatory change after contract signed makes product inadequate | Live Regulation CI + 90-day out for regulatory-change-only |
| Their data leaks out of our infra | Dedicated tenancy + encryption at rest + annual pen test + cyber insurance |
| LLM provider outage during their audit | Multi-provider fallback (primary Groq, fallback Anthropic, fallback Together) |
| Customer's regulator demands something we don't support | 60-day SLA to add it or return pro-rata fees — captured in MSA |
| Customer churns after year 1 | Renewal process (§Stage 6), health scoring, expansion into adjacent regulations |
| Custom work over-runs | SOW always fixed-fee, not T&M; scope creep triggers Change Order at €200/hr |
| They ask for source code | Escrow agreement (third-party) if they pay +€20k/yr for it |

---

## 8. When this playbook fails

Red flags to walk away from the deal even if money is offered:

- They refuse to sign any DPA (means they don't take data protection seriously; you'll be blamed)
- They insist on indemnification for compliance outcomes beyond our control
- They want exclusive industry rights (defeats the SaaS model)
- Their procurement is > 6 months and they won't pay a deposit
- They expect us to operate their compliance program (we're a tool, not a consultancy)
- Payment terms longer than Net-60

---

## 9. Metrics that matter

Track these monthly:

- **Pipeline:** # qualified deals × avg deal size × probability
- **Win rate:** signed deals / qualified deals
- **Time-to-close:** days from Stage 1 to PO
- **Time-to-go-live:** days from PO to Stage 5 sign-off
- **Net Revenue Retention:** (renewals + expansion - churn) / prior-period ARR
- **Gross margin per Enterprise customer:** revenue − LLM cost − infra − support time
- **Customer Health Score:** usage trend + support ticket health + quarterly-review sentiment

Red alert thresholds:
- Time-to-close > 90 days → investigate friction
- Time-to-go-live > 6 weeks → playbook failure, post-mortem
- NRR < 110% → product gap or competitive threat
- Gross margin per customer < 70% → pricing too low or scope too wide

---

## 10. Document control

This playbook lives at [ENTERPRISE_DELIVERY_PLAYBOOK.md](ENTERPRISE_DELIVERY_PLAYBOOK.md). It is expected to be updated every quarter based on lessons from each deal. Update log:

| Date | Change | Deal context |
|---|---|---|
| 2026-04-23 | Initial version | Pre-first-Enterprise-deal |

After each Enterprise deal closes, update this doc with:
- What worked
- What didn't
- What template needs amending
- What pricing assumption was right/wrong

**Rule:** nothing goes into a customer engagement that isn't in this playbook. If something new is needed, add it here *first*, then execute.
