# CRP Comply Roadmap TODO

This document tracks the remaining work from the Phase 5 agentic upgrade and beyond. It is a living report: when a line is completed, update its status and add the relevant commit or test evidence.

## Legend

- **P0** — blocks the next release
- **P1** — user-visible improvement, ship as soon as stable
- **P2** — expansion / coverage
- **P3** — exploratory / performance / platform hardening
- **Status:** `todo` | `in_progress` | `done` | `deferred`

## Phase 5a — Per-user preference learning & explicit feedback

| # | Task | Status | Owner | Acceptance criteria |
|---|---|---|---|---|
| 5a.1 | User preference profile + persistence | **done** | Agent B | `GET/POST /api/v1/me/preferences`, JSON persisted under `data/user_preferences/`, tests green |
| 5a.2 | Explicit feedback widget (thumbs + comment) | **done** | Agent B | `FeedbackRow` rendered on assistant bubbles, optimistic UI, `POST /agent/{id}/feedback` extended |
| 5a.3 | Preference learner from explicit + implicit signals | **done** | Agent B | `preference_learner.py`, 10+ signal rules, decay + loss-aversion weights, tests |
| 5a.4 | Planner uses learned preferences | **done** | Agent B | `UserNeed` defaults from profile, system-prompt footnote, preferred regulations passed to tools |
| 5a.5 | Session feedback list endpoint | **done** | Agent B | `GET /agent/{session_id}/feedback` returns ledger entries for that session |

**Open questions resolved (AFK):**

1. **4K models:** hard warning, default baseline 8K. Implemented in `slm_profile.py` as `legacy_4k_warn`.
2. **Web-search default for new users:** "Research" (`standard`). Implemented as default in `SearchDepthSelector` and loaded from `preferred_depth`.
3. **Preference scope:** per-user with org-level fallback. Implemented as `data/user_preferences/{tenant_id}/{user_id}.json`.

## Phase 5b — Web-search depth + sidecar robustness + SLM fix

| # | Task | Status | Owner | Acceptance criteria |
|---|---|---|---|---|
| 5b.1 | Web-search depth chooser UI | **done** | Agent B | `SearchDepthSelector` in composer, 3 depth levels, latency badges |
| 5b.2 | Unified backend depth mapping | **done** | Agent B | `research_by_depth` + `build_web_search_with_depth_tool`, `brief→/search`, `standard→/research_intelligent`, `thorough→/research_agent` |
| 5b.3 | Sidecar retries with exponential backoff | **done** | Agent B | Max 3 attempts, tested with 503 sequence |
| 5b.4 | Sidecar circuit breaker | **done** | Agent B | Opens after 5 failures, returns `circuit open` error |
| 5b.5 | Sidecar in-memory TTL cache | **done** | Agent B | `research_intelligent` cached for 5 min, cache-hit test |
| 5b.6 | Structured timeout fallback | **done** | Agent B | `SidecarTimeoutError` with JSON payload; `WebClient.research_by_depth` returns corpus fallback |
| 5b.7 | SLM profile reframed as budget allocator | **done** | Agent B | `legacy_4k_warn`, `default_8k`, `default_16k`; 6+ iterations preserved; warning logged below 8K |

## Phase 5c — New regulation experts

| # | Task | Status | Owner | Acceptance criteria |
|---|---|---|---|---|
| 5c.1 | NIS2 regulation expert | **done** | Agent B | `test_nis2_expert.py` green, OES/MSP classification |
| 5c.2 | NIST AI RMF regulation expert | **done** | Agent B | function-to-control mapping, tests green |
| 5c.3 | DORA regulation expert | **done** | Agent B | deterministic intent→article map, tests green |
| 5c.4 | UK AI Act regulation expert | **done** | Agent B | UK risk-tier mapping, tests green |
| 5c.5 | HIPAA regulation expert | **done** | Agent B | PHI handling guidance, tests green |
| 5c.6 | SOC 2 regulation expert | **done** | Agent B | common-criteria/trust-service mapping, tests green |

**Reference:** `docs/CREATING_REGULATION_EXPERTS.md`

## Phase 5d — Integrations & adoption hooks

| # | Task | Status | Owner | Acceptance criteria |
|---|---|---|---|---|
| 5d.1 | MCP server surface | todo | Agent B | `crp_comply/mcp_server.py`, tests, docs |
| 5d.2 | LangChain / LlamaIndex adoption hooks | todo | Agent B | `src/crp_comply/integrations/langchain.py`, example notebook |

## Phase 5e — Platform hardening

| # | Task | Status | Owner | Acceptance criteria |
|---|---|---|---|---|
| 5e.1 | Persist CSO across processes | **done** | Agent B | `src/crp_comply/agent/cso_store.py` with `FileCSOStore` + `RedisCSOStore`, env-driven backend, `tests/test_cso_store.py` green |
| 5e.2 | CRPv5 positioned loop default for SLM | todo | Agent B | Flip default when `crp.stl` + SLM detected, eval tests |
| 5e.3 | Persistent checkpoints + SafetyControlPlane | todo | Agent B | Redis checkpoint store, control-plane integration |
| 5e.4 | SLM / web-research eval harness | todo | Agent B | 10 eval cases, latency + citation checks |

