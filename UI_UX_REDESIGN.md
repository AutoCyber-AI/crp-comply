# CRP Comply — UI/UX Redesign

> 📌 **Session handoff:** see [HANDOFF.md](HANDOFF.md) for the current state of the redesign implementation (v2 pages are built and compile; not yet committed). This doc is canonical for **design & IA**.

*Brand-aligned design system + the roadmap from where we are today.*

---

## 1. Where we stand (session recount)

This redesign lands on top of a platform that has been hardened in
seven batches over this session. Briefly:

| Batch | Theme                              | What shipped                                                                                                                         |
| ----- | ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| 1     | Core gaps closure                  | `EventLog`, envelope schema cleanup, CKF recall wiring.                                                                              |
| 2     | Supply chain & polite crawl        | `pip-audit` + `bandit` in CI, scoped workflow permissions, per-host delays for scrapers.                                             |
| 3     | Retrieval & provenance              | MMR reranking in `query_regulation`, signed provenance tuples.                                                                       |
| 4     | Cost & routing                      | `UsageTracker.record_tokens`, `get_cost_summary`, NDJSON drill-down, tier-aware `model_router` with provider-availability fallback.   |
| 5     | Clarification UX                    | `ClarificationNeeded` gains `priority` / `skippable` / `fact_key`; `POST /agent/{id}/clarify?skip=true` supported.                    |
| 6     | Evaluations                         | `crp_comply.evals` package (`EvalCase`, `EvalRunner`, `EvalReport`), 3 seed cases (`ai_act_basic`), CLI `python -m crp_comply.evals`.|
| 7     | Recipes v1                          | `Recipe` / `RecipeRunner`, API endpoints (`GET/POST /api/v1/recipes[...]`), 3 built-in recipes (SoA, NIST profile, FRIA).             |
| 7.5   | **Recipe expansion — this batch**   | **20 new recipes** bringing the library to **23**: EU AI Act Arts 9, 10, 11/Annex IV, 13, 14, 15, 17, 26, 27, 47, 50, 72, 73; ISO/IEC 42001 clauses 5.2, 6.1.2, 6.1.3, 6.1.4, 9.2.2, 9.3, Annex A SoA; GDPR Art 35 DPIA; NIST AI RMF profile; meta conformity evidence pack. Plus [RECIPE_COVERAGE_TRACKER.md](RECIPE_COVERAGE_TRACKER.md) living audit of every article/clause. |

Tests at the top of the session: 265. Currently: **316 passing** +
(recipes verify cleanly via the loader round-trip).

---

## 2. Brand foundations

The CRP Comply logo is the north star:

- **Mark:** a stylised lower-case "c" whose negative space is shaped
  like the scales of justice. Balanced. Forward-leaning. Both
  technology (clean geometric curve) and law (classical scale motif).
- **Wordmark:** "CRP COMPLY" in an all-caps geometric sans, tight
  tracking, sitting below the mark.
- **Palette:** lime-yellow primary over black + white neutrals. The
  logo ships transparent so it lays over any background without a
  card/box.

### 2.1 Colour tokens

| Token                    | Hex       | Use                                                 |
| ------------------------ | --------- | --------------------------------------------------- |
| `--crp-primary`          | `#D4E84A` | brand fill; CTA background; logo                    |
| `--crp-primary-hover`    | `#C2D541` | hover / focus rings                                  |
| `--crp-primary-muted`    | `#EEF5B3` | chips, success toasts, highlight backgrounds         |
| `--crp-ink`              | `#0B0B0C` | body text, headlines, logo fill on light            |
| `--crp-ink-2`            | `#2A2A2E` | secondary text                                       |
| `--crp-ink-3`            | `#6B6B72` | muted text, borders                                  |
| `--crp-surface`          | `#FFFFFF` | base surface                                         |
| `--crp-surface-2`        | `#F7F7F4` | app shell background (warm off-white)               |
| `--crp-surface-inverse`  | `#0B0B0C` | footer, marketing hero, inverse cards                |
| `--crp-success`          | `#3BA776` | compliant / pass                                     |
| `--crp-warning`          | `#E5A23D` | attention / clarification-needed                     |
| `--crp-danger`           | `#D0453C` | nonconformity / incident                             |
| `--crp-risk-high`        | `#9F1B1B` | Annex III / prohibited flags                         |

**Accessibility:** body text sits on white/ink-2 (contrast >7:1).
Primary yellow is used for surfaces with **ink** text only — never
for text on white (fails WCAG AA at body sizes). Inverse CTA: ink
surface with primary yellow text passes AA at >=16px semibold.

### 2.2 Typography

- **Display / headings:** Geometric sans (recommend *Space Grotesk*
  or *General Sans*). Tight tracking (-1%), weight 600 at hero, 500
  at section heads.
