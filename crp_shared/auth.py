# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Shared Clerk JWT verification, identity resolution, and entitlement.

Used by BOTH CRP Gateway and CRP Comply. Keep in sync across repos.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import HTTPException, Request

logger = logging.getLogger(__name__)

CLERK_ISSUER = os.environ.get("CLERK_ISSUER", "https://clerk.crprotocol.io")
CLERK_SECRET_KEY = os.environ.get("CLERK_SECRET_KEY", "")
CLERK_PUBLISHABLE_KEY = os.environ.get("CLERK_PUBLISHABLE_KEY", "")
CLERK_AUDIENCE = os.environ.get("CLERK_AUDIENCE", "crp-comply")

# Security: only accept tokens issued for these parties.
AUTHORIZED_PARTIES = [
    p.strip()
    for p in os.environ.get(
        "CLERK_AUTHORIZED_PARTIES",
        "https://comply.crprotocol.io,https://gateway.crprotocol.io",
    ).split(",")
    if p.strip()
]


# ---------------------------------------------------------------------------
# Identity model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Identity:
    """Clerk-authenticated identity."""

    user_id: str       # Clerk "sub" claim
    org_id: str | None  # Clerk "org_id" claim (None for personal accounts)
    org_role: str | None  # Clerk "org_role" claim


def resolve_account(identity: Identity) -> tuple[str, str]:
    """Return (account_type, account_id).

    Teams:  ("org", org_id)
    Personal: ("user", user_id)
    """
    if identity.org_id:
        return ("org", identity.org_id)
    return ("user", identity.user_id)


# ---------------------------------------------------------------------------
# JWT verification
# ---------------------------------------------------------------------------

_jwks_cache: dict[str, Any] | None = None
_jwks_fetched_at: float = 0.0
_JWKS_TTL_SECONDS = 3600

# In-memory token revocation list (JTI).
# TODO: Replace with Redis-backed revocation list for production.
_revoked_jtis: set[str] = set()


def revoke_token_jti(jti: str) -> None:
    """Add a JWT ID to the revoked set."""
    _revoked_jtis.add(jti)


async def _fetch_jwks() -> dict[str, Any] | None:
    """Fetch and cache Clerk JWKS."""
    global _jwks_cache, _jwks_fetched_at
    import time

    now = time.time()
    if _jwks_cache and (now - _jwks_fetched_at) < _JWKS_TTL_SECONDS:
        return _jwks_cache

    jwks_url = f"{CLERK_ISSUER.rstrip('/')}/.well-known/jwks.json"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(jwks_url, timeout=10)
            resp.raise_for_status()
            _jwks_cache = resp.json()
            _jwks_fetched_at = now
            logger.info("Fetched Clerk JWKS from %s", jwks_url)
            return _jwks_cache
    except Exception as exc:
        logger.warning("Failed to fetch Clerk JWKS: %s", exc)
        return _jwks_cache  # return stale if available


