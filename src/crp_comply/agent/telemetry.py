"""Loop telemetry persistence + replay store — PHASE_7 §21 7.12.

Every typed ``loop.*`` event the orchestrator emits is appended to a
per-run JSONL file under
``{CRP_COMPLY_DATA_DIR}/telemetry/loop_runs/{tenant_safe}/{run_id}.jsonl``.

Layout
------

* ``telemetry/loop_runs/<tenant>/<run_id>.jsonl`` — one JSON object per
  line. Each object has::

      {"name": "loop.opened", "ts": 1717070000.123,
       "payload": {...}}        # plaintext mode

  or::

      {"name": "loop.opened", "ts": 1717070000.123,
       "envelope": "v1.<nonce>.<ct>"}   # sealed mode

* ``telemetry/loop_runs/<tenant>/_index.jsonl`` — one line per
  ``run_id`` opened, recording ``(run_id, session_id, opened_at,
  closed_at)`` so the replay endpoint can answer
  "does this user own this run?" without scanning files. The index
  is *append-only*; closures append a fresh line, the loader picks the
  most recent record per run.

Bypass guards (PHASE_7 §21 7.12)
-------------------------------

* The store is keyed on tenant *and* run id. Cross-tenant replay
  requests resolve to "not found" so existence cannot be probed.
* ``store_event`` is best-effort: any I/O failure is logged and
  swallowed so a disk hiccup never crashes the loop. Replay simply
  returns the events that *were* written.
* Sealing is opt-in via ``CRP_COMPLY_LOOP_TELEMETRY_SEAL=1``. When on,
  every payload is run through the existing tenant KEK envelope so an
  attacker who copies the JSONL files off disk learns only event
  names + timestamps, not the observation contents.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


logger = logging.getLogger("crp_comply.agent.telemetry")


__all__ = [
    "LoopTelemetry",
    "RunRecord",
    "default_telemetry_root",
]


# ── Helpers ──────────────────────────────────────────────────────────


_SAFE_NAME = re.compile(r"[^A-Za-z0-9_\-]")


def _safe(name: str, *, fallback: str) -> str:
    s = _SAFE_NAME.sub("_", name or "")
    return s or fallback


def default_telemetry_root() -> Path:
    base = Path(os.environ.get("CRP_COMPLY_DATA_DIR", "data"))
    root = base / "telemetry" / "loop_runs"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _seal_enabled() -> bool:
    return os.environ.get("CRP_COMPLY_LOOP_TELEMETRY_SEAL", "0") == "1"


# ── Records ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    session_id: str
    tenant_id: str
    opened_at: float
    closed_at: float | None = None


# ── Store ────────────────────────────────────────────────────────────


@dataclass
class LoopTelemetry:
    """Append-only per-run event log + index.

    Construct one per process. Methods are thread-safe.
    """

    root: Path = field(default_factory=default_telemetry_root)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def _tenant_dir(self, tenant_id: str) -> Path:
        d = self.root / _safe(tenant_id, fallback="anonymous")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _run_path(self, tenant_id: str, run_id: str) -> Path:
        return self._tenant_dir(tenant_id) / f"{_safe(run_id, fallback='_')}.jsonl"

    def _index_path(self, tenant_id: str) -> Path:
        return self._tenant_dir(tenant_id) / "_index.jsonl"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def open_run(
        self,
        *,
        run_id: str,
        session_id: str,
        tenant_id: str,
    ) -> None:
        """Record a new run in the index. Idempotent (append-only)."""
        rec = RunRecord(
            run_id=run_id,
            session_id=session_id,
            tenant_id=tenant_id,
            opened_at=time.time(),
        )
        self._append_index(rec)

    def close_run(self, *, run_id: str, tenant_id: str) -> None:
        existing = self.find_run(run_id=run_id, tenant_id=tenant_id)
        if existing is None:
            return
        rec = RunRecord(
            run_id=run_id,
            session_id=existing.session_id,
            tenant_id=tenant_id,
            opened_at=existing.opened_at,
            closed_at=time.time(),
        )
        self._append_index(rec)

    def store_event(
        self,
        *,
        run_id: str,
        tenant_id: str,
        event: dict[str, Any],
    ) -> None:
        """Append one event to the run's JSONL.

        ``event`` must be the dict shape emitted by
        :func:`crp_comply.api.events.make_event`: ``{"event": "loop.x",
        "ts": ..., "run_id": ..., ...}``. The remaining keys are
        treated as the payload.

        Best-effort: I/O errors are logged and swallowed.
        """
        if not run_id or not isinstance(event, dict):
            return
        name = str(event.get("event") or "")
        if not name:
            return
        ts = float(event.get("ts") or time.time())
        payload = {k: v for k, v in event.items() if k not in {"event", "ts"}}
        line: dict[str, Any] = {"name": name, "ts": ts}
        try:
            if _seal_enabled():
                line["envelope"] = _seal_payload(payload)
            else:
                line["payload"] = payload
            self._append_event(tenant_id=tenant_id, run_id=run_id, line=line)
        except Exception as exc:  # pragma: no cover - I/O hiccups
            logger.warning(
                "loop telemetry write failed run=%s name=%s: %s",
                run_id,
                name,
                exc,
            )

    def find_run(self, *, run_id: str, tenant_id: str) -> RunRecord | None:
        """Return the most recent index entry for *run_id* under *tenant_id*."""
        path = self._index_path(tenant_id)
        if not path.exists():
            return None
        latest: RunRecord | None = None
        try:
            with path.open("r", encoding="utf-8") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        row = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if row.get("run_id") != run_id:
                        continue
                    latest = RunRecord(
                        run_id=row["run_id"],
                        session_id=row.get("session_id", ""),
                        tenant_id=row.get("tenant_id", tenant_id),
                        opened_at=float(row.get("opened_at") or 0.0),
                        closed_at=(
                            float(row["closed_at"]) if row.get("closed_at") is not None else None
                        ),
                    )
        except OSError:
            return None
        return latest

    def replay(self, *, run_id: str, tenant_id: str) -> list[dict[str, Any]]:
        """Return all events for *run_id* if owned by *tenant_id*.

        Returns an empty list when the run does not exist, the tenant
        does not own it, or the file is missing. Sealed envelopes are
        opened lazily; events that fail to decrypt are dropped with a
        warning (the loop log is best-effort, not a forensic record).
        """
        if self.find_run(run_id=run_id, tenant_id=tenant_id) is None:
            return []
        path = self._run_path(tenant_id, run_id)
        if not path.exists():
            return []
        out: list[dict[str, Any]] = []
        try:
            with path.open("r", encoding="utf-8") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        row = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    name = row.get("name")
                    ts = row.get("ts")
                    if not name or ts is None:
                        continue
                    payload: dict[str, Any]
                    if "envelope" in row:
                        try:
                            payload = _open_payload(row["envelope"])
                        except Exception as exc:
                            logger.warning(
                                "loop telemetry decrypt failed run=%s: %s",
                                run_id,
                                exc,
                            )
                            continue
                    else:
                        payload = row.get("payload") or {}
                    out.append({"event": name, "ts": float(ts), **payload})
        except OSError:
            return []
        return out

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _append_index(self, rec: RunRecord) -> None:
        line = json.dumps(
            {
                "run_id": rec.run_id,
                "session_id": rec.session_id,
                "tenant_id": rec.tenant_id,
                "opened_at": rec.opened_at,
                "closed_at": rec.closed_at,
            },
            separators=(",", ":"),
            ensure_ascii=False,
        )
        path = self._index_path(rec.tenant_id)
        with self._lock:
            try:
                with path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError as exc:  # pragma: no cover
                logger.warning(
                    "loop telemetry index write failed run=%s: %s",
                    rec.run_id,
                    exc,
                )

    def _append_event(
        self,
        *,
        tenant_id: str,
        run_id: str,
        line: dict[str, Any],
    ) -> None:
        path = self._run_path(tenant_id, run_id)
        encoded = json.dumps(line, separators=(",", ":"), ensure_ascii=False)
        with self._lock:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(encoded + "\n")


# ── Encryption helpers ───────────────────────────────────────────────


def _seal_payload(payload: dict[str, Any]) -> str:
    """Wrap *payload* in the active KEK envelope. Lazy import so the
    telemetry module stays importable in test environments without a
    KEK configured."""
    from ..api.kek import seal as _seal  # late import

    return _seal(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))


def _open_payload(envelope: str) -> dict[str, Any]:
    from ..api.kek import open_envelope as _open  # late import

    plaintext, _ = _open(envelope)
    decoded = json.loads(plaintext.decode("utf-8"))
    if not isinstance(decoded, dict):
        return {}
    return decoded


# ── Iter helpers (used by tests) ─────────────────────────────────────


def iter_run_files(root: Path) -> Iterable[Path]:
    """Yield every per-run JSONL under *root* (recurses tenants)."""
    if not root.exists():
        return
    for tenant_dir in root.iterdir():
        if not tenant_dir.is_dir():
            continue
        for p in tenant_dir.glob("*.jsonl"):
            if p.name == "_index.jsonl":
                continue
            yield p
