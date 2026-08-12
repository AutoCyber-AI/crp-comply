#!/usr/bin/env bash
# Nightly disaster-recovery backup for crp-comply.
#
# Thin wrapper around ``crp-comply backup-nightly`` so existing
# crontabs that point at this script continue to work after the upload
# logic moved into the Python CLI (boto3 — no awscli dependency).
#
# Recommended Railway setup: skip this script entirely and set the cron
# service's Start Command to ``crp-comply backup-nightly``.
#
# Reads the same env vars as the CLI subcommand:
#   CRP_COMPLY_DATA_DIR, BACKUP_DEST_DIR, BACKUP_RETENTION_DAYS,
#   BACKUP_R2_ENDPOINT, BACKUP_R2_BUCKET,
#   AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION,
#   BACKUP_S3_BUCKET.
set -euo pipefail
exec crp-comply backup-nightly "$@"
