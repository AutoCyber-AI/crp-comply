# Backup & Restore Architecture

> **Status:** production · **Last revised:** 2026‑05‑01
> **Code:** [backup.py](../src/crp_comply/backup.py) · [backup_scheduler.py](../src/crp_comply/backup_scheduler.py) · [backup_encryption.py](../src/crp_comply/backup_encryption.py)
> **CLI:** `crp-comply backup-nightly` · `crp-comply restore <path>` · `crp-comply restore-user <path> --user <id>`

This document is the single source of truth for how `crp‑comply`
protects customer data against accidental loss, host failure, region
outage, cloud‑provider compromise, **and the operator themselves**.
It documents *what* is captured, *where* it goes, *how* it is
encrypted, *how* it is recovered (whole-volume **or** single‑user),
and which security surfaces are **explicitly** in or out of scope.

---

## 1. Design principles

1. **Two restore granularities.** A nightly tarball gives whole-volume
   disaster recovery. A `restore_user(archive, user_id)` path gives
   single-user rollback without touching anyone else's data — needed
   for accidental account deletion, regulator-ordered data correction,
   or migrating one tenant into a fresh deployment.
2. **Run inside the API process.** Railway volumes are not shared
   between services, so a separate cron service cannot read them. The
   scheduler is an `asyncio` task started during FastAPI lifespan
   ([`backup_scheduler.scheduler_loop`](../src/crp_comply/backup_scheduler.py)).
   The same `run_backup_once()` helper backs the
   `crp-comply backup-nightly` CLI so there is one code path.
3. **Defence in depth on egress.** R2 / S3 already encrypt at rest,
   but those keys are *provider‑managed*. We add a **client‑side
   AES‑256‑GCM** layer keyed by an environment variable the cloud
   provider never sees. Stolen R2 credentials or a misconfigured
   public ACL leak only ciphertext.
4. **Fail loud, fail safe.** When `BACKUP_ENCRYPTION_KEY` is configured
   but encryption fails, the backup is left local‑only and never
   uploaded — preferable to silently shipping plaintext.
5. **Never trust an archive.** Every member is validated against
   path traversal, absolute paths, symlink/hardlink/device entries,
   and oversized payloads before any byte hits the volume.

---

## 2. What goes into the tarball

`backup_all()` walks `${CRP_COMPLY_DATA_DIR}` recursively and writes
a gzip‑compressed tar with `arcname` set to the relative path. Two
top‑level prefixes are *excluded* to avoid recursion / duplication:

| Prefix         | Why excluded                                       |
| -------------- | -------------------------------------------------- |
| `backups/`     | Where prior tarballs live; would compound nightly  |
| `exports/`     | Per‑user Art. 15/20 exports; ephemeral by definition |

### 2.1 Per‑user content captured

| Path inside archive (relative)   | Content                                              | Format |
| -------------------------------- | ---------------------------------------------------- | ------ |
| `reports/{user_id}/`             | Generated artefacts, gap reports, draft exhibits     | JSON   |
| `evidence_packs/{user_id}/`      | Hashed evidence bundles, control‑linkage manifests   | JSON   |
| `ckf/{user_id}/`                 | Contextual Knowledge Fabric facts + edges            | JSON / SQLite |
| `programme/{user_id}/`           | Multi‑year programme state, milestones, budgets      | JSON   |
| `telemetry/{user_id}/`           | Per‑user CRP envelope metrics, latency histograms    | JSONL  |
| `artefacts/{user_id}/`           | Stitched continuation drafts, derivations            | JSON   |
| `agent_sessions/{user_id}/`      | Multi‑turn agent transcripts (encrypted at rest)     | JSON   |
| `retention/{user_id}/`           | Retention policy decisions + scheduled deletions     | JSON   |
| `derivation/{user_id}/`          | CRP derivation manifests linking source → output     | JSON   |

### 2.2 Tenant‑scoped content captured

| Path                              | Content                                          |
| --------------------------------- | ------------------------------------------------ |
| `contacts/{tenant_id}.json`       | DPO / contact roster, regulatory notices         |
| `org_profiles/{tenant_id}.json`   | Recipe inputs, business profile, residency       |
| `audit_chain/{tenant_id}/`        | Hash‑chained audit log per tenant                |

### 2.3 Global / cross‑tenant content captured

| Path                       | Content                                                |
| -------------------------- | ------------------------------------------------------ |
| `users.json`               | Account directory (passwords are bcrypt‑hashed)        |
| `api_keys.json`            | Tenant API tokens (encrypted via `StateEncryptor`)     |
| `usage.json`               | Daily quota counters per tier                          |
| `provider_config.json`     | Per‑user BYOK LLM endpoints (KEK‑wrapped)              |
| `storage_prefs.json`       | Per‑tenant storage / residency preferences             |
| `rag_index/`               | Re‑computable; included for cold‑start operability     |
| `crp_artefacts.sqlite`     | CRP bundle index                                       |

