# CRP Comply — Launch Readiness Checklist

**Status:** Ready for launch candidate cutover.  
**Last updated:** 2026-06-21.

Use this checklist before tagging a release as launch-ready. Each section should
be signed off by the owner and linked to evidence (CI run, report, or ticket).

## 1. Engineering quality

| # | Item | Owner | Evidence | Status |
|---|------|-------|----------|--------|
| 1.1 | Full backend test suite passes (`pytest tests/`) | Engineering | CI / local run | ☐ |
| 1.2 | Eval suite passes ≥95% (`pytest tests/eval/`) | Engineering | CI eval job | ☐ |
| 1.3 | Ruff lint clean (`ruff check src tests`) | Engineering | CI lint job | ☐ |
| 1.4 | Bandit medium/high clean (`bandit -r src/crp_comply`) | Security | CI security job | ☐ |
| 1.5 | pip-audit tracked and documented | Security | CI security job / `Pipfile.lock` | ☐ |
| 1.6 | Frontend TypeScript compiles (`npx tsc --noEmit`) | Engineering | CI / local run | ☐ |
| 1.7 | Frontend build succeeds (`npm run build`) | Engineering | CI / local run | ☐ |
| 1.8 | Frontend tests pass (`npm test -- --run`) | Engineering | CI / local run | ☐ |
| 1.9 | Critical user flows manually smoke-tested | Engineering/QA | Smoke-test notes | ☐ |
| 1.10 | No `TODO` or `FIXME` blockers in release branch | Engineering | Grep report | ☐ |

## 2. Security & privacy

| # | Item | Owner | Evidence | Status |
|---|------|-------|----------|--------|
| 2.1 | `CRP_COMPLY_JWT_SECRET` set and persisted | Infrastructure | Env audit | ☐ |
| 2.2 | Clerk JWT audience and webhook secrets configured | Auth | Env audit | ☐ |
| 2.3 | Stripe webhook signing secret and price IDs set | Billing | Env audit | ☐ |
| 2.4 | BYOK keys encrypted at rest (AES-256-GCM) | Security | Code review / test | ☐ |
| 2.5 | Tenant isolation tests pass (`tests/test_batch10_tenant_isolation.py`) | Security | CI | ☐ |
| 2.6 | Security headers (HSTS, CSP, COOP, CORP, X-Frame-Options) enabled | Security | Config / header scan | ☐ |
| 2.7 | Privacy policy and DPA published and reviewed | Legal | `/privacy`, `/dpa` | ☐ |
| 2.8 | Subprocessor list published | Legal | `/subprocessors` | ☐ |
| 2.9 | "0 bytes leave your network" badge visible on landing/README | Marketing | README + Landing | ☐ |

## 3. Compliance model

| # | Item | Owner | Evidence | Status |
|---|------|-------|----------|--------|
| 3.1 | Continuous compliance engine initialised in API lifespan | Engineering | `src/crp_comply/api/app.py` | ☐ |
| 3.2 | Obligation lifecycle store initialised and persisted | Engineering | `src/crp_comply/programme/lifecycle.py` | ☐ |
| 3.3 | Gap reports render with remediation hints and blockers | Product | `/app/continuous` | ☐ |
| 3.4 | Remediation tickets can be created and listed | Product | API + dashboard | ☐ |
| 3.5 | Corpus-change staleness marks affected obligations | Engineering | Test / manual | ☐ |
| 3.6 | Eval suite covers EU AI Act, GDPR, ISO 42001, DPIA, technical docs, transparency | Engineering | `tests/eval/` | ☐ |

## 4. Infrastructure & operations

| # | Item | Owner | Evidence | Status |
|---|------|-------|----------|--------|
| 4.1 | Production environment linked and service healthy | Infrastructure | Railway dashboard | ☐ |
| 4.2 | Volume persistence configured and probed on startup | Infrastructure | `src/crp_comply/api/persistence_probe.py` | ☐ |
| 4.3 | Nightly backup job scheduled and tested | Infrastructure | `scripts/backup-nightly.sh` / restore drill | ☐ |
| 4.4 | RAG bootstrap completes successfully on fresh deploy | Engineering | Deploy logs | ☐ |
| 4.5 | Health endpoint returns `200 OK` with version info | Engineering | `/api/v1/health` | ☐ |
| 4.6 | Live-regulation CI scoped to `corpus/_scraped/**` | Engineering | `.github/workflows/live-regulation-ci.yml` | ☐ |
| 4.7 | Rate limiting active on public endpoints | Engineering | Config / test | ☐ |

## 5. Documentation & marketing

| # | Item | Owner | Evidence | Status |
|---|------|-------|----------|--------|
| 5.1 | README lead rewritten, no overclaims | Marketing | `README.md` | ☐ |
| 5.2 | Landing, Pricing, Product copy updated | Marketing | `frontend/src/pages/Landing.tsx`, `Pricing.tsx`, `Product.tsx` | ☐ |
| 5.3 | Marketing brief (`MARKETING.md`) free of "98% gross margin" / "managed LLM tokens" overclaims | Marketing | `MARKETING.md` | ☐ |
| 5.4 | Enterprise templates created (NDA, DPA, MSA, SOW) | Legal/CS | `enterprise/templates/` | ☐ |
| 5.5 | Local-LLM and BYOK guides current | Docs | `docs/LOCAL_LLM_GUIDE.md`, `docs/BYOK_MODES.md` | ☐ |
| 5.6 | Backup/restore drill documented | Ops | `docs/BACKUP_AND_RESTORE.md` | ☐ |
| 5.7 | AGENTS.md updated with any changed conventions | Engineering | `AGENTS.md` | ☐ |

## 6. Billing & monetisation

| # | Item | Owner | Evidence | Status |
|---|------|-------|----------|--------|
| 6.1 | Stripe price IDs configured for all paid tiers | Billing | Env / config | ☐ |
| 6.2 | Checkout session and portal session tested end-to-end | Billing | Staging test | ☐ |
| 6.3 | Tier-feature matrix tests pass | Billing | `tests/test_billing*.py` | ☐ |
| 6.4 | Quota visibility accurate in UI | Product | `/app/settings` | ☐ |
| 6.5 | Overage messaging and blocking logic tested | Billing | Tests / manual | ☐ |

## 7. Launch sign-off

| Role | Name | Signature / approval | Date |
|------|------|----------------------|------|
| Engineering lead | | | |
| Security / privacy | | | |
| Legal / compliance | | | |
| Product / marketing | | | |
| Infrastructure | | | |

## Release command

When the checklist is complete, cut the release:

```bash
git tag -a v$(python -c "import crp_comply; print(crp_comply.__version__)") -m "Launch candidate"
git push origin --tags
```

Then deploy via Railway and verify the production health endpoint.
