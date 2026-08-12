# STRATEGIC REASSESSMENT — CRP Comply Deliverables

> 📌 **Session handoff:** see [HANDOFF.md](HANDOFF.md) for the current state of the repo and next-action priority. This doc is canonical for **scope**; `REMAINING_WORK.md` is canonical for **launch blockers**; `UI_UX_REDESIGN.md` is canonical for **UX**.

**Status:** Revised draft, Phase 4.6 → 4.7 hand-off (2026-04-23)
**Author:** Lead engineering, CRP Comply
**Scope:** Product-level reassessment of what CRP Comply promises to its users, prompted by hard questions raised during the Phase 4.2 → 4.6 transition and by the ingestion of the unofficial ISO 42001 explainer by Dr. Sid Ahmed Benraouane (Routledge, 2024). This document supersedes earlier deliverable scoping in `CRP_MASTER_TODO.md` and extends `docs/CRP_CAPABILITIES.md`. Items that were scoped but deliberately deferred live in [DEFERRED_TODOS.md](DEFERRED_TODOS.md).

> **Third-party attribution.** Where this document draws structural concepts from the book *"AI Management System Certification According to the ISO/IEC 42001 Standard — How to Audit, Certify, and Build Responsible AI Systems"* (Benraouane, © 2024 Routledge / Taylor & Francis Group, ISBN 978-1-032-73397-5), we cite by section path only (see [corpus/iso/42001/explainer/benraouane_2024.headings.json](corpus/iso/42001/explainer/benraouane_2024.headings.json)). No body prose from the book is reproduced here.

---

## 0. TL;DR

The Phase 4.2 tool catalogue and Phase 4.6 agent endpoints complete the **reasoning engine**. A paying customer will still reasonably ask us four questions we must answer without hand-waving:

1. **"How do you even see what my application is doing?"** The proxy only sees what flows through it. A company RAG, vector DB, MCP tool, or internal API that the application calls *before* reaching an LLM is invisible to us. **→ Fix in the core CRP protocol, not in Comply.** §2.
2. **"Will you tell me how to fix non-compliance — not just flag it?"** Today we produce findings without prescribed remediation paths. Prompt engineering cannot carry this load; it must be deterministic and verifiable. §3 + [DEFERRED_TODOS.md §1](DEFERRED_TODOS.md).
3. **"Do you give me compliance mappings?"** Yes — but authored *per framework, against the regulation's own text*. No internal ontology hub. §4 + [DEFERRED_TODOS.md §2](DEFERRED_TODOS.md).
4. **"What's your coverage of the regulation I actually care about?"** EU AI Act first, honestly measured, CI-enforced. §5 + [DEFERRED_TODOS.md §3](DEFERRED_TODOS.md).

**Immediate focus (this and the next phase):** §2 — Context-Source provenance in the core CRP protocol, plus its Comply-side consumers. Everything else in this doc is scoped but queued behind it. LLM hosting economics is out of scope here and tracked in [DEFERRED_TODOS.md §5](DEFERRED_TODOS.md).

The explainer is unambiguous on what an AIMS (AI Management System) must produce. We take its teachings as a target spec and commit to the deliverables expansion in §6 / §7. None of it requires work outside the architectural envelope we already committed to; it is product decisions and schema work.

---

## 1. What the explainer teaches us

The book is a conformance-oriented guide written by a US delegate to ISO who helped draft ISO/IEC 42001. Its *structure* tells us, at a glance, what an AIMS must actually deliver on the ground — the things an auditor will ask to see during a Stage 1 or Stage 2 conformity assessment. We read the section paths (see headings index) and distil the following actionable points:

