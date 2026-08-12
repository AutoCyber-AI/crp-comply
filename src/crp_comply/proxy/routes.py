# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""OpenAI-compatible proxy routes with compliance interception.

Provides drop-in replacement endpoints for the OpenAI API:
  POST /v1/chat/completions   — proxied chat completions (streaming + non-streaming)
  GET  /v1/models             — forwarded model list
  GET  /v1/compliance/records — list proxy audit records
  GET  /v1/compliance/records/{id}        — single audit record
  GET  /v1/compliance/records/{id}/verify — HMAC integrity check
  GET  /v1/compliance/stats   — aggregate compliance statistics
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse, StreamingResponse

from ..api.auth import Tier
from ..api.deps import get_auth
from .interceptor import ComplianceInterceptor
from .models import ChatCompletionRequest

logger = logging.getLogger("crp_comply.proxy")

router = APIRouter(tags=["proxy"])
openai_router = APIRouter(tags=["proxy-openai"])

# ── Singleton ──────────────────────────────────────────────────

_interceptor: ComplianceInterceptor | None = None


def init_proxy(interceptor: ComplianceInterceptor) -> None:
    """Inject the shared :class:`ComplianceInterceptor` at startup."""
    global _interceptor
    _interceptor = interceptor


def _get_interceptor() -> ComplianceInterceptor:
    if _interceptor is None:
        raise RuntimeError("Proxy interceptor not initialised")
    return _interceptor


# ── Credential Resolution ─────────────────────────────────────

API_KEY_PREFIX = "crp_"
API_KEY_LEGACY_PREFIX = "crc_"


@dataclass
class ProxyCredentials:
    tier: Tier
    user_id: str
    upstream_url: str
    upstream_key: str


async def resolve_proxy_credentials(
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
    x_upstream_api_key: Annotated[str | None, Header()] = None,
    x_upstream_url: Annotated[str | None, Header()] = None,
) -> ProxyCredentials:
    """Resolve CRP Comply auth + upstream LLM credentials.

    Supports two usage modes:

    **Managed mode** (server holds upstream key):
        Authorization: Bearer crc_...
        (upstream key from CRP_COMPLY_UPSTREAM_API_KEY env)

    **BYOK mode** (bring-your-own-key):
        X-API-Key: crc_...
        Authorization: Bearer <YOUR_API_KEY>   (forwarded to upstream)
    """
    auth = get_auth()
    tier = Tier.FREE
    user_id = "anonymous"
    upstream_key: str | None = x_upstream_api_key

    # ── CRP Comply auth ──
    # Priority: X-API-Key header > Authorization with CRP key prefix
    def _is_crp_key(k: str) -> bool:
        return k.startswith(API_KEY_PREFIX) or k.startswith(API_KEY_LEGACY_PREFIX)

    if x_api_key and _is_crp_key(x_api_key):
        result = auth.verify_api_key(x_api_key)
        if result:
            user_id, tier = result
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid CRP Comply API key",
            )

    # ── Upstream key ──
    # Priority: X-Upstream-API-Key > Authorization (if not CRP key) > env
    if not upstream_key and authorization and authorization.startswith("Bearer "):
        token = authorization[7:]
        if _is_crp_key(token):
            # It's a CRP key in the Authorization header (managed mode)
            if user_id == "anonymous":
                result = auth.verify_api_key(token)
                if result:
                    user_id, tier = result
                else:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid CRP Comply API key",
                    )
        else:
            # Regular LLM API key — forward to upstream
            upstream_key = token

    if not upstream_key:
        upstream_key = os.environ.get("CRP_COMPLY_UPSTREAM_API_KEY", "")

    # ── Per-user provider config (from setup wizard) ──
    if not upstream_key:
        try:
            from ..api.provider import get_user_upstream

            user_cfg = get_user_upstream(user_id)
            if user_cfg:
                x_upstream_url = x_upstream_url or user_cfg[0]
                upstream_key = user_cfg[1]
        except RuntimeError:
            pass  # Provider store not initialised (tests, CLI)

    if not upstream_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No LLM provider configured. Visit the setup wizard to "
                "connect your OpenAI or Anthropic API key, or provide "
                "X-Upstream-API-Key header."
            ),
        )

    # ── Upstream URL ──
    upstream_url = x_upstream_url or os.environ.get(
        "CRP_COMPLY_UPSTREAM_URL", "https://api.openai.com/v1"
    )

    return ProxyCredentials(
        tier=tier,
        user_id=user_id,
        upstream_url=upstream_url,
        upstream_key=upstream_key,
    )


