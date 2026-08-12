# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""FastAPI dependency injection — auth, comply instance, tier checks."""

from __future__ import annotations

import logging
import os
from typing import Annotated

from fastapi import Depends, HTTPException, Header, Request, status

from .session_store import SESSION_COOKIE_NAME, get_session_store

from ..core import CRPComply
from .auth import AuthManager, Tier
from crp_shared.auth import Identity
from crp_shared.passkey import AuthContext, PasskeyManager

logger = logging.getLogger(__name__)

# One-time warning so log spam is avoided when CLERK_ISSUER is absent.
_warned_clerk_issuer_missing: bool = False

# ── Singletons (initialised at app startup) ────────────────────
_auth_manager: AuthManager | None = None
_comply_instance: CRPComply | None = None
_passkey_manager: PasskeyManager | None = None


def init_dependencies(auth: AuthManager, comply: CRPComply) -> None:
    """Called once at app startup to inject singletons."""
    global _auth_manager, _comply_instance
    _auth_manager = auth
    _comply_instance = comply


def init_passkey_manager() -> PasskeyManager | None:
    """Initialise the shared passkey manager from the DB pool."""
    global _passkey_manager
    if _passkey_manager is not None:
        return _passkey_manager
    try:
        from crp_shared.db import _pool

        if _pool is None:
            return None
        rp_id = os.environ.get("PASSKEY_RP_ID", os.environ.get("DOMAIN", "localhost"))
        rp_id = rp_id.replace("https://", "").replace("http://", "").split(":")[0]
        origin = os.environ.get("PASSKEY_ORIGIN", os.environ.get("DOMAIN", "https://localhost"))
        if not origin.startswith(("http://", "https://")):
            origin = f"https://{origin}"
        _passkey_manager = PasskeyManager(
            pool=_pool,
            rp_id=rp_id,
            rp_name="CRP Comply",
            origin=origin,
            session_ttl_seconds=int(os.environ.get("PASSKEY_SESSION_TTL_SECONDS", "3600")),
        )
        logger.info("[startup] Passkey manager initialised (rp_id=%s)", rp_id)
        return _passkey_manager
    except Exception as exc:
        logger.warning("[startup] Passkey manager initialisation failed: %s", exc)
        return None


def get_passkey_manager() -> PasskeyManager | None:
    return _passkey_manager


def _derive_passkey_rp_and_origin(request: Request) -> tuple[str, str]:
    """Return the WebAuthn RP ID and origin for the current request.

    Environment variables take precedence so operators can pin the value in
    load-balanced or multi-tenant deployments. If unset, derive from the
    request itself so passkeys work on localhost, custom domains, and Railway
    without manual configuration.
    """
    env_rp_id = os.environ.get("PASSKEY_RP_ID") or os.environ.get("DOMAIN")
    if env_rp_id:
        rp_id = env_rp_id.replace("https://", "").replace("http://", "").split(":")[0]
        origin = os.environ.get("PASSKEY_ORIGIN") or os.environ.get("DOMAIN") or f"https://{rp_id}"
        if not origin.startswith(("http://", "https://")):
            origin = f"https://{origin}"
        return rp_id, origin

    # Prefer the browser's own Origin/Referer header so verification matches
    # the origin the authenticator signed.
    origin_header = request.headers.get("Origin") or request.headers.get("Referer")
    if origin_header:
        try:
            from urllib.parse import urlparse

            parsed = urlparse(origin_header)
            if parsed.hostname:
                host = parsed.hostname.split(":")[0]
                scheme = parsed.scheme or request.headers.get("X-Forwarded-Proto") or "https"
                return host, f"{scheme}://{host}"
        except Exception:
            pass

    host = (
        request.headers.get("X-Forwarded-Host")
        or request.headers.get("Host")
        or request.url.hostname
        or "localhost"
    )
    host = host.split(":")[0]
    scheme = request.headers.get("X-Forwarded-Proto") or request.url.scheme or "https"
    return host, f"{scheme}://{host}"


def get_passkey_manager_for_request(request: Request) -> PasskeyManager | None:
    """Return a passkey manager configured for the request's effective domain."""
    global_manager = get_passkey_manager()
    if global_manager is None:
        return None
    rp_id, origin = _derive_passkey_rp_and_origin(request)
    return PasskeyManager(
        pool=global_manager.pool,
        rp_id=rp_id,
        rp_name=global_manager.rp_name,
        origin=origin,
        session_ttl_seconds=global_manager.session_ttl_seconds,
        challenge_ttl_seconds=global_manager.challenge_ttl_seconds,
    )


