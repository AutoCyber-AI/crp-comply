# HANDOFF — Session Transfer Note

**Last session ended:** 2026-04-24
**Branch:** `master` (3 commits ahead of `origin/master`)
**Last commit on disk:** `bf69bea` — *"BATCH 10: tenant isolation hardening + human-input auto-dispatch"*
**Working tree:** dirty — UI/UX redesign in progress (see §3)

## Email delivery for the free assessment

The `/api/v1/public/email-report` endpoint sends the analyst memo by trying transports in this order — set ONE on the deploy:

- `RESEND_API_KEY` (recommended; HTTP, no SMTP juggling). Optional `CRP_COMPLY_EMAIL_FROM="CRP Comply <noreply@yourdomain>"` (default sender domain must be verified in Resend).
- SMTP fallback: `SMTP_HOST`, `SMTP_PORT` (default 587), `SMTP_USER`, `SMTP_PASSWORD`, optional `CRP_COMPLY_EMAIL_FROM`.
- If neither is set the lead is recorded in SQLite and the response tells the caller why; nothing is dropped silently.

### Sending from a Gmail address (no Resend account required)

Gmail SMTP works on Railway with a **Google App Password** (not your normal Gmail password). Generate one at https://myaccount.google.com/apppasswords (requires 2FA on the Google account). Then set on Railway:

```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=contact@crprotocol.io      # your Gmail address (or Workspace alias)
SMTP_PASSWORD=<16-char app password>  # NOT your Google password
CRP_COMPLY_EMAIL_FROM=CRP Comply <contact@crprotocol.io>
```

Notes:
- Free Gmail accounts are capped at ~500 emails/day; Workspace accounts at ~2000/day. Fine for the free-assessment funnel.
- The "from" address must match `SMTP_USER` (or be a verified send-as alias on that Gmail account); otherwise Gmail will rewrite it.
- Resend exists for higher volume + per-domain reputation, but for a small landing-funnel Gmail SMTP is the simpler path.

## Optional UIE extractor (Stage 4)

The `crp` SDK logs `UIE not available — Stage 4 will be skipped` on startup when no `uie` package is importable. Stage 4 is a SHOULD-tier optional extractor; the four-stage pipeline degrades cleanly to Stages 1–3 (tagger + GLiNER + relation classifier). No user-facing feature depends on it. The warning is informational; ignore unless a benchmark calls for relational triple extraction.

> **New agent: read this file first, then the three companions in §1.**
> Everything else is supporting material indexed in §2.

---

## 1. The canonical docs (read in this order)

| # | Document | Why it's canonical |
|---|---|---|
| 1 | [STRATEGIC_REASSESSMENT.md](STRATEGIC_REASSESSMENT.md) | Product-level scope. Answers the four customer questions. |
| 2 | [COMPLIANCE_MODEL_GAPS.md](COMPLIANCE_MODEL_GAPS.md) | **Single source of truth** for outstanding work, deferrals, and hygiene. Replaces the previous `TODO.md` / `REMAINING_WORK.md` / `DESIGN_GAP_ASSESSMENT.md` / `DEFERRED_ITEMS.md` / `DEFERRED_TODOS.md` / `PHASE3_FEASIBILITY_AND_GAPS.md` (deleted 2026-04-25). |
| 3 | [UI_UX_REDESIGN.md](UI_UX_REDESIGN.md) | UX spec (12-page IA). §9–§11 normative for the frontend. |
| 4 | [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md) | Go-live scorecard + pre-launch checklist. |

If the docs disagree: `STRATEGIC_REASSESSMENT.md` wins on scope, `UI_UX_REDESIGN.md` wins on UX, `COMPLIANCE_MODEL_GAPS.md` wins on "is this launch-blocking?".

---

## 2. Full doc index (what each file is for)

**Specification & scope**
- `STRATEGIC_REASSESSMENT.md` — canonical scope (see §1).
- `COMPLIANCE_MODEL_GAPS.md` — canonical work tracker (see §1).
- `UI_UX_REDESIGN.md` — canonical UX spec (see §1).
- `REDESIGN_STRATEGY.md` — earlier architectural redesign (tier matrix, monetisation framing).
- `COMPLIANCE_MODEL_ANALYSIS.md` — the brutal §6 audit that the gaps tracker is built on.