# ── Chat Completions ──────────────────────────────────────────


@openai_router.post("/chat/completions")
async def proxy_chat_completions(
    req: ChatCompletionRequest,
    request: Request,
    creds: ProxyCredentials = Depends(resolve_proxy_credentials),
):
    """OpenAI-compatible ``POST /v1/chat/completions`` with automatic
    compliance interception, PII scanning, and audit trail generation.
    """
    from ..api.routes import check_rate_limit

    check_rate_limit(creds.user_id, creds.tier.value)

    interceptor = _get_interceptor()
    request_id = str(uuid.uuid4())
    purpose = interceptor.infer_processing_purpose(path=request.url.path)

    # ── Pre-flight compliance checks ──
    input_text = interceptor.extract_text(req)
    # Round 5: SECURITY_SCANNING requires explicit per-user consent.
    can_scan = interceptor.check_user_consent(creds.user_id, purpose)
    if can_scan:
        pre_pii = interceptor.scan_pii(input_text)
        injection_risk = interceptor.detect_injection(input_text)
    else:
        logger.warning(
            "SECURITY_SCANNING consent not granted for user=%s; running degraded (no scan)",
            creds.user_id,
        )
        pre_pii = (False, [])
        injection_risk = "NONE"

    if pre_pii[0]:
        logger.warning(
            "PII detected in input: categories=%s user=%s",
            pre_pii[1],
            creds.user_id,
        )
    if injection_risk != "NONE":
        logger.warning("Prompt injection risk=%s user=%s", injection_risk, creds.user_id)

    if req.stream:
        return _streaming_response(
            req, request, interceptor, creds, pre_pii, injection_risk, request_id, purpose
        )

    # ── Non-streaming path ──
    try:
        response = await interceptor.forward_chat_completion(
            req, creds.upstream_url, creds.upstream_key
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Upstream error: {e.response.text[:500]}",
        )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to reach upstream provider: {e}",
        )

    # ── Post-flight compliance checks ──
    response_text = ""
    if response.choices:
        response_text = response.choices[0].message.content or ""
    post_pii = interceptor.scan_pii(response_text)

    record = interceptor.create_audit_record(
        request=req,
        response_text=response_text,
        response_model=response.model,
        input_tokens=response.usage.prompt_tokens if response.usage else 0,
        output_tokens=response.usage.completion_tokens if response.usage else 0,
        pre_pii=pre_pii,
        post_pii=post_pii,
        injection_risk=injection_risk,
        tier=creds.tier.value,
        user_id=creds.user_id,
        request_id=request_id,
        purpose=purpose,
        path=request.url.path,
    )

    # Return standard OpenAI response with compliance headers
    resp_data = response.model_dump(exclude_none=True)
    return JSONResponse(
        content=resp_data,
        headers={
            "X-CRP-Comply": "active",
            "X-CRP-Comply-Record-ID": record.record_id,
            "X-CRP-Comply-Risk": record.risk_level,
            "X-CRP-Comply-Hallucination-Risk": record.provenance.get(
                "hallucination_risk_level", "UNKNOWN"
            )
            if hasattr(record, "provenance") and record.provenance
            else "UNKNOWN",
        },
    )


