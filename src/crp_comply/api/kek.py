# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Rotating key-encryption-key (KEK) envelope for BYOK secrets —
addresses PRODUCT_SECURITY.md §4 gap #7 (KDF rotation).

BYOK LLM keys and webhook secrets are stored encrypted at rest. This
module wraps them with a *versioned* KEK, so operators can rotate the
master key without losing access to historic ciphertexts.

Envelope layout (base64-URL on the wire)::

    v{kek_version}.{nonce_b64}.{ciphertext_b64}

Decryption walks the KEK history until one succeeds, then (if a
newer KEK is now the active one) re-encrypts and the caller rewrites
the storage. That keeps silent rotation cheap.

Backends:

* libsodium SecretBox if ``pynacl`` is installed (preferred).
* cryptography AESGCM as fallback.

The master KEK chain is read from ``CRP_COMPLY_KEK_CHAIN`` — a
colon-separated list of ``v{n}={b64_32_bytes}`` entries, highest version
is the active one. If not set, a single KEK is derived from
``CRP_COMPLY_JWT_SECRET`` via HKDF-SHA256 (fallback, not recommended for
production).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("crp_comply.api.kek")


# ── Optional crypto backends ──────────────────────────────────
try:
    from nacl.secret import SecretBox  # type: ignore[import-not-found]
    from nacl.utils import random as nacl_random  # type: ignore[import-not-found]

    _NACL_OK = True
except Exception:  # pragma: no cover
    _NACL_OK = False

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    _CRYPTO_OK = True
except Exception:  # pragma: no cover
    _CRYPTO_OK = False


@dataclass
class Kek:
    version: int
    key: bytes  # 32 bytes


def _hkdf_sha256(ikm: bytes, salt: bytes, info: bytes, length: int = 32) -> bytes:
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    t = b""
    okm = b""
    i = 1
    while len(okm) < length:
        t = hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        okm += t
        i += 1
    return okm[:length]


def _load_chain() -> list[Kek]:
    raw = os.getenv("CRP_COMPLY_KEK_CHAIN", "").strip()
    if raw:
        chain: list[Kek] = []
        for entry in raw.split(":"):
            entry = entry.strip()
            if not entry:
                continue
            try:
                v, b64 = entry.split("=", 1)
                if not (v.startswith("v")):
                    raise ValueError("KEK version tag must start with 'v'")
                version = int(v[1:])
                key = base64.b64decode(b64)
                if len(key) != 32:
                    raise ValueError("KEK must be 32 bytes")
                chain.append(Kek(version=version, key=key))
            except Exception as exc:
                log.error("ignoring bad KEK chain entry %r: %s", entry, exc)
        if chain:
            chain.sort(key=lambda k: k.version, reverse=True)
            return chain

    # Fallback: derive a single KEK from JWT secret. Loud warn.
    secret = os.getenv("CRP_COMPLY_JWT_SECRET", "")
    if not secret:
        log.warning(
            "no CRP_COMPLY_KEK_CHAIN and no JWT secret; using ephemeral KEK "
            "(persistence lost on restart — DO NOT use in production)"
        )
        return [Kek(version=0, key=secrets.token_bytes(32))]
    derived = _hkdf_sha256(
        secret.encode("utf-8"),
        salt=b"crp-comply-kek",
        info=b"byok-envelope",
    )
    return [Kek(version=1, key=derived)]


_CHAIN: list[Kek] = _load_chain()


def active_kek() -> Kek:
    return _CHAIN[0]


def _kek_by_version(v: int) -> Kek | None:
    for k in _CHAIN:
        if k.version == v:
            return k
    return None


# ── Envelope ──────────────────────────────────────────────────


def _box_encrypt(key: bytes, plaintext: bytes) -> tuple[bytes, bytes]:
    if _NACL_OK:
        nonce = nacl_random(SecretBox.NONCE_SIZE)
        ct = SecretBox(key).encrypt(plaintext, nonce).ciphertext
        return nonce, ct
    if _CRYPTO_OK:
        nonce = secrets.token_bytes(12)
        ct = AESGCM(key).encrypt(nonce, plaintext, None)
        return nonce, ct
    raise RuntimeError("no encryption backend: install pynacl or cryptography")


def _box_decrypt(key: bytes, nonce: bytes, ciphertext: bytes) -> bytes:
    if _NACL_OK:
        return SecretBox(key).decrypt(ciphertext, nonce)
    if _CRYPTO_OK:
        return AESGCM(key).decrypt(nonce, ciphertext, None)
    raise RuntimeError("no decryption backend")


def seal(plaintext: str | bytes) -> str:
    """Encrypt with the active KEK; return the on-the-wire envelope."""
    if isinstance(plaintext, str):
        plaintext = plaintext.encode("utf-8")
    kek = active_kek()
    nonce, ct = _box_encrypt(kek.key, plaintext)
    return (
        f"v{kek.version}."
        f"{base64.urlsafe_b64encode(nonce).decode('ascii').rstrip('=')}."
        f"{base64.urlsafe_b64encode(ct).decode('ascii').rstrip('=')}"
    )


def _b64url_pad(s: str) -> bytes:
    pad = (-len(s)) % 4
    return base64.urlsafe_b64decode(s + ("=" * pad))


def open_envelope(envelope: str) -> tuple[bytes, int]:
    """Decrypt and return ``(plaintext, kek_version_used)``.

    Caller can compare ``kek_version_used`` with :func:`active_kek().version`
    and silently re-seal + persist the newer envelope when they differ.
    """
    try:
        v_tag, nonce_s, ct_s = envelope.split(".", 2)
        if not (v_tag.startswith("v")):
            raise ValueError("envelope version tag must start with 'v'")
        version = int(v_tag[1:])
    except Exception as exc:
        raise ValueError(f"malformed envelope: {exc}") from exc
    kek = _kek_by_version(version)
    if kek is None:
        raise ValueError(f"unknown KEK version v{version}; rotate in lockstep")
    plaintext = _box_decrypt(kek.key, _b64url_pad(nonce_s), _b64url_pad(ct_s))
    return plaintext, version


def needs_rewrap(envelope: str) -> bool:
    try:
        v_tag = envelope.split(".", 1)[0]
        version = int(v_tag[1:])
    except Exception:
        return False
    return version != active_kek().version


def rewrap(envelope: str) -> str:
    plaintext, _ = open_envelope(envelope)
    return seal(plaintext)


def chain_summary() -> dict[str, Any]:
    """Return a non-sensitive view of the KEK chain for ops dashboards."""
    return {
        "active_version": _CHAIN[0].version,
        "versions": [k.version for k in _CHAIN],
        "backend": "pynacl" if _NACL_OK else ("cryptography" if _CRYPTO_OK else "none"),
    }


def _reset_for_tests() -> None:
    """Reload the KEK chain from the current environment. Tests only."""
    global _CHAIN
    _CHAIN = _load_chain()