- **Body:** Humanist sans (*Inter* or *IBM Plex Sans*). Weight 400,
  line-height 1.55.
- **Mono:** *JetBrains Mono* for citations, article references, and
  evidence IDs.
- **Scale (rem):** 0.75 · 0.875 · 1 · 1.125 · 1.25 · 1.5 · 2 · 2.5 · 3.5.

### 2.3 Shape, grid & motion

- **Grid:** 8 px base unit. 12-col desktop, 4-col mobile, 1 440 px
  max-width content.
- **Radius:** 12 px for cards, 8 px for inputs, full-pill for chips.
- **Elevation:** soft single-layer shadow (`0 2px 12px rgba(11,11,12,.06)`).
  Inverse cards use a 1 px ink-3 border instead of shadow.
- **Motion:** 180 ms / cubic-bezier(.2,.8,.2,1) for UI transitions.
  Scales-of-justice mark tips ±3° as loading animation on
  long-running recipe runs.

### 2.4 Iconography

- **Set:** *Lucide* (open source, geometric).
- **House icons** (custom, 1.5-stroke, inherit current colour):
  `recipe`, `evidence-pack`, `annex-iv-binder`, `fria`, `dpia`,
  `soa`, `audit-trail`, `citation`.
- **Brand moments:** the scales-of-justice cut-out from the logo
  appears as a divider glyph between report sections and as the
  empty-state illustration.

---

## 3. Information architecture

```
┌─ Marketing ─────────────────────────────────────────────────────┐
│ /               Home · value prop · recipe carousel             │
│ /regulations    AI Act · ISO 42001 · NIST · GDPR overview pages │
│ /recipes        Public recipe catalogue (requires login to run) │
│ /pricing        Free · Pro · Team · Enterprise (Stripe)          │
│ /security       Trust centre                                     │
│ /docs           /docs/api · /docs/recipes · /docs/runbooks       │
└────────────────────────────────────────────────────────────────┘

┌─ App (authenticated) ───────────────────────────────────────────┐
│ /app                                                            │
│ ├ dashboard       Health of all AI systems, top actions         │
│ ├ systems/:id     System card · evidence · recipes · timeline   │
│ ├ recipes         Library · run · history                       │
│ ├ evidence        Evidence pack browser, diff, export           │
│ ├ agent/:sid      Live agent session view                        │
│ ├ evals           Eval suites + scoreboards                      │
│ ├ audit-log       Event log + provenance viewer                  │
│ └ settings        Org · billing · members · API keys             │
└────────────────────────────────────────────────────────────────┘
```

---

## 4. Key screens

### 4.1 Dashboard (`/app`)

- **Hero strip:** org name, certification badges (ISO 42001 active /
  AI Act DoC current), next-review countdown.
- **Compliance score ring** (primary yellow arc on ink ring). Three
  sub-rings: AI Act · ISO 42001 · GDPR.
- **Top risks card:** top 5 AI-risk-register items with owner, level,
  due-date pill.
- **Recent runs card:** last 10 recipe / agent runs with status chip.
- **Evidence pack card:** one-click "Generate Conformity Evidence
  Pack" — runs the `conformity_evidence_pack` meta-recipe.

### 4.2 System card (`/app/systems/:id`)

Two-column layout:

- **Left (sticky):** system metadata (Annex III row, risk tier,
  intended purpose, lifecycle stage), provider/deployer actor
  toggle, shortcuts to "Run FRIA / DPIA / AISIA".
- **Right tabs:**
  - *Evidence* — every produced deliverable with version history.
  - *Recipes* — library filtered to ones applicable to this system.
  - *Timeline* — event log including recipe runs, state changes,
    incidents.
  - *Risks* — linked entries in the AI Risk Register.

### 4.3 Agent session (`/app/agent/:sid`)

- Centre: streaming transcript (tool calls collapsed by default,
  citations shown inline as chips).
- Right rail: **Context panel** with running recall-facts, current
  envelope token budget meter (primary-yellow fill), and clarification
  queue (with the new `priority` chips and per-question *Skip* button
  for low-priority skippable items — pure UI mapping of batch 5).
- Bottom: user-input with a "Force clarify now" button when
  medium/high-priority questions are pending.

### 4.4 Recipe library & runner (`/app/recipes`)

- **Catalogue grid:** cards grouped by regulation family, filtered
  by actor (provider / deployer / GPAI) and tier (Free / Pro /
  Enterprise — free-tier cards show a padlock and "Upgrade" CTA
  consistent with the API-level 402 response from batch 7).
- **Recipe detail:** sections outline, required-inputs form on the
  right, citations listed as a monospace vertical list (e.g.
  `Article 14(4)(a)`).
- **Runner:** live progress with one accordion per section; each
  section shows *citations consulted* (chips) and *CKF facts
  recalled* (count). On completion: side-by-side Markdown / JSON
  toggle, "Save to evidence" button, and a "Diff against previous
  run" view.

