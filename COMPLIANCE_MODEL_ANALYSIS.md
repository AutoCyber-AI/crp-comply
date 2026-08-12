# CRP Comply — Compliance Model Analysis

**Date:** 2026-04-24
**Scope:** Reasoning-only. No code, no product copy. A clear-eyed look at
whether the story we're currently telling users ("platform vs optional
runtime") actually produces a compliant outcome under the EU AI Act and
ISO/IEC 42001, and what our system would need to do instead.

---

## 1. The claim on the Guide page, stated plainly

Today the Guide tells the user:

> "CRP Comply is two products in one. The **platform** turns your profile
> and questions into regulator-ready deliverables. The **runtime**
> (optional) audits every LLM call your own AI product makes."

Read literally, this says: a user who never installs the proxy or SDK
can still arrive at regulator-ready deliverables, purely by answering
questions in the dashboard. That framing is convenient for skeptical
buyers ("try the platform first"), but **it is not true for a full
EU AI Act or ISO 42001 conformity programme**. It is only true for a
subset of deliverables — the static, policy-level ones.

This distinction matters because a user who reads our page today may
reasonably believe that completing every recipe in the library produces
an audit-ready evidence pack. It doesn't. It produces a policy library.
Those are different artefacts.

---

## 2. What the regulations actually ask for

Before assessing our system, we have to ground the analysis in the
actual obligations. Below are the clauses that decide whether a
deliverable can be produced from a questionnaire alone, or whether it
needs runtime signal.

### EU AI Act (high-risk system path)

| Article | Obligation | Data source required |
|---|---|---|
| **Art. 9** — Risk management system | Continuous, iterative identification/evaluation of risks across the lifecycle. | **Hybrid.** Design-time interview produces the plan; operation-time metrics (incidents, near-misses, drift) are needed to keep it current. |
| **Art. 10** — Data governance | Quality, relevance, representativeness, bias examination of training / validation / test data. | **Hybrid.** Needs the actual dataset manifest, lineage, bias audit output — not a description. |
| **Art. 11** + **Annex IV** — Technical documentation | General description, detailed design, monitoring metrics, performance, risk-mgmt outputs, lifecycle changes, post-market monitoring plan. | **Hybrid.** Sections 1–3 are design-time; section on monitoring metrics / performance is runtime-fed. |
| **Art. 12** — Automatic logging | "Capable of automatically recording events (logs) over the lifetime of the system." Traceability of functioning appropriate to intended purpose. | **Runtime-only.** This is literally what the proxy/SDK is for. A questionnaire cannot produce this. |
| **Art. 13** — Transparency & instructions for use | Clear documentation for the deployer. | **Static.** Interview-driven. |
| **Art. 14** — Human oversight | Measures designed into the system to allow meaningful oversight. | **Static** (design), but **runtime evidence** that the oversight hooks are actually invoked. |
| **Art. 15** — Accuracy, robustness, cybersecurity | Appropriate levels across lifecycle; declared in instructions for use. | **Hybrid.** You declare targets statically; you *prove* them with runtime accuracy/robustness/attack telemetry. |
| **Art. 17** — QMS | Documented quality management system. | **Static.** Policy document. |
| **Art. 26/27** — Deployer obligations incl. FRIA (Art. 27) | Fundamental Rights Impact Assessment for certain deployers. | **Hybrid.** Context-driven; for live systems requires usage data. |
| **Art. 72** — Post-market monitoring | Actively and systematically collect, document and analyse data on performance. | **Runtime-only.** By definition. |
| **Art. 73** — Serious incident reporting | Report serious incidents within 15 days (2 for fatality). | **Runtime-only.** No log = no report. |

### ISO/IEC 42001

- **Clauses 4–10** (leadership, planning, support, operation, performance evaluation, improvement): policy/process artefacts — static.
- **Annex A controls** split the same way:
  - A.2 policies, A.3 internal org, A.4 resources, A.5 impact assessment → **static / interview-driven**.
  - A.6 system lifecycle, A.7 data for AI, A.8 information for stakeholders → **hybrid** (needs dataset manifests, stakeholder comms artefacts).
  - **A.9 use of the AI system, A.10 third-party relationships** → **runtime-fed** (actual usage, actual vendor dependencies observed).
- **Clause 9.1 Monitoring, measurement, analysis, evaluation** → by definition runtime.
- **Operational planning and control (8.x)** → cannot be evidenced by a form; auditors look for records of operation.

### The same pattern in adjacent standards

