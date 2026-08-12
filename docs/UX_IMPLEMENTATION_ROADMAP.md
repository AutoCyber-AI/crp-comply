# CRP Comply UX Implementation Roadmap

This roadmap translates the research report in `UX_SATISFACTION_REPORT_CONTENT/ux_satisfaction_report.agent.final.md` into engineering deliverables. It is the canonical source for the 7-phase implementation plan.

## Executive summary

CRP Comply's structural differentiators — passkey security, local LLM, HMAC-signed evidence, and EU AI Act specificity — must become *visible* and *delightful* in the UI. The roadmap sequences work from the highest-leverage surface changes (perceived performance, streaming, onboarding) through AI trust, security UX, reliability, and finally team/enterprise scale.

## Phase overview

| Phase | Theme | Duration | Highest-impact deliverable |
|---|---|---|---|
| 0 | Skills, reports, design system | 3–5 days | Living docs and component conventions |
| 1 | Perceived performance & streaming | 2 weeks | Skeleton taxonomy + first-chunk streaming |
| 2 | Navigation & power-user efficiency | 2 weeks | CMD+K command palette + CLI-to-web bridge |
| 3 | 60-second onboarding | 2 weeks | Passkey → microsurvey → demo classification → confetti |
| 4 | AI trust & autonomy | 3 weeks | Autonomy dial + intent preview + citation layers |
| 5 | Security UX as delight | 2 weeks | Visible trust badges + Redis sessions + step-up auth |
| 6 | Reliability & observability | 3 weeks | IndexedDB drafts + feature flags + Prometheus/Grafana |
| 7 | Collaboration & scale | 4 weeks | RBAC + workspaces + tiered tenant isolation |

## Phase 1 — Perceived Performance & Streaming

- Skeleton taxonomy for Table, Card, Chart, Content, Form.
- Systematic skeleton coverage on Vault, Dashboard, RecipeLibrary, Inbox, Evidence, Programme, Continuous.
- `useOptimisticMutation` helper applied to recipe runs, saves, uploads, and settings.
- Refactor `AgentChat` streaming with first-chunk transition and phase labels.
- Surface tool invocations inline.

**Success metrics:** Lighthouse CLS < 0.1; no blank screens during agent load.

## Phase 2 — Navigation & Power-User Efficiency

- [x] Global CMD+K command palette (`cmdk`) with fuzzy search.
- [x] `g`-then-letter navigation shortcuts and action prefixes.
- [x] Recent commands persisted to `localStorage`.
- [x] "Copy CLI command" buttons on recipes, reports, vault items.
- [x] Web terminal mode mirroring CLI help (`CliBridge`).
- [x] Backend `/api/v1/search` endpoint — unified search across recipes, reports, evidence packs, artefacts, and obligations.
- [x] Palette consumes `/api/v1/search` with debounced server-side search.

**Deliverables:**
- `frontend/src/components/CommandPalette.tsx`
- `frontend/src/components/CliBridge.tsx`
- `frontend/src/components/CliCopyButton.tsx`
- `frontend/src/components/ShortcutsHelp.tsx`
- `frontend/src/hooks/useKeyboardShortcuts.ts`
- `frontend/src/lib/commands.ts`
- `frontend/src/lib/cliBridge.ts`
- `frontend/src/lib/api.ts` (`searchAll`, `SearchResult`, `SearchResponse`)
- `src/crp_comply/api/search.py`

**Success metrics:** palette opens in <50 ms; every page reachable in ≤2 keystrokes.

## Phase 3 — 60-Second Onboarding

- [x] Replace the 6-step wizard with the 60-second first-run flow.
- [x] 3-question microsurvey stored in `OrgProfile`.
- [x] Deterministic demo classification endpoint (`POST /api/v1/onboarding/quick`).
- [x] Celebration component + endowed-progress messaging.
- [x] 4-item onboarding checklist with auto-completed first item.

**Deliverables:**
- `frontend/src/pages/v2/Onboarding.tsx`
- `frontend/src/lib/api.ts` (`classifyOnboarding`)
- `frontend/src/pages/v2/__tests__/Onboarding.test.tsx`
- `src/crp_comply/api/onboarding.py` (`/onboarding/quick`)
- `tests/test_onboarding_quick.py`

**Status:** ✅ Complete

**Success metrics:** median TTV < 90 s; checklist completion > 45%.

## Phase 4 — AI Trust & Autonomy ✅