async def current_clerk_identity(request: Request) -> Identity:
    """FastAPI dependency: verify Clerk JWT and return Identity."""
    auth_header = request.headers.get("Authorization") or ""
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    token = auth_header[7:]
    if not token:
        raise HTTPException(status_code=401, detail="Empty bearer token")

    # Try python-jose first (lightweight, no extra deps)
    try:
        from jose import JWTError, jwt as jose_jwt

        jwks = await _fetch_jwks()
        if not jwks:
            raise HTTPException(status_code=503, detail="Clerk JWKS unavailable")

        header = jose_jwt.get_unverified_header(token)
        kid = header.get("kid")
        key = None
        for k in jwks.get("keys", []):
            if k.get("kid") == kid:
                key = k
                break
        if not key:
            raise HTTPException(status_code=401, detail="Invalid token key ID")

        claims = jose_jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            issuer=CLERK_ISSUER,
            audience=CLERK_AUDIENCE,
            options={"verify_aud": True},
        )
    except JWTError as exc:
        logger.warning("Clerk JWT verification failed: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid token") from exc
    except Exception as exc:
        logger.warning("Clerk JWT verification error: %s", exc)
        raise HTTPException(status_code=401, detail="Token verification failed") from exc

    # Security: verify authorizedParties
    azp = claims.get("azp")
    if azp and AUTHORIZED_PARTIES and azp not in AUTHORIZED_PARTIES:
        logger.warning("Unauthorized party: azp=%s", azp)
        raise HTTPException(status_code=401, detail="Unauthorized party")

    # Fallback: check Origin/Referer header if azp is absent
    if not azp and AUTHORIZED_PARTIES:
        origin = request.headers.get("Origin") or request.headers.get("Referer") or ""
        if origin:
            from urllib.parse import urlparse
            parsed = urlparse(origin)
            origin_host = f"{parsed.scheme}://{parsed.netloc}"
            if origin_host not in AUTHORIZED_PARTIES:
                logger.warning("Unauthorized origin: %s", origin_host)
                raise HTTPException(status_code=401, detail="Unauthorized origin")
        else:
            # No azp and no origin — be strict in production, lenient in dev
            if os.environ.get("ENV", "production") != "development":
                logger.warning("No azp or origin in token — rejecting in production")
                raise HTTPException(status_code=401, detail="Unauthorized request")

    user_id = claims.get("sub", "")
    org_id = claims.get("org_id") or claims.get("organization_id") or None
    org_role = claims.get("org_role") or None

    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing sub claim")

    # Security: basic JTI revocation check (in-memory only).
    jti = claims.get("jti")
    if jti and jti in _revoked_jtis:
        logger.warning("Revoked token used: jti=%s", jti)
        raise HTTPException(status_code=401, detail="Token revoked")

    # Device fingerprint for anomaly detection.
    user_agent = request.headers.get("User-Agent", "") or ""
    client_ip = request.headers.get("CF-Connecting-IP") or request.headers.get("X-Forwarded-For", "") or ""
    logger.debug("Auth: user=%s ip=%s ua=%s", user_id, client_ip, user_agent[:50])

    return Identity(user_id=user_id, org_id=org_id, org_role=org_role)


# ---------------------------------------------------------------------------
# Entitlement (read from Clerk metadata)
# ---------------------------------------------------------------------------

_entitlement_cache: dict[str, tuple[dict[str, Any], float]] = {}
_ENTITLEMENT_TTL_SECONDS = 60


async def get_entitlement(identity: Identity, product: str) -> dict[str, Any]:
    """Read per-product entitlement from Clerk org/user metadata.

    Args:
        identity: The authenticated identity.
        product: One of "comply", "gateway", "scan".

    Returns:
        {"plan": str, "quota": int, "credits": int, "stripe_customer_id": str|None}
    """
    import time

    cache_key = f"{identity.user_id}:{identity.org_id or ''}:{product}"
    now = time.time()
    cached = _entitlement_cache.get(cache_key)
    if cached and (now - cached[1]) < _ENTITLEMENT_TTL_SECONDS:
        return cached[0]

    if not CLERK_SECRET_KEY:
        logger.warning("CLERK_SECRET_KEY not set — entitlement reads disabled")
        return {"plan": "free", "quota": 100, "credits": 0, "stripe_customer_id": None}

    kind, account_id = resolve_account(identity)
    base = "organizations" if kind == "org" else "users"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://api.clerk.com/v1/{base}/{account_id}",
                headers={"Authorization": f"Bearer {CLERK_SECRET_KEY}"},
                timeout=10,
            )
            resp.raise_for_status()
            meta = resp.json().get("public_metadata", {})
    except Exception as exc:
        logger.warning("Failed to read Clerk metadata for %s/%s: %s", base, account_id, exc)
        return {"plan": "free", "quota": 100, "credits": 0, "stripe_customer_id": None}

    result = {
        "plan": meta.get(f"{product}_plan", "free"),
        "quota": meta.get(f"{product}_quota", 100),
        "credits": meta.get("creditBalanceCents", 0),
        "stripe_customer_id": meta.get("stripeCustomerId"),
    }
    _entitlement_cache[cache_key] = (result, now)
    return result
