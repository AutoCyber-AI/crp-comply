# Production Readiness Assessment

**Date:** 2026-04-25
**Owner:** engineering lead
**Scope:** decide what must change before charging the first paying
customer; document the path from "feature-complete in dev" to "stable
under multi-tenant production load with revenue at stake".
**Companion docs (do not duplicate):**

- [COMPLIANCE_MODEL_GAPS.md](COMPLIANCE_MODEL_GAPS.md) — engineering ledger.
- [PRODUCT_SECURITY.md](PRODUCT_SECURITY.md) — OWASP posture, security controls.
- [STRATEGIC_REASSESSMENT.md](STRATEGIC_REASSESSMENT.md) — product scope.
- [HOSTING_POSITIONING.md](HOSTING_POSITIONING.md) — Railway / cloud / SDK lanes.
- [STRIPE_MONETISATION.md](STRIPE_MONETISATION.md) — pricing + billing wiring.

> **Bottom line.** Substrate is production-grade: **450 backend tests
> green** (was 431), security primitives shipped, evidence layer signed,
> multi-tenant isolation tested, BYOK working, CI lints/tests/scans on
> every push. **Backups + DR + GDPR Art. 17/20 self-service shipped
> April 2026** (`crp_comply.backup` module, `/me/export`, `/me`, paid
> `/me/backups`, `backup-all` CLI, `scripts/backup-nightly.sh`). The
> remaining gap to "100%" is **frontend collapse + recipe coverage +
> launch-checklist execution**, not architecture rework. Realistic path
> to first paying customer: walk [USER_ACTIONS_REQUIRED.md](USER_ACTIONS_REQUIRED.md)
> and the §6 launch checklist.

---

## 1. Readiness Scorecard

Each axis is scored 0–5. "Production-ready" = ≥4.

| Axis | Score | Evidence | Gap to 5/5 |
|---|---|---|---|
| **Backend correctness** | 5 | 450 tests pass; deterministic eval harness ships 13 cases | none |
| **Security primitives** | 5 | OWASP top-10 mapped; Ed25519 signing, BYOK encryption, rate-limit, PII redaction, bandit + pip-audit in CI | none — see §2 |
| **Multi-tenant isolation** | 5 | `tests/test_batch10_tenant_isolation.py` enforces full cross-tenant denial | none |
| **Evidence layer** | 5 | `DerivationManifest` + signed bundles + staleness endpoint | render pills in Reports vault (§B13) |
| **Agent orchestration** | 4 | tool-calling, clarification budget, continuation, contradiction; no SSE streaming, no mid-draft interrupts | §B5 streaming, §B10 interrupts |
| **LLM provider abstraction** | 4 | OpenAI, Anthropic, BYOK, autodetect, fallback; live-LLM smoke test now in CI-optional | §B7 per-task routing wiring |
| **Recipe coverage** | 3 | 12 recipes shipped; 4 v1 must-haves missing (FRIA, SoA, ISO 23894, NIST RMF Profile) | §B3 |
| **Frontend** | 3 | Workspace + AgentChat both live; provenance pills render; 8-state programme collapses to 4 | §B1 collapse, §B14 8-state, §B13 vault pills |
| **Billing & monetisation** | 5 | Stripe live; 5 tiers (FREE/STARTER/PRO/ENTERPRISE/CLOUD); /billing/status; metered overage via Billing Meters API; payment-action-required webhook | token-grain telemetry §B8 |
| **CI/CD** | 4 | Lint + 3.10–3.13 matrix + frontend tsc + docker + bandit + pip-audit | live-LLM smoke optional; vitest TODO |
| **Docs** | 5 | Single gap-tracker, single readiness doc, single security doc, single hosting doc | none |
| **Operational runbook** | 4 | Volume persistence + BYOK modes documented; **backup/restore CLI shipped**; **`scripts/backup-nightly.sh` + R2 off-site path documented**; managed-backup endpoints (`/me/backups`) live | restore drill in production must be performed once (§3.6) |
| **Eval harness** | 4 | 13 deterministic cases; live-LLM smoke test ships | expand to 20 cases (§B2) |

**Overall:** 4.2 / 5 — fit for design-partner / first-customer, gated on
the eight 🟥 / 🟧 items in §4 and the launch checklist in §6.

---

## 2. Security Posture (cross-references PRODUCT_SECURITY.md)

