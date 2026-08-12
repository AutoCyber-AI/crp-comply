# USER ACTIONS REQUIRED

> **Audience:** the platform operator (you).
> **Purpose:** a step-by-step guide tied to the **current state** of your
> Stripe account, Railway deployment, and Clerk tenant. Every item the
> agent **could not** do for you is listed below.
>
> Last refreshed: April 2026 — backups + DR + Stripe-tier alignment pass.

---

## 0 · TL;DR — what shipped, what's left

The agent has now wired:

* **Backups (paid feature, gated by `managed_backups` entitlement)** — three
  separate backup paths now exist:
  1. `GET /api/v1/me/export` — **GDPR Art. 20** download (always free, all tiers).
  2. `POST /api/v1/me/backups` — **managed snapshot** kept on the platform's
     volume, listable / re-downloadable / deletable. Paid only.
  3. `python -m crp_comply backup-all <dest>` — **operator-side full DR
     archive** consumed by the nightly cron + off-site shipper.
* **Stripe alignment**: STARTER tier now exists in the backend, the
  metered overage env var is now read as `STRIPE_METER_EVENT_NAME`
  (matches your existing `comply_proxy_requests` meter), and the
  `customer.subscription.trial_will_end` webhook handler has been
  **removed** since you don't run trials.
* **Tier matrix** has the `managed_backups` flag on STARTER / PRO /
  ENTERPRISE / CLOUD; FREE is excluded.

What's left is dashboard-side work in **Stripe**, **Railway**, **Clerk**,
plus copy/paste of a few env vars. All of it is documented below.

---

## 1 · Stripe — exactly what to do, given your current state

### 1.1 Prices: keep three new, archive three old

You currently have these prices on the **CRP Comply** product:

| Created | Amount     | Description / lookup-key suggestion          | Action      |
| ------- | ---------- | -------------------------------------------- | ----------- |
| Apr 26  | **$49.00** | starter / `comply_starter`                   | **KEEP**    |
| Apr 26  | $199.00    | professional / `comply_professional`         | **KEEP**    |
| Apr 26  | $599.00    | enterprise / `comply_enterprise`             | **KEEP**    |
| Apr 15  | $0.50 / 1K | overage meter (`comply_proxy_requests`)      | **KEEP**    |
| Apr 15  | $149.00    | "Comply Pro" (legacy)                        | **ARCHIVE** |
| Apr 15  | $699.00    | "Comply Enterprise" (legacy)                 | **ARCHIVE** |
| Apr 15  | $1,999.00  | "Comply Cloud" (legacy)                      | **ARCHIVE** |

> **Don't *delete* the legacy prices** — Stripe forbids deleting any
> price that has ever been on a subscription. Use **Archive** instead
> (Stripe Dashboard → product → price → ⋮ → Archive). Archived prices
> stay on existing subscriptions but disappear from new checkout flows.

After archiving, copy the **Price IDs** of the three new ones into
Railway env vars (see §1.4).

### 1.2 Webhook events — your current set is exactly right

Your current webhook subscriptions:

```
checkout.session.completed
customer.subscription.deleted
customer.subscription.updated
invoice.paid
invoice.payment_action_required
invoice.payment_failed
```

✅ This is the complete set the backend now handles. The earlier draft
asked for `customer.subscription.trial_will_end` — that has been
**removed from both the backend and the docs** because the platform
doesn't offer trials. Don't add that event in Stripe.

### 1.3 The "Cloud" / "Enterprise" / "FREE" tier explained

| Internal tier | UI label             | Implementation                                                                                            |
| ------------- | -------------------- | --------------------------------------------------------------------------------------------------------- |
| `free`        | Free                 | No Stripe checkout. Default tier for any new user. Quota-capped. Hard-blocked from paid features.         |
| `starter`     | Starter ($49)        | Stripe price `$49`. Single-seat. 5K calls/mo. SOFT_ALLOW overage (metered).                               |
| `pro`         | Professional ($199)  | Stripe price `$199`. Up-to-5 seats. 50K calls/mo. SOFT_ALLOW overage.                                     |
| `enterprise`  | Business ($599)      | Stripe price `$599`. 25 seats. 250K calls/mo. SOFT_ALLOW overage. Adds `multi_user`, `custom_frameworks`. |
| `cloud`       | Enterprise (contact) | **No public Stripe price**. Activated by hand from the operator console / SDK after a sales conversation. |

