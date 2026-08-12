# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Backup, restore, and per-user export/erase utilities.

This module is the single authoritative place that knows the full list of
per-user data categories produced by ``crp-comply``. It is consumed by:

* the CLI subcommands ``crp-comply export-user``, ``crp-comply delete-user``,
  ``crp-comply backup-all``, ``crp-comply restore`` (see :mod:`crp_comply.cli`)
* the API endpoints ``GET /me/export`` and ``DELETE /me`` for self-service
  GDPR Art. 17 / Art. 20 (see :mod:`crp_comply.api.me`)
* nightly cron / hosted-tier disaster-recovery scripts under ``scripts/``

Data taxonomy (under ``$CRP_COMPLY_DATA_DIR``)
----------------------------------------------

Account-scoped (single file, contains many users — filtered to the target
user when exporting/deleting):

* ``users.json``                — auth identities + tier
* ``api_keys.json``             — per-user issued API keys
* ``usage.json``                — per-tier usage counters keyed by user_id
* ``provider_config.json``      — BYOK upstream credentials per user

User-scoped (one directory tree per user — moved/copied wholesale):

* ``reports/{user_id}/``        — generated audit reports
* ``evidence_packs/{user_id}/`` — evidence pack zips
* ``artefacts/{user_id}/``      — DPIAs, risk assessments, model cards
* ``agent_sessions/{user_id}/`` — paused/resumed agent runs
* ``ckf/{user_id}/``            — Contextual Knowledge Fabric facts
* ``telemetry/{user_id}/``      — anonymous-mode telemetry, when enabled
* ``retention/{user_id}/``      — retention-policy state

Cross-user (filtered by user_id field, not by directory):

* ``proxy_audit/{record_id}.json`` — chat-completion audit records (one
  file per record; each carries a ``user_id`` field)

The tarball format produced by :func:`export_user` is a plain ``.tar.gz``
with a single top-level directory ``crp-comply-export-{user_id}/`` so that
``tar -xzf`` lands in a self-contained folder. A ``MANIFEST.json`` at the
top level records counts and SHA-256 digests for every file so a verifier
can confirm the archive is intact before restoring.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import shutil
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

# ─── Constants ───────────────────────────────────────────────────────────

#: Account-scoped JSON files keyed by user_id at the top level.
USER_KEYED_JSON_FILES: tuple[str, ...] = (
    "users.json",
    "api_keys.json",
    "usage.json",
    "provider_config.json",
)

#: Top-level directories containing one subfolder per user.
USER_SCOPED_DIRS: tuple[str, ...] = (
    "reports",
    "evidence_packs",
    "artefacts",
    "agent_sessions",
    "ckf",
    "telemetry",
    "retention",
)

#: Top-level directories containing files keyed by record_id with a
#: ``user_id`` field inside each JSON.
RECORD_KEYED_DIRS: tuple[str, ...] = ("proxy_audit",)


def get_data_dir() -> Path:
    """Resolve the canonical ``$CRP_COMPLY_DATA_DIR`` path."""
    return Path(os.environ.get("CRP_COMPLY_DATA_DIR", "data"))


# ─── Result dataclasses ──────────────────────────────────────────────────


@dataclass
class ExportSummary:
    user_id: str
    archive_path: Path
    bytes_written: int
    files_included: int
    categories: dict[str, int] = field(default_factory=dict)
    sha256: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "archive_path": str(self.archive_path),
            "bytes": self.bytes_written,
            "files": self.files_included,
            "categories": dict(self.categories),
            "sha256": self.sha256,
        }


@dataclass
class DeleteSummary:
    user_id: str
    items_deleted: int
    categories: dict[str, int] = field(default_factory=dict)
    gdpr_art17: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "items_deleted": self.items_deleted,
            "categories": dict(self.categories),
            "gdpr_art17": self.gdpr_art17,
        }


@dataclass
class BackupSummary:
    archive_path: Path
    bytes_written: int
    files_included: int
    sha256: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "archive_path": str(self.archive_path),
            "bytes": self.bytes_written,
            "files": self.files_included,
            "sha256": self.sha256,
        }


