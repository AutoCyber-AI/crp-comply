# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""
Artefact intake — Layer 2 of the three-layer compliance model.

Regulators do not audit a policy in isolation; they audit a policy
backed by evidence. ``COMPLIANCE_MODEL_ANALYSIS.md`` classifies
deliverables into three buckets, and Bucket B (Annex IV technical
file, DPIA, FRIA, bias assessments) depends on user-supplied
artefacts — model cards, dataset cards, architecture diagrams,
signed DPAs, penetration-test reports, prior certifications.

Until this module existed, the recipe-drafting pipeline had no
place to *look* for those artefacts, so Bucket B drafts quietly
substituted plausible-looking prose for evidence that wasn't
there. That is the failure mode §4 of the analysis document
calls out by name.

Design choices
--------------
* **Storage is filesystem-only**, matching :mod:`reports` and
  :mod:`evidence_packs`. The workspace volume is the single
  source of truth and persists across container restarts per
  ``docs/VOLUME_PERSISTENCE.md``.
* **Tenant isolation is per-user-id**. The same ``user_id`` that
  scopes reports scopes artefacts.
* **Clause tagging is first-class**. Every artefact may declare
  a list of regulatory clause identifiers it evidences (e.g.
  ``["eu_ai_act_art_10", "iso_42001_A.7"]``). Drafting code can
  therefore ask "what have we got for Art. 10?" without parsing
  filenames.
* **Hashing is deterministic and stored**. Each artefact carries a
  SHA-256 of its bytes so the evidence-pack exporter can emit a
  tamper-evident manifest without re-reading the file.

Security
--------
* File size is capped at ``MAX_ARTEFACT_BYTES`` (25 MB) to keep a
  free-tier user from filling the volume.
* Original filenames are sanitised before being joined with the
  storage path. ``_sanitize`` is imported from :mod:`reports` to
  keep the sanitiser logic single-sourced.
* We accept any content-type; downstream consumers (evidence-pack
  builder, UI preview) decide how to render based on the recorded
  ``content_type``. We do not execute or parse artefacts here.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse

from .deps import get_current_user, meter_call

logger = logging.getLogger("crp_comply.api.artefacts")

MAX_ARTEFACT_BYTES = 25 * 1024 * 1024  # 25 MB