> **Note on RAG index.** The RAG index is regenerable from the corpus
> but is included to make a cold disaster recovery operational
> immediately. After a restore you may optionally run
> `crp-comply ingest --rebuild` to refresh it.

### 2.4 What is NOT in the tarball

* `corpus/` — public regulatory PDFs and JSON; lives in the git repo
  and is shipped with each container build.
* `frontend/dist/` — static build artefacts.
* In‑memory state: rate‑limit windows, in‑flight jobs.
* Process secrets — environment variables (KEKs, JWT secret, Stripe
  keys) live in the platform secret manager (Railway environment),
  *not* on the volume, so they are *not* backed up. Restoring without
  the original `BACKUP_ENCRYPTION_KEY` and `CRP_COMPLY_KEK_CHAIN`
  yields ciphertext you cannot decrypt — keep these in a secrets
  vault separate from the backup target.

---

## 3. Encryption layer (AES‑256‑GCM, client‑side)

### 3.1 File format

When `BACKUP_ENCRYPTION_KEY` (or `BACKUP_ENCRYPTION_PASSPHRASE`) is
set, `run_backup_once()` runs the gzipped tarball through
`backup_encryption.encrypt_file()` before any boto3 upload. The
output filename gets a `.enc` suffix.

```
magic(8)            = b"CRPENC01"
header_len(4)       = uint32 BE
header_json(N)      = {
    "alg": "AES-256-GCM",
    "chunk_size": 4194304,
    "key_id": "<first 12 hex of SHA-256(KEK)>",
    "created_at": "<RFC 3339 UTC>",
    "source": "crp-comply-backup",
    "version": 1
}
[ nonce(12) || ct_len(4) || ciphertext+tag(...) ] *
final_marker(8)     = b"CRPEND01"
```

* **Streaming** — 4 MiB chunks; multi‑GB archives never fully load
  into memory.
* **Fresh nonce per chunk** — `os.urandom(12)`. No nonce reuse risk
  even across thousands of backups.
* **AAD per chunk** — chunk index packed as `>Q` is bound into AEAD
  so re‑ordering or truncation is detectable.
* **Authentication** — every chunk has its own GCM tag; partial
  decryption is impossible.

### 3.2 Key management

```bash
# Production: a 32-byte random key in base64 or hex
export BACKUP_ENCRYPTION_KEY="$(python -c 'import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())')"

# Lower-strength alternative (passphrase hashed to 32 bytes)
export BACKUP_ENCRYPTION_PASSPHRASE="correct horse battery staple..."
```

**Storage:** the KEK lives in a secret manager *separate* from the R2
account (e.g. Bitwarden, 1Password, AWS Secrets Manager, HashiCorp
Vault). If R2 and the KEK share the same blast radius, you have
gained nothing.

**Rotation:** drop in a new `BACKUP_ENCRYPTION_KEY`. Old archives
remain decryptable so long as you keep prior keys available — the
file header records `key_id` (12 hex chars of SHA‑256) so restore
tooling can pick the right KEK.

---

## 4. Threat model — explicit security surfaces

This section enumerates **every** surface we have considered, marked
with the mitigation in place. Items marked ❌ are accepted residual
risk; the operator playbook compensates.

### 4.1 Confidentiality (data at rest, in transit, in third‑party hands)

| # | Threat                                                    | Mitigated? | Mechanism                                              |
| - | --------------------------------------------------------- | :--------: | ------------------------------------------------------ |
| 1 | Public‑bucket misconfiguration on R2/S3                   | ✅         | Ciphertext only; `BACKUP_ENCRYPTION_KEY` required      |
| 2 | Stolen R2 / S3 access key                                 | ✅         | Ciphertext only                                        |
| 3 | Cloudflare/AWS insider with bucket access                 | ✅         | Ciphertext only                                        |
| 4 | Network interception in transit                           | ✅         | TLS + ciphertext (defence in depth)                    |
| 5 | Plaintext archive left on local volume                    | ✅         | `run_backup_once()` `unlinks` plaintext after encrypt |
| 6 | Encryption fails silently → plaintext shipped             | ✅         | Fail‑safe: never uploads when KEK set + encrypt errors |
| 7 | Quantum future attacker recording today's ciphertext      | ❌ accept  | AES‑256 ≈ 128‑bit post‑quantum; revisit ML‑KEM in 2030 |
| 8 | Compromise of API host *while running*                    | ❌ accept  | KEK in process memory; mitigated by short host TTL     |
| 9 | Joint compromise of secret manager + bucket               | ❌ accept  | Separation of duties between providers required       |

