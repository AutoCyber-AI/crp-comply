# CRP Comply — Railway Setup Guide

This guide deploys CRP Comply to [Railway](https://railway.app) with Redis for cross-process CSO/session persistence.

## 1. Prerequisites

- A Railway account (https://railway.app).
- The `crp-comply` repo pushed to GitHub.
- A GitHub App or personal access token if you plan to use auto-remediation PRs.

## 2. Create the Railway project

```bash
railway login
railway init --name crp-comply
```

Or create the project in the Railway dashboard and connect the GitHub repo.

## 3. Add a Redis service

Option A — Railway CLI:

```bash
railway add --database redis
```

Option B — Dashboard:

1. Click **New** → **Database** → **Add Redis**.
2. Wait for the service to provision.

Railway injects the Redis URL as the `REDIS_URL` environment variable automatically.

## 4. Configure environment variables

In the Railway dashboard (or via `railway variables`), set the following on the **CRP Comply service**:

| Variable | Value | Purpose |
|----------|-------|---------|
| `CRP_COMPLY_CSO_STORE` | `redis` | Switches session memory from file to Redis. |
| `CRP_COMPLY_REDIS_URL` | `${{Redis.REDIS_URL}}` | References the Redis service URL. |
| `CRP_COMPLY_CSO_TTL_SECONDS` | `604800` | Session TTL (7 days). Adjust as needed. |
| `CRP_COMPLY_DATA_DIR` | `/app/data` | Local fallback/data directory. |
| `OPENAI_API_KEY` | *(secret)* | Hosted LLM provider key. |
| `ANTHROPIC_API_KEY` | *(secret)* | Optional second provider. |
| `CRP_GATEWAY_KEY` | *(secret)* | CRP Gateway key if using Gateway routing. |
| `GITHUB_APP_ID` | *(secret)* | GitHub App ID for remediation PRs. |
| `GITHUB_APP_PRIVATE_KEY` | *(secret)* | GitHub App private key PEM. |

> **Note:** Use Railway reference variables (`${{Redis.REDIS_URL}}`) so the URL updates automatically if Redis is reprovisioned.

## 5. Deploy

```bash
railway up
```

Railway will build the Dockerfile (or `nixpacks` if no Dockerfile) and deploy the service.

## 6. Verify

1. Open the deployed service URL.
2. Check the health endpoint:
   ```bash
   curl https://<your-domain>/health
   ```
3. Start a chat session, then redeploy (`railway up`).
4. Re-open the same session — your CSO and context should persist via Redis.

## 7. Scaling / production notes

- Redis is used for **session persistence**, not long-term archival. Set `CRP_COMPLY_CSO_TTL_SECONDS` to match your retention policy.
- For sensitive deployments, enable Redis TLS and set `rediss://` in `CRP_COMPLY_REDIS_URL`.
- If Redis is unreachable, `CompliantMemory` falls back to a blank session and logs a warning — the app stays up.
- Attach a persistent volume at `/app/data` if you still need file-based storage for logs or exports.

## 8. Adding a custom domain

```bash
railway domain
```

Or add one in the service settings in the Railway dashboard.
