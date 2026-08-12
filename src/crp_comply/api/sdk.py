# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Python SDK gateway — the endpoint family used by ``crp-comply-sdk``.

The SDK is a thin HTTP wrapper distributed on PyPI. Its value is that every
call to a user's local or remote LLM (LM Studio, Ollama, OpenAI, Anthropic…)
is sent through these endpoints so CRP Comply can:

* run the audit engine (HMAC chain, PII scan, risk classifier, injection checks)
* persist the audit record for later retrieval
* count the call against the user's monthly quota
* gate premium features server-side (tier matrix in :data:`SDK_FEATURE_MATRIX`)

Every SDK feature lives here so the gating logic is one place.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from .auth import Tier
from .deps import (
    _extract_credentials,
    get_current_tier,
    get_current_user,
    meter_call,
)

logger = logging.getLogger("crp_comply.api.sdk")

router = APIRouter(prefix="/sdk", tags=["sdk"])


# ── Tier → SDK Feature Matrix ──────────────────────────────────
# The SDK surfaces methods for every feature below; the backend decides
# whether a call is allowed based on the caller's tier.

SDK_FEATURE_MATRIX: dict[str, dict[str, bool]] = {
    # Free tier — basic audit only, 100 calls/mo hard cap (enforced by meter_call)
    Tier.FREE.value: {
        "chat": True,
        "audit": True,
        "classify_risk": True,
        "scan_pii": True,
        "export_markdown": False,
        "dpia": False,
        "evidence_pack": False,
        "export_audit_chain": False,
        "session_replay": False,
        "worker": False,
    },
    # Pro / Scale — full auditing + reporting, markdown export
    Tier.PRO.value: {
        "chat": True,
        "audit": True,
        "classify_risk": True,
        "scan_pii": True,
        "export_markdown": True,
        "dpia": True,
        "evidence_pack": True,
        "export_audit_chain": False,
        "session_replay": True,
        "worker": True,
    },
    Tier.SCALE.value: {
        "chat": True,
        "audit": True,
        "classify_risk": True,
        "scan_pii": True,
        "export_markdown": True,
        "dpia": True,
        "evidence_pack": True,
        "export_audit_chain": False,
        "session_replay": True,
        "worker": True,
    },
    # Enterprise — everything
    Tier.ENTERPRISE.value: {
        "chat": True,
        "audit": True,
        "classify_risk": True,
        "scan_pii": True,
        "export_markdown": True,
        "dpia": True,
        "evidence_pack": True,
        "export_audit_chain": True,
        "session_replay": True,
        "worker": True,
    },
    Tier.CLOUD.value: {
        "chat": True,
        "audit": True,
        "classify_risk": True,
        "scan_pii": True,
        "export_markdown": True,
        "dpia": True,
        "evidence_pack": True,
        "export_audit_chain": True,
        "session_replay": True,
        "worker": True,
    },
}

# Minimum tier required for a feature, for error messages
FEATURE_MIN_TIER: dict[str, str] = {
    "chat": Tier.FREE.value,
    "audit": Tier.FREE.value,
    "classify_risk": Tier.FREE.value,
    "scan_pii": Tier.FREE.value,
    "export_markdown": Tier.PRO.value,
    "dpia": Tier.PRO.value,
    "evidence_pack": Tier.PRO.value,
    "session_replay": Tier.PRO.value,
    "export_audit_chain": Tier.ENTERPRISE.value,
    "worker": Tier.PRO.value,
}


def check_sdk_feature(tier: Tier, feature: str) -> None:
    """Raise HTTP 402 feature_not_in_tier if tier can't use feature."""
    matrix = SDK_FEATURE_MATRIX.get(tier.value, {})
    if not matrix.get(feature, False):
        required = FEATURE_MIN_TIER.get(feature, Tier.PRO.value)
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "feature_not_in_tier",
                "feature": feature,
                "your_tier": tier.value,
                "required_tier": required,
                "upgrade_url": "/pricing",
                "message": (
                    f"The SDK feature '{feature}' requires the {required} "
                    f"tier or higher. You are on the {tier.value} tier. "
                    f"Upgrade at /pricing."
                ),
            },
        )


# ── Request / response models ──────────────────────────────────


class SDKMessage(BaseModel):
    role: str = Field(..., pattern=r"^(system|user|assistant|tool|developer)$")
    content: str = Field(..., max_length=200_000)


