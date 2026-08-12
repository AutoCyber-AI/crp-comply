# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Per-user Contextual Knowledge Fabric (CKF) store.

Thin wrapper around the CRP ``ContextualKnowledgeFabric`` so the API layer
can access a user's facts/events and export them for GDPR Art. 20 portability
without depending directly on the optional CRP library.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tarfile
import threading
from io import BytesIO
from pathlib import Path
from typing import Any

logger = logging.getLogger("crp_comply.agent.ckf")

_FABRICS: dict[str, Any] = {}
_lock = threading.Lock()


def _safe_dir_name(name: str) -> str:
    """Sanitise a string for use as a directory name."""
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", name)


def _load_user_fabric(user_id: str) -> Any | None:
    """Load or create the per-user CKF, returning None if CRP is unavailable."""
    try:
        from crp.ckf.fabric import CKFConfig, ContextualKnowledgeFabric
    except Exception as exc:
        logger.debug("CRP CKF unavailable: %s", exc)
        return None

    data_dir = os.environ.get("CRP_COMPLY_DATA_DIR", "data")
    persist_dir = Path(data_dir) / "ckf" / _safe_dir_name(user_id)
    persist_dir.mkdir(parents=True, exist_ok=True)
    persist_path = str(persist_dir / "ckf.db")

    config = CKFConfig(
        max_facts=10_000,
        hnsw_threshold=1000,
        persist_path=persist_path,
        gc_budget_bytes=500 * 1024 * 1024,
        community_detect_enabled=True,
    )
    fabric = ContextualKnowledgeFabric(config)
    if Path(persist_path).exists():
        try:
            fabric.restore(persist_path)
        except Exception as exc:
            logger.debug("CKF restore failed for %s: %s", user_id, exc)
    return fabric


class CKFStore:
    """Lightweight accessor for a user's CKF facts and events.

    Use :meth:`for_user` to obtain a cached instance. All methods return
    empty results gracefully when the CRP CKF library is not installed.
    """

    def __init__(self, user_id: str, fabric: Any | None = None) -> None:
        self.user_id = user_id
        self.fabric = fabric

    @classmethod
    def for_user(cls, user_id: str) -> "CKFStore":
        """Return a cached CKF store for ``user_id``."""
        with _lock:
            if user_id not in _FABRICS:
                _FABRICS[user_id] = _load_user_fabric(user_id)
            return cls(user_id, _FABRICS.get(user_id))

    def facts(self) -> list[dict[str, Any]]:
        """Return all facts visible in the user's fabric."""
        if self.fabric is None:
            return []
        try:
            result = self.fabric.query(max_results=10_000)
            facts = getattr(result, "facts", None)
            if facts is None and isinstance(result, dict):
                facts = result.get("facts")
            return [_fact_to_dict(f) for f in (facts or [])]
        except Exception as exc:
            logger.warning("CKF facts query failed for %s: %s", self.user_id, exc)
            return []

    def events(self) -> list[dict[str, Any]]:
        """Return temporal events from the user's fabric if supported."""
        if self.fabric is None:
            return []
        try:
            if hasattr(self.fabric, "temporal_query"):
                result = self.fabric.temporal_query(max_results=10_000)
                events = getattr(result, "events", None)
                if events is None and isinstance(result, dict):
                    events = result.get("events")
                return [_event_to_dict(e) for e in (events or [])]
        except Exception as exc:
            logger.debug("CKF temporal_query not available for %s: %s", self.user_id, exc)
        return []

    def export_tarball(self) -> BytesIO:
        """Build a gzipped tar of the user's CKF facts, events, and persisted files.

        Returns a seekable ``BytesIO`` positioned at the start of the stream.
        """
        buf = BytesIO()
        data_dir = os.environ.get("CRP_COMPLY_DATA_DIR", "data")
        persist_dir = Path(data_dir) / "ckf" / _safe_dir_name(self.user_id)

        # Persist any in-memory state before snapshotting.
        if self.fabric is not None:
            try:
                persist_path = str(persist_dir / "ckf.db")
                if hasattr(self.fabric, "persist"):
                    self.fabric.persist(persist_path)
                elif hasattr(self.fabric, "snapshot"):
                    self.fabric.snapshot(persist_path)
            except Exception as exc:
                logger.debug("ckf.persist before export failed: %s", exc)

        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            facts_data = json.dumps(self.facts(), indent=2, default=str).encode("utf-8")
            events_data = json.dumps(self.events(), indent=2, default=str).encode("utf-8")
            for name, data in (("facts.json", facts_data), ("events.json", events_data)):
                info = tarfile.TarInfo(name=name)
                info.size = len(data)
                tf.addfile(info, BytesIO(data))

            if persist_dir.exists():
                for entry in persist_dir.rglob("*"):
                    if entry.is_file():
                        tf.add(entry, arcname=str(entry.relative_to(persist_dir.parent)))

        buf.seek(0)
        return buf


def _fact_to_dict(fact: Any) -> dict[str, Any]:
    """Normalise a CRP Fact (or dict) into a plain dictionary."""
    if isinstance(fact, dict):
        return fact
    return {
        "id": getattr(fact, "id", ""),
        "text": getattr(fact, "text", ""),
        "category": getattr(fact, "category", ""),
        "confidence": float(getattr(fact, "confidence", 0.0)),
    }


def _event_to_dict(event: Any) -> dict[str, Any]:
    """Normalise a CRP event (or dict) into a plain dictionary."""
    if isinstance(event, dict):
        return event
    return {
        "id": getattr(event, "id", ""),
        "timestamp": getattr(event, "timestamp", ""),
        "type": getattr(event, "type", ""),
        "description": getattr(event, "description", ""),
    }


__all__ = ["CKFStore"]
