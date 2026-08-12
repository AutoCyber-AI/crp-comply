# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""FastAPI route definitions for CRP Comply API."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse

from ..core import CRPComply
from .auth import AuthManager, Tier, check_feature_access
from .deps import (
    get_auth,
    get_auth_context,
    get_comply,
    get_current_tier,
    get_current_user,
    get_passkey_manager,
    get_passkey_manager_for_request,
    meter_call,
)
from .models import (
    APIKeyCreated,
    APIKeyCreateRequest,
    APIKeyResponse,
    CertificateRequest,
    ComplianceReportRequest,
    ComplianceReportResponse,
    ComplianceControl,
    DPIARequest,
    DPIAResponse,
    EvidencePackRequest,
    EvidencePackResponse,
    HealthResponse,
    RiskAssessRequest,
    RiskAssessResponse,
    RiskLevel,
    SessionAuditRequest,
    SessionAuditResponse,
    AuditFinding,
    SignedCertificate,
    TechnicalDocsRequest,
    TechnicalDocsResponse,
    TransparencyRequest,
    TransparencyResponse,
)

logger = logging.getLogger("crp_comply.api")

# Protected API routes.
router = APIRouter()

# Passkey lifecycle routes — must NOT require an existing MFA session.
passkey_router = APIRouter()


def _to_iso(ts) -> str:
    """Convert a value to ISO 8601 string (handles float timestamps, strings, etc.)."""
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    if ts:
        return str(ts)
    return datetime.now(timezone.utc).isoformat()


def _require_feature(tier: Tier, feature: str) -> None:
    if not check_feature_access(tier, feature):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Feature '{feature}' requires a higher tier. Current: {tier.value}",
        )


# ── Path Safety ────────────────────────────────────────────────
_ALLOWED_SESSION_DIRS: list[str] = []


def configure_session_dirs(dirs: list[str]) -> None:
    """Configure allowed directories for session file access."""
    _ALLOWED_SESSION_DIRS.clear()
    _ALLOWED_SESSION_DIRS.extend(dirs)


def _safe_session_path(raw: str) -> Path:
    """Validate and resolve a session file path, preventing path traversal."""
    p = Path(raw).resolve()
    if not p.suffix == ".json":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Session file must be a .json file",
        )
    if _ALLOWED_SESSION_DIRS:
        for allowed in _ALLOWED_SESSION_DIRS:
            if str(p).startswith(str(Path(allowed).resolve())):
                break
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Session file path is outside allowed directories",
            )
    if not p.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session file not found: {p.name}",
        )
    return p


# ── Health ─────────────────────────────────────────────────────
@router.get("/health", response_model=HealthResponse, tags=["system"])
async def health():
    from crp_comply import __version__

    try:
        from crp._version import __version__ as crp_ver
    except Exception:
        crp_ver = "unknown"

    return HealthResponse(
        status="healthy",
        version=__version__,
        tier="api",
        crp_version=crp_ver,
        comply_version=__version__,
    )


# ── Deliverable Persistence Helper ─────────────────────────────
def _persist_report(
    *,
    user_id: str,
    kind: str,
    system_name: str,
    tier: Tier,
    payload: dict,
    markdown: str | None = None,
    risk_level: str | None = None,
) -> str | None:
    """Save a generated report to the ReportStore. Returns the new report id.

    Anonymous callers are skipped — they have nowhere to retrieve reports from
    anyway. Errors are logged but never raised: a persistence failure must
    not break report generation.
    """
    if user_id == "anonymous":
        return None
    try:
        from .reports import get_report_store

        rec = get_report_store().save(
            user_id=user_id,
            kind=kind,
            system_name=system_name,
            tier=tier.value,
            payload=payload,
            markdown=markdown,
            risk_level=risk_level,
        )
        return rec.get("id")
    except Exception as exc:
        logger.warning("report persist failed kind=%s user=%s: %s", kind, user_id, exc)
        return None


# ── Risk Assessment ────────────────────────────────────────────
@router.post(
    "/risk-assessment",
    response_model=RiskAssessResponse,
    tags=["compliance"],
    summary="EU AI Act Article 6 risk classification",
    dependencies=[Depends(meter_call("risk-assessment"))],
)
async def risk_assessment(
    req: RiskAssessRequest,
    comply: CRPComply = Depends(get_comply),
    tier: Tier = Depends(get_current_tier),
    user_id: str = Depends(get_current_user),
):
    _require_feature(tier, "risk_assessment")

    result = comply.assess_risk(
        category=req.category,
        affects_fundamental_rights=req.affects_fundamental_rights,
        safety_critical=req.has_critical_infrastructure,
        processes_personal_data=req.has_biometric,
    )
    # result is a RiskAssessment object — convert to dict
    result_dict = result.to_dict() if hasattr(result, "to_dict") else result
    raw_level = result_dict.get("risk_level", "MINIMAL").upper()
    response = RiskAssessResponse(
        system_name=req.system_name,
        risk_level=RiskLevel(raw_level),
        category=req.category,
        obligations=result_dict.get("obligations", []),
        prohibitions=result_dict.get("prohibitions", []),
        assessment_date=result_dict.get("assessment_date", datetime.now(timezone.utc).isoformat()),
        crp_version=result_dict.get("crp_version", ""),
    )
    _persist_report(
        user_id=user_id,
        kind="risk_assessment",
        system_name=req.system_name,
        tier=tier,
        payload=response.model_dump(),
        risk_level=raw_level,
    )
    return response


# ── Compliance Report ─────────────────────────────────────────
@router.post(
    "/compliance-report",
    response_model=ComplianceReportResponse,
    tags=["compliance"],
    summary="Generate full compliance status report",
    dependencies=[Depends(meter_call("compliance-report"))],
)
async def compliance_report(
    req: ComplianceReportRequest,
    comply: CRPComply = Depends(get_comply),
    tier: Tier = Depends(get_current_tier),
    user_id: str = Depends(get_current_user),
):
    feature = "compliance_report" if tier != Tier.FREE else "basic_compliance_report"
    _require_feature(tier, feature)

    # Pull runtime stats from the proxy interceptor if available
    session_stats = None
    try:
        from ..proxy.routes import _get_interceptor

        interceptor = _get_interceptor()
        stats = interceptor.get_compliance_stats()
        session_stats = stats.model_dump()
    except (RuntimeError, Exception):
        pass  # Interceptor not initialised or no records yet

    result = comply.compliance_report(session_stats=session_stats)

    # Flatten controls from all frameworks
    controls = []
    for fw_name, fw_data in result.get("frameworks", {}).items():
        for c in fw_data.get("controls", []):
            controls.append(
                ComplianceControl(
                    control_id=c.get("control_id", ""),
                    title=c.get("description", ""),
                    status=c.get("status", "unknown"),
                    framework=fw_name,
                    evidence=c.get("evidence", ""),
                )
            )

    summary = result.get("summary", {})
    score = summary.get("compliance_score", 0.0)

    # Determine overall status from score
    if score >= 90:
        overall_status = "compliant"
    elif score >= 70:
        overall_status = "partially_compliant"
    else:
        overall_status = "non_compliant"

    response = ComplianceReportResponse(
        system_name=req.system_name,
        overall_status=overall_status,
        risk_level=result.get("risk_assessment", {}).get("risk_level", "MINIMAL"),
        controls=controls,
        score=score,
        generated_at=_to_iso(result.get("generated_at")),
        crp_version=result.get("crp_version", ""),
    )
    _persist_report(
        user_id=user_id,
        kind="compliance_report",
        system_name=req.system_name,
        tier=tier,
        payload=response.model_dump(),
        risk_level=response.risk_level,
    )
    return response


# ── Compliance Report (Markdown) ──────────────────────────────
@router.post(
    "/compliance-report/markdown",
    tags=["compliance"],
    summary="Generate compliance report in Markdown format",
    dependencies=[Depends(meter_call("compliance-report-markdown"))],
)
async def compliance_report_markdown(
    req: ComplianceReportRequest,
    comply: CRPComply = Depends(get_comply),
    tier: Tier = Depends(get_current_tier),
    user_id: str = Depends(get_current_user),
):
    _require_feature(tier, "compliance_report")
    md = comply.compliance_report_markdown()
    _persist_report(
        user_id=user_id,
        kind="compliance_report_markdown",
        system_name=req.system_name,
        tier=tier,
        payload={"system_name": req.system_name},
        markdown=md,
    )
    return {"markdown": md, "system_name": req.system_name}


# ── DPIA ───────────────────────────────────────────────────────
@router.post(
    "/dpia",
    response_model=DPIAResponse,
    tags=["compliance"],
    summary="GDPR Article 35 Data Protection Impact Assessment",
    dependencies=[Depends(meter_call("dpia"))],
)
async def generate_dpia(
    req: DPIARequest,
    comply: CRPComply = Depends(get_comply),
    tier: Tier = Depends(get_current_tier),
    user_id: str = Depends(get_current_user),
):
    _require_feature(tier, "dpia")

    report = comply.generate_dpia(
        system_name=req.system_name,
        data_subjects=req.data_subjects,
        processes_personal_data=req.processes_personal_data,
        makes_automated_decisions=req.makes_automated_decisions,
        safety_critical=req.safety_critical,
        profiles_individuals=req.profiles_individuals,
        affects_fundamental_rights=req.affects_fundamental_rights,
    )
    report_dict = report.to_dict()

    # Map DPIAReport dict keys to DPIAResponse fields
    mitigations = report_dict.get("mitigation_measures", [])
    residual = report_dict.get("residual_risks", [])
    consultation = report_dict.get("consultation_required", False)

    response = DPIAResponse(
        system_name=req.system_name,
        dpia_required=consultation or len(mitigations) > 0,
        risk_categories=report_dict.get("risk_assessment", {}),
        mitigations=mitigations,
        residual_risk=", ".join(residual) if residual else "none identified",
        recommendation=(
            "Supervisory authority consultation required"
            if consultation
            else "Risks adequately mitigated by CRP controls"
        ),
        generated_at=_to_iso(report_dict.get("generated_at")),
    )
    _persist_report(
        user_id=user_id,
        kind="dpia",
        system_name=req.system_name,
        tier=tier,
        payload=response.model_dump(),
    )
    return response


