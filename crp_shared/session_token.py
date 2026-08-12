"""
CRP Session Token (CRP-SPEC-007).

Issues and verifies compact, URL-safe session tokens that carry enough state to
allow Gateway consumers to resume or route a session without re-running the full
context pipeline on every request.

The token is NOT a JWT in the JWS sense; it is a HMAC-SHA256 signed compact
serialization designed to be parseable by lightweight consumers.

Payload fields:
  v    - token format version (currently "4")
  sid  - session id
  win  - current window id
  qh   - quality hash of the active context window
  sb   - soft budget consumed (tokens)
  ct   - continuation count
  cid  - conversation / thread id
  dag  - DAG node id of the active continuation
  str  - current strategy name
  pol  - active policy id
  ckf  - CKF etag / source fingerprint
  scope- capability scope mask
  iat  - issued at (unix seconds)
  exp  - expires at (unix seconds)
  nonce- one-time nonce used during signing
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

CRP_SESSION_TOKEN_VERSION = "4"


class TokenError(Exception):
    pass


@dataclass
class SessionToken:
    v: str = CRP_SESSION_TOKEN_VERSION
    sid: str = ""
    win: str = ""
    qh: str = ""
    sb: int = 0
    ct: int = 0
    cid: str = ""
    dag: str = ""
    str_: str = ""  # strategy
    pol: str = ""
    ckf: str = ""
    scope: int = 0
    iat: int = 0
    exp: int = 0
    nonce: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "v": self.v,
            "sid": self.sid,
            "win": self.win,
            "qh": self.qh,
            "sb": self.sb,
            "ct": self.ct,
            "cid": self.cid,
            "dag": self.dag,
            "str": self.str_,
            "pol": self.pol,
            "ckf": self.ckf,
            "scope": self.scope,
            "iat": self.iat,
            "exp": self.exp,
            "nonce": self.nonce,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionToken:
        token = cls()
        token.v = str(data.get("v", CRP_SESSION_TOKEN_VERSION))
        token.sid = data.get("sid", "")
        token.win = data.get("win", "")
        token.qh = data.get("qh", "")
        token.sb = int(data.get("sb", 0))
        token.ct = int(data.get("ct", 0))
        token.cid = data.get("cid", "")
        token.dag = data.get("dag", "")
        token.str_ = data.get("str", "")
        token.pol = data.get("pol", "")
        token.ckf = data.get("ckf", "")
        token.scope = int(data.get("scope", 0))
        token.iat = int(data.get("iat", 0))
        token.exp = int(data.get("exp", 0))
        token.nonce = data.get("nonce", "")
        return token


class SessionTokenManager:
    def __init__(self, gateway_master_key: bytes, default_ttl_seconds: int = 3600) -> None:
        self.gateway_master_key = gateway_master_key
        self.default_ttl_seconds = default_ttl_seconds

    def derive_key(self, session_id: str) -> bytes:
        return HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=session_id.encode("utf-8"),
            info=b"crp-session-token-v4",
        ).derive(self.gateway_master_key)

    def issue(
        self,
        session_id: str,
        window_id: str = "",
        quality_hash: str = "",
        soft_budget: int = 0,
        continuation_count: int = 0,
        conversation_id: str = "",
        dag_node_id: str = "",
        strategy: str = "",
        policy_id: str = "",
        ckf_etag: str = "",
        scope: int = 0,
        ttl_seconds: int | None = None,
    ) -> str:
        now = int(time.time())
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds
        token = SessionToken(
            sid=session_id,
            win=window_id,
            qh=quality_hash,
            sb=soft_budget,
            ct=continuation_count,
            cid=conversation_id,
            dag=dag_node_id,
            str_=strategy,
            pol=policy_id,
            ckf=ckf_etag,
            scope=scope,
            iat=now,
            exp=now + ttl,
            nonce=secrets.token_urlsafe(12),
        )
        return self._serialize(token)

    def verify(self, serialized: str) -> SessionToken:
        try:
            parts = serialized.split(".")
            if len(parts) != 3:
                raise TokenError("Invalid token format")
            header_b64, payload_b64, signature_b64 = parts

            header = json.loads(self._urlsafe_b64decode(header_b64))
            payload = json.loads(self._urlsafe_b64decode(payload_b64))
            signature = self._urlsafe_b64decode(signature_b64)

            if header.get("alg") != "HS256":
                raise TokenError("Unsupported algorithm")

            token = SessionToken.from_dict(payload)
            if token.v != CRP_SESSION_TOKEN_VERSION:
                raise TokenError("Unsupported token version")

            if int(time.time()) > token.exp:
                raise TokenError("Token expired")

            expected = self._sign(header_b64, payload_b64, token.sid)
            if not hmac.compare_digest(expected, signature):
                raise TokenError("Invalid signature")

            return token
        except TokenError:
            raise
        except Exception as exc:
            raise TokenError(f"Token verification failed: {exc}") from exc

    def _serialize(self, token: SessionToken) -> str:
        header_b64 = self._urlsafe_b64encode(
            json.dumps({"alg": "HS256", "typ": "CRP-SESS-v4"}, separators=(",", ":")).encode()
        )
        payload_b64 = self._urlsafe_b64encode(
            json.dumps(token.to_dict(), separators=(",", ":"), sort_keys=True).encode()
        )
        signature = self._sign(header_b64, payload_b64, token.sid)
        sig_b64 = self._urlsafe_b64encode(signature)
        return f"{header_b64}.{payload_b64}.{sig_b64}"

    def _sign(self, header_b64: str, payload_b64: str, session_id: str) -> bytes:
        signing_key = self.derive_key(session_id)
        material = f"{header_b64}.{payload_b64}".encode()
        return hmac.new(signing_key, material, hashlib.sha256).digest()

    @staticmethod
    def _urlsafe_b64encode(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    @staticmethod
    def _urlsafe_b64decode(data: str) -> bytes:
        padding = 4 - len(data) % 4
        if padding != 4:
            data += "=" * padding
        return base64.urlsafe_b64decode(data)

    @staticmethod
    def hash_context(text: str) -> str:
        """Compute a deterministic quality hash for a context window."""
        return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def encode_scope(*capabilities: str) -> int:
    """Encode capability scope as a 32-bit bitmask from canonical names."""
    canonical = {
        "chat": 1 << 0,
        "completion": 1 << 1,
        "embedding": 1 << 2,
        "image": 1 << 3,
        "audio": 1 << 4,
        "agent": 1 << 5,
        "tool": 1 << 6,
        "comply_stream": 1 << 7,
        "admin": 1 << 8,
    }
    mask = 0
    for cap in capabilities:
        mask |= canonical.get(cap, 0)
    return mask
