# Volume Persistence Runbook

**Status check:** `GET https://<your-service>/api/v1/health/detailed` returns
a `volume` block. Inspect it after every deploy until confidence is high.

## 1. How persistence works

CRP Comply writes **three categories of customer data** to `/app/data`:

| Path | Content |
|---|---|
| `/app/data/users.json`, `api_keys.json` | Auth (Clerk-issued users + API keys) |
| `/app/data/usage/` | Monthly quota counters |
| `/app/data/reports/{user_id}/` | Every generated report (JSON + optional Markdown) |
| `/app/data/evidence_packs/{user_id}/{pack_id}/` | Regulator-ready zips + manifests |
| `/app/data/provider_config.json` | Each user's encrypted LLM credentials |

**If `/app/data` is ephemeral, every deploy wipes all of this.** That is a
critical data-loss bug. The probe and this runbook exist to make the failure
mode impossible to miss.

## 2. Railway setup (one-time)

1. Railway dashboard → CRP Comply service → **Settings → Volumes**
2. **New Volume**
   - Name: `crp-comply-data`
   - Mount path: `/app/data`
   - Size: 1 GB minimum, 10 GB recommended
3. Save. Railway will redeploy.

## 3. Verify persistence is live

### 3a. First deploy after volume attach

Logs should contain:

```
volume probe: first-boot at ... (data_dir=/app/data)
```

This is **expected on the very first boot after volume attach**, because the
marker file doesn't exist yet.

### 3b. Trigger a redeploy (any push, or "Redeploy" button)

Logs should now contain:

```
volume probe: PERSISTENT OK — last boot ..., total boots seen=2
```

If instead you see `first-boot` again, **the volume is NOT mounted**. Stop
accepting paid users until this is fixed.

### 3c. Inspect `/api/v1/health/detailed`

```json
{
  "alive": true,
  "ready": true,
  "volume": {
    "probed": true,
    "data_dir": "/app/data",
    "writable": true,
    "first_boot": false,
    "persistent": true,
    "previous_boot_id": "a1b2...",
    "previous_boot_at": "2026-04-22T18:32:11+00:00",
    "current_boot_id": "c3d4...",
    "current_boot_at": "2026-04-23T09:05:02+00:00",
    "previous_boots_seen": 7
  }
}
```

- `persistent: true` → volume survived the last redeploy. ✅
- `persistent: null` → first boot since volume attach. Redeploy once to confirm.
- `persistent: false` or `first_boot: true` when `previous_boots_seen` = 0 and
  you know you've redeployed → **the volume is ephemeral. Fix now.**

## 4. Required environment variables

Set in Railway **Variables** tab:

| Name | Purpose | Example |
|---|---|---|
| `CRP_COMPLY_JWT_SECRET` | JWT signing + evidence-pack HMAC | `openssl rand -hex 32` |
| `CRP_COMPLY_DATA_DIR` | Where to write | `/app/data` |
| `CLERK_SECRET_KEY` | Clerk backend | `<YOUR_CLERK_SECRET_KEY>` |
| `VITE_CLERK_PUBLISHABLE_KEY` | Clerk frontend (build arg) | `<YOUR_CLERK_PUBLISHABLE_KEY>` |
| `STRIPE_SECRET_KEY` | Stripe | `<YOUR_STRIPE_SECRET_KEY>` |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhooks | `<YOUR_STRIPE_WEBHOOK_SECRET>` |

Optional retention knobs (defaults are sensible):

```
CRP_COMPLY_REPORT_RETENTION_DAYS=180
CRP_COMPLY_EVIDENCE_RETENTION_DAYS=365
CRP_COMPLY_RETENTION_INTERVAL_SECONDS=86400
CRP_COMPLY_RETENTION_ENABLED=true
```

## 5. Backup strategy

Railway volumes live in a single AZ (yours is US-West California). For paid
customers you **must** have off-site backups. Pick one:

### 5a. Manual on-demand snapshot (any time, from your laptop)

```bash
# one-liner: stream a tar of the volume over SSH out of a Railway shell
railway run --service crp-comply -- \
  tar czf - -C /app data | gpg -c > crp-$(date +%F).tgz.gpg
```

Store the `.tgz.gpg` in S3 / Backblaze B2 / Cloudflare R2 / your offline drive.

### 5b. Nightly automated backup (recommended for production)

Add a second Railway service (or cron) that mounts the **same** volume
read-only and pushes a tarball to object storage:

```bash
# runs 03:00 UTC daily
0 3 * * * tar czf - -C /app data \
  | openssl enc -aes-256-cbc -salt -pbkdf2 -pass env:BACKUP_PASSPHRASE \
  | aws s3 cp - s3://my-crp-backups/crp-$(date +%F).tgz.enc \
  --storage-class STANDARD_IA
```

Set a lifecycle rule on the bucket: **Standard-IA for 30 days → Glacier for
1 year → delete**. Keep 35+ daily + 12+ monthly rotations.

### 5c. What the backup actually contains

```
/app/data/
  users.json              # Clerk user → tier mapping
  api_keys.json           # API key → user (hashed)
  usage/                  # monthly quota counters
  reports/{user}/         # every generated report
  evidence_packs/{user}/  # zip + manifest + HMAC sig
  provider_config.json    # per-user encrypted LLM creds
  .crp_volume_marker.json # boot history (not customer data)
```