| Control | Status | Module |
|---|---|---|
| Authentication (JWT + Clerk) | ✅ | [src/crp_comply/api/auth.py](src/crp_comply/api/auth.py) |
| Per-tenant data isolation | ✅ | [tests/test_batch10_tenant_isolation.py](tests/test_batch10_tenant_isolation.py) |
| BYOK encryption-at-rest | ✅ | [src/crp_comply/api/byok.py](src/crp_comply/api/byok.py) |
| Ed25519 evidence signing | ✅ | [src/crp_comply/recipes/derivation.py](src/crp_comply/recipes/derivation.py) |
| Rate limiting | ✅ | [src/crp_comply/api/rate_limit.py](src/crp_comply/api/rate_limit.py) |
| PII pre-LLM redaction | ✅ | [src/crp_comply/agent/redactor.py](src/crp_comply/agent/redactor.py) |
| Prompt-injection defences | ✅ | covered in `tests/test_security_primitives.py` |
| Static analysis (bandit) | ✅ | `.github/workflows/ci.yml` `security-bandit` job |
| Dependency scanning (pip-audit) | ✅ | `.github/workflows/ci.yml` `security-pip-audit` job |
| HTTPS / TLS termination | 🟡 | provided by Railway; verify on custom domain |
| Secrets in env vars (no commits) | ✅ | `.gitignore` covers; PyPI token rotation pending (§D1) |
| Audit log of mutations | 🟡 | structured logs exist; no immutable WORM store yet |
| Backup + restore drill | 🟡 | code paths shipped (`crp_comply.backup`, `scripts/backup-nightly.sh` wrapping `crp-comply backup-nightly`, `python -m crp_comply restore`); production drill still pending |
| SOC 2 attestation | 🔵 | deferred — see COMPLIANCE_MODEL_GAPS §C |

**Pre-launch security must-do (blocking):**

1. Rotate the leaked PyPI token referenced in §D1 of the gap tracker.
2. Verify TLS + HSTS on the production custom domain.
3. Document a backup → restore drill against a non-production environment
   (Railway volume `data/`).

**Pre-launch advised (non-blocking):**

- Append-only audit log for all `POST/PUT/DELETE` API mutations.
- Subresource integrity hashes on the frontend bundle.

---

## 3. Operational Readiness

### 3.1 Hosting topology

Railway-hosted Docker container; persistent volume mounted at
`data/` per [docs/VOLUME_PERSISTENCE.md](docs/VOLUME_PERSISTENCE.md).
Frontend builds to static assets served from the same container or a
CDN.

### 3.2 Required environment variables (production)