@dataclass
class RestoreSummary:
    files_restored: int
    bytes_read: int
    overwrite: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "files_restored": self.files_restored,
            "bytes_read": self.bytes_read,
            "overwrite": self.overwrite,
        }


# ─── Helpers ─────────────────────────────────────────────────────────────


def _safe_user_id(user_id: str) -> str:
    """Reject anything that could escape the data dir."""
    if not user_id or not user_id.strip():
        raise ValueError("user_id must be non-empty")
    cleaned = user_id.strip()
    if "/" in cleaned or "\\" in cleaned or ".." in cleaned or "\x00" in cleaned:
        raise ValueError(f"user_id contains forbidden characters: {user_id!r}")
    if len(cleaned) > 200:
        raise ValueError("user_id too long")
    return cleaned


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _filter_user_keyed_json(path: Path, user_id: str) -> dict[str, Any] | None:
    """Load a top-level JSON file and return only the slice owned by ``user_id``.

    The shape of these files varies — some are flat ``{user_id: payload}``
    maps, some wrap that under a ``users`` / ``api_keys`` / ``records`` key.
    We try the most common shapes and fall through to ``None`` on miss.
    """
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("could not parse %s during user filter", path)
        return None
    if not isinstance(raw, dict):
        return None

    # Shape A: top-level dict keyed by user_id.
    if user_id in raw and isinstance(raw[user_id], (dict, list)):
        return {user_id: raw[user_id]}

    # Shape B: nested {"users": {user_id: ...}} or {"api_keys": {...}}.
    out: dict[str, Any] = {}
    for top_key, top_val in raw.items():
        if isinstance(top_val, dict) and user_id in top_val:
            out[top_key] = {user_id: top_val[user_id]}
        elif isinstance(top_val, list):
            owned = [
                item
                for item in top_val
                if isinstance(item, dict)
                and (item.get("user_id") == user_id or item.get("owner") == user_id)
            ]
            if owned:
                out[top_key] = owned
    return out or None


def _delete_from_user_keyed_json(path: Path, user_id: str) -> int:
    """Strip ``user_id`` from a top-level JSON file. Returns count removed."""
    if not path.exists():
        return 0
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    if not isinstance(raw, dict):
        return 0

    removed = 0
    if user_id in raw:
        del raw[user_id]
        removed += 1

    for top_key, top_val in list(raw.items()):
        if isinstance(top_val, dict) and user_id in top_val:
            del top_val[user_id]
            removed += 1
        elif isinstance(top_val, list):
            before = len(top_val)
            raw[top_key] = [
                item
                for item in top_val
                if not (
                    isinstance(item, dict)
                    and (item.get("user_id") == user_id or item.get("owner") == user_id)
                )
            ]
            removed += before - len(raw[top_key])

    if removed:
        path.write_text(json.dumps(raw, indent=2, sort_keys=True), encoding="utf-8")
    return removed


def _iter_user_files(data_dir: Path, user_id: str) -> Iterable[tuple[str, Path]]:
    """Yield ``(category, absolute_path)`` for every file owned by ``user_id``.

    Uses the three shapes documented at module top: account-scoped JSON
    slices, user-scoped directories, and record-keyed directories with a
    ``user_id`` field.
    """
    # Account-scoped JSON slices — written virtually as ``./users.json`` etc.
    for fname in USER_KEYED_JSON_FILES:
        p = data_dir / fname
        slice_ = _filter_user_keyed_json(p, user_id)
        if slice_ is not None:
            yield (fname, p)  # caller will materialise the filtered slice

    # User-scoped dirs.
    for d in USER_SCOPED_DIRS:
        user_dir = data_dir / d / user_id
        if user_dir.exists() and user_dir.is_dir():
            for f in user_dir.rglob("*"):
                if f.is_file():
                    yield (d, f)

    # Record-keyed dirs.
    for d in RECORD_KEYED_DIRS:
        rec_dir = data_dir / d
        if not rec_dir.exists():
            continue
        for f in rec_dir.rglob("*.json"):
            if not f.is_file():
                continue
            try:
                payload = json.loads(f.read_text(encoding="utf-8"))
            except Exception as _bandit_exc:
                logger.debug("swallowed in backup.export_categories (user filter): %s", _bandit_exc)
                continue
            owner = payload.get("user_id") if isinstance(payload, dict) else None
            if owner == user_id:
                yield (d, f)


