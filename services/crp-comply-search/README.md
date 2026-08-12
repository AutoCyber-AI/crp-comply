# crp-comply-search

Standalone web-search sidecar for the **crp-comply** language-agent
loop (PHASE_7 §7.8 / §16). It fans out compliance queries to
DuckDuckGo (default), Brave Search, or Tavily, applies a
git-tracked trust-tier YAML profile, fetches and hashes every
result, and returns a typed JSON envelope the main API can splice
into the agent's tool stream.

The sidecar is **a separate service** by design (PHASE_7 §16.1 +
§21 7.8 — "do not inline the sidecar back into the main app"). It
runs in a separate process, with its own Dockerfile, its own
Railway service, and reaches the main API only over the Railway
private network.

## Endpoints

| Method | Path        | Description                                   |
|--------|-------------|-----------------------------------------------|
| POST   | `/search`   | Run one query against the configured backend. |
| POST   | `/research` | Multi-query expansion + dedupe.               |
| GET    | `/health`   | Liveness.                                     |
| GET    | `/metrics`  | Prometheus counters + histograms.             |

## Configuration

| Env var                          | Default                               | Notes |
|----------------------------------|---------------------------------------|-------|
| `CRP_COMPLY_SEARCH_BACKEND`      | `local`                               | `local` / `brave` / `tavily` |
| `CRP_COMPLY_SEARCH_PROFILE`      | `crp_comply_official`                 | Loaded from `profiles/`. |
| `CRP_COMPLY_SEARCH_PROFILES_DIR` | (bundled `profiles/`)                 | Override for tenant forks. |
| `CRP_COMPLY_ENABLE_BRAVE`        | `0`                                   | Required to enable Brave backend. |
| `CRP_COMPLY_ENABLE_TAVILY`       | `0`                                   | Required to enable Tavily backend. |
| `CRP_COMPLY_SEARCH_API_KEY`      | (none)                                | Bearer token clients must present. |
| `CRP_COMPLY_SEARCH_DDG_DELAY`    | `1.2`                                 | DDG min-delay seconds (§16). |

## Audit trail

Every result carries `content_hash` (sha256 of the fetched body)
and a `raw_text_blob_id` placeholder so the main API can replay
the exact bytes the LLM saw (§16.6).

## Deployment on Railway

This is its own service. See
[`docs/RAILWAY_SEARCH_SIDECAR.md`](../../docs/RAILWAY_SEARCH_SIDECAR.md)
for the recommended layout (single repo, two services, different
start commands).
