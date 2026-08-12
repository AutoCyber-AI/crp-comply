# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Session management routes for Phase 5 Security UX.

Provides Redis-backed server sessions with ``HttpOnly`` cookies plus
endpoints to list and revoke active sessions.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status

from crp_comply.api.deps import (
    get_auth_context,
    get_current_tenant,
    get_current_user,
    get_passkey_manager_for_request,
)
from crp_comply.api.session_store import (
    SESSION_COOKIE_NAME,
    STEP_UP_TTL_SECONDS,
    SessionRecord,
    get_session_store,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _cookie_settings() -> dict[str, Any]:
    """Return conservative cookie settings for the session cookie."""
    secure = os.environ.get("CRP_COMPLY_COOKIE_SECURE", "false").lower() in {"1", "true", "yes"}
    return {
        "key": SESSION_COOKIE_NAME,
        "httponly": True,
        "secure": secure,
        "samesite": "strict",
        "path": "/",
    }


def _current_session_id(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE_NAME)


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


def _hash_header(value: str | None) -> str | None:
    if not value:
        return None
    import hashlib

    return hashlib.sha256(value.encode()).hexdigest()[:16]


@router.post("/session", summary="Create or refresh a web session")
async def create_session(
    response: Response,
    request: Request,
    user_id: str = Depends(get_current_user),
    tenant_id: str | None = Depends(get_current_tenant),
    user_agent: str | None = Header(None),
) -> dict[str, Any]:
    """Create a server-side session and return it as an HttpOnly cookie."""
    store = get_session_store()
    ip = request.client.host if request.client else None
    record = await store.create(
        user_id=user_id,
        tenant_id=tenant_id,
        ip_hash=_hash_header(ip),
        ua_hash=_hash_header(user_agent),
    )
    settings = _cookie_settings()
    max_age = int(os.environ.get("CRP_COMPLY_SESSION_TTL_SECONDS", "604800"))
    response.set_cookie(value=record.session_id, max_age=max_age, **settings)
    logger.info("Session created for user %s", user_id)
    return {
        "session_id": record.session_id,
        "created_at": record.created_at,
        "expires_in_seconds": max_age,
    }


@router.get("/sessions", summary="List active sessions")
async def list_sessions(
    request: Request,
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    """Return active server-side sessions for the current user."""
    store = get_session_store()
    current_id = _current_session_id(request)
    records = await store.list_for_user(user_id)
    return {
        "sessions": [
            {
                "session_id": r.session_id,
                "current": r.session_id == current_id,
                "created_at": r.created_at,
                "last_seen_at": r.last_seen_at,
                "ip_hash": r.ip_hash,
                "ua_hash": r.ua_hash,
            }
            for r in records
        ],
        "count": len(records),
    }


@router.delete("/sessions/{session_id}", summary="Revoke a session")
async def revoke_session(
    session_id: str,
    response: Response,
    request: Request,
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    """Revoke a single session. Revoking the current session also clears the cookie."""
    store = get_session_store()
    ok = await store.revoke(session_id, user_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if _current_session_id(request) == session_id:
        response.delete_cookie(**_cookie_settings())
    return {"status": "revoked", "session_id": session_id}


@router.delete("/sessions", summary="Revoke all other sessions")
async def revoke_other_sessions(
    response: Response,
    request: Request,
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    """Revoke all sessions for the user except the current one."""
    store = get_session_store()
    current_id = _current_session_id(request)
    removed = await store.revoke_all_for_user(user_id, except_session_id=current_id)
    return {"status": "revoked", "removed": removed}


@router.post("/session/refresh", summary="Refresh current session TTL")
async def refresh_session(
    response: Response,
    request: Request,
    user_id: str = Depends(get_current_user),
) -> dict[str, Any]:
    """Touch the current session and refresh its cookie."""
    store = get_session_store()
    session_id = _current_session_id(request)
    if session_id:
        await store.touch(session_id)
    else:
        # No cookie yet; create one.
        record = await store.create(user_id=user_id)
        session_id = record.session_id
    max_age = int(os.environ.get("CRP_COMPLY_SESSION_TTL_SECONDS", "604800"))
    response.set_cookie(value=session_id, max_age=max_age, **_cookie_settings())
    return {"session_id": session_id, "refreshed_at": time.time()}


async def elevate_session(request: Request, session_id: str | None = None) -> SessionRecord | None:
    """Mark a session as step-up elevated for a short window.

    Used by the step-up authentication endpoint; callers must already
    have verified a fresh passkey assertion.
    """
    store = get_session_store()
    sid = session_id or _current_session_id(request)
    if not sid:
        return None
    record = await store.get(sid)
    if not record:
        return None
    until = time.time() + STEP_UP_TTL_SECONDS
    await store.set_elevated(sid, until)
    record.elevated_until = until
    return record


@router.post("/step-up", summary="Step-up authenticate with passkey")
async def step_up(
    request: Request,
    response: Response,
    user_id: str = Depends(get_current_user),
    tenant_id: str | None = Depends(get_current_tenant),
) -> dict[str, Any]:
    """Verify a fresh passkey assertion and elevate the current session.

    The session is marked as elevated for ``STEP_UP_TTL_SECONDS`` so
    sensitive actions can proceed without repeated re-authentication. An
    MFA session cookie is also set so the web frontend does not need to
    store the token in ``sessionStorage``.
    """
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
        logger.exception("[step-up] passkey verification failed for user=%s: %s", user_id, exc)
        raise HTTPException(
            status_code=400,
            detail="Passkey verification failed",
        ) from exc

    if auth_result["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Credential does not belong to user")

    if auth_result["decision"] == "block":
        raise HTTPException(
            status_code=403,
            detail="Login blocked by adaptive risk policy",
            headers={"X-Risk-Score": str(auth_result["risk_score"])},
        )

    record = await elevate_session(request)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active session cookie. Create a session first via POST /auth/session.",
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
        "status": "elevated",
        "elevated_until": record.elevated_until,
        "mfa_token": mfa_token,
        "expires_in": manager.session_ttl_seconds,
        "risk_score": auth_result["risk_score"],
        "risk_factors": auth_result["risk_factors"],
    }
