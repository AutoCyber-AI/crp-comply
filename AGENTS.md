# Agent guidance for CRP Comply

## Project conventions

- **Python:** 3.10+ compatible syntax, type hints, `from __future__ import annotations`.
- **Linting:** `ruff check src tests` and `bandit -r src/crp_comply --severity-level medium --confidence-level medium` must pass.
- **Tests:** `pytest tests/` (run full suite before final commit). Eval suite threshold is 95% (`pytest tests/eval/`).
- **Frontend:** React + TypeScript + Tailwind. Run `npm run lint`, `npx tsc --noEmit`, `npm run build`, and `npm test -- --run` in `frontend/`.
- **File I/O:** Use `Path.write_text` / `read_text` with explicit `encoding="utf-8"`. Escape / sanitise user IDs before using them in filesystem paths (`_sanitize`).

## Recently added modules

- `src/crp_comply/agent/preferences.py` — durable per-user preference profile (Phase 5a).
- `src/crp_comply/agent/preference_learner.py` — derives defaults from explicit ratings and implicit telemetry (Phase 5a).
- `src/crp_comply/agent/slm_profile.py` — reframed as a budget allocator for small-context models; 8K baseline, 4K warning (Phase 5b).
- `src/crp_comply/sidecar_client.py` — retries, circuit breaker, TTL cache, structured timeout errors (Phase 5b).
- `frontend/src/components/agent/FeedbackRow.tsx` — in-chat thumbs up/down + comment widget (Phase 5a).
- `frontend/src/components/agent/SearchDepthSelector.tsx` — web-research depth chooser with latency badges (Phase 5b).
- `docs/CREATING_REGULATION_EXPERTS.md` — guide for adding new regulation expert subagents.
- `docs/CRP_COMPLY_ROADMAP_TODO.md` — living roadmap of remaining Phase 5+ work.
- `src/crp_comply/continuous_compliance/` — verdict-rule graph, continuous audit scheduler, remediation tickets.
- `src/crp_comply/api/continuous.py` — FastAPI router for the continuous compliance dashboard.
- `frontend/src/pages/v2/Continuous.tsx` — frontend continuous compliance dashboard.
- `enterprise/templates/` — starter NDA, DPA, MSA, SOW templates (must be reviewed by counsel before use).
- `src/crp_comply/api/search.py` — unified global search endpoint (`/api/v1/search`) powering CMD+K (Phase 2).
- `src/crp_comply/api/onboarding.py` — 60-second onboarding with deterministic `/onboarding/quick` classification (Phase 3).
- `frontend/src/components/CommandPalette.tsx` — CMD+K palette consuming `/api/v1/search`.
- `frontend/src/pages/v2/Onboarding.tsx` — 3-question microsurvey, endowed-progress checklist, and celebration UI.
- `frontend/src/components/agent/AutonomyDial.tsx` — 4-level autonomy selector (Phase 4).
- `frontend/src/components/agent/IntentPreviewModal.tsx` — run confirmation / intent preview (Phase 4).
- `frontend/src/components/agent/InlineCheckpointCard.tsx` — inline checkpoint approve/reject (Phase 4).
- `frontend/src/components/agent/CitationHoverCard.tsx` — hover cards for citations (Phase 4).
- `frontend/src/components/agent/ConfidenceLabel.tsx` — qualitative confidence chips (Phase 4).
- `frontend/src/components/agent/LearnedPreferenceIndicator.tsx` — learned-preference badge + override (Phase 4).
- `frontend/src/lib/confidence.ts` — score → label mapping (Phase 4).
- `frontend/src/lib/citationSummaries.ts` — static article summary fallback (Phase 4).
- `frontend/src/pages/Settings/PreferencesPanel.tsx` — Settings preferences tab (Phase 4).
- `src/crp_comply/agent/mcp_permissions.py` — checkpoint `resolution_note` / `resolved_by` fields (Phase 4).
- `src/crp_comply/api/checkpoint_routes.py` — accept optional `note` on checkpoint resolve (Phase 4).
- `src/crp_comply/agent/dialogue.py` — `DialogueStateTracker` with confirm/repair/probe state machine (Round 7).
- `src/crp_comply/agent/clarifier.py` — `ClarifierStore` snapshot now carries `dialogue_state` and `policy_decision` (Round 7).
- `src/crp_comply/agent/loop_runtime.py` — Phase-7 loop stores dialogue policy decisions for tracker-based resume (Round 7).
- `src/crp_comply/agent/orchestrator.py` — legacy `ClarificationNeeded` now suspends via `ClarifierStore` and returns a uniform `pending_action="probe"` result (Round 7).
- `src/crp_comply/api/agent.py` — unified `_resume_via_tracker()` helper shared by legacy `/clarify`, `/clarify/stream`, and `/loop/resume/{token}` (Round 7).
- `frontend/src/components/agent/ClarifierCard.tsx` — clarification card supports `action`, `options`, and `onOption` (Round 7).
- `frontend/src/components/agent/TranscriptBubble.tsx` — new `confirmation-q` and `repair-q` transcript kinds (Round 7).
- `frontend/src/components/agent/Composer.tsx` — renders pending option buttons for confirm/repair/probe (Round 7).
- `frontend/src/pages/v2/AgentChat.tsx` — branches on `pending_action` and routes option clicks through `agentClarifyStream` (Round 7).
- `frontend/src/lib/idb.ts` — IndexedDB draft persistence helper for recipe workspace (Phase 6).
- `frontend/src/test/fakeIndexedDB.ts` — in-memory IndexedDB mock for Vitest (Phase 6).
- `src/crp_comply/api/session_store.py` — Redis/file-backed server sessions with step-up elevation (Phase 5).
- `src/crp_comply/api/session_routes.py` — `HttpOnly` cookie session + step-up endpoints (Phase 5).
- `src/crp_comply/api/rbac.py` — Clerk-org-role RBAC scaffold (Owner/Admin/Member/Viewer/Guest) (Phase 7).
- `src/crp_comply/api/sharing.py` — evidence share links with public fetch and revoke (Phase 7).
- `frontend/src/components/ShareButton.tsx` — one-click share dialog + copy link (Phase 7).
- `frontend/src/pages/v2/Team.tsx` — team role + members scaffold page (Phase 7).
- `tests/test_agent_autonomy.py` / `tests/test_recipe_autonomy.py` — autonomy→enforcer mode mapping tests.
- `tests/test_passkey_mfa_cookie.py` — HttpOnly cookie MFA flow tests.
- `tests/test_rbac.py` / `tests/test_sharing.py` — RBAC + sharing tests.

## Marketing guardrails

- Do not claim "98% gross margin" or "managed LLM tokens" as the business model.
- Position managed LLM tokens as an **optional convenience add-on**; BYOK / local LLM is the default.
- Surface the "0 bytes leave your network" privacy badge on landing and README.

## Before committing

1. Run backend tests + eval.
2. Run ruff + bandit.
3. Run frontend lint / type-check / build / test.
4. Update this file if conventions or module guidance changes.