def _streaming_response(
    req: ChatCompletionRequest,
    request: Request,
    interceptor: ComplianceInterceptor,
    creds: ProxyCredentials,
    pre_pii: tuple[bool, list[str]],
    injection_risk: str,
    request_id: str,
    purpose: Any,
) -> StreamingResponse:
    """Build a ``StreamingResponse`` that proxies SSE chunks from the
    upstream provider while accumulating content for post-hoc audit.
    """

    async def event_generator():
        collected_content: list[str] = []
        response_model = req.model

        headers = {
            "Authorization": f"Bearer {creds.upstream_key}",
            "Content-Type": "application/json",
        }
        url = f"{creds.upstream_url.rstrip('/')}/chat/completions"
        body = req.model_dump(exclude_none=True)
        body["stream"] = True

        try:
            async with interceptor.http_client.stream(
                "POST", url, json=body, headers=headers
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    stripped = line.strip()
                    if not stripped:
                        continue

                    # Forward raw SSE line
                    yield f"{stripped}\n\n"

                    # Parse for audit
                    if stripped.startswith("data: "):
                        data_str = stripped[6:]
                        if data_str == "[DONE]":
                            continue
                        try:
                            data = json.loads(data_str)
                            if "model" in data:
                                response_model = data["model"]
                            for choice in data.get("choices", []):
                                delta = choice.get("delta", {})
                                content = delta.get("content")
                                if content:
                                    collected_content.append(content)
                        except json.JSONDecodeError:
                            pass

        except httpx.HTTPStatusError as e:
            error = {
                "error": {
                    "message": f"Upstream error: {e.response.status_code}",
                    "type": "upstream_error",
                }
            }
            yield f"data: {json.dumps(error)}\n\n"
            yield "data: [DONE]\n\n"
            return
        except httpx.RequestError as e:
            error = {"error": {"message": f"Connection failed: {e}", "type": "connection_error"}}
            yield f"data: {json.dumps(error)}\n\n"
            yield "data: [DONE]\n\n"
            return

        # ── Post-stream audit ──
        full_response = "".join(collected_content)
        post_pii = interceptor.scan_pii(full_response)

        try:
            interceptor.create_audit_record(
                request=req,
                response_text=full_response,
                response_model=response_model,
                input_tokens=0,  # not available in streaming mode
                output_tokens=0,
                pre_pii=pre_pii,
                post_pii=post_pii,
                injection_risk=injection_risk,
                tier=creds.tier.value,
                user_id=creds.user_id,
                request_id=request_id,
                purpose=purpose,
                path=request.url.path,
            )
        except Exception:
            logger.exception("Failed to create audit record for streamed request")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-CRP-Comply": "active",
        },
    )


# ── Models List ────────────────────────────────────────────────


@openai_router.get("/models")
async def proxy_list_models(
    creds: ProxyCredentials = Depends(resolve_proxy_credentials),
):
    """Forward ``GET /v1/models`` to the upstream provider."""
    interceptor = _get_interceptor()
    try:
        return await interceptor.forward_models_list(creds.upstream_url, creds.upstream_key)
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"Upstream error: {e.response.text[:500]}",
        )
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to reach upstream: {e}",
        )


# ── Compliance Record Endpoints ────────────────────────────────


@router.get("/compliance/records", tags=["proxy-compliance"])
async def list_compliance_records(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    creds: ProxyCredentials = Depends(resolve_proxy_credentials),
):
    """List proxy compliance audit records for the current user (newest first)."""
    interceptor = _get_interceptor()
    # Per-user isolation: non-admin users only see their own records
    user_filter = creds.user_id if creds.user_id != "anonymous" else None
    records = interceptor.list_audit_records(
        limit=limit,
        offset=offset,
        user_id=user_filter,
    )
    return {"records": records, "count": len(records), "limit": limit, "offset": offset}


