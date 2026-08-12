# Compliance-Model Gap Tracker — single source of truth

**Date opened:** 2026-04-24
**Last consolidation:** 2026-04-25
**Owner:** engineering lead

This document consolidates every "remaining work" tracker in the repo into a
single ledger. It supersedes — and is the reason we deleted — the following
historical files:

- `TODO.md` (high-level Phase 1/2/3 list)
- `DEFERRED_ITEMS.md` (product/positioning deferrals)
- `DEFERRED_TODOS.md` (engineering deferrals)
- `REMAINING_WORK.md` (launch-blocker punch list)
- `DESIGN_GAP_ASSESSMENT.md` (LLM-intelligence design gaps)
- `PHASE3_FEASIBILITY_AND_GAPS.md` (Stripe/Railway manual checklist)

If you need rationale for a deferral, the reason is now inline in §C below.
Companion docs that survive (intentionally narrower scope):

- [STRATEGIC_REASSESSMENT.md](STRATEGIC_REASSESSMENT.md) — product scope.
- [UI_UX_REDESIGN.md](UI_UX_REDESIGN.md) — UX spec.
- [PRODUCT_SECURITY.md](PRODUCT_SECURITY.md) — OWASP posture, residual sec gaps.
- [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md) — go-live checklist.
- [RECIPE_COVERAGE_TRACKER.md](RECIPE_COVERAGE_TRACKER.md) — recipe-by-article matrix.

Legend: ✅ shipped · 🟡 partial · ❌ missing · 🔵 deferred

---

## A. §6 audit — "interaction model that matches the regulatory model"

The original brutal-honest audit against
[COMPLIANCE_MODEL_ANALYSIS.md](COMPLIANCE_MODEL_ANALYSIS.md) §6 named nine
specific surface deficits. Status today:

| # | Gap | Status |
|---|---|---|
| 1 | Agent quality — article-cited Socratic interviews | ✅ DSL + enumeration shipped; in-loop branch ordering at agent layer pending |
| 2 | Recipe ↔ Agent — one drafting surface | 🟡 backend bridge shipped; frontend collapse pending |
| 3 | Evidence substrate — proxy queryable from drafting | ✅ shipped (`build_query_proxy_metrics_tool`) |
| 4 | Artefact intake — wired to drafting | ✅ shipped (`build_fetch_artefact_tool`) |
| 5 | Programme tracker — obligation lifecycle states | ✅ shipped (8-state machine + REST + tests) |
| 6 | Provenance tagging — per-paragraph attribution | ✅ shipped backend + frontend pills |
| 7 | Live / keep-current deliverables | ✅ shipped (`DerivationManifest` + staleness endpoint) |
| 8 | Bucket A/B/C honesty in UI | ✅ shipped (`BUCKET_META`) |
| 9 | Three-layer framing on Guide | ✅ shipped |

**Bottom line:** all nine gaps have substrate and tests. Eight are shipped
end-to-end. Gap 2 awaits a frontend collapse only (substrate + REST live).

Detailed evidence and "what remains" sub-bullets for each of the nine gaps
were preserved in git history before this consolidation; the canonical record
of *what shipped* is in the tests and modules below:

| Gap | Module | Tests |
|---|---|---|
| 1 | [src/crp_comply/recipes/loader.py](src/crp_comply/recipes/loader.py), [src/crp_comply/recipes/human_inputs.py](src/crp_comply/recipes/human_inputs.py) | [tests/test_interview_branches.py](tests/test_interview_branches.py) |
| 2 | [src/crp_comply/api/draft_sessions.py](src/crp_comply/api/draft_sessions.py) | covered by `tests/test_api.py` |
| 3 | [src/crp_comply/agent/tools.py](src/crp_comply/agent/tools.py) | [tests/test_evidence_substrate.py](tests/test_evidence_substrate.py) |
| 4 | [src/crp_comply/agent/tools.py](src/crp_comply/agent/tools.py) | [tests/test_evidence_substrate.py](tests/test_evidence_substrate.py) |
| 5 | [src/crp_comply/programme/lifecycle.py](src/crp_comply/programme/lifecycle.py) | [tests/test_programme_lifecycle.py](tests/test_programme_lifecycle.py) |
| 6 | [src/crp_comply/recipes/executor.py](src/crp_comply/recipes/executor.py) | [tests/test_batch3_rerank_provenance.py](tests/test_batch3_rerank_provenance.py) |
| 7 | [src/crp_comply/recipes/derivation.py](src/crp_comply/recipes/derivation.py) | [tests/test_derivation_manifest.py](tests/test_derivation_manifest.py) |
| 8 | `frontend/src/pages/v2/RecipeLibrary.tsx` | n/a (UI) |
| 9 | `frontend/src/pages/v2/Guide.tsx` | n/a (UI) |