def get_auth_context(request: Request) -> AuthContext:
    """Build a privacy-preserving auth context from the request."""
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    ip = (
        forwarded_for.split(",")[0].strip()
        if forwarded_for
        else (request.client.host if request.client else "")
    )
    return AuthContext(
        ip_address=ip or "unknown",
        user_agent=request.headers.get("User-Agent", "") or "unknown",
        geo_hint=request.headers.get("X-Timezone", "") or None,
    )


async def require_passkey_mfa(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_passkey_mfa_session: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    """FastAPI dependency: require a valid passkey MFA session for Clerk users."""
    # API keys are long-lived service credentials; passkey MFA is for humans.
    if x_api_key:
        return
    if not authorization or not authorization.startswith("Bearer "):
        return
    manager = get_passkey_manager()
    if manager is None:
        return

    token = authorization[7:]
    auth = get_auth()
    clerk_claims = auth.verify_clerk_token(token)
    if not clerk_claims:
        return
    sub = clerk_claims.get("sub", "")
    if not sub.startswith("user_"):
        return
    user_id = f"clerk:{sub}"

    mfa_token = x_passkey_mfa_session
    if not mfa_token:
        mfa_token = request.cookies.get("crp_passkey_mfa_token")
    context = get_auth_context(request)
    assessment = await manager.verify_mfa_session(mfa_token, user_id, context)
    if assessment is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"detail": "Passkey MFA required", "code": "passkey_mfa_required"},
        )
    if assessment.decision in ("challenge", "block"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "detail": "Passkey step-up required",
                "code": "passkey_step_up",
                "risk_score": assessment.score,
                "risk_factors": assessment.factors,
            },
        )


def get_auth() -> AuthManager:
    if _auth_manager is None:
        raise RuntimeError("AuthManager not initialised")
    return _auth_manager


def get_comply() -> CRPComply:
    if _comply_instance is None:
        raise RuntimeError("CRPComply not initialised")
    return _comply_instance


async def _extract_credentials(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
) -> tuple[str, Tier]:
    """Extract user identity from Bearer token, API key header, or session cookie.

    Returns (user_id, tier).
    """
    auth = get_auth()

    # Try API key first
    if x_api_key:
        result = auth.verify_api_key(x_api_key)
        if result:
            return result
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
        )

    # Try Bearer token
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:]

        # Try Clerk JWT first (RS256, verified via JWKS)
        clerk_claims = auth.verify_clerk_token(token)
        if clerk_claims is None and not os.environ.get("CLERK_ISSUER"):
            global _warned_clerk_issuer_missing
            if not _warned_clerk_issuer_missing:
                _warned_clerk_issuer_missing = True
                logger.warning(
                    "Bearer token received but CLERK_ISSUER env var is not set — "
                    "Clerk JWT verification is disabled. All signed-in users will get "
                    "401 Unauthorized. Set CLERK_ISSUER=https://<your-frontend-api> "
                    "in your Railway environment variables to enable Clerk auth."
                )
        if clerk_claims:
            clerk_user_id = clerk_claims.get("sub", "")
            # Clerk organisation handle lives under ``org_id`` (session
            # claim) or ``o.id`` / ``organization_id`` depending on the
            # template. We take the first non-empty value so multi-org
            # deployments get true per-workspace isolation. When the
            # claim is absent we fall back to solo tenancy (tenant=user).
            tenant_id = (
                str(clerk_claims.get("org_id") or "").strip()
                or str(clerk_claims.get("organization_id") or "").strip()
                or (
                    str((clerk_claims.get("o") or {}).get("id") or "").strip()
                    if isinstance(clerk_claims.get("o"), dict)
                    else ""
                )
            )
            # Upsert user from Clerk — email may not be in session token,
            # so we use the Clerk user ID as fallback
            user = auth.upsert_oauth_user(
                provider="clerk",
                provider_id=clerk_user_id,
                email=clerk_claims.get("email", f"{clerk_user_id}@clerk"),
                name=clerk_claims.get("name", clerk_user_id),
                tenant_id=tenant_id or None,
            )
            return user.id, user.tier

        # Fall back to internal JWT (HS256)
        user_id = auth.verify_token(token)
        if user_id:
            user = auth.get_user(user_id)
            if user:
                return user_id, user.tier
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    # Try HttpOnly session cookie (Phase 5)
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id:
        store = get_session_store()
        record = await store.get(session_id)
        if record:
            await store.touch(session_id)
            try:
                tier = Tier(record.tier)
            except ValueError:
                tier = Tier.FREE
            return record.user_id, tier

    # No auth provided — allow with FREE tier for health/public endpoints
    # The route-level feature check will block restricted endpoints
    return "anonymous", Tier.FREE


