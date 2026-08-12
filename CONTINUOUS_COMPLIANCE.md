# Continuous Compliance — How CRP-Comply Proves It At Any Moment

**Purpose:** Answer the question *"Is our proxy/connector to the customer's system actually like this — can it continually audit and, at any point, produce and explain why the system is or is not compliant?"*

**Short answer:** yes. This document describes the data path, the evidence store, the on-demand audit endpoint, and the narrated-gap report — and what is built today vs. what is still scheduled.

**Last updated:** 2026-04-23 (Phase 4.1c)
**Related:** [OFFICIAL_SOURCES.md](OFFICIAL_SOURCES.md), [LLM_INTELLIGENCE_DESIGN.md](LLM_INTELLIGENCE_DESIGN.md), [USER_PROVIDED_DOCS.md](USER_PROVIDED_DOCS.md)

---

## 1. The three promises

The product must, at any moment in a customer's lifecycle, be able to:

1. **Observe** — capture every AI/data interaction in the customer's system in real time (the "proxy/connector").
2. **Decide** — compute, per regulation clause, whether the current state is compliant, non-compliant, or unknown.
3. **Explain** — emit a human-readable report that cites the clause, quotes (or redacts) the authoritative text, enumerates the evidence behind each decision, and lists concrete remediation steps.

Each of the three sections below maps one promise to the concrete code path and data artefact that delivers it.

---

## 2. Observe — the connector path

### 2.1 SDK + proxy (built)

Customers integrate CRP-Comply in one of two modes, both of which emit the same event schema into the CKF (Compliance Knowledge Fabric):

| Mode | Code path | What gets captured |
|---|---|---|
| **In-process SDK** | `sdk/` → the customer imports our client and wraps their LLM calls / data access | Request + response + metadata (model, prompt hash, user id, decision, latency) |
| **Proxy** | `src/crp_comply/proxy/` (interceptor.py + routes.py) — sits between the customer app and the model provider | Same event schema, no code changes in the customer app |

Both paths write into the **CKF event log** — a single append-only ledger keyed by (customer_id, system_id, timestamp). Every event carries:

- `system_id` — which AI system in the customer's estate this belongs to
- `event_kind` — `inference`, `training_run`, `data_ingest`, `human_review`, `incident`, `policy_change`, `evidence_upload`
- `payload` — the raw material the auditor needs (prompt hash, model card id, output class, PII flags, guardrail decisions, etc.)
- `provenance` — who/what produced it, what SDK version, what policy version

### 2.2 Tenant-supplied evidence (built)

Not everything is a live event. Some controls are satisfied by artefacts (risk register, DPIA, model card, test reports). The SDK exposes `evidence_upload(system_id, kind, file)` which normalises these into the same CKF ledger so the audit engine sees one store.

### 2.3 What this means for continuous audit

Because every interaction and every artefact lands in the CKF **as it happens**, the system already has, at any wall-clock instant, the complete factual basis for answering "are you compliant right now?". The audit engine does not need to *re-collect* — it reads.

---

## 3. Decide — the on-demand audit engine

### 3.1 The compliance graph

Each regulation in [OFFICIAL_SOURCES.md](OFFICIAL_SOURCES.md) is expanded into a **control graph**:

```
regulation ──► clause (e.g. EU AI Act Art. 9 §3) ──► control (e.g. "risk management system documented")
                                                   ──► evidence_requirement (e.g. "risk register present + reviewed in last 12mo")
                                                   ──► verdict_rule (SQL-style predicate over CKF)
```

The corpus indexed in Phase 4.1b + 4.1c (1,574 chunks across 11 sources) is the **text backbone** of this graph. Clause titles and bodies (or surrogates for ISO) let the retrieval layer surface the right clause for any question, and the LLM composes the narrative. The verdict_rules themselves are authored as structured predicates — not free-text prompts — so every verdict is deterministic and replayable.

### 3.2 The audit call

```python
from crp_comply.agent.audit import compliance_audit

report = compliance_audit(
    customer_id="acme",
    system_id="acme-claims-triage",
    frameworks=["eu_ai_act", "iso_42001", "gdpr"],  # pick any subset
    at_timestamp=None,  # None = right now; any iso-8601 = point-in-time replay
)
```

The engine:

1. Freezes the CKF state at `at_timestamp` (or "now").
2. Resolves every in-scope clause → control → evidence_requirement from the compliance graph.
3. For each evidence_requirement, evaluates its `verdict_rule` against the frozen CKF state.
4. Produces a per-clause verdict: `compliant` | `non_compliant` | `insufficient_evidence` | `not_applicable`.
5. For each non-compliant/insufficient verdict, performs a RAG retrieval against the clause id + the verdict_rule narrative to pull the authoritative clause text (or redacted surrogate for ISO).
6. Renders a report (see §4).

Because step 1 is a snapshot and step 3 is deterministic, **the same (customer_id, system_id, at_timestamp) triple always produces the same verdict**. This is what makes the audit trail defensible.

### 3.3 Corpus versioning

The `corpus/_scraped/manifest.json` records, per source: `source_id`, `version`, `content_hash`, `scraped_at`. Every report cites the manifest entry, so a verdict produced on 2026-04-23 against `eu_ai_act@consolidated-2024-08-01` stays reproducible even after the regulation changes — you simply re-run against the new corpus version and diff.

---

## 4. Explain — the narrated-gap report

A report bundle (Markdown + JSON + evidence archive) contains, per clause:

- **Clause citation** — e.g. "EU AI Act, Article 9(3)" with link to https://eur-lex.europa.eu/... from [OFFICIAL_SOURCES.md](OFFICIAL_SOURCES.md)
- **Verdict** — compliant / non-compliant / insufficient / n/a
- **Why** — the verdict_rule's human-readable predicate ("risk register exists AND was reviewed in last 365 days AND covers this system_id")
- **Evidence** — the actual CKF records that satisfied or failed the predicate (event ids, artefact hashes, timestamps)
- **Authoritative text** — for verbatim-allowed sources (EU/NIST/OECD/CoE/UK/EDPB) the quoted clause; for ISO the **redacted surrogate** plus the publisher URL
- **Remediation** — concrete next actions, generated by the model from the gap + clause text, cross-linked to the customer's framework of choice (e.g. "Upload a DPIA satisfying GDPR Art. 35 at `/evidence/dpia/acme-claims-triage`")

Because the evidence is a hash-pinned record in CKF, not a free-text claim, the report is **auditor-defensible**: a regulator or external auditor can ask to see event `ckf-evt-01J...` and get the original payload back byte-for-byte.

---

## 5. What is built vs. what is scheduled

Being explicit about v1 scope — this is the deliverable-reality map:

| Capability | Status | Code / artefact |
|---|---|---|
| SDK event capture | ✅ built | `sdk/` |
| Proxy event capture | ✅ built | `src/crp_comply/proxy/` |
| CKF append-only ledger | ✅ built (per earlier phases) | core store |
| Evidence upload | ✅ built | SDK + API endpoints |
| Regulation corpus scraped + indexed | ✅ built (Phase 4.1 / 4.1b / 4.1c — 1,574 chunks, 11 sources) | `corpus/_scraped/`, `data/rag_index/` |
| Copyright-safe ISO handling (redact-on-ingest) | ✅ built (Phase 4.1c) | `src/crp_comply/agent/copyright.py` |
| Compliance graph (clause → control → verdict_rule) | 🟡 **next milestone (Phase 4.2)** | to be authored per framework; EU AI Act first |
| `compliance_audit(...)` on-demand engine | 🟡 **next milestone (Phase 4.2)** | scaffolded in agent, verdict engine to be written |
| Point-in-time replay | 🟡 depends on CKF timestamp indexing — already append-only, indexing present | |
| Narrated-gap report renderer | 🟡 **next milestone (Phase 4.2)** — depends on the two above | |

**Interpretation:** the *observability substrate* (Promise 1) is live today. The *corpus backbone* for Promise 2 and Promise 3 is live today (verified end-to-end: 1,574 chunks, EU AI Act retrieval returning Article 48 CE marking at score 0.885, ISO 42001 retrieval returning redacted surrogates at score 0.80). The *verdict engine + report renderer* that bind observability to the corpus are the next milestone (Phase 4.2), which is why this document ends with a clear map rather than a demo video.

Once Phase 4.2 lands, every customer will be able to call `compliance_audit(...)` at any wall-clock moment, or over any historical window, and receive a report that explains — clause by clause, with cited authoritative text or redacted-surrogate-plus-URL for ISO, and hash-pinned CKF evidence — why the system is or is not compliant.
