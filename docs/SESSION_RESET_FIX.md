# Session reset / LLM setup reset fix

## Problem

Users were being kicked back to onboarding and losing their LLM-provider
configuration every ~20 minutes on Railway-hosted deployments.

Root causes:

1. **Ephemeral filesystem.** Railway free / hobby containers lose their local
   filesystem on sleep/restart unless a persistent volume is attached. The
   backend stored OrgProfile, provider config, and agent sessions under
   `{CRP_COMPLY_DATA_DIR}`.
2. **Aggressive idle sign-out.** The frontend previously signed users out after
   30 minutes of inactivity.
3. **No refresh-token flow.** Internal JWTs expired after one hour; a fresh
   sign-in was required.

## What changed

### 1. Pluggable persistence backend (`crp_comply.persistent_json_store`)

A new generic key/value store supports file (default) or Redis backends via
environment variables:

```bash
# strongly recommended for production SaaS deployments
CRP_COMPLY_PERSISTENCE_STORE=redis
CRP_COMPLY_REDIS_URL=redis://localhost:6379/0
# 0 = no expiration for tenant/provider/session data
CRP_COMPLY_PERSISTENCE_TTL_SECONDS=0
```

The following data now survives container restarts:

* OrgProfile (`crp_comply.org_profile`)
* Per-user LLM provider config (`crp_comply.api.provider`)
* Agent session records (`crp_comply.api.agent`)
* CSO / agent memory (`CRP_COMPLY_CSO_STORE=redis`)

### 2. Frontend idle sign-out relaxed

`frontend/src/App.tsx` now defaults to:

* **55-minute warning**
* **60-minute idle sign-out**
* **8-hour sign-out when "Remember this device" is enabled** (toggle UI will
  follow in a later release)

The previous 25/30-minute thresholds are gone.

### 3. Reasoning visibility and response quality

* The system prompt now explicitly instructs the agent to call
  `consult_regulation_expert` when the user names a specific framework.
* Direct-answer lengths were increased so brief/standard answers are no longer
  one-sentence responses.
* `AgentResult`, `AgentSessionState`, and the chat UI now expose a
  `reasoning_tape` and the list of `experts_invoked` so users can see how an
  answer was built.

## Migration

1. Provision a Redis instance (Railway "Add a service" → Redis).
2. Copy the Redis URL into your environment variables:
   `CRP_COMPLY_REDIS_URL`.
3. Set `CRP_COMPLY_PERSISTENCE_STORE=redis`.
4. Redeploy. Existing file-backed data is not auto-migrated; export/import via
   the existing API if you need to preserve current tenant profiles.

## Verification

* Backend: `pytest tests/test_persistent_json_store.py tests/test_provider_context.py tests/test_api_agent.py`
* Frontend: `cd frontend && npm run build`