| Topic taught by the explainer | Section path (pointer) | Our current coverage | Gap to close |
|-------------------------------|------------------------|----------------------|--------------|
| **Context Analysis is the *first* crucial step of an AIMS** | Part 2 > Introduction > *Why Context Analysis Is Crucial to AI Management System?* | Partial — we capture context **inside** CRP envelopes, but we do not produce the *Context Analysis deliverable* (ISO 42001 Clause 4.1–4.2) | **New deliverable: `context_analysis.md`** driven from declared Context Manifest |
| **AI Policy requires specific components and role definitions** | Part 2 > Introduction > *AI Policy: Characteristics and Components* / *What Should Be in the AI Policy?* / *Define the Roles and Responsibilities* | None | **New deliverable: `ai_policy.md`** generated from a customer questionnaire + our template |
| **AI Strategy is a distinct artefact** | Part 2 > Introduction > *AI Strategy* | None | **New deliverable: `ai_strategy.md`** |
| **Risk Management = assessment + treatment + impact assessment (Clauses 6.1.2 / 6.1.3 / 6.1.4)** | Part 2 > Introduction > *AI Risk Management, Risk Treatment, and Impact Assessment* | DPIA ≈ partial GDPR-only slice | **Three deliverables:** Risk Register (6.1.2), Risk Treatment Plan (6.1.3), AI Impact Assessment (6.1.4) |
| **Typology of Risks (seven categories)** | Part 2 > Introduction > *A Typology of Risks* | None | Extend agent's classifier to tag each finding with its risk category |
| **Data Management Risk + ISO data quality requirements** | Part 2 > Introduction > *The Planning of Data Management Risk* / *ISO Standard Data Quality Requirements* | None | New section in Risk Register; new tool `check_data_quality_requirements` |
| **Tangible + Intangible Resources (infrastructure + competence)** | Part 2 > Introduction > *Tangible Resources: The AI Infrastructure* / *Intangible Resources: AI Competence Model* | None | **New deliverable: Competence Matrix**; enrich technical docs with infra inventory |
| **Communication (Clause 7.4)** | Part 2 > Introduction > *Communication (Clause 7.4)* | None | **New section in compliance report** |
| **Documented Information Register** | Part 2 > Introduction > *Documented Information* | Implicit — our Evidence Pack is close, but not an ISO-style register | Add a `documented_information_register.json` manifest to Evidence Pack |
| **Internal Audit Programme** | Part 2 > Introduction > *Set Up an Internal Audit Program* | None | **New deliverable: `internal_audit_programme.md`** + scheduling tool |
| **Management Review** | Part 2 > Introduction > *Management Review* | None | **New deliverable: `management_review_minutes_template.md`** |
| **Corrective + Preventive Actions + PDCA** | Part 2 > Introduction > *Corrective Actions and Preventive Actions Framework* / *Continual Improvement: The PDCA Approach* | None | **New deliverable: CAPA register**, tool `open_corrective_action` |

The explainer also strongly emphasises that **an AIMS is a living system** — PDCA, not one-shot. Our platform must reflect that: sessions, reports, and findings must be re-entrant and track state across management reviews.

---

## 2. Question 1 — Context visibility (IMMEDIATE FOCUS)

> **User's verbatim question:** *"How do we know what context the user's application is on eg. an LLM could be connected to a company db and a company RAG for context that influences decisions...does our CRP proxy account for that...the context windows etc.."*
>
> **Follow-up:** *"wouldn't it be better if the CRP protocol was able to detect what is being used?!?! ... should we fix the protocol itself and update it (personally would prefer this..stronger protocol, more adoption)"*

### 2.1 Honest diagnosis

The CRP proxy is a **data-plane control point**: we see what flows through the `/v1` OpenAI-compatible proxy. We do **not** natively track:

* Retrieval from a customer's private vector DB that happens *before* the LLM call and is stuffed into the prompt.
* Tool/function-calling results returned by MCP servers, internal APIs, or agent frameworks outside CRP.
* System prompts baked into the customer's fine-tuned model.
* Anything outside the proxy's traffic capture.

**What the CRP protocol already has** (confirmed by repo review of `context-relay-protocol/`, April 2026):

* A **Decision Provenance Engine** (`crp/provenance/`) that classifies every LLM-produced claim as `CONTEXT_GROUNDED | PARAMETRIC | MIXED | UNCERTAIN`. This is *output-side* provenance — claim → envelope fact.
* A **Source Grounding Engine** (`crp/advanced/source_grounding.py`) that stores verbatim passages for high-confidence facts.
* A tool-mediated pull model (`crp/core/context_tools.py`) with structured `role: "tool"` messages.
* A `Fact` dataclass (`crp/extraction/types.py`) with `source_window_id`, `extraction_stage`, `metadata` — but **no field that records which external source (RAG / DB / MCP / tool / user / system) supplied the upstream text**.