**Operational / security / delivery**
- `PRODUCT_SECURITY.md` — OWASP Top-10 posture + residual gap tracker.
- `PRODUCTION_READINESS.md` — go-live checklist (functional / security / ops / compliance).
- `ENTERPRISE_DELIVERY_PLAYBOOK.md` — enterprise GTM + BYOK narrative.
- `HOSTING_POSITIONING.md` — deploy/host story.
- `CONTINUOUS_COMPLIANCE.md` — live-regulation CI + diff engine.
- `STRIPE_MONETISATION.md` — billing architecture.

**Catalogues & trackers (living)**
- `RECIPE_COVERAGE_TRACKER.md` — every EU AI Act / ISO 42001 / NIST / GDPR article ↔ recipe mapping. Update alongside every recipe batch.
- `LLM_INTELLIGENCE_DESIGN.md` — the 7-primitive LLM layer + agent design.
- `OFFICIAL_SOURCES.md` — regulation source-of-truth URIs used by the scrapers.
- `USER_PROVIDED_DOCS.md` — user-supplied reference material ingested into the corpus.

**Meta**
- `README.md`, `LICENSE.md` — unchanged.

---

## 3. Where we left off — VERBATIM state

### 3.1 Backend — shipped through BATCH 10 (`bf69bea`)
Everything through **BATCH 10** is committed and green:

- **BATCH 1–7:** core gaps, supply chain + polite scrapers, MMR rerank + signed provenance, cost/routing telemetry, clarification UX (priority/skippable/fact_key), evals harness, recipes v1 (3 built-ins).
- **BATCH 7.5:** library expanded to 23 recipes + `RECIPE_COVERAGE_TRACKER.md`.
- **BATCH 8:** intelligent tailoring + Wave B recipes → **30 built-in recipes** (Arts 4, 5, 49, 53, 86; GDPR Art 30; ISO 42001 Clause 6.2; etc.). Tailoring engine produces `TailoringPlan` with `skip_rationale` per section. Endpoints: `POST /api/v1/recipes/{id}/tailor`, `POST /api/v1/recipes/recommend`.
- **BATCH 9:** dynamic tri-state tailoring, notification multiplexer, `plan_recipe` tool, completion notifier, Art 50 + DPIA retrofit (commits `a2ae108`, `6472e55`).
- **BATCH 10:** tenant isolation hardening + human-input auto-dispatch (commit `bf69bea`). **394/394 tests passing.**

Backend endpoints used by the new frontend:
```
GET  /api/v1/recipes
GET  /api/v1/recipes/{id}
POST /api/v1/recipes/{id}/tailor
POST /api/v1/recipes/recommend
GET  /api/v1/recipes/{id}/human-inputs
POST /api/v1/recipes/{id}/run
GET  /notifications/inbox
POST /notifications/inbox/drain
GET  /notifications/contact-profile
PUT  /notifications/contact-profile
```

### 3.2 Frontend — UI/UX redesign in flight (NOT YET COMMITTED)

Directive from the user (verbatim): *"COMPLETE UI/UX REDESIGN AND IMPLEMENTATION… VERY CONVENIENT, NOT CLUTTERED, INNOVATIVE… PRESENT THE DELIVERABLES AS THEY ARE CREATED/NEEDED."*

Strategic decision: replace the 16 per-artefact pages with **one "Live Evidence Binder" Workspace** where recipes stream deliverables into a right-rail binder. Consolidated IA: **Dashboard / Workspace / Recipes / Vault / Inbox / Settings** (+ Onboarding wizard).

**Status: build is green.** `npm run build` in `frontend/` succeeds — 1651 modules, no TS errors, no CSS errors.

Files created (untracked — ready to stage):
- `frontend/src/design/tokens.css` — CSS variables, dark-mode via `:root.dark` + `prefers-color-scheme`.
- `frontend/src/design/primitives.tsx` — 14 components (Logo, ScalesMark, Button, Card, Chip, StatusChip, CitationChip, TierLock, ComplianceRing, SectionAccordion, Skeleton, EmptyState, ScalesDivider).
- `frontend/src/lib/profile.tsx` — `OrgProfile` type + `ProfileProvider` + `useProfile()` + localStorage persistence (`crp_comply_profile`).
- `frontend/src/components/AppShell.tsx` — 6-item sidebar + topbar + inbox-polling badge + dark-mode toggle + onboarding redirect.
- `frontend/src/pages/v2/Dashboard.tsx` — hero + ComplianceRing + top-actions grid + recent deliverables.
- `frontend/src/pages/v2/Workspace.tsx` — **the Live Evidence Binder (~520 lines).** RecipePicker + PendingInputs queue + staggered-reveal LiveBinder (180 ms cascade).
- `frontend/src/pages/v2/RecipeLibrary.tsx` — tailored-first catalogue (per `UI_UX_REDESIGN §9.2`).
- `frontend/src/pages/v2/Vault.tsx` — unified deliverables browser (replaces Reports / EvidencePack / TechnicalDocs).
- `frontend/src/pages/v2/Inbox.tsx` — priority-sorted notifications with drain.
- `frontend/src/pages/v2/Onboarding.tsx` — 5-step wizard per `UI_UX_REDESIGN §11.3`.

