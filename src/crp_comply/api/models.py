# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Pydantic models for API request/response schemas."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ── Enums ──────────────────────────────────────────────────────
class Tier(str, Enum):
    FREE = "free"
    STARTER = "starter"
    PRO = "pro"
    SCALE = "scale"
    ENTERPRISE = "enterprise"
    CLOUD = "cloud"


class RiskLevel(str, Enum):
    MINIMAL = "MINIMAL"
    LIMITED = "LIMITED"
    HIGH = "HIGH"
    UNACCEPTABLE = "UNACCEPTABLE"


# ── Auth Models ────────────────────────────────────────────────
class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserInfo(BaseModel):
    id: str
    email: str
    name: str
    provider: str  # "github" | "google" | "clerk" | ...
    tier: Tier = Tier.FREE
    created_at: datetime
    #: Tenant / workspace handle. For Clerk orgs this is the ``org_id``
    #: claim; otherwise it defaults to the user's own id so solo-tenant
    #: deployments work unchanged. Every data-returning endpoint MUST
    #: filter by ``tenant_id`` to prevent cross-account reads.
    tenant_id: str = ""
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None
    subscription_status: str | None = None
    cancel_at_period_end: bool = False
    current_period_end: str | None = None


class APIKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class APIKeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    # On the multi-tenant SaaS this field is **ignored** — every key
    # inherits the owning user's account tier. It is retained as
    # ``Optional`` purely for the self-hosted admin path (anonymous
    # caller bootstrap) which uses it to set the admin user's tier on
    # first key creation. Previously the SaaS UI offered a tier dropdown
    # whose value was silently dropped, producing free-tier keys
    # regardless of selection.
    tier: Tier | None = None
    expires_in_days: int | None = Field(
        default=None,
        ge=1,
        le=3650,
        description="Optional key lifetime in days. Defaults to API_KEY_DEFAULT_EXPIRY_DAYS env var (365).",
    )


class APIKeyResponse(BaseModel):
    id: str
    name: str
    key_prefix: str  # first 8 chars for identification
    created_at: datetime
    tier: Tier
    expires_at: datetime | None = None
    revoked: bool = False


class APIKeyCreated(APIKeyResponse):
    key: str  # full key, shown only once


# ── Risk Assessment ────────────────────────────────────────────
class RiskAssessRequest(BaseModel):
    system_name: str = Field(..., min_length=1, max_length=200)
    category: str = Field(
        default="GENERAL_PURPOSE",
        description="AI system category per EU AI Act Art. 6",
    )
    description: str = Field(default="", max_length=5000)
    has_biometric: bool = False
    has_critical_infrastructure: bool = False
    has_law_enforcement: bool = False
    affects_fundamental_rights: bool = False


class RiskAssessResponse(BaseModel):
    system_name: str
    risk_level: RiskLevel
    category: str
    obligations: list[str]
    prohibitions: list[str]
    assessment_date: str
    crp_version: str


# ── Compliance Report ──────────────────────────────────────────
class ComplianceReportRequest(BaseModel):
    system_name: str = Field(..., min_length=1, max_length=200)
    category: str = Field(default="GENERAL_PURPOSE")
    include_iso42001: bool = True


class ComplianceControl(BaseModel):
    control_id: str
    title: str
    status: str
    framework: str
    evidence: str


class ComplianceReportResponse(BaseModel):
    system_name: str
    overall_status: str
    risk_level: str
    controls: list[ComplianceControl]
    score: float
    generated_at: str
    crp_version: str


# ── DPIA ───────────────────────────────────────────────────────
class DPIARequest(BaseModel):
    system_name: str = Field(..., min_length=1, max_length=200)
    data_subjects: str = Field(
        default="end users",
        description="Description of data subjects affected",
    )
    processing_purpose: str = Field(
        default="AI-assisted context management",
        description="Purpose of data processing",
    )
    processes_personal_data: bool = Field(
        default=True,
        description="Whether the system processes personal data",
    )
    makes_automated_decisions: bool = Field(
        default=False,
        description="Whether the system makes automated decisions affecting individuals",
    )
    safety_critical: bool = Field(
        default=False,
        description="Whether the system is used in safety-critical contexts",
    )
    profiles_individuals: bool = Field(
        default=False,
        description="Whether the system profiles individuals",
    )
    affects_fundamental_rights: bool = Field(
        default=False,
        description="Whether processing affects fundamental rights",
    )