---

## B. Engineering work still genuinely outstanding

**Verified against the codebase on 2026-04-25.** Many items in the
historical trackers (rate-limiting, Ed25519 evidence signing, model
routing, Stripe billing, pip-audit + bandit in CI, PII pre-LLM
redaction, clarification-budget cap, continuation, contradiction
detection) were already shipped — those rows are now removed.

Severity legend: 🟥 launch-blocking · 🟧 strongly advised · 🟩 nice-to-have

### B1. 🟥 Frontend collapse — Workspace + AgentChat → Draft (Gap 2 UI)

Backend bridge primitive lives at `/api/v1/drafts`. UI still ships the
two parallel surfaces. Merge `Workspace.tsx` + `AgentChat.tsx` into a
single `Draft.tsx` driven by the bridge; wire "Save to vault" to
`POST /drafts/{id}/report`.

### B2. 🟥 Eval suite expansion — 3 → 20 cases

`src/crp_comply/evals/cases/ai_act_basic/` ships 3 YAML cases
(CV screening, social scoring, chatbot). Design target is ≥20 covering
EU AI Act, GDPR, ISO 42001, NIST AI RMF. New suites should land at
`evals/cases/{gdpr,iso42001,nist_rmf}/` and the CI step in
[.github/workflows/ci.yml](.github/workflows/ci.yml) should fail
under 95% pass rate against the stub agent.

### B3. 🟥 Deliverable recipes — v1 must-haves still missing

Per [RECIPE_COVERAGE_TRACKER.md](RECIPE_COVERAGE_TRACKER.md), four v1
must-haves do not yet have recipes:

- EU AI Act **Art. 27 Fundamental Rights Impact Assessment (FRIA)**
- ISO 42001 **Statement of Applicability (SoA)**
- ISO 42001 **AI Risk Assessment (ISO 23894 methodology)**
- **NIST AI RMF Profile (Govern / Map / Measure / Manage)**

Four more upgrade existing template endpoints to agent recipes:
EU AI Act Annex IV Tech Docs, EU AI Act Art. 13 Transparency Decl.,
GDPR Art. 35 DPIA, Conformity Evidence Pack.

### B4. 🟧 LLM-driven gap discovery harness

A real LLM run (even on a tiny local model) catches integration bugs
that fixture-based tests miss. We now have one: see
[tests/test_llm_integration_lmstudio.py](tests/test_llm_integration_lmstudio.py).
Skip-by-default; opt in by setting `CRP_COMPLY_LIVE_LLM_BASE_URL`.
Default model `gemma-3-270m-it-qat` at `http://192.168.0.6:1234`.

### B5. 🟧 Streaming tokens to frontend (SSE)

`ComplianceLLM.chat_with_tools` returns the whole response. The
frontend chat would feel alive with token streaming. Provider
adapters already support it; needs SSE plumbing through the agent
endpoints.

### B6. 🟧 SDK Mode C — long-poll worker

`crp-comply worker --lmstudio …` not yet shipped in
`sdk/src/crp_comply_sdk/`. Server-side WebSocket channel also missing.
Mode A (cloud BYOK) and Mode B (HTTPS tunnel) work today.

### B7. 🟧 Per-task model routing usage in agent

`api/model_router.py` exists. Orchestrator currently picks one model
per session. Wire the router so extraction → cheap, drafting → mid,
contradiction → high.

### B8. 🟧 Token-accounting telemetry

`api/usage.py` counts calls. Add `input_tokens`, `output_tokens`,
`provider`, `model`, `latency_ms`, `cost_usd` per call to enable the
managed-pass-through pricing tier.

### B9. 🟧 Agent-loop wiring of unused CRP primitives

Per [LLM_INTELLIGENCE_DESIGN.md](LLM_INTELLIGENCE_DESIGN.md) §3.3, three
primitives are still unused inside the orchestrator:

- `crp.envelope.packer` / `reranker` / `scoring` — orchestrator builds
  messages by hand. Switching unlocks the "Llama-with-CRP beats
  Claude-without" claim.
- `crp.extraction.pipeline` — free-text user messages should flow
  through the 6-stage extractor, not just tool-call output.
- `crp.ckf.pattern_query` — `recall_facts` calls plain CKF reads;
  pattern_query enables structural queries (e.g. all unmitigated
  high-risk findings for a system).

