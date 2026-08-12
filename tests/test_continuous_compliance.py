"""Tests for the continuous compliance engine (Round 19)."""

from __future__ import annotations

import pytest

from crp_comply.continuous_compliance import (
    ComplianceAuditResult,
    ContinuousComplianceEngine,
    Verdict,
)
from crp_comply.programme import LifecycleState, ProgrammeStore


@pytest.fixture
def stores(tmp_path):
    programme = ProgrammeStore(data_dir=tmp_path)
    engine = ContinuousComplianceEngine(data_dir=tmp_path, programme_store=programme)
    return programme, engine


def test_audit_empty_programme(stores):
    _, engine = stores
    result = engine.audit("user-1")
    assert isinstance(result, ComplianceAuditResult)
    assert result.overall_score == 0.0
    assert result.gap_report == []


def test_audit_signed_is_compliant(stores):
    programme, engine = stores
    programme.transition(
        user_id="user-1",
        obligation_id="eu_ai_act_annex_iv",
        recipe_id="eu_ai_act_annex_iv",
        system_name="CV Scanner",
        new_state=LifecycleState.DRAFT_READY,
        observed_evidence=True,
    )
    programme.transition(
        user_id="user-1",
        obligation_id="eu_ai_act_annex_iv",
        recipe_id="eu_ai_act_annex_iv",
        new_state=LifecycleState.SIGNED,
        observed_evidence=True,
    )
    result = engine.audit("user-1")
    assert result.overall_score == 1.0
    assert len(result.obligations) == 1
    assert result.obligations[0].verdict == Verdict.COMPLIANT.value
    assert result.gap_report == []


def test_audit_draft_is_partial(stores):
    programme, engine = stores
    programme.transition(
        user_id="user-1",
        obligation_id="gdpr_dpia",
        recipe_id="gdpr_dpia",
        new_state=LifecycleState.DRAFT_READY,
        observed_evidence=True,
    )
    result = engine.audit("user-1")
    assert result.overall_score == 0.5
    assert result.obligations[0].verdict == Verdict.PARTIAL.value
    assert len(result.gap_report) == 1
    assert "Draft exists" in result.gap_report[0]["reason"]


def test_audit_stale_is_non_compliant(stores):
    programme, engine = stores
    programme.transition(
        user_id="user-1",
        obligation_id="iso_42001_statement",
        recipe_id="iso_42001_statement",
        new_state=LifecycleState.DRAFT_READY,
        observed_evidence=True,
    )
    programme.transition(
        user_id="user-1",
        obligation_id="iso_42001_statement",
        recipe_id="iso_42001_statement",
        new_state=LifecycleState.SIGNED,
        observed_evidence=True,
    )
    programme.mark_stale(
        user_id="user-1",
        obligation_id="iso_42001_statement",
        reason="corpus updated",
    )
    result = engine.audit("user-1")
    assert result.obligations[0].verdict == Verdict.NON_COMPLIANT.value
    assert len(result.gap_report) == 1


def test_audit_not_started_is_not_assessed(stores):
    programme, engine = stores
    programme.transition(
        user_id="user-1",
        obligation_id="eu_ai_act_risk_classification",
        recipe_id="eu_ai_act_risk_classification",
        new_state=LifecycleState.NOT_STARTED,
    )
    result = engine.audit("user-1")
    assert result.obligations[0].verdict == Verdict.NOT_ASSESSED.value


def test_audit_overall_score_for_mix(stores):
    programme, engine = stores
    programme.transition(
        user_id="user-1",
        obligation_id="ob-1",
        recipe_id="eu_ai_act_annex_iv",
        new_state=LifecycleState.DRAFT_READY,
        observed_evidence=True,
    )
    programme.transition(
        user_id="user-1",
        obligation_id="ob-1",
        recipe_id="eu_ai_act_annex_iv",
        new_state=LifecycleState.SIGNED,
        observed_evidence=True,
    )
    programme.transition(
        user_id="user-1",
        obligation_id="ob-2",
        recipe_id="gdpr_dpia",
        new_state=LifecycleState.DRAFT_READY,
        observed_evidence=True,
    )
    programme.transition(
        user_id="user-1",
        obligation_id="ob-3",
        recipe_id="iso_42001_statement",
        new_state=LifecycleState.NOT_STARTED,
    )
    result = engine.audit("user-1")
    assert result.overall_score == pytest.approx(0.5, abs=0.01)
    assert len(result.gap_report) == 1


def test_remediation_ticket_defaults(stores):
    programme, engine = stores
    programme.transition(
        user_id="user-2",
        obligation_id="gdpr_dpia",
        recipe_id="gdpr_dpia",
        new_state=LifecycleState.DRAFT_READY,
        observed_evidence=True,
    )
    engine.audit("user-2")
    ticket = engine.create_remediation("user-2", "gdpr_dpia", "DPO")
    assert ticket.obligation_id == "gdpr_dpia"
    assert ticket.owner == "DPO"
    assert ticket.status == "open"
    assert any("DPO review" in item for item in ticket.evidence_checklist)


def test_remediation_persistence(stores):
    programme, engine = stores
    programme.transition(
        user_id="user-3",
        obligation_id="iso_42001_statement",
        recipe_id="iso_42001_statement",
        new_state=LifecycleState.DRAFT_READY,
        observed_evidence=True,
    )
    engine.audit("user-3")
    ticket = engine.create_remediation("user-3", "iso_42001_statement", "Compliance Lead")
    loaded = engine.list_remediations("user-3")
    assert len(loaded) == 1
    assert loaded[0].ticket_id == ticket.ticket_id


def test_last_audit_persisted(stores):
    _, engine = stores
    assert engine.get_last_audit("user-4") is None
    engine.audit("user-4")
    loaded = engine.get_last_audit("user-4")
    assert loaded is not None
    assert loaded.user_id == "user-4"


def test_mark_stale_on_corpus_change(stores):
    programme, engine = stores
    programme.transition(
        user_id="user-5",
        obligation_id="eu_ai_act_annex_iv",
        recipe_id="eu_ai_act_annex_iv",
        new_state=LifecycleState.DRAFT_READY,
        observed_evidence=True,
    )
    programme.transition(
        user_id="user-5",
        obligation_id="eu_ai_act_annex_iv",
        recipe_id="eu_ai_act_annex_iv",
        new_state=LifecycleState.SIGNED,
        observed_evidence=True,
    )
    engine.mark_stale_on_corpus_change("user-5", "eu_ai_act_annex_iv", "new case law")
    rec = programme.get("user-5", "eu_ai_act_annex_iv")
    assert rec.state == LifecycleState.STALE.value


def test_gap_report_remediation_hints(stores):
    programme, engine = stores
    programme.transition(
        user_id="user-6",
        obligation_id="gdpr_dpia",
        recipe_id="gdpr_dpia",
        new_state=LifecycleState.WAITING_ON_ARTEFACT,
        blockers=["missing model card"],
        observed_evidence=True,
    )
    result = engine.audit("user-6")
    gap = result.gap_report[0]
    assert "Resolve blockers" in gap["remediation_hint"]
    assert "missing model card" in gap["remediation_hint"]