- **NIST AI RMF — Measure / Manage functions**: explicit expectation of ongoing measurement against the mapped risks.
- **GDPR Art. 30** (records of processing), **Art. 32** (security of processing), **Art. 33** (breach notification within 72h): all require runtime records.
- **NIS2** incident reporting windows (24h / 72h / 1 month): runtime-only.

---

## 3. The honest taxonomy of deliverables

Every deliverable we ship should be classified into one of three buckets,
and the UI should tell the user which bucket they're in *before* they
start.

### Bucket A — Static / interview-producible

Produced entirely from the profile + a structured interview with the
agent + regulatory corpus retrieval. No runtime signal needed.

- AI policy (ISO 42001 Clause 5)
- Statement of Applicability (ISO 42001 Annex A)
- QMS description (AI Act Art. 17)
- Risk management *plan* (AI Act Art. 9 — the plan, not the ongoing register)
- Instructions for use / transparency disclosure (Art. 13)
- Human oversight design (Art. 14 — the design, not the evidence)
- GPAI model documentation (Art. 53 — if claimant is a GPAI provider)
- Supplier / third-party governance policy (ISO 42001 A.10 policy level)
- Intended-purpose statement, prohibited-use acceptable-use policy

These are the deliverables where the current "answer questions → get
draft" loop is genuinely appropriate. They are roughly **30–40%** of a
full conformity programme by artefact count, and maybe **50%** by word
volume, but **well under half of the evidentiary surface** an auditor
actually tests against.

### Bucket B — Hybrid (needs an artefact upload or a runtime sample)

Produced by interview + **user-supplied artefacts** (model card,
dataset card, architecture diagram, DPA, security test report) +
optional runtime data.

- Data governance documentation (Art. 10) — needs a dataset manifest.
- Annex IV technical documentation — needs model card, eval results, architecture.
- DPIA (GDPR Art. 35) — needs the actual processing description, categories of data observed.
- FRIA (AI Act Art. 27) — needs actual deployment context.
- Bias / fairness assessment — needs either an uploaded eval or proxy-observed output distributions.
- Cybersecurity / robustness assessment (Art. 15) — needs pen-test output or adversarial eval.
- Supplier assessment records — needs the actual contracts / DPAs.

These are the deliverables where our current flow **silently produces a
plausible-looking document that is actually fiction** if the user hasn't
uploaded the underlying evidence. That is a meaningful risk to the user
and to us.

### Bucket C — Runtime-only / continuously re-generated

Cannot exist without the proxy, SDK, or log ingestion.

- Art. 12 automatic event logs — the logs themselves.
- Art. 15 continuous accuracy/robustness monitoring evidence.
- Art. 72 post-market monitoring reports.
- Art. 73 serious incident register + individual reports.
- ISO 42001 Clause 9.1 monitoring/measurement records.
- ISO 42001 A.9 operational use records.
- GDPR Art. 30 Records of Processing Activities (if the system processes personal data in inference).
- GDPR Art. 33 breach notifications.
- NIS2 incident notifications.
- Ongoing audit chain — tamper-evident HMAC-signed event stream.

**A programme that omits Bucket C is not a compliant programme.** It is
a readiness assessment. That is still valuable — for sales, for funding
due diligence, for early-stage startups before go-live — but it is not
what the user thinks they are buying when we say "regulator-ready
deliverables."

---

## 4. How our system actually behaves today — against that taxonomy

Summarising the codebase as it stands (recipes, agent, proxy, vault,
tests):

### What works

- The **corpus + retrieval layer** is genuinely solid. The agent cites
  real articles. This is the hardest part, and we have it.
- The **profile + recipe engine** is well-suited to Bucket A. When a
  user fills in the profile and answers clarifying questions for the
  Statement of Applicability or an AI policy, the output is credible.
- The **proxy and SDK exist** and produce a signed audit chain. The
  bones of Bucket C are present.
- The **agent** (batch 5 clarification, batch 7 recipes, batch 8/9
  tailoring) can have a conversation about obligations.

### Where the design drifts from the obligations

1. **Recipes are framed as single-shot form fills.** A real DPIA is
   never one-shot — it is a structured interview (often across multiple
   sittings), with contributions from a DPO, a security engineer, a
   product manager, and the AI team. Our UX assumes one person, one
   session, one form. This is why users say "recipes for what?" — they
   don't recognise what they're looking at as the compliance work they
   know from real life.

2. **The agent and the recipes are separate surfaces.** The agent
   (`/app/chat`) can talk about an obligation but cannot *drive* the
   production of the deliverable attached to that obligation. The
   recipe (`/app/recipes`) can produce a deliverable but does not
   conduct an agent-grade interview. These should be **one loop**,
   not two surfaces.

