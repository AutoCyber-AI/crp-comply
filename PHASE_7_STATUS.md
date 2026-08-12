# Phase 7 — Language Agent Loop: Status & Verification

_As of commit on top of `d7f1d67` (May 2026)._

This document is the source of truth for what's shipped against
[PHASE_7_LANGUAGE_AGENT_LOOP.md](PHASE_7_LANGUAGE_AGENT_LOOP.md) §18 and §21.
Every "✅ done" row is backed by a file path and a passing test file.

## 1. Sub-phase check-off

| # | Scope (PHASE_7 §18) | Status | Shipped artefacts | Proof |
|---|---|---|---|---|
| 7.0 | Event taxonomy + SSE skeleton | ✅ done | [src/crp_comply/api/events.py](src/crp_comply/api/events.py) — 23-member `LoopEvent` enum; `PAYLOAD_SCHEMA` exhaustively keyed | [tests/test_loop_events.py](tests/test_loop_events.py) |
| 7.1 | Triage layer (wasa-ai port) | ✅ done | [src/crp_comply/agent/triage.py](src/crp_comply/agent/triage.py) + [triage_patterns.yaml](src/crp_comply/agent/triage_patterns.yaml) | [tests/test_batch4_cost_routing.py](tests/test_batch4_cost_routing.py) |
| 7.2 | Cache layer (exact + semantic + plan) | ✅ done | [src/crp_comply/agent/cache.py](src/crp_comply/agent/cache.py) | round-trip + invalidation tests in cost-routing batch |
| 7.3 | `LoopState` FSM + Planner + degenerate single-step | ✅ done | [src/crp_comply/agent/loop_state.py](src/crp_comply/agent/loop_state.py), [orchestrator.py](src/crp_comply/agent/orchestrator.py) | [tests/test_agent_orchestrator.py](tests/test_agent_orchestrator.py) |
| 7.4 | ReAct + tool dispatch + observation streaming | ✅ done | [src/crp_comply/agent/step_runner.py](src/crp_comply/agent/step_runner.py), [tools.py](src/crp_comply/agent/tools.py) | [tests/test_agent_tools.py](tests/test_agent_tools.py), [tests/test_agent_tools_extended.py](tests/test_agent_tools_extended.py) |
| 7.5 | `ask_user` + suspend/resume + clarifier card | ✅ done | [src/crp_comply/agent/clarifier.py](src/crp_comply/agent/clarifier.py) (24 h TTL, indistinguishable expiry) + frontend `ClarifierCard` | [tests/test_loop_resume_security.py](tests/test_loop_resume_security.py), [tests/test_batch5_clarification.py](tests/test_batch5_clarification.py) |
| 7.6 | Reflector + plan revision + CKF coverage | ✅ done | [src/crp_comply/agent/reflector.py](src/crp_comply/agent/reflector.py); `plan_revisions` budget dimension | [tests/test_batch6_evals.py](tests/test_batch6_evals.py) |
| 7.7 | `FederatedFabric` wrapper + CKF telemetry | ✅ done | [src/crp_comply/agent/federated_fabric.py](src/crp_comply/agent/federated_fabric.py); `LoopEvent.CKF_QUERY` | [tests/test_batch3_rerank_provenance.py](tests/test_batch3_rerank_provenance.py) |
| 7.8 | Web-search sidecar `crp-comply-search` (DDG + trust-tier) + Brave/Tavily stubs | ✅ done | [services/crp-comply-search/](services/crp-comply-search/) — `LocalDDGBackend`, `BraveBackend`/`TavilyBackend` `NotImplementedError` stubs, **plus new `SearXNGBackend`** | [tests/test_searxng_backend.py](tests/test_searxng_backend.py) + sidecar tests |
| 7.9 | Trust-tier YAML profiles (local Goggles equivalent) | ✅ done | `crp_comply_official.yaml` + `crp_comply_news.yaml` | profile-rank fixture tests |
| 7.10 | `run_recipe` tool + recipe streaming | ✅ done | `RECIPE_START` / `RECIPE_DELTA` / `RECIPE_DONE` events | [tests/test_batch7_recipes.py](tests/test_batch7_recipes.py) |
| 7.11 | Frontend reasoning tape + lane banners + trust-tier pills | ✅ done | [frontend/src/components/ReasoningTape.tsx](frontend/src/components/ReasoningTape.tsx) + fixtures | `npx tsc -b` clean, fixture-driven visual QA |
| 7.12 | Budgets, replays, hardening, soak | ✅ done | [src/crp_comply/agent/loop_budget.py](src/crp_comply/agent/loop_budget.py), [src/crp_comply/agent/telemetry.py](src/crp_comply/agent/telemetry.py); `GET /agent/runs/{run_id}/replay`; `LoopEvent.ABORT` + `AbortPayload` | [tests/test_loop_budget.py](tests/test_loop_budget.py), [tests/test_loop_telemetry.py](tests/test_loop_telemetry.py), [tests/test_loop_replay.py](tests/test_loop_replay.py), [tests/test_loop_soak.py](tests/test_loop_soak.py) |
| 7.13 | Brave activation (deferred per §16.2) | ⏸ stub | `BraveBackend` raises with clear message | gated by volume/quality/customer trigger |
| 7.14 | Tavily activation (deferred per §16.2) | ⏸ stub | `TavilyBackend` raises with clear message | same |
| **7.15 (NEW)** | **Self-hosted intelligent SearXNG host + agentic client + new tools (`vendor_profile`, `compare_documents`)** | 🚧 in-progress | [services/crp-comply-searxng/](services/crp-comply-searxng/) scaffold landed (this commit) | tests pending |

