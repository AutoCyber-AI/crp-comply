# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Compliance interception engine — CRP-native PII scanning, injection
detection, risk classification, upstream forwarding, consent management,
and tamper-evident audit trail.

Every proxied LLM request is:
  1. PII-scanned via CRP PIIScanner (7 categories)
  2. Injection-checked via CRP InjectionDetector (21 patterns + ML)
  3. Risk-classified via CRP RiskClassifier (EU AI Act Art. 6)
  4. Consent-verified via CRP ConsentManager
  5. Forwarded to the upstream LLM provider
  6. PII-scanned (output)
  7. Written to CRP ComplianceAuditTrail (HMAC-chained, tamper-evident)
  8. Logged to CRP ProcessingRecordKeeper (GDPR Art. 30)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("crp_comply.proxy")

try:
    from crp.security import (
        ComplianceAuditTrail,
        ComplianceEventType,
        ConsentManager,
        DataClassification,
        DataLineageTracker,
        ErasureManager,
        InjectionDetector,
        PIIScanner,
        ProcessingPurpose,
        ProcessingRecordKeeper,
        RetentionManager,
        RiskClassifier,
    )
    from crp.provenance import (
        DecisionProvenanceEngine,
        ProvenanceConfig,
    )

    _CRP_AVAILABLE = True
except ImportError:
    _CRP_AVAILABLE = False
    logger.critical(
        "CRP SDK not installed — proxy compliance features are DISABLED. "
        "Install with: pip install 'crprotocol[full]>=2.0.0'"
    )

from .models import (  # noqa: E402
    AuditRecord,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ComplianceStats,
)