**The gap:** output-side provenance is symmetric with input-side provenance *only* if inputs carry source-kind metadata. Today they don't. `AttributionType` measures where the output came from, not where the envelope fact came from.

Pretending otherwise would fail an ISO 42001 Clause 4 (Context) audit — the explainer's first chapter of Part 2 exists because this is the step organisations botch most often.

### 2.2 Design response — fix the CRP protocol itself

We fix this in `context-relay-protocol`, not as a Comply bolt-on. Rationale: (a) every CRP user benefits, (b) input-side provenance becomes a first-class primitive symmetric with the existing output-side DPE, (c) stronger protocol → more adoption.

**New primitives (PR target: `context-relay-protocol`):**

1. **`SourceKind` enum + `ContextSource` frozen dataclass** (`crp/core/context_source.py`):

   ```python
   class SourceKind(str, Enum):
       USER_TURN = "user_turn"
       SYSTEM_PROMPT = "system_prompt"
       RAG_RETRIEVAL = "rag_retrieval"
       VECTOR_DB = "vector_db"
       DATABASE = "database"
       MCP_TOOL = "mcp_tool"
       FUNCTION_CALL = "function_call"
       WEB_SEARCH = "web_search"
       FILE_UPLOAD = "file_upload"
       AGENT_MEMORY = "agent_memory"
       PARAMETRIC = "parametric"       # model internal knowledge
       UNATTESTED = "unattested"       # detected but not declared

   @dataclass(frozen=True)
   class ContextSource:
       kind: SourceKind
       source_id: str              # stable handle, e.g. "acme-hr-vdb"
       origin: Literal["declared", "observed", "heuristic"]
       trust_level: Literal["trusted", "untrusted", "unknown"]
       contains_pii: bool | None = None
       region: str | None = None
       retrieved_at: datetime | None = None
       retrieval_query: str | None = None   # for RAG/DB
       upstream_uri: str | None = None
       declared_by_manifest_id: str | None = None
   ```

2. **`Fact.source: ContextSource | None`** — optional, backward-compat default `None`. Populated by the message-assembly layer when it knows the origin (tool call response, RAG block, user turn). Consumed by the envelope builder and surfaced in a new **`[CONTEXT_SOURCES]`** envelope section.

3. **Detective-mode parser** in `dispatch_router.assemble_messages`: when messages arrive without explicit `ContextSource` attribution, pattern-match for common markers (`role: "tool"`, `<RAG>`, `[retrieved]`, MCP tool-result blocks, `system` role, etc.) and attach a heuristic `ContextSource(origin="heuristic")`. Anything that can't be classified becomes `UNATTESTED`.

4. **Attestation binding (optional)**: callers may register a `ContextManifest` that declares their intended sources. At envelope construction, if observed sources ⊄ declared sources, emit a `CONTEXT_ATTESTATION_MISMATCH` audit event. Manifest registration is a protocol-level concept; enforcement (refusing traffic) is a Comply concern.

5. **Provenance chain extension**: the existing DPE already emits §7.14.2 audit events for "envelope context selection provenance" and "fact extraction provenance". We extend these events to carry `ContextSource` per fact, making input-side provenance auditable the same way output-side already is.

### 2.3 Comply-side consumers

Once the protocol exposes `ContextSource`, CRP Comply produces:

* **Context Analysis document** (ISO 42001 §4.1–4.2) — auto-assembled from declared + observed sources. Every source row cites its `ContextSource` record.
* **Attestation audit findings** — each `CONTEXT_ATTESTATION_MISMATCH` becomes a finding in the compliance report with a concrete remediation (register the source in the manifest or remove it).
* **GDPR Art. 30 Records of Processing** — derivable from `ContextSource.contains_pii`, `region`, `retrieval_query` metadata.
* **AI Act Art. 10 data-governance evidence** — the protocol-level source ledger is the evidence base.

**Honest caveat rendered on every Context Analysis:**

> *"CRP observed `{observed_sources}`. The customer's Context Manifest additionally declares `{declared_sources}`. Sources that are neither observed nor declared are **out of audit scope** — the customer's Management Review must review manifest completeness before the next audit cycle."*

We don't fake omniscience; we formalise the attestation boundary and make manifest completeness a measurable compliance objective.

### 2.4 Where the manifest schema lives