- [x] 4-level autonomy dial (`AutonomyDial`) wired to `/me/preferences` and intent preview.
- [x] **Autonomy selection is forwarded to backend agent/recipe runs and maps to `PolicyEnforcer` mode** (`suggest`→`strict`, `draft`/`autonomous_with_checkpoints`→`default`, `full`→`off`).
- [x] Intent preview modal (`IntentPreviewModal`) before recipe run, with plan summary, skipped sections, pending questions, and per-run autonomy override.
- [x] Inline checkpoint approval card (`InlineCheckpointCard`) in chat/workspace with approve/reject + optional note.
- [x] Citation hover cards (`CitationHoverCard`) with static and async article summaries in `LiveBinder`.
- [x] Qualitative confidence labels (`ConfidenceLabel`) on deliverables and chat bubbles.
- [x] Learned-preferences indicator (`LearnedPreferenceIndicator`) with autonomy override affordance in AgentChat.
- [x] New **Preferences** settings tab (`PreferencesPanel`) for default autonomy.

**New modules:**

| Module | Purpose |
|--------|---------|
| `frontend/src/components/agent/AutonomyDial.tsx` | 4-level autonomy selector |
| `frontend/src/components/agent/IntentPreviewModal.tsx` | Run confirmation / intent preview |
| `frontend/src/components/agent/InlineCheckpointCard.tsx` | Inline checkpoint approve/reject |
| `frontend/src/components/agent/CitationHoverCard.tsx` | Hover cards for citations |
| `frontend/src/components/agent/ConfidenceLabel.tsx` | Qualitative confidence chips |
| `frontend/src/components/agent/LearnedPreferenceIndicator.tsx` | Learned-preference badge + override |
| `frontend/src/lib/confidence.ts` | Score → label mapping |
| `frontend/src/lib/citationSummaries.ts` | Static article summary fallback |
| `frontend/src/pages/Settings/PreferencesPanel.tsx` | Settings preferences tab |
| `src/crp_comply/agent/mcp_permissions.py` | `resolution_note` / `resolved_by` on checkpoints |
| `src/crp_comply/api/checkpoint_routes.py` | Accept optional `note` on resolve |

**Validation:** frontend 95+ tests passing, backend 1176+ tests passing, lint/build/ruff/bandit green. Autonomy mapping covered by `tests/test_agent_autonomy.py` and `tests/test_recipe_autonomy.py`.

**Success metrics:** >85% intent-preview acceptance; citation CTR > 20%.

## Phase 5 — Security UX ✅

- [x] Visible trust badges in header/footer/landing.
- [x] Redis-backed `HttpOnly` session cookies.
- [x] Adaptive step-up authentication for sensitive actions.
- [x] Session revocation UI.
- [x] **Passkey MFA session token and app API key removed from `sessionStorage`/`localStorage`**; MFA token is now an `HttpOnly` cookie. SDK callers can still use `X-Passkey-Mfa-Session` / `X-Api-Key` headers.

**Success metrics:** passkey success > 95%; no secrets in `localStorage`/`sessionStorage`.

## Phase 6 — Reliability & Observability ⚠️ Partial

- [x] **IndexedDB draft auto-save** for recipe workspace (`frontend/src/lib/idb.ts`, `Workspace.tsx`).
- [ ] Offline mutation queue / Background Sync — deferred.
- [x] Circuit breakers with LLM fallback chain (sidecar + local-LLM fallback in loop runtime).
- [ ] Self-hosted feature flags — deferred.
- [ ] OpenTelemetry + Prometheus + Grafana + RUM — deferred.
- [ ] Multi-window burn-rate SLO alerting — deferred.

**Success metrics:** < 0.1% data loss on network failure; 99.9% availability measured.

## Phase 7 — Collaboration & Scale ⚠️ Partial

- [x] **RBAC scaffold** (`src/crp_comply/api/rbac.py`) with Owner/Admin/Member/Viewer/Guest derived from Clerk org role.
- [ ] Workspaces with activity feeds — deferred (existing `Workspace.tsx` is the recipe runner, not a team workspace).
- [ ] Tiered tenant isolation: RLS (Free/Starter), schema-per-tenant (Scale), DB-per-tenant (Enterprise) — deferred.
- [x] Personalisation engine and recipe recommendations (onboarding + dashboard).
- [x] **One-click evidence sharing** (`src/crp_comply/api/sharing.py`, `frontend/src/components/ShareButton.tsx`) with public share links and revoke.
- [ ] Team invite loops — deferred.

**Success metrics:** RBAC passes adversarial tests; team invite conversion > 15%.

## Skills created

- `.kimi/skills/crp-comply-ux-implementation/SKILL.md`
- `.kimi/skills/crp-comply-onboarding/SKILL.md`
- `.kimi/skills/crp-comply-security-ux/SKILL.md`
- `.kimi/skills/crp-comply-observability/SKILL.md`

## Design system

See `frontend/docs/DESIGN_SYSTEM.md` for skeleton taxonomy, animation tokens, confidence labels, and provenance pills.

## Architecture decision

The approved approach is **incremental modernisation on the existing React 18 + Vite + TanStack Query stack** (Option A). A Next.js 15 migration is deferred to a future Phase 8 gate, to be revisited once RUM data is available.