@router.get("/compliance/records/{record_id}", tags=["proxy-compliance"])
async def get_compliance_record(
    record_id: str,
    creds: ProxyCredentials = Depends(resolve_proxy_credentials),
):
    """Get a single proxy audit record by ID."""
    interceptor = _get_interceptor()
    record = interceptor.get_audit_record(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Audit record not found")
    return record


@router.get("/compliance/records/{record_id}/verify", tags=["proxy-compliance"])
async def verify_compliance_record(
    record_id: str,
    creds: ProxyCredentials = Depends(resolve_proxy_credentials),
):
    """Verify HMAC-SHA256 integrity of an audit record."""
    interceptor = _get_interceptor()
    record = interceptor.get_audit_record(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Audit record not found")

    valid = interceptor.verify_audit_record(record_id)
    return {
        "record_id": record_id,
        "integrity_valid": valid,
        "algorithm": "HMAC-SHA256",
    }


@router.get("/compliance/stats", tags=["proxy-compliance"])
async def compliance_stats(
    creds: ProxyCredentials = Depends(resolve_proxy_credentials),
):
    """Per-user compliance statistics across proxied requests."""
    interceptor = _get_interceptor()
    user_filter = creds.user_id if creds.user_id != "anonymous" else None
    return interceptor.get_compliance_stats(user_id=user_filter)


# ── GDPR Art. 17 — Right to Erasure ──────────────────────────


@router.delete("/compliance/erase/{user_id}", tags=["proxy-compliance"])
async def erase_user_data(
    user_id: str,
    creds: ProxyCredentials = Depends(resolve_proxy_credentials),
):
    """Erase all audit records for a user (GDPR Art. 17)."""
    if creds.user_id != user_id and creds.tier.value not in ("enterprise", "cloud"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Self-erasure only; admins require enterprise tier",
        )
    interceptor = _get_interceptor()
    deleted = interceptor.erase_user_data(user_id)
    return {
        "user_id": user_id,
        "items_erased": deleted,
        "gdpr_art17": True,
    }


# ── Audit Chain Verification ──────────────────────────────────


@router.get("/compliance/chain/verify", tags=["proxy-compliance"])
async def verify_audit_chain(
    creds: ProxyCredentials = Depends(resolve_proxy_credentials),
):
    """Verify the CRP tamper-evident audit trail chain integrity."""
    interceptor = _get_interceptor()
    valid, broken_at = interceptor.verify_audit_chain()
    return {
        "chain_valid": valid,
        "broken_at_sequence": broken_at,
        "algorithm": "HMAC-SHA256-chained",
    }


# ── Audit Trail Export (regulatory submission) ────────────────


@router.get("/compliance/export", tags=["proxy-compliance"])
async def export_audit_trail(
    creds: ProxyCredentials = Depends(resolve_proxy_credentials),
):
    """Export the full CRP audit trail for regulatory submission."""
    interceptor = _get_interceptor()
    return interceptor.export_audit_trail()


# ── GDPR Art. 30 — Processing Records ────────────────────────


@router.get("/compliance/processing-records", tags=["proxy-compliance"])
async def list_processing_records(
    creds: ProxyCredentials = Depends(resolve_proxy_credentials),
):
    """Export GDPR Art. 30 processing activity records."""
    interceptor = _get_interceptor()
    records = interceptor.export_processing_records()
    return {"records": records, "count": len(records), "gdpr_art30": True}


# ── Injection Analysis ────────────────────────────────────────


@router.post("/compliance/analyze/injection", tags=["proxy-compliance"])
async def analyze_injection(
    body: dict,
    creds: ProxyCredentials = Depends(resolve_proxy_credentials),
):
    """Detailed injection analysis using CRP InjectionDetector (21 patterns + ML)."""
    text = body.get("text", "")
    if not text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide 'text' field to analyze",
        )
    interceptor = _get_interceptor()
    return interceptor.get_injection_details(text)


# ── Consent Management (CRP ConsentManager) ───────────────────


@router.post("/compliance/consent/grant", tags=["proxy-compliance"])
async def grant_consent(
    body: dict,
    creds: ProxyCredentials = Depends(resolve_proxy_credentials),
):
    """Grant consent for a processing purpose via CRP ConsentManager."""
    purpose = body.get("purpose", "")
    if not purpose:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide 'purpose' field (e.g. 'security_scanning', 'analytics')",
        )
    interceptor = _get_interceptor()
    interceptor.grant_consent(purpose)
    return {
        "status": "granted",
        "purpose": purpose,
        "user_id": creds.user_id,
    }