`schemas/context_manifest.schema.json` lives in the **`context-relay-protocol`** repo alongside `ContextSource`. CRP Comply consumes it. Reason: any CRP integrator (not just Comply customers) should be able to declare and bind a manifest.

### 2.5 SDK impact

The CRP-Comply SDK (deferred to Phase 4.8) will expose a thin wrapper over the protocol primitive:

```python
from crp import ContextManifest, ContextSource, SourceKind

manifest = ContextManifest(system_id="resume-rank-v1", customer_id="acme")
manifest.add(ContextSource(kind=SourceKind.VECTOR_DB, source_id="acme-hr-vdb",
                           origin="declared", trust_level="trusted",
                           contains_pii=True, region="eu-west-1"))
manifest.sign(secret=os.environ["CRP_MANIFEST_SECRET"])
manifest.register()
```

---

## 3. Question 2 — Remediation recommendations

> **User's verbatim question:** *"DO WE RECOMMEND HOW THEY COULD FIX THEIR INCOMPLIANCE"*
>
> **Follow-up (verbatim):** *"JUST SYSTEM PROMPTS AND PROMPT ENGINEERING DONT SOLVE PROBLEMS...WE NEED SOLID SOLUTIONS, THAT CANT BE SHAKEN, REFUSED OR DISPUTED!"* and *"recommendation must be relevant, not too general and TAILORED TO THE USE CASE...start general end narrow (tailored!)"*.

### 3.1 Honest diagnosis

Today, compliance reports surface findings. Phase 4.2's agent can cite regulations. Neither answers *"given this finding, what should I do on Monday morning?"*. A prompt-engineering solution ("instruct the LLM to always propose a fix") is too shaky — an LLM can refuse, drift, or hallucinate. The remediation engine must be **deterministic and verifiable**, not persuasion-based.

### 3.2 Design response — deterministic Controls Catalogue + template renderer

We commit to a catalogue-driven architecture. The LLM does **not** author remediation prose; it fills parameter slots in locked templates.

**Shape** (`src/crp_comply/catalogs/controls/CTRL-*.yaml`, one file per control):

```yaml
id: CTRL-AIACT-HR-72-POSTMARKET-MONITORING
title: Post-market monitoring for high-risk AI systems
regulation_refs:
  - framework: eu_ai_act
    clause_id: "Art. 72"
    chunk_id: corpus://eu_ai_act/regulation_2024_1689/art_72#c1   # resolves to ingested corpus
  - framework: iso_42001
    clause_id: "A.6.2.6"
    chunk_id: corpus://iso/42001/2023/annex_a/a_6_2_6#c1
applies_when:               # AST, not a string parsed by the LLM
  all:
    - fact: risk_level
      op: eq
      value: HIGH
    - fact: system_lifecycle_stage
      op: in
      value: [deployed, post-market]
remediation_template: |
  1. Instrument {observed_inference_endpoints} with structured logging of
     {required_metrics}.
  2. Establish {review_cadence} review meetings owned by {accountable_role}.
  ...
parameters:                 # all drawn from Context Manifest + session facts
  - name: observed_inference_endpoints
    source: manifest.sources[kind=mcp_tool|function_call]
  - name: required_metrics
    source: static
    value: ["accuracy", "false_positive_rate", "drift_score", "latency_p95"]
  - name: review_cadence
    source: static
    value: "monthly"
  - name: accountable_role
    source: context_analysis.roles[responsibility=ai_product_owner]
verification:               # re-runnable, no LLM involved
  - kind: log_schema_conformance
    expects_fields: [timestamp, model_version, input_hash, output, latency_ms]
  - kind: artefact_exists
    artefact: management_review_minutes
    within_days: 180
```

**Runtime flow:**
1. Finding raised → agent looks up candidate controls via `applies_when` evaluation (pure Python AST eval, no LLM).
2. For each matched control, the renderer resolves `parameters` from the Context Manifest + session facts. If a required parameter is missing, the agent asks the user via `clarify_question` — this is how we go "general → narrow / tailored".
3. Template is rendered into a `RemediationPlan`. LLM only fills the `{parameter}` slots; it cannot rewrite the template.
4. `verification` items are checked immediately where possible; deferred items become CAPA entries.

