# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Tests for CRP Comply core module."""

import json
import uuid

import pytest

from crp_comply.core import CRPComply, DPIAReport, SessionAuditReport


@pytest.fixture
def comply():
    return CRPComply()


class TestCRPComplyInit:
    def test_instance_creation(self, comply):
        assert comply is not None

    def test_has_classifier(self, comply):
        assert comply._classifier is not None

    def test_has_reporter(self, comply):
        assert comply._reporter is not None


class TestRiskAssessment:
    def test_default_category(self, comply):
        result = comply.assess_risk()
        assert result is not None
        d = result.to_dict() if hasattr(result, "to_dict") else result
        assert "risk_level" in d

    def test_general_purpose_category(self, comply):
        result = comply.assess_risk(category="GENERAL_PURPOSE")
        d = result.to_dict() if hasattr(result, "to_dict") else result
        assert d["risk_level"] in ("minimal", "limited", "high", "unacceptable")

    def test_with_risk_factors(self, comply):
        result = comply.assess_risk(
            affects_fundamental_rights=True,
            safety_critical=True,
        )
        d = result.to_dict() if hasattr(result, "to_dict") else result
        assert "risk_level" in d


class TestComplianceReport:
    def test_basic_report(self, comply):
        result = comply.compliance_report()
        assert isinstance(result, dict)

    def test_report_has_generated_at(self, comply):
        result = comply.compliance_report()
        assert "generated_at" in result

    def test_markdown(self, comply):
        md = comply.compliance_report_markdown()
        assert isinstance(md, str)
        assert "CRP Comply" in md or "Compliance" in md


class TestDPIA:
    def test_generate_dpia(self, comply):
        report = comply.generate_dpia(system_name="Test System")
        assert isinstance(report, DPIAReport)

    def test_dpia_to_dict(self, comply):
        report = comply.generate_dpia(system_name="Test System")
        d = report.to_dict()
        assert "mitigations" in d or "risk_assessment" in d

    def test_dpia_to_markdown(self, comply):
        report = comply.generate_dpia(system_name="Test System")
        md = report.to_markdown()
        assert isinstance(md, str)
        assert "Test System" in md


class TestTransparency:
    def test_declaration(self, comply):
        result = comply.transparency_declaration()
        assert isinstance(result, dict)
        assert "system_name" in result

    def test_declaration_has_data_processed(self, comply):
        result = comply.transparency_declaration()
        assert "data_processed" in result


class TestTechnicalDocs:
    def test_generate(self, comply):
        result = comply.technical_documentation()
        assert isinstance(result, dict)
        assert "document_type" in result


class TestSessionAudit:
    def test_audit_from_session_file(self, comply, tmp_path):
        session_data = {
            "session_id": str(uuid.uuid4()),
            "header": {"risk_level": "minimal", "windows_completed": 5},
            "audit_trail": [],
            "events": [],
            "quality": {"tier_distribution": {"S": 3, "A": 2}},
        }
        session_file = tmp_path / "test_session.json"
        session_file.write_text(json.dumps(session_data), encoding="utf-8")

        report = comply.audit_session(session_file=str(session_file))
        assert isinstance(report, SessionAuditReport)
        assert report.compliance_score >= 0

    def test_audit_missing_file(self, comply):
        with pytest.raises(FileNotFoundError):
            comply.audit_session(session_file="/nonexistent/file.json")

    def test_audit_report_to_dict(self, comply, tmp_path):
        session_data = {
            "session_id": "test-123",
            "header": {},
            "audit_trail": [],
            "events": [],
        }
        session_file = tmp_path / "session.json"
        session_file.write_text(json.dumps(session_data), encoding="utf-8")

        report = comply.audit_session(session_file=str(session_file))
        d = report.to_dict()
        assert d["session_id"] == "test-123"
        assert "compliance_score" in d
        assert "findings" in d


class TestEvidencePack:
    def test_generate_pack(self, comply):
        result = comply.conformity_evidence_pack(
            system_name="Test AI System",
            category="context_management",
        )
        assert isinstance(result, dict)
        assert "artifacts" in result

    def test_pack_includes_all_artifacts(self, comply):
        result = comply.conformity_evidence_pack(system_name="Test")
        artifacts = result["artifacts"]
        assert "compliance_report" in artifacts
        assert "risk_assessment" in artifacts
        assert "dpia" in artifacts
        assert "technical_documentation" in artifacts
        assert "transparency_declaration" in artifacts


class TestFullReport:
    def test_full_markdown(self, comply):
        md = comply.full_report_markdown(system_name="Test AI")
        assert isinstance(md, str)
        assert len(md) > 100
