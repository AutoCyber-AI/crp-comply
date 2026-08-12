"""
Shared passkey (FIDO2/WebAuthn) MFA engine for CRP Gateway and CRP Comply.

Provides:
- Registration and authentication option generation.
- Credential persistence in PostgreSQL.
- Short-lived MFA session tokens.
- Adaptive risk scoring based on IP, user-agent, time and geolocation.

Both services authenticate identity with Clerk first; passkeys act as the
mandatory second factor and step-up guard for sensitive actions.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any

import asyncpg
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import (
    base64url_to_bytes,
    bytes_to_base64url,
    parse_authentication_credential_json,
    parse_registration_credential_json,
)
from webauthn.helpers.exceptions import InvalidAuthenticationResponse
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AttestationConveyancePreference,
    PublicKeyCredentialDescriptor,
    PublicKeyCredentialType,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

# ---------------------------------------------------------------------------
# Database schema (applied by each service at startup)
# ---------------------------------------------------------------------------

PASSKEY_SCHEMA = """
CREATE TABLE IF NOT EXISTS passkey_credentials (
    credential_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    tenant_id TEXT,
    public_key TEXT NOT NULL,
    sign_count INTEGER NOT NULL DEFAULT 0,
    rp_id TEXT NOT NULL,
    device_name TEXT,
    transports TEXT[] DEFAULT '{}',
    created_at DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM now()),
    last_used_at DOUBLE PRECISION,
    revoked BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_passkey_credentials_user_id
    ON passkey_credentials(user_id);

CREATE TABLE IF NOT EXISTS passkey_challenges (
    challenge_hash TEXT PRIMARY KEY,
    user_id TEXT,
    challenge TEXT NOT NULL,
    purpose TEXT NOT NULL,
    expires_at DOUBLE PRECISION NOT NULL,
    created_at DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM now())
);

CREATE INDEX IF NOT EXISTS idx_passkey_challenges_expires
    ON passkey_challenges(expires_at);

CREATE TABLE IF NOT EXISTS passkey_login_events (
    event_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    tenant_id TEXT,
    credential_id TEXT,
    ip_hash TEXT NOT NULL,
    ua_hash TEXT NOT NULL,
    geo_hash TEXT,
    success BOOLEAN NOT NULL,
    risk_score REAL NOT NULL DEFAULT 0,
    risk_factors TEXT[] DEFAULT '{}',
    created_at DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM now())
);

CREATE INDEX IF NOT EXISTS idx_passkey_events_user
    ON passkey_login_events(user_id, created_at);