**Hard invariant (not a prompt instruction):** at the orchestrator level, `ComplianceAgent.finalize()` refuses to finalise a session while any finding has an `applies_when`-matched control with no rendered remediation. No prompt-level rule is trusted for this — it's code.

**Regulation-grounded:** every control's `regulation_refs.chunk_id` must resolve to an ingested corpus chunk at build time. CI fails if it doesn't. Remediations are therefore anchored to regulation text we actually possess.

### 3.3 Why this is different from prompt engineering

| Prompt engineering approach | Deterministic approach (what we commit to) |
|---|---|
| LLM decides when to recommend | `applies_when` AST decides |
| LLM authors remediation prose | Template renderer authors prose; LLM fills slots |
| LLM cites regulation from memory | `regulation_refs.chunk_id` must resolve to ingested corpus |
| LLM can skip a finding | Orchestrator refuses `finalize()` if remediation missing |
| Quality = prompt quality | Quality = YAML review + CI validation |

The full refactor (replacing current behaviour) is tracked in [DEFERRED_TODOS.md §1](DEFERRED_TODOS.md).

### 3.4 Scope honesty

We produce *prescriptive compliance-engineering guidance*. We do **not** promise legal advice — every remediation plan carries the boilerplate *"This is a compliance-engineering recommendation. Consult counsel for jurisdiction-specific legal advice."*

---

## 4. Question 3 — Compliance mappings

> **User's verbatim question:** *"DO WE PROVIDE COMPLIANCE MAPPINGS?!?!"*
>
> **Follow-up (verbatim):** *"our mappings need to be accurate as FUCK. IT LITERALLY CAN CAUSE LEGAL PROBLEMS!"* and *"Our own internal ontology isnt really something people can trust us with..they trust the regulations themselves...Couldnt we just generate maybe something along the lines of mappings for a framework, per framework...does cross-framework even need to happen?!"*.

### 4.1 Honest diagnosis

We produce per-framework outputs (GDPR DPIA, AI Act risk classification, ISO 42001 gap scan). The earlier strategic draft proposed a **hub-and-spoke** design where a CRP-internal "compliance objectives" ontology sat between frameworks. **Discarded:** customers trust regulations, not our ontology. Any bridging layer is a liability surface with no trust anchor.

### 4.2 Design response — per-framework mappings, authored against regulation text

Each framework is treated as a first-class deliverable on its own merits. **Cross-framework mapping is optional and queued behind single-framework quality**; see below for the open question.

**Single-framework mapping file** (one per framework): `src/crp_comply/catalogs/frameworks/{framework}.yaml` contains the canonical list of clauses/articles we cover, each with:

```yaml
framework: eu_ai_act
version: "Regulation (EU) 2024/1689"
clauses:
  - clause_id: "Art. 72"
    title: "Post-market monitoring by providers and post-market monitoring plan for high-risk AI systems"
    chunk_id: corpus://eu_ai_act/regulation_2024_1689/art_72#c1   # from ingested corpus
    controls: [CTRL-AIACT-HR-72-POSTMARKET-MONITORING]
    applies_to: [high_risk_providers]
    provenance:
      reviewer: "lead-compliance-eng"
      reviewer_role: "compliance-engineer"
      reviewed_at: 2026-04-30
      status: internal_review
```

**Open question (answer before any cross-framework work starts): does the customer actually need cross-framework mapping?** Strong argument for "no": each framework report standing on its own is legally cleaner; cross-framework assertions are where legal risk concentrates. Strong argument for "yes": enterprise customers running multi-jurisdiction want one source of truth. **Decision recorded in [DEFERRED_TODOS.md §2](DEFERRED_TODOS.md); we do not start cross-framework work until the answer is yes with a named requesting customer.**

**If we do ship cross-framework pairs** (queued): per-pair files like `catalogs/mappings/eu_ai_act_to_iso_42001.yaml`, each row citing *both* regulation chunk_ids (source + target) + reviewer provenance + `mapping_version` hash. No transitive mapping through an internal hub. Every report that cites a cross-framework mapping renders the disclaimer: *"This mapping is our compliance-engineering interpretation, not legal advice. Consult counsel before relying on it for regulatory submission."*

### 4.3 Coverage promise (EU AI Act first)

**Launch focus: EU AI Act.** Measured, CI-enforced, published.