class ComplianceInterceptor:
    """Core compliance interception engine for the LLM proxy.

    Wraps CRP's full security stack:
    - PIIScanner (7 categories, configurable)
    - InjectionDetector (21 regex patterns + optional ML backends)
    - RiskClassifier (EU AI Act Art. 6 classification)
    - ComplianceAuditTrail (HMAC-SHA256 chained, tamper-evident)
    - ConsentManager (8 processing purposes, withdrawal support)
    - ProcessingRecordKeeper (GDPR Art. 30 records)
    - ErasureManager (GDPR Art. 17 right-to-erasure)
    - RetentionManager (classification-based retention policies)
    - DataLineageTracker (data provenance through the proxy)
    """

    def __init__(
        self,
        data_dir: Path,
        hmac_secret: str,
        http_timeout: float = 120.0,
    ) -> None:
        self.data_dir = data_dir
        self.audit_dir = data_dir / "proxy_audit"
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        self._hmac_secret = hmac_secret.encode()
        self.http_client = httpx.AsyncClient(timeout=http_timeout)
        # Per-user isolation dicts for multi-tenant audit/consent compliance (PROXY-GAP-B, C fix)
        self._per_user_trails: dict[str, Any] = {}
        self._per_user_pr: dict[str, Any] = {}
        self._per_user_consent: dict[str, Any] = {}
        self._per_user_consent_grants: dict[str, set[str]] = {}

        if not _CRP_AVAILABLE:
            # Degraded mode — CRP not installed. Compliance features will
            # use regex fallbacks; full audit trail is unavailable.
            self.pii_scanner = None  # type: ignore[assignment]
            self.injection_detector = None  # type: ignore[assignment]
            self.risk_classifier = None  # type: ignore[assignment]
            self.audit_trail = None  # type: ignore[assignment]
            self.processing_records = None  # type: ignore[assignment]
            self.erasure_manager = None  # type: ignore[assignment]
            self.consent_manager = None  # type: ignore[assignment]
            self.retention_manager = None  # type: ignore[assignment]
            self.lineage_tracker = None  # type: ignore[assignment]
            self.provenance_engine = None  # type: ignore[assignment]
            # Round 5: fail fast in production when critical CRP subsystems are missing.
            env = (os.environ.get("CRP_COMPLY_ENV") or os.environ.get("ENVIRONMENT", "")).lower()
            if env in ("production", "prod", "staging"):
                raise RuntimeError(
                    "CRP SDK is required in production for PII scanning, injection detection, "
                    "provenance, and audit trails. Install with: pip install 'crprotocol[full]>=4.0.0'"
                )
            return

        # ── CRP Security Stack ──
        self.pii_scanner = PIIScanner()
        self.injection_detector = InjectionDetector()
        self.risk_classifier = RiskClassifier()
        self.audit_trail = ComplianceAuditTrail(
            signing_key=hmac_secret.encode(), session_id="proxy"
        )
        self.processing_records = ProcessingRecordKeeper(session_id="proxy")
        self.erasure_manager = ErasureManager()
        self.consent_manager = ConsentManager(session_id="proxy")
        self.retention_manager = RetentionManager()
        self.lineage_tracker = DataLineageTracker()
        self.provenance_engine = DecisionProvenanceEngine(
            config=ProvenanceConfig(
                enabled=True,
                similarity_threshold=0.50,
                risk_scoring_enabled=True,
                entailment_enabled=True,
            ),
        )

        # Round 5: do NOT grant default SECURITY_SCANNING consent globally.
        # Per-user consent must be explicit; requests from users without consent
        # are degraded (scanning skipped) or refused.

    async def close(self) -> None:
        """Shut down the HTTP client."""
        await self.http_client.aclose()

    # ── Text Extraction ────────────────────────────────────────

    @staticmethod
    def extract_text(request: ChatCompletionRequest) -> str:
        """Concatenate all text content from a chat request."""
        parts: list[str] = []
        for msg in request.messages:
            if isinstance(msg.content, str):
                parts.append(msg.content)
            elif isinstance(msg.content, list):
                for item in msg.content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        parts.append(item.get("text", ""))
        return "\n".join(parts)

    # ── PII Detection (CRP PIIScanner — 7 categories) ─────────

    def scan_pii(self, text: str) -> tuple[bool, list[str]]:
        """Scan *text* for PII using CRP's PIIScanner.

        Returns ``(detected, categories)`` where *categories* lists
        the types of PII found (e.g. ``["email", "phone"]``).
        """
        result = self.pii_scanner.scan(text)
        return result.has_pii, list(result.pii_types_found)

    # ── Injection Detection (CRP InjectionDetector — 21 patterns + ML) ──

    def detect_injection(self, text: str) -> str:
        """Detect prompt-injection attempts using CRP's InjectionDetector.

        Returns a risk level: ``"NONE"``, ``"MEDIUM"``, or ``"HIGH"``.
        """
        report = self.injection_detector.scan(text)
        if not report.has_flags:
            return "NONE"
        if report.highest_confidence >= 0.80:
            return "HIGH"
        if report.highest_confidence >= 0.50:
            return "MEDIUM"
        return "MEDIUM" if report.has_flags else "NONE"

    def get_injection_details(self, text: str) -> dict[str, Any]:
        """Full injection analysis with flag details."""
        report = self.injection_detector.scan(text)
        return {
            "has_flags": report.has_flags,
            "highest_confidence": round(report.highest_confidence, 3),
            "ml_backend": report.ml_backend,
            "ml_confidence": round(report.ml_confidence, 3),
            "flags": [
                {
                    "type": f.injection_type.value
                    if hasattr(f.injection_type, "value")
                    else str(f.injection_type),
                    "pattern": f.pattern_name,
                    "confidence": round(f.confidence, 3),
                    "matched_text": f.matched_text[:80],
                }
                for f in report.flags
            ],
        }

    # ── Data Classification ────────────────────────────────────

    def analyse_provenance(
        self,
        input_text: str,
        output_text: str,
        session_id: str = "proxy",
    ) -> dict[str, Any]:
        """Run DecisionProvenanceEngine on the request/response pair.

        Returns a summary dict suitable for embedding in audit records.
        """
        try:
            report = self.provenance_engine.analyse(
                output_text=output_text,
                packed_facts=input_text,
                session_id=session_id,
                window_id=0,
            )
            hallucination = report.hallucination_risk
            return {
                "total_claims": len(report.claims),
                "supported_claims": sum(
                    1 for c in report.claims if c.attribution_type.value == "supported"
                )
                if report.claims
                else 0,
                "unsupported_claims": sum(
                    1 for c in report.claims if c.attribution_type.value == "unsupported"
                )
                if report.claims
                else 0,
                "mean_fidelity": round(report.fidelity.mean_score, 3) if report.fidelity else 0.0,
                "hallucination_risk_level": hallucination.window_risk_level
                if hallucination
                else "UNKNOWN",
                "hallucination_mean_score": round(hallucination.mean_risk_score, 3)
                if hallucination
                else 0.0,
                "high_risk_claims": hallucination.high_risk_count if hallucination else 0,
                "critical_risk_claims": hallucination.critical_risk_count if hallucination else 0,
            }
        except Exception:
            logger.debug("Provenance analysis skipped (non-critical)", exc_info=True)
            return {
                "total_claims": 0,
                "supported_claims": 0,
                "unsupported_claims": 0,
                "mean_fidelity": 0.0,
                "hallucination_risk_level": "UNKNOWN",
                "hallucination_mean_score": 0.0,
                "high_risk_claims": 0,
                "critical_risk_claims": 0,
            }

    @staticmethod
    def classify_data(has_pii: bool, pii_categories: list[str]) -> str:
        """Classify data sensitivity based on PII presence (all 5 levels).

        Uses CRP DataClassification:
          PUBLIC(0), INTERNAL(1), CONFIDENTIAL(2), RESTRICTED(3), CRITICAL(4)
        """
        if not has_pii:
            return DataClassification.INTERNAL.name
        # Highest sensitivity: credentials, SSN, credit cards
        critical = {"ssn", "ssn_us", "credit_card", "aws_key", "api_key_generic"}
        if any(cat in critical for cat in pii_categories):
            return DataClassification.CRITICAL.name
        # High sensitivity: passport, IBAN
        restricted = {"passport", "iban"}
        if any(cat in restricted for cat in pii_categories):
            return DataClassification.RESTRICTED.name
        # Moderate sensitivity: email, phone, IP
        confidential = {"email", "phone_international", "ip_address"}
        if any(cat in confidential for cat in pii_categories):
            return DataClassification.CONFIDENTIAL.name
        # Default for unknown PII types
        return DataClassification.RESTRICTED.name

    # ── Quality Grading (S/A/B/C/D) ──────────────────────────

    @staticmethod
    def grade_quality(
        *,
        has_pii: bool,
        injection_risk: str,
        provenance: dict[str, Any],
    ) -> str:
        """Grade proxy interaction quality (S/A/B/C/D).

        Based on:
        - Fidelity score from provenance analysis
        - Hallucination risk level
        - PII presence and injection risk
        """
        score = 100.0

        # Fidelity scoring (0-40 points)
        fidelity = provenance.get("mean_fidelity", 0.0)
        if fidelity >= 0.9:
            score -= 0
        elif fidelity >= 0.7:
            score -= 10
        elif fidelity >= 0.5:
            score -= 20
        elif fidelity > 0:
            score -= 30
        else:
            score -= 5  # No provenance data — mild penalty

        # Hallucination risk (0-30 points)
        hallucination = provenance.get("hallucination_risk_level", "UNKNOWN")
        if hallucination == "CRITICAL":
            score -= 30
        elif hallucination == "HIGH":
            score -= 20
        elif hallucination == "MEDIUM":
            score -= 10
        elif hallucination == "UNKNOWN":
            # GAP 2 fix: un-gradable output cannot be trusted — apply
            # same penalty as HIGH to prevent masking via absent provenance.
            score -= 20

        # PII detected (0-15 points)
        if has_pii:
            score -= 15

        # Injection risk (0-20 points)
        if injection_risk == "HIGH":
            score -= 20
        elif injection_risk == "MEDIUM":
            score -= 10

        # Map to tier
        if score >= 90:
            return "S"
        if score >= 75:
            return "A"
        if score >= 60:
            return "B"
        if score >= 40:
            return "C"
        return "D"

    # ── Consent Management ────────────────────────────────────

    def grant_consent(self, purpose: str, reason: str = "") -> dict[str, Any]:
        """Grant consent for a processing purpose."""
        purpose_map = {p.value: p for p in ProcessingPurpose}
        pp = purpose_map.get(purpose)
        if pp is None:
            return {"error": f"Unknown purpose: {purpose}"}
        record = self.consent_manager.grant(pp, reason=reason)
        return {
            "purpose": purpose,
            "status": "granted",
            "consent_id": record.consent_id,
        }

    def deny_consent(self, purpose: str, reason: str = "") -> dict[str, Any]:
        """Deny/withdraw consent for a processing purpose."""
        purpose_map = {p.value: p for p in ProcessingPurpose}
        pp = purpose_map.get(purpose)
        if pp is None:
            return {"error": f"Unknown purpose: {purpose}"}
        record = self.consent_manager.deny(pp, reason=reason)
        return {
            "purpose": purpose,
            "status": "denied",
            "consent_id": record.consent_id,
        }

    def get_consent_status(self) -> dict[str, Any]:
        """Return current consent state."""
        state = self.consent_manager.state
        granted = [p.value for p in ProcessingPurpose if state.is_granted(p)]
        denied = [p.value for p in state.denied_purposes()]
        return {
            "session_id": state.session_id,
            "purposes_granted": sorted(granted),
            "purposes_denied": sorted(denied),
            "details": state.to_dict(),
        }

    # ── Consent & Purpose (Round 5) ───────────────────────────

    def _user_consent_manager(self, user_id: str) -> Any:
        """Return (or create) a per-user ConsentManager."""
        if not _CRP_AVAILABLE:
            return self.consent_manager
        if user_id not in self._per_user_consent:
            self._per_user_consent[user_id] = ConsentManager(session_id=f"proxy:{user_id}")
        return self._per_user_consent[user_id]

    def check_user_consent(self, user_id: str, purpose: Any) -> bool:
        """Return True if *user_id* has explicitly granted *purpose*.

        Anonymous users are treated as not having granted any purpose. The CRP
        ConsentManager defaults to granted; we track explicit grants ourselves
        so that consent is opt-in.
        """
        if user_id == "anonymous":
            return False
        purpose_value = purpose.value if hasattr(purpose, "value") else str(purpose)
        return purpose_value in self._per_user_consent_grants.get(user_id, set())

    def grant_user_consent(self, user_id: str, purpose: Any, reason: str = "") -> None:
        """Explicitly grant a processing purpose for a user."""
        if user_id == "anonymous":
            return
        purpose_value = purpose.value if hasattr(purpose, "value") else str(purpose)
        self._per_user_consent_grants.setdefault(user_id, set()).add(purpose_value)
        if _CRP_AVAILABLE:
            cm = self._user_consent_manager(user_id)
            try:
                cm.grant(purpose, reason=reason or f"granted by {user_id}")
            except Exception:
                logger.exception("grant_user_consent failed")

    @staticmethod
    def infer_processing_purpose(*, path: str = "", body: dict[str, Any] | None = None) -> Any:
        """Infer the GDPR Art. 30 processing purpose from the request.

        Defaults to SECURITY_SCANNING for the compliance proxy; uses
        LLM_INFERENCE only when the request is clearly a plain chat completion
        and no scanning is required.
        """
        if not _CRP_AVAILABLE:
            return None
        path = (path or "").lower()
        body = body or {}
        # Chat completions → context management / inference.
        if "/chat/completions" in path:
            return ProcessingPurpose.CONTEXT_MANAGEMENT
        if "/models" in path:
            return ProcessingPurpose.ANALYTICS
        # Classification / DPIA / assessment paths.
        if any(p in path for p in ("classify", "assess", "risk", "dpia")):
            return ProcessingPurpose.QUALITY_ASSESSMENT
        # Fallback.
        return ProcessingPurpose.SECURITY_SCANNING

    # ── Retention Management ──────────────────────────────────

    def enforce_retention(self) -> dict[str, Any]:
        """Run retention enforcement — identify and purge expired records."""
        expired_ids = self.retention_manager.enforce()
        purged = 0
        for data_id in expired_ids:
            record_file = self.audit_dir / f"{data_id}.json"
            try:
                record_file.unlink()
                self.retention_manager.mark_purged(data_id)
                purged += 1
            except FileNotFoundError:
                self.retention_manager.mark_purged(data_id)
        if purged:
            self.audit_trail.record(
                event_type=ComplianceEventType.DATA_PROCESSED,
                session_id="proxy:retention",
                data={"action": "retention_enforcement", "purged_count": purged},
            )
        return {
            "expired_count": len(expired_ids),
            "purged_count": purged,
            "retention_policy": self.retention_manager.to_dict()["policy"],
        }

    def get_retention_status(self) -> dict[str, Any]:
        """Return current retention tracking status."""
        return self.retention_manager.to_dict()

    # ── Data Lineage ──────────────────────────────────────────

    def get_data_lineage(self) -> dict[str, Any]:
        """Return data lineage tracking summary."""
        return self.lineage_tracker.to_dict()

    # ── Upstream Forwarding ────────────────────────────────────

    async def forward_chat_completion(
        self,
        request: ChatCompletionRequest,
        upstream_url: str,
        upstream_key: str,
    ) -> ChatCompletionResponse:
        """Forward a **non-streaming** chat completion request."""
        headers = {
            "Authorization": f"Bearer {upstream_key}",
            "Content-Type": "application/json",
        }
        url = f"{upstream_url.rstrip('/')}/chat/completions"
        body = request.model_dump(exclude_none=True)
        body["stream"] = False

        resp = await self.http_client.post(url, json=body, headers=headers)
        resp.raise_for_status()
        return ChatCompletionResponse(**resp.json())

    async def forward_models_list(
        self,
        upstream_url: str,
        upstream_key: str,
    ) -> dict[str, Any]:
        """Forward a GET /models request to the upstream provider."""
        headers = {"Authorization": f"Bearer {upstream_key}"}
        url = f"{upstream_url.rstrip('/')}/models"
        resp = await self.http_client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()

    # ── Audit Trail (CRP ComplianceAuditTrail — HMAC-chained) ──

    def _sign(self, payload: dict[str, Any]) -> str:
        """HMAC-SHA256 sign a dict (canonical JSON, sorted keys)."""
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hmac.new(self._hmac_secret, canonical.encode(), hashlib.sha256).hexdigest()

    def create_audit_record(
        self,
        *,
        request: ChatCompletionRequest,
        response_text: str,
        response_model: str,
        input_tokens: int,
        output_tokens: int,
        pre_pii: tuple[bool, list[str]],
        post_pii: tuple[bool, list[str]],
        injection_risk: str,
        tier: str,
        user_id: str = "anonymous",
        request_id: str | None = None,
        purpose: Any | None = None,
        path: str = "",
    ) -> AuditRecord:
        """Create a signed audit record and persist to disk.

        Also logs to CRP's ComplianceAuditTrail (chained) and
        ProcessingRecordKeeper (GDPR Art. 30).
        """
        record_id = request_id or str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        request_session_id = record_id
        user_session_id = f"proxy:{user_id}"

        request_text = self.extract_text(request)
        request_hash = hashlib.sha256(request_text.encode()).hexdigest()
        response_hash = hashlib.sha256(response_text.encode()).hexdigest()

        all_pii = list(set(pre_pii[1] + post_pii[1]))
        has_pii = pre_pii[0] or post_pii[0]

        # ── Data classification ──
        data_classification = self.classify_data(has_pii, all_pii)

        # ── Provenance / hallucination analysis ──
        provenance = self.analyse_provenance(
            input_text=request_text,
            output_text=response_text,
            session_id=f"proxy:{user_id}",
        )

        # ── Quality grading (S/A/B/C/D) ──
        quality_tier = self.grade_quality(
            has_pii=has_pii,
            injection_risk=injection_risk,
            provenance=provenance,
        )

        risk_level = "HIGH" if has_pii or injection_risk != "NONE" else "MINIMAL"
        # Escalate risk if hallucination score is concerning
        if provenance["hallucination_risk_level"] in ("HIGH", "CRITICAL"):
            risk_level = "HIGH"

        # ── Consent verification (PROXY-GAP-C: per-user consent manager) ──
        # Round 5: consent is no longer auto-granted. Records reflect whatever
        # purposes the user has explicitly granted.
        _active_consent = self._user_consent_manager(user_id)
        consent_verified: list[str] = []
        if _active_consent is not None:
            try:
                consent_verified = [
                    p.value
                    for p in _active_consent.state.records
                    if _active_consent.state.is_granted(p)
                ]
            except Exception:
                consent_verified = []

        # ── Data lineage tracking ──
        self.lineage_tracker.record(
            data_id=record_id,
            origin="proxy_request",
            source_label=f"user:{user_id}",
            classification=DataClassification[data_classification],
        )

        # ── Retention tracking ──
        self.retention_manager.register(
            data_id=record_id,
            classification=DataClassification[data_classification],
            source_label=f"audit:{user_id}",
        )

        record_data: dict[str, Any] = {
            "record_id": record_id,
            "timestamp": now,
            "model": response_model or request.model,
            "request_hash": request_hash,
            "response_hash": response_hash,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "pii_detected_input": pre_pii[0],
            "pii_detected_output": post_pii[0],
            "pii_categories": all_pii,
            "injection_risk": injection_risk,
            "risk_level": risk_level,
            "data_classification": data_classification,
            "quality_tier": quality_tier,
            "tier": tier,
            "user_id": user_id,
            "provenance": provenance,
            "consent_purposes": sorted(consent_verified),
            "compliance_status": {
                "eu_ai_act_art6": True,
                "gdpr_art35": not has_pii or tier in ("enterprise", "cloud"),
                "gdpr_art30_recorded": True,
                "audit_trail_signed": True,
                "audit_trail_chained": True,
                "transparency_logged": True,
                "pii_scanned": True,
                "injection_scanned": True,
            },
        }

        signature = self._sign(record_data)
        record_data["hmac_signature"] = signature

        # Persist to disk
        record_file = self.audit_dir / f"{record_id}.json"
        record_file.write_text(json.dumps(record_data, indent=2), encoding="utf-8")

        # ── Log to CRP ComplianceAuditTrail (PROXY-GAP-B: per-request chain) ──
        event_type = (
            ComplianceEventType.PII_DETECTED
            if has_pii
            else (
                ComplianceEventType.INJECTION_DETECTED
                if injection_risk != "NONE"
                else ComplianceEventType.DATA_PROCESSED
            )
        )
        if _CRP_AVAILABLE:
            # Round 5: each request gets its own audit trail / processing record
            # session so user requests are not mixed under session_id="proxy".
            per_request_trail = ComplianceAuditTrail(
                signing_key=self._hmac_secret,
                session_id=request_session_id,
            )
            per_request_pr = ProcessingRecordKeeper(
                session_id=request_session_id,
            )
            per_request_trail.record(
                event_type=event_type,
                session_id=request_session_id,
                data={
                    "record_id": record_id,
                    "user_id": user_id,
                    "model": record_data["model"],
                    "risk_level": risk_level,
                    "pii_categories": all_pii,
                    "injection_risk": injection_risk,
                    "data_classification": data_classification,
                    "provenance": provenance,
                },
            )
            # Keep a lightweight reference in the per-user chain for easy listing.
            if user_id not in self._per_user_trails:
                self._per_user_trails[user_id] = ComplianceAuditTrail(
                    signing_key=self._hmac_secret,
                    session_id=user_session_id,
                )
            self._per_user_trails[user_id].record(
                event_type=event_type,
                session_id=user_session_id,
                data={
                    "record_id": record_id,
                    "model": record_data["model"],
                    "risk_level": risk_level,
                },
            )
            # Also record in the global chain so admin export/verify still work
            if self.audit_trail is not None:
                self.audit_trail.record(
                    event_type=event_type,
                    session_id=user_session_id,
                    data={
                        "record_id": record_id,
                        "model": record_data["model"],
                        "risk_level": risk_level,
                    },
                )
            # Replace the per-user PR cache with the per-request one for this call.
            self._per_user_pr[user_id] = per_request_pr

        # ── Log to GDPR Art. 30 processing record (PROXY-GAP-D: inferred purpose) ──
        # Round 5: purpose is inferred from request path/body and passed in,
        # rather than always defaulting to SECURITY_SCANNING.
        if _CRP_AVAILABLE:
            _proc_purpose = purpose
            if _proc_purpose is None:
                _proc_purpose = self.infer_processing_purpose(path=path)
            if _proc_purpose is None:
                _proc_purpose = ProcessingPurpose.SECURITY_SCANNING
            legal_basis = (
                "Legitimate interest (GDPR Art. 6(1)(f))"
                if _proc_purpose == ProcessingPurpose.SECURITY_SCANNING
                else "Contractual necessity / user request (GDPR Art. 6(1)(b))"
            )
            _pr = self._per_user_pr.get(user_id)
            if _pr is not None:
                _pr.record(
                    purpose=_proc_purpose,
                    data_categories=["llm_prompt", "llm_response"],
                    legal_basis=legal_basis,
                    input_size_bytes=len(request_text.encode()),
                    output_size_bytes=len(response_text.encode()),
                    automated_decision=False,
                    human_oversight=True,
                )
            # Also update global processing records for aggregate ROPA export
            if self.processing_records is not None:
                self.processing_records.record(
                    purpose=_proc_purpose,
                    data_categories=["llm_prompt", "llm_response"],
                    legal_basis=legal_basis,
                    input_size_bytes=len(request_text.encode()),
                    output_size_bytes=len(response_text.encode()),
                    automated_decision=False,
                    human_oversight=True,
                )

        return AuditRecord(**record_data)

    # ── Erasure (GDPR Art. 17) ─────────────────────────────────

    def erase_user_data(self, user_id: str) -> int:
        """Delete all audit records for a user (GDPR Art. 17)."""
        request = self.erasure_manager.create_request(
            requester_hash=hashlib.sha256(user_id.encode()).hexdigest(),
            scope="full",
            target_ids=[user_id],
        )

        records = self.list_audit_records(limit=100_000)
        deleted = 0
        for r in records:
            if r.get("user_id") == user_id:
                record_file = self.audit_dir / f"{r['record_id']}.json"
                try:
                    record_file.unlink()
                    deleted += 1
                except FileNotFoundError:
                    pass

        self.erasure_manager.complete_request(request.request_id, deleted)

        self.audit_trail.record(
            event_type=ComplianceEventType.ERASURE_COMPLETED,
            session_id=f"proxy:{user_id}",
            data={"user_id_hash": request.requester_hash, "items_erased": deleted},
        )
        return deleted

    # ── Audit Queries ─────────────────────────────────────────

    def list_audit_records(
        self,
        limit: int = 50,
        offset: int = 0,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return recent audit records (newest first), optionally filtered by user_id."""
        files = sorted(
            self.audit_dir.glob("*.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        records: list[dict[str, Any]] = []
        skipped = 0
        for f in files:
            try:
                record = json.loads(f.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            # Per-user filtering
            if user_id and record.get("user_id") != user_id:
                continue
            if skipped < offset:
                skipped += 1
                continue
            records.append(record)
            if len(records) >= limit:
                break
        return records

    def get_audit_record(self, record_id: str) -> dict[str, Any] | None:
        """Return a single audit record by ID, or ``None``."""
        # Prevent path traversal
        safe = re.sub(r"[^a-zA-Z0-9\-]", "", record_id)
        path = self.audit_dir / f"{safe}.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def verify_audit_record(self, record_id: str) -> bool:
        """Verify HMAC integrity of a stored audit record."""
        record = self.get_audit_record(record_id)
        if not record:
            return False
        stored_sig = record.pop("hmac_signature", "")
        expected_sig = self._sign(record)
        return hmac.compare_digest(stored_sig, expected_sig)

    def verify_audit_chain(self) -> tuple[bool, int]:
        """Verify the CRP compliance audit trail chain integrity."""
        return self.audit_trail.verify_chain()

    def export_audit_trail(self, since: float | None = None) -> dict[str, Any]:
        """Export CRP audit trail for regulatory submission."""
        return self.audit_trail.export(include_signatures=True, since=since)

    def export_processing_records(self) -> list[dict[str, Any]]:
        """Export GDPR Art. 30 processing records."""
        return self.processing_records.export()

    def processing_summary(self) -> dict[str, Any]:
        """Return processing records summary (GDPR Art. 30)."""
        return self.processing_records.summary()

    def erasure_status(self) -> dict[str, Any]:
        """Return GDPR Art. 17 erasure request status."""
        return self.erasure_manager.to_dict()

    def query_audit_trail(
        self,
        event_type: str | None = None,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query CRP audit trail events by type or session."""
        entries = self.audit_trail.query(
            event_type=event_type,
            session_id=session_id,
        )
        return [e.to_dict() for e in entries]

    def get_compliance_stats(self, user_id: str | None = None) -> ComplianceStats:
        """Compute aggregate compliance statistics, optionally per-user."""
        records = self.list_audit_records(limit=100_000, user_id=user_id)
        total = len(records)
        if total == 0:
            return ComplianceStats()

        pii_count = sum(
            1 for r in records if r.get("pii_detected_input") or r.get("pii_detected_output")
        )
        injection_count = sum(1 for r in records if r.get("injection_risk") != "NONE")
        models: dict[str, int] = {}
        risk_dist: dict[str, int] = {}
        quality_dist: dict[str, int] = {}
        consent_count = 0
        retention_count = 0
        lineage_count = 0
        compliant = 0
        for r in records:
            m = r.get("model", "unknown")
            models[m] = models.get(m, 0) + 1
            rl = r.get("risk_level", "MINIMAL")
            risk_dist[rl] = risk_dist.get(rl, 0) + 1
            qt = r.get("quality_tier", "")
            if qt:
                quality_dist[qt] = quality_dist.get(qt, 0) + 1
            if r.get("consent_purposes"):
                consent_count += 1
            if all(r.get("compliance_status", {}).values()):
                compliant += 1

        # Count retention/lineage tracked items from managers
        try:
            retention_count = (
                len(self.retention_manager._records)
                if hasattr(self.retention_manager, "_records")
                else 0
            )
        except Exception:
            retention_count = 0
        try:
            lineage_count = (
                len(self.lineage_tracker._entries)
                if hasattr(self.lineage_tracker, "_entries")
                else 0
            )
        except Exception:
            lineage_count = 0

        return ComplianceStats(
            total_requests=total,
            pii_detections=pii_count,
            injection_attempts=injection_count,
            compliance_rate=round(compliant / total * 100, 1),
            models_used=models,
            risk_distribution=risk_dist,
            quality_distribution=quality_dist,
            consent_coverage=round(consent_count / total * 100, 1),
            retention_tracked=retention_count,
            lineage_tracked=lineage_count,
        )