class DPIAResponse(BaseModel):
    system_name: str
    dpia_required: bool
    risk_categories: dict[str, Any]
    mitigations: list[str]
    residual_risk: str
    recommendation: str
    generated_at: str


# ── Transparency ───────────────────────────────────────────────
class TransparencyRequest(BaseModel):
    system_name: str = Field(..., min_length=1, max_length=200)
    provider_name: str = Field(default="")
    deployer_name: str = Field(default="")


class TransparencyResponse(BaseModel):
    system_name: str
    declaration: dict[str, Any]
    generated_at: str


# ── Technical Documentation ────────────────────────────────────
class TechnicalDocsRequest(BaseModel):
    system_name: str = Field(..., min_length=1, max_length=200)
    category: str = Field(default="GENERAL_PURPOSE")


class TechnicalDocsResponse(BaseModel):
    system_name: str
    documentation: dict[str, Any]
    generated_at: str


# ── Session Audit ──────────────────────────────────────────────
class SessionAuditRequest(BaseModel):
    session_file: str = Field(..., description="Path to persisted CRP session JSON file")


class AuditFinding(BaseModel):
    severity: str
    category: str
    detail: str


class SessionAuditResponse(BaseModel):
    session_id: str
    compliance_score: float
    findings: list[AuditFinding]
    audit_trail_verified: bool
    events_analysed: int
    generated_at: str


# ── Evidence Pack ──────────────────────────────────────────────
class EvidencePackRequest(BaseModel):
    system_name: str = Field(..., min_length=1, max_length=200)
    category: str = Field(default="GENERAL_PURPOSE")
    session_file: str | None = Field(
        default=None, description="Optional path to session file for audit"
    )


class EvidencePackResponse(BaseModel):
    system_name: str
    pack_id: str
    artifacts: list[str]
    generated_at: str
    download_url: str | None = None


# ── License ────────────────────────────────────────────────────
class LicenseInfo(BaseModel):
    tier: Tier
    valid: bool
    expires_at: datetime | None
    features: list[str]


# ── Signed Certificate (CLOUD tier) ───────────────────────────
class CertificateRequest(BaseModel):
    system_name: str = Field(..., min_length=1, max_length=200)
    category: str = Field(default="GENERAL_PURPOSE")
    organisation: str = Field(default="", max_length=200)


class SignedCertificate(BaseModel):
    certificate_id: str
    system_name: str
    organisation: str
    risk_level: str
    compliance_score: float
    frameworks: list[str]
    issued_at: str
    expires_at: str
    issuer: str = "AutoCyber AI Pty Ltd — CRP Comply Cloud"
    signature: str
    verification_url: str


# ── Generic ────────────────────────────────────────────────────
class HealthResponse(BaseModel):
    status: str = "healthy"
    version: str
    tier: str
    crp_version: str = ""
    comply_version: str = ""


class ErrorResponse(BaseModel):
    detail: str
    error_code: str | None = None