### 4.5 Evidence pack viewer (`/app/evidence`)

- Tree view of deliverables keyed by regulation.
- Each deliverable row: title, version, date, signer, hash, status
  chip.
- Bulk actions: export as ZIP (Markdown + JSON + hashes manifest),
  or render a single PDF binder (cover letter from the
  `conformity_evidence_pack` recipe).

### 4.6 Audit log (`/app/audit-log`)

- Append-only event timeline (our `EventLog` surface).
- Provenance viewer per entry: signed tuple, model, prompt hash,
  retrieved-citation IDs — mapped from batch 3 signed provenance.

---

## 5. Marketing surfaces

- **Hero:** left — wordmark + tagline "*The evidence binder your
  AI compliance programme prints itself.*" + primary CTA on yellow.
  Right — looping animation of a recipe being rendered section by
  section with citations materialising, set inside a mac-style
  window over an ink background.
- **Social proof strip:** regulator logos + notified-body-style
  shapes rendered monochrome.
- **Recipe carousel:** live-previews of the 23 recipes, filterable
  by regulation.
- **Pricing:** 4 tiers (Free / Pro / Team / Enterprise). Recipes
  marked with tier locks consistent with the API enforcement.
  Stripe checkout launches from the CTAs (next round).

---

## 6. Design-system scaffolding checklist

- [ ] Add `theme.css` exposing the tokens above (`:root` and
      `.dark`).
- [ ] Publish `@crp/ui` package (or Tailwind preset) with the
      colour + radius + shadow tokens.
- [ ] Ship icon set (Lucide + 8 house SVGs).
- [ ] Build Storybook entries for: `Button`, `Chip`, `CitationChip`,
      `StatusChip`, `TierLock`, `SectionAccordion`, `TokenMeter`,
      `EvidenceRow`, `CompliancePieRing`, `ClarificationQueueItem`.
- [ ] Dark-mode palette (invert surface/ink; primary stays yellow).
- [ ] Screenshot-regression tests for the marketing hero and
      dashboard at 1440 / 1024 / 375.
- [ ] Accessibility audit on every screen (axe-core CI gate).

---

## 7. Implementation waves (UI)

1. **Wave A — tokens & identity:** theme CSS, logo assets, fav-set,
   marketing hero + pricing.
2. **Wave B — dashboard + system card:** core navigational shell,
   compliance-score ring, evidence pack generator.
3. **Wave C — agent session + clarification queue:** wire the
   batch-5 `priority` / `skippable` model into the UI.
4. **Wave D — evidence pack viewer + audit log:** export binder,
   signed-provenance viewer.
5. **Wave E — evals scoreboard + billing (Stripe):** close the
   Stripe round that was deferred.

---

## 8. Open questions to lock before Wave A

1. Brand typography licence (Inter + Space Grotesk are free; confirm
   we keep those over a paid pairing).
2. Exact hex of the logo yellow — sampled here as `#D4E84A` from the
   supplied PNG; confirm against the master vector when available.
3. Dark-mode strategy: follow-system vs manual toggle — default
   recommendation: follow-system with manual override in settings.
4. PDF renderer: weasyprint (Python, matches our stack) vs headless
   Chromium (higher fidelity, heavier) for the evidence binder.

---

*Living document — update alongside `RECIPE_COVERAGE_TRACKER.md` as
new waves ship.*

---

## 9. Anti-clutter principles (BATCH 8)

The product must reward the user's attention, not consume it.
Compliance is already heavy — the UI must not add friction.

### 9.1 Progressive disclosure
- **One primary action per screen.** Secondary actions live in an
  overflow menu or become visible on row-hover.
- **Accordion everything.** Every recipe section, every tailoring
  rationale, every evidence block opens on demand. Default state
  is collapsed except for the required sections.
- **Dense but airy.** Max 7 items in top-nav. Max 5 sections
  above-the-fold on the dashboard. A quiet layout with 24px gutters
  always beats a dashboard that shows everything at once.

### 9.2 "Tailored for you" is the default
For any authenticated user, every recipe the UI renders is the
**tailored** version by default. The full catalogue view is only
accessible via a secondary action ("Browse full library").
- Sections that don't apply collapse into a single chip:
  > `3 sections not applicable to you — view rationale ↓`
  Clicking reveals each skipped section with its `skip_rationale`.
- The user can flip to "Show everything" but never has to.
- Applicability conditions that fired (e.g. `actor=deployer`,
  `is_chatbot`) appear as muted tag-badges next to each skip
  rationale — audit-grade transparency, one glance.

### 9.3 No modal pop-ups for routine decisions
- Inline confirm (toast + undo for 5s) for destructive actions
  under a certain blast-radius.