This is **100% of customer-facing state**. Back this up and you can rebuild
from a blank Railway project.

## 6. Restore procedure (tested end-to-end)

**Scenario:** the Railway volume is corrupted / wiped / the whole region goes
down and you need to restore on a fresh service.

1. **Deploy the service without customer traffic.** Either point Cloudflare
   to a maintenance page or keep the new service behind a private URL.
2. **Attach a fresh volume** at `/app/data` (Settings → Volumes → New).
3. **SSH into the Railway shell:**
   ```bash
   railway shell --service crp-comply
   ```
4. **Stream the backup back in** (adapt to your storage):
   ```bash
   aws s3 cp s3://my-crp-backups/crp-2026-04-22.tgz.enc - \
     | openssl enc -d -aes-256-cbc -pbkdf2 -pass env:BACKUP_PASSPHRASE \
     | tar xzf - -C /app
   ```
5. **Fix ownership** (the entrypoint also does this, but belt-and-braces):
   ```bash
   chown -R app:app /app/data
   ```
6. **Redeploy** (so the probe captures a new boot marker).
7. **Verify:**
   ```bash
   curl https://<new-service>/api/v1/health/detailed \
     | jq '.volume.persistent, .volume.previous_boots_seen'
   ```
   Should return `true` and a number > 0.
8. **Spot-check one customer's reports:**
   ```bash
   curl -H "Authorization: Bearer crp_..." \
     https://<new-service>/api/v1/reports | jq '.reports | length'
   ```
   Non-zero → restore is good.
9. **Point DNS back.** Announce the RTO to affected customers if SLA applies.

**Test this procedure BEFORE you have paying customers.** Set a calendar
reminder to re-test every 90 days.

## 7. Data control — what your customers can do (GDPR Art. 15–22)

Every customer has these endpoints out of the box. All are tier-unrestricted
because they are legal rights, not features:

| Right | Endpoint | SDK method |
|---|---|---|
| Access (Art. 15) | `GET /api/v1/reports` + `/evidence-packs` + `/me` + `/usage` | `client.list_reports()`, `client.list_evidence_packs()`, `client.me()`, `client.usage()` |
| Portability (Art. 20) | `GET /api/v1/reports/{id}` (JSON) + `/evidence-packs/{id}/download` (zip) | `client.get_report()`, `client.download_evidence_pack()` |
| Erasure (Art. 17) | `DELETE /api/v1/reports/{id}` + `DELETE /api/v1/evidence-packs/{id}` | `client.delete_report()`, `client.delete_evidence_pack()` |

**Account-level erasure:** today a customer emails support and you delete
their `reports/{user_id}/` and `evidence_packs/{user_id}/` directories plus
their row in `users.json` / `api_keys.json`. This is on the backlog to become
a self-service `DELETE /me` endpoint before GA.

**Retention:** the background sweeper deletes reports older than
`CRP_COMPLY_REPORT_RETENTION_DAYS` (180) and evidence packs older than
`CRP_COMPLY_EVIDENCE_RETENTION_DAYS` (365). Adjust per your DPA commitments.

## 8. Testing guide — prove persistence before you take money

Run this checklist once, end-to-end, against your live Railway service:

1. **Redeploy test:**
   - Hit `/api/v1/health/detailed`, note `current_boot_id`.
   - Railway → Redeploy.
   - Hit `/api/v1/health/detailed` again. Expect `previous_boot_id` ==
     your noted value, `persistent: true`, `previous_boots_seen >= 1`.
2. **Report persistence test:**
   - Authenticate, `POST /api/v1/compliance-report` (use the SDK).
   - Note the returned `report_id`.
   - Redeploy.
   - `GET /api/v1/reports/{report_id}` — must return 200 with the same body.
3. **Evidence pack persistence test:**
   - `POST /api/v1/evidence-pack`, note `pack_id`.
   - Redeploy.
   - `GET /api/v1/evidence-packs/{pack_id}/download` — zip bytes must match
     (sha256 before/after).
4. **Backup round-trip test:**
   - Take a backup per §5a.
   - Spin up a **second** Railway service + volume, restore per §6.
   - Re-run steps 2 and 3 against the new service — every ID must resolve.
5. **Erasure test:**
   - `DELETE /api/v1/reports/{id}` — expect 204.
   - `GET /api/v1/reports/{id}` — expect 404.
   - Redeploy — `GET` must still 404 (deletion must persist too).
6. **Quota persistence test:**
   - Generate a few reports, note `GET /usage` counter.
   - Redeploy.
   - `GET /usage` — counter must be unchanged.

If **any** of steps 1–6 fail, do not accept paid signups until resolved.

## 9. If the probe warns

| Log line | Meaning | Action |
|---|---|---|
| `data_dir could not be created` | The mount path isn't writable from the container user | Check `docker-entrypoint.sh` chown and the volume mount path |
| `data_dir not writable` | Permissions broken after mount | Restart the service; entrypoint will re-chown |
| `first-boot` on every redeploy | Volume not mounted | Attach the volume in Railway dashboard |