### Backend test suite at `d7f1d67`

```
752 passed, 4 skipped, 1 deselected (slow soak), 0 warnings
```

Frontend `npx tsc -b` clean.

## 2. Architectural additions in this commit

### 2.1 Two-agent web-search topology

```
┌──────────────────┐
│ main FastAPI     │
│ (agent loop)     │
└─────────┬────────┘
          │ POST /search, /research, /vendor_profile, /compare_documents
          ▼
┌─────────────────────────────────────┐
│ crp-comply-search (existing)        │  ← agent #1 (client-side)
│   • LocalDDGBackend                 │
│   • SearXNGBackend (new)            │
│   • [planned] QueryExpander         │
│   • [planned] CrossEncoderReranker  │
│   • [planned] ChunkCiter            │
│   • [planned] VendorProfileTool     │
│   • [planned] CompareDocumentsTool  │
└─────────┬───────────────────────────┘
          │ JSON over Railway private network
          ▼
┌─────────────────────────────────────┐
│ crp-comply-searxng (NEW this commit)│  ← agent #2 (host-side)
│   • intent-aware engine routing     │
│   • CELEX/case-law fingerprinting   │
│   • feedback-driven learning        │
│     reranker (SQLite + decay)       │
│   • CRP custom engines:             │
│       eur_lex, edpb, curia, bailii  │
└─────────────────────────────────────┘
```

### 2.2 Files added

```
services/crp-comply-searxng/
├── Dockerfile
├── settings.yml
├── limiter.toml
├── railway.toml
├── README.md
├── engines/
│   ├── eur_lex.py
│   ├── edpb.py
│   ├── bailii.py
│   └── curia.py
└── plugins/
    ├── query_router.py               # CRP Query Router      (agent #2.A)
    └── learning_reranker.py          # CRP Learning Reranker (agent #2.B)
```

### 2.3 Upstream image

The runtime image pins the upstream `searxng/searxng:<tag>` image and overlays
only the files in this directory. No SearXNG source is vendored in this
repository, so there is no git submodule to maintain.

## 3. What you (the operator) need to do

### 3.1 GitHub

1. (Optional) **Branch-protect** the `services/crp-comply-searxng/` path so config changes require review.