### 4.2 Integrity (tampering, replay, swap)

| #  | Threat                                                    | Mitigated? | Mechanism                                              |
| -- | --------------------------------------------------------- | :--------: | ------------------------------------------------------ |
| 10 | Per‑chunk modification of ciphertext                      | ✅         | GCM tag per 4 MiB chunk                                |
| 11 | Reordering chunks of the same archive                     | ✅         | Chunk‑index AAD bound into AEAD                        |
| 12 | Truncation (drop a chunk from the tail)                   | ✅         | `CRPEND01` final marker required                       |
| 13 | Substitution of one archive for another (replay)          | ✅         | `key_id` + `created_at` in header; manifest hash       |
| 14 | Operator‑replaced archive **+ matching KEK** on storage   | ❌ accept  | Object Lock at R2 (governance, 7 d) — runbook item     |

### 4.3 Restore‑side surfaces (the side most people forget)

These are surfaces an attacker could exploit by **planting a malicious
archive** that the operator restores — even if all the encryption
above is sound. Closed in the [`restore()`](../src/crp_comply/backup.py)
implementation.

| #  | Threat                                                    | Mitigated? | Mechanism                                              |
| -- | --------------------------------------------------------- | :--------: | ------------------------------------------------------ |
| 15 | Path traversal via `../` in tar member names              | ✅         | Reject any member containing `..` or starting `/`      |
| 16 | Absolute‑path member (`/etc/passwd`)                      | ✅         | Reject any member whose name starts with `/`           |
| 17 | Symlink / hardlink members redirecting writes             | ✅         | `member.issym() or member.islnk()` → reject            |
| 18 | Devices / FIFO / character special members                | ✅         | Only `member.isfile()` is accepted                     |
| 19 | Resolved path escapes `data_dir` after symlink resolution | ✅         | `target.resolve().relative_to(data_dir.resolve())`     |
| 20 | Tar bomb (one entry claiming 100 GiB)                     | ✅         | 5 GiB per‑member size cap                              |
| 21 | Decompression‑bomb gzip                                   | ✅ partial | Per‑member size cap applies post‑decompress; total‑size cap is operator‑set via volume quota |
| 22 | Account‑scoped JSON clobber on per‑user restore           | ✅         | `_merge_user_keyed_json` overlays only the target slice |
| 23 | Cross‑user contamination on per‑user restore              | ✅         | `_member_belongs_to_user` filter on every member       |
| 24 | Existing newer file silently overwritten                  | ✅         | `overwrite=False` is default                           |

> **Test coverage:** every `✅` row above is exercised in
> [tests/test_backup_restore.py](../tests/test_backup_restore.py).

### 4.4 Availability

| #  | Threat                                                       | Mitigated? | Mechanism                                              |
| -- | ------------------------------------------------------------ | :--------: | ------------------------------------------------------ |
| 25 | Bucket region outage                                         | ✅         | Choose an EU‑resident bucket; runbook covers manual fail‑over to S3 backup target |
| 26 | KEK loss (catastrophic)                                      | ❌ accept  | Mitigated by 2‑of‑3 secret‑manager + ops procedure     |
| 27 | All retained archives empty / corrupted                      | ✅         | Quarterly automated restore drill (§7.4)               |

---

## 5. Off‑site target: Cloudflare R2

| Setting                        | Value                                          |
| ------------------------------ | ---------------------------------------------- |
| Bucket                         | `crp-comply-backups`                           |
| Region                         | `auto` (set EEA at create time for GDPR Art. 44) |
| Endpoint                       | `https://<account>.r2.cloudflarestorage.com`   |
| Object key                     | `crp-comply-{YYYYMMDDTHHMMSS}Z.tar.gz[.enc]`   |
| Retention                      | `BACKUP_RETENTION_DAYS` (default 60 days)      |
| Schedule                       | `BACKUP_SCHEDULE_HOUR_UTC:00` (default 03:00)  |
| **Object Lock (recommended)**  | Governance mode, 7‑day cooldown — blocks replay #14 |

R2 was chosen over S3 because **zero egress fees** make restore drills
free, and EEA‑resident buckets satisfy GDPR Art. 44 without SCCs.
Switching to S3 only requires unsetting `BACKUP_R2_*` and setting
`BACKUP_S3_BUCKET`.

---

## 6. Schedule & lifecycle