class SDKAuditRequest(BaseModel):
    """A request/response pair to audit — the core SDK call.

    ``messages`` is the request payload (OpenAI-style). ``response`` is the
    completion text returned by the upstream LLM (LM Studio, Ollama,
    OpenAI, Anthropic…). ``backend`` identifies which local/remote LLM was
    used for traceability in the audit chain.
    """

    messages: list[SDKMessage] = Field(..., min_length=1, max_length=200)
    response: str = Field(..., max_length=500_000)
    backend: str = Field(
        default="unknown",
        pattern=r"^(lmstudio|ollama|openai|anthropic|azure|vertex|unknown|custom)$",
    )
    model: str = Field(default="unknown", max_length=128)
    system_name: str = Field(default="unspecified", max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)
    latency_ms: int | None = None
    tokens_prompt: int | None = None
    tokens_completion: int | None = None


class SDKAuditResponse(BaseModel):
    audit_id: str
    risk_level: str
    compliance_status: str
    pii_detected: bool
    pii_types: list[str]
    injection_detected: bool
    injection_score: float
    warnings: list[str]
    hmac_chain_prev: str | None
    persisted: bool
    tier: str
    quota_used: int
    quota_remaining: int
    timestamp: str


class SDKClassifyRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=200_000)
    category: str = Field(default="GENERAL_PURPOSE", max_length=64)


class SDKClassifyResponse(BaseModel):
    risk_level: str
    pii_detected: bool
    pii_types: list[str]
    injection_detected: bool
    injection_score: float
    warnings: list[str]


class SDKFeatureInfo(BaseModel):
    feature: str
    allowed: bool
    required_tier: str
    your_tier: str


class SDKFeaturesResponse(BaseModel):
    tier: str
    features: list[SDKFeatureInfo]
    quota: dict[str, Any]
    version: str


# ── Audit core helper ──────────────────────────────────────────


def _audit_pair(
    *,
    user_id: str,
    tier: Tier,
    req: SDKAuditRequest,
) -> dict[str, Any]:
    """Run the CRP audit engine against a request/response pair."""
    # Compose joined text for the PII / injection scanners
    joined = " ".join(m.content for m in req.messages) + "\n" + req.response

    pii_types: list[str] = []
    injection_score = 0.0
    warnings: list[str] = []

    # PII scan
    try:
        from crp.security.pii_scanner import PIIScanner

        scanner = PIIScanner()
        # Some implementations expose .scan(); some .detect(). Use getattr.
        fn = getattr(scanner, "scan", None) or getattr(scanner, "detect", None)
        if fn:
            result = fn(joined)
            if hasattr(result, "detections"):
                pii_types = sorted({d.type for d in result.detections})
            elif isinstance(result, list):
                pii_types = sorted({getattr(d, "type", str(d)) for d in result})
    except Exception as exc:
        logger.debug("pii_scanner unavailable: %s", exc)

    # Injection detection
    try:
        from crp.security.injection_detector import InjectionDetector

        detector = InjectionDetector()
        fn = getattr(detector, "detect", None) or getattr(detector, "scan", None)
        if fn:
            result = fn(joined)
            injection_score = float(getattr(result, "score", 0.0))
            if getattr(result, "detected", False):
                warnings.append(f"Prompt injection suspected (score={injection_score:.2f})")
    except Exception as exc:
        logger.debug("injection_detector unavailable: %s", exc)

    # Risk classification
    risk_level = "MINIMAL"
    try:
        from crp.security.risk_classifier import RiskClassifier

        rc = RiskClassifier()
        fn = getattr(rc, "classify", None)
        if fn:
            result = fn(text=joined)
            risk_level = str(getattr(result, "risk_level", "MINIMAL")).upper()
    except Exception as exc:
        logger.debug("risk_classifier unavailable: %s", exc)

    compliance_status = "compliant"
    if risk_level in ("HIGH", "UNACCEPTABLE"):
        compliance_status = "requires_review"
    if injection_score > 0.7:
        compliance_status = "blocked"
        warnings.append("High injection score — response flagged for review")
    if pii_types and tier == Tier.FREE:
        warnings.append("PII detected. Configure redaction in /app/settings for automatic masking.")

    return {
        "risk_level": risk_level,
        "compliance_status": compliance_status,
        "pii_detected": bool(pii_types),
        "pii_types": pii_types,
        "injection_detected": injection_score > 0.5,
        "injection_score": round(injection_score, 3),
        "warnings": warnings,
    }