So **"FREE" needs no Stripe object at all** — it's the default. **"Cloud"
also needs no public price** because the contact-sales tile does not put
the user through Stripe Checkout. If you later want to bill Cloud
through Stripe, create a custom price + invoice for that one customer
inside the Stripe Dashboard; nothing in the code changes.

### 1.4 Final env-var set for Railway

Below is the **complete** list of env vars the production app reads.
Compare against your current Railway env (you posted it as having 12
vars — three need to be removed/renamed, three new ones added).

| Var                                  | Status     | Value to set                                                                              |
| ------------------------------------ | ---------- | ----------------------------------------------------------------------------------------- |
| `CLERK_ISSUER`                       | KEEP       | as-is                                                                                     |
| `CLERK_SECRET_KEY`                   | KEEP       | as-is                                                                                     |
| `VITE_CLERK_PUBLISHABLE_KEY`         | KEEP       | as-is                                                                                     |
| `CRP_COMPLY_BASE_URL`                | KEEP       | as-is, must start with `https://`                                                         |
| `CRP_COMPLY_CORS_ORIGINS`            | KEEP       | as-is                                                                                     |
| `CRP_COMPLY_DATA_DIR`                | KEEP       | `/app/data`                                                                               |
| `CRP_COMPLY_JWT_SECRET`              | KEEP       | rotate to `openssl rand -hex 64` if it has ever been committed                            |
| `STRIPE_SECRET_KEY`                  | KEEP       | `<YOUR_STRIPE_SECRET_KEY>`                                                                               |
| `STRIPE_WEBHOOK_SECRET`              | KEEP       | `<YOUR_STRIPE_WEBHOOK_SECRET>`                                                                                 |
| **`STRIPE_COMPLY_STARTER_PRICE_ID`** | **ADD**    | price ID of the **$49** price                                                             |
| `STRIPE_COMPLY_PRO_PRICE_ID`         | UPDATE     | price ID of the **$199** price (currently points at the legacy $149 — replace it)         |
| `STRIPE_COMPLY_ENTERPRISE_PRICE_ID`  | UPDATE     | price ID of the **$599** price (currently points at the legacy $699 — replace it)         |
| `STRIPE_COMPLY_CLOUD_PRICE_ID`       | **REMOVE** | not needed; Cloud is contact-sales only. Delete the env var to avoid confusion.           |
| **`STRIPE_METER_EVENT_NAME`**        | **ADD**    | `comply_proxy_requests` (matches your existing meter; backend reports overage to it)      |

After saving, Railway redeploys automatically. Confirm with:

```bash
curl -H "Authorization: Bearer <your-jwt>" \
  https://<your-host>/api/v1/billing/status
```

You should see `{"tier": "...", "current_period_end": "..."}` once a
test subscription has been completed.

### 1.5 Quotas, seats, and how requests are counted

**Quotas** are enforced in [src/crp_comply/api/usage.py](src/crp_comply/api/usage.py):

```python
TIER_MONTHLY_QUOTA = {
    Tier.FREE: 100,
    Tier.STARTER: 5_000,
    Tier.PRO: 50_000,
    Tier.ENTERPRISE: 250_000,
    Tier.CLOUD: 1_000_000,
}
OVERAGE_POLICY = {
    Tier.FREE: "HARD_BLOCK",       # 402 once cap is hit
    Tier.STARTER: "SOFT_ALLOW",    # billed via meter
    Tier.PRO: "SOFT_ALLOW",        # billed via meter
    Tier.ENTERPRISE: "SOFT_ALLOW", # billed via meter
    Tier.CLOUD: "SOFT_ALLOW",      # bespoke contract
}
```

