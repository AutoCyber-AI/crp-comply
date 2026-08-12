"""
CRP Audit Trail & HMAC Chain (CRP-SPEC-011).

Provides tamper-evident, append-only audit logging with per-session HMAC chains,
window-level HMACs, chain verification, export formats (NDJSON, OCSF, SARIF),
and real-time streaming to CRP Comply.

This module is intentionally independent of FastAPI and can be used by both
CRP Gateway and CRP Comply.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import asyncpg
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


class EventSeverity(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    CRITICAL = "CRITICAL"


class EventType(str, Enum):
    # Session events
    SESSION_CREATED = "SESSION_CREATED"
    SESSION_CONTINUED = "SESSION_CONTINUED"
    SESSION_TERMINATED = "SESSION_TERMINATED"

    # Dispatch events
    DISPATCH_STARTED = "DISPATCH_STARTED"
    DISPATCH_COMPLETED = "DISPATCH_COMPLETED"
    DISPATCH_FAILED = "DISPATCH_FAILED"
    RE_DISPATCH = "RE_DISPATCH"
    STRATEGY_UPGRADE = "STRATEGY_UPGRADE"

    # DPE events
    DPE_COMPLETED = "DPE_COMPLETED"
    FABRICATION_DETECTED = "FABRICATION_DETECTED"
    DISTORTION_DETECTED = "DISTORTION_DETECTED"
    CONTRADICTION_DETECTED = "CONTRADICTION_DETECTED"
    REPETITION_DETECTED = "REPETITION_DETECTED"
    COMPLETENESS_GAP = "COMPLETENESS_GAP"
    FLOW_REMEDIATION = "FLOW_REMEDIATION"
    STOP_INJECT = "STOP_INJECT"

    # Safety events
    SAFETY_HALT = "SAFETY_HALT"
    SAFETY_BUDGET_DEPLETED = "SAFETY_BUDGET_DEPLETED"
    OVERSIGHT_TRIGGERED = "OVERSIGHT_TRIGGERED"
    POLICY_VIOLATION = "POLICY_VIOLATION"

    # Compliance events
    PII_DETECTED = "PII_DETECTED"
    EU_AI_ACT_CLASSIFIED = "EU_AI_ACT_CLASSIFIED"
    COMPLY_EXPORT = "COMPLY_EXPORT"

    # CKF events
    FACT_RETRIEVED = "FACT_RETRIEVED"
    FACT_INGESTED = "FACT_INGESTED"
    FACT_DELETED = "FACT_DELETED"
    FACT_QUARANTINED = "FACT_QUARANTINED"
    CKF_ETAG_CHANGED = "CKF_ETAG_CHANGED"

    # Agent events
    TOOL_CALL = "TOOL_CALL"
    AGENT_LOOP_ITERATION = "AGENT_LOOP_ITERATION"
    FAN_OUT_CREATED = "FAN_OUT_CREATED"
    FAN_IN_MERGED = "FAN_IN_MERGED"
    COMPLETENESS_CONTINUATION = "COMPLETENESS_CONTINUATION"
    FLOW_STITCH = "FLOW_STITCH"


class ChainIntegrity(str, Enum):
    VALID = "VALID"
    BROKEN = "BROKEN"
    PARTIAL = "PARTIAL"
    UNVERIFIED = "UNVERIFIED"


@dataclass
class AuditEvent:
    event_type: EventType
    severity: EventSeverity
    session_id: str
    window_id: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    event_hmac: str = ""
    event_index: int = 0

    def canonical_data_hash(self) -> str:
        """SHA-256 of sorted JSON of the event data fields."""
        canonical = json.dumps(self.data, sort_keys=True, separators=(",", ":"), default=str)
        return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class WindowSummary:
    window_id: str
    window_number: int
    session_id: str
    timestamp: str
    response_content_hash: str
    dpe_report_hash: str
    window_hmac: str
    previous_window_hmac: str


class AuditTrail:
    """Postgres-backed append-only audit trail with HMAC chains."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        gateway_master_key: bytes,
        comply_webhook_url: str | None = None,
        comply_api_key: str | None = None,
        http_post: Callable[..., Any] | None = None,
    ) -> None:
        self.pool = pool
        self.gateway_master_key = gateway_master_key
        self.comply_webhook_url = comply_webhook_url
        self.comply_api_key = comply_api_key
        self.http_post = http_post

    # ------------------------------------------------------------------
    # Key derivation
    # ------------------------------------------------------------------

    def derive_session_hmac_key(self, session_id: str) -> bytes:
        """Derive a per-session HMAC key via HKDF-SHA256 (SPEC-015 §3.1)."""
        return self.derive_session_hmac_key_static(self.gateway_master_key, session_id)

    @staticmethod
    def derive_session_hmac_key_static(master_key: bytes, session_id: str) -> bytes:
        """Derive a per-session HMAC key via HKDF-SHA256 (SPEC-015 §3.1)."""
        return HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=session_id.encode("utf-8"),
            info=b"crp-session-sign-v3",
        ).derive(master_key)

    # ------------------------------------------------------------------
    # Event HMAC chain
    # ------------------------------------------------------------------

    @staticmethod
    def compute_event_hmac(
        event: AuditEvent,
        previous_event_hmac: str,
        session_key: bytes,
    ) -> str:
        payload = (
            event.event_type.value
            + event.timestamp
            + event.canonical_data_hash()
            + event.window_id
            + previous_event_hmac
        )
        digest = hmac.new(session_key, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return "sha256:" + digest

    @staticmethod
    def compute_window_hmac(
        summary: WindowSummary,
        session_key: bytes,
    ) -> str:
        payload = (
            summary.session_id
            + str(summary.window_number)
            + summary.timestamp
            + summary.response_content_hash
            + summary.dpe_report_hash
            + summary.previous_window_hmac
        )
        digest = hmac.new(session_key, payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return "sha256:" + digest

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def record_event(
        self,
        event: AuditEvent,
        tenant_id: str | None = None,
    ) -> AuditEvent:
        """Append an event to the audit chain. Returns the event with HMAC set."""
        session_key = self.derive_session_hmac_key(event.session_id)

        async with self.pool.acquire() as conn, conn.transaction():
            # Get the previous event HMAC for this session.
                row = await conn.fetchrow(
                    """
                    SELECT event_hmac FROM gateway_audit_events
                    WHERE session_id = $1
                    ORDER BY event_index DESC
                    LIMIT 1
                    """,
                    event.session_id,
                )
                previous_hmac = row["event_hmac"] if row else ""

                # Determine next index.
                idx_row = await conn.fetchrow(
                    "SELECT COALESCE(MAX(event_index), -1) + 1 AS idx FROM gateway_audit_events WHERE session_id = $1",
                    event.session_id,
                )
                event.event_index = idx_row["idx"] if idx_row else 0

                # Compute HMAC.
                event.event_hmac = self.compute_event_hmac(event, previous_hmac, session_key)

                await conn.execute(
                    """
                    INSERT INTO gateway_audit_events
                        (event_id, event_type, severity, session_id, window_id, tenant_id,
                         event_index, data, event_hmac, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                    """,
                    secrets.token_urlsafe(16),
                    event.event_type.value,
                    event.severity.value,
                    event.session_id,
                    event.window_id,
                    tenant_id,
                    event.event_index,
                    json.dumps(event.data, default=str),
                    event.event_hmac,
                    event.timestamp,
                )

        await self._maybe_stream_event(event, tenant_id)
        return event

    async def record_window(
        self,
        summary: WindowSummary,
        tenant_id: str | None = None,
    ) -> WindowSummary:
        """Append a window summary with its HMAC."""
        session_key = self.derive_session_hmac_key(summary.session_id)
        summary.window_hmac = self.compute_window_hmac(summary, session_key)

        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO gateway_audit_windows
                    (window_id, session_id, tenant_id, window_number, timestamp,
                     response_content_hash, dpe_report_hash, window_hmac, previous_window_hmac)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                ON CONFLICT (window_id) DO UPDATE SET
                    window_hmac = EXCLUDED.window_hmac,
                    previous_window_hmac = EXCLUDED.previous_window_hmac
                """,
                summary.window_id,
                summary.session_id,
                tenant_id,
                summary.window_number,
                summary.timestamp,
                summary.response_content_hash,
                summary.dpe_report_hash,
                summary.window_hmac,
                summary.previous_window_hmac,
            )
        return summary

    async def get_events(
        self,
        session_id: str,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[AuditEvent]:
        rows = await self.pool.fetch(
            """
            SELECT event_type, severity, session_id, window_id, data, event_hmac,
                   event_index, created_at
            FROM gateway_audit_events
            WHERE session_id = $1
            ORDER BY event_index ASC
            LIMIT $2 OFFSET $3
            """,
            session_id,
            limit,
            offset,
        )
        return [
            AuditEvent(
                event_type=EventType(r["event_type"]),
                severity=EventSeverity(r["severity"]),
                session_id=r["session_id"],
                window_id=r["window_id"],
                data=json.loads(r["data"]) if isinstance(r["data"], str) else r["data"],
                event_hmac=r["event_hmac"],
                event_index=r["event_index"],
                timestamp=r["created_at"],
            )
            for r in rows
        ]

    async def get_windows(
        self,
        session_id: str,
    ) -> list[WindowSummary]:
        rows = await self.pool.fetch(
            """
            SELECT * FROM gateway_audit_windows
            WHERE session_id = $1
            ORDER BY window_number ASC
            """,
            session_id,
        )
        return [
            WindowSummary(
                window_id=r["window_id"],
                window_number=r["window_number"],
                session_id=r["session_id"],
                timestamp=r["timestamp"],
                response_content_hash=r["response_content_hash"],
                dpe_report_hash=r["dpe_report_hash"],
                window_hmac=r["window_hmac"],
                previous_window_hmac=r["previous_window_hmac"],
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    async def verify_chain(
        self,
        session_id: str,
        from_index: int = 0,
    ) -> tuple[ChainIntegrity, int | None]:
        """Verify the full event chain for a session."""
        events = await self.get_events(session_id)
        if not events:
            return ChainIntegrity.UNVERIFIED, None

        session_key = self.derive_session_hmac_key(session_id)
        previous_hmac = ""
        broken_at: int | None = None

        for idx, event in enumerate(events):
            if idx < from_index:
                previous_hmac = event.event_hmac
                continue
            expected = self.compute_event_hmac(event, previous_hmac, session_key)
            if not hmac.compare_digest(expected, event.event_hmac):
                broken_at = event.event_index
                break
            previous_hmac = event.event_hmac

        if broken_at is not None:
            return ChainIntegrity.BROKEN, broken_at
        if from_index > 0:
            return ChainIntegrity.PARTIAL, None
        return ChainIntegrity.VALID, None

    async def verify_window(
        self,
        window_id: str,
    ) -> tuple[ChainIntegrity, WindowSummary | None]:
        """Verify a single window HMAC."""
        row = await self.pool.fetchrow(
            "SELECT * FROM gateway_audit_windows WHERE window_id = $1",
            window_id,
        )
        if not row:
            return ChainIntegrity.BROKEN, None

        summary = WindowSummary(
            window_id=row["window_id"],
            window_number=row["window_number"],
            session_id=row["session_id"],
            timestamp=row["timestamp"],
            response_content_hash=row["response_content_hash"],
            dpe_report_hash=row["dpe_report_hash"],
            window_hmac=row["window_hmac"],
            previous_window_hmac=row["previous_window_hmac"],
        )
        session_key = self.derive_session_hmac_key(summary.session_id)
        expected = self.compute_window_hmac(summary, session_key)
        if hmac.compare_digest(expected, summary.window_hmac):
            return ChainIntegrity.VALID, summary
        return ChainIntegrity.BROKEN, summary

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    async def export_ndjson(
        self,
        session_id: str,
        include_debug: bool = False,
    ) -> str:
        events = await self.get_events(session_id, limit=10000)
        lines = []
        for event in events:
            if event.severity == EventSeverity.DEBUG and not include_debug:
                continue
            lines.append(
                json.dumps(
                    {
                        "event_type": event.event_type.value,
                        "timestamp": event.timestamp,
                        "session_id": event.session_id,
                        "window_id": event.window_id,
                        "data": event.data,
                        "hmac": event.event_hmac,
                    },
                    default=str,
                )
            )
        return "\n".join(lines) + "\n" if lines else ""

    async def export_ocsf(
        self,
        session_id: str,
        include_debug: bool = False,
    ) -> list[dict[str, Any]]:
        events = await self.get_events(session_id, limit=10000)
        out = []
        severity_map = {
            EventSeverity.DEBUG: 0,
            EventSeverity.INFO: 1,
            EventSeverity.WARN: 3,
            EventSeverity.CRITICAL: 5,
        }
        activity_map = {
            EventType.DISPATCH_STARTED: 1,
            EventType.DISPATCH_COMPLETED: 2,
            EventType.DISPATCH_FAILED: 3,
            EventType.SESSION_CREATED: 4,
            EventType.SAFETY_HALT: 99,
        }
        for event in events:
            if event.severity == EventSeverity.DEBUG and not include_debug:
                continue
            out.append(
                {
                    "class_uid": 6003,
                    "activity_id": activity_map.get(event.event_type, 0),
                    "severity_id": severity_map.get(event.severity, 1),
                    "time": event.timestamp,
                    "src_endpoint": {"uid": event.session_id},
                    "metadata": {
                        "product": {"name": "CRP Gateway", "vendor_name": "AutoCyber AI"}
                    },
                    "unmapped": {
                        "crp_hmac": event.event_hmac,
                        "crp_event_type": event.event_type.value,
                        "crp_risk_level": event.data.get("risk_level"),
                    },
                }
            )
        return out

    # ------------------------------------------------------------------
    # Comply streaming
    # ------------------------------------------------------------------

    async def _maybe_stream_event(
        self,
        event: AuditEvent,
        tenant_id: str | None,
    ) -> None:
        if not self.comply_webhook_url or not self.comply_api_key or not self.http_post:
            return
        if event.severity == EventSeverity.DEBUG:
            return

        payload = {
            "events": [
                {
                    "event_type": event.event_type.value,
                    "timestamp": event.timestamp,
                    "session_id": event.session_id,
                    "window_id": event.window_id,
                    "data": event.data,
                    "hmac": event.event_hmac,
                }
            ],
            "session_id": event.session_id,
            "chain_tip_hmac": event.event_hmac,
            "tenant_id": tenant_id,
        }

        try:
            body = json.dumps(payload, default=str)
            ts = str(int(time.time()))
            sig = self._sign_comply_payload(body, ts)
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.comply_api_key}",
                "X-CRP-Signature": f"t={ts},v1={sig}",
            }
            await self.http_post(self.comply_webhook_url, headers=headers, data=body, timeout=10)
        except Exception:
            # Best-effort streaming; failures must not block the request.
            pass

    def _sign_comply_payload(self, body: str, timestamp: str) -> str:
        material = f"{timestamp}.{body}".encode()
        secret = self.comply_api_key.encode("utf-8") if self.comply_api_key else b""
        return hmac.new(secret, material, hashlib.sha256).hexdigest()

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    async def purge_older_than(self, days: int) -> int:
        """Remove audit events and windows older than N days."""
        cutoff_dt = datetime.now(timezone.utc) - __import__("datetime").timedelta(days=days)
        cutoff = cutoff_dt.isoformat()
        events_result = await self.pool.execute(
            "DELETE FROM gateway_audit_events WHERE created_at < $1",
            cutoff,
        )
        windows_result = await self.pool.execute(
            "DELETE FROM gateway_audit_windows WHERE timestamp < $1",
            cutoff,
        )
        # Parse "DELETE N" results.
        events_deleted = int(events_result.split()[1]) if events_result.startswith("DELETE") else 0
        windows_deleted = int(windows_result.split()[1]) if windows_result.startswith("DELETE") else 0
        return events_deleted + windows_deleted
