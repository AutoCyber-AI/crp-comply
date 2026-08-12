# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Self-service GDPR endpoints (Art. 17 / Art. 20).

Every authenticated user can:

* ``GET  /me/export``  — download a tarball of every byte we hold
  about them (Art. 20 portability).
* ``DELETE /me``       — wipe their account and all dependent data
  (Art. 17 erasure). Issues a 200 with the per-category counts.

These wrap :mod:`crp_comply.backup` so the same code paths are
exercised by the CLI subcommands ``crp-comply export-user`` and
``crp-comply delete-user``.
"""

from __future__ import annotations

import logging
import shutil
import time
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..agent.preferences import get_preference_store
from ..backup import delete_user, export_user, get_data_dir, _safe_user_id
from .auth import Tier, check_feature_access
from .deps import get_current_tenant, get_current_tier, get_current_user
from .models import UserPreferenceProfileResponse, UserPreferenceProfileUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/me", tags=["self-service"])


# ── Managed backups (paid feature) ─────────────────────────────
class ManagedBackupRecord(BaseModel):
    id: str
    created_at: float
    size_bytes: int
    sha256: str | None = None


class ManagedBackupList(BaseModel):
    backups: list[ManagedBackupRecord]


def _managed_backup_dir(user_id: str) -> Path:
    """Per-user directory under the data volume holding stored snapshots."""
    safe = _safe_user_id(user_id)
    d = get_data_dir() / "managed_backups" / safe
    d.mkdir(parents=True, exist_ok=True)
    return d


def _require_managed_backups(tier: Tier) -> None:
    if not check_feature_access(tier, "managed_backups"):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Managed backups require a paid plan (Starter or higher).",
        )


@router.get("/export", summary="Export all data we hold about you (GDPR Art. 20).")
def me_export(user_id: Annotated[str, Depends(get_current_user)]):
    """Generate and stream a ``.tar.gz`` containing every artefact we hold."""
    try:
        summary = export_user(user_id)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("export_user failed user=%s", user_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"export failed: {type(exc).__name__}",
        ) from exc

    archive = summary.archive_path
    return FileResponse(
        path=str(archive),
        media_type="application/gzip",
        filename=archive.name,
        headers={
            "X-CRP-Comply-Export-Files": str(summary.files_included),
            "X-CRP-Comply-Export-SHA256": summary.sha256,
            "X-CRP-Comply-GDPR-Article": "20",
        },
    )


@router.delete("", summary="Erase your account and all dependent data (GDPR Art. 17).")
def me_delete(user_id: Annotated[str, Depends(get_current_user)]):
    """Cascade-delete every artefact tied to the authenticated user."""
    try:
        summary = delete_user(user_id, cascade=True)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("delete_user failed user=%s", user_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"erasure failed: {type(exc).__name__}",
        ) from exc
    return summary.as_dict()


@router.post(
    "/backups",
    response_model=ManagedBackupRecord,
    summary="Create a server-stored snapshot of your data (paid feature).",
)
def create_managed_backup(
    user_id: Annotated[str, Depends(get_current_user)],
    tier: Annotated[Tier, Depends(get_current_tier)],
) -> ManagedBackupRecord:
    """Generate a snapshot and store it on the platform for later restore.

    Distinct from ``GET /me/export`` (GDPR Art. 20, always free): this
    creates a *retained* snapshot that the user can list and re-download
    without re-running export. Gated by the ``managed_backups`` feature
    flag, which is granted to every paid tier.
    """
    _require_managed_backups(tier)
    summary = export_user(user_id)
    dest_dir = _managed_backup_dir(user_id)
    ts = int(time.time())
    backup_id = f"snapshot-{ts}"
    target = dest_dir / f"{backup_id}.tar.gz"
    shutil.move(str(summary.archive_path), target)
    return ManagedBackupRecord(
        id=backup_id,
        created_at=float(ts),
        size_bytes=target.stat().st_size,
        sha256=summary.sha256,
    )


@router.get(
    "/backups",
    response_model=ManagedBackupList,
    summary="List your stored snapshots (paid feature).",
)
def list_managed_backups(
    user_id: Annotated[str, Depends(get_current_user)],
    tier: Annotated[Tier, Depends(get_current_tier)],
) -> ManagedBackupList:
    _require_managed_backups(tier)
    d = _managed_backup_dir(user_id)
    records: list[ManagedBackupRecord] = []
    for p in sorted(d.glob("snapshot-*.tar.gz")):
        st = p.stat()
        records.append(
            ManagedBackupRecord(
                id=p.stem,
                created_at=float(st.st_mtime),
                size_bytes=st.st_size,
            )
        )
    return ManagedBackupList(backups=records)


@router.get(
    "/backups/{backup_id}",
    summary="Download one of your stored snapshots (paid feature).",
)
def download_managed_backup(
    backup_id: str,
    user_id: Annotated[str, Depends(get_current_user)],
    tier: Annotated[Tier, Depends(get_current_tier)],
):
    _require_managed_backups(tier)
    # Reject path traversal — only accept simple "snapshot-<digits>" ids.
    if not backup_id.startswith("snapshot-") or not backup_id[9:].isdigit():
        raise HTTPException(status_code=400, detail="invalid backup id")
    target = _managed_backup_dir(user_id) / f"{backup_id}.tar.gz"
    if not target.is_file():
        raise HTTPException(status_code=404, detail="backup not found")
    return FileResponse(
        path=str(target),
        media_type="application/gzip",
        filename=target.name,
    )


@router.delete(
    "/backups/{backup_id}",
    summary="Delete one of your stored snapshots (paid feature).",
)
def delete_managed_backup(
    backup_id: str,
    user_id: Annotated[str, Depends(get_current_user)],
    tier: Annotated[Tier, Depends(get_current_tier)],
) -> dict[str, str]:
    _require_managed_backups(tier)
    if not backup_id.startswith("snapshot-") or not backup_id[9:].isdigit():
        raise HTTPException(status_code=400, detail="invalid backup id")
    target = _managed_backup_dir(user_id) / f"{backup_id}.tar.gz"
    if target.is_file():
        target.unlink()
        return {"status": "deleted", "id": backup_id}
    raise HTTPException(status_code=404, detail="backup not found")


# ── Preference profile (Phase 5a) ──────────────────────────────────────────


@router.get(
    "/preferences",
    response_model=UserPreferenceProfileResponse,
    summary="Get your learned preference profile.",
)
def get_preferences(
    user_id: Annotated[str, Depends(get_current_user)],
    tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> UserPreferenceProfileResponse:
    """Return the durable per-user preference profile."""
    if user_id == "anonymous":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Preference profiles require authentication.",
        )
    profile = get_preference_store().load(tenant_id, user_id)
    return UserPreferenceProfileResponse(**profile.to_dict())


@router.post(
    "/preferences",
    response_model=UserPreferenceProfileResponse,
    summary="Update or reset your learned preference profile.",
)
def update_preferences(
    req: UserPreferenceProfileUpdate,
    user_id: Annotated[str, Depends(get_current_user)],
    tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> UserPreferenceProfileResponse:
    """Override learned defaults, or reset personalization to defaults."""
    if user_id == "anonymous":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Preference profiles require authentication.",
        )
    store = get_preference_store()
    profile = store.load(tenant_id, user_id)
    if req.reset:
        profile = store.reset(tenant_id, user_id)
    else:
        if req.preferred_depth is not None:
            profile.preferred_depth = req.preferred_depth
        if req.preferred_format is not None:
            profile.preferred_format = req.preferred_format
        if req.preferred_audience is not None:
            profile.preferred_audience = req.preferred_audience
        if req.preferred_regulations is not None:
            profile.preferred_regulations = req.preferred_regulations
        if req.trusted_source_domains is not None:
            profile.trusted_source_domains = req.trusted_source_domains
        if req.satisfaction_criteria is not None:
            profile.satisfaction_criteria = req.satisfaction_criteria
        if req.preferred_autonomy is not None:
            profile.preferred_autonomy = req.preferred_autonomy
        store.save(profile)
    return UserPreferenceProfileResponse(**profile.to_dict())
