# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Authentication & authorisation — API keys, JWT tokens, OAuth2, Clerk."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from jose import JWTError, jwt
from passlib.context import CryptContext

from . import auth_db_sync
from .models import APIKeyCreated, APIKeyResponse, Tier, UserInfo

logger = logging.getLogger("crp_comply.auth")

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ── Defaults ───────────────────────────────────────────────────
DEFAULT_JWT_ALGORITHM = "HS256"
DEFAULT_TOKEN_EXPIRE_SECONDS = 3600  # 1 hour
API_KEY_PREFIX = "crp_"  # crp-comply key prefix (was crc_; legacy keys still verified)
API_KEY_LEGACY_PREFIX = "crc_"  # accept old keys for backward compatibility
API_KEY_LENGTH = 48
API_KEY_DEFAULT_EXPIRY_DAYS = int(os.environ.get("API_KEY_DEFAULT_EXPIRY_DAYS", "365"))

# ── Clerk JWKS cache ───────────────────────────────────────────
_clerk_jwks_cache: dict[str, Any] | None = None
_clerk_jwks_fetched_at: float = 0
_CLERK_JWKS_CACHE_TTL = 3600  # 1 hour


def _get_clerk_jwks(issuer: str) -> dict[str, Any]:
    """Fetch and cache Clerk JWKS public keys."""
    global _clerk_jwks_cache, _clerk_jwks_fetched_at
    now = time.time()
    if _clerk_jwks_cache and (now - _clerk_jwks_fetched_at) < _CLERK_JWKS_CACHE_TTL:
        return _clerk_jwks_cache
    jwks_url = f"{issuer.rstrip('/')}/.well-known/jwks.json"
    resp = httpx.get(jwks_url, timeout=10)
    resp.raise_for_status()
    _clerk_jwks_cache = resp.json()
    _clerk_jwks_fetched_at = now
    logger.info("Fetched Clerk JWKS from %s", jwks_url)
    return _clerk_jwks_cache


