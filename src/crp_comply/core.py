# Copyright © 2025 Constantinos Vidiniotis. All rights reserved.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""CRP Comply — AI Governance & EU AI Act Compliance Platform.

Provides protocol-level AI governance that makes compliance structurally
impossible to skip.  Every LLM call is automatically classified by risk
level, PII-scanned, provenance-tracked, quality-assessed, and written to
a tamper-evident HMAC-SHA256 audit trail.

Usage::

    from crp_comply import CRPComply

    comply = CRPComply()

    # Risk assessment
    assessment = comply.assess_risk(
        category="healthcare",
        processes_personal_data=True,
        makes_automated_decisions=True,
    )

    # Generate compliance report
    report = comply.compliance_report()

    # Generate DPIA
    dpia = comply.generate_dpia(
        system_name="Patient Triage AI",
        data_subjects="patients",
        processing_description="AI-assisted triage and priority scoring",
    )

    # Full conformity evidence pack
    pack = comply.conformity_evidence_pack(system_name="My AI System")

EU AI Act: Art. 6-17 (full high-risk compliance)
ISO 42001: A.6.2 (AI-specific controls)
GDPR: Art. 5-7, 9, 17, 22, 30, 35
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("crp_comply")


# ---------------------------------------------------------------------------
# DPIA (Data Protection Impact Assessment) — GDPR Art. 35
# ---------------------------------------------------------------------------


@dataclass
class DPIAReport:
    """Data Protection Impact Assessment report (GDPR Art. 35)."""

    dpia_id: str
    generated_at: float
    system_name: str
    system_version: str
    controller: str
    dpo_contact: str
    processing_description: str
    data_subjects: str
    data_categories: list[str]
    legal_basis: str
    necessity_assessment: str
    risk_assessment: dict[str, Any]
    mitigation_measures: list[str]
    residual_risks: list[str]
    consultation_required: bool
    review_schedule: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_type": "dpia",
            "dpia_id": self.dpia_id,
            "generated_at": self.generated_at,
            "framework": "GDPR Article 35",
            "system_name": self.system_name,
            "system_version": self.system_version,
            "controller": self.controller,
            "dpo_contact": self.dpo_contact,
            "processing_description": self.processing_description,
            "data_subjects": self.data_subjects,
            "data_categories": self.data_categories,
            "legal_basis": self.legal_basis,
            "necessity_assessment": self.necessity_assessment,
            "risk_assessment": self.risk_assessment,
            "mitigation_measures": self.mitigation_measures,
            "residual_risks": self.residual_risks,
            "consultation_required": self.consultation_required,
            "review_schedule": self.review_schedule,
        }

    def to_markdown(self) -> str:
        """Render as Markdown for human-readable output."""
        lines = [
            "# Data Protection Impact Assessment (DPIA)",
            "",
            f"**DPIA ID:** {self.dpia_id}  ",
            "**Framework:** GDPR Article 35  ",
            f"**Generated:** {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(self.generated_at))}  ",
            "",
            "---",
            "",
            "## 1. System Description",
            "",
            "| Field | Value |",
            "|---|---|",
            f"| **System** | {self.system_name} |",
            f"| **Version** | {self.system_version} |",
            f"| **Controller** | {self.controller} |",
            f"| **DPO Contact** | {self.dpo_contact} |",
            "",
            "## 2. Processing Description",
            "",
            f"{self.processing_description}",
            "",
            "## 3. Data Subjects & Categories",
            "",
            f"**Data Subjects:** {self.data_subjects}",
            "",
            "**Data Categories:**",
        ]
        for cat in self.data_categories:
            lines.append(f"- {cat}")
        lines.extend(
            [
                "",
                "## 4. Legal Basis",
                "",
                f"{self.legal_basis}",
                "",
                "## 5. Necessity & Proportionality Assessment",
                "",
                f"{self.necessity_assessment}",
                "",
                "## 6. Risk Assessment",
                "",
            ]
        )
        for risk_type, details in self.risk_assessment.items():
            lines.append(f"### {risk_type}")
            if isinstance(details, dict):
                lines.append(f"- **Likelihood:** {details.get('likelihood', 'N/A')}")
                lines.append(f"- **Severity:** {details.get('severity', 'N/A')}")
                lines.append(f"- **Risk Level:** {details.get('risk_level', 'N/A')}")
                lines.append(f"- **Description:** {details.get('description', 'N/A')}")
            lines.append("")
        lines.extend(
            [
                "## 7. Mitigation Measures (CRP Native)",
                "",
            ]
        )
        for i, m in enumerate(self.mitigation_measures, 1):
            lines.append(f"{i}. {m}")
        lines.extend(
            [
                "",
                "## 8. Residual Risks",
                "",
            ]
        )
        for r in self.residual_risks:
            lines.append(f"- ⚠ {r}")
        lines.extend(
            [
                "",
                "## 9. Supervisory Authority Consultation",
                "",
                f"{'**Required** — residual risks remain HIGH after mitigation.' if self.consultation_required else 'Not required — risks adequately mitigated.'}",
                "",
                "## 10. Review Schedule",
                "",
                f"{self.review_schedule}",
                "",
                "---",
                "*Generated by CRP Comply — crprotocol.io*",
            ]
        )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Session Audit Report
