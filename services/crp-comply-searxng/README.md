# crp-comply-searxng

Self-hosted SearXNG sidecar — the **second of two intelligent agents** in
the CRP Comply web-search stack.

```
┌─────────────────┐     POST /search        ┌──────────────────────┐
│ main FastAPI    │ ──────────────────────▶ │ crp-comply-search    │
│ (agent loop)    │                          │  (intelligence #1)   │
└─────────────────┘                          │   • query expansion  │
                                             │   • cross-encoder    │
                                             │     rerank           │
                                             │   • chunk + cite     │
                                             │   • vendor_profile   │
                                             │   • compare_documents│
                                             └──────────┬───────────┘
                                                        │ JSON
                                                        ▼
                                             ┌──────────────────────┐
                                             │ crp-comply-searxng   │
                                             │  (intelligence #2 —  │
                                             │   THIS service)      │
                                             │   • intent-aware     │
                                             │     engine routing   │
                                             │   • authority        │
                                             │     fingerprinting   │
                                             │   • feedback-driven  │
                                             │     learning         │
                                             │     reranker         │
                                             │   • CRP custom       │
                                             │     engines          │
                                             │     (EUR-Lex, EDPB,  │
                                             │      CURIA, BAILII)  │
                                             └──────────────────────┘
```

## What's in here

```
services/crp-comply-searxng/
├── Dockerfile               # FROM searxng/searxng:<pinned> + overlay
├── settings.yml             # opinionated, audit-grade config
├── limiter.toml             # private-network politeness
├── railway.toml             # Railway deployment recipe (internal-only)
├── engines/
│   ├── eur_lex.py           # EUR-Lex CELEX search
│   ├── edpb.py              # European Data Protection Board register
│   ├── bailii.py            # UK & Ireland case law
│   └── curia.py             # CJEU case law
└── plugins/
    ├── query_router.py      # intent-aware engine selection (agent #2.A)
    └── learning_reranker.py # feedback-driven engine scoring  (agent #2.B)
```

## Why two agents

| Agent | Lives in | Decides |
|---|---|---|
| **#1 (client)** `crp-comply-search` | Python sidecar | sub-query expansion, cross-encoder reranking of document hits, chunk-and-cite, vendor profiling, document comparison. |
| **#2 (host)** `crp-comply-searxng` | this service | which engines to fan out to per query, per intent, per learned utility; rewrites the SearXNG `engineref_list` *before* any HTTP egress. |

Two-stage agency means the host stops asking engines that don't help
*before* the client wastes tokens reranking their results.

## Server-side intelligence: how the host learns

`plugins/learning_reranker.py` exposes:

- `POST /crp/feedback` — `crp-comply-search` posts `{intent, engine, useful}` after the agent loop closes a run with that citation actually used in the final output.
- `GET /crp/scores/<intent>` — current per-engine decayed utility (Prometheus + ops dashboard).

The router plugin reads `engine_scores(intent)` on every request and reorders engines accordingly. Engines that consistently produce useful citations climb; engines that don't drift down. Cold-start fallback is the static intent ordering in `settings.yml::crp_agent.router.intents`.

## Build & deploy locally

```bash
docker build -t crp-comply-searxng services/crp-comply-searxng
docker run --rm -p 8080:8080 \
  -e SEARXNG_SECRET_KEY=$(openssl rand -hex 32) \
  -e SEARXNG_REDIS_URL=redis://host.docker.internal:6379/0 \
  -v searxng_crp:/var/lib/searxng-crp \
  crp-comply-searxng
curl 'http://127.0.0.1:8080/search?q=GDPR+article+5&format=json&crp_intent=regulation_text'
```

## Submodule note (Windows authors)

The submodule contains one file (`utils/templates/etc/httpd/sites-available/searxng.conf:socket`) whose name is invalid on NTFS. The submodule is sparse-checked-out on Windows to skip it (`.git/info/sparse-checkout = !/utils/templates/etc/httpd/sites-available/`); CI and Railway (Linux) check it out fully and don't need the workaround.