## Phase 5f — Release & operations

| # | Task | Status | Owner | Acceptance criteria |
|---|---|---|---|---|
| 5f.1 | Final backend test suite | **done** | Agent B | `pytest tests/ -q` ≥ 1096 passed, 6 skipped |
| 5f.2 | Frontend lint / type-check / build / test | **done** | Agent B | `npm run lint`, `npx tsc --noEmit`, `npm run build`, `npm test -- --run` all green |
| 5f.3 | Bandit security scan | **done** | Agent B | `bandit -r src/crp_comply --severity-level medium --confidence-level medium` clean |
| 5f.4 | PyPI token rotation | todo | Owner | Rotate leaked/aged token in Railway env |
| 5f.5 | Update `AGENTS.md` if conventions changed | **done** | Agent B | Documented Round 7 dialogue/clarifier modules and frontend changes |

## Round 7 — Clarification System Unification, Repair, and Incremental Confirmation

| # | Task | Status | Owner | Acceptance criteria |
|---|---|---|---|---|
| 7.1 | Dialogue state machine enrichment | **done** | Agent B | `DialogueState` tracks `confirmed_slots`, `repair_history`, `pending_decision`; `PolicyDecision` serialisation; `DialogueStateTracker.resume()` handles confirm→repair→re-confirm |
| 7.2 | Clarifier snapshot unification | **done** | Agent B | `ClarifierRecord.policy_decision_json`; `suspend()` stores `dialogue_state`, `policy_decision`, `dialogue_action`, `policy_options` |
| 7.3 | Legacy/Phase-7 suspension unification | **done** | Agent B | Legacy `ClarificationNeeded` persists via `ClarifierStore` with uniform `AgentResult(pending_action="probe")`; loop runtime stores policy decision |
| 7.4 | API resume paths convergence | **done** | Agent B | `_resume_via_tracker()` helper; `/clarify`, `/clarify/stream`, and `/loop/resume/{token}` all use tracker logic |
| 7.5 | Frontend confirm/repair UI | **done** | Agent B | `ClarifierCard`/`TranscriptBubble`/`Composer`/`AgentChat` support `confirmation-q`/`repair-q` and option clicks |
| 7.6 | Tests | **done** | Agent B | `tests/test_agent_dialogue.py` confirm→proceed, confirm→repair, contradiction repair, vague repair; `ClarifierCard.test.tsx` option buttons |
| 7.7 | Validation | **done** | Agent B | Backend 1176 passed / 6 skipped; ruff + bandit clean; frontend lint/build/test green (95 passed) |

## 7-phase UX satisfaction upgrade — audit & integration fixes

| # | Task | Status | Owner | Acceptance criteria |
|---|---|---|---|---|
| UX.1 | Phase 4 autonomy wiring | **done** | Agent B | `autonomy` field on `AgentStartRequest`/`RecipeRunRequest`; `_build_agent` maps levels to `PolicyEnforcer` mode; frontend `Workspace`/`AgentChat` pass selected level; tests green |
| UX.2 | Phase 5 secret removal | **done** | Agent B | `crp_passkey_mfa_token` set as `HttpOnly` cookie by `/passkeys/verify` and `/auth/step-up`; frontend `api.ts`/`passkey.ts` no longer read `sessionStorage`; `X-Api-Key` / `X-Passkey-Mfa-Session` removed from web client |
| UX.3 | Phase 6 IndexedDB drafts | **done** | Agent B | `frontend/src/lib/idb.ts` helper; `Workspace.tsx` loads/saves/clears drafts via IndexedDB; `fakeIndexedDB.ts` mock; tests green |
| UX.4 | Phase 7 RBAC scaffold | **done** | Agent B | `src/crp_comply/api/rbac.py` with `WorkspaceRole` and `require_role`; `/team/role` and `/team/members` endpoints; tests green |
| UX.5 | Phase 7 evidence sharing | **done** | Agent B | `src/crp_comply/api/sharing.py` CRUD + public share link; `ShareButton.tsx` in Vault detail; `/app/team` page; tests green |
| UX.6 | Validation | **done** | Agent B | Backend 1215 passed / 6 skipped; frontend 106 passed; ruff + bandit clean; LM Studio reachable and responds |

## Recently completed

- Phase 1–4 agentic upgrades (user-need engine, regulation experts, web research, perfect corpus).
- SearXNG submodule removal; upstream Docker image with overlay engines.
- SLM positioning round and `gdpr` expert.
- Phase 5a/5b implementation and integration tests.
- **Round 7** — unified confirmation/repair/probe clarification flow across backend and frontend.
- **7-phase UX satisfaction upgrade audit** — autonomy wired, secrets moved to HttpOnly cookies, IndexedDB drafts, RBAC + sharing scaffold.

## How to update this file

When you start or finish an item, change its status and add evidence (test command, commit hash, PR link). Do not delete rows — deferred items keep context for future sprints.
