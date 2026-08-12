"""In-process nightly backup scheduler.

Railway volumes are isolated per service, so a separate cron *service*
cannot read the API service's ``/app/data`` volume. The scheduler in
this module therefore runs **inside** the API process: an asyncio task
started during FastAPI lifespan that, once a day at the configured UTC
hour, archives ``CRP_COMPLY_DATA_DIR``, uploads the archive to
Cloudflare R2 (or AWS S3), and prunes both local and remote archives
beyond ``BACKUP_RETENTION_DAYS``.

The same :func:`run_backup_once` helper is used by the
``crp-comply backup-nightly`` CLI so there is a single source of truth.

Environment variables (all read at run time, never required at import):

* ``CRP_COMPLY_DATA_DIR``       — live data directory (default ``/app/data``).
* ``BACKUP_DEST_DIR``           — local archive directory.
* ``BACKUP_RETENTION_DAYS``     — rolling window (default 60).
* ``BACKUP_R2_ENDPOINT``        — Cloudflare R2 S3-compatible endpoint URL.
* ``BACKUP_R2_BUCKET``          — Cloudflare R2 bucket name.
* ``BACKUP_S3_BUCKET``          — AWS S3 bucket (alternative to R2).
* ``AWS_ACCESS_KEY_ID`` /
  ``AWS_SECRET_ACCESS_KEY`` /
  ``AWS_DEFAULT_REGION``        — credentials (R2 = ``auto`` region).
* ``BACKUP_SCHEDULE_HOUR_UTC``  — hour of day to run (default ``3``).
* ``CRP_COMPLY_BACKUP_INPROCESS`` — set to ``0`` to disable scheduling.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def run_backup_once() -> dict[str, Any]:
    """Archive the live data dir, ship it off-site, and prune.

    Returns a JSON-serialisable summary dict. Never raises for
    "no off-site target configured" — that's a valid dev scenario.
    Raises on actual upload errors so the caller (CLI or scheduler)
    can surface them.
    """
    from crp_comply.backup import backup_all, get_data_dir

    data_dir = get_data_dir()
    dest_dir = Path(os.environ.get("BACKUP_DEST_DIR", str(data_dir / "backups")))
    dest_dir.mkdir(parents=True, exist_ok=True)
    retention = int(os.environ.get("BACKUP_RETENTION_DAYS", "60"))

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = dest_dir / f"crp-comply-{ts}.tar.gz"
    logger.info("backup: archiving %s -> %s", data_dir, archive)
    summary = backup_all(archive)
    result: dict[str, Any] = {
        "archive": str(archive),
        "summary": summary.as_dict(),
        "retention_days": retention,
    }

    # Client-side encryption (defence-in-depth) — when a KEK is
    # configured, encrypt the tarball before any off-site upload so
    # only ciphertext leaves this process.
    upload_path = archive
    upload_name = archive.name
    try:
        from crp_comply.backup_encryption import (
            encrypt_file,
            is_encryption_enabled,
        )

        if is_encryption_enabled():
            enc_path = dest_dir / f"{archive.name}.enc"
            enc_summary = encrypt_file(archive, enc_path)
            # Plaintext tarball is no longer needed locally — wipe it
            # so a host compromise cannot replay yesterday's data.
            try:
                archive.unlink()
            except OSError:
                logger.warning("backup: failed to unlink plaintext archive %s", archive)
            upload_path = enc_path
            upload_name = enc_path.name
            result["encryption"] = {
                "enabled": True,
                "alg": enc_summary["alg"],
                "key_id": enc_summary["key_id"],
                "chunks": enc_summary["chunks"],
                "ciphertext_bytes": enc_summary["bytes_out"],
            }
            result["archive"] = str(enc_path)
            logger.info(
                "backup: encrypted to %s (key_id=%s)",
                enc_path,
                enc_summary["key_id"],
            )
        else:
            result["encryption"] = {"enabled": False}
            logger.info(
                "backup: BACKUP_ENCRYPTION_KEY not set — uploading plaintext "
                "(R2 still encrypts at rest, but operator-managed encryption "
                "is recommended for defence in depth)"
            )
    except Exception as exc:  # pragma: no cover - keep backup running
        logger.warning("backup: encryption failed (%s); aborting upload to be safe", exc)
        result["encryption"] = {"enabled": False, "error": str(exc)}
        # Do NOT upload plaintext if the operator asked for encryption
        # but it failed. Better to fail loud than to leak silently.
        from crp_comply.backup_encryption import is_encryption_enabled

        if is_encryption_enabled():
            result["target"] = "local-only-encryption-failed"
            return result

    # Prune local archives.
    cutoff = time.time() - retention * 86400
    pruned_local = 0
    for pattern in ("crp-comply-*.tar.gz", "crp-comply-*.tar.gz.enc"):
        for p in dest_dir.glob(pattern):
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink()
                    pruned_local += 1
            except OSError:
                pass
    result["pruned_local"] = pruned_local

    r2_endpoint = os.environ.get("BACKUP_R2_ENDPOINT", "").strip()
    r2_bucket = os.environ.get("BACKUP_R2_BUCKET", "").strip()
    s3_bucket = os.environ.get("BACKUP_S3_BUCKET", "").strip()

    if r2_endpoint and r2_bucket:
        import boto3  # type: ignore[import-not-found]

        client = boto3.client(
            "s3",
            endpoint_url=r2_endpoint,
            region_name=os.environ.get("AWS_DEFAULT_REGION", "auto"),
        )
        logger.info("backup: uploading to R2 bucket=%s key=%s", r2_bucket, upload_name)
        client.upload_file(str(upload_path), r2_bucket, upload_name)

        paginator = client.get_paginator("list_objects_v2")
        cutoff_dt = datetime.now(timezone.utc).timestamp() - retention * 86400
        removed = 0
        for page in paginator.paginate(Bucket=r2_bucket, Prefix="crp-comply-"):
            for obj in page.get("Contents", []) or []:
                if obj["LastModified"].timestamp() < cutoff_dt:
                    client.delete_object(Bucket=r2_bucket, Key=obj["Key"])
                    removed += 1
        result["target"] = f"r2://{r2_bucket}"
        result["pruned_remote"] = removed
    elif s3_bucket:
        import boto3  # type: ignore[import-not-found]

        client = boto3.client("s3")
        logger.info("backup: uploading to S3 bucket=%s key=%s", s3_bucket, upload_name)
        client.upload_file(str(upload_path), s3_bucket, upload_name)
        result["target"] = f"s3://{s3_bucket}"
    else:
        logger.info(
            "backup: no off-site target configured "
            "(BACKUP_R2_ENDPOINT / BACKUP_S3_BUCKET unset) — local only"
        )
        result["target"] = "local-only"

    return result


def _seconds_until_next_run(hour_utc: int) -> float:
    """Compute seconds until the next ``hour_utc:00 UTC``."""
    now = datetime.now(timezone.utc)
    target = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    if target <= now:
        target = target + timedelta(days=1)
    return max(1.0, (target - now).total_seconds())


def is_enabled() -> bool:
    """The scheduler runs unless explicitly disabled."""
    return os.environ.get("CRP_COMPLY_BACKUP_INPROCESS", "1").lower() not in (
        "0",
        "false",
        "no",
    )


async def scheduler_loop() -> None:
    """Daily loop: sleep to the next ``hour_utc:00`` then run a backup.

    Failures are logged but never crash the loop — the next day's run
    will retry. Designed to be cancelled cleanly during shutdown.
    """
    hour_utc = int(os.environ.get("BACKUP_SCHEDULE_HOUR_UTC", "3"))
    logger.info("backup scheduler: armed for %02d:00 UTC", hour_utc)
    while True:
        delay = _seconds_until_next_run(hour_utc)
        logger.info("backup scheduler: sleeping %.0fs until next run", delay)
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            raise
        try:
            # backup_all + boto3 are blocking; run off the event loop.
            await asyncio.to_thread(run_backup_once)
            logger.info("backup scheduler: nightly backup complete")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — keep loop alive
            logger.error("backup scheduler: nightly backup FAILED: %s", exc)