### B10. 🟧 Bidirectional mid-draft interrupts

Resume after clarification works. "Actually, the system runs in
Germany only — please redraft" mid-generation does not. Requires
WebSocket push-pull on top of the existing chat endpoints.

### B11. 🟧 Tier-feature matrix end-to-end audit

`SDK_FEATURE_MATRIX` exists in `api/sdk.py`; no test asserts every
endpoint actually denies on out-of-tier access. Add fuzz coverage in
`tests/test_auth.py` that walks every endpoint × every tier.

### B12. 🟧 Tenant-configurable retention windows

`api/retention.py` defaults are 180 d reports / 365 d evidence.
Surface as a per-user setting before first Enterprise customer.

### B13. 🟧 Reports vault renders provenance pills

`Workspace.tsx` renders pills via `LiveBinder`. The Reports vault page
should render the same `ProvenancePill` primitive against
`json_payload.sections[].paragraphs`.

### B14. 🟧 Programme.tsx — render all 8 lifecycle sub-states

Currently collapses to 4. The 8-state enum is live; the colour bands
should map 1:1.

### B15. 🟧 Live staleness badge on report cards

`GET /reports/{id}/staleness` is on-demand only. A background watcher
should pre-compute `is_stale` for the dashboard badge.

### B16. 🟧 Public marketing-site framing parity

Landing + Pricing should echo the three-layer framing (programme /
artefacts / evidence). Stop calling the proxy "optional" — it IS the
evidence layer for Bucket C deliverables.

### B17. 🟩 Per-user CKF export

`GET /ckf/export` → tarball — needed for GDPR Art. 20 portability of
the customer's own fact graph.

### B18. 🟩 Per-host scraper rate-limit review

`scrapers/base.py` has per-host `time.sleep`. Audit delays before any
weekly cron escalates throughput.

### B19. 🟩 Live Regulation CI hardening

`live-regulation-ci.yml` has `contents:write` + `pull-requests:write`.
Replace with deploy key or GitHub App scoped to `corpus/**` only.

---

## C. Deferred backlog (decisions to NOT ship now, with revisit triggers)

Each row is a decision recorded with a reason and a revisit trigger.

### C1. Product / monetisation

| Item | Why deferred | Revisit when |
|---|---|---|
| Annual billing discount | Monthly first; simpler | After first 10 paying customers |
| Usage-based overage charges | Flat tiers cleaner for v1 | Business tier > 20 customers |
| Free-tier conversion experiments | Need paid tiers genuinely differentiated first | After agent UI ships |

### C2. Regulation corpus — out of v1

| Item | Why deferred | Revisit when |
|---|---|---|
| DORA, MiCA | Sectoral / out of scope | If a fintech customer asks |
| Chinese GenAI Measures + CAC rules | Translation + legal-review cost | If a China-serving customer requests as Enterprise pack |
| Full MDR / FDA SaMD (medical AI) | Sectoral, highly specialised | Healthcare vertical |
| Copyright case law | Case law, not primary regulation | Not planned as corpus |
| All 27 EU NIS2 transpositions | ~100h curation in many languages | Per Enterprise jurisdiction |
| ISO/IEC 27001 as primary corpus | Not AI-specific | Enterprise add-on pack |
| US EO 14110 + Federal Register | Behind US tier demand | Enterprise pack on demand |
| US state AI laws (CO, NYC, CA) | One state per customer ask | Enterprise pack on demand |
| Singapore Model AI Governance | Behind APAC demand | Enterprise pack on demand |
| Canada AIDA + Quebec Law 25 | AIDA not yet in force | When AIDA enters force |
| ISO/IEC 23053:2022 | Optional companion | If user supplies |
| NIST AI RMF Playbook | Need Playbook, not just Core, for actionable mappings | Before NIST claims enter customer-facing deliverables |

### C3. Features explicitly out of v1

| Item | Why deferred | Revisit when |
|---|---|---|
| Fine-tuned domain LLM | Curated context > fine-tuning | If hosted-LLM bill > $10k/mo AND retrieval plateaus |
| Multi-agent crew | Token cost + debug pain | Not planned |
| Agentic loops over external systems (Slack/GitHub/prod) | Security blast-radius | Enterprise custom only |
| Autonomous scheduled agent runs | Cost determinism | After retention data shows pull-demand |
| RLHF feedback loop | Premature; small-N noisy | After > 1000 agent runs |
| Voice / meeting transcription | Scope creep | Not planned |
| Mobile app | Web is enough | After 50 paying customers ask |
| Bidirectional mid-draft interrupts | See B10 | UI re-architecture |