class AuthManager:
    """Manages users, API keys, and JWT tokens.

    Uses PostgreSQL for persistence when DATABASE_URL is available,
    with local JSON files as a self-hosted fallback. The in-memory
    dictionaries remain authoritative after load so reads stay fast.
    """

    def __init__(
        self,
        data_dir: Path | str = "data",
        jwt_secret: str | None = None,
        token_expire_seconds: int = DEFAULT_TOKEN_EXPIRE_SECONDS,
    ) -> None:
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._users_file = self._data_dir / "users.json"
        self._keys_file = self._data_dir / "api_keys.json"

        # JWT secret — must be supplied explicitly or persisted on disk.
        # Never fall back to a random secret; that would invalidate all
        # existing tokens on restart.
        resolved_secret: str | None = jwt_secret
        if resolved_secret is None:
            secret_file = self._data_dir / ".jwt_secret"
            if secret_file.exists():
                resolved_secret = secret_file.read_text(encoding="utf-8").strip()
        if not resolved_secret:
            raise RuntimeError(
                "JWT secret is required. Pass jwt_secret or set "
                "CRP_COMPLY_JWT_SECRET and persist it."
            )
        self._jwt_secret = resolved_secret
        self._token_expire = token_expire_seconds

        self._users: dict[str, dict[str, Any]] = {}
        self._api_keys: dict[str, dict[str, Any]] = {}  # hash -> key metadata
        self._load()

    # ── Persistence ────────────────────────────────────────────
    def _load(self) -> None:
        if self._users_file.exists():
            self._users = json.loads(self._users_file.read_text(encoding="utf-8"))
        if self._keys_file.exists():
            self._api_keys = json.loads(self._keys_file.read_text(encoding="utf-8"))

    def _save_users(self) -> None:
        self._users_file.write_text(
            json.dumps(self._users, indent=2, default=str), encoding="utf-8"
        )

    def _save_keys(self) -> None:
        self._keys_file.write_text(
            json.dumps(self._api_keys, indent=2, default=str), encoding="utf-8"
        )

    # ── User Management ────────────────────────────────────────
    def upsert_oauth_user(
        self,
        provider: str,
        provider_id: str,
        email: str,
        name: str,
        tenant_id: str | None = None,
    ) -> UserInfo:
        """Create or update a user from OAuth2 login.

        ``tenant_id`` is the workspace / organisation handle (Clerk
        ``org_id``, SSO group, etc.). When omitted, the user's own id
        becomes the tenant — solo tenancy. Every data-returning endpoint
        filters by tenant so that a user in tenant A can never read
        resources persisted by tenant B, even if that user is later
        invited to tenant B.
        """
        user_id = f"{provider}:{provider_id}"
        now = datetime.now(timezone.utc).isoformat()
        resolved_tenant = (tenant_id or "").strip() or user_id

        if user_id in self._users:
            self._users[user_id]["email"] = email
            self._users[user_id]["name"] = name
            # Tenant is sticky once set — updates only when caller sends
            # a non-empty value. This prevents a silent downgrade from
            # org tenant to solo tenant on a token that lacks the claim.
            if tenant_id:
                self._users[user_id]["tenant_id"] = resolved_tenant
            else:
                self._users[user_id].setdefault("tenant_id", resolved_tenant)
        else:
            self._users[user_id] = {
                "id": user_id,
                "email": email,
                "name": name,
                "provider": provider,
                "tier": Tier.FREE.value,
                "created_at": now,
                "tenant_id": resolved_tenant,
            }
        self._save_users()
        auth_db_sync.upsert_user(self._users[user_id])
        u = self._users[user_id]
        return UserInfo(
            id=u["id"],
            email=u["email"],
            name=u["name"],
            provider=u["provider"],
            tier=Tier(u["tier"]),
            created_at=u["created_at"],
            tenant_id=u.get("tenant_id") or u["id"],
            stripe_customer_id=u.get("stripe_customer_id"),
            stripe_subscription_id=u.get("stripe_subscription_id"),
            subscription_status=u.get("subscription_status"),
            cancel_at_period_end=bool(u.get("cancel_at_period_end", False)),
            current_period_end=u.get("current_period_end"),
        )

    def get_user(self, user_id: str) -> UserInfo | None:
        # Prefer live DB record when available so upgrades/changes are
        # visible immediately across instances.
        db_user = auth_db_sync.get_user(user_id)
        u = db_user or self._users.get(user_id)
        if not u:
            return None
        return UserInfo(
            id=u["id"],
            email=u["email"],
            name=u["name"],
            provider=u["provider"],
            tier=Tier(u["tier"]),
            created_at=u["created_at"],
            tenant_id=u.get("tenant_id") or u["id"],
        )

    def get_tenant_id(self, user_id: str) -> str:
        """Return the tenant handle for ``user_id``.

        Falls back to ``user_id`` itself when no record exists yet or
        when the stored record predates the tenant field — the same
        solo-tenant default used on first insert.
        """
        u = self._users.get(user_id)
        if not u:
            return user_id
        return u.get("tenant_id") or user_id

    def set_user_tier(self, user_id: str, tier: Tier) -> bool:
        if user_id not in self._users:
            db_user = auth_db_sync.get_user(user_id)
            if not db_user:
                return False
            self._users[user_id] = db_user
        self._users[user_id]["tier"] = tier.value
        self._save_users()
        auth_db_sync.set_user_tier(user_id, tier.value)
        return True

    def set_user_subscription(
        self,
        user_id: str,
        *,
        stripe_customer_id: str | None = None,
        stripe_subscription_id: str | None = None,
        subscription_status: str | None = None,
        cancel_at_period_end: bool | None = None,
        current_period_end: str | None = None,
    ) -> bool:
        """Persist Stripe subscription metadata for a user."""
        if user_id not in self._users:
            db_user = auth_db_sync.get_user(user_id)
            if not db_user:
                return False
            self._users[user_id] = db_user
        user = self._users[user_id]
        if stripe_customer_id is not None:
            user["stripe_customer_id"] = stripe_customer_id
        if stripe_subscription_id is not None:
            user["stripe_subscription_id"] = stripe_subscription_id
        if subscription_status is not None:
            user["subscription_status"] = subscription_status
        if cancel_at_period_end is not None:
            user["cancel_at_period_end"] = cancel_at_period_end
        if current_period_end is not None:
            user["current_period_end"] = current_period_end
        self._save_users()
        auth_db_sync.upsert_user(user)
        return True

    def set_github_installation(self, user_id: str, installation_id: str) -> bool:
        """Store the GitHub App installation ID for a user.

        Auto-creates the user record if it doesn't exist, so GitHub App
        callbacks from Clerk-authenticated users always succeed.
        """
        if user_id not in self._users:
            # Try to hydrate from DB before auto-provisioning.
            db_user = auth_db_sync.get_user(user_id)
            if db_user:
                self._users[user_id] = db_user
            else:
                # Auto-provision user from GitHub callback context
                now = datetime.now(timezone.utc).isoformat()
                self._users[user_id] = {
                    "id": user_id,
                    "email": "",
                    "name": "",
                    "provider": "clerk",
                    "tier": Tier.FREE.value,
                    "created_at": now,
                    "tenant_id": user_id,
                }
        self._users[user_id]["github_installation_id"] = installation_id
        self._save_users()
        auth_db_sync.set_github_installation(user_id, installation_id)
        return True

    def get_github_installation(self, user_id: str) -> str | None:
        """Return the GitHub App installation ID for a user, or None."""
        db_id = auth_db_sync.get_github_installation(user_id)
        if db_id:
            return db_id
        u = self._users.get(user_id)
        if not u:
            return None
        return u.get("github_installation_id")

    # ── JWT Tokens ─────────────────────────────────────────────
    def create_token(self, user_id: str) -> str:
        now = int(time.time())
        payload = {
            "sub": user_id,
            "iat": now,
            "exp": now + self._token_expire,
        }
        return jwt.encode(payload, self._jwt_secret, algorithm=DEFAULT_JWT_ALGORITHM)

    def verify_token(self, token: str) -> str | None:
        """Return user_id if token is valid, else None."""
        try:
            payload = jwt.decode(token, self._jwt_secret, algorithms=[DEFAULT_JWT_ALGORITHM])
            return payload.get("sub")
        except JWTError:
            return None

    def verify_clerk_token(self, token: str) -> dict[str, Any] | None:
        """Verify a Clerk session JWT using their JWKS endpoint.

        Returns the decoded claims dict (with 'sub' = Clerk user ID)
        or None if verification fails or Clerk is not configured.
        """
        issuer = os.environ.get("CLERK_ISSUER")
        if not issuer:
            return None
        try:
            jwks = _get_clerk_jwks(issuer)
            # Match the key ID from the token header
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            key = None
            for k in jwks.get("keys", []):
                if k.get("kid") == kid:
                    key = k
                    break
            if not key:
                logger.debug("Clerk JWKS kid %s not found", kid)
                return None
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                issuer=issuer,
                audience=os.environ.get("CLERK_AUDIENCE", "crp-comply"),
                # Small clock-skew tolerance: Clerk session tokens are
                # short-lived (~60s) and a request that queues for even a
                # few seconds under load (e.g. behind a slow upstream call)
                # would otherwise fail verification on an otherwise-valid
                # token the instant it crosses `exp`. Does not extend the
                # token's real validity window meaningfully.
                # NOTE: python-jose (not PyJWT) takes leeway inside `options`,
                # not as a top-level decode() kwarg.
                options={"verify_aud": True, "leeway": 10},
            )
            return claims
        except JWTError as exc:
            # Surface auth failures at warning level in production so
            # Clerk audience/issuer mismatches are diagnosable from logs.
            logger.warning("Clerk token verification failed: %s", exc)
            return None
        except httpx.HTTPError as exc:
            logger.warning("Failed to fetch Clerk JWKS: %s", exc)
            return None

    # ── API Keys ───────────────────────────────────────────────
    @staticmethod
    def _hash_key(key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()

    def create_api_key(
        self,
        user_id: str,
        name: str,
        tier: Tier | None = None,
        expires_in_days: int | None = None,
    ) -> APIKeyCreated:
        """Generate a new API key for a user.

        ``expires_in_days`` defaults to ``API_KEY_DEFAULT_EXPIRY_DAYS``.
        Pass ``0`` or ``None`` to create a non-expiring key.
        """
        raw_key = API_KEY_PREFIX + secrets.token_urlsafe(API_KEY_LENGTH)
        key_hash = self._hash_key(raw_key)
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()

        resolved_days = (
            expires_in_days if expires_in_days is not None else API_KEY_DEFAULT_EXPIRY_DAYS
        )
        expires_at = (
            (
                now_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
                + timedelta(days=resolved_days)
            ).isoformat()
            if resolved_days
            else None
        )

        user = self.get_user(user_id)
        key_tier = tier or (user.tier if user else Tier.FREE)

        entry: dict[str, Any] = {
            "id": key_hash[:12],
            "name": name,
            "user_id": user_id,
            "key_prefix": raw_key[:12],
            "tier": key_tier.value,
            "created_at": now,
            "revoked": False,
            "expires_at": expires_at,
            "key_hash": key_hash,
        }
        self._api_keys[key_hash] = entry
        self._save_keys()
        auth_db_sync.create_api_key(entry)

        return APIKeyCreated(
            id=key_hash[:12],
            name=name,
            key_prefix=raw_key[:12],
            key=raw_key,
            created_at=now,
            tier=key_tier,
            expires_at=expires_at,
        )

    def verify_api_key(self, key: str) -> tuple[str, Tier] | None:
        """Verify an API key. Returns (user_id, tier) or None.

        Tier is resolved from the user's current record (not the key's
        stored tier) so that billing upgrades take effect immediately.
        """
        if not (key.startswith(API_KEY_PREFIX) or key.startswith(API_KEY_LEGACY_PREFIX)):
            return None
        key_hash = self._hash_key(key)

        # Prefer live DB record when available (supports cross-instance
        # revocation / expiry without needing to restart/reload).
        entry = auth_db_sync.get_api_key(key_hash) or self._api_keys.get(key_hash)
        if not entry:
            return None

        # Expiry check (DB already filters, but enforce in memory too).
        if entry.get("expires_at"):
            try:
                if datetime.fromisoformat(entry["expires_at"]) < datetime.now(timezone.utc):
                    return None
            except ValueError:
                return None
        if entry.get("revoked"):
            return None

        user_id = entry["user_id"]
        # Resolve current tier from user record (GAP-006 fix)
        user_dict = auth_db_sync.get_user(user_id) or self._users.get(user_id)
        if user_dict and user_dict.get("disabled"):
            return None
        tier = Tier(user_dict["tier"]) if user_dict else Tier(entry["tier"])
        return user_id, tier

    def list_api_keys(self, user_id: str) -> list[APIKeyResponse]:
        """List all API keys for a user (without the actual key)."""
        db_keys = auth_db_sync.list_api_keys(user_id)
        merged = {entry["key_hash"]: entry for entry in db_keys}
        for key_hash, entry in self._api_keys.items():
            if entry["user_id"] == user_id and key_hash not in merged:
                merged[key_hash] = entry

        result: list[APIKeyResponse] = []
        for entry in merged.values():
            if entry.get("revoked"):
                continue
            if entry.get("expires_at"):
                try:
                    if datetime.fromisoformat(entry["expires_at"]) < datetime.now(timezone.utc):
                        continue
                except ValueError:
                    continue
            result.append(
                APIKeyResponse(
                    id=entry["id"],
                    name=entry["name"],
                    key_prefix=entry["key_prefix"],
                    created_at=entry["created_at"],
                    tier=Tier(entry["tier"]),
                    expires_at=entry.get("expires_at"),
                )
            )
        return result

    def revoke_api_key(self, user_id: str, key_id: str) -> bool:
        """Revoke an API key by its ID."""
        to_remove = None
        for key_hash, entry in self._api_keys.items():
            if entry["id"] == key_id and entry["user_id"] == user_id:
                to_remove = key_hash
                break
        if to_remove:
            self._api_keys[to_remove]["revoked"] = True
            self._save_keys()

        db_ok = auth_db_sync.revoke_api_key(user_id, key_id)
        return to_remove is not None or db_ok


# ── License Key Validation ─────────────────────────────────────
TIER_FEATURES: dict[Tier, list[str]] = {
    Tier.FREE: [
        "risk_assessment",
        "basic_compliance_report",
    ],
    Tier.STARTER: [
        # Entry paid tier — single-user, capped quota.
        "risk_assessment",
        "compliance_report",
        "dpia",
        "transparency_declaration",
        "session_audit",
        "evidence_pack",
        "pdf_export",
        "managed_backups",
    ],
    Tier.PRO: [
        "risk_assessment",
        "compliance_report",
        "dpia",
        "transparency_declaration",
        "technical_documentation",
        "session_audit",
        "evidence_pack",
        "pdf_export",
        "agent_intelligence",
        "managed_backups",
    ],
    Tier.SCALE: [
        # SPEC-047 aligned successor to PRO — same capability surface.
        "risk_assessment",
        "compliance_report",
        "dpia",
        "transparency_declaration",
        "technical_documentation",
        "session_audit",
        "evidence_pack",
        "pdf_export",
        "agent_intelligence",
        "managed_backups",
    ],
    Tier.ENTERPRISE: [
        "risk_assessment",
        "compliance_report",
        "dpia",
        "transparency_declaration",
        "technical_documentation",
        "session_audit",
        "evidence_pack",
        "pdf_export",
        "multi_user",
        "custom_frameworks",
        "agent_intelligence",
        "managed_backups",
    ],
    Tier.CLOUD: [
        # Everything in ENTERPRISE
        "risk_assessment",
        "compliance_report",
        "dpia",
        "transparency_declaration",
        "technical_documentation",
        "session_audit",
        "evidence_pack",
        "pdf_export",
        "multi_user",
        "custom_frameworks",
        "agent_intelligence",
        # Cloud-exclusive
        "signed_certificates",
        "priority_support",
        "managed_backups",
    ],
}


def check_feature_access(tier: Tier, feature: str) -> bool:
    """Check if a tier has access to a specific feature."""
    return feature in TIER_FEATURES.get(tier, [])


def get_tier_features(tier: Tier) -> list[str]:
    """Get all features available for a tier."""
    return TIER_FEATURES.get(tier, [])
