"""Client-side encryption for off-site backups (defence-in-depth).

The Cloudflare R2 / AWS S3 buckets we ship nightly tarballs to already
provide TLS in transit and per-object encryption at rest, but those
keys are managed by the cloud provider. This module adds an
**operator-controlled** layer on top: every byte that leaves the
``$CRP_COMPLY_DATA_DIR`` is encrypted with AES-256-GCM under a key the
cloud provider never sees, *before* it touches the boto3 upload.

Threat model addressed
----------------------

* Cloudflare insider with bucket access cannot read customer data.
* Mis-configured bucket ACL (accidental public exposure) leaks only
  ciphertext.
* Stolen R2 access key downloads ciphertext without the operator KEK.

Threat model NOT addressed (out of scope)
-----------------------------------------

* Process compromise on the API node — the KEK is loaded into memory
  on startup. Use Hashicorp Vault or KMS if you need to rotate beyond
  process lifetime.

File format (versioned, streamed)
---------------------------------

::

    magic(8)           = b"CRPENC01"
    header_len(4)      = uint32 BE
    header_json(N)     = {"alg": "AES-256-GCM", "chunk_size": 4194304,
                          "key_id": "<sha256 prefix of KEK>",
                          "created_at": "<iso8601>",
                          "source": "crp-comply-backup",
                          "version": 1}
    [ nonce(12) || ct_len(4) || ciphertext+tag(...) ] *
    final_marker(8)    = b"CRPEND01"

Each chunk uses a *fresh random nonce* so reuse across files is safe.
The last GCM tag is part of the final ciphertext block. The whole
file is read sequentially — no random-access required.

Decryption is implemented in :func:`decrypt_stream` with the same
chunking; ``crp-comply restore`` autodetects the magic header and
streams through the decryptor before extracting the tar.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import struct
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)


MAGIC = b"CRPENC01"
END_MARKER = b"CRPEND01"
DEFAULT_CHUNK_SIZE = 4 * 1024 * 1024  # 4 MiB
NONCE_LEN = 12
KEY_LEN = 32  # AES-256


# ---------------------------------------------------------------------------
# Key management
# ---------------------------------------------------------------------------


class BackupKeyError(RuntimeError):
    """Raised when the backup KEK is missing or malformed."""


def load_kek() -> bytes:
    """Load the 32-byte AES-256 KEK from environment.

    Two formats are accepted (in order):

    1. ``BACKUP_ENCRYPTION_KEY`` — base64 or hex-encoded 32-byte key.
    2. ``BACKUP_ENCRYPTION_PASSPHRASE`` — passphrase that is hashed
       with SHA-256 to derive a 32-byte key. **Lower-strength**: the
       full 32-byte path is preferred for production.

    Raises :class:`BackupKeyError` when neither is set.
    """
    raw = (os.environ.get("BACKUP_ENCRYPTION_KEY") or "").strip()
    if raw:
        # Try base64 first, then hex.
        import base64

        for decoder, name in ((base64.b64decode, "base64"), (bytes.fromhex, "hex")):
            try:
                key = decoder(raw)
            except Exception:
                continue
            if len(key) == KEY_LEN:
                return key
            logger.debug(
                "BACKUP_ENCRYPTION_KEY decoded as %s but length=%d (need %d)",
                name,
                len(key),
                KEY_LEN,
            )
        raise BackupKeyError("BACKUP_ENCRYPTION_KEY set but is not a 32-byte base64 or hex value")

    passphrase = (os.environ.get("BACKUP_ENCRYPTION_PASSPHRASE") or "").strip()
    if passphrase:
        return hashlib.sha256(passphrase.encode("utf-8")).digest()

    raise BackupKeyError(
        "no backup encryption key configured "
        "(set BACKUP_ENCRYPTION_KEY or BACKUP_ENCRYPTION_PASSPHRASE)"
    )


def is_encryption_enabled() -> bool:
    """True if either KEK env var is set."""
    return bool(
        (os.environ.get("BACKUP_ENCRYPTION_KEY") or "").strip()
        or (os.environ.get("BACKUP_ENCRYPTION_PASSPHRASE") or "").strip()
    )


def key_id(kek: bytes) -> str:
    """Stable short identifier for a KEK (first 12 hex chars of SHA-256).

    Used in the file header so a multi-key restore tool can pick the
    right KEK without trial decryption.
    """
    return hashlib.sha256(kek).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Streaming encrypt / decrypt
# ---------------------------------------------------------------------------


def encrypt_file(
    src_path: Path | str,
    dst_path: Path | str,
    *,
    kek: bytes | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> dict[str, object]:
    """Encrypt ``src_path`` to ``dst_path`` using AES-256-GCM streaming.

    Returns a summary dict with the bytes read/written, the ``key_id``
    and the per-chunk count — useful for auditing.
    """
    src = Path(src_path)
    dst = Path(dst_path)
    if kek is None:
        kek = load_kek()
    if len(kek) != KEY_LEN:
        raise BackupKeyError(f"KEK must be {KEY_LEN} bytes, got {len(kek)}")
    aead = AESGCM(kek)

    header = {
        "alg": "AES-256-GCM",
        "chunk_size": chunk_size,
        "key_id": key_id(kek),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": "crp-comply-backup",
        "version": 1,
    }
    header_bytes = json.dumps(header, separators=(",", ":")).encode("utf-8")

    bytes_in = 0
    bytes_out = 0
    chunks = 0
    with src.open("rb") as fin, dst.open("wb") as fout:
        fout.write(MAGIC)
        fout.write(struct.pack(">I", len(header_bytes)))
        fout.write(header_bytes)
        bytes_out += len(MAGIC) + 4 + len(header_bytes)
        chunk_idx = 0
        while True:
            chunk = fin.read(chunk_size)
            if not chunk:
                break
            bytes_in += len(chunk)
            nonce = os.urandom(NONCE_LEN)
            # Bind chunk index into the AAD so re-ordering is detectable.
            aad = struct.pack(">Q", chunk_idx)
            ct = aead.encrypt(nonce, chunk, aad)
            fout.write(nonce)
            fout.write(struct.pack(">I", len(ct)))
            fout.write(ct)
            bytes_out += NONCE_LEN + 4 + len(ct)
            chunks += 1
            chunk_idx += 1
        fout.write(END_MARKER)
        bytes_out += len(END_MARKER)

    return {
        "bytes_in": bytes_in,
        "bytes_out": bytes_out,
        "chunks": chunks,
        "key_id": header["key_id"],
        "alg": header["alg"],
    }


def is_encrypted_file(path: Path | str) -> bool:
    """Probe the first 8 bytes for our magic."""
    p = Path(path)
    try:
        with p.open("rb") as fh:
            return fh.read(len(MAGIC)) == MAGIC
    except OSError:
        return False


def read_header(path: Path | str) -> dict[str, object]:
    """Read and return the JSON header without decrypting any chunks."""
    p = Path(path)
    with p.open("rb") as fh:
        magic = fh.read(len(MAGIC))
        if magic != MAGIC:
            raise BackupKeyError(f"not a CRP encrypted file: {p}")
        (header_len,) = struct.unpack(">I", fh.read(4))
        header_bytes = fh.read(header_len)
        return json.loads(header_bytes.decode("utf-8"))


def decrypt_file(
    src_path: Path | str,
    dst_path: Path | str,
    *,
    kek: bytes | None = None,
) -> dict[str, object]:
    """Reverse :func:`encrypt_file`. Verifies AAD + GCM tag per chunk."""
    src = Path(src_path)
    dst = Path(dst_path)
    if kek is None:
        kek = load_kek()
    if len(kek) != KEY_LEN:
        raise BackupKeyError(f"KEK must be {KEY_LEN} bytes, got {len(kek)}")
    aead = AESGCM(kek)

    bytes_in = 0
    bytes_out = 0
    chunks = 0
    with src.open("rb") as fin, dst.open("wb") as fout:
        magic = fin.read(len(MAGIC))
        if magic != MAGIC:
            raise BackupKeyError(f"not a CRP encrypted file: {src}")
        (header_len,) = struct.unpack(">I", fin.read(4))
        header_bytes = fin.read(header_len)
        header = json.loads(header_bytes.decode("utf-8"))
        bytes_in = len(MAGIC) + 4 + header_len
        if header.get("key_id") != key_id(kek):
            raise BackupKeyError(
                f"KEK mismatch: file expects key_id={header.get('key_id')}, "
                f"have key_id={key_id(kek)}"
            )
        chunk_idx = 0
        while True:
            head = fin.read(len(END_MARKER))
            if head == END_MARKER:
                break
            if len(head) < len(END_MARKER):
                raise BackupKeyError(f"truncated archive at chunk {chunk_idx}")
            # ``head`` is the first 8 bytes of a 12-byte nonce; pull the rest.
            nonce = head + fin.read(NONCE_LEN - len(END_MARKER))
            if len(nonce) < NONCE_LEN:
                raise BackupKeyError(f"truncated archive at chunk {chunk_idx}")
            ct_len_buf = fin.read(4)
            if len(ct_len_buf) < 4:
                raise BackupKeyError(f"truncated archive at chunk {chunk_idx}")
            (ct_len,) = struct.unpack(">I", ct_len_buf)
            ct = fin.read(ct_len)
            if len(ct) != ct_len:
                raise BackupKeyError(
                    f"truncated chunk {chunk_idx}: expected {ct_len}, got {len(ct)}"
                )
            aad = struct.pack(">Q", chunk_idx)
            pt = aead.decrypt(nonce, ct, aad)
            fout.write(pt)
            bytes_in += NONCE_LEN + 4 + len(ct)
            bytes_out += len(pt)
            chunks += 1
            chunk_idx += 1

    return {
        "bytes_in": bytes_in,
        "bytes_out": bytes_out,
        "chunks": chunks,
        "key_id": key_id(kek),
        "header": header,
    }


__all__ = [
    "BackupKeyError",
    "DEFAULT_CHUNK_SIZE",
    "MAGIC",
    "END_MARKER",
    "load_kek",
    "is_encryption_enabled",
    "key_id",
    "encrypt_file",
    "decrypt_file",
    "is_encrypted_file",
    "read_header",
]
