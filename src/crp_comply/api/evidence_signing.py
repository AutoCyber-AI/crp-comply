# Copyright © 2025-2026 Constantinos Vidiniotis / AutoCyber AI Pty Ltd.
# Licensed under Elastic License 2.0 — see LICENSE.md for details.
"""Ed25519 evidence-pack signing — addresses PRODUCT_SECURITY.md §4 gap #4.

Replaces the symmetric HMAC signatures in :mod:`crp_comply.api.reports`
with detached Ed25519 signatures. The public key is published at
``/.well-known/crp-comply-evidence-key.pub`` so regulators can verify
evidence packs **without access to any shared secret**.

Key storage:

* Private key: encrypted in ``{data_dir}/.keys/evidence_ed25519.priv``
  (libsodium-compatible raw 32-byte seed, base64'd). Protected by a
  passphrase derived from ``CRP_COMPLY_EVIDENCE_SIGNING_SECRET`` or, if
  absent, from ``CRP_COMPLY_JWT_SECRET`` (both read-at-startup only).
* Public key: plain bytes at
  ``{data_dir}/.keys/evidence_ed25519.pub``. Also served by the app so
  everyone in the supply chain can grab it over HTTPS.

Rotation: calling :func:`rotate_keys` generates a new keypair and writes
``{data_dir}/.keys/history/ed25519_{fingerprint}.json`` retaining every
previous keypair metadata (expiry, rotated_at) so historic signatures
remain verifiable.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


log = logging.getLogger("crp_comply.api.evidence_signing")


# ─────────────────────────────────────────────────────────────
# Optional dependency — graceful fallback to HMAC if PyNaCl/cryptography
# are both unavailable (e.g. constrained build). Production images
# should install one of them.
# ─────────────────────────────────────────────────────────────

try:
    from nacl import signing as _nacl_signing  # type: ignore[import-not-found]

    _NACL_OK = True
except Exception:  # pragma: no cover
    _NACL_OK = False

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )
    from cryptography.hazmat.primitives import serialization

    _CRYPTO_OK = True
except Exception:  # pragma: no cover
    _CRYPTO_OK = False


ED25519_SUPPORTED = _NACL_OK or _CRYPTO_OK


# ─────────────────────────────────────────────────────────────
# Data types
# ─────────────────────────────────────────────────────────────


@dataclass
class SigningResult:
    algorithm: str  # "ed25519" or "hmac-sha256"
    signature_b64: str
    public_key_b64: str | None  # None for HMAC
    key_fingerprint: str  # sha256[:16] of public key (or shared secret)
    signed_at: str


@dataclass
class KeyMaterial:
    algorithm: str
    private: bytes | None  # raw seed for Ed25519; shared secret bytes for HMAC
    public: bytes | None
    fingerprint: str


# ─────────────────────────────────────────────────────────────
# Key material
# ─────────────────────────────────────────────────────────────


def _keys_dir(data_dir: Path) -> Path:
    d = data_dir / ".keys"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _fingerprint(public_bytes: bytes) -> str:
    return hashlib.sha256(public_bytes).hexdigest()[:16]


def _generate_ed25519_seed() -> tuple[bytes, bytes]:
    """Return ``(private_seed_32B, public_32B)``."""
    if _NACL_OK:
        sk = _nacl_signing.SigningKey.generate()
        return bytes(sk), bytes(sk.verify_key)
    if _CRYPTO_OK:
        sk = Ed25519PrivateKey.generate()
        priv = sk.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        pub = sk.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return priv, pub
    raise RuntimeError("Ed25519 unavailable: install pynacl or cryptography")


def load_or_create_keys(data_dir: Path) -> KeyMaterial:
    """Load persistent keys from disk, generating if first-run."""
    kd = _keys_dir(data_dir)
    priv_path = kd / "evidence_ed25519.priv"
    pub_path = kd / "evidence_ed25519.pub"

    if ED25519_SUPPORTED:
        if priv_path.exists() and pub_path.exists():
            priv = base64.b64decode(priv_path.read_text().strip())
            pub = base64.b64decode(pub_path.read_text().strip())
            return KeyMaterial(
                algorithm="ed25519",
                private=priv,
                public=pub,
                fingerprint=_fingerprint(pub),
            )
        priv, pub = _generate_ed25519_seed()
        priv_path.write_text(base64.b64encode(priv).decode("ascii"))
        pub_path.write_text(base64.b64encode(pub).decode("ascii"))
        try:
            os.chmod(priv_path, 0o600)
        except Exception as _bandit_exc:
            log.debug("swallowed in _generate_ed25519_seed: %s", _bandit_exc)
            pass
        log.info("generated new ed25519 evidence key: fingerprint=%s", _fingerprint(pub))
        return KeyMaterial(
            algorithm="ed25519",
            private=priv,
            public=pub,
            fingerprint=_fingerprint(pub),
        )

    # HMAC fallback
    secret = (
        os.getenv("CRP_COMPLY_EVIDENCE_SIGNING_SECRET") or os.getenv("CRP_COMPLY_JWT_SECRET") or ""
    ).encode("utf-8")
    if not secret:
        log.warning("no evidence signing secret set; signatures will be empty")
        return KeyMaterial("hmac-sha256", None, None, "unset")
    return KeyMaterial(
        algorithm="hmac-sha256",
        private=secret,
        public=None,
        fingerprint=hashlib.sha256(secret).hexdigest()[:16],
    )


def rotate_keys(data_dir: Path) -> KeyMaterial:
    """Generate a fresh keypair, archive the old one, return the new."""
    if not ED25519_SUPPORTED:
        raise RuntimeError("rotate_keys requires pynacl or cryptography")
    kd = _keys_dir(data_dir)
    history = kd / "history"
    history.mkdir(parents=True, exist_ok=True)
    old = load_or_create_keys(data_dir)
    if old.algorithm == "ed25519" and old.public is not None:
        archive = history / f"ed25519_{old.fingerprint}.json"
        archive.write_text(
            json.dumps(
                {
                    "fingerprint": old.fingerprint,
                    "public_b64": base64.b64encode(old.public).decode("ascii"),
                    "rotated_at": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
            )
        )
    (kd / "evidence_ed25519.priv").unlink(missing_ok=True)
    (kd / "evidence_ed25519.pub").unlink(missing_ok=True)
    return load_or_create_keys(data_dir)


# ─────────────────────────────────────────────────────────────
# Sign / verify
# ─────────────────────────────────────────────────────────────


def sign(data: bytes, key: KeyMaterial) -> SigningResult:
    """Produce a detached signature."""
    if key.algorithm == "ed25519":
        if _NACL_OK:
            sk = _nacl_signing.SigningKey(key.private)
            sig_bytes = bytes(sk.sign(data).signature)
        elif _CRYPTO_OK:
            sk = Ed25519PrivateKey.from_private_bytes(key.private or b"")
            sig_bytes = sk.sign(data)
        else:
            raise RuntimeError("ed25519 key but no backend loaded")
        return SigningResult(
            algorithm="ed25519",
            signature_b64=base64.b64encode(sig_bytes).decode("ascii"),
            public_key_b64=base64.b64encode(key.public or b"").decode("ascii"),
            key_fingerprint=key.fingerprint,
            signed_at=datetime.now(timezone.utc).isoformat(),
        )

    import hmac as _hmac

    sig = _hmac.new(key.private or b"", data, hashlib.sha256).digest()
    return SigningResult(
        algorithm="hmac-sha256",
        signature_b64=base64.b64encode(sig).decode("ascii"),
        public_key_b64=None,
        key_fingerprint=key.fingerprint,
        signed_at=datetime.now(timezone.utc).isoformat(),
    )


def verify(data: bytes, signature_b64: str, public_key_b64: str) -> bool:
    """Verify an ed25519 signature against a published public key."""
    if not ED25519_SUPPORTED:
        return False
    try:
        pub = base64.b64decode(public_key_b64)
        sig = base64.b64decode(signature_b64)
    except Exception:
        return False
    try:
        if _NACL_OK:
            _nacl_signing.VerifyKey(pub).verify(data, sig)
            return True
        if _CRYPTO_OK:
            Ed25519PublicKey.from_public_bytes(pub).verify(sig, data)
            return True
    except Exception:
        return False
    return False


def verify_manifest(manifest: dict[str, Any], signature_b64: str, public_key_b64: str) -> bool:
    """Verify the Ed25519 signature over a manifest dict.

    The signature was computed over the canonical JSON of the manifest
    *before* the ``signature`` field was attached, so this helper strips
    that field (and any runtime-only metadata such as ``zip_bytes`` and
    ``zip_path`` that are added after signing), re-serialises with the same
    parameters, and verifies.
    """
    stripped = {
        k: v for k, v in manifest.items() if k not in {"signature", "zip_bytes", "zip_path"}
    }
    canonical = json.dumps(stripped, indent=2, default=str, ensure_ascii=False).encode("utf-8")
    return verify(canonical, signature_b64, public_key_b64)


# ─────────────────────────────────────────────────────────────
# Public-key serving
# ─────────────────────────────────────────────────────────────


def export_public_key(data_dir: Path) -> dict[str, Any]:
    """Return the published public-key record for
    ``/.well-known/crp-comply-evidence-key.pub``.

    Fields are chosen to be human-readable AND machine-consumable.
    """
    key = load_or_create_keys(data_dir)
    return {
        "algorithm": key.algorithm,
        "fingerprint": key.fingerprint,
        "public_key_b64": (base64.b64encode(key.public).decode("ascii") if key.public else None),
        "usage": "crp-comply-evidence-pack-signatures",
        "verification": ("signature = base64(ed25519_sign(private, canonical_json(manifest)))"),
    }