# ─── Public API ──────────────────────────────────────────────────────────


def export_user(user_id: str, dest: Path | str | None = None) -> ExportSummary:
    """Export every byte the platform knows about ``user_id`` into a tarball.

    Implements GDPR Art. 20 (data portability). The archive layout is::

        crp-comply-export-{user_id}/
            MANIFEST.json
            users.json                   # filtered slice
            api_keys.json                # filtered slice
            usage.json                   # filtered slice
            provider_config.json         # filtered slice
            reports/...                  # raw user-scoped files
            evidence_packs/...
            artefacts/...
            agent_sessions/...
            ckf/...
            telemetry/...
            retention/...
            proxy_audit/{record}.json    # filtered by user_id field
    """
    user_id = _safe_user_id(user_id)
    data_dir = get_data_dir()

    if dest is None:
        ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        dest = data_dir / "exports" / f"{user_id}-{ts}.tar.gz"
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    top = f"crp-comply-export-{user_id}"
    manifest: dict[str, Any] = {
        "user_id": user_id,
        "generated_at": time.time(),
        "schema_version": 1,
        "files": [],
    }
    categories: dict[str, int] = {}
    files_included = 0

    with tarfile.open(dest, "w:gz") as tar:
        # Account-scoped slices (synthesise filtered JSON in-memory).
        for fname in USER_KEYED_JSON_FILES:
            slice_ = _filter_user_keyed_json(data_dir / fname, user_id)
            if slice_ is None:
                continue
            payload = json.dumps(slice_, indent=2, sort_keys=True).encode("utf-8")
            arcname = f"{top}/{fname}"
            info = tarfile.TarInfo(name=arcname)
            info.size = len(payload)
            info.mtime = int(time.time())
            tar.addfile(info, io.BytesIO(payload))
            manifest["files"].append(
                {
                    "path": arcname,
                    "size": len(payload),
                    "sha256": _sha256_bytes(payload),
                    "category": "account",
                }
            )
            categories[fname] = categories.get(fname, 0) + 1
            files_included += 1

        # User-scoped dirs and record-keyed dirs.
        for category, file_path in _iter_user_files(data_dir, user_id):
            if category in USER_KEYED_JSON_FILES:
                continue  # already handled above
            try:
                data = file_path.read_bytes()
            except OSError:
                continue
            rel = file_path.relative_to(data_dir).as_posix()
            arcname = f"{top}/{rel}"
            info = tarfile.TarInfo(name=arcname)
            info.size = len(data)
            info.mtime = int(file_path.stat().st_mtime)
            tar.addfile(info, io.BytesIO(data))
            manifest["files"].append(
                {
                    "path": arcname,
                    "size": len(data),
                    "sha256": _sha256_bytes(data),
                    "category": category,
                }
            )
            categories[category] = categories.get(category, 0) + 1
            files_included += 1

        # Manifest last so it can record everything else.
        manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
        info = tarfile.TarInfo(name=f"{top}/MANIFEST.json")
        info.size = len(manifest_bytes)
        info.mtime = int(time.time())
        tar.addfile(info, io.BytesIO(manifest_bytes))

    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
    return ExportSummary(
        user_id=user_id,
        archive_path=dest,
        bytes_written=dest.stat().st_size,
        files_included=files_included,
        categories=categories,
        sha256=digest,
    )