```
                ┌─────────────────────────────────────────────────┐
03:00 UTC daily │ FastAPI lifespan task wakes scheduler_loop()    │
                │  ↓                                              │
                │ run_backup_once()                               │
                │   ├─ backup_all()  →  /app/data/backups/X.tar.gz│
                │   ├─ encrypt_file() →  X.tar.gz.enc (if KEK set)│
                │   ├─ unlink plaintext tarball                   │
                │   ├─ boto3 upload_file() → r2://bucket/X.tar.gz.enc
                │   ├─ prune local archives older than 60 days    │
                │   └─ prune R2 objects   older than 60 days      │
                │  ↓                                              │
                │ next loop: sleep until 03:00 UTC tomorrow       │
                └─────────────────────────────────────────────────┘
```

A failed run logs `backup scheduler: nightly backup failed` and the
loop survives — the next 03:00 UTC retries. Disable with
`CRP_COMPLY_BACKUP_INPROCESS=0`.

---

## 7. Restore procedures

### 7.1 Whole‑volume restore (disaster recovery)

```bash
# 1. Pull the most recent object from R2.
aws --endpoint-url "$BACKUP_R2_ENDPOINT" s3 cp \
    s3://crp-comply-backups/crp-comply-20260501T030000Z.tar.gz.enc \
    /tmp/restore.tar.gz.enc

# 2. Restore. backup.restore() auto-detects CRPENC01 magic, decrypts to
#    a tempfile, validates every member, and overlays into $DATA_DIR.
export BACKUP_ENCRYPTION_KEY="<the same key used at backup time>"
crp-comply restore /tmp/restore.tar.gz.enc
```

### 7.2 Single‑user restore (the path most people need)

When a user accidentally deletes their organisation profile, when a
regulator orders correction of one tenant's record, or when you are
migrating exactly one customer into a fresh deployment, **do not**
restore the whole volume. Use:

```bash
crp-comply restore-user /tmp/restore.tar.gz.enc --user u_abc123 --overwrite
```

Programmatic equivalent:

```python
from crp_comply.backup import restore_user
summary = restore_user("/tmp/restore.tar.gz.enc", "u_abc123", overwrite=True)
```

What the per‑user restore guarantees:

* **User‑scoped directories** (`reports/`, `ckf/`, `evidence_packs/`,
  `agent_sessions/`, …) — only files under `<dir>/u_abc123/` are
  written. Bob's `reports/bob/` is untouched.
* **Account‑scoped JSON files** (`users.json`, `api_keys.json`,
  `usage.json`, `provider_config.json`) — only the row keyed by
  `u_abc123` (or list‑items where `user_id == u_abc123`) is overlaid.
  Existing entries for other users are preserved bit‑for‑bit. This
  is the merge in `_merge_user_keyed_json()`.
* **Record‑keyed dirs** (`proxy_audit/`) — every JSON's payload is
  parsed and the `user_id` field is checked. Records owned by other
  users are skipped at extract time.
* **Tenant‑level paths** (`contacts/`, `org_profiles/`,
  `audit_chain/`) — these are tenant‑wide, not user‑specific, so a
  per‑user restore deliberately **skips** them. If you need to roll
  back tenant data, do it explicitly with a whole‑volume restore to
  a sandbox.

### 7.3 Disaster‑recovery checklist (whole‑service rebuild)

1. **Provision new Railway service** with the same `CRP_COMPLY_*`
   secrets *plus* the original `BACKUP_ENCRYPTION_KEY`.
2. **Mount fresh volume** at `/app/data`.
3. **Pull latest archive** from R2 (above).
4. **`crp-comply restore <archive>`** — overlays files onto the
   empty volume; existing files preserved unless `--overwrite`.
5. **Re‑run `crp-comply ingest --rebuild`** to refresh the RAG index
   if you skipped it in the archive (it is *included* by default).
6. **Smoke test**: hit `/api/v1/health`, then one tenant‑scoped read
   such as `/api/v1/programmes`.

### 7.4 Automated quarterly restore drill

Restore that has not been tested is restore that does not work.
We ship a drill script under [scripts/restore-drill.sh](../scripts/restore-drill.sh)
that:

1. Pulls a randomly‑chosen archive from R2.
2. Restores it to a temporary `$RANDOM_VOLUME`.
3. Computes SHA‑256 over a deterministic set of canonical files
   (e.g. one file from each user‑scoped dir).
4. Compares against the manifest hash recorded inside the archive's
   `MANIFEST.json` (export tarballs) or the per‑run hash logged at
   backup time (whole‑volume tarballs).
5. Writes the result to
   `audit_chain/{tenant}/restore-drills.json` with timestamp, archive
   identifier, success/fail, and the byte hash.

