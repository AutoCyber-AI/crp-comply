# Product Security Posture — CRP-Comply

**Status:** Living document — updated with each release.
**Last updated:** 2026-04-24
**Audience:** security reviewers, customers' infosec teams, internal engineers.

This document describes the security posture of the CRP-Comply product
itself (as distinct from the compliance reports it produces for its users).
It pairs with [docs/BYOK_MODES.md](docs/BYOK_MODES.md) (data-flow
diagrams), [docs/VOLUME_PERSISTENCE.md](docs/VOLUME_PERSISTENCE.md)
(backup / restore / residency), and
[LLM_INTELLIGENCE_DESIGN.md §10](LLM_INTELLIGENCE_DESIGN.md) (agent-level
threat model).

> **Threat model summary.** We build a regulated-industry product. The most
> damaging realistic attacks are (a) extracting other tenants' data, (b)
> injecting text into a user's free-form description that subverts the
> compliance analyst, (c) leaking BYOK LLM keys, (d) tampering with an
> evidence pack post-issuance. Mitigations for each are enumerated below.

---

## 1. Controls already shipped

| Domain | Control | Where it lives |
|---|---|---|
| **Authentication** | API keys (`crc_*`), JWT (HS256), Clerk OIDC w/ JWKS cache | `src/crp_comply/api/auth.py` |
| **Authorisation** | Per-tier feature matrix; 403 on out-of-tier access | `api/sdk.py::SDK_FEATURE_MATRIX`, `api/deps.py::_require_feature_or_403` |
| **Quota enforcement** | Monthly call cap per tier, counter in `meter_call` | `api/deps.py`, `api/usage.py` |
| **Prompt-injection defense** | System prompt frames user input as untrusted narrative; tools are the only classification emitter (LLM cannot directly label a system "low-risk") | `agent/orchestrator.py::SYSTEM_PROMPT`, `agent/tools.py` |
| **PII redaction pre-LLM** | `crp.security.PIIScanner` + regex fallback (EMAIL/PHONE/CARD/IBAN) wraps task + extra_context before the first LLM call | `agent/crp_integration.py::redact_pii`, wired in `agent/orchestrator.py::run` |
| **Contradiction detection** | New user statements are checked against prior CKF facts via `crp.extraction.contradiction` | `agent/crp_integration.py::detect_hit_contradictions` |
| **Clarification budget** | Hard cap of 6 clarification rounds per report — past that the agent proceeds with stated assumptions (logged) instead of hanging | `agent/orchestrator.py::DEFAULT_CLARIFICATION_BUDGET` |
| **Tenant isolation (data)** | All user artefacts keyed by `user_id` under `data/reports/{user}/…`, `ckf/{user}/…` — no cross-tenant filesystem paths | `api/reports.py`, `api/persistence_probe.py` |
| **Audit trail** | Every envelope + tool call + LLM request + extracted fact persisted to `reports/{user}/{session}/trace.jsonl`; included in evidence pack | `agent/orchestrator.py` |
| **Evidence-pack integrity** | SHA-256 content-hashed, HMAC-signed bundle | `core.py`, `api/reports.py` |
| **Secret handling** | BYOK LLM keys encrypted at rest (libsodium secretbox, key derived from `CRP_COMPLY_JWT_SECRET`); never logged; redacted in stack traces | `api/provider.py` |
| **Transport** | All production traffic via Railway TLS termination; HSTS enabled by platform | Railway config |
| **Output-bound CRP-ness** | Agent outputs go through CRP envelope packer → every chunk the LLM saw is hashable and replayable | `agent/crp_integration.py::pack_hits_to_envelope` |
| **Supply-chain** | `pyproject.toml` pins; `dependabot.yml` active; Ruff linter in CI | `.github/dependabot.yml`, `.github/workflows/ci.yml` |
| **Container posture** | Non-root user, minimal base image, volume-scoped data dir | `Dockerfile`, `docker-entrypoint.sh` |
| **Proxy mode** | Interceptor runs all requests through `run_pii_scan` + `run_injection_check` before forwarding to the upstream provider | `proxy/interceptor.py` |
| **Copyright/IP guard** | Corpus ingest flags license of every chunk; ISO 42001 stored by clause ID not verbatim redistribution | `agent/corpus.py::CorpusDocument.license` |
| **Corpus integrity** | Every chunk carries `source_url` + `retrieved_at` + `content_hash`; Live Regulation CI preserves versions | `agent/corpus.py`, `.github/workflows/live-regulation-ci.yml` |

---

## 2. OWASP Top-10 (2021) mapping