Every authenticated POST that ends up calling an LLM or returning a
report goes through `Depends(meter_call("<endpoint>"))`. After tallying,
**overage** calls (anything beyond the included quota) are emitted to
your Stripe Meter as `comply_proxy_requests` events. The meter then
multiplies × $0.50 / 1,000 on the customer's next invoice.

**Seats** are tracked per Clerk **organization**. The `multi_user`
feature flag (PRO and above) lets a Clerk org admin invite teammates.
The platform doesn't cap the seat count itself — that's a soft limit
documented in `Pricing.tsx`. If you want a hard cap, add it to
`AuthManager.upsert_oauth_user` in [src/crp_comply/api/auth.py](src/crp_comply/api/auth.py)
by counting members of the same `tenant_id` and refusing if the count
exceeds the tier's cap. (Open question worth deferring; today it's a
trust + customer-success problem, not a billing one.)

### 1.6 Terms of Service + Privacy Policy URLs

Stripe Checkout requires both URLs to be reachable. Until you publish
your own pages, the cheapest legitimate fix is:

1. Use a generator (e.g. iubenda, GetTerms.io, Termly free tier) to draft
   the two policies tailored to your jurisdiction (Australia + EU).
2. Host them on the marketing site (e.g. `https://crprotocol.io/legal/tos`
   and `/legal/privacy`).
3. Paste both URLs into **Stripe Dashboard → Settings → Public details →
   Terms of service / Privacy policy**.

The Privacy Policy MUST mention:

* `DELETE /api/v1/me` is the user's GDPR Art. 17 self-service.
* `GET  /api/v1/me/export` is the user's GDPR Art. 20 self-service.
* All data is stored on Railway in the EU (or the region you've
  selected) and encrypted at rest via the BYOK key.

---

## 2 · Backups & Disaster Recovery

### 2.1 The three independent backup planes

| Plane          | What                            | Who triggers it          | Lives where                                                |
| -------------- | ------------------------------- | ------------------------ | ---------------------------------------------------------- |
| **User Art.20** | per-user tarball                | end-user                 | streamed once, not retained                                |
| **Managed**    | per-user retained snapshot      | end-user (paid)          | `/app/data/managed_backups/<user>/snapshot-*.tar.gz`       |
| **Operator DR** | full-platform tarball           | **in-process scheduler** | `/app/data/backups/`, then shipped off-site (R2 / S3 / B2) |

Each plane is independent — losing one doesn't lose the others. If the
Railway volume is wiped, planes 1 and 2 die with it; plane 3 is the only
one that survives because it ships to a different cloud.

### 2.2 Off-site shipment via Cloudflare R2 (recommended)

> **🛑 IMPORTANT — architectural change (April 2026):** the nightly
> backup now runs **inside the API service** as an asyncio task. There
> is **no separate Railway cron service** any more. Railway volumes are
> isolated per-service: a sibling service attaching `/app/data` would
> get a brand-new empty volume, not a view of the API service's data.
> If you previously created a `crp-comply-backup` cron service per the
> old instructions in this section, **delete it** — it cannot see your
> data and is silently producing empty archives.

Cloudflare R2 is the cheapest credible target — egress is free and
storage is $0.015 / GB-month. Setup once:

1. **Cloudflare account** → R2 → Create bucket `crp-comply-backups`.
   Pick the region closest to your Railway region.
2. **R2 API tokens** → Create token → "Object read & write" permission
   scoped to that bucket → write down `Access Key ID` and `Secret
   Access Key`.
3. **Account R2 endpoint** appears as
   `https://<accountid>.r2.cloudflarestorage.com` on the bucket page.
4. **Railway → your API service → Variables**, add:

   ```
   BACKUP_R2_ENDPOINT=https://<accountid>.r2.cloudflarestorage.com
   BACKUP_R2_BUCKET=crp-comply-backups
   AWS_ACCESS_KEY_ID=<from step 2>
   AWS_SECRET_ACCESS_KEY=<from step 2>
   AWS_DEFAULT_REGION=auto
   BACKUP_RETENTION_DAYS=60
   ```

   (R2 uses the AWS S3 protocol, hence the `AWS_*` env vars.)

   > 🔒 **Do NOT commit these values to the repo.** They live in the
   > Railway dashboard only — committing AWS-style credentials is an
   > OWASP A02:2021 secrets-leak. The application reads them at run
   > time via `os.environ`.

