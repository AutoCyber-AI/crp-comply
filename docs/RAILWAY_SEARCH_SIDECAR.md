# Deploying the web-search sidecar on Railway

PHASE_7 §7.8 ships **`crp-comply-search`** as a *separate*
deployable service, not an in-process module. The main API
(`crp-comply`) talks to it over Railway's private network using
`CRP_COMPLY_SEARCH_URL` and a shared bearer token.

## TL;DR — same repo, two services

> **Recommended:** keep both halves in the *same* GitHub repo and
> create **two Railway services** in **one Railway project**, with
> different Root Directories and start commands.

Why not separate repos:

* The trust-tier YAML profiles, the `loop.web.start` /
  `loop.web.result` event schemas, and the audit format
  (`content_hash`, `raw_text_blob_id`) are **shared contracts**.
  Splitting them across repos guarantees they drift.
* One PR ships both halves atomically — no "main API expects v2,
  sidecar is still on v1" releases.
* Railway natively supports per-service "Root Directory" so a
  single repo with two Dockerfiles is the canonical layout.
* Billing/observability is per-service either way; nothing is
  gained by separate repos.

Why not a single service with `procfile`-style multi-process:

* PHASE_7 §21 7.8 mandates separation: the sidecar must be its
  own process so it can be scaled, restarted, and rate-limited
  independently. Inlining it would also re-introduce the DDoS
  surface area we deliberately moved off the API container.

## Layout

```
crp-comply/                         ← repo root
├── Dockerfile                      ← main API
├── pyproject.toml                  ← main API
├── src/crp_comply/...              ← main API code
└── services/
    └── crp-comply-search/          ← sidecar (separate service)
        ├── Dockerfile
        ├── pyproject.toml
        ├── railway.toml
        └── src/crp_comply_search/...
```

## One-time Railway setup

1. **Create the project.** New project → "Deploy from GitHub" →
   point at the `crp-comply` repo. Railway will create the first
   service from the *root* `Dockerfile`. Rename it to
   **`crp-comply`** in the service settings.

2. **Add the sidecar service.** In the same project: "+ New" →
   "GitHub Repo" → same repo. Open the new service's settings:

   | Setting          | Value                              |
   |------------------|------------------------------------|
   | Service name     | `crp-comply-search`                |
   | Root Directory   | `services/crp-comply-search`       |
   | Builder          | Dockerfile                          |
   | Dockerfile path  | `Dockerfile` (relative to root dir) |
   | Start Command    | *(leave blank — image CMD wins)*    |
   | Health Check Path| `/health`                          |

   Railway picks up `railway.toml` inside the root dir
   automatically; the table above is what to verify in the UI.

3. **Set sidecar env vars** (Service `crp-comply-search` →
   Variables):

   ```
   CRP_COMPLY_SEARCH_BACKEND     = local
   CRP_COMPLY_SEARCH_PROFILE     = crp_comply_official
   CRP_COMPLY_SEARCH_API_KEY     = <generate a 32-byte hex secret>
   CRP_COMPLY_SEARCH_DDG_DELAY   = 1.2
   # Brave/Tavily are stubs; do NOT set ENABLE_* unless you have keys:
   # CRP_COMPLY_ENABLE_BRAVE     = 1
   # BRAVE_API_KEY               = ...
   ```

4. **Wire the main API** (Service `crp-comply` → Variables) to
   reach the sidecar over the private network. Railway exposes
   each service on `${{<service>.RAILWAY_PRIVATE_DOMAIN}}` (port
   `PORT`, which we expose as `8081`):

   ```
   CRP_COMPLY_SEARCH_URL  = http://${{crp-comply-search.RAILWAY_PRIVATE_DOMAIN}}:8081
   CRP_COMPLY_SEARCH_API_KEY = <same secret as the sidecar>
   ```

   The `${{ ... }}` reference syntax tells Railway to resolve the
   value from the other service at deploy time and re-deploy the
   API automatically when the sidecar's domain changes.

5. **Do not expose the sidecar publicly.** In the sidecar
   service's "Networking" tab, leave "Public Domain" off. Only
   the private domain is needed; the main API is the sole client.

## Verifying the wiring

After both services deploy:

```bash
# From inside the API container (Railway → service → "Connect"):
curl -s -H "Authorization: Bearer $CRP_COMPLY_SEARCH_API_KEY" \
     "$CRP_COMPLY_SEARCH_URL/health" | jq
```

Expected:

```json
{
  "status": "ok",
  "backend": "local",
  "profile": "crp_comply_official",
  "profiles": ["crp_comply_official", "crp_comply_news"],
  "version": "0.1.0"
}
```

If the API can't reach the sidecar, check:

* Both services are in the **same Railway project** (private
  networking only spans one project).
* The sidecar binds `0.0.0.0` (the bundled `__main__` does).
* `CRP_COMPLY_SEARCH_URL` uses `http://` *and* the
  `RAILWAY_PRIVATE_DOMAIN` reference, not the public domain.

## Scaling notes

* The sidecar is stateless; horizontal scaling works, but the
  DDG rate limiter is **per-process**. If you scale to N replicas
  you effectively get N×(1/`CRP_COMPLY_SEARCH_DDG_DELAY`)
  queries/sec to DuckDuckGo, which they'll throttle. Stay at 1
  replica for the local backend, or switch to Brave/Tavily before
  scaling out.
* CPU is dominated by HTML parsing; a small instance (512 MB,
  0.5 vCPU) is plenty for 5–10 rps.

## Upgrade path

To switch off DDG: set `CRP_COMPLY_SEARCH_BACKEND=brave`,
`CRP_COMPLY_ENABLE_BRAVE=1`, `BRAVE_API_KEY=...`. Restart the
sidecar service only; the main API does not need to redeploy.