A failing drill pages on‑call. The drill is run quarterly via cron
on the same hosted environment.

---

## 8. Environment variables

| Variable                            | Default          | Purpose                                              |
| ----------------------------------- | ---------------- | ---------------------------------------------------- |
| `CRP_COMPLY_DATA_DIR`               | `/app/data`      | Volume root; everything inside is captured           |
| `CRP_COMPLY_BACKUP_INPROCESS`       | `1`              | Set to `0` to disable in‑process scheduler           |
| `BACKUP_DEST_DIR`                   | `$DATA/backups`  | Local archive directory                              |
| `BACKUP_RETENTION_DAYS`             | `60`             | Rolling retention window (local + remote)            |
| `BACKUP_SCHEDULE_HOUR_UTC`          | `3`              | Hour of day (UTC) to run                             |
| `BACKUP_R2_ENDPOINT`                | *(unset)*        | Cloudflare R2 S3‑compatible URL                      |
| `BACKUP_R2_BUCKET`                  | *(unset)*        | Cloudflare R2 bucket name                            |
| `BACKUP_S3_BUCKET`                  | *(unset)*        | Alternative AWS S3 bucket                            |
| `AWS_ACCESS_KEY_ID`                 | *(required)*     | R2/S3 credentials                                    |
| `AWS_SECRET_ACCESS_KEY`             | *(required)*     | R2/S3 credentials                                    |
| `AWS_DEFAULT_REGION`                | `auto`           | R2 uses `auto`; S3 uses real region                  |
| **`BACKUP_ENCRYPTION_KEY`**         | *(unset)*        | **Required for production.** 32‑byte AES‑256 key (b64 or hex) |
| **`BACKUP_ENCRYPTION_PASSPHRASE`**  | *(unset)*        | Lower‑strength fallback (SHA‑256 of passphrase)      |

---

## 9. Operations

### 9.1 Monitoring

`run_backup_once()` returns a dict that is logged structured:

```json
{
  "archive": "/app/data/backups/crp-comply-20260501T030000Z.tar.gz.enc",
  "summary": {"bytes_written": 1023456789, "files_included": 12345, "sha256": "..."},
  "retention_days": 60,
  "encryption": {"enabled": true, "alg": "AES-256-GCM", "key_id": "55423710ae4f", "chunks": 244, "ciphertext_bytes": 1023468976},
  "pruned_local": 3,
  "target": "r2://crp-comply-backups",
  "pruned_remote": 1
}
```

Wire this into your alerting:
* **Page on missing `target` for 26 h** — one missed window.
* **Page on `encryption.enabled = false` in production** — config drift.
* **Page on `summary.files_included < <last_known_good> * 0.5`** —
  catastrophic data loss before the backup ran.
* **Page on quarterly restore‑drill failure** (§7.4).

### 9.2 Cost ceiling

At ~50 active customers averaging 200 MB each: ~10 GB/day archive,
~600 GB at 60‑day retention. R2 storage at €0.013/GB‑month → **~€8
/month** for the whole rolling window with zero egress on restore.

---

## 10. Known limitations

* **No cross‑archive incremental.** Every nightly archive is a full
  snapshot. Future work: weekly full + daily delta keyed by
  `user_id` prefix. Not a priority while the dataset stays under
  ~10 GB total.
* **KEK rotation requires keeping prior keys.** No automatic
  re‑encryption job — rotate by writing a one‑shot script that
  decrypts old objects with the old key and re‑encrypts with the new.
* **Per‑user restore does not roll back tenant‑shared data.**
  `audit_chain/`, `org_profiles/`, `contacts/` are explicitly skipped
  in single‑user mode (see §7.2). Use whole‑volume restore to a
  sandbox if those are needed.

---

## 11. Quick reference

```bash
# Manual one-off backup (uses scheduler code path)
crp-comply backup-nightly

# Restore from local file (auto-detects encryption)
crp-comply restore ./crp-comply-20260501T030000Z.tar.gz.enc

# Restore one user from a full backup archive
crp-comply restore-user ./crp-comply-20260501T030000Z.tar.gz.enc --user u_abc123

# Generate a new KEK
python -c "import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"

# Inspect an encrypted archive without decrypting
python -c "from crp_comply.backup_encryption import read_header; print(read_header('archive.enc'))"
```

---

## 12. Related documents

* [VOLUME_PERSISTENCE.md](VOLUME_PERSISTENCE.md) — Railway volume layout
* [PRODUCT_SECURITY.md](../PRODUCT_SECURITY.md) — full crypto inventory
* [docker-entrypoint.sh](../docker-entrypoint.sh) — startup ordering