@router.post("/compliance/consent/deny", tags=["proxy-compliance"])
async def deny_consent(
    body: dict,
    creds: ProxyCredentials = Depends(resolve_proxy_credentials),
):
    """Deny/withdraw consent for a processing purpose via CRP ConsentManager."""
    purpose = body.get("purpose", "")
    if not purpose:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide 'purpose' field to deny",
        )
    interceptor = _get_interceptor()
    interceptor.deny_consent(purpose)
    return {
        "status": "denied",
        "purpose": purpose,
        "user_id": creds.user_id,
    }


@router.get("/compliance/consent", tags=["proxy-compliance"])
async def get_consent_status(
    creds: ProxyCredentials = Depends(resolve_proxy_credentials),
):
    """Get current consent status from CRP ConsentManager."""
    interceptor = _get_interceptor()
    return interceptor.get_consent_status()


# ── Retention Management (CRP RetentionManager) ──────────────


@router.post("/compliance/retention/enforce", tags=["proxy-compliance"])
async def enforce_retention(
    creds: ProxyCredentials = Depends(resolve_proxy_credentials),
):
    """Trigger retention policy enforcement — purge expired records."""
    if creds.tier.value not in ("enterprise", "cloud"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Retention enforcement requires enterprise or cloud tier",
        )
    interceptor = _get_interceptor()
    result = interceptor.enforce_retention()
    return result


@router.get("/compliance/retention", tags=["proxy-compliance"])
async def get_retention_status(
    creds: ProxyCredentials = Depends(resolve_proxy_credentials),
):
    """Get retention policy status from CRP RetentionManager."""
    interceptor = _get_interceptor()
    return interceptor.get_retention_status()


# ── Data Lineage (CRP DataLineageTracker) ─────────────────────


@router.get("/compliance/lineage", tags=["proxy-compliance"])
async def get_data_lineage(
    creds: ProxyCredentials = Depends(resolve_proxy_credentials),
):
    """Get data lineage summary from CRP DataLineageTracker."""
    interceptor = _get_interceptor()
    return interceptor.get_data_lineage()


# ── Quality Distribution ──────────────────────────────────────


@router.get("/compliance/quality", tags=["proxy-compliance"])
async def get_quality_summary(
    creds: ProxyCredentials = Depends(resolve_proxy_credentials),
):
    """Get quality tier distribution (S/A/B/C/D) across proxied requests."""
    interceptor = _get_interceptor()
    user_filter = creds.user_id if creds.user_id != "anonymous" else None
    stats = interceptor.get_compliance_stats(user_id=user_filter)
    return {
        "quality_distribution": stats.quality_distribution,
        "total_graded": sum(stats.quality_distribution.values()),
        "tiers": ["S", "A", "B", "C", "D"],
    }


# ── Audit Trail Query ─────────────────────────────────────────


@router.get("/compliance/audit-trail/query", tags=["proxy-compliance"])
async def query_audit_trail(
    event_type: str | None = Query(default=None),
    creds: ProxyCredentials = Depends(resolve_proxy_credentials),
):
    """Query CRP compliance audit trail events."""
    interceptor = _get_interceptor()
    session_filter = f"proxy:{creds.user_id}" if creds.user_id != "anonymous" else None
    entries = interceptor.query_audit_trail(
        event_type=event_type,
        session_id=session_filter,
    )
    return {"entries": entries, "count": len(entries)}


# ── Processing Summary (GDPR Art. 30) ─────────────────────────


@router.get("/compliance/processing-summary", tags=["proxy-compliance"])
async def processing_summary(
    creds: ProxyCredentials = Depends(resolve_proxy_credentials),
):
    """GDPR Art. 30 processing activity summary."""
    interceptor = _get_interceptor()
    return interceptor.processing_summary()


# ── Erasure Status (GDPR Art. 17) ──────────────────────────────


@router.get("/compliance/erasure-status", tags=["proxy-compliance"])
async def erasure_status(
    creds: ProxyCredentials = Depends(resolve_proxy_credentials),
):
    """GDPR Art. 17 erasure request status and history."""
    interceptor = _get_interceptor()
    return interceptor.erasure_status()