# ── Endpoints ──────────────────────────────────────────────────


@router.get("/features", response_model=SDKFeaturesResponse)
async def sdk_features(
    creds: Annotated[tuple[str, Tier], Depends(_extract_credentials)],
):
    """Return which SDK features the caller's tier can use.

    The SDK calls this once at startup to surface typed errors for locked
    features instead of round-tripping every call.
    """
    from crp_comply import __version__ as version
    from .usage import get_usage_tracker

    user_id, tier = creds
    matrix = SDK_FEATURE_MATRIX.get(tier.value, {})
    features = [
        SDKFeatureInfo(
            feature=f,
            allowed=matrix.get(f, False),
            required_tier=FEATURE_MIN_TIER.get(f, Tier.PRO.value),
            your_tier=tier.value,
        )
        for f in FEATURE_MIN_TIER.keys()
    ]

    quota = {
        "tier": tier.value,
        "used": 0,
        "quota": 0,
        "remaining": 0,
        "resets_at": None,
    }
    if user_id != "anonymous":
        try:
            q = get_usage_tracker().check_quota(user_id, tier)
            quota = {
                "tier": tier.value,
                "used": q["used"],
                "quota": q["quota"],
                "remaining": q["remaining"],
                "resets_at": q["resets_at"],
            }
        except Exception as _bandit_exc:
            logger.debug("swallowed in sdk.features (quota best-effort): %s", _bandit_exc)
            pass

    return SDKFeaturesResponse(
        tier=tier.value,
        features=features,
        quota=quota,
        version=version,
    )