# ── Transparency Declaration ──────────────────────────────────
@router.post(
    "/transparency",
    response_model=TransparencyResponse,
    tags=["compliance"],
    summary="EU AI Act Article 13 transparency declaration",
    dependencies=[Depends(meter_call("transparency"))],
)
async def transparency_declaration(
    req: TransparencyRequest,
    comply: CRPComply = Depends(get_comply),
    tier: Tier = Depends(get_current_tier),
    user_id: str = Depends(get_current_user),
):
    _require_feature(tier, "transparency_declaration")

    result = comply.transparency_declaration()
    response = TransparencyResponse(
        system_name=req.system_name,
        declaration=result,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
    _persist_report(
        user_id=user_id,
        kind="transparency",
        system_name=req.system_name,
        tier=tier,
        payload=response.model_dump(),
    )
    return response


# ── Technical Documentation ────────────────────────────────────
@router.post(
    "/technical-docs",
    response_model=TechnicalDocsResponse,
    tags=["compliance"],
    summary="EU AI Act Article 11 technical documentation",
    dependencies=[Depends(meter_call("technical-docs"))],
)
async def technical_documentation(
    req: TechnicalDocsRequest,
    comply: CRPComply = Depends(get_comply),
    tier: Tier = Depends(get_current_tier),
    user_id: str = Depends(get_current_user),
):
    _require_feature(tier, "technical_documentation")

    result = comply.technical_documentation()
    response = TechnicalDocsResponse(
        system_name=req.system_name,
        documentation=result,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
    _persist_report(
        user_id=user_id,
        kind="technical_docs",
        system_name=req.system_name,
        tier=tier,
        payload=response.model_dump(),
    )
    return response


# ── Session Audit ──────────────────────────────────────────────
@router.post(
    "/audit",
    response_model=SessionAuditResponse,
    tags=["audit"],
    summary="Audit a persisted CRP session file",
    dependencies=[Depends(meter_call("session-audit"))],
)
async def audit_session(
    req: SessionAuditRequest,
    comply: CRPComply = Depends(get_comply),
    tier: Tier = Depends(get_current_tier),
    user_id: str = Depends(get_current_user),
):
    _require_feature(tier, "session_audit")

    session_path = _safe_session_path(req.session_file)

    report = comply.audit_session(session_file=str(session_path))
    report_dict = report.to_dict()
    findings = [
        AuditFinding(
            severity=f.get("severity", "INFO"),
            category=f.get("category", "general"),
            detail=f.get("description", f.get("detail", "")),
        )
        for f in report_dict.get("findings", [])
    ]
    response = SessionAuditResponse(
        session_id=report_dict.get("session_id", "unknown"),
        compliance_score=report_dict.get("compliance_score", 0.0),
        findings=findings,
        audit_trail_verified=report_dict.get("audit_trail_intact", False),
        events_analysed=report_dict.get("audit_trail_entries", 0),
        generated_at=_to_iso(report_dict.get("generated_at")),
    )
    _persist_report(
        user_id=user_id,
        kind="session_audit",
        system_name=response.session_id or req.session_file,
        tier=tier,
        payload=response.model_dump(),
    )
    return response


# ── Evidence Pack ──────────────────────────────────────────────
@router.post(
    "/evidence-pack",
    response_model=EvidencePackResponse,
    tags=["compliance"],
    summary="Generate complete conformity evidence pack",
    dependencies=[Depends(meter_call("evidence-pack"))],
)
async def evidence_pack(
    req: EvidencePackRequest,
    comply: CRPComply = Depends(get_comply),
    tier: Tier = Depends(get_current_tier),
    user_id: str = Depends(get_current_user),
):
    _require_feature(tier, "evidence_pack")

    safe_session = None
    if req.session_file:
        safe_session = str(_safe_session_path(req.session_file))

    result = comply.conformity_evidence_pack(
        system_name=req.system_name,
        category=req.category,
        session_file=safe_session,
    )
    artifacts_dict = result if isinstance(result, dict) else {}
    # ``conformity_evidence_pack`` wraps artifacts under an ``artifacts`` key;
    # tolerate both shapes so the builder receives the per-file payloads.
    artifacts = artifacts_dict.get("artifacts", artifacts_dict)
    artifact_names = list(artifacts.keys())

    # Build a real zip under /app/data/evidence_packs/{user_id}/{pack_id}/
    pack_id: str
    zip_bytes = 0
    if user_id != "anonymous":
        try:
            import hashlib as _hashlib
            from pathlib import Path as _Path

            from .reports import get_pack_builder

            builder = get_pack_builder()
            corpus_manifest_hash = ""
            try:
                cmp = _Path("corpus") / "_scraped" / "manifest.json"
                if cmp.exists():
                    corpus_manifest_hash = _hashlib.sha256(cmp.read_bytes()).hexdigest()
            except Exception as _bandit_exc:
                logger.debug("corpus manifest hash best-effort: %s", _bandit_exc)

            provenance: dict[str, Any] = {}
            if corpus_manifest_hash:
                provenance["corpus_manifest_hash"] = corpus_manifest_hash

            manifest = builder.build(
                user_id=user_id,
                system_name=req.system_name,
                category=req.category,
                tier=tier.value,
                artifacts=artifacts,
                provenance=provenance,
            )
            pack_id = manifest["pack_id"]
            zip_bytes = manifest.get("zip_bytes", 0)
            _persist_report(
                user_id=user_id,
                kind="evidence_pack",
                system_name=req.system_name,
                tier=tier,
                payload={
                    "pack_id": pack_id,
                    "zip_bytes": zip_bytes,
                    "artifacts": artifact_names,
                    "category": req.category,
                },
            )
        except Exception as exc:
            logger.warning("evidence pack persist failed user=%s: %s", user_id, exc)
            pack_id = str(uuid.uuid4())
    else:
        pack_id = str(uuid.uuid4())

    return EvidencePackResponse(
        system_name=req.system_name,
        pack_id=pack_id,
        artifacts=artifact_names,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


# ── Full Markdown Report ──────────────────────────────────────
@router.post(
    "/full-report",
    tags=["compliance"],
    summary="Generate complete compliance report in Markdown",
    dependencies=[Depends(meter_call("full-report"))],
)
async def full_report(
    req: ComplianceReportRequest,
    comply: CRPComply = Depends(get_comply),
    tier: Tier = Depends(get_current_tier),
    user_id: str = Depends(get_current_user),
):
    _require_feature(tier, "compliance_report")
    md = comply.full_report_markdown(
        system_name=req.system_name,
        category=req.category,
    )
    _persist_report(
        user_id=user_id,
        kind="full_report",
        system_name=req.system_name,
        tier=tier,
        payload={"system_name": req.system_name, "category": req.category},
        markdown=md,
    )
    return {"markdown": md, "system_name": req.system_name}


# ── Signed Certificate (CLOUD tier) ────────────────────────────
CERTIFICATE_ISSUER = "AutoCyber AI Pty Ltd \u2014 CRP Comply Cloud"
CERTIFICATE_VALIDITY_DAYS = 365


# ── User Profile & JWT Exchange ────────────────────────────────


@router.get(
    "/me",
    tags=["auth"],
    summary="Get current user profile, tier, and provider status",
)
async def get_me(
    user_id: str = Depends(get_current_user),
    tier: Tier = Depends(get_current_tier),
    auth: AuthManager = Depends(get_auth),
):
    """Return the authenticated user's profile, tier, and provider status."""
    import os

    user_data = auth._users.get(user_id, {})

    # First-touch welcome bonus: every signed-in user gets $5 of platform
    # credit (~100 hosted calls) so they can experience the agent before
    # bringing a key. Idempotent — only granted once per user.
    if user_id and user_id != "anonymous":
        try:
            from .credits import get_credit_store

            get_credit_store().ensure_welcome_bonus(user_id)
        except Exception:  # pragma: no cover — never block /me on bonus
            pass

    # Provider status
    provider_configured = False
    provider_source = "none"
    provider_name = None
    try:
        from .provider import get_provider_store

        store = get_provider_store()
        cfg = store.get(user_id)
        if cfg:
            provider_configured = True
            provider_source = "user"
            provider_name = cfg.get("provider")
    except RuntimeError:
        pass

    if not provider_configured and os.environ.get("CRP_COMPLY_UPSTREAM_API_KEY"):
        provider_configured = True
        provider_source = "env"
        provider_name = "openai"

    # Count user's API keys
    key_count = len(auth.list_api_keys(user_id=user_id))

    # Current monthly usage / quota status
    usage_status: dict[str, object] | None = None
    try:
        from .usage import get_usage_tracker

        usage_status = get_usage_tracker().check_quota(user_id, tier)
    except RuntimeError:
        pass

    return {
        "user_id": user_id,
        "email": user_data.get("email"),
        "name": user_data.get("name"),
        "tier": tier.value,
        "created_at": user_data.get("created_at"),
        "stripe_customer_id": user_data.get("stripe_customer_id"),
        "provider": {
            "configured": provider_configured,
            "source": provider_source,
            "provider": provider_name,
        },
        "api_key_count": key_count,
        "usage": usage_status,
    }


@router.get(
    "/usage",
    tags=["billing"],
    summary="Current month's call usage and quota for the authenticated user",
)
async def get_usage(
    user_id: str = Depends(get_current_user),
    tier: Tier = Depends(get_current_tier),
):
    """Return the user's quota status and current-period usage breakdown.

    Anonymous callers get a synthetic FREE-tier response with zeroed counters.
    """
    from .usage import get_usage_tracker

    tracker = get_usage_tracker()
    status_ = tracker.check_quota(user_id, tier)
    breakdown = tracker.get_usage(user_id)
    return {
        **status_,
        "by_endpoint": breakdown.get("by_endpoint", {}),
        "first_call_at": breakdown.get("first_call_at"),
        "last_call_at": breakdown.get("last_call_at"),
    }


# ── Persisted Reports — list, fetch, download, delete ─────────
@router.get(
    "/reports",
    tags=["reports"],
    summary="List all compliance deliverables generated by the current user",
)
async def list_reports(
    kind: str | None = None,
    limit: int = 100,
    offset: int = 0,
    user_id: str = Depends(get_current_user),
):
    """Return the user's generated reports (metadata only, payloads excluded)."""
    if user_id == "anonymous":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in to view your reports.",
        )
    from .reports import get_report_store

    store = get_report_store()
    items = store.list(user_id, kind=kind, limit=min(limit, 500), offset=max(offset, 0))
    counts = store.count(user_id)
    return {
        "reports": items,
        "counts": counts,
        "total": counts.get("_total", 0),
        "total_bytes": counts.get("_total_bytes", 0),
    }


@router.get(
    "/reports/{report_id}",
    tags=["reports"],
    summary="Fetch a previously generated report by id",
)
async def get_report(
    report_id: str,
    user_id: str = Depends(get_current_user),
):
    if user_id == "anonymous":
        raise HTTPException(status_code=401, detail="Sign in to view reports.")
    from .reports import get_report_store

    rec = get_report_store().get(user_id, report_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return rec


@router.get(
    "/reports/{report_id}/staleness",
    tags=["reports"],
    summary="Check whether a report's underlying evidence has drifted",
)
async def get_report_staleness(
    report_id: str,
    user_id: str = Depends(get_current_user),
):
    """Compare the report's stored derivation manifest to a fresh snapshot.

    Closes Gap #7 from ``COMPLIANCE_MODEL_GAPS.md``: a deliverable signed
    last week is no longer trustworthy if a referenced artefact has been
    re-uploaded or the proxy has logged new injection attempts. Returns
    ``{is_stale, reasons}`` so the UI can prompt re-running the recipe.
    """
    if user_id == "anonymous":
        raise HTTPException(status_code=401, detail="Sign in to view reports.")
    from .reports import get_report_store

    rec = get_report_store().get(user_id, report_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Report not found")

    old_manifest = rec.get("derivation") or {}
    if not old_manifest:
        # Pre-Gap-#7 reports have no manifest to diff against.
        return {
            "report_id": report_id,
            "is_stale": False,
            "reasons": [],
            "tracked": False,
        }

    # Build a fresh manifest from the current substrate.
    from ..recipes.derivation import DerivationManifest, build_manifest, diff_manifests

    artefact_index: dict[str, str] = {}
    proxy_window: dict[str, Any] = {}
    corpus_manifest_hash = ""
    try:
        from .artefacts import get_artefact_store

        for art in get_artefact_store().list(user_id):
            sha = (art.get("sha256") if isinstance(art, dict) else getattr(art, "sha256", "")) or ""
            aid = (art.get("id") if isinstance(art, dict) else getattr(art, "id", "")) or ""
            if sha and aid:
                artefact_index[aid] = sha
    except Exception as _bandit_exc:
        logger.debug("swallowed in manifest (artefact index best-effort): %s", _bandit_exc)
        pass
    try:
        from ..proxy.routes import _get_interceptor

        stats = _get_interceptor().get_compliance_stats(user_id)
        if stats is not None:
            proxy_window = stats.model_dump() if hasattr(stats, "model_dump") else dict(stats)
    except Exception as _bandit_exc:
        logger.debug("swallowed in manifest (proxy stats best-effort): %s", _bandit_exc)
        pass
    try:
        import hashlib
        from pathlib import Path as _P

        cmp = _P("corpus") / "_scraped" / "manifest.json"
        if cmp.exists():
            corpus_manifest_hash = hashlib.sha256(cmp.read_bytes()).hexdigest()
    except Exception as _bandit_exc:
        logger.debug("swallowed in manifest (corpus manifest best-effort): %s", _bandit_exc)
        pass

    payload = rec.get("payload", {}) or {}
    profile = payload.get("profile", {}) if isinstance(payload, dict) else {}
    inputs = payload.get("inputs", {}) if isinstance(payload, dict) else {}
    fresh = build_manifest(
        recipe_id=old_manifest.get("recipe_id", rec.get("kind", "")),
        recipe_version=old_manifest.get("recipe_version", ""),
        profile=profile if isinstance(profile, dict) else {},
        inputs=inputs if isinstance(inputs, dict) else {},
        artefact_index=artefact_index,
        proxy_window=proxy_window,
        corpus_manifest_hash=corpus_manifest_hash,
    )
    old = DerivationManifest.from_dict(old_manifest)
    reasons = diff_manifests(old, fresh)
    return {
        "report_id": report_id,
        "is_stale": bool(reasons),
        "reasons": reasons,
        "tracked": True,
        "old_manifest": old.to_dict(),
        "current_manifest": fresh.to_dict(),
    }


@router.get(
    "/reports/{report_id}/markdown",
    tags=["reports"],
    summary="Download a report as markdown",
)
async def download_report_markdown(
    report_id: str,
    user_id: str = Depends(get_current_user),
):
    from fastapi.responses import Response

    if user_id == "anonymous":
        raise HTTPException(status_code=401, detail="Sign in to download reports.")
    from .reports import get_report_store

    rec = get_report_store().get(user_id, report_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Report not found")
    md = rec.get("markdown")
    if not md:
        # Synthesise a minimal markdown from the JSON payload
        import json as _json

        md = (
            f"# {rec.get('kind', 'report').replace('_', ' ').title()}\n\n"
            f"**System:** {rec.get('system_name')}\n\n"
            f"**Generated:** {rec.get('created_at')}\n\n"
            f"**Tier:** {rec.get('tier')}\n\n"
            f"## Payload\n\n```json\n"
            f"{_json.dumps(rec.get('payload', {}), indent=2, default=str)}\n```\n"
        )
    system = (rec.get("system_name") or "report").replace(" ", "-")
    kind = rec.get("kind", "report")
    filename = f"crp-comply-{kind}-{system}-{report_id[:8]}.md"
    return Response(
        content=md,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete(
    "/reports/{report_id}",
    tags=["reports"],
    summary="Delete a stored report",
)
async def delete_report(
    report_id: str,
    user_id: str = Depends(get_current_user),
):
    if user_id == "anonymous":
        raise HTTPException(status_code=401, detail="Sign in to delete reports.")
    from .reports import get_report_store

    removed = get_report_store().delete(user_id, report_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"deleted": True, "report_id": report_id}


# ── Evidence Packs — list, manifest, zip download, delete ─────
@router.get(
    "/evidence-packs",
    tags=["reports"],
    summary="List evidence packs built for the current user",
)
async def list_evidence_packs(
    limit: int = 50,
    user_id: str = Depends(get_current_user),
):
    if user_id == "anonymous":
        raise HTTPException(status_code=401, detail="Sign in to view evidence packs.")
    from .reports import get_pack_builder

    return {"packs": get_pack_builder().list(user_id, limit=min(limit, 200))}


@router.get(
    "/evidence-packs/{pack_id}",
    tags=["reports"],
    summary="Fetch the manifest for an evidence pack",
)
async def get_evidence_pack(
    pack_id: str,
    user_id: str = Depends(get_current_user),
):
    if user_id == "anonymous":
        raise HTTPException(status_code=401, detail="Sign in to view evidence packs.")
    from .reports import get_pack_builder

    manifest = get_pack_builder().get_manifest(user_id, pack_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="Evidence pack not found")
    return manifest


@router.get(
    "/evidence-packs/{pack_id}/download",
    tags=["reports"],
    summary="Download the evidence pack as a zip archive",
)
async def download_evidence_pack(
    pack_id: str,
    user_id: str = Depends(get_current_user),
):
    from fastapi.responses import FileResponse

    if user_id == "anonymous":
        raise HTTPException(status_code=401, detail="Sign in to download evidence packs.")
    from .reports import get_pack_builder

    zip_path = get_pack_builder().get_zip(user_id, pack_id)
    if zip_path is None:
        raise HTTPException(status_code=404, detail="Evidence pack not found")
    return FileResponse(
        path=str(zip_path),
        media_type="application/zip",
        filename=f"crp-comply-evidence-{pack_id[:8]}.zip",
    )


@router.delete(
    "/evidence-packs/{pack_id}",
    tags=["reports"],
    summary="Delete an evidence pack",
)
async def delete_evidence_pack(
    pack_id: str,
    user_id: str = Depends(get_current_user),
):
    if user_id == "anonymous":
        raise HTTPException(status_code=401, detail="Sign in to delete evidence packs.")
    from .reports import get_pack_builder

    removed = get_pack_builder().delete(user_id, pack_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Evidence pack not found")
    return {"deleted": True, "pack_id": pack_id}


@router.get(
    "/ckf/export",
    tags=["ckf"],
    summary="Export the user's customer knowledge file (GDPR Art. 20 portability)",
)
async def export_ckf(
    user_id: str = Depends(get_current_user),
):
    """Return a gzipped tarball containing the user's CKF facts, events, and persisted files.

    This endpoint supports GDPR Article 20 data-portability requests by packaging
    all customer-knowledge data the tenant has contributed into a self-contained,
    machine-readable archive.
    """
    if user_id == "anonymous":
        raise HTTPException(status_code=401, detail="Sign in to export your data.")

    from ..agent.ckf import CKFStore

    try:
        store = CKFStore.for_user(user_id)
        buf = store.export_tarball()
    except Exception as exc:
        logger.exception("CKF export failed for %s", user_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"CKF export failed: {exc}",
        ) from exc

    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in user_id)[:64]
    filename = f"ckf-export-{safe_id}.tar.gz"
    return StreamingResponse(
        buf,
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/auth/exchange",
    tags=["auth"],
    summary="Exchange Clerk JWT for a CRP API key",
)
async def exchange_token(
    user_id: str = Depends(get_current_user),
    tier: Tier = Depends(get_current_tier),
    auth: AuthManager = Depends(get_auth),
):
    """Exchange an authenticated session (Clerk JWT) for a CRP API key.

    If the user already has an API key, returns the existing key metadata.
    Otherwise, auto-creates one named 'auto'.
    """
    if user_id == "anonymous":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in to get an API key",
        )

    # Check if user already has a key
    existing = auth.list_api_keys(user_id=user_id)
    if existing:
        return {
            "status": "existing",
            "key_id": existing[0].id,
            "key_prefix": existing[0].key_prefix,
            "tier": tier.value,
            "message": "API key already exists. Use the Settings page to manage keys.",
        }

    # Auto-create a key for this user
    created = auth.create_api_key(user_id=user_id, name="auto")
    return {
        "status": "created",
        "key_id": created.id,
        "key": created.key,
        "key_prefix": created.key_prefix,
        "tier": tier.value,
        "message": "API key created. Store it securely — it won't be shown again.",
    }


# ── API Key Management ─────────────────────────────────────────
DEFAULT_ADMIN_USER = "local:admin"


@router.post(
    "/keys",
    response_model=APIKeyCreated,
    tags=["auth"],
    summary="Create a new API key",
)
async def create_api_key(
    req: APIKeyCreateRequest,
    user_id: str = Depends(get_current_user),
    auth: AuthManager = Depends(get_auth),
):
    # For authenticated users, create the key under their account
    if user_id != "anonymous":
        # Ensure user record exists
        if not auth.get_user(user_id):
            auth.upsert_oauth_user(
                provider="clerk",
                provider_id=user_id.replace("clerk:", ""),
                email=f"{user_id}@clerk",
                name=user_id,
            )
        return auth.create_api_key(
            user_id=user_id, name=req.name, expires_in_days=req.expires_in_days
        )

    # Fallback: self-hosted admin model
    user = auth.get_user(DEFAULT_ADMIN_USER)
    if not user:
        auth.upsert_oauth_user(
            provider="local",
            provider_id="admin",
            email="admin@localhost",
            name="Admin",
        )
    auth.set_user_tier(DEFAULT_ADMIN_USER, Tier(req.tier.value) if req.tier else Tier.FREE)
    return auth.create_api_key(
        user_id=DEFAULT_ADMIN_USER, name=req.name, expires_in_days=req.expires_in_days
    )


@router.get(
    "/keys",
    response_model=list[APIKeyResponse],
    tags=["auth"],
    summary="List all API keys",
)
async def list_api_keys(
    user_id: str = Depends(get_current_user),
    auth: AuthManager = Depends(get_auth),
):
    target = user_id if user_id != "anonymous" else DEFAULT_ADMIN_USER
    return auth.list_api_keys(user_id=target)


@router.post(
    "/keys/rotate",
    response_model=APIKeyCreated,
    tags=["auth"],
    summary="Rotate API keys (revoke all existing, create a new one)",
)
async def rotate_api_keys(
    user_id: str = Depends(get_current_user),
    auth: AuthManager = Depends(get_auth),
):
    target = user_id if user_id != "anonymous" else DEFAULT_ADMIN_USER
    for key in auth.list_api_keys(user_id=target):
        auth.revoke_api_key(user_id=target, key_id=key.id)
    return auth.create_api_key(user_id=target, name="rotated")


@router.delete(
    "/keys/{key_id}",
    tags=["auth"],
    summary="Revoke an API key",
)
async def revoke_api_key(
    key_id: str,
    user_id: str = Depends(get_current_user),
    auth: AuthManager = Depends(get_auth),
):
    target = user_id if user_id != "anonymous" else DEFAULT_ADMIN_USER
    if not auth.revoke_api_key(user_id=target, key_id=key_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found",
        )
    return {"status": "revoked", "key_id": key_id}


# ── GAP-015: Metrics (CRP MetricsExporter + HealthMonitor) ────

_metrics = None
_health_monitor = None


def _get_metrics():
    global _metrics
    if _metrics is None:
        from crp.observability import MetricsExporter

        _metrics = MetricsExporter()
    return _metrics


def _get_health_monitor():
    global _health_monitor
    if _health_monitor is None:
        from crp.observability import HealthMonitor

        _health_monitor = HealthMonitor()
        _health_monitor.add_check("proxy", lambda: True)
        _health_monitor.add_check("auth", lambda: _get_metrics() is not None)
    return _health_monitor


@router.get("/metrics", tags=["system"])
async def metrics_endpoint():
    """Prometheus-format metrics for Railway monitoring."""
    try:
        from crp.observability import ExportFormat

        m = _get_metrics()
        return {"metrics": m.export(ExportFormat.JSON)}
    except ImportError:
        return {"metrics": {}}


@router.get("/health/detailed", tags=["system"])
async def detailed_health():
    """Detailed health probe using CRP HealthMonitor."""
    try:
        hm = _get_health_monitor()
        status = hm.probe()
        base = {
            "alive": status.alive,
            "ready": status.ready,
            "details": status.details,
        }
    except Exception:
        base = {"alive": True, "ready": True, "details": {}}

    # Volume persistence status (helpful for Railway / Fly / k8s operators)
    try:
        from .persistence_probe import build_status_dict

        base["volume"] = build_status_dict()
    except Exception:
        base["volume"] = {"probed": False}
    return base


# ── GAP-016: Per-User Dashboard Stats ─────────────────────────


@router.get("/dashboard/stats", tags=["dashboard"])
async def user_dashboard_stats(
    user_id: str = Depends(get_current_user),
    tier: Tier = Depends(get_current_tier),
):
    """Per-user dashboard statistics — proxy usage, PII detections, compliance."""
    from ..proxy.routes import _interceptor

    stats = {
        "user_id": user_id,
        "tier": tier.value,
        "total_requests": 0,
        "pii_detections": 0,
        "injection_attempts": 0,
        "compliance_rate": 0.0,
        "models_used": {},
        "risk_distribution": {},
    }

    if _interceptor is None:
        return stats

    # Get per-user compliance stats
    user_filter = user_id if user_id != "anonymous" else None
    cs = _interceptor.get_compliance_stats(user_id=user_filter)
    stats["total_requests"] = cs.total_requests
    stats["pii_detections"] = cs.pii_detections
    stats["injection_attempts"] = cs.injection_attempts
    stats["compliance_rate"] = cs.compliance_rate
    stats["models_used"] = cs.models_used
    stats["risk_distribution"] = cs.risk_distribution

    return stats


# ── GAP-018: Certificate Signing with FactIntegrityChain ──────


@router.post(
    "/certificate",
    response_model=SignedCertificate,
    tags=["cloud"],
    summary="Issue a digitally signed compliance certificate (CLOUD tier)",
)
async def issue_certificate(
    req: CertificateRequest,
    comply: CRPComply = Depends(get_comply),
    tier: Tier = Depends(get_current_tier),
    auth: AuthManager = Depends(get_auth),
):
    _require_feature(tier, "signed_certificates")

    # Run risk assessment
    risk = comply.assess_risk(category=req.category)
    risk_dict = risk.to_dict() if hasattr(risk, "to_dict") else risk
    risk_level = risk_dict.get("risk_level", "MINIMAL").upper()

    # Run compliance report
    report = comply.compliance_report()
    score = report.get("score", 0.0)

    now = datetime.now(timezone.utc)
    cert_id = f"CRC-{uuid.uuid4().hex[:12].upper()}"
    issued_at = now.isoformat()
    expires_at = (now + timedelta(days=CERTIFICATE_VALIDITY_DAYS)).isoformat()

    # Build the canonical payload for signing
    payload = (
        f"{cert_id}|{req.system_name}|{req.organisation}|"
        f"{risk_level}|{score}|{issued_at}|{expires_at}"
    )

    # Use FactIntegrityChain (BLAKE3+HMAC) for tamper-evident signing
    try:
        from crp.ckf import FactIntegrityChain

        chain = FactIntegrityChain(session_key=auth._jwt_secret)
        chain.add_fact(cert_id, payload)
        signature = chain.get_hash(cert_id) or ""
        chain_sig = chain.chain_signature()
        # Store chain signature alongside certificate for later verification
        signature = f"{signature}:{chain_sig}"
    except (ImportError, Exception):
        # Fallback to HMAC-SHA256
        signature = hmac.new(
            auth._jwt_secret.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()

    return SignedCertificate(
        certificate_id=cert_id,
        system_name=req.system_name,
        organisation=req.organisation,
        risk_level=risk_level,
        compliance_score=score,
        frameworks=["EU AI Act", "ISO 42001", "GDPR Art. 35"],
        issued_at=issued_at,
        expires_at=expires_at,
        issuer=CERTIFICATE_ISSUER,
        signature=signature,
        verification_url=f"https://crprotocol.io/verify/{cert_id}",
    )


# ── GAP-020: Rate Limiting (CRP RBACEnforcer) ─────────────────

import threading as _threading

_rate_limiters: dict[str, object] = {}
_rate_lock = _threading.Lock()

_TIER_RATE_LIMITS = {
    "free": {"dispatch_per_minute": 10, "ingest_mb_per_minute": 5.0},
    "pro": {"dispatch_per_minute": 60, "ingest_mb_per_minute": 100.0},
    "enterprise": {"dispatch_per_minute": 300, "ingest_mb_per_minute": 500.0},
    "cloud": {"dispatch_per_minute": 1000, "ingest_mb_per_minute": 1000.0},
}


def check_rate_limit(user_id: str, tier_val: str) -> None:
    """Check and enforce per-user rate limits using CRP RBACEnforcer."""
    try:
        from crp.security import RBACEnforcer, RateLimitConfig
        from crp.security.rbac import Role

        with _rate_lock:
            if user_id not in _rate_limiters:
                limits = _TIER_RATE_LIMITS.get(tier_val, _TIER_RATE_LIMITS["free"])
                config = RateLimitConfig(
                    dispatch_per_minute=limits["dispatch_per_minute"],
                    ingest_mb_per_minute=limits["ingest_mb_per_minute"],
                )
                _rate_limiters[user_id] = RBACEnforcer(role=Role.OPERATOR, config=config)
            enforcer = _rate_limiters[user_id]

        allowed = enforcer.check_rate_limit("dispatch")
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded for tier '{tier_val}'. Please wait.",
            )
        enforcer.record_dispatch()
    except ImportError:
        pass
    except HTTPException:
        raise
    except Exception as _bandit_exc:
        logger.debug(
            "swallowed in audit_trail_enforcement (CRP integration best-effort): %s", _bandit_exc
        )
        pass


# ── GAP-022: Audit Trail Tamper Protection (FactIntegrityChain) ──

_audit_chain = None


def _get_audit_chain():
    """Get or create the FactIntegrityChain for audit trail tamper protection."""
    global _audit_chain
    if _audit_chain is None:
        try:
            from crp.ckf import FactIntegrityChain
            import os

            session_key = os.environ.get("CRP_COMPLY_JWT_SECRET", "comply-audit")
            _audit_chain = FactIntegrityChain(session_key=session_key)
        except ImportError:
            return None
    return _audit_chain


@router.post("/audit-chain/add", tags=["audit"])
async def add_to_audit_chain(
    body: dict,
    user_id: str = Depends(get_current_user),
    tier: Tier = Depends(get_current_tier),
):
    """Add a fact to the tamper-evident audit chain."""
    _require_feature(tier, "session_audit")

    chain = _get_audit_chain()
    if chain is None:
        raise HTTPException(503, "FactIntegrityChain not available")

    fact_id = body.get("fact_id", str(uuid.uuid4()))
    text = body.get("text", "")
    if not text:
        raise HTTPException(400, "Provide 'text' field")

    chain.add_fact(fact_id, text)
    return {
        "fact_id": fact_id,
        "hash": chain.get_hash(fact_id),
        "chain_signature": chain.chain_signature(),
    }


@router.get("/audit-chain/verify", tags=["audit"])
async def verify_audit_chain(
    user_id: str = Depends(get_current_user),
    tier: Tier = Depends(get_current_tier),
):
    """Verify the tamper-evident audit chain integrity."""
    _require_feature(tier, "session_audit")

    chain = _get_audit_chain()
    if chain is None:
        raise HTTPException(503, "FactIntegrityChain not available")

    signature = chain.chain_signature()
    valid = chain.verify_chain(signature)
    return {
        "chain_valid": valid,
        "chain_signature": signature,
        "algorithm": "BLAKE3+HMAC" if hasattr(chain, "_blake3") else "SHA256+HMAC",
    }


@router.get("/audit-chain/export", tags=["audit"])
async def export_audit_chain(
    user_id: str = Depends(get_current_user),
    tier: Tier = Depends(get_current_tier),
):
    """Export the audit chain for external verification."""
    _require_feature(tier, "session_audit")

    chain = _get_audit_chain()
    if chain is None:
        raise HTTPException(503, "FactIntegrityChain not available")

    return chain.export_for_verification()


# ── GAP-024: ContextualKnowledgeFabric (Per-User Instances) ────

import os as _os

_ckf_instances: dict[str, object] = {}
_ckf_lock = _threading.Lock()


def _safe_dir_name(name: str) -> str:
    """Sanitize a string for use as a directory name."""
    import re as _re_mod

    return _re_mod.sub(r"[^a-zA-Z0-9_\-]", "_", name)


def _get_user_ckf(user_id: str):
    """Get or create a per-user CKF instance with persistence."""
    with _ckf_lock:
        if user_id not in _ckf_instances:
            try:
                from crp.ckf.fabric import ContextualKnowledgeFabric, CKFConfig

                data_dir = _os.environ.get("CRP_COMPLY_DATA_DIR", "data")
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
                ckf = ContextualKnowledgeFabric(config)
                if Path(persist_path).exists():
                    try:
                        ckf.restore(persist_path)
                    except Exception as _bandit_exc:
                        logger.debug("swallowed in ckf_restore (best-effort): %s", _bandit_exc)
                        pass
                _ckf_instances[user_id] = ckf
            except ImportError:
                return None
        return _ckf_instances.get(user_id)


@router.get("/knowledge/health", tags=["knowledge"])
async def knowledge_health(
    user_id: str = Depends(get_current_user),
    tier: Tier = Depends(get_current_tier),
):
    """Per-user CKF health — fact count, memory usage, GC status."""
    ckf = _get_user_ckf(user_id)
    if ckf is None:
        raise HTTPException(status_code=503, detail="ContextualKnowledgeFabric not available")

    try:
        health = ckf.health()
        return {
            "user_id": user_id,
            "health": health.to_dict() if hasattr(health, "to_dict") else str(health),
            "should_gc": ckf.should_gc(),
        }
    except Exception as exc:
        return {"user_id": user_id, "health": str(exc), "should_gc": False}


@router.get("/knowledge/communities", tags=["knowledge"])
async def knowledge_communities(
    limit: int = 20,
    user_id: str = Depends(get_current_user),
    tier: Tier = Depends(get_current_tier),
):
    """CRP_AUDIT_4 §C.15 — surface ``ckf.detect_communities`` so the
    UI can render a "topics covered in this conversation" pane.
    Requires the ``crprotocol[full]`` extra (igraph + leidenalg).
    Returns ``[]`` on a base install or empty fabric."""
    ckf = _get_user_ckf(user_id)
    if ckf is None:
        raise HTTPException(status_code=503, detail="ContextualKnowledgeFabric not available")
    from ..agent.crp_integration import crp_ckf_communities

    return {"communities": crp_ckf_communities(ckf, limit=int(limit))}


@router.get("/knowledge/graph-walk", tags=["knowledge"])
async def knowledge_graph_walk(
    seed: str,
    max_hops: int = 2,
    limit: int = 50,
    user_id: str = Depends(get_current_user),
    tier: Tier = Depends(get_current_tier),
):
    """CRP_AUDIT_4 §C.15 — surface ``ckf.graph_walk`` for multi-hop
    fact expansion. ``seed`` is a comma-separated list of fact IDs."""
    ckf = _get_user_ckf(user_id)
    if ckf is None:
        raise HTTPException(status_code=503, detail="ContextualKnowledgeFabric not available")
    from ..agent.crp_integration import crp_ckf_graph_walk

    seeds = [s.strip() for s in seed.split(",") if s.strip()]
    if not seeds:
        raise HTTPException(
            status_code=400, detail="Provide at least one seed fact_id via ?seed=..."
        )
    return {
        "seeds": seeds,
        "max_hops": int(max_hops),
        "facts": crp_ckf_graph_walk(ckf, seed_ids=seeds, max_hops=int(max_hops), limit=int(limit)),
    }


@router.post("/knowledge/store", tags=["knowledge"])
async def knowledge_store(
    body: dict,
    user_id: str = Depends(get_current_user),
    tier: Tier = Depends(get_current_tier),
):
    """Store facts in the per-user knowledge fabric."""
    ckf = _get_user_ckf(user_id)
    if ckf is None:
        raise HTTPException(status_code=503, detail="ContextualKnowledgeFabric not available")

    facts = body.get("facts", [])
    window_id = body.get("window_id", "")
    if not facts:
        raise HTTPException(status_code=400, detail="Provide 'facts' list")

    try:
        from crp.ckf.fabric import Fact as CKFFact

        fact_objs = []
        for f in facts:
            if isinstance(f, dict):
                fact_objs.append(CKFFact(text=f.get("text", ""), source_window_id=window_id))
            else:
                fact_objs.append(f)
        ckf.store(fact_objs, window_id=window_id)
        config = getattr(ckf, "_config", None)
        if config and config.persist_path:
            try:
                ckf.persist(config.persist_path)
            except Exception as _bandit_exc:
                logger.debug("swallowed in ckf_persist (best-effort): %s", _bandit_exc)
                pass
        return {"stored": len(facts), "user_id": user_id}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Store failed: {exc}")


# ── GAP-025: Observability / Telemetry ──────────────────────────

_event_emitter_comply = None
_audit_log_comply = None
_quality_reporter_comply = None


def _get_event_emitter_comply():
    global _event_emitter_comply
    if _event_emitter_comply is None:
        try:
            from crp.observability.events import EventEmitter

            _event_emitter_comply = EventEmitter(max_listeners_per_event=100)
            _event_emitter_comply.start()
        except ImportError:
            pass
    return _event_emitter_comply


_telemetry_writers_comply: dict[str, Any] = {}
_telemetry_writers_lock = _threading.Lock()


def _get_telemetry_writer_comply(user_id: str = "shared"):
    """Get or create a per-user telemetry writer."""
    with _telemetry_writers_lock:
        if user_id not in _telemetry_writers_comply:
            try:
                from crp.observability.telemetry import TelemetryWriter

                data_dir = _os.environ.get("CRP_COMPLY_DATA_DIR", "data")
                telemetry_dir = Path(data_dir) / "telemetry" / _safe_dir_name(user_id)
                telemetry_dir.mkdir(parents=True, exist_ok=True)
                _telemetry_writers_comply[user_id] = TelemetryWriter(
                    str(telemetry_dir / "comply.jsonl")
                )
            except ImportError:
                return None
        return _telemetry_writers_comply.get(user_id)


def _get_audit_log_comply():
    global _audit_log_comply
    if _audit_log_comply is None:
        try:
            from crp.observability.audit import AuditLog

            _audit_log_comply = AuditLog()
        except ImportError:
            pass
    return _audit_log_comply


def _get_quality_reporter_comply():
    global _quality_reporter_comply
    if _quality_reporter_comply is None:
        try:
            from crp.observability.quality import QualityReporter

            _quality_reporter_comply = QualityReporter()
        except ImportError:
            pass
    return _quality_reporter_comply


@router.get("/telemetry", tags=["observability"])
async def get_telemetry(
    user_id: str = Depends(get_current_user),
    tier: Tier = Depends(get_current_tier),
):
    """Read recent telemetry data for the current user only."""
    import json as _json_mod

    data_dir = _os.environ.get("CRP_COMPLY_DATA_DIR", "data")
    telemetry_file = Path(data_dir) / "telemetry" / _safe_dir_name(user_id) / "comply.jsonl"
    if not telemetry_file.exists():
        return {"records": [], "total": 0, "user_id": user_id}

    records = []
    try:
        lines = telemetry_file.read_text(encoding="utf-8").strip().split("\n")
        for line in lines[-100:]:
            if line.strip():
                records.append(_json_mod.loads(line))
    except Exception as _bandit_exc:
        logger.debug("swallowed in telemetry_read (best-effort): %s", _bandit_exc)
        pass
    return {"records": records, "total": len(records), "user_id": user_id}


@router.get("/quality", tags=["observability"])
async def quality_report(
    user_id: str = Depends(get_current_user),
    tier: Tier = Depends(get_current_tier),
):
    """Quality report for the compliance proxy."""
    reporter = _get_quality_reporter_comply()
    if reporter is None:
        return {"quality": "unknown", "reporter_available": False}

    try:
        qr = reporter.assess(overhead_pct=5.0, fact_miss_pct=0.0)
        return {
            "tier": qr.tier.name if hasattr(qr.tier, "name") else str(qr.tier),
            "reporter_available": True,
        }
    except Exception:
        return {"quality": "unknown", "reporter_available": True}


@router.post("/events/emit", tags=["observability"])
async def emit_event(
    body: dict,
    user_id: str = Depends(get_current_user),
    tier: Tier = Depends(get_current_tier),
):
    """Emit a CRP event for observability pipeline."""
    emitter = _get_event_emitter_comply()
    if emitter is None:
        raise HTTPException(status_code=503, detail="EventEmitter not available")

    event_type = body.get("event_type", "")
    data = body.get("data", {})
    if not event_type:
        raise HTTPException(status_code=400, detail="Provide 'event_type' field")

    try:
        data["_user_id"] = user_id
        emitter.emit(event_type, data)
        # Write to per-user telemetry
        writer = _get_telemetry_writer_comply(user_id)
        if writer:
            try:
                writer.write({"event_type": event_type, "user_id": user_id, **data})
            except Exception as _bandit_exc:
                logger.debug("swallowed in emit_event (best-effort): %s", _bandit_exc)
                pass
        return {"emitted": True, "event_type": event_type, "user_id": user_id}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Emit failed: {exc}")


# ── GAP-029: RetentionManager + DataLineageTracker ──────────────

_retention_manager = None
_lineage_tracker = None


def _get_retention_manager():
    global _retention_manager
    if _retention_manager is None:
        try:
            from crp.security.privacy import RetentionManager, RetentionPolicy

            policy = RetentionPolicy(
                default_retention_hours=720,
                auto_purge=True,
            )
            _retention_manager = RetentionManager(policy=policy)
        except ImportError:
            pass
    return _retention_manager


def _get_lineage_tracker():
    global _lineage_tracker
    if _lineage_tracker is None:
        try:
            from crp.security.privacy import DataLineageTracker

            _lineage_tracker = DataLineageTracker()
        except ImportError:
            pass
    return _lineage_tracker


@router.post("/retention/register", tags=["privacy"])
async def register_data_retention(
    body: dict,
    user_id: str = Depends(get_current_user),
    tier: Tier = Depends(get_current_tier),
):
    """Register data for retention policy tracking."""
    _require_feature(tier, "session_audit")

    mgr = _get_retention_manager()
    if mgr is None:
        raise HTTPException(status_code=503, detail="RetentionManager not available")

    data_id = body.get("data_id", str(uuid.uuid4()))
    classification = body.get("classification", "INTERNAL")
    source_label = body.get("source_label", "")

    try:
        from crp.security.privacy import DataClassification

        cls_map = {
            "PUBLIC": DataClassification.PUBLIC,
            "INTERNAL": DataClassification.INTERNAL,
            "CONFIDENTIAL": DataClassification.CONFIDENTIAL,
            "RESTRICTED": DataClassification.RESTRICTED,
            "CRITICAL": DataClassification.CRITICAL,
        }
        cls = cls_map.get(classification.upper(), DataClassification.INTERNAL)
        mgr.register(data_id, cls, source_label)
        return {"registered": True, "data_id": data_id, "classification": classification}
    except ImportError:
        raise HTTPException(status_code=503, detail="DataClassification not available")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Registration failed: {exc}")


@router.get("/retention/expired", tags=["privacy"])
async def get_expired_data(
    user_id: str = Depends(get_current_user),
    tier: Tier = Depends(get_current_tier),
):
    """Get data items that have exceeded their retention period."""
    _require_feature(tier, "session_audit")

    mgr = _get_retention_manager()
    if mgr is None:
        return {"expired": [], "manager_available": False}

    try:
        expired = mgr.get_expired()
        return {"expired": expired, "manager_available": True}
    except Exception:
        return {"expired": [], "manager_available": True}


@router.post("/retention/enforce", tags=["privacy"])
async def enforce_retention(
    user_id: str = Depends(get_current_user),
    tier: Tier = Depends(get_current_tier),
):
    """Enforce retention policies — purge expired data."""
    _require_feature(tier, "session_audit")

    mgr = _get_retention_manager()
    if mgr is None:
        raise HTTPException(status_code=503, detail="RetentionManager not available")

    try:
        purged = mgr.enforce()
        return {"purged": purged, "count": len(purged)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Enforcement failed: {exc}")


@router.post("/lineage/record", tags=["privacy"])
async def record_lineage(
    body: dict,
    user_id: str = Depends(get_current_user),
    tier: Tier = Depends(get_current_tier),
):
    """Record data lineage for provenance tracking."""
    _require_feature(tier, "session_audit")

    tracker = _get_lineage_tracker()
    if tracker is None:
        raise HTTPException(status_code=503, detail="DataLineageTracker not available")

    data_id = body.get("data_id", str(uuid.uuid4()))
    origin = body.get("origin", "")
    source_label = body.get("source_label", "")
    classification = body.get("classification", "INTERNAL")
    parent_ids = body.get("parent_ids", [])

    try:
        from crp.security.privacy import DataClassification

        cls_map = {
            "PUBLIC": DataClassification.PUBLIC,
            "INTERNAL": DataClassification.INTERNAL,
            "CONFIDENTIAL": DataClassification.CONFIDENTIAL,
            "RESTRICTED": DataClassification.RESTRICTED,
            "CRITICAL": DataClassification.CRITICAL,
        }
        cls = cls_map.get(classification.upper(), DataClassification.INTERNAL)
        # Tag data_id with user ownership for per-user isolation
        prefixed_data_id = f"{_safe_dir_name(user_id)}:{data_id}"
        entry = tracker.record(prefixed_data_id, origin, source_label, cls, parent_ids)
        return {
            "recorded": True,
            "data_id": data_id,
            "entry": entry.to_dict() if hasattr(entry, "to_dict") else str(entry),
        }
    except ImportError:
        raise HTTPException(status_code=503, detail="DataClassification not available")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Lineage record failed: {exc}")


@router.get("/lineage/{data_id}", tags=["privacy"])
async def get_lineage(
    data_id: str,
    user_id: str = Depends(get_current_user),
    tier: Tier = Depends(get_current_tier),
):
    """Get the lineage chain for a data item."""
    _require_feature(tier, "session_audit")

    tracker = _get_lineage_tracker()
    if tracker is None:
        return {"data_id": data_id, "lineage": None, "tracker_available": False}

    try:
        # Enforce per-user ownership by prefixing data_id
        prefixed_data_id = f"{_safe_dir_name(user_id)}:{data_id}"
        lineage = tracker.get_lineage(prefixed_data_id)
        return {
            "data_id": data_id,
            "user_id": user_id,
            "lineage": lineage.to_dict()
            if lineage and hasattr(lineage, "to_dict")
            else str(lineage)
            if lineage
            else None,
            "tracker_available": True,
        }
    except Exception:
        return {"data_id": data_id, "user_id": user_id, "lineage": None, "tracker_available": True}


# ── GAP-030: HumanOversightController ───────────────────────────

_oversight_controller = None


def _get_oversight_controller():
    global _oversight_controller
    if _oversight_controller is None:
        try:
            from crp.security.consent import (
                HumanOversightController,
                HumanOversightLevel,
                OversightConfig,
            )

            config = OversightConfig(
                level=HumanOversightLevel.INFORMED,
                require_approval_for_dispatch=False,
                require_approval_for_ingest=False,
                require_approval_for_export=True,
                require_approval_for_deletion=True,
                halt_on_injection_detection=True,
                halt_on_pii_detection=True,
                max_autonomous_dispatches=100,
            )
            _oversight_controller = HumanOversightController(
                config=config,
            )
        except ImportError:
            pass
    return _oversight_controller


@router.post("/oversight/check", tags=["oversight"])
async def check_oversight(
    body: dict,
    user_id: str = Depends(get_current_user),
    tier: Tier = Depends(get_current_tier),
):
    """Check if an operation requires human approval."""
    _require_feature(tier, "session_audit")

    controller = _get_oversight_controller()
    if controller is None:
        raise HTTPException(status_code=503, detail="HumanOversightController not available")

    operation = body.get("operation", "")
    if not operation:
        raise HTTPException(status_code=400, detail="Provide 'operation' field")

    try:
        requires = controller.requires_approval(operation)
        return {
            "operation": operation,
            "requires_approval": requires,
            "level": controller.level.name
            if hasattr(controller.level, "name")
            else str(controller.level),
            "halt_on_injection": controller.should_halt_on_injection(),
            "halt_on_pii": controller.should_halt_on_pii(),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Oversight check failed: {exc}")


@router.post("/oversight/approve", tags=["oversight"])
async def record_approval(
    body: dict,
    user_id: str = Depends(get_current_user),
    tier: Tier = Depends(get_current_tier),
):
    """Record an approval or denial decision for an oversight event."""
    _require_feature(tier, "session_audit")

    controller = _get_oversight_controller()
    if controller is None:
        raise HTTPException(status_code=503, detail="HumanOversightController not available")

    operation = body.get("operation", "")
    approved = body.get("approved", False)
    reason = body.get("reason", "")

    try:
        event = controller.request_approval(operation, details={"user_id": user_id})
        controller.record_decision(
            event_id=event.event_id if hasattr(event, "event_id") else str(event),
            approved=approved,
            approved_by=user_id,
            reason=reason,
        )
        return {
            "recorded": True,
            "approved": approved,
            "operation": operation,
            "event_id": event.event_id if hasattr(event, "event_id") else str(event),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Approval record failed: {exc}")


@router.get("/oversight/config", tags=["oversight"])
async def get_oversight_config(
    user_id: str = Depends(get_current_user),
    tier: Tier = Depends(get_current_tier),
):
    """Get current human oversight configuration."""
    _require_feature(tier, "session_audit")

    controller = _get_oversight_controller()
    if controller is None:
        return {"config": None, "controller_available": False}

    try:
        config_dict = controller.to_dict()
        return {"config": config_dict, "controller_available": True}
    except Exception:
        return {
            "level": controller.level.name
            if hasattr(controller.level, "name")
            else str(controller.level),
            "controller_available": True,
        }


# ── GAP-031: ScaleModeSelector ──────────────────────────────────

_scale_selector_comply = None


def _get_scale_selector_comply():
    global _scale_selector_comply
    if _scale_selector_comply is None:
        try:
            from crp.advanced.scale_mode import ScaleModeSelector

            _scale_selector_comply = ScaleModeSelector(context_window=128_000)
        except ImportError:
            pass
    return _scale_selector_comply


@router.post("/scale/configure", tags=["scale"])
async def configure_scale(
    body: dict,
    user_id: str = Depends(get_current_user),
    tier: Tier = Depends(get_current_tier),
):
    """Auto-select the right dispatch strategy based on task size."""
    selector = _get_scale_selector_comply()
    if selector is None:
        raise HTTPException(status_code=503, detail="ScaleModeSelector not available")

    estimated_tokens = body.get("estimated_tokens", 50000)
    model_capability = body.get("model_capability", 1)

    try:
        config = selector.configure_session(
            estimated_tokens=estimated_tokens,
            model_capability=model_capability,
        )
        return {
            "quality_tier": config.quality_tier.name
            if hasattr(config.quality_tier, "name")
            else str(config.quality_tier),
            "processing_mode": config.processing_mode,
            "cqs_enabled": config.cqs_enabled,
            "validation_tiers": config.validation_tiers,
            "review_cycles_enabled": config.review_cycles_enabled,
            "planning_window": config.planning_window,
            "hierarchical": config.hierarchical,
            "re_grounding": config.re_grounding,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Scale configuration failed: {exc}")


# ── GAP-033: EmbeddingDefense ────────────────────────────────────

_embedding_defense = None


def _get_embedding_defense():
    global _embedding_defense
    if _embedding_defense is None:
        try:
            from crp.security.embedding_defense import EmbeddingDefense

            _embedding_defense = EmbeddingDefense()
        except ImportError:
            pass
    return _embedding_defense


@router.post("/embeddings/protect", tags=["security"])
async def protect_embeddings(
    body: dict,
    user_id: str = Depends(get_current_user),
    tier: Tier = Depends(get_current_tier),
):
    """Protect embeddings with SQ8 quantization and XOR salting."""
    _require_feature(tier, "session_audit")

    defense = _get_embedding_defense()
    if defense is None:
        raise HTTPException(status_code=503, detail="EmbeddingDefense not available")

    embedding = body.get("embedding", [])
    if not embedding or not isinstance(embedding, list):
        raise HTTPException(status_code=400, detail="Provide 'embedding' as a list of floats")

    try:
        protected = defense.protect(embedding)
        return {
            "protected": True,
            "dimensions": protected.dimensions,
            "scale": protected.scale,
            "zero_point": protected.zero_point,
            "data": protected.to_dict(),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Protection failed: {exc}")


@router.post("/embeddings/recover", tags=["security"])
async def recover_embeddings(
    body: dict,
    user_id: str = Depends(get_current_user),
    tier: Tier = Depends(get_current_tier),
):
    """Recover original embeddings from protected form."""
    _require_feature(tier, "session_audit")

    defense = _get_embedding_defense()
    if defense is None:
        raise HTTPException(status_code=503, detail="EmbeddingDefense not available")

    protected_data = body.get("protected", {})
    if not protected_data:
        raise HTTPException(
            status_code=400, detail="Provide 'protected' dict from protect endpoint"
        )

    try:
        from crp.security.embedding_defense import ProtectedEmbedding

        protected = ProtectedEmbedding.from_dict(protected_data)
        recovered = defense.recover(protected)
        return {"recovered": True, "embedding": recovered, "dimensions": len(recovered)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Recovery failed: {exc}")


# ── Storage Preference (per-user) ──────────────────────────────

_storage_prefs_lock = _threading.Lock()


def _storage_prefs_path() -> Path:
    """Path to the storage preferences JSON file."""
    data_dir = _os.environ.get("CRP_COMPLY_DATA_DIR", "data")
    p = Path(data_dir) / "storage_prefs.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_storage_prefs() -> dict:
    """Load all user storage preferences."""
    import json as _json_mod

    p = _storage_prefs_path()
    if p.exists():
        try:
            return _json_mod.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_storage_prefs(prefs: dict) -> None:
    """Persist storage preferences."""
    import json as _json_mod

    _storage_prefs_path().write_text(_json_mod.dumps(prefs, indent=2), encoding="utf-8")


@router.get("/storage/preference", tags=["storage"])
async def get_storage_preference(
    user_id: str = Depends(get_current_user),
    tier: Tier = Depends(get_current_tier),
):
    """Get the current user's storage location preference."""
    with _storage_prefs_lock:
        prefs = _load_storage_prefs()
        user_pref = prefs.get(_safe_dir_name(user_id), {})

    cloud_data_dir = _os.environ.get("CRP_COMPLY_CLOUD_DATA_DIR", "")
    local_data_dir = _os.environ.get("CRP_COMPLY_DATA_DIR", "data")
    return {
        "user_id": user_id,
        "storage_mode": user_pref.get("mode", "local"),
        "local_data_dir": local_data_dir,
        "cloud_available": bool(cloud_data_dir),
        "cloud_data_dir": cloud_data_dir if cloud_data_dir else None,
    }


@router.post("/storage/preference", tags=["storage"])
async def set_storage_preference(
    body: dict,
    user_id: str = Depends(get_current_user),
    tier: Tier = Depends(get_current_tier),
):
    """Set the current user's storage location preference.

    mode: 'local' — store on the user's machine (default data dir)
    mode: 'cloud' — store on Railway persistent volume (CRP_COMPLY_CLOUD_DATA_DIR)
    """
    import time as _time_mod

    mode = body.get("mode", "local")
    if mode not in ("local", "cloud"):
        raise HTTPException(status_code=400, detail="mode must be 'local' or 'cloud'")

    cloud_data_dir = _os.environ.get("CRP_COMPLY_CLOUD_DATA_DIR", "")
    if mode == "cloud" and not cloud_data_dir:
        raise HTTPException(
            status_code=400,
            detail="Cloud storage is not configured. Set CRP_COMPLY_CLOUD_DATA_DIR env var.",
        )

    with _storage_prefs_lock:
        prefs = _load_storage_prefs()
        safe_uid = _safe_dir_name(user_id)
        prefs[safe_uid] = {
            "mode": mode,
            "updated_at": _time_mod.time(),
        }
        _save_storage_prefs(prefs)

    local_data_dir = _os.environ.get("CRP_COMPLY_DATA_DIR", "data")
    return {
        "user_id": user_id,
        "storage_mode": mode,
        "effective_data_dir": cloud_data_dir if mode == "cloud" else local_data_dir,
    }


def get_user_data_dir(user_id: str) -> str:
    """Return the effective data directory for a given user based on preference."""
    with _storage_prefs_lock:
        prefs = _load_storage_prefs()
        user_pref = prefs.get(_safe_dir_name(user_id), {})

    if user_pref.get("mode") == "cloud":
        cloud_dir = _os.environ.get("CRP_COMPLY_CLOUD_DATA_DIR", "")
        if cloud_dir:
            return cloud_dir

    return _os.environ.get("CRP_COMPLY_DATA_DIR", "data")


# ── Admin Panel Endpoints ──────────────────────────────────────

_ADMIN_SECRET = _os.environ.get("CRP_ADMIN_SECRET", "")


def _require_admin(request: Request) -> None:
    """Verify admin access via X-Admin-Secret header or env var."""
    if not _ADMIN_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin access not configured. Set CRP_ADMIN_SECRET env var.",
        )
    provided = request.headers.get("X-Admin-Secret", "")
    if not hmac.compare_digest(provided, _ADMIN_SECRET):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid admin credentials.",
        )


@router.get("/admin/users", tags=["admin"])
async def admin_list_users(
    request: Request,
    auth: AuthManager = Depends(get_auth),
):
    """List all users with statistics (admin only)."""
    _require_admin(request)

    users_list = []
    tier_dist: dict[str, int] = {}
    disabled_count = 0
    total_keys = 0

    for uid, u in auth._users.items():
        tier_val = u.get("tier", "free")
        tier_dist[tier_val] = tier_dist.get(tier_val, 0) + 1
        is_disabled = u.get("disabled", False)
        if is_disabled:
            disabled_count += 1

        # Count API keys for this user
        key_count = sum(1 for entry in auth._api_keys.values() if entry.get("user_id") == uid)
        total_keys += key_count

        users_list.append(
            {
                "user_id": uid,
                "email": u.get("email"),
                "name": u.get("name"),
                "tier": tier_val,
                "created_at": u.get("created_at"),
                "stripe_customer_id": u.get("stripe_customer_id"),
                "disabled": is_disabled,
                "api_key_count": key_count,
            }
        )

    return {
        "users": users_list,
        "stats": {
            "total_users": len(users_list),
            "tier_distribution": tier_dist,
            "total_api_keys": total_keys,
            "disabled_users": disabled_count,
        },
    }


@router.post("/admin/users/tier", tags=["admin"])
async def admin_set_user_tier(
    request: Request,
    auth: AuthManager = Depends(get_auth),
):
    """Set a user's tier (admin only)."""
    _require_admin(request)
    body = await request.json()
    user_id = body.get("user_id", "")
    tier_str = body.get("tier", "")

    if not user_id or user_id not in auth._users:
        raise HTTPException(status_code=404, detail="User not found.")
    try:
        new_tier = Tier(tier_str)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid tier: {tier_str}")

    auth.set_user_tier(user_id, new_tier)
    return {"user_id": user_id, "tier": new_tier.value}


@router.post("/admin/users/{user_id}/disable", tags=["admin"])
async def admin_disable_user(
    user_id: str,
    request: Request,
    auth: AuthManager = Depends(get_auth),
):
    """Disable a user account (admin only)."""
    _require_admin(request)
    if user_id not in auth._users:
        raise HTTPException(status_code=404, detail="User not found.")
    auth._users[user_id]["disabled"] = True
    auth._save_users()
    return {"user_id": user_id, "disabled": True}


@router.post("/admin/users/{user_id}/enable", tags=["admin"])
async def admin_enable_user(
    user_id: str,
    request: Request,
    auth: AuthManager = Depends(get_auth),
):
    """Enable a user account (admin only)."""
    _require_admin(request)
    if user_id not in auth._users:
        raise HTTPException(status_code=404, detail="User not found.")
    auth._users[user_id]["disabled"] = False
    auth._save_users()
    return {"user_id": user_id, "disabled": False}


# ---------------------------------------------------------------------------
# Passkey MFA (FIDO2/WebAuthn)
# ---------------------------------------------------------------------------


def _comply_passkey_user_id(authorization: str | None) -> tuple[str, str | None]:
    """Return (passkey_user_id, tenant_id) from a Clerk bearer token."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authorization header"
        )
    auth = get_auth()
    claims = auth.verify_clerk_token(authorization[7:])
    if not claims:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Clerk token")
    sub = claims.get("sub", "")
    tenant_id = (
        str(claims.get("org_id") or "").strip()
        or str(claims.get("organization_id") or "").strip()
        or (
            str((claims.get("o") or {}).get("id") or "").strip()
            if isinstance(claims.get("o"), dict)
            else ""
        )
    )
    return f"clerk:{sub}", tenant_id or None


@passkey_router.post("/passkeys/register-options")
async def comply_passkey_register_options(
    request: Request,
    authorization: str = Header(...),
):
    """Generate WebAuthn registration options for the current Clerk user."""
    user_id, tenant_id = _comply_passkey_user_id(authorization)
    manager = get_passkey_manager_for_request(request)
    if manager is None:
        raise HTTPException(status_code=503, detail="Passkey MFA not available")
    body = await request.json() if await request.body() else {}
    email = body.get("email", user_id)
    return await manager.registration_options(
        user_id=user_id,
        user_name=email,
        user_display_name=body.get("display_name") or email,
        tenant_id=tenant_id,
    )


@passkey_router.post("/passkeys/register")
async def comply_passkey_register(
    request: Request,
    authorization: str = Header(...),
):
    """Verify and persist a newly created passkey credential."""
    user_id, tenant_id = _comply_passkey_user_id(authorization)
    manager = get_passkey_manager_for_request(request)
    if manager is None:
        raise HTTPException(status_code=503, detail="Passkey MFA not available")
    body = await request.json()
    credential = body.get("credential")
    if not credential:
        raise HTTPException(status_code=400, detail="Missing credential")
    try:
        result = await manager.verify_registration(
            user_id=user_id,
            credential_dict=credential,
            tenant_id=tenant_id,
            device_name=body.get("device_name", "Primary device"),
            context=get_auth_context(request),
        )
        return result
    except Exception as exc:
        logger.exception("[passkey] registration verification failed for user=%s: %s", user_id, exc)
        raise HTTPException(
            status_code=400,
            detail=f"Passkey registration verification failed: {exc}",
        ) from exc


@passkey_router.post("/passkeys/auth-options")
async def comply_passkey_auth_options(
    request: Request,
    authorization: str = Header(...),
):
    """Generate WebAuthn authentication options for the current Clerk user."""
    user_id, _tenant_id = _comply_passkey_user_id(authorization)
    manager = get_passkey_manager_for_request(request)
    if manager is None:
        raise HTTPException(status_code=503, detail="Passkey MFA not available")
    return await manager.authentication_options(user_id=user_id)


PASSKEY_MFA_COOKIE_NAME = "crp_passkey_mfa_token"


def _passkey_cookie_settings() -> dict[str, Any]:
    """Return conservative cookie settings for the passkey MFA token."""
    secure = os.environ.get("CRP_COMPLY_COOKIE_SECURE", "false").lower() in {"1", "true", "yes"}
    return {
        "key": PASSKEY_MFA_COOKIE_NAME,
        "httponly": True,
        "secure": secure,
        "samesite": "strict",
        "path": "/",
    }


@passkey_router.post("/passkeys/verify")
async def comply_passkey_verify(
    request: Request,
    response: Response,
    authorization: str = Header(...),
):
    """Verify a passkey assertion and issue an MFA session token.

    The token is returned in the JSON body for SDK/external callers and is
    also set as an HttpOnly cookie for the web frontend so browser clients
    no longer need to read it from sessionStorage.
    """
    user_id, tenant_id = _comply_passkey_user_id(authorization)
    manager = get_passkey_manager_for_request(request)
    if manager is None:
        raise HTTPException(status_code=503, detail="Passkey MFA not available")
    body = await request.json()
    credential = body.get("credential")
    if not credential:
        raise HTTPException(status_code=400, detail="Missing credential")

    context = get_auth_context(request)
    try:
        auth_result = await manager.verify_authentication(
            credential_dict=credential,
            context=context,
            tenant_id=tenant_id,
        )
    except Exception as exc:
        logger.exception(
            "[passkey] authentication verification failed for user=%s: %s", user_id, exc
        )
        raise HTTPException(
            status_code=400,
            detail=f"Passkey authentication verification failed: {exc}",
        ) from exc

    if auth_result["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Credential does not belong to user")

    if auth_result["decision"] == "block":
        raise HTTPException(
            status_code=403,
            detail="Login blocked by adaptive risk policy",
            headers={"X-Risk-Score": str(auth_result["risk_score"])},
        )

    mfa_token = await manager.create_mfa_session(
        user_id=user_id,
        credential_id=auth_result["credential_id"],
        context=context,
        risk_score=auth_result["risk_score"],
    )

    response.set_cookie(
        value=mfa_token,
        max_age=manager.session_ttl_seconds,
        **_passkey_cookie_settings(),
    )

    return {
        "mfa_token": mfa_token,
        "expires_in": manager.session_ttl_seconds,
        "risk_score": auth_result["risk_score"],
        "risk_factors": auth_result["risk_factors"],
    }


@passkey_router.get("/passkeys")
async def comply_passkey_list(
    authorization: str = Header(...),
):
    """List passkey credentials for the current Clerk user."""
    user_id, _tenant_id = _comply_passkey_user_id(authorization)
    manager = get_passkey_manager()
    if manager is None:
        raise HTTPException(status_code=503, detail="Passkey MFA not available")
    rows = await manager.list_credentials(user_id)
    return {
        "credentials": [
            {
                "credential_id": row["credential_id"],
                "device_name": row["device_name"],
                "transports": row["transports"],
                "created_at": row["created_at"],
                "last_used_at": row["last_used_at"],
            }
            for row in rows
        ]
    }


@passkey_router.delete("/passkeys/{credential_id}")
async def comply_passkey_delete(
    credential_id: str,
    authorization: str = Header(...),
):
    """Revoke a passkey credential."""
    user_id, _tenant_id = _comply_passkey_user_id(authorization)
    manager = get_passkey_manager()
    if manager is None:
        raise HTTPException(status_code=503, detail="Passkey MFA not available")
    ok = await manager.delete_credential(user_id, credential_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Credential not found")
    return {"status": "revoked", "credential_id": credential_id}


@passkey_router.get("/passkeys/status")
async def comply_passkey_status(
    authorization: str = Header(...),
):
    """Check whether the current Clerk user has registered passkeys."""
    user_id, _tenant_id = _comply_passkey_user_id(authorization)
    manager = get_passkey_manager()
    if manager is None:
        raise HTTPException(status_code=503, detail="Passkey MFA not available")
    has = await manager.has_credentials(user_id)
    return {"has_passkeys": has, "mandatory": True}