def delete_user(user_id: str, *, cascade: bool = True) -> DeleteSummary:
    """Erase every byte the platform stores about ``user_id``.

    Implements GDPR Art. 17 (right to erasure). When ``cascade`` is False
    only the auth row + api_keys are removed (account suspension); when
    True (default) all eleven data categories are wiped.
    """
    user_id = _safe_user_id(user_id)
    data_dir = get_data_dir()
    categories: dict[str, int] = {}
    total = 0

    # Account-scoped JSON files: always strip these.
    for fname in USER_KEYED_JSON_FILES:
        if not cascade and fname not in ("users.json", "api_keys.json"):
            continue
        n = _delete_from_user_keyed_json(data_dir / fname, user_id)
        if n:
            categories[fname] = n
            total += n

    if not cascade:
        return DeleteSummary(user_id=user_id, items_deleted=total, categories=categories)

    # User-scoped dirs: rmtree the user's subfolder.
    for d in USER_SCOPED_DIRS:
        user_dir = data_dir / d / user_id
        if user_dir.exists() and user_dir.is_dir():
            file_count = sum(1 for _ in user_dir.rglob("*") if _.is_file())
            shutil.rmtree(user_dir, ignore_errors=True)
            if file_count:
                categories[d] = file_count
                total += file_count

    # Record-keyed dirs: filter by user_id field.
    for d in RECORD_KEYED_DIRS:
        rec_dir = data_dir / d
        if not rec_dir.exists():
            continue
        removed = 0
        for f in rec_dir.rglob("*.json"):
            try:
                payload = json.loads(f.read_text(encoding="utf-8"))
            except Exception as _bandit_exc:
                logger.debug("swallowed in backup.delete_user: %s", _bandit_exc)
                continue
            if isinstance(payload, dict) and payload.get("user_id") == user_id:
                try:
                    f.unlink()
                    removed += 1
                except OSError:
                    continue
        if removed:
            categories[d] = removed
            total += removed

    # CACHE-GAP-1 fix: invalidate AgentCache entries keyed on this user/tenant
    # so previously-cached answers are not served to other users post-erasure.
    # GDPR Art. 17 requires the erasure to cascade through derived/cached data.
    try:
        from .agent.cache import AgentCache

        cache = AgentCache()
        dropped = cache.invalidate_tenant(user_id)
        if dropped:
            categories["agent_cache"] = dropped
            total += dropped
    except Exception as _bandit_exc:
        logger.debug("agent cache invalidation skipped (non-fatal): %s", _bandit_exc)

    return DeleteSummary(user_id=user_id, items_deleted=total, categories=categories)


def backup_all(dest: Path | str) -> BackupSummary:
    """Tar+gzip the entire ``$CRP_COMPLY_DATA_DIR`` for disaster recovery.

    The archive preserves the directory layout so ``restore`` is a
    file-level overlay. Suitable for nightly cron jobs that ship the
    output to S3/B2/R2/Backblaze.
    """
    data_dir = get_data_dir()
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    files_included = 0
    if not data_dir.exists():
        # Empty archive — still emit a valid file so the cron downstream
        # alarm catches the "data dir missing" case visibly.
        with tarfile.open(dest, "w:gz") as tar:
            info = tarfile.TarInfo(name="EMPTY")
            info.size = 0
            info.mtime = int(time.time())
            tar.addfile(info, io.BytesIO(b""))
        return BackupSummary(
            archive_path=dest,
            bytes_written=dest.stat().st_size,
            files_included=0,
            sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),
        )

    with tarfile.open(dest, "w:gz") as tar:
        for f in data_dir.rglob("*"):
            if not f.is_file():
                continue
            # Skip prior backups so we don't recurse our own output if the
            # operator points dest into the data dir.
            try:
                rel = f.relative_to(data_dir).as_posix()
            except ValueError:
                continue
            if rel.startswith("backups/") or rel.startswith("exports/"):
                continue
            tar.add(str(f), arcname=rel)
            files_included += 1

    return BackupSummary(
        archive_path=dest,
        bytes_written=dest.stat().st_size,
        files_included=files_included,
        sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),
    )