# ── Compliance Agent (Phase 4.6) ───────────────────────────────
class AgentStartRequest(BaseModel):
    """Start a new agent session with a natural-language compliance task."""

    task: str = Field(
        ...,
        min_length=4,
        max_length=4000,
        description=(
            "Plain-English compliance task. Example: 'Assess whether our "
            "resume-ranking system is high-risk under the EU AI Act and "
            "produce a DPIA-style summary.'"
        ),
    )
    system_id: str = Field(
        default="",
        max_length=200,
        description="Customer-scoped identifier for the AI system being assessed.",
    )
    customer_id: str = Field(
        default="",
        max_length=200,
        description="Optional customer/org id for multi-tenant scoping inside the CKF.",
    )
    extra_context: str = Field(
        default="",
        max_length=8000,
        description=(
            "Free-form context to prepend as a system note — e.g. product "
            "description, deployment region, data sources."
        ),
    )
    max_iters: int = Field(
        default=8,
        ge=1,
        le=20,
        description="Hard cap on LLM↔tool round-trips for this run.",
    )
    depth: str = Field(
        default="",
        max_length=20,
        description="Web-research depth: brief | standard | thorough. Defaults to user preference.",
    )
    autonomy: str = Field(
        default="",
        max_length=40,
        description=(
            "User-selected autonomy level: suggest | draft | "
            "autonomous_with_checkpoints | full. Maps to the agent's "
            "Policy Enforcement Point mode."
        ),
    )


class AgentToolCallSummary(BaseModel):
    tool: str
    ok: bool
    error: str = ""


class AgentSessionState(BaseModel):
    """Public projection of an agent session's current state."""

    session_id: str
    user_id: str
    state: str = Field(
        ...,
        description="One of: done | awaiting_clarification | max_iters | error | running",
    )
    task: str
    system_id: str = ""
    customer_id: str = ""
    iterations: int = 0
    tool_calls: int = 0
    facts_stored: int = 0
    pending_question: str = ""
    pending_context: str = ""
    pending_priority: str = Field(
        default="",
        description="Priority of pending clarification — high | medium | low.",
    )
    pending_skippable: bool = Field(
        default=False,
        description="Whether the UI may let the user skip this clarification.",
    )
    pending_fact_key: str = Field(
        default="",
        description="Machine-readable fact key for the missing datum (if supplied by LLM).",
    )
    pending_options: list[str] = Field(
        default_factory=list,
        description="Optional button labels for confirm/repair actions.",
    )
    resume_token: str = Field(
        default="",
        description="ClarifierStore resume token when the session is awaiting input.",
    )
    pending_action: str = Field(
        default="probe",
        description="Kind of clarification interaction: probe | confirm | repair.",
    )
    final_text: str = ""
    error: str = ""
    clarifications: list[dict[str, str]] = Field(
        default_factory=list,
        description="History of [{question, answer}] pairs from prior clarify() calls.",
    )
    created_at: str
    updated_at: str
    trace_path: str = ""
    messages: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Full message history for loop-mode sessions.",
    )
    reasoning_tape: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Lightweight trace of tool calls and phase events for this session.",
    )
    experts_invoked: list[str] = Field(
        default_factory=list,
        description="Regulation-specific experts consulted during the run.",
    )


class AgentClarifyRequest(BaseModel):
    """Answer the agent's pending clarification question and resume.

    Set ``skip=True`` to record the fact as 'unknown' and proceed without
    further LLM back-and-forth; the orchestrator will still enforce the
    clarification budget and mark the assumption explicitly in the
    evidence pack.
    """

    answer: str = Field(default="", max_length=4000)
    skip: bool = Field(
        default=False,
        description="If True, record the missing fact as 'unknown' and resume.",
    )


class AgentFinalizeRequest(BaseModel):
    """Persist the session's final_text as a retrievable ComplianceReport."""

    system_name: str = Field(
        default="",
        max_length=200,
        description=(
            "Optional override for the persisted report's system_name; "
            "defaults to session.system_id."
        ),
    )
    include_trace: bool = Field(
        default=True,
        description="Whether to include the JSONL trace path in the stored report.",
    )


class AgentFinalizeResponse(BaseModel):
    session_id: str
    report_id: str | None
    markdown: str
    system_name: str
    generated_at: str


class AgentSessionList(BaseModel):
    sessions: list[AgentSessionState]