# Allowed artefact "kind" values. These map 1:1 onto the rows shown
# in the frontend Artefacts page; keeping the set closed means the
# UI can render a known icon + copy per kind instead of freeform
# strings. Add new kinds here deliberately, not opportunistically.
ARTEFACT_KINDS: frozenset[str] = frozenset(
    {
        "model_card",
        "dataset_card",
        "architecture",
        "pentest",
        "prior_cert",
        "dpa",
        "bias_audit",
        "other",
    }
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sanitize(name: str) -> str:
    """Filesystem-safe rendering of an identifier.

    Mirrors :func:`crp_comply.api.reports._sanitize`; duplicated
    here to avoid an import cycle when :mod:`reports` is not yet
    initialised during cold-start.
    """
    keep = "-_."
    cleaned = "".join(c if c.isalnum() or c in keep else "_" for c in name)
    return cleaned[:120] or "unnamed"


class ArtefactStore:
    """Per-user filesystem artefact store.

    Layout::

        {data_dir}/artefacts/{user_id_safe}/{artefact_id}/
            meta.json            # envelope + clause tags + hashes
            blob.<ext>           # original file bytes

    The envelope is returned to API callers; the blob is served via
    a separate download endpoint so we never hold large payloads in
    memory during list queries.
    """

    def __init__(self, data_dir: Path) -> None:
        self._root = Path(data_dir) / "artefacts"
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _user_dir(self, user_id: str) -> Path:
        d = self._root / _sanitize(user_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _artefact_dir(self, user_id: str, artefact_id: str) -> Path:
        return self._user_dir(user_id) / _sanitize(artefact_id)

    def save(
        self,
        *,
        user_id: str,
        kind: str,
        filename: str,
        content_type: str,
        data: bytes,
        clauses: list[str] | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        if kind not in ARTEFACT_KINDS:
            raise ValueError(f"Unknown artefact kind: {kind!r}")
        if len(data) > MAX_ARTEFACT_BYTES:
            raise ValueError(f"Artefact exceeds {MAX_ARTEFACT_BYTES} bytes (got {len(data)})")
        if not data:
            raise ValueError("Empty artefact payload")

        artefact_id = str(uuid.uuid4())
        now = _utc_now_iso()
        sha = hashlib.sha256(data).hexdigest()
        safe_name = _sanitize(filename or "upload")
        # Preserve an extension when one is present so downloads
        # round-trip correctly without sniffing content-type.
        suffix = Path(safe_name).suffix or ""
        blob_name = f"blob{suffix}"

        meta: dict[str, Any] = {
            "id": artefact_id,
            "user_id": user_id,
            "kind": kind,
            "filename": safe_name,
            "content_type": content_type or "application/octet-stream",
            "size_bytes": len(data),
            "sha256": sha,
            "clauses": list(clauses or []),
            "description": description or "",
            "created_at": now,
        }

        adir = self._artefact_dir(user_id, artefact_id)
        with self._lock:
            adir.mkdir(parents=True, exist_ok=True)
            (adir / blob_name).write_bytes(data)
            (adir / "meta.json").write_text(
                json.dumps(meta, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

        logger.info(
            "artefact saved: kind=%s id=%s user=%s bytes=%d sha=%s",
            kind,
            artefact_id,
            user_id,
            len(data),
            sha[:12],
        )
        return meta

    def list(self, user_id: str) -> list[dict[str, Any]]:
        d = self._user_dir(user_id)
        out: list[dict[str, Any]] = []
        for sub in d.iterdir():
            if not sub.is_dir():
                continue
            meta_path = sub / "meta.json"
            if not meta_path.exists():
                continue
            try:
                out.append(json.loads(meta_path.read_text(encoding="utf-8")))
            except Exception as exc:  # pragma: no cover — corrupt file
                logger.warning("failed to read artefact meta %s: %s", meta_path, exc)
        out.sort(key=lambda r: r.get("created_at") or "", reverse=True)
        return out

    def get(self, user_id: str, artefact_id: str) -> dict[str, Any] | None:
        adir = self._artefact_dir(user_id, artefact_id)
        meta_path = adir / "meta.json"
        if not meta_path.exists():
            return None
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def blob_path(self, user_id: str, artefact_id: str) -> Path | None:
        adir = self._artefact_dir(user_id, artefact_id)
        if not adir.exists():
            return None
        for child in adir.iterdir():
            if child.name.startswith("blob"):
                return child
        return None

    def delete(self, user_id: str, artefact_id: str) -> bool:
        adir = self._artefact_dir(user_id, artefact_id)
        if not adir.exists():
            return False
        with self._lock:
            for child in adir.iterdir():
                try:
                    child.unlink()
                except OSError:
                    pass
            try:
                adir.rmdir()
            except OSError:
                pass
        return True

    def for_clauses(self, user_id: str, clauses: list[str]) -> list[dict[str, Any]]:
        """Return artefacts tagged with at least one of the given clauses.

        Intended for the recipe drafting pipeline: before it writes a
        paragraph that cites Art. 10(3), it can ask the store "do we
        have a dataset card for this?" and stamp the draft with a
        real artefact reference instead of inventing one.
        """
        wanted = set(clauses)
        return [a for a in self.list(user_id) if wanted.intersection(set(a.get("clauses") or []))]


_store: ArtefactStore | None = None


def init_artefact_store(data_dir: Path) -> None:
    global _store
    _store = ArtefactStore(data_dir)
    logger.info("ArtefactStore initialised at %s", data_dir)


def get_artefact_store() -> ArtefactStore:
    if _store is None:
        raise RuntimeError("ArtefactStore is not initialised")
    return _store


# ─────────────────────────────────────────────────────────────────
#   HTTP surface
# ─────────────────────────────────────────────────────────────────
#
# Artefact upload is a write operation and therefore metered. The
# ``meter_call`` dependency enforces per-tier quota ceilings exactly
# as for report generation and proxy calls, so a hostile user cannot
# fill the volume by looping uploads on a free tier.

router = APIRouter(prefix="/artefacts", tags=["artefacts"])


@router.get(
    "",
    summary="List artefacts uploaded by the current user",
)
async def list_artefacts_endpoint(user_id: str = Depends(get_current_user)):
    if user_id == "anonymous":
        # Anonymous users are scoped to an ephemeral id and should not be
        # encouraged to store evidence artefacts they cannot later retrieve.
        return {"artefacts": []}
    return {"artefacts": get_artefact_store().list(user_id)}


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    summary="Upload a user-supplied evidence artefact",
    dependencies=[Depends(meter_call("artefacts-upload"))],
)
async def upload_artefact(
    file: UploadFile = File(...),
    kind: str = Form(...),
    clauses: str = Form(""),
    description: str = Form(""),
    user_id: str = Depends(get_current_user),
):
    if user_id == "anonymous":
        raise HTTPException(
            status_code=401,
            detail="Sign in to upload artefacts.",
        )
    if kind not in ARTEFACT_KINDS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown artefact kind {kind!r}; expected one of {sorted(ARTEFACT_KINDS)}",
        )

    data = await file.read()
    if len(data) > MAX_ARTEFACT_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Artefact exceeds {MAX_ARTEFACT_BYTES // (1024 * 1024)} MB limit",
        )
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    # ``clauses`` is a comma-separated list in form-data to avoid the
    # double-escaping that ``application/x-www-form-urlencoded`` array
    # semantics would otherwise require. Empty entries are dropped.
    clause_list = [c.strip() for c in clauses.split(",") if c.strip()]

    meta = get_artefact_store().save(
        user_id=user_id,
        kind=kind,
        filename=file.filename or "upload",
        content_type=file.content_type or "application/octet-stream",
        data=data,
        clauses=clause_list,
        description=description,
    )
    return meta


@router.get(
    "/{artefact_id}",
    summary="Fetch an artefact's metadata envelope",
)
async def get_artefact_meta(
    artefact_id: str,
    user_id: str = Depends(get_current_user),
):
    if user_id == "anonymous":
        raise HTTPException(status_code=401, detail="Sign in to view artefacts.")
    meta = get_artefact_store().get(user_id, artefact_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Artefact not found")
    return meta


@router.get(
    "/{artefact_id}/download",
    summary="Download the raw artefact bytes",
)
async def download_artefact(
    artefact_id: str,
    user_id: str = Depends(get_current_user),
):
    if user_id == "anonymous":
        raise HTTPException(status_code=401, detail="Sign in to download artefacts.")
    store = get_artefact_store()
    meta = store.get(user_id, artefact_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Artefact not found")
    path = store.blob_path(user_id, artefact_id)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="Artefact blob missing")
    return FileResponse(
        path=str(path),
        media_type=meta.get("content_type") or "application/octet-stream",
        filename=meta.get("filename") or f"{artefact_id}.bin",
    )


@router.delete(
    "/{artefact_id}",
    summary="Delete an artefact",
)
async def delete_artefact(
    artefact_id: str,
    user_id: str = Depends(get_current_user),
):
    if user_id == "anonymous":
        raise HTTPException(status_code=401, detail="Sign in to manage artefacts.")
    if not get_artefact_store().delete(user_id, artefact_id):
        raise HTTPException(status_code=404, detail="Artefact not found")
    return {"deleted": True, "artefact_id": artefact_id}