3. **The proxy is described as optional.** For Bucket C it is the
   only source of evidence. Describing it as optional is sales-safe
   but is misleading for anyone actually trying to reach conformity.
   A more honest frame: *"The platform alone produces your policy
   programme. The runtime is what converts that programme into
   evidence."*

4. **There is no plumbing from proxy telemetry into deliverable
   drafting.** Today the audit chain is a log a user can download.
   It is not a **queryable evidence substrate** that the agent can
   retrieve from when composing a post-market monitoring report,
   an Art. 15 accuracy report, or a serious-incident register. This
   is the single biggest architectural gap — the proxy produces
   evidence, the recipes consume regulation, and nothing in the
   middle joins them.

5. **There is no programme-level view.** EU AI Act conformity is a
   programme, not a document. It runs continuously: you re-examine
   risks each release, you log incidents, you refresh the Annex IV
   file when the model changes. Our dashboard shows "compliance score"
   but there is no concept of a **conformity programme with a
   lifecycle state** (onboarding → QMS established → technical file
   assembled → monitoring live → first post-market review → annual
   management review…). The user cannot see *where they are* in the
   actual obligations arc.

6. **Artefact intake is thin.** For Bucket B deliverables, the user
   needs to give us things: model card, dataset card, architecture
   diagram, security pen-test, vendor DPAs, a prior ISO 27001 SoA. We
   have no first-class "upload your evidence artefacts" surface. Every
   Bucket B draft produced today is implicitly making up the facts it
   cannot see.

7. **The interview is not professional-grade.** A DPIA interview in
   practice looks like: *"Walk me through the data categories your
   model receives. Now: are any of these Art. 9 special category? Walk
   me through who inside the organisation can see the outputs. Is the
   output consequential to the data subject? If yes, is there a human
   review before action is taken?"* Each answer opens or closes
   branches. Our recipe clarifying-question system asks a flat set
   of fields. Good enough for an AI policy; nowhere near good enough
   for a DPIA or a FRIA.

8. **Deliverables are not "live."** Once generated, a recipe output is
   a Markdown file. In reality: Annex IV documentation must be
   **kept up to date for the lifetime of the system**. Our model of
   "generated on date X, archived in Vault" does not reflect the
   **keep-current** obligation. Deliverables should be *derived views*
   over the evidence substrate, re-rendered on demand.

---

## 5. The mental model we should be pitching instead

Here is the framing the product actually executes, stated the way it
should be presented to a prospect or a user:

> Compliance has three layers, and the layers depend on each other.
>
> **Layer 1 — Programme.** An AI policy, a QMS, a risk management
> system, a Statement of Applicability. This is your framework. We
> produce it from a structured interview plus the regulatory corpus.
> You can get here without instrumenting anything.
>
> **Layer 2 — Artefacts.** Model cards, dataset cards, architecture
> diagrams, DPAs, pen-test reports, prior certifications. You supply
> these. We ingest, cross-reference, and slot them into the documents
> that reference them (Annex IV, data governance docs, supplier
> register). Without Layer 2, Layer 1 is theatre.
>
> **Layer 3 — Evidence.** Automatic logs (Art. 12), continuous
> monitoring (Art. 15, Art. 72), incident records (Art. 73), records
> of processing (GDPR Art. 30), ISO 42001 Clause 9.1 measurement. This
> only exists if the runtime sees the traffic. The proxy or SDK is
> mandatory for a compliant outcome against any regulation that
> demands operational evidence — which is all of them. Without Layer 3,
> you have a policy programme, not a compliance programme.
>
> You can buy us layer-by-layer. You should not pretend you are done
> after Layer 1.

This framing is still commercially attractive — it still gives
skeptical buyers an on-ramp — but it stops misleading them about where
the finish line is.

---

## 6. The interaction model that would match the obligations

The existing "pick a recipe, fill a form, get a draft" loop should be
replaced (not extended) with an agent-led, evidence-aware composition
loop. Conceptually:

1. **User picks an obligation** (e.g. "produce Annex IV technical
   documentation for product X") — or the system picks it based on the
   programme state.
2. **Agent opens a drafting session.** The session persists. It has a
   current draft, a list of open interview questions, a list of
   required artefacts, and a list of required runtime evidence queries.
3. **The agent conducts the interview.** Socratic, branching, citing
   the regulatory source for every question it asks ("I'm asking this
   because Art. 10(3) requires datasets be relevant and
   representative…"). The user can answer, defer, or delegate.
4. **The agent asks for artefacts.** ("I need the model card for the
   system referenced in §2. Upload, or point me to a URL, or let me
   draft a placeholder and flag it.")
5. **The agent pulls runtime evidence.** It queries the proxy's
   evidence substrate: *"In the last 30 days this model served N
   inferences, refusal rate R, flagged-output rate F, observed data
   categories {…}, top 10 countries of origin {…}."* Those facts go
   into the draft, cited to the audit chain entries that prove them.
6. **The draft assembles progressively.** Every paragraph has a
   provenance tag: *interview answer / uploaded artefact / runtime
   metric / regulatory quotation*. A paragraph with no provenance is
   flagged; nothing is invented.
7. **The deliverable closes when provenance is complete.** Not when
   a form is submitted. You can sign an incomplete draft, but the
   system tells you which clauses are unsourced and what that means
   under audit.
8. **The deliverable stays live.** The derivation is recorded. The
   next time the underlying evidence moves (new model version, new
   incident, new refusal-rate month), the system offers to re-derive
   and the user approves or adjusts.

This is what "professional interaction, context from the AI system
itself" looks like in concrete terms.

---

## 7. What this implies for the product surface

*(Listed so we know the scope; not built in this document.)*

- **Two concepts users need to understand**, not three:
  1. *The programme* — the living state of your compliance posture.
  2. *The evidence feed* — what the runtime sees, what artefacts you have uploaded, what the interview captured.
  Every deliverable is a *view* over those two.
- **Replace the recipe library page** with a programme tracker that shows
  the obligations you are on the hook for and, for each, the state
  of the deliverable (not started / interview in progress / waiting
  on artefact / waiting on runtime evidence / draft ready / signed /
  stale).
- **Fold the agent and recipes into a single drafting surface.** The
  chat is how you talk to a deliverable.
- **Make artefact intake a first-class page** (a "data room") — every
  upload is tagged with what clauses it evidences.
- **Expose the evidence substrate** — a read-only page showing what
  the proxy has observed, what the agent can cite.
- **Stop calling the runtime "optional."** Call it what it is: the
  evidence layer. Price can still be a separate conversation.
- **Fix the broken landing-page Docs link** (noted; trivial).
- **Recognise in the pricing/positioning page** that there are three
  honest product states: Readiness (platform only), Operational
  compliance (platform + runtime + artefact room), Managed (the
  above with analyst support). The current two-tier "platform /
  optional runtime" framing blurs this.

---

## 8. Short answer to the user's question

> *Isn't the proxy needed for full-time compliance?*

**Yes.** For any regulation with an operational-evidence clause — which
is all of them that matter (AI Act Art. 12 / 15 / 72 / 73, ISO 42001
Clause 9.1 + A.9, GDPR Art. 30 / 32 / 33, NIS2) — the proxy (or the SDK,
or direct log ingestion) is not optional. What is optional is *when* you
turn it on. You can sell the platform alone as a readiness programme,
but you must stop describing the resulting output as a compliance
outcome.

> *Shouldn't deliverables be generated on demand from information
> collected through the proxy?*

**Yes, for Bucket B and Bucket C deliverables.** Bucket A deliverables
can stay interview-driven because they describe intent, not operation.
Everything that describes operation has to be derived from the evidence
substrate, or it is fiction.

> *Not all deliverables can be created just from descriptions, right?
> We need user inquiries, professional interaction, context from the
> AI system itself.*

**Correct on all three.** The current form-driven recipe loop is
appropriate for the intent-level deliverables and inappropriate for
everything else. The agent is the right surface for the interview; the
proxy is the right source for the system context; artefact intake is
the missing third input. Today only the first two exist, and they are
not wired to the recipes.

---

## 9. Recommendation

Treat this as the moment to change the product story, not to add
another feature. The specific next moves, in order, would be:

1. **Re-frame** the Guide page and the landing page around the
   three-layer model (programme / artefacts / evidence) instead of
   the two-product model (platform / optional runtime).
2. **Repair** the landing-page navigation — Docs link and any other
   dead routes — so the story we tell on the outside matches what
   exists on the inside.
3. **Design the evidence substrate** — the queryable layer between
   the proxy's audit chain and the recipe/agent composition loop. This
   is the single biggest missing piece and it unlocks Buckets B and C.
4. **Merge the agent and the recipe into one drafting surface** with
   progressive, provenance-tagged composition. Keep the form as a
   fallback path for Bucket A.
5. **Add an artefact room** — first-class upload surface with clause
   tagging.
6. **Replace the recipe library** with a programme tracker.
7. **Reprice** accordingly (readiness / operational / managed) so the
   honest layering is also the commercial layering.

The rest — polish, theming, BYOK banner wording — is downstream of
getting the model right.

---

*End of analysis.*