5. **Verify the volume.** On the API service → **Settings** →
   **Volumes**, confirm `crp-comply-data` is attached at `/app/data`.
   That's all — no second service needed. The next time the API
   container starts, the in-process scheduler arms itself for
   `BACKUP_SCHEDULE_HOUR_UTC` (default `03:00 UTC`).

6. **Delete any old cron service.** If you (or earlier instructions in
   this document) created a separate Railway service named
   `crp-comply-backup` with start command `crp-comply backup-nightly`
   on a cron schedule, delete that service entirely. It is now
   redundant and, due to volume isolation, was never able to read your
   live data anyway.

7. **Verify** after 24 h, from your laptop:

   ```bash
   pip install boto3
   python - <<'PY'
   import os, boto3
   s3 = boto3.client("s3", endpoint_url=os.environ["BACKUP_R2_ENDPOINT"])
   for obj in s3.list_objects_v2(Bucket=os.environ["BACKUP_R2_BUCKET"]).get("Contents", []):
       print(obj["Key"], obj["Size"], obj["LastModified"])
   PY
   ```

   You should see one `crp-comply-YYYYMMDDTHHMMSSZ.tar.gz` entry per
   day. The archive is also browseable on the live volume at
   `/app/data/backups/`.

8. **Manual / ad-hoc run** (optional). The same code path is exposed as
   the Click subcommand `crp-comply backup-nightly` for ops debugging,
   e.g. `railway run crp-comply backup-nightly` from your laptop or
   `docker exec <container> crp-comply backup-nightly`. Implementation:
   [src/crp_comply/backup_scheduler.py](src/crp_comply/backup_scheduler.py).

9. **Tunables** (all optional, env vars on the API service):

   * `BACKUP_SCHEDULE_HOUR_UTC` — change the run hour (default `3`).
   * `CRP_COMPLY_BACKUP_INPROCESS=0` — disable the scheduler entirely
     (e.g. if you ship backups some other way).
   * `BACKUP_S3_BUCKET` — alternative AWS S3 target (used if R2 vars
     are unset).

> **R2 free-tier sanity check**: 60-day retention × ~50 MB nightly ≈
> 3 GB → comfortably inside the 10 GB Cloudflare R2 free tier. If your
> nightly archive grows past ~150 MB, lower `BACKUP_RETENTION_DAYS` or
> upgrade R2.

### 2.3 Restore drill (do this once before opening signups)

```bash
# 1. Download a known-good archive locally
aws s3 cp s3://crp-comply-backups/crp-comply-backup-20260427T030000.tar.gz . \
  --endpoint-url=https://<accountid>.r2.cloudflarestorage.com

# 2. Spin up a throwaway Railway env (or local docker)
docker compose up -d --build crp-comply

# 3. Inside the container:
docker compose exec crp-comply python -m crp_comply restore \
  /app/crp-comply-backup-20260427T030000.tar.gz --overwrite --yes

# 4. Smoke test:
curl https://staging-host/api/v1/health
```

Record the elapsed time. That's your **RTO**. Add it to the runbook.

### 2.4 What happens if Railway loses the volume entirely?

1. Provision a fresh Railway service.
2. Mount a fresh 10 GB volume at `/app/data`.
3. Set the same env vars from §1.4.
4. SSH / `railway run`:
   ```bash
   aws s3 cp s3://crp-comply-backups/<latest>.tar.gz /app/restore.tar.gz \
     --endpoint-url=$BACKUP_R2_ENDPOINT
   python -m crp_comply restore /app/restore.tar.gz --overwrite --yes
   ```
5. Re-deploy. Users sign back in via Clerk; their CKF, reports,
   evidence packs, and managed backups are all back.

---

## 3 · Clerk MFA — programmatic enforcement (free-tier workaround)