### C4. UI / UX deferrals

| Item | Why deferred | Revisit when |
|---|---|---|
| Dark mode / theme variants | Not a blocker | Post-launch polish |
| WCAG-AA accessibility audit | Current product passes basic checks | Before first Enterprise signature |
| Public marketing-site polish | Agent is the value unlock | After agent live + 5 paying customers |

### C5. Security / compliance hardening

| Item | Why deferred | Revisit when |
|---|---|---|
| SOC 2 Type I | ~$20k + 3 mo engagement | First Enterprise prospect blocker |
| SOC 2 Type II | Follows Type I | After Type I |
| ISO 27001 cert of CRP-Comply itself | Meta-compliance; no buyer ask | When asked |
| Penetration test (external) | ~$8k; premature pre-revenue | Before first Business-tier paid deployment |
| EU-region-only deployment option | Railway can't pin EU-only credibly | Move to Fly.io / dedicated VPC when asked |

### C6. Observability / ops

| Item | Why deferred | Revisit when |
|---|---|---|
| Centralised log aggregation (Datadog / BetterStack) | Railway logs OK for < 10 customers | > 5 paying customers OR > 1 incident |
| Public uptime status page | Premature | Before first Business-tier SLA customer |
| PagerDuty / on-call rotation | Solo dev | After Business tier has 3+ customers |

### C7. Integrations

| Item | Why deferred | Revisit when |
|---|---|---|
| Slack app | Nice-to-have | On customer request |
| MS Teams app | Enterprise-adjacent | Enterprise request |
| Jira / Linear remediation push | Useful but scope | After Business tier ships |
| SSO (SAML/OIDC) | Required for Enterprise | Before first Enterprise signature |
| SCIM user provisioning | Enterprise-only | Before first Enterprise > 50 seats |

### C8. Documentation debt

| Item | Why deferred | Revisit when |
|---|---|---|
| Curated API reference at /docs/api | OpenAPI auto-generated page exists | After v0.3.0 SDK |
| Video walkthroughs | Text docs first | After UI redesign |
| Customer case studies | Need customers first | After 3 signed logos agree to publish |

### C9. Continuous-monitoring deliverables

| Deliverable | Why deferred | Revisit when |
|---|---|---|
| ISO 42001 §9.2 internal audit report | Needs running-history baseline | After customers have 3+ months of records |
| ISO 42001 §9.3 management review minutes | Same | Same |
| EU AI Act Art. 71 post-market monitoring plan | Needs production telemetry from customer | When SDK audit-log adoption hits 5+ customers |
| Auto-generated logs per Art. 18–19 | Continuous, customer-side via SDK | Ongoing — SDK v0.3.0 |

### C10. Larger refactors deferred

| Item | Why deferred | Trigger |
|---|---|---|
| Deterministic remediation engine (controls/ YAML catalogue) | Must not be prompt-engineered; needs Context-Source protocol work first | After Context-Source lands in CRP |
| Regulation-to-regulation mappings (per-pair files) | Requires open question: do customers want crosswalks at all, or per-framework reports only? | After 5+ controls ship |
| Coverage tracking (≥ 90% EU AI Act articles, CI-enforced) | Ships with first control-catalogue release | Alongside controls/ |

---

## D. Hygiene

| # | Item | Status |
|---|---|---|
| D1 | Revoke any pasted PyPI tokens | OWNER ACTION |
| D2 | Gitignore `_*.txt` / `_*.py` scratch files | TODO |
| D3 | Gitignore `crp_sessions/` (user data) in CRP main repo | TODO (cross-repo) |
| D4 | Drop `crp-data-snapshot.tgz` from repo / move to releases | TODO |
| D5 | Verify ISO 42001 explainer DOCX redistribution licence | DONE — stored by clause ID, body not republished |
| D6 | Frontend lint/type-check in CI | ✅ shipped |
| D7 | Frontend `vitest` test step in CI | TODO |
| D8 | SDK release pipeline (`.github/workflows/release.yml` is server-only) | TODO |

---

## E. Process

1. When something newly outstanding is discovered, add a row to §B (engineering)
   or §C (deferred-decision) with owner + trigger.
2. When an item ships, mark the row ✅ and move it to the relevant module's
   test file as the canonical record. Do **not** keep a "shipped" graveyard
   here — git history is the audit trail.
3. Quarterly: re-read §C and reassess every "Revisit when" trigger.

---

**End of consolidated tracker.**