| Risk | Our primary mitigation |
|---|---|
| A01 Broken Access Control | Per-tier feature matrix checked at every SDK/agent endpoint via `_require_feature_or_403`; user_id derived from authenticated principal, never from request body. |
| A02 Cryptographic Failures | bcrypt for passwords (`passlib`); HS256 JWT w/ env-provided secret ≥ 32 bytes; libsodium secretbox for BYOK keys; TLS at Railway edge. |
| A03 Injection | LLM prompt-injection mitigated via tool-only classification + system-prompt framing + `run_injection_check`. SQL: no raw SQL — JSON file persistence + sqlite via parameterised queries only. |
| A04 Insecure Design | Agent tools are deterministic Python, not LLM calls — the LLM cannot invent an article number or a fine amount. Clarification budget prevents infinite loops. |
| A05 Security Misconfiguration | Defaults are tight: `CRP_COMPLY_ENVIRONMENT=production` disables debug routes; CORS allow-list is explicit; Docker runs as non-root. |
| A06 Vulnerable & Outdated Components | Dependabot weekly; pinned `pyproject.toml`; Ruff + pytest in CI. |
| A07 Identification & Authentication Failures | API keys hashed before storage (never comparable via plaintext); JWT expiry default 1 h; Clerk JWKS cache with TTL. |
| A08 Software & Data Integrity Failures | Evidence pack HMAC signature; corpus `content_hash`; immutable report trace (append-only JSONL). |
| A09 Security Logging & Monitoring Failures | Every agent step + tool call logged; trace persisted per-session; Live Regulation CI opens a PR for any corpus drift. |
| A10 Server-Side Request Forgery | Scrapers target an allow-list of regulator hosts (EUR-Lex, NIST, OECD, CoE, gov.uk, EDPB); no user-controlled URL fetching in production paths. |

---

## 3. Data-flow summary

```
  User (browser or pip SDK)
     │
     ▼  HTTPS (TLS 1.2+)
  Railway edge ─► FastAPI app
     │                │
     │                ├─ auth.py       (API key / JWT / Clerk verify)
     │                ├─ deps.py       (tier gate, quota meter)
     │                ├─ agent/        (orchestrator → tools → LLM)
     │                │    ├─ redact_pii (pre-LLM)
     │                │    ├─ injection_check
     │                │    └─ contradiction_detect
     │                ├─ proxy/        (in-line interceptor, same filters)
     │                └─ reports/      (signed evidence packs)
     │
     └─ BYOK LLM endpoint (cloud or tunnel or SDK worker)
        — only `{prompt → response}` crosses this boundary.
```

**Nothing proprietary ever reaches the user's device.** Prompts, tool
implementations, regulation RAG, orchestrator state machine all stay
server-side. The pip SDK is 100% public, auditable source.

---

## 4. Residual gaps (tracked)

These are known limitations as of 2026-04-24. Each has an owner and a
ship target.

| # | Gap | Severity | Plan |
|---|---|---|---|
| 1 | No rate limiting beyond per-tier monthly quota — a single user can burst all N calls in 1 minute | medium | Add per-minute token bucket in `deps.py::meter_call` (SlowAPI or Redis if available). |
| 2 | No signed webhook outbound (e.g. to Slack / customer SIEM for incidents) | low | Design in v1.1; not a regulator ask. |
| 3 | BYOK key rotation flow is manual (user deletes + re-enters) | low | Add `POST /settings/llm-keys/rotate` endpoint. |
| 4 | Evidence pack signing uses HMAC (symmetric); a compromised server key forges any past pack | medium | Migrate to detached Ed25519 signatures + publish public key in `/.well-known/crp-comply-evidence-key.pub`. |
| 5 | No tenant-configurable retention windows (default is 180 d reports / 365 d evidence) | low | Tenant setting; store in user profile. |
| 6 | Proxy mode does not yet stream tokens — it buffers and filters then forwards | low | Streaming pass on SSE is queued with frontend chat UI. |
| 7 | No periodic secret re-derivation / KDF rotation | low | When Stripe wiring lands, adopt rotating KEK. |
| 8 | No DAST/SAST in CI beyond Ruff — no `pip-audit` or `bandit` run | medium | Add both to `.github/workflows/ci.yml` in the next security pass. |
| 9 | Live Regulation CI job has `contents: write` + `pull-requests: write` — needs path-scoped write so a compromised action cannot rewrite source code | medium | Replace with deploy key or GitHub App scoped to `corpus/**` only. |
| 10 | No rate limit on scraper targets — bursty Live Regulation CI could trip a regulator's WAF | low | Per-host `time.sleep` already present in `scrapers/base.py`; review delays. |

None of the above block the v1 paid launch.

---

## 5. Responsible disclosure

Please email security reports to `security@crprotocol.io` with PGP
encryption if the issue is sensitive. See [SECURITY.md](SECURITY.md) for
the full coordinated-disclosure policy.

---

## 6. Regulatory claims we make about ourselves

- **GDPR processor posture:** we process customer compliance data under a
  DPA; sub-processors (Railway, LLM providers) are listed and can be
  pinned off via BYOK.
- **EU AI Act:** CRP-Comply itself is a *general-purpose* compliance tool;
  we don't make high-risk-AI claims about our own product because the
  decisional output is *advisory* and every classification is produced by
  a deterministic tool (not an LLM).
- **ISO 42001 self-audit:** the Statement of Applicability we plan to ship
  as an agent recipe (§16.2 of the design doc) will also be executed
  against ourselves and published with each release.

---

## 7. Change log

- **2026-04-24** — Initial posture doc. Captures controls shipped in
  crp-comply `ef366c7` + CRP 2.3.1. Ten residual gaps tracked.