def restore(
    src: Path | str,
    *,
    overwrite: bool = False,
    user_filter: str | None = None,
) -> RestoreSummary:
    """Restore a ``backup_all`` (or ``export_user``) tarball into ``$CRP_COMPLY_DATA_DIR``.

    By default existing files are skipped so a partial restore over a
    live volume cannot silently clobber newer data. Pass ``overwrite=True``
    to force-replace every file in the archive.

    Pass ``user_filter=<user_id>`` to restore only the bytes that
    belong to a single user — preferred for selective recovery from
    a full ``backup_all`` archive. Use the higher-level
    :func:`restore_user` wrapper instead of touching this kwarg directly.
    """
    src = Path(src)
    if not src.exists():
        raise FileNotFoundError(src)

    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    # If the archive was encrypted by ``backup_scheduler`` (CRP magic
    # header), transparently decrypt to a temp file before tar-extracting.
    plain_src = src
    tmp_plain: Path | None = None
    try:
        from crp_comply.backup_encryption import (
            decrypt_file,
            is_encrypted_file,
        )

        if is_encrypted_file(src):
            import tempfile

            fd, tmp_path = tempfile.mkstemp(suffix=".tar.gz", prefix="crp-restore-")
            os.close(fd)
            tmp_plain = Path(tmp_path)
            logger.info("restore: decrypting %s -> %s", src, tmp_plain)
            decrypt_file(src, tmp_plain)
            plain_src = tmp_plain
    except Exception:
        # Re-raise: a missing KEK or wrong key is a hard failure.
        if tmp_plain and tmp_plain.exists():
            try:
                tmp_plain.unlink()
            except OSError:
                pass
        raise

    files_restored = 0
    bytes_read = 0
    try:
        with tarfile.open(plain_src, "r:gz") as tar:
            for member in tar.getmembers():
                # Reject everything that is not a regular file: symlinks,
                # hardlinks, devices, fifos and directories with a payload
                # are all attack vectors.
                if not member.isfile():
                    continue
                if member.issym() or member.islnk():  # belt + braces
                    logger.warning("skipping non-regular member %s", member.name)
                    continue
                # Reject zip-bomb-class entries early. 5 GiB per file is a
                # generous upper bound for a CRP-comply payload.
                if member.size < 0 or member.size > 5 * 1024 * 1024 * 1024:
                    logger.warning(
                        "skipping member %s: implausible size %d",
                        member.name,
                        member.size,
                    )
                    continue
                # Sanitise: never allow path traversal.
                name = member.name.replace("\\", "/")
                if name.startswith("/") or ".." in name.split("/"):
                    logger.warning("skipping unsafe member %s", name)
                    continue
                # If the archive is an export tarball, strip the top-level dir.
                parts = name.split("/", 1)
                if parts[0].startswith("crp-comply-export-") and len(parts) == 2:
                    name = parts[1]
                target = data_dir / name
                # Resolve the target *as-if* and confirm it stays inside
                # data_dir even after symlink resolution. ``resolve(strict=False)``
                # works on missing paths.
                try:
                    resolved = target.resolve(strict=False)
                    data_dir_resolved = data_dir.resolve(strict=False)
                    resolved.relative_to(data_dir_resolved)
                except (ValueError, OSError):
                    logger.warning("skipping member that escapes data_dir: %s", name)
                    continue
                if target.exists() and not overwrite:
                    continue
                ef = tar.extractfile(member)
                if ef is None:
                    continue
                data = ef.read()
                # Per-user filtering: skip any file that does not belong
                # to ``user_filter``. Membership rules mirror
                # ``_iter_user_files`` (account-scoped JSON, user-scoped
                # dirs, record-keyed dirs).
                if user_filter is not None and not _member_belongs_to_user(name, user_filter, data):
                    continue
                # Account-scoped JSON files in user-restore mode: merge
                # the restored slice into the live file rather than
                # clobbering everyone else's rows.
                if user_filter is not None and name in USER_KEYED_JSON_FILES:
                    _merge_user_keyed_json(data_dir / name, data, user_filter)
                    files_restored += 1
                    bytes_read += len(data)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                files_restored += 1
                bytes_read += len(data)
    finally:
        if tmp_plain and tmp_plain.exists():
            try:
                tmp_plain.unlink()
            except OSError:
                pass

    return RestoreSummary(
        files_restored=files_restored,
        bytes_read=bytes_read,
        overwrite=overwrite,
    )