> **Authoritative source:** [USER_ACTIONS_REQUIRED.md §1.4](USER_ACTIONS_REQUIRED.md#14--final-env-var-set-for-railway).
> The table below is a summary; the operator-facing guide includes the
> exact ADD / UPDATE / REMOVE actions tied to your current Railway env.

| Variable | Purpose | Notes |
|---|---|---|
| `CRP_COMPLY_DATA_DIR` | Persistent volume mount path | `/app/data` on Railway |
| `CRP_COMPLY_BASE_URL` | Public URL of the deployment | must start with `https://` |
| `CRP_COMPLY_JWT_SECRET` | HS256 signing secret for internal JWTs | rotate quarterly |
| `CRP_COMPLY_CORS_ORIGINS` | CORS allowlist | required, no `*` in prod |
| `CRP_COMPLY_LLM_BASE_URL` | Default LLM endpoint | optional, autodetect fallback |
| `CRP_COMPLY_LLM_API_KEY` | Default LLM key | required if not BYOK-only |
| `CRP_COMPLY_LLM_MODEL` | Default model | e.g. `gpt-4o-mini` |
| `CRP_COMPLY_BYOK_KEY` | Server-side encryption key for BYOK secrets | rotate quarterly |
| `CRP_COMPLY_RATE_LIMIT_RPS` | Per-tenant request budget | default sane |
| `CRP_COMPLY_TELEMETRY` | `0` to disable anonymous metrics | default on |
| `CLERK_ISSUER` | Clerk JWKS issuer | required |
| `CLERK_SECRET_KEY` | Auth | required |
| `VITE_CLERK_PUBLISHABLE_KEY` | Frontend auth | required |
| `STRIPE_SECRET_KEY` | Billing | `<YOUR_STRIPE_SECRET_KEY>` |
| `STRIPE_WEBHOOK_SECRET` | Subscription events | `<YOUR_STRIPE_WEBHOOK_SECRET>` |
| `STRIPE_COMPLY_STARTER_PRICE_ID` | Stripe price ID for the $49 tier | **required** for STARTER checkout |
| `STRIPE_COMPLY_PROFESSIONAL_PRICE_ID` | Stripe price ID for the $199 tier | required for Professional checkout (legacy aliases `STRIPE_COMPLY_PRO_PRICE_ID` and `STRIPE_COMPLY_PROFESISIONAL_PRICE_ID` are also accepted by the backend) |
| `STRIPE_COMPLY_ENTERPRISE_PRICE_ID` | Stripe price ID for the $599 tier | required for Business checkout |
| `STRIPE_METER_EVENT_NAME` | Stripe Billing Meter event name | e.g. `comply_proxy_requests`; enables overage billing |
| `BACKUP_R2_ENDPOINT` + `BACKUP_R2_BUCKET` + `AWS_*` | Off-site backup target | recommended (Cloudflare R2); see [USER_ACTIONS_REQUIRED §2.2](USER_ACTIONS_REQUIRED.md#22--off-site-shipment-via-cloudflare-r2-recommended) |
| `BACKUP_RETENTION_DAYS` | Rolling retention window for the off-site bucket | default 14, set 30 for stricter SLAs |

### 3.3 Persistent state to back up

| Path | Contents | Backup priority | Captured by `backup-all`? |
|---|---|---|---|
| `data/users.json` etc. | User keyed JSON (auth, api_keys, usage) | 🟥 critical | yes |
| `data/ckf/` | Customer fact graphs | 🟥 critical | yes |
| `data/reports/`, `evidence_packs/`, `artefacts/`, `agent_sessions/` | per-user generated artefacts | 🟥 critical | yes |
| `data/managed_backups/` | per-user retained snapshots (paid feature) | 🟥 critical | yes |
| `data/rag_index/` | Regulation embeddings | 🟧 rebuildable from `corpus/` | excluded (rebuildable) |
| `data/storage_prefs.json` | Tenant prefs | 🟥 critical | yes |
| `data/telemetry/` | Anonymous metrics | 🟩 rebuildable | yes (cheap) |
| `data/proxy_audit/` | Append-only proxy audit log | 🟧 useful | yes |

**Backup automation now ships in-tree:**

* `python -m crp_comply backup-all <dest>` writes a verified tarball.
* `scripts/backup-nightly.sh` wraps that + retention pruning + R2 / S3
  / B2 upload (driven by env vars).
* `python -m crp_comply restore <archive> --overwrite --yes` re-hydrates
  a fresh volume in one command.

### 3.4 Health & metrics

- `GET /healthz` — liveness.
- `GET /readyz` — readiness (checks corpus index loaded).
- Structured logs to stdout; Railway captures to log drain.
- No Prometheus / OpenTelemetry exporter today — see post-launch.

### 3.5 Failure modes & recovery

| Failure | Detection | Mitigation |
|---|---|---|
| LLM provider outage | provider returns `error` finish_reason | autodetect fallback in `ComplianceLLM`; user sees retry banner |
| Disk full on `data/` volume | Railway alarm | scale volume; vacuum `telemetry/` |
| BYOK key compromise | manual report | rotate `CRP_COMPLY_BYOK_KEY`; force re-encrypt — runbook missing |
| Stripe webhook missed | reconcile script | manual today; cron desired |
| Corpus index corruption | `/readyz` 500 | rebuild via `python -m crp_comply.scripts.build_index` |

### 3.6 Operational gaps to close before launch

1. **Incident response runbook** — single page: who, where, what to
   restart, how to roll back. *(Pending.)*
2. **Backup → restore drill** in production — the code paths exist
   (`scripts/backup-nightly.sh` + `python -m crp_comply restore`) but
   need to be exercised once against a staging volume. See
   [USER_ACTIONS_REQUIRED.md §2.3](USER_ACTIONS_REQUIRED.md#23--restore-drill-do-this-once-before-opening-signups).
3. **Status page or hosted health dashboard** — even a static page
   pointing at `/healthz`. *(Pending.)*

---

## 4. Path to 100% Readiness

Items below are referenced from
[COMPLIANCE_MODEL_GAPS.md](COMPLIANCE_MODEL_GAPS.md) §B. Closing the
🟥 set is the minimum bar for charging the first customer.

### 4.1 Launch-blocking (🟥)

| Ref | Title | Owner | Estimated complexity | Status |
|---|---|---|---|---|
| §B1 | Frontend collapse — Workspace + AgentChat → Draft | frontend | medium | open |
| §B2 | Eval suite expansion 13 → 20 cases | backend | low (we now have the harness) | open |
| §B3 | Four missing v1 recipes (FRIA, SoA, ISO 23894, NIST RMF Profile) | content | medium | open |
| §2 sec | Rotate leaked PyPI token | platform | trivial | open |
| §3.6 | Incident-response runbook | platform | low | open |
| §3.6 | Backup → restore drill | platform | low | **code shipped** — needs a single staging run |

### 4.2 Strongly advised before first paying customer (🟧)

| Ref | Title |
|---|---|
| §B4 | Live-LLM smoke test in CI-optional lane (now shipped — green against LM Studio) |
| §B5 | SSE streaming to frontend chat |
| §B7 | Per-task model-router wiring (cheap → mid → high) |
| §B8 | Token-grain telemetry for usage-based pricing |
| §B11 | Tier-feature matrix end-to-end audit |
| §B13 | Reports vault renders provenance pills |
| §B14 | Programme.tsx renders all 8 lifecycle states |
| §B16 | Marketing-site framing parity (three-layer narrative) |

### 4.3 Post-launch (🟩 / 🔵)

§B6 SDK Mode C, §B9 unused CRP primitives, §B10 mid-draft interrupts,
§B12 tenant-configurable retention, §B15 staleness badge, §B17 CKF
export, §B18 scraper rate-limits, §B19 live-regulation CI scoping, plus
all of §C deferred-decision categories.

---

## 5. Compliance Posture (the company eating its own dog food)

Because we sell a compliance product, our own posture is part of the
sales conversation.

| Regime | Self-claim | Evidence | Gap |
|---|---|---|---|
| GDPR (we are processor) | ✅ | DPA template ready, BYOK keeps customer data encrypted at rest | publish DPA on website |
| EU AI Act | 🟡 | product itself is **not** high-risk (decision-support tool, human-in-loop, no biometrics, no critical infra) — reasoning documented in [STRATEGIC_REASSESSMENT.md](STRATEGIC_REASSESSMENT.md) | article-by-article self-assessment using our own FRIA recipe (chicken-and-egg with §B3) |
| ISO 42001 | 🔵 | aspirational — run our own product against itself once §B3 SoA recipe ships | none yet |
| NIST AI RMF | 🔵 | same as above | none yet |
| SOC 2 | 🔵 | not pursued for first 12 months | controls inventory drafted in PRODUCT_SECURITY |

**Recommended sequencing:** ship §B3 (FRIA + SoA recipes) → run them on
our own product → publish the resulting reports as the canonical
"the compliance company is itself compliant" sales artefact.

---

## 6. Pre-Launch Checklist

Walk this list start-to-finish before flipping the public DNS.

### 6.1 Code

- [x] `pytest -q` green (currently **450 passed**, 4 skipped — live-LLM)
- [x] `npm run build` in `frontend/` green (verified 26 Apr 2026)
- [x] Landing pricing matches `/pricing` ($0 / $49 / $199 / $599)
- [x] SEO/AEO meta in `frontend/index.html` (title, description, OG,
      Twitter card, canonical, JSON-LD Organization + SoftwareApplication
      + FAQPage)
- [x] `frontend/public/robots.txt` + `frontend/public/sitemap.xml` shipped
- [x] HTTP security-headers middleware (HSTS, CSP, X-Frame-Options=DENY,
      X-Content-Type-Options=nosniff, Referrer-Policy, Permissions-Policy,
      COOP/CORP) — `crp_comply.api.app._security_headers`
- [x] In-process nightly backup scheduler (asyncio task at 03:00 UTC,
      uploads to Cloudflare R2 / AWS S3, 60-day rolling retention) —
      `crp_comply.backup_scheduler`
- [x] `ruff check .` green (`src/` clean — 0 findings; per-file ignores
      documented in `pyproject.toml` for ordered security imports + PEP-563
      string annotations)
- [x] `bandit -r src/ -ll` green (0 medium/high; 33 low triaged, none
      affect production paths)
- [x] `pip-audit` triaged (10 CVEs in transitive deps; project pins bumped
      for `python-multipart>=0.0.26` + `lxml>=6.1`; remainder live in
      conda env, do not affect production wheel)
- [ ] Frontend collapse §B1 merged (Workspace + AgentChat → Draft — still
      two surfaces; non-blocking, queued post-launch)
- [x] Four missing recipes §B3 merged (FRIA, ISO 42001 SoA, ISO 42001 AI
      Risk Assessment, NIST AI RMF Profile — all shipped under
      `src/crp_comply/recipes/builtin/`)
- [ ] Eval harness ≥ 20 cases (§B2) — currently **13 cases** across
      `ai_act_basic / gdpr / iso42001 / nist_rmf`; 7 short of target,
      non-blocking

### 6.2 Infra

- [ ] Railway production environment provisioned
- [ ] Persistent volume `data/` mounted
- [ ] All env vars from §3.2 set in production env
- [ ] Custom domain DNS pointing at Railway, TLS issued, HSTS verified
- [ ] CORS allowlist matches frontend origin (no `*`)
- [ ] Backup → restore drill performed and timed
- [ ] `/healthz` and `/readyz` return 200 in prod
- [ ] Log drain configured (or at minimum, Railway log retention extended)

### 6.3 Billing

- [x] Stripe live mode keys in production env
- [x] Stripe price IDs set per
      [USER_ACTIONS_REQUIRED.md §1.4](USER_ACTIONS_REQUIRED.md#14--final-env-var-set-for-railway)
      (3 active prices: $49 / $199 / $599; 3 legacy prices archived)
- [x] Webhook endpoint registered, signing secret in env, 6 events subscribed (§1.2)
- [x] `STRIPE_METER_EVENT_NAME=comply_proxy_requests` set; meter receives
      events on the first overage call
- [ ] One full subscription cycle tested in test mode end-to-end
- [ ] Refund / cancel flows tested
- [ ] `GET /api/v1/billing/status` returns plan + period_end after checkout

### 6.4 Auth

- [x] Clerk production instance live
- [x] Allowed redirect URLs include the production domain
- [x] Account-deletion flow tested (GDPR Art. 17) — `DELETE /api/v1/me` shipped
- [x] Account-export flow tested (GDPR Art. 20) — `GET /api/v1/me/export` shipped
- [ ] MFA enforced via frontend `<RequireMfa>` (Clerk free-tier workaround —
      see [USER_ACTIONS_REQUIRED §3](USER_ACTIONS_REQUIRED.md#3--clerk-mfa--programmatic-enforcement-free-tier-workaround))

### 6.5 Compliance

- [x] Privacy policy live and dated (`/privacy` — full GDPR / APP / CCPA notice, 26 Apr 2026)
- [x] Terms of Service live and dated (`/terms` — full binding T&Cs, 26 Apr 2026)
- [x] Contact page live (`/contact`, `contact@crprotocol.io`)
- [x] DPA published / linkable (`/dpa` — full Art. 28 GDPR addendum incl.
      SCC Module 2 references, Annex 1 processing particulars, Annex 2
      security measures, Annex 3 sub-processor list)
- [ ] Cookie banner (or documented exemption) live
- [x] `LICENSE.md` + Elastic License 2.0 visible in repo and footer
- [ ] PyPI token rotated (§D1)

### 6.6 Smoke tests against production

- [ ] Sign-up → first draft → save to vault works
- [ ] BYOK round-trip works (set key, see model echoed in response metadata)
- [ ] Stripe upgrade → tier change reflected in next API call
- [ ] Rate-limiter denies 11th request in 1 s burst (confirms wiring)
- [ ] `tests/test_llm_integration_lmstudio.py` against a small
      production-tier model returns non-empty text

### 6.7 Sign-off

- [ ] Engineering lead: ____________________ date: __________
- [ ] Founder / CEO:    ____________________ date: __________

---

## 7. Known Risks at Launch (and what we do if they hit)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Tiny local-LLM customers report poor draft quality | high | medium | docs explicitly recommend mid-tier models for drafting; eval harness publishes per-model scores |
| Recipe coverage gap surfaces in early sale | medium | high | publish [RECIPE_COVERAGE_TRACKER.md](RECIPE_COVERAGE_TRACKER.md) on the marketing site; commit roadmap dates |
| LLM provider outage during a customer demo | medium | medium | autodetect fallback already shipped; document the failover behaviour |
| Pricing-page friction (Stripe price IDs wrong) | low | high | test-mode dry run in §6.3 |
| Customer asks for SOC 2 in month 1 | medium | low | gracefully decline + commit roadmap; controls inventory in PRODUCT_SECURITY |
| Regulator asks for our own FRIA | low | high | ship §B3 and run it on ourselves *before* first regulated-industry customer |

---

## 8. Success Metrics for the First 90 Days

These define "did the launch work?" — not aspirational, just enough to
decide the next bet.

| Metric | Target |
|---|---|
| Uptime | ≥ 99.5% |
| First-draft generation success rate (no 5xx) | ≥ 98% |
| Median first-draft latency | ≤ 30 s |
| Eval harness pass rate per release | ≥ 95% |
| Critical security findings | 0 |
| Paying customers | ≥ 3 |
| First customer-reported regulation gap | resolved in ≤ 14 days |

---

**Next action:** close the §4.1 launch-blocking list, walk §6, sign §6.7.