# ---------------------------------------------------------------------------


@dataclass
class SessionAuditReport:
    """Per-session compliance audit report."""

    report_id: str
    session_id: str
    generated_at: float
    risk_level: str
    dispatches_audited: int
    pii_detections: int
    injection_attempts: int
    quality_tiers: dict[str, int]
    audit_trail_entries: int
    audit_trail_intact: bool
    compliance_score: float
    findings: list[dict[str, str]]
    recommendations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_type": "session_audit",
            "report_id": self.report_id,
            "session_id": self.session_id,
            "generated_at": self.generated_at,
            "risk_level": self.risk_level,
            "dispatches_audited": self.dispatches_audited,
            "pii_detections": self.pii_detections,
            "injection_attempts": self.injection_attempts,
            "quality_tiers": self.quality_tiers,
            "audit_trail_entries": self.audit_trail_entries,
            "audit_trail_intact": self.audit_trail_intact,
            "compliance_score": self.compliance_score,
            "findings": self.findings,
            "recommendations": self.recommendations,
        }

    def to_markdown(self) -> str:
        """Render as Markdown."""
        score_emoji = (
            "✅" if self.compliance_score >= 90 else ("⚠️" if self.compliance_score >= 70 else "❌")
        )
        lines = [
            "# CRP Comply — Session Audit Report",
            "",
            f"**Report ID:** {self.report_id}  ",
            f"**Session:** {self.session_id}  ",
            f"**Generated:** {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(self.generated_at))}  ",
            f"**Compliance Score:** {score_emoji} {self.compliance_score:.1f}%  ",
            "",
            "---",
            "",
            "## Summary",
            "",
            "| Metric | Value |",
            "|---|---|",
            f"| Risk Level | {self.risk_level} |",
            f"| Dispatches Audited | {self.dispatches_audited} |",
            f"| PII Detections | {self.pii_detections} |",
            f"| Injection Attempts | {self.injection_attempts} |",
            f"| Audit Trail Entries | {self.audit_trail_entries} |",
            f"| Audit Trail Integrity | {'✅ Intact' if self.audit_trail_intact else '❌ TAMPERED'} |",
            "",
            "## Quality Distribution",
            "",
            "| Tier | Count |",
            "|---|---|",
        ]
        for tier in ["S", "A", "B", "C", "D"]:
            count = self.quality_tiers.get(tier, 0)
            lines.append(f"| {tier} | {count} |")
        lines.extend(
            [
                "",
                "## Findings",
                "",
            ]
        )
        if self.findings:
            for f in self.findings:
                severity = f.get("severity", "INFO")
                icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢", "INFO": "ℹ️"}.get(severity, "ℹ️")
                lines.append(f"- {icon} **[{severity}]** {f.get('description', '')}")
        else:
            lines.append("No findings — all governance controls operating normally.")
        lines.extend(
            [
                "",
                "## Recommendations",
                "",
            ]
        )
        for r in self.recommendations:
            lines.append(f"- {r}")
        lines.extend(
            [
                "",
                "---",
                "*Generated by CRP Comply — crprotocol.io*",
            ]
        )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# CRP Comply — Main Product Class