def _member_belongs_to_user(name: str, user_id: str, data: bytes | None) -> bool:
    """Return True iff ``name`` (and optionally its payload) belongs to ``user_id``.

    Used by :func:`restore` when ``user_filter`` is set.
    """
    parts = name.split("/")
    head = parts[0]
    # Account-scoped JSON files always pass the *name* check; the actual
    # filter happens in ``_merge_user_keyed_json`` which only writes the
    # ``user_id`` slice.
    if head in USER_KEYED_JSON_FILES:
        return True
    # User-scoped directories.
    if head in USER_SCOPED_DIRS:
        return len(parts) >= 2 and parts[1] == user_id
    # Record-keyed dirs — peek at the JSON payload's user_id field.
    if head in RECORD_KEYED_DIRS:
        if data is None:
            return False
        try:
            payload = json.loads(data.decode("utf-8"))
        except Exception:
            return False
        return isinstance(payload, dict) and payload.get("user_id") == user_id
    # Tenant-level paths and global config files: never belong to a single user.
    return False


def _merge_user_keyed_json(path: Path, data: bytes, user_id: str) -> None:
    """Merge the ``user_id``-keyed slice from a tarball blob into ``path``.

    Live ``users.json`` / ``api_keys.json`` etc. on disk likely contain
    rows for *other* users. A per-user restore must overlay only the
    target user's rows without clobbering anyone else.
    """
    try:
        incoming = json.loads(data.decode("utf-8"))
    except Exception:
        logger.warning("could not parse incoming %s for merge", path.name)
        return
    if not isinstance(incoming, dict):
        return

    if path.exists():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(current, dict):
                current = {}
        except Exception:
            current = {}
    else:
        current = {}

    # Shape A: top-level ``{user_id: ...}`` — copy across.
    if user_id in incoming:
        current[user_id] = incoming[user_id]

    # Shape B: nested ``{"users": {user_id: ...}}`` — copy each nested slice.
    for top_key, top_val in incoming.items():
        if top_key == user_id:
            continue
        if isinstance(top_val, dict) and user_id in top_val:
            target = current.setdefault(top_key, {})
            if isinstance(target, dict):
                target[user_id] = top_val[user_id]
        elif isinstance(top_val, list):
            owned = [
                item
                for item in top_val
                if isinstance(item, dict)
                and (item.get("user_id") == user_id or item.get("owner") == user_id)
            ]
            if not owned:
                continue
            target_list = current.setdefault(top_key, [])
            if isinstance(target_list, list):
                # Drop existing rows for this user, then extend.
                target_list[:] = [
                    item
                    for item in target_list
                    if not (
                        isinstance(item, dict)
                        and (item.get("user_id") == user_id or item.get("owner") == user_id)
                    )
                ]
                target_list.extend(owned)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")


def restore_user(src: Path | str, user_id: str, *, overwrite: bool = False) -> RestoreSummary:
    """Restore only the data belonging to ``user_id`` from a backup archive.

    This is the preferred path for per-user recovery — restoring an
    accidentally-deleted account, rolling back one customer to last
    night's state, or migrating a single tenant into a fresh deployment
    — without touching anyone else's data.

    Accepts either a full ``backup_all`` archive or a per-user
    ``export_user`` archive (the latter has all rows owned by the
    target user, so the user_id filter is effectively a no-op).
    """
    user_id = _safe_user_id(user_id)
    return restore(src, overwrite=overwrite, user_filter=user_id)


__all__ = [
    "USER_KEYED_JSON_FILES",
    "USER_SCOPED_DIRS",
    "RECORD_KEYED_DIRS",
    "ExportSummary",
    "DeleteSummary",
    "BackupSummary",
    "RestoreSummary",
    "get_data_dir",
    "export_user",
    "delete_user",
    "backup_all",
    "restore",
    "restore_user",
]