Files modified (staged status: *modified*):
- `frontend/src/App.tsx` — routes consolidated to 9 v2 routes under `AppShell`.
- `frontend/src/main.tsx` — wraps `<App />` in `<ProfileProvider>`.
- `frontend/src/index.css` — full rewrite with tokens, base, components, utilities layers.
- `frontend/src/lib/api.ts` — appended Recipes + Notifications sections (~150 new lines).
- `frontend/tailwind.config.js` — full rewrite mapping tokens + legacy `brand-*` ramp remapped to yellow.
- `frontend/tsconfig.tsbuildinfo` — build artefact.

### 3.3 Verify in one command
```bash
cd frontend && npm run build
# expected: "✓ 1651 modules transformed. ✓ built in ~2s"
```

---

## 4. What to do next (priority order)

1. **Commit the frontend redesign.** Suggested message:
   `feat(ui): Live Evidence Binder redesign — tokens + primitives + v2 pages (Dashboard/Workspace/Recipes/Vault/Inbox/Onboarding)`
   Stage: all `frontend/src/design/**`, `frontend/src/pages/v2/**`, `frontend/src/components/AppShell.tsx`, `frontend/src/lib/profile.tsx`, plus the 5 modified files in §3.2.
2. **Dev-server smoke test** — `cd frontend && npm run dev`, verify Onboarding → Dashboard → Workspace run with a real BATCH-10 backend (`uvicorn crp_comply.api:app --reload`).
3. **Delete or archive v1 pages** once smoke test passes: `Dashboard.tsx`, `Setup.tsx`, `RiskAssessment.tsx`, `ComplianceReport.tsx`, `DPIA.tsx`, `Transparency.tsx`, `TechnicalDocs.tsx`, `SessionAudit.tsx`, `EvidencePack.tsx`, `Reports.tsx` (keep `Landing.tsx`, `Pricing.tsx`, `FreeAssessment.tsx`, `Settings.tsx`, `Admin.tsx`, `SDKDocs.tsx` — still referenced from App.tsx).
4. **Resume the launch punch list** per `COMPLIANCE_MODEL_GAPS.md §B`:
   - **§B1** — Frontend collapse Workspace + AgentChat → Draft.
   - **§B2** — Eval suite expansion 3 → 20 cases.
   - **§B3** — Remaining v1 recipe must-haves (FRIA, SoA, ISO 23894, NIST RMF Profile).
5. **Deferred — multi-tenant / per-user productionalisation.** User quote: *"WE'LL COME BACK TO THE MULTI-TENANT/PER-USER PRODUCTIONALISATION LATER."* Resume after the UI/UX + §B2 + §B3 + §B4 are green.

---

## 5. Known divergences between docs

- `RECIPE_COVERAGE_TRACKER.md` header says "BATCH 8 … 30 recipes". Post-BATCH 10 recipe count is still 30. Sweep next time recipes move.

---

## 6. Session memory anchors

- Repo root: `c:\Users\User\Desktop\crp-comply\`.
- Frontend root: `frontend/` (React 18.3 + Vite 5.4 + TS 5.5 + Tailwind 3.4 + Clerk 6.4 + react-query).
- Backend entry: `crp_comply.api:app` (FastAPI).
- Brand tokens: `--crp-primary` `#D4E84A` on `--crp-ink` `#0B0B0C`; typography Space Grotesk / Inter / JetBrains Mono.
- Profile localStorage key: `crp_comply_profile`.
- Onboarding redirect rule: `AppShell` sends unonboarded users (`!profile.actor`) to `/app/onboard`.

---

*This note is the single source of truth for session handoff. Update §3 and §4 at the end of every significant session so the next agent can resume without archaeology.*