- Modals reserved for: signing an evidence pack, changing the
  organisation profile (since it invalidates all tailoring plans),
  and cancelling a subscription.

### 9.4 Silence over noise
- No badges for "New!" features older than 14 days.
- No "did you know" tooltips after the third session.
- Notification centre is append-only; read-state hides items by
  default.

---

## 10. Agentic-AI UX patterns

CRP Comply is an agentic product — the agent runs recipes, extracts
regulation, and drafts text. The UI must make the agent **legible
and interruptible** without overwhelming the user.

### 10.1 Streaming with always-visible controls
- Every agent response streams token-by-token.
- `Stop` and `Pin-context` buttons remain visible and clickable
  throughout the stream (no "wait until the model finishes" hostage).
- On Stop, the partial draft is preserved as a revision so the user
  can continue, discard, or re-run with adjusted inputs.

### 10.2 Tool-call receipts, collapsed by default
- Every tool the agent uses (`classify_ai_act_risk`,
  `lookup_article`, `recall_facts`, etc.) emits a one-line receipt:
  > `🔧 lookup_article("Article 27(1)") → 412 words`
- Receipts are folded into a collapsible "Agent trace" below the
  response. Power users open it; everyone else ignores it.
- When the agent cites a regulation, the citation is a hyperlink
  that opens the source chunk in a right-side panel — never a
  full-page navigation.

### 10.3 Clarification queue, not interrupt storm
- If the agent needs multiple clarifications, they queue up in one
  card with a progress indicator (`1 of 3`). The user answers in
  sequence without losing flow.
- Queue is sorted by impact: blocking questions first (can't
  produce the artefact without the answer) → quality questions
  (affects tailoring granularity) → optional.

### 10.4 Evidence-first output
- Every recipe output lands with a built-in **Evidence** panel
  listing the citations, the CKF facts consulted, the inputs
  provided, and the tailoring plan that filtered the sections.
- Exporting to PDF includes this panel as an appendix. The binder
  is verifiable without re-opening the app.

---

## 11. Authentication gate (authoritative)

> **Only authenticated users can progress to the main app.**
> Everything else is landing / marketing / public docs.

### 11.1 Public surfaces (no auth)
| Path              | Purpose                                              |
| ----------------- | ---------------------------------------------------- |
| `/`               | Marketing hero + social proof + pricing summary.      |
| `/pricing`        | Tier comparison + FAQ.                               |
| `/regulations`    | Browse-only catalogue of supported regulations.      |
| `/recipes`        | Browse-only catalogue of recipe definitions (no run). |
| `/docs`           | Public product documentation.                        |
| `/security`       | Security & trust page.                               |
| `/login`, `/signup` | Auth flows.                                        |

### 11.2 Protected surfaces (auth required)
All routes under `/app/*` — dashboard, recipe runner, agent chat,
evidence binder, organisation profile, billing settings.
- Unauthenticated hit to `/app/*` → `302 Location: /login?next=<path>`
- Session expired mid-action → toast banner, no hard redirect; the
  user's in-flight draft is preserved.

### 11.3 Onboarding wizard (first authenticated session)
A friendly five-step form that populates the canonical `UserProfile`
used by every tailoring plan thereafter:
1. **Your role** — provider, deployer, importer, distributor,
   authorised representative, GPAI provider. (maps to `actor`)
2. **Where you operate** — jurisdictions (multi-select), EU
   establishment (bool). (maps to `jurisdiction`,
   `established_in_eu`)
3. **What you build / use** — system category, Annex III row if
   applicable, is GPAI / GPAI systemic. (maps to `system_category`,
   `annex_iii_row`, `is_high_risk`, `is_gpai`, `is_gpai_systemic`)
4. **Data & interaction modalities** — personal data, special
   categories, biometrics, chatbot, synthetic content, emotion
   recognition, deepfake, automated decision-making, children users.
   (maps to the Art 50 / GDPR / Art 86 flags)
5. **Existing certifications** — ISO 42001, ISO 27001, SOC 2,
   sector-specific. (maps to the `iso_*_certified` flags)

Each step has:
- No more than 4 fields visible at once.
- Inline examples ("e.g. a CV-screening tool is high-risk under
  Annex III §4(a)").
- A "Not sure?" link that opens a contextual explainer — never
  blocks completion.

On completion, the dashboard renders a personalised "What you owe"
panel backed by `recommend_recipes()` — the top applicable recipes
ranked by urgency and missing evidence.

### 11.4 Profile drift guardrail
Changing any onboarding answer re-runs `recommend_recipes()` and
flags any already-produced deliverables whose tailoring plan would
now differ. The user can **re-tailor**, **keep as-is** (with a
dated snapshot of the obsolete profile), or **archive**.

---

*Living document — update alongside `RECIPE_COVERAGE_TRACKER.md` as
new waves ship.*