async def get_current_user(
    creds: Annotated[tuple[str, Tier], Depends(_extract_credentials)],
) -> str:
    return creds[0]


async def get_current_tier(
    creds: Annotated[tuple[str, Tier], Depends(_extract_credentials)],
) -> Tier:
    return creds[1]


async def get_current_tenant(
    creds: Annotated[tuple[str, Tier], Depends(_extract_credentials)],
) -> str:
    """Return the tenant (workspace / org) handle for the caller.

    For Clerk callers this is the ``org_id`` claim when present;
    otherwise it mirrors ``user_id`` so solo-tenant deployments keep
    working. Anonymous callers get ``"anonymous"``.

    **Use this — not ``get_current_user`` — when scoping queries to
    multi-seat resources** (inbox, contact profile, shared recipes).
    Mixing the two is how cross-account leaks happen.
    """
    user_id, _tier = creds
    if user_id == "anonymous":
        return "anonymous"
    return get_auth().get_tenant_id(user_id)


# ---------------------------------------------------------------------------
# Identity-aware auth (NEW — aligns with CRP shared auth spec)
# ---------------------------------------------------------------------------


async def current_clerk_identity(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> "Identity":
    """FastAPI dependency: verify Clerk JWT and return Identity.

    Uses the shared CRP auth layer (authorizedParties validation,
    JWKS caching, proper claim extraction) with the real FastAPI
    request so Origin, User-Agent and IP are available for validation.
    """
    from crp_shared.auth import current_clerk_identity as _shared_current_clerk_identity

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )

    return await _shared_current_clerk_identity(request)


def meter_call(endpoint: str):
    """FastAPI dependency factory: count this request against the user's monthly quota.

    Anonymous users are skipped here (the public router has its own IP rate-limit).
    Authenticated users on HARD_BLOCK tiers get a 402 if they're over quota.
    SOFT_ALLOW tiers are recorded as overage for downstream metered billing.

    Usage in a route:
        @router.post("/some-thing", dependencies=[Depends(meter_call("some_thing"))])
    """
    from .usage import QuotaExceededError, get_usage_tracker

    async def _dep(
        creds: Annotated[tuple[str, Tier], Depends(_extract_credentials)],
    ) -> None:
        user_id, tier = creds
        if user_id == "anonymous":
            return
        # First-touch welcome bonus: every signed-in user gets $5 of
        # platform credit (~100 hosted calls) so they can experience the
        # full agent flow before being asked for a key. Idempotent.
        try:
            from .credits import get_credit_store

            get_credit_store().ensure_welcome_bonus(user_id)
        except Exception:  # pragma: no cover — never block on bonus
            pass
        try:
            get_usage_tracker().record_call(user_id, tier, endpoint)
        except QuotaExceededError as exc:
            # Before hard-blocking, try to absorb the call from the user's
            # prepaid credit-pack balance (Stripe one-time top-ups). Only
            # if there is no balance left do we return 402.
            from .credits import get_credit_store
            import os as _os

            try:
                overage_usd = float(_os.environ.get("CRP_COMPLY_OVERAGE_USD_PER_CALL", "0.05"))
            except ValueError:
                overage_usd = 0.05
            ok, balance = get_credit_store().charge_usd(user_id, overage_usd, f"overage:{endpoint}")
            if ok:
                # Credit pack absorbed the overage — let the call proceed.
                return
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "error": "quota_exceeded",
                    "message": (
                        f"Monthly quota of {exc.quota} calls reached on the "
                        f"{exc.tier.value} tier. Buy a credit pack to continue, "
                        f"upgrade your plan, or switch to Local mode."
                    ),
                    "tier": exc.tier.value,
                    "used": exc.used,
                    "quota": exc.quota,
                    "credit_balance_usd": balance.get("balance_usd", 0.0),
                    "upgrade_url": "/pricing",
                    "topup_url": "/app/billing#credits",
                },
                headers={"X-Quota-Reset-At": ""},
            ) from exc

    return _dep