Clerk's dashboard MFA toggle is locked out on the free plan, so you
enforce it from the React frontend instead. The Clerk team's pattern is
documented at <https://clerk.com/docs/nextjs/reference/components/authentication/task-setup-mfa>.
The same approach works in the Vite / React-Router app you already have:

1. Enable at least one MFA strategy in Clerk:
   `Authentication → Multi-factor` → tick **TOTP (Authenticator app)**
   and **Backup codes**. (These are free-plan features even though
   *enforcement* is paid.)
2. In the frontend, after sign-in, check the user's MFA enrolment
   status via the Clerk SDK and redirect them to a setup screen if
   missing. Add this to `frontend/src/components/RequireAuth.tsx`:

   ```tsx
   import { useUser } from "@clerk/clerk-react";

   export function RequireMfa({ children }: { children: React.ReactNode }) {
     const { user, isLoaded } = useUser();
     if (!isLoaded) return null;
     const hasMfa =
       user?.totpEnabled || (user?.backupCodeEnabled ?? false);
     if (!hasMfa) {
       return <Navigate to="/account/mfa-setup" replace />;
     }
     return <>{children}</>;
   }
   ```

3. Render `<MfaSetup />` (use Clerk's `<UserProfile />` component which
   exposes the TOTP enrollment flow) at `/account/mfa-setup`.
4. Wrap any sensitive admin route with `<RequireMfa>`.

This delivers the same outcome as the paid Clerk MFA toggle — every
user is forced through enrolment before reaching the app — without
upgrading Clerk.

> When you eventually outgrow Clerk free tier, flip the dashboard
> toggle and remove `<RequireMfa>`; both flows are compatible.

---

## 4 · Pre-launch verification checklist

Tick these in order. Each line maps to one concrete observable.

```
Code / repo
[ ] git pull && python -m pytest -q   →  450 passed
[ ] cd frontend && npm run build       →  no errors
[ ] grep -r STRIPE_COMPLY_CLOUD_PRICE_ID src/  →  no matches (removed)

Stripe Dashboard
[ ] $49 / $199 / $599 prices kept; $149 / $699 / $1999 archived
[ ] Webhook subscribed to the 6 events listed in §1.2 (no trial event)
[ ] Meter "comply_proxy_requests" exists; $0.50 / 1K price linked
[ ] Settings → Public details has ToS + Privacy URLs

Railway
[ ] Volume mounted at /app/data, ≥ 10 GB
[ ] Env vars match §1.4 exactly (3 added/updated, 1 removed, 1 renamed)
[ ] Cron job "0 3 * * *  crp-comply backup-nightly" enabled
[ ] R2 bucket receives a tarball after the next 03:00 UTC tick
[ ] curl https://<host>/api/v1/health  →  200

Clerk
[ ] TOTP + Backup codes enabled in Clerk dashboard
[ ] frontend/RequireMfa wraps every authenticated route
[ ] Test signup → forced through MFA setup → can reach /app

Backups & DR
[ ] GET /api/v1/me/export returns a tar.gz with MANIFEST.json
[ ] POST /api/v1/me/backups (paid user) returns a snapshot id
[ ] DELETE /api/v1/me removes everything in staging
[ ] Restore drill performed; RTO recorded in runbook

Security hygiene
[ ] CRP_COMPLY_JWT_SECRET rotated post-merge
[ ] PyPI token for crp-comply-sdk rotated and stored in GitHub secrets
[ ] HSTS header observed: curl -I https://<host>/
```

When all are ticked, you're cleared to open public signups.

---

## 5 · Things still on the backlog (deliberately deferred)

These are tracked in `PRODUCTION_READINESS.md` §4.3 / §B and are not
blocking launch:

* Wire `api/model_router` into the orchestrator's per-turn dispatch.
* Frontend banner subscribed to `billing_action_required` notifications.
* Frontend plan badge calling `GET /billing/status`.
* Programme.tsx rendering all 8 lifecycle states.
* Eval suite expansion 13 → 20 cases.
* Tier-feature-matrix fuzz test.
* Append-only audit log for mutating endpoints.

You can ship without them. They're scheduled for the first month after
launch.