| Framework | Corpus ingested? | In-scope clauses | Launch target | Status |
|---|---|---|---|---|
| **EU AI Act** (Reg. 2024/1689) | ✓ | Arts. 5, 6, 9–17, 26–29, 50, 52, 72, 99, Annex III, Annex IV | **≥90%** | **IMMEDIATE** |
| GDPR | ✓ | Arts. 5, 6, 22, 25, 30, 35, 37 | ≥90% | Queued |
| ISO/IEC 42001:2023 | ✓ (official standard) | All clauses + Annex A | ≥90% | Queued |
| NIST AI RMF 1.0 | Core only — **Playbook needed** | GOVERN/MAP/MEASURE/MANAGE + Playbook actions | ≥90% | **Blocked on Playbook ingestion — see [DEFERRED_TODOS.md §4](DEFERRED_TODOS.md)** |
| ISO/IEC 27001:2022 | ✗ | Annex A AI-relevant controls | Post-launch | Deferred |

**Coverage measurement** (`src/crp_comply/catalogs/coverage.yaml`): for each framework, `covered_clauses / total_in_scope_clauses`. CI fails if EU AI Act coverage drops below 90% at launch. Report artefacts render an explicit "Not covered" label for any in-scope clause without a mapped control.

**Explicitly deferred (post-launch, surface "not covered" in reports):** ISO/IEC 23894, ISO/IEC 42005, UK AI regulatory principles (2024), CCPA/CPRA, NYC Local Law 144.

---

## 5. Updated CRP-Comply deliverables catalogue

This is the new, authoritative list of artefacts a paying customer receives, superseding earlier scoping.

### 5.1 Current deliverables (shipped, keep)

| # | Artefact | Route | Tier |
|---|----------|-------|------|
| 1 | Risk Assessment (EU AI Act Art. 6) | `POST /api/v1/risk-assessment` | FREE+ |
| 2 | Compliance Report | `POST /api/v1/compliance-report` | FREE+ |
| 3 | DPIA (GDPR Art. 35) | `POST /api/v1/dpia` | PRO+ |
| 4 | Transparency Declaration (AI Act Art. 50) | `POST /api/v1/transparency` | PRO+ |
| 5 | Technical Documentation (AI Act Art. 11) | `POST /api/v1/technical-docs` | PRO+ |
| 6 | Session Audit (CRP envelope audit trail) | `POST /api/v1/session-audit` | PRO+ |
| 7 | Evidence Pack (zip) | `POST /api/v1/evidence-pack` | PRO+ |
| 8 | Agent session (LLM reasoning) | `POST /api/v1/agent/start` | PRO+ |
| 9 | Signed Certificate | `POST /api/v1/certificate` | CLOUD |

### 5.2 New deliverables (Phase 4.7, committed)

| # | Artefact | Clause / Article backing | Tier |
|----|----------|-------------------------|------|
| 10 | **Context Manifest** (registration + validation) | ISO 42001 §4.1–4.2 | PRO+ |
| 11 | **Context Analysis document** | ISO 42001 §4.1–4.3 | PRO+ |
| 12 | **AI Policy** | ISO 42001 §5.2; explainer *AI Policy: Characteristics and Components* | PRO+ |
| 13 | **AI Strategy** | explainer *AI Strategy* | PRO+ |
| 14 | **Risk Register** (Clause 6.1.2) | ISO 42001 §6.1.2 | PRO+ |
| 15 | **Risk Treatment Plan** (Clause 6.1.3) | ISO 42001 §6.1.3 | PRO+ |
| 16 | **AI Impact Assessment** (Clause 6.1.4 + Annex B) | ISO 42001 §6.1.4; AI Act Art. 27 | PRO+ |
| 17 | **Competence Matrix** | ISO 42001 §7.2; explainer *AI Competence Model* | ENTERPRISE+ |
| 18 | **Documented Information Register** | ISO 42001 §7.5 | PRO+ |
| 19 | **Internal Audit Programme** | ISO 42001 §9.2 | ENTERPRISE+ |
| 20 | **Management Review Minutes template** | ISO 42001 §9.3 | ENTERPRISE+ |
| 21 | **Corrective Action register (CAPA)** | ISO 42001 §10.1 | PRO+ |
| 22 | **Cross-Framework Crosswalk** (ISO 42001 ↔ AI Act ↔ GDPR ↔ NIST ↔ 27001) | N/A (our own artefact) | PRO+ |
| 23 | **Remediation Plans** (one per finding) | Controls Catalogue | PRO+ |

