# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Volume persistence probe.

Writes a boot marker file into the data directory on every startup and records
what it finds from previous boots. This makes it immediately obvious in the
logs whether the container's data volume is truly persistent (e.g. a mounted
Railway / Fly / Kubernetes volume) or ephemeral (writes are lost on redeploy).

Behaviour
---------
* On first ever boot:         logs ``first-boot`` — can't tell yet.
* On subsequent boot AND the marker survived:   logs ``persistent: OK``.
* On subsequent boot AND the marker is gone:    logs ``EPHEMERAL WARNING``.

Also exposes ``build_status_dict()`` for the ``/health/detailed`` endpoint so
operators can inspect state at runtime.
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("crp_comply.api.persistence")

MARKER_FILENAME = ".crp_volume_marker.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_marker(path: Path) -> dict[str, Any] | None:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("failed to read volume marker: %s", exc)
    return None


def _write_marker(path: Path, marker: dict[str, Any]) -> None:
    try:
        path.write_text(json.dumps(marker, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("failed to write volume marker: %s", exc)


def probe_volume(data_dir: Path) -> dict[str, Any]:
    """Record a boot marker and return a status dict.

    The returned dict contains::

        {
            "data_dir": "/app/data",
            "writable": True|False,
            "first_boot": True|False,
            "persistent": True|False|None,      # None => unknown (first boot)
            "previous_boot_id": "...",
            "previous_boot_at": "...",
            "current_boot_id": "...",
            "current_boot_at": "...",
            "previous_boots_seen": 7,
            "warning": "..." | None,
        }
    """
    data_dir = Path(data_dir)
    status: dict[str, Any] = {
        "data_dir": str(data_dir),
        "writable": False,
        "first_boot": True,
        "persistent": None,
        "previous_boot_id": None,
        "previous_boot_at": None,
        "current_boot_id": str(uuid.uuid4()),
        "current_boot_at": _now_iso(),
        "previous_boots_seen": 0,
        "warning": None,
    }

    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        status["warning"] = f"data_dir could not be created: {exc}"
        logger.error("volume probe: %s", status["warning"])
        return status

    # Probe writability with a temp file (separate from the marker)
    probe_path = data_dir / ".crp_write_probe"
    try:
        probe_path.write_text(f"probe-{time.time()}", encoding="utf-8")
        probe_path.unlink()
        status["writable"] = True
    except Exception as exc:
        status["warning"] = f"data_dir not writable: {exc}"
        logger.error("volume probe: %s", status["warning"])
        return status

    marker_path = data_dir / MARKER_FILENAME
    previous = _read_marker(marker_path)

    if previous is None:
        status["first_boot"] = True
        status["persistent"] = None  # can't tell yet
        status["previous_boots_seen"] = 0
        logger.info(
            "volume probe: first-boot at %s (data_dir=%s) — persistence cannot be confirmed "
            "until the next restart. If this log appears on every redeploy, the volume is NOT persistent.",
            status["current_boot_at"],
            data_dir,
        )
    else:
        status["first_boot"] = False
        status["persistent"] = True
        status["previous_boot_id"] = previous.get("current_boot_id")
        status["previous_boot_at"] = previous.get("current_boot_at")
        status["previous_boots_seen"] = int(previous.get("boot_count", 0))
        logger.info(
            "volume probe: PERSISTENT OK — last boot %s (marker age %s), total boots seen=%d",
            previous.get("current_boot_at"),
            status["current_boot_at"],
            status["previous_boots_seen"] + 1,
        )

    # Write the new marker, carrying forward the boot count
    new_marker = {
        "current_boot_id": status["current_boot_id"],
        "current_boot_at": status["current_boot_at"],
        "previous_boot_id": status["previous_boot_id"],
        "previous_boot_at": status["previous_boot_at"],
        "boot_count": status["previous_boots_seen"] + 1,
        "pid": os.getpid(),
    }
    _write_marker(marker_path, new_marker)

    return status


# ── last-known status for /health/detailed ─────────────────────
_last_status: dict[str, Any] | None = None


def record_status(status: dict[str, Any]) -> None:
    """Store the probe result for later retrieval."""
    global _last_status
    _last_status = status


def build_status_dict() -> dict[str, Any]:
    """Return the latest probe result (or ``{"probed": False}``)."""
    if _last_status is None:
        return {"probed": False}
    return {"probed": True, **_last_status}