### 3.2 Railway

1. **Create a new service** in your existing `crp-comply` project:
   - Source: `Constantinos-uni/crp-comply`, branch `master`.
   - Root directory: `services/crp-comply-searxng`.
   - Builder: Dockerfile (auto-detected from `railway.toml`).
   - **Public networking: OFF.** This must remain off — the service only listens on the private DNS.
   - Service name: `crp-comply-searxng` (gives DNS `crp-comply-searxng.railway.internal`).
2. **Provision a Redis add-on** in the same project (if you don't already have one for caching). Bind its `REDIS_URL` to this service.
3. **Set the following env vars** on the `crp-comply-searxng` service:
   | Var | Value | Notes |
   |---|---|---|
   | `SEARXNG_SECRET_KEY` | `openssl rand -hex 32` output | required by SearXNG |
   | `SEARXNG_REDIS_URL` | `${{Redis.REDIS_URL}}` | Railway template ref |
   | `INSTANCE_NAME` | `crp-comply-searxng` | display only |
4. **Add a persistent volume** mounted at `/var/lib/searxng-crp` (size: 1 GB is plenty — it stores the learning reranker's SQLite). Volume name: `searxng-crp-feedback`.
5. **Update `crp-comply-search` env vars** to point at the new service:
   | Var | Value |
   |---|---|
   | `CRP_COMPLY_WEBSEARCH_BACKEND` | `searxng` |
   | `CRP_COMPLY_SEARXNG_URL` | `http://crp-comply-searxng.railway.internal:8080` |
   | `CRP_COMPLY_SEARXNG_ENGINES` | leave empty — engines now selected by the host-side agent |
6. **Redeploy** `crp-comply-search`. Verify in its logs: `backend=searxng url=http://crp-comply-searxng.railway.internal:8080`.
7. **Smoke test** from a Railway shell on `crp-comply-search`:
   ```bash
   curl -s -X POST http://crp-comply-searxng.railway.internal:8080/search \
     -d 'q=GDPR+article+5&format=json&crp_intent=regulation_text' | jq '.results[0].url'
   # Expect a eur-lex.europa.eu URL near the top.
   ```

### 3.3 Local dev (optional)

```powershell
cd c:\Users\User\Desktop\crp-comply
docker build -t crp-comply-searxng services/crp-comply-searxng
docker run --rm -p 8080:8080 -e SEARXNG_SECRET_KEY=$(openssl rand -hex 32) crp-comply-searxng
```

## 4. What's still pending in 7.15

These are explicitly NOT in this commit; they land in the next pass:

- [ ] `services/crp-comply-search/src/crp_comply_search/intelligence/query_expander.py` — LLM-driven sub-query fan-out, gated off in lane A.
- [ ] `services/crp-comply-search/src/crp_comply_search/intelligence/reranker.py` — `cross-encoder/ms-marco-MiniLM-L-6-v2`, top-20 → top-6.
- [ ] `services/crp-comply-search/src/crp_comply_search/intelligence/chunker.py` — chunk-and-cite passages with `citation_id`.
- [ ] `web_research`, `vendor_profile`, `compare_documents` tool definitions in `src/crp_comply/agent/tools.py`.
- [ ] `LoopEvent.WEB_EXPAND`, `WEB_RERANK`, `WEB_CITE` registered in `src/crp_comply/api/events.py` + frontend mirror.
- [ ] Feedback-loop call site: when the orchestrator finalises a run with web citations actually used, `POST /crp/feedback` to the SearXNG host so it learns.
- [ ] Tests: `tests/test_searxng_intelligence.py`, `tests/test_vendor_profile.py`, `tests/test_compare_documents.py`, `services/crp-comply-search/tests/test_searxng_self_hosted.py`.
- [ ] Frontend fixtures + `ReasoningTape` cards for the three new events.

Once all of the above land, 7.15 closes and Phase 7 is fully done sans the
deliberately-deferred 7.13/7.14.