The **Evidence Pack** is updated to bundle all applicable artefacts (10–23) alongside the existing ones, producing a pre-audit-ready submission.

---

## 6. Phase plan

```
Phase 4.6 ✓  Agent API endpoints                           — SHIPPED in this commit
Phase 4.7    Context-Source provenance + EU AI Act focus:
             4.7.0  (context-relay-protocol) ContextSource/SourceKind primitive,
                    Fact.source field, assemble_messages propagation,
                    detective-mode parser, [CONTEXT_SOURCES] envelope section,
                    CONTEXT_ATTESTATION_MISMATCH audit event                [PROTOCOL PR]
             4.7.1  (context-relay-protocol) ContextManifest type + schema   [PROTOCOL PR]
             4.7.2  (crp-comply) consume ContextSource, produce Context
                    Analysis deliverable, GDPR Art. 30 RoPA, attestation
                    findings in compliance reports
             4.7.3  (crp-comply) EU AI Act coverage.yaml + CI gate ≥90%
             4.7.4  (crp-comply) Controls Catalogue skeleton (deterministic
                    templates) — see DEFERRED_TODOS.md §1
             4.7.5  (crp-comply) Risk Register + Risk Treatment Plan + AI
                    Impact Assessment endpoints
             4.7.6  (crp-comply) AI Policy / AI Strategy template generators
             4.7.7  (crp-comply) Internal Audit Programme, Management Review,
                    CAPA register, Competence Matrix, Documented Information
                    Register
Phase 4.8    SDK (ContextManifest helpers + BYOK)           — deferred
Phase 4.9    Evaluations + BYOK LM Studio demo video        — deferred
```

Items tracked but not in the above phase plan live in [DEFERRED_TODOS.md](DEFERRED_TODOS.md). Each 4.7.x milestone ships with tests, updates this document's deliverables table, and extends `docs/CRP_CAPABILITIES.md`.

---

## 7. What this commit ships

* `src/crp_comply/api/agent.py` — full Phase 4.6 agent router (start / list / get / clarify / finalize / delete).
* `src/crp_comply/api/models.py` — new Pydantic models (`AgentStartRequest`, `AgentSessionState`, `AgentClarifyRequest`, `AgentFinalizeRequest`, `AgentFinalizeResponse`, `AgentSessionList`).
* `src/crp_comply/api/auth.py` — new `agent_intelligence` feature gate on PRO/ENTERPRISE/CLOUD tiers.
* `src/crp_comply/api/reports.py` — `agent_session` registered as a persistable report kind.
* `src/crp_comply/api/app.py` — mounts the agent router under `/api/v1`, initialises session store in the lifespan.
* `src/crp_comply/agent/ingest/explainer_extract.py` — headings-only metadata extractor; the explainer body text is not indexed (copyright-safe).
* `corpus/iso/42001/explainer/benraouane_2024.md` — the explainer, moved into the ISO 42001 tree, tagged as third-party commentary (redaction-aware).
* `corpus/iso/42001/explainer/benraouane_2024.headings.json` — 161-heading pointer index used for citations in this document.
* `tests/test_api_agent.py` — 16 new tests covering auth, tier gating, validation, clarify-resume, session listing, isolation, finalize, delete, and error-path.

**Test suite:** 248/248 passing (previously 232; +16).

---

## 8. Non-goals (explicit)

To avoid scope creep, this reassessment explicitly does **not** commit to:

* Static analysis of customer source code (out of scope — we are a runtime + reasoning layer).
* Automatic generation of model cards from customer infrastructure (we generate the *document*, we do not introspect weights).
* Legal opinions (we produce compliance engineering guidance only).
* Replacement of a certified auditor — our Evidence Pack is audit-ready; the auditor still audits.

---

## 9. Attribution

Benraouane, S. A. (2024). *AI Management System Certification According to the ISO/IEC 42001 Standard — How to Audit, Certify, and Build Responsible AI Systems.* Routledge / Taylor & Francis Group, LLC. ISBN 978-1-032-73397-5. Used as a structural reference. No body prose reproduced in CRP-Comply artefacts.