class AgentContinueRequest(BaseModel):
    """Send a follow-up turn into a closed (``done`` / ``max_iters`` /
    ``error``) agent session — keeps the same ``session_id`` so the
    UI thread stays continuous, but re-runs the agent loop with the
    prior task + final answer + clarifications replayed as
    ``extra_context`` and the new message as the active task.
    """

    message: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="The follow-up question or instruction.",
    )
    depth: str = Field(
        default="",
        max_length=20,
        description="Override web-research depth for this turn: brief | standard | thorough.",
    )


class AgentFeedbackRequest(BaseModel):
    """Per-answer / per-fact feedback signal (Phase 5). Routes to the
    per-tenant CKF, the per-user preference learner, and the JSONL
    feedback ledger.
    """

    fact_id: str = Field(
        "", max_length=200, description="Optional CRP fact identifier for per-fact RLHF."
    )
    signal: str = Field("boost", pattern="^(boost|penalize|reject|edit)$")
    original_text: str = Field(
        "", max_length=50_000, description="Original AI output when signal is 'edit'."
    )
    edited_text: str = Field(
        "", max_length=50_000, description="User-edited version of the AI output."
    )
    section_id: str = Field(
        "", max_length=200, description="Section or message identifier being edited."
    )
    reason: str = Field("", max_length=500)
    message_id: str = Field("", max_length=200, description="Assistant message being rated.")
    rating: int | None = Field(default=None, ge=1, le=5)
    helpful: bool | None = Field(default=None)
    comment: str = Field("", max_length=1000)
    regulation: str = Field("", max_length=100)
    depth: str = Field("", max_length=20)
    format: str = Field("", max_length=20)
    audience: str = Field("", max_length=20)
    sources: list[str] = Field(default_factory=list)


class UserPreferenceProfileResponse(BaseModel):
    """Public projection of a user's learned preference profile."""

    tenant_id: str
    user_id: str
    preferred_depth: str = "standard"
    preferred_format: str = "prose"
    preferred_audience: str = "unknown"
    preferred_regulations: list[str] = Field(default_factory=list)
    trusted_source_domains: list[str] = Field(default_factory=list)
    satisfaction_criteria: list[str] = Field(default_factory=list)
    preferred_autonomy: str = Field(
        default="autonomous_with_checkpoints",
        pattern="^(suggest|draft|autonomous_with_checkpoints|full)$",
    )
    feedback_summary: dict[str, Any] = Field(default_factory=dict)
    explicit_feedback_count: int = 0
    implicit_signal_count: int = 0
    updated_at: str = ""


class UserPreferenceProfileUpdate(BaseModel):
    """Allow the user to override learned preferences or reset them."""

    preferred_depth: str | None = Field(default=None, pattern="^(brief|standard|thorough)$")
    preferred_format: str | None = Field(
        default=None, pattern="^(summary|checklist|report|citation_list|decision_tree|prose)$"
    )
    preferred_audience: str | None = Field(
        default=None, pattern="^(executive|legal|engineer|auditor|unknown)$"
    )
    preferred_regulations: list[str] | None = None
    trusted_source_domains: list[str] | None = None
    satisfaction_criteria: list[str] | None = None
    preferred_autonomy: str | None = Field(
        default=None, pattern="^(suggest|draft|autonomous_with_checkpoints|full)$"
    )
    reset: bool = Field(
        default=False, description="If True, clear learned scores and return defaults."
    )


class AgentPreviewRequest(BaseModel):
    """Pre-flight envelope preview — surfaces what CRP would pack for
    a given task without actually dispatching. Used by the UI's
    "explain this answer" expander (Phase 5)."""

    task: str = Field(..., min_length=1, max_length=4000)
    extra_context: str = Field("", max_length=20_000)


class AgentEstimateRequest(BaseModel):
    """Pre-flight cost estimate. Calls
    :meth:`crp.Client.estimate_session` to project token / dollar cost
    before the user commits."""

    task: str = Field(..., min_length=1, max_length=4000)
    extra_context: str = Field("", max_length=20_000)
    planned_dispatches: int = Field(1, ge=1, le=20)
    avg_output_tokens: int | None = Field(None, ge=1, le=32_768)