CREATE TABLE IF NOT EXISTS passkey_mfa_sessions (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    credential_id TEXT,
    ip_hash TEXT NOT NULL,
    ua_hash TEXT NOT NULL,
    risk_score REAL NOT NULL DEFAULT 0,
    created_at DOUBLE PRECISION NOT NULL DEFAULT EXTRACT(EPOCH FROM now()),
    expires_at DOUBLE PRECISION NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_passkey_mfa_sessions_user
    ON passkey_mfa_sessions(user_id);
"""


# ---------------------------------------------------------------------------
# Context and risk model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuthContext:
    """Privacy-preserving login context used for adaptive risk scoring."""

    ip_address: str | None
    user_agent: str | None
    geo_hint: str | None = None  # e.g. "AU-Sydney" or timezone

    def ip_hash(self) -> str:
        return _hash(self.ip_address or "unknown")

    def ua_hash(self) -> str:
        return _hash(self.user_agent or "unknown")

    def geo_hash(self) -> str:
        return _hash(self.geo_hint or "unknown")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class RiskAssessment:
    score: float
    factors: list[str]
    decision: str  # "allow", "challenge", "block"


# ---------------------------------------------------------------------------
# Passkey manager
# ---------------------------------------------------------------------------


class PasskeyManager:
    """Manages WebAuthn credentials, challenges and adaptive MFA sessions."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        rp_id: str,
        rp_name: str,
        origin: str,
        session_ttl_seconds: int = 3600,
        challenge_ttl_seconds: int = 120,
    ) -> None:
        self.pool = pool
        self.rp_id = rp_id
        self.rp_name = rp_name
        self.origin = origin
        self.session_ttl_seconds = session_ttl_seconds
        self.challenge_ttl_seconds = challenge_ttl_seconds

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    async def registration_options(
        self,
        user_id: str,
        user_name: str,
        user_display_name: str,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """Return WebAuthn registration options and store the challenge."""
        challenge_bytes = secrets.token_bytes(32)
        challenge_b64 = bytes_to_base64url(challenge_bytes)

        opts = generate_registration_options(
            rp_id=self.rp_id,
            rp_name=self.rp_name,
            user_id=user_id.encode("utf-8"),
            user_name=user_name,
            user_display_name=user_display_name,
            challenge=challenge_bytes,
            timeout=120000,
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.DISCOURAGED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
            attestation=AttestationConveyancePreference.NONE,
        )

        # Exclude credentials already registered for this user.
        existing = await self.list_credentials(user_id)
        if existing:
            opts.exclude_credentials = [
                PublicKeyCredentialDescriptor(
                    type=PublicKeyCredentialType.PUBLIC_KEY,
                    id=base64url_to_bytes(row["credential_id"]),
                )
                for row in existing
            ]

        await self._store_challenge(user_id, challenge_b64, "register")
        return json.loads(options_to_json(opts))

    async def verify_registration(
        self,
        user_id: str,
        credential_dict: dict[str, Any],
        tenant_id: str | None = None,
        device_name: str | None = None,
        context: AuthContext | None = None,
    ) -> dict[str, Any]:
        """Verify a WebAuthn registration response and persist the credential."""
        # Parse the client response and recover the challenge the browser signed.
        try:
            parsed_cred = parse_registration_credential_json(credential_dict)
        except Exception as exc:
            raise ValueError("Invalid registration credential format") from exc

        try:
            client_data = json.loads(parsed_cred.response.client_data_json.decode("utf-8"))
            challenge_b64 = client_data["challenge"]
        except Exception as exc:
            raise ValueError("Could not extract challenge from registration response") from exc
        expected_challenge = await self._consume_challenge(user_id, challenge_b64, "register")
        if expected_challenge is None:
            raise ValueError("Invalid or expired registration challenge")

        verified = verify_registration_response(
            credential=parsed_cred,
            expected_challenge=base64url_to_bytes(expected_challenge),
            expected_rp_id=self.rp_id,
            expected_origin=self.origin,
            require_user_verification=True,
        )

        credential_id = bytes_to_base64url(verified.credential_id)
        public_key = bytes_to_base64url(verified.credential_public_key)
        sign_count = verified.sign_count

        transports = credential_dict.get("response", {}).get("transports", [])
        if isinstance(transports, str):
            transports = [transports]

        await self.pool.execute(
            """
            INSERT INTO passkey_credentials
                (credential_id, user_id, tenant_id, public_key, sign_count, rp_id, device_name, transports)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (credential_id) DO UPDATE SET
                public_key = EXCLUDED.public_key,
                sign_count = EXCLUDED.sign_count,
                revoked = FALSE,
                last_used_at = EXTRACT(EPOCH FROM now())
            """,
            credential_id,
            user_id,
            tenant_id,
            public_key,
            sign_count,
            self.rp_id,
            device_name or "Passkey",
            transports,
        )

        await self._record_event(
            user_id=user_id,
            tenant_id=tenant_id,
            credential_id=credential_id,
            context=context or AuthContext(ip_address=None, user_agent=None),
            success=True,
            risk_score=0,
            risk_factors=["registration"],
        )

        return {
            "credential_id": credential_id,
            "sign_count": sign_count,
            "device_name": device_name or "Passkey",
        }

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    async def authentication_options(
        self,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Return WebAuthn authentication options and store the challenge."""
        challenge_bytes = secrets.token_bytes(32)
        challenge_b64 = bytes_to_base64url(challenge_bytes)

        allow_credentials = None
        if user_id:
            rows = await self.list_credentials(user_id)
            allow_credentials = [
                PublicKeyCredentialDescriptor(
                    type=PublicKeyCredentialType.PUBLIC_KEY,
                    id=base64url_to_bytes(row["credential_id"]),
                )
                for row in rows
                if not row["revoked"]
            ]

        opts = generate_authentication_options(
            rp_id=self.rp_id,
            challenge=challenge_bytes,
            timeout=120000,
            allow_credentials=allow_credentials,
            user_verification=UserVerificationRequirement.REQUIRED,
        )

        await self._store_challenge(user_id, challenge_b64, "authenticate")
        return json.loads(options_to_json(opts))

    async def verify_authentication(
        self,
        credential_dict: dict[str, Any],
        context: AuthContext,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """Verify a WebAuthn assertion, update sign count and return risk info."""
        try:
            parsed_cred = parse_authentication_credential_json(credential_dict)
        except Exception as exc:
            raise ValueError("Invalid authentication credential format") from exc

        try:
            client_data = json.loads(parsed_cred.response.client_data_json.decode("utf-8"))
            challenge_b64 = client_data["challenge"]
        except Exception as exc:
            raise ValueError("Could not extract challenge from authentication response") from exc
        credential_id_b64 = parsed_cred.id

        row = await self.pool.fetchrow(
            "SELECT * FROM passkey_credentials WHERE credential_id = $1 AND revoked = FALSE",
            credential_id_b64,
        )
        if not row:
            raise ValueError("Credential not found or revoked")

        user_id = row["user_id"]
        expected_challenge = await self._consume_challenge(user_id, challenge_b64, "authenticate")
        if expected_challenge is None:
            raise ValueError("Invalid or expired authentication challenge")

        try:
            verified = verify_authentication_response(
                credential=parsed_cred,
                expected_challenge=base64url_to_bytes(expected_challenge),
                expected_rp_id=self.rp_id,
                expected_origin=self.origin,
                credential_public_key=base64url_to_bytes(row["public_key"]),
                credential_current_sign_count=row["sign_count"],
                require_user_verification=True,
            )
        except InvalidAuthenticationResponse as exc:
            risk = await self.assess_risk(user_id, context)
            await self._record_event(
                user_id=user_id,
                tenant_id=tenant_id or row.get("tenant_id"),
                credential_id=credential_id_b64,
                context=context,
                success=False,
                risk_score=risk.score,
                risk_factors=risk.factors,
            )
            raise exc

        await self.pool.execute(
            "UPDATE passkey_credentials SET sign_count = $1, last_used_at = EXTRACT(EPOCH FROM now()) WHERE credential_id = $2",
            verified.new_sign_count,
            credential_id_b64,
        )

        risk = await self.assess_risk(user_id, context, credential_id=credential_id_b64)
        await self._record_event(
            user_id=user_id,
            tenant_id=tenant_id or row.get("tenant_id"),
            credential_id=credential_id_b64,
            context=context,
            success=True,
            risk_score=risk.score,
            risk_factors=risk.factors,
        )

        return {
            "user_id": user_id,
            "credential_id": credential_id_b64,
            "risk_score": risk.score,
            "risk_factors": risk.factors,
            "decision": risk.decision,
        }

    # ------------------------------------------------------------------
    # Credentials
    # ------------------------------------------------------------------

    async def list_credentials(self, user_id: str) -> list[asyncpg.Record]:
        return await self.pool.fetch(
            "SELECT * FROM passkey_credentials WHERE user_id = $1 AND revoked = FALSE ORDER BY created_at DESC",
            user_id,
        )

    async def delete_credential(self, user_id: str, credential_id: str) -> bool:
        result = await self.pool.execute(
            "UPDATE passkey_credentials SET revoked = TRUE WHERE credential_id = $1 AND user_id = $2",
            credential_id,
            user_id,
        )
        return "UPDATE 1" in result

    async def has_credentials(self, user_id: str) -> bool:
        row = await self.pool.fetchrow(
            "SELECT 1 FROM passkey_credentials WHERE user_id = $1 AND revoked = FALSE LIMIT 1",
            user_id,
        )
        return row is not None

    # ------------------------------------------------------------------
    # MFA sessions
    # ------------------------------------------------------------------

    async def create_mfa_session(
        self,
        user_id: str,
        credential_id: str,
        context: AuthContext,
        risk_score: float,
    ) -> str:
        """Create a short-lived MFA session token and return the raw token."""
        token = bytes_to_base64url(secrets.token_bytes(32))
        token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        now = time.time()
        expires = now + self.session_ttl_seconds

        await self.pool.execute(
            """
            INSERT INTO passkey_mfa_sessions
                (token_hash, user_id, credential_id, ip_hash, ua_hash, risk_score, created_at, expires_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (token_hash) DO NOTHING
            """,
            token_hash,
            user_id,
            credential_id,
            context.ip_hash(),
            context.ua_hash(),
            risk_score,
            now,
            expires,
        )
        return token

    async def verify_mfa_session(
        self,
        token: str | None,
        user_id: str,
        context: AuthContext,
    ) -> RiskAssessment | None:
        """Return risk assessment if token is valid, else None."""
        if not token:
            return None

        token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        now = time.time()

        row = await self.pool.fetchrow(
            "SELECT * FROM passkey_mfa_sessions WHERE token_hash = $1 AND user_id = $2",
            token_hash,
            user_id,
        )
        if not row:
            return None

        if row["expires_at"] < now:
            await self.pool.execute(
                "DELETE FROM passkey_mfa_sessions WHERE token_hash = $1", token_hash
            )
            return None

        # Context drift: record IP/UA changes for observability but do not
        # force a fresh passkey on every network hop. Per-token expiry and
        # explicit revocation remain the hard guards.
        factors = []
        if row["ip_hash"] != context.ip_hash():
            factors.append("ip_changed")
        if row["ua_hash"] != context.ua_hash():
            factors.append("device_changed")

        return RiskAssessment(
            score=row["risk_score"],
            factors=factors,
            decision="allow",
        )

    async def revoke_mfa_session(self, token: str) -> None:
        token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        await self.pool.execute(
            "DELETE FROM passkey_mfa_sessions WHERE token_hash = $1", token_hash
        )

    # ------------------------------------------------------------------
    # Adaptive risk engine
    # ------------------------------------------------------------------

    async def assess_risk(
        self,
        user_id: str,
        context: AuthContext,
        credential_id: str | None = None,
    ) -> RiskAssessment:
        """Compute a privacy-preserving risk score for the current login context."""
        score = 0.0
        factors: list[str] = []
        now = time.time()

        # New device fingerprint
        recent_events = await self.pool.fetch(
            """
            SELECT ip_hash, ua_hash, geo_hash, success, created_at, risk_factors
            FROM passkey_login_events
            WHERE user_id = $1 AND created_at > $2
            ORDER BY created_at DESC
            LIMIT 10
            """,
            user_id,
            now - 90 * 24 * 3600,
        )

        known_ips = {row["ip_hash"] for row in recent_events if row["success"]}
        known_uas = {row["ua_hash"] for row in recent_events if row["success"]}
        known_geos = {
            row["geo_hash"] for row in recent_events if row["success"] and row["geo_hash"]
        }

        if recent_events:
            # Only flag unknown context when we have prior successful context to
            # compare against. Without history every new login looks suspicious.
            if known_ips and context.ip_hash() not in known_ips:
                score += 40.0
                factors.append("unknown_ip")
            if known_uas and context.ua_hash() not in known_uas:
                score += 30.0
                factors.append("unknown_device")
            if known_geos and context.geo_hash() and context.geo_hash() not in known_geos:
                score += 25.0
                factors.append("unknown_location")
        else:
            # First ever passkey use - slightly elevate risk but never block.
            score += 20.0
            factors.append("first_passkey_use")

        # Unusual hour (00:00-05:00 local time if geo_hint contains timezone offset)
        hour = time.localtime().tm_hour
        if 0 <= hour < 5:
            score += 15.0
            factors.append("unusual_hour")

        # Recent failures
        failures_24h = sum(
            1 for row in recent_events if not row["success"] and row["created_at"] > now - 24 * 3600
        )
        if failures_24h:
            score += min(30.0, failures_24h * 10.0)
            factors.append(f"recent_failures:{failures_24h}")

        # Stale account (no successful login in 30 days)
        last_success = next((row["created_at"] for row in recent_events if row["success"]), None)
        if last_success is not None and last_success < now - 30 * 24 * 3600:
            score += 20.0
            factors.append("stale_session")

        # Clamp and decide
        score = min(100.0, max(0.0, score))

        # Bootstrap window: the first successful verification after registration, and
        # any verification within minutes of creating a new credential, must not be
        # blocked so users can complete enrollment on a new device.
        successful_auths = [
            row
            for row in recent_events
            if row["success"] and "registration" not in (row.get("risk_factors") or [])
        ]
        is_first_success = not successful_auths

        is_new_credential = False
        if credential_id:
            cred_row = await self.pool.fetchrow(
                "SELECT created_at FROM passkey_credentials WHERE credential_id = $1 AND user_id = $2 AND revoked = FALSE",
                credential_id,
                user_id,
            )
            if cred_row is not None and now - cred_row["created_at"] < 600:
                is_new_credential = True

        if is_first_success or is_new_credential:
            score = min(score, 35.0)
            factors.append("first_verification_bootstrap")
            decision = "allow"
        elif score >= 80:
            decision = "block"
        elif score >= 40:
            decision = "challenge"
        else:
            decision = "allow"

        return RiskAssessment(score=score, factors=factors, decision=decision)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _store_challenge(
        self,
        user_id: str | None,
        challenge_b64: str,
        purpose: str,
    ) -> None:
        challenge_hash = hashlib.sha256(challenge_b64.encode("ascii")).hexdigest()
        expires = time.time() + self.challenge_ttl_seconds
        await self.pool.execute(
            """
            INSERT INTO passkey_challenges (challenge_hash, user_id, challenge, purpose, expires_at)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (challenge_hash) DO NOTHING
            """,
            challenge_hash,
            user_id,
            challenge_b64,
            purpose,
            expires,
        )

    async def _consume_challenge(
        self,
        user_id: str | None,
        challenge_b64: str,
        purpose: str,
    ) -> str | None:
        challenge_hash = hashlib.sha256(challenge_b64.encode("ascii")).hexdigest()
        now = time.time()

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT * FROM passkey_challenges WHERE challenge_hash = $1 AND purpose = $2",
                    challenge_hash,
                    purpose,
                )
                if not row:
                    return None
                if row["expires_at"] < now:
                    await conn.execute(
                        "DELETE FROM passkey_challenges WHERE challenge_hash = $1", challenge_hash
                    )
                    return None
                if user_id is not None and row["user_id"] not in (user_id, None):
                    return None
                await conn.execute(
                    "DELETE FROM passkey_challenges WHERE challenge_hash = $1", challenge_hash
                )
                return row["challenge"]

    async def _record_event(
        self,
        user_id: str,
        tenant_id: str | None,
        credential_id: str | None,
        context: AuthContext,
        success: bool,
        risk_score: float,
        risk_factors: list[str],
    ) -> None:
        event_id = secrets.token_urlsafe(16)
        await self.pool.execute(
            """
            INSERT INTO passkey_login_events
                (event_id, user_id, tenant_id, credential_id, ip_hash, ua_hash, geo_hash, success, risk_score, risk_factors)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            """,
            event_id,
            user_id,
            tenant_id,
            credential_id,
            context.ip_hash(),
            context.ua_hash(),
            context.geo_hash(),
            success,
            risk_score,
            risk_factors,
        )

    async def cleanup_expired(self) -> None:
        """Remove expired challenges and MFA sessions."""
        now = time.time()
        await self.pool.execute("DELETE FROM passkey_challenges WHERE expires_at < $1", now)
        await self.pool.execute("DELETE FROM passkey_mfa_sessions WHERE expires_at < $1", now)