# ---------------------------------------------------------------------------


class CRPComply:
    """CRP Comply — AI Governance & EU AI Act Compliance Platform.

    Wraps CRP's protocol-level governance features into a coherent
    compliance product with report generation, risk assessment,
    DPIA generation, and audit trail export.

    Usage::

        from crp_comply import CRPComply

        comply = CRPComply()

        # Quick compliance check
        report = comply.compliance_report()
        print(f"Score: {report['summary']['compliance_score']}%")

        # Risk assessment for your AI system
        assessment = comply.assess_risk(category="healthcare")
        print(f"Risk: {assessment.risk_level.value}")

        # DPIA for regulators
        dpia = comply.generate_dpia(
            system_name="Patient Triage AI",
            data_subjects="patients",
        )
        print(dpia.to_markdown())
    """

    def __init__(
        self,
        controller: str = "AutoCyber AI Pty Ltd",
        dpo_contact: str = "contact@crprotocol.io",
    ) -> None:
        self._controller = controller
        self._dpo_contact = dpo_contact
        self._reporter = self._build_reporter()
        self._classifier = self._build_classifier()

    @staticmethod
    def _build_reporter():
        from crp.security.compliance import ComplianceReporter

        return ComplianceReporter()

    @staticmethod
    def _build_classifier():
        from crp.security.compliance import RiskClassifier

        return RiskClassifier()

    # ── Risk Assessment ─────────────────────────────────────────────

    def assess_risk(
        self,
        category: str = "context_management",
        intended_purpose: str = "",
        processes_personal_data: bool = False,
        makes_automated_decisions: bool = False,
        affects_fundamental_rights: bool = False,
        safety_critical: bool = False,
        profiles_individuals: bool = False,
    ):
        """Run EU AI Act risk assessment (Art. 6).

        Returns a RiskAssessment with classification, mitigations,
        and residual risks.
        """
        from crp.security.compliance import AISystemCategory

        cat_map = {c.value: c for c in AISystemCategory}
        system_cat = cat_map.get(category, AISystemCategory.CONTEXT_MANAGEMENT)

        return self._classifier.assess(
            category=system_cat,
            intended_purpose=intended_purpose,
            processes_personal_data=processes_personal_data,
            makes_automated_decisions=makes_automated_decisions,
            affects_fundamental_rights=affects_fundamental_rights,
            safety_critical=safety_critical,
            profiles_individuals=profiles_individuals,
        )

    # ── Compliance Report ───────────────────────────────────────────

    def compliance_report(
        self,
        session_stats: dict[str, Any] | None = None,
        risk_assessment=None,
    ) -> dict[str, Any]:
        """Generate EU AI Act + ISO 42001 compliance status report.

        Returns structured JSON with per-control implementation status,
        evidence links, and overall compliance score.
        """
        return self._reporter.generate_report(
            session_stats=session_stats,
            risk_assessment=risk_assessment,
        )

    def compliance_report_markdown(
        self,
        session_stats: dict[str, Any] | None = None,
        risk_assessment=None,
    ) -> str:
        """Generate compliance report as formatted Markdown."""
        report = self.compliance_report(session_stats, risk_assessment)

        lines = [
            "# CRP Comply — Compliance Status Report",
            "",
            f"**Generated:** {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(report['generated_at']))}  ",
            f"**Compliance Score:** {report['summary']['compliance_score']}%  ",
            f"**Total Controls:** {report['summary']['total_controls']}  ",
            f"**Implemented:** {report['summary']['implemented']}  ",
            "",
            "---",
            "",
        ]

        for fw_name, fw_data in report["frameworks"].items():
            nice_name = {
                "eu_ai_act": "EU AI Act (2024/1689)",
                "iso_42001": "ISO/IEC 42001:2023",
            }.get(fw_name, fw_name)
            lines.extend(
                [
                    f"## {nice_name}",
                    "",
                    f"**Coverage:** {fw_data['implemented']}/{fw_data['total_controls']} controls ({fw_data['compliance_pct']}%)",
                    "",
                    "| Control | Article | Description | Status | Implementation |",
                    "|---|---|---|---|---|",
                ]
            )
            for c in fw_data["controls"]:
                status_icon = {
                    "implemented": "✅",
                    "partial": "⚠️",
                    "planned": "🔲",
                    "not_applicable": "➖",
                }.get(c["status"], "❓")
                impl_short = (
                    c["implementation"][:80] + "..."
                    if len(c["implementation"]) > 80
                    else c["implementation"]
                )
                lines.append(
                    f"| {c['control_id']} | {c['article']} | {c['description']} | {status_icon} {c['status']} | {impl_short} |"
                )
            lines.append("")

        if risk_assessment:
            ra = risk_assessment if isinstance(risk_assessment, dict) else risk_assessment.to_dict()
            lines.extend(
                [
                    "## Risk Assessment",
                    "",
                    f"- **Risk Level:** {ra.get('risk_level', 'N/A')}",
                    f"- **Category:** {ra.get('system_category', 'N/A')}",
                    f"- **Purpose:** {ra.get('intended_purpose', 'N/A')}",
                    "",
                ]
            )

        lines.extend(
            [
                "---",
                "*Generated by CRP Comply — crprotocol.io*",
            ]
        )
        return "\n".join(lines)

    # ── Technical Documentation (Art. 11) ───────────────────────────

    def technical_documentation(
        self,
        risk_assessment=None,
    ) -> dict[str, Any]:
        """Generate EU AI Act Article 11 technical documentation.

        Structured output suitable for submission to national
        competent authorities during conformity assessment.
        """
        from crp.security.compliance import TransparencyDeclaration

        transparency = TransparencyDeclaration()
        if risk_assessment:
            transparency.risk_level = risk_assessment.risk_level
        return self._reporter.generate_technical_documentation(
            transparency=transparency,
            risk_assessment=risk_assessment,
        )

    # ── Transparency Declaration (Art. 13) ──────────────────────────

    def transparency_declaration(self) -> dict[str, Any]:
        """Generate transparency declaration for AI system users.

        EU AI Act Art. 13 requires providers to ensure high-risk AI
        systems are sufficiently transparent for deployers.
        """
        from crp.security.compliance import TransparencyDeclaration

        return TransparencyDeclaration().to_dict()

    # ── DPIA Generation (GDPR Art. 35) ──────────────────────────────

    def generate_dpia(
        self,
        system_name: str = "CRP-powered AI System",
        data_subjects: str = "end users",
        processing_description: str = "",
        data_categories: list[str] | None = None,
        legal_basis: str = "Legitimate interest (GDPR Art. 6(1)(f))",
        category: str = "context_management",
        processes_personal_data: bool = True,
        makes_automated_decisions: bool = False,
        safety_critical: bool = False,
        profiles_individuals: bool = False,
        affects_fundamental_rights: bool = False,
    ) -> DPIAReport:
        """Generate a Data Protection Impact Assessment (GDPR Art. 35).

        Returns a structured DPIA with risk assessment, mitigation
        measures, and recommendations.  Use ``dpia.to_markdown()``
        for a formatted report.
        """
        # Run risk assessment to inform DPIA
        assessment = self.assess_risk(
            category=category,
            processes_personal_data=processes_personal_data,
            makes_automated_decisions=makes_automated_decisions,
        )

        if data_categories is None:
            data_categories = [
                "Text data provided for AI context management",
                "Extracted facts and knowledge graph relationships",
                "Session metadata (timestamps, quality scores)",
                "Audit trail entries (HMAC-signed governance events)",
            ]
            if processes_personal_data:
                data_categories.append("Potentially personal data within ingested text")

        if not processing_description:
            processing_description = (
                f"The {system_name} uses the Context Relay Protocol (CRP) to manage "
                f"context windows for Large Language Model (LLM) interactions. "
                f"Text provided by {data_subjects} is processed through CRP's "
                f"6-stage extraction pipeline to extract atomic facts. These facts "
                f"are stored in a session-scoped knowledge graph and used to pack "
                f"context envelopes for LLM calls. All processing is logged to a "
                f"tamper-evident HMAC-SHA256 audit trail."
            )

        # Build risk assessment section — dynamic based on ALL input parameters
        risk_assessment_data = {
            "Unauthorized Access to Personal Data": {
                "likelihood": "Medium" if profiles_individuals else "Low",
                "severity": "Critical"
                if (processes_personal_data and affects_fundamental_rights)
                else "High"
                if processes_personal_data
                else "Medium",
                "risk_level": "High"
                if (
                    processes_personal_data and (profiles_individuals or affects_fundamental_rights)
                )
                else "Medium"
                if processes_personal_data
                else "Low",
                "description": (
                    "Risk of unauthorized access to personal data within ingested text. "
                    "CRP mitigates via session-scoped cryptographic isolation, AES-256-GCM "
                    "encryption at rest, RBAC access controls, and automatic session expiry."
                ),
            },
            "Data Retention Beyond Necessity": {
                "likelihood": "Medium" if profiles_individuals else "Low",
                "severity": "High" if affects_fundamental_rights else "Medium",
                "risk_level": "Medium"
                if (profiles_individuals or affects_fundamental_rights)
                else "Low",
                "description": (
                    "Risk of retaining personal data longer than necessary. CRP mitigates "
                    "via classification-based retention policies with automatic expiry, "
                    "session timeout, and right-to-erasure support (GDPR Art. 17)."
                ),
            },
            "Inaccurate AI Output Affecting Data Subjects": {
                "likelihood": "High"
                if (makes_automated_decisions and safety_critical)
                else "Medium"
                if makes_automated_decisions
                else "Low",
                "severity": "Critical"
                if safety_critical
                else "High"
                if (makes_automated_decisions and affects_fundamental_rights)
                else "Medium",
                "risk_level": "Critical"
                if (safety_critical and makes_automated_decisions)
                else "High"
                if makes_automated_decisions
                else "Low",
                "description": (
                    "Risk of LLM generating inaccurate outputs used in decisions affecting "
                    "data subjects. CRP mitigates via quality tier assessment (S/A/B/C/D), "
                    "Decision Provenance Engine (claim-level attribution and hallucination "
                    "risk scoring), and human oversight controls."
                ),
            },
            "PII Leakage in LLM Context": {
                "likelihood": "High"
                if (processes_personal_data and profiles_individuals)
                else "Medium"
                if processes_personal_data
                else "Low",
                "severity": "Critical"
                if (affects_fundamental_rights and processes_personal_data)
                else "High",
                "risk_level": "High"
                if (
                    processes_personal_data and (profiles_individuals or affects_fundamental_rights)
                )
                else "Medium"
                if processes_personal_data
                else "Low",
                "description": (
                    "Risk of personal data in ingested text being included in LLM context "
                    "envelopes. CRP mitigates via PII detection with configurable patterns, "
                    "data classification (5 levels), and anti-poisoning quarantine."
                ),
            },
            "Audit Trail Tampering": {
                "likelihood": "Very Low",
                "severity": "Critical" if safety_critical else "High",
                "risk_level": "Medium" if safety_critical else "Low",
                "description": (
                    "Risk of governance audit trail being modified to conceal non-compliance. "
                    "CRP mitigates via HMAC-SHA256 chained signatures with tamper detection, "
                    "making any modification cryptographically detectable."
                ),
            },
        }

        # CRP native mitigations
        mitigations = assessment.mitigations

        # Residual risks
        residual = assessment.residual_risks

        # Determine if supervisory consultation is needed
        high_risks = sum(
            1
            for r in risk_assessment_data.values()
            if isinstance(r, dict) and r.get("risk_level") in ("High", "Critical")
        )
        consultation_required = high_risks >= 2

        return DPIAReport(
            dpia_id=f"dpia-{uuid.uuid4().hex[:12]}",
            generated_at=time.time(),
            system_name=system_name,
            system_version=self._get_version(),
            controller=self._controller,
            dpo_contact=self._dpo_contact,
            processing_description=processing_description,
            data_subjects=data_subjects,
            data_categories=data_categories,
            legal_basis=legal_basis,
            necessity_assessment=(
                "Processing through CRP is necessary to provide AI context management "
                "functionality. CRP applies data minimization by extracting only relevant "
                "facts from source text, storing them in session-scoped boundaries, and "
                "automatically expiring data per classification-based retention policies. "
                "Processing is proportionate to the stated purpose — CRP processes only "
                "what is needed for context assembly and does not retain data beyond "
                "session lifecycle unless explicitly persisted by the deployer."
            ),
            risk_assessment=risk_assessment_data,
            mitigation_measures=mitigations,
            residual_risks=residual,
            consultation_required=consultation_required,
            review_schedule=(
                "This DPIA shall be reviewed: (1) annually, (2) when processing "
                "operations change materially, (3) when new risk factors are identified, "
                "(4) when CRP is updated to a new major version."
            ),
        )

    # ── Session Audit ───────────────────────────────────────────────

    def audit_session(
        self,
        orchestrator=None,
        session_file: str | None = None,
    ) -> SessionAuditReport:
        """Audit a CRP session for compliance.

        Analyses the session's audit trail, quality scores, and
        governance events to produce a compliance audit report.

        Either provide a live ``orchestrator`` or a ``session_file``
        path to a persisted session JSON.
        """
        dispatches = 0
        pii_count = 0
        injection_count = 0
        quality_tiers: dict[str, int] = {}
        audit_entries = 0
        audit_intact = True
        findings: list[dict[str, str]] = []
        recommendations: list[str] = []
        risk_level = "minimal"
        session_id = "unknown"

        if orchestrator is not None:
            session_id = getattr(orchestrator, "_session", None)
            if session_id and hasattr(session_id, "session_id"):
                session_id = session_id.session_id
            else:
                session_id = "live-session"

            # Get session status for metrics
            try:
                status = orchestrator.session_status()
                dispatches = status.windows_completed
            except Exception:
                dispatches = 0

        elif session_file is not None:
            import json as _json
            import pathlib

            path = pathlib.Path(session_file)
            if not path.exists():
                raise FileNotFoundError(f"Session file not found: {session_file}")
            data = _json.loads(path.read_text(encoding="utf-8"))
            session_id = data.get("session_id", path.stem)

            # Parse session data
            header = data.get("header", {})
            risk_level = header.get("risk_level", "minimal")
            dispatches = header.get("windows_completed", 0)

            # Count audit trail entries
            trail = data.get("audit_trail", [])
            audit_entries = len(trail)

            # Verify audit trail integrity
            if trail:
                audit_intact = self._verify_trail_chain(trail)
                if not audit_intact:
                    findings.append(
                        {
                            "severity": "HIGH",
                            "description": "Audit trail integrity check FAILED — chain is broken or tampered",
                        }
                    )

            # Parse events for PII/injection counts
            events = data.get("events", [])
            for evt in events:
                evt_type = evt.get("type", "")
                if "pii" in evt_type.lower():
                    pii_count += 1
                if "injection" in evt_type.lower():
                    injection_count += 1

            # Parse quality data
            quality_data = data.get("quality", {})
            quality_tiers = quality_data.get("tier_distribution", {})

        # Generate findings based on metrics
        if dispatches == 0:
            findings.append(
                {
                    "severity": "INFO",
                    "description": "No dispatches recorded in this session",
                }
            )

        if pii_count > 0:
            findings.append(
                {
                    "severity": "MEDIUM",
                    "description": f"PII detected in {pii_count} event(s) — verify consent and purpose limitation",
                }
            )
            recommendations.append(
                "Review PII detection events and confirm processing has valid "
                "legal basis under GDPR Art. 6"
            )

        if injection_count > 0:
            findings.append(
                {
                    "severity": "HIGH",
                    "description": f"{injection_count} prompt injection attempt(s) detected and logged",
                }
            )
            recommendations.append(
                "Investigate injection attempts — review source text and consider "
                "tightening input validation rules"
            )

        if not audit_intact:
            recommendations.append(
                "CRITICAL: Audit trail integrity compromised — investigate "
                "immediately and preserve forensic evidence"
            )

        # Standard recommendations
        if not recommendations:
            recommendations.append("No issues found — maintain current governance posture")

        recommendations.append(
            "Export audit trail periodically for off-site backup and regulatory readiness"
        )

        # Calculate compliance score
        score = 100.0
        for f in findings:
            if f["severity"] == "HIGH":
                score -= 15
            elif f["severity"] == "MEDIUM":
                score -= 5
        score = max(0.0, score)

        return SessionAuditReport(
            report_id=f"audit-{uuid.uuid4().hex[:12]}",
            session_id=str(session_id),
            generated_at=time.time(),
            risk_level=risk_level,
            dispatches_audited=dispatches,
            pii_detections=pii_count,
            injection_attempts=injection_count,
            quality_tiers=quality_tiers,
            audit_trail_entries=audit_entries,
            audit_trail_intact=audit_intact,
            compliance_score=score,
            findings=findings,
            recommendations=recommendations,
        )

    # ── Conformity Evidence Pack ────────────────────────────────────

    def conformity_evidence_pack(
        self,
        system_name: str = "CRP-powered AI System",
        category: str = "context_management",
        data_subjects: str = "end users",
        session_file: str | None = None,
    ) -> dict[str, Any]:
        """Generate a complete conformity evidence pack for regulators.

        Combines all compliance artifacts into a single exportable
        package:  compliance report, risk assessment, DPIA, technical
        documentation, transparency declaration, and optionally a
        session audit report.

        This is what you hand to a regulator or auditor.
        """
        # Risk assessment
        assessment = self.assess_risk(category=category, processes_personal_data=True)

        # Compile all artifacts
        pack = {
            "document_type": "conformity_evidence_pack",
            "generated_at": time.time(),
            "version": self._get_version(),
            "system_name": system_name,
            "artifacts": {
                "compliance_report": self.compliance_report(
                    risk_assessment=assessment,
                ),
                "risk_assessment": assessment.to_dict(),
                "dpia": self.generate_dpia(
                    system_name=system_name,
                    data_subjects=data_subjects,
                    category=category,
                ).to_dict(),
                "technical_documentation": self.technical_documentation(
                    risk_assessment=assessment,
                ),
                "transparency_declaration": self.transparency_declaration(),
            },
        }

        # Add session audit if available
        if session_file:
            audit = self.audit_session(session_file=session_file)
            pack["artifacts"]["session_audit"] = audit.to_dict()

        return pack

    # ── Markdown Export ──────────────────────────────────────────────

    def full_report_markdown(
        self,
        system_name: str = "CRP-powered AI System",
        category: str = "context_management",
        data_subjects: str = "end users",
    ) -> str:
        """Generate a complete compliance report as a single Markdown document.

        Suitable for printing, sharing, or including in regulatory submissions.
        """
        assessment = self.assess_risk(category=category, processes_personal_data=True)
        dpia = self.generate_dpia(
            system_name=system_name,
            data_subjects=data_subjects,
            category=category,
        )

        sections = [
            self.compliance_report_markdown(risk_assessment=assessment),
            "",
            "---",
            "",
            dpia.to_markdown(),
        ]
        return "\n".join(sections)

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _get_version() -> str:
        try:
            from crp._version import __version__

            return __version__
        except Exception:
            return "2.0.0"

    @staticmethod
    def _verify_trail_chain(trail: list[dict]) -> bool:
        """Verify audit trail hash chain integrity."""
        for i, entry in enumerate(trail):
            if i == 0:
                continue
            expected_prev = entry.get("previous_hash", "")
            actual_prev_data = trail[i - 1].get("entry_hash", "")
            if expected_prev and actual_prev_data and expected_prev != actual_prev_data:
                return False
        return True