@router.post(
    "/audit",
    response_model=SDKAuditResponse,
    dependencies=[Depends(meter_call("sdk-audit"))],
)
async def sdk_audit(
    req: SDKAuditRequest,
    user_id: str = Depends(get_current_user),
    tier: Tier = Depends(get_current_tier),
):
    """Audit a request/response pair from the SDK.

    This is the main SDK endpoint. Every call:

    * runs the CRP audit engine (PII, injection, risk classification)
    * persists an audit record to ``/app/data/proxy_audit/{id}.json``
    * counts against the monthly quota
    * returns a structured result the SDK can surface to the caller
    """
    if user_id == "anonymous":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="SDK requires an API key. Create one in /app/settings.",
        )

    check_sdk_feature(tier, "audit")

    audit_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # Run audit
    audit_result = _audit_pair(user_id=user_id, tier=tier, req=req)

    # Persist via the proxy interceptor if available (HMAC chained record)
    hmac_prev: str | None = None
    persisted = False
    try:
        from ..proxy.routes import _get_interceptor

        interceptor = _get_interceptor()

        request_payload = {
            "messages": [m.model_dump() for m in req.messages],
            "model": req.model,
            "backend": req.backend,
            "system_name": req.system_name,
            "metadata": req.metadata,
            "latency_ms": req.latency_ms,
            "tokens_prompt": req.tokens_prompt,
            "tokens_completion": req.tokens_completion,
        }
        response_payload = {
            "id": audit_id,
            "choices": [
                {
                    "message": {"role": "assistant", "content": req.response},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": req.tokens_prompt or 0,
                "completion_tokens": req.tokens_completion or 0,
            },
        }

        create_fn = getattr(interceptor, "create_audit_record", None)
        if create_fn:
            record = create_fn(
                user_id=user_id,
                request=request_payload,
                response=response_payload,
                model=req.model,
            )
            persisted = True
            if record:
                hmac_prev = getattr(record, "hmac_prev", None) or getattr(
                    record, "previous_hmac", None
                )
    except Exception as exc:
        logger.warning("sdk_audit: interceptor persist failed: %s", exc)

    # Fallback persistence: write a lean JSON record
    if not persisted:
        try:
            from pathlib import Path
            import json
            import os

            data_dir = Path(os.environ.get("CRP_COMPLY_DATA_DIR", "data"))
            out_dir = data_dir / "proxy_audit"
            out_dir.mkdir(parents=True, exist_ok=True)
            record = {
                "id": audit_id,
                "user_id": user_id,
                "timestamp": now,
                "backend": req.backend,
                "model": req.model,
                "system_name": req.system_name,
                "request_hash": hashlib.sha256(
                    (" ".join(m.content for m in req.messages)).encode()
                ).hexdigest(),
                "response_hash": hashlib.sha256(req.response.encode()).hexdigest(),
                "risk_level": audit_result["risk_level"],
                "pii_types": audit_result["pii_types"],
                "injection_score": audit_result["injection_score"],
                "source": "sdk",
            }
            (out_dir / f"{audit_id}.json").write_text(
                json.dumps(record, indent=2, default=str), encoding="utf-8"
            )
            persisted = True
        except Exception as exc:
            logger.warning("sdk_audit: fallback persist failed: %s", exc)

    # Quota snapshot
    quota_used = 0
    quota_remaining = 0
    try:
        from .usage import get_usage_tracker

        q = get_usage_tracker().check_quota(user_id, tier)
        quota_used = q["used"]
        quota_remaining = q["remaining"]
    except Exception as _bandit_exc:
        logger.debug("swallowed in sdk.audit (quota best-effort): %s", _bandit_exc)
        pass

    return SDKAuditResponse(
        audit_id=audit_id,
        risk_level=audit_result["risk_level"],
        compliance_status=audit_result["compliance_status"],
        pii_detected=audit_result["pii_detected"],
        pii_types=audit_result["pii_types"],
        injection_detected=audit_result["injection_detected"],
        injection_score=audit_result["injection_score"],
        warnings=audit_result["warnings"],
        hmac_chain_prev=hmac_prev,
        persisted=persisted,
        tier=tier.value,
        quota_used=quota_used,
        quota_remaining=quota_remaining,
        timestamp=now,
    )


@router.post(
    "/classify",
    response_model=SDKClassifyResponse,
    dependencies=[Depends(meter_call("sdk-classify"))],
)
async def sdk_classify(
    req: SDKClassifyRequest,
    user_id: str = Depends(get_current_user),
    tier: Tier = Depends(get_current_tier),
):
    """Classify a text snippet without persisting an audit record.

    Cheaper than ``/audit`` and allowed on free tier; useful for
    "is this prompt going to be risky before I send it" checks.
    """
    check_sdk_feature(tier, "classify_risk")
    result = _audit_pair(
        user_id=user_id,
        tier=tier,
        req=SDKAuditRequest(
            messages=[SDKMessage(role="user", content=req.text)],
            response="",
            backend="unknown",
            model="n/a",
        ),
    )
    return SDKClassifyResponse(**{k: v for k, v in result.items() if k != "compliance_status"})


# ── Mode C: SDK worker (long-running compliance task) ──────────


class SDKWorkerRequest(BaseModel):
    """Request a background compliance task be run by the agent.

    Mode C (design §5) is the headless, long-running variant of the
    interactive compliance agent. The caller submits a task ("produce a
    DPIA for system X", "assess AI Act risk for use-case Y"), the agent
    runs the tool-using loop on the server, and the result — including
    citations, envelope, and any clarifications — is returned in one
    structured payload. The caller does not need a UI session; the
    answer is either complete or flagged as needing clarification.
    """

    task: str = Field(..., min_length=4, max_length=8_000)
    system_id: str = Field(default="", max_length=200)
    customer_id: str = Field(default="", max_length=200)
    extra_context: str = Field(default="", max_length=32_000)
    max_iters: int = Field(default=8, ge=1, le=24)
    clarification_budget: int = Field(default=6, ge=0, le=12)
    max_continuation_windows: int = Field(default=4, ge=1, le=8)
    redact_pii_pre_llm: bool = Field(default=True)


class SDKWorkerResponse(BaseModel):
    worker_id: str
    state: str
    final_text: str = ""
    pending_question: str = ""
    pending_context: str = ""
    iterations: int = 0
    tool_calls: int = 0
    facts_stored: int = 0
    clarifications_used: int = 0
    clarification_budget: int = 0
    pii_redactions: int = 0
    continuation_windows: int = 1
    continuation_reason: str = ""
    tier: str
    quota_used: int = 0
    quota_remaining: int = 0
    elapsed_ms: int = 0
    timestamp: str


@router.post(
    "/worker",
    response_model=SDKWorkerResponse,
    dependencies=[Depends(meter_call("sdk-worker"))],
)
async def sdk_worker(
    req: SDKWorkerRequest,
    user_id: str = Depends(get_current_user),
    tier: Tier = Depends(get_current_tier),
):
    """Run a compliance agent task synchronously as a headless worker.

    Wraps :class:`crp_comply.agent.ComplianceAgent` with:

    * pre-LLM PII redaction (``crp.security.pii_scanner``)
    * clarification budget enforcement (design §4.1)
    * continuation wrap when the final answer gets truncated by the
      provider's output-token limit (``crp.continuation.stitch``)

    Intended for CI / batch callers (the ``comply worker`` CLI and any
    third-party scheduler) that don't need the interactive clarify loop.
    """
    import asyncio as _asyncio

    if user_id == "anonymous":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="SDK worker requires an API key. Create one in /app/settings.",
        )
    check_sdk_feature(tier, "worker")

    # Build a full agent lazily so this endpoint is cheap to import even
    # when the agent surface is broken.
    try:
        from ..agent import ComplianceAgent, ComplianceLLM, default_registry
        from ..agent.rag_service import RagService
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Agent subsystem unavailable: {exc}",
        ) from exc

    try:
        llm = ComplianceLLM.for_user(user_id)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"No LLM provider configured: {exc}. Set CRP_COMPLY_LLM_BASE_URL, "
                "OPENAI_API_KEY, or ANTHROPIC_API_KEY."
            ),
        ) from exc

    try:
        from .routes import _get_user_ckf  # type: ignore[attr-defined]

        fabric = _get_user_ckf(user_id)
    except Exception:
        fabric = None

    rag = None
    try:
        rag = RagService()
    except Exception:
        rag = None

    artefact_store = None
    proxy_metrics = None
    try:
        from .artefacts import get_artefact_store

        artefact_store = get_artefact_store()
    except Exception:
        artefact_store = None
    try:
        from ..proxy.routes import _interceptor as _proxy_singleton  # type: ignore

        proxy_metrics = _proxy_singleton
    except Exception:
        proxy_metrics = None

    registry = default_registry(
        rag=rag,
        fabric=fabric,
        artefact_store=artefact_store,
        proxy_metrics=proxy_metrics,
        user_id=user_id,
    )
    agent = ComplianceAgent(
        llm=llm,
        fabric=fabric,
        tools=registry,
        max_iters=int(req.max_iters),
        max_clarifications=int(req.clarification_budget),
        redact_pii_pre_llm=bool(req.redact_pii_pre_llm),
        continue_on_length=True,
        max_continuation_windows=int(req.max_continuation_windows),
        rag=rag,
    )

    worker_id = str(uuid.uuid4())
    started = time.monotonic()
    try:
        result = await _asyncio.to_thread(
            agent.run,
            req.task,
            system_id=req.system_id,
            customer_id=req.customer_id,
            session_id=worker_id,
            extra_context=req.extra_context,
        )
    except Exception as exc:
        logger.exception("sdk_worker failed worker=%s", worker_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Worker run failed: {exc}",
        ) from exc
    elapsed_ms = int((time.monotonic() - started) * 1000)

    # Quota snapshot
    quota_used = 0
    quota_remaining = 0
    try:
        from .usage import get_usage_tracker

        q = get_usage_tracker().check_quota(user_id, tier)
        quota_used = q["used"]
        quota_remaining = q["remaining"]
    except Exception as _bandit_exc:
        logger.debug("swallowed in sdk.worker (quota best-effort): %s", _bandit_exc)
        pass

    return SDKWorkerResponse(
        worker_id=worker_id,
        state=result.state,
        final_text=result.final_text,
        pending_question=result.pending_question,
        pending_context=result.pending_context,
        iterations=int(result.iterations),
        tool_calls=int(result.tool_calls),
        facts_stored=int(result.facts_stored),
        clarifications_used=int(getattr(result, "clarifications_used", 0)),
        clarification_budget=int(getattr(result, "clarification_budget", req.clarification_budget)),
        pii_redactions=int(getattr(result, "pii_redactions", 0)),
        continuation_windows=int(getattr(result, "continuation_windows", 1)),
        continuation_reason=str(getattr(result, "continuation_reason", "") or ""),
        tier=tier.value,
        quota_used=quota_used,
        quota_remaining=quota_remaining,
        elapsed_ms=elapsed_ms,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
