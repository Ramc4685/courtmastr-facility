"""AES-256-GCM for C4 secrets we must replay, such as webhook signing keys (security-baseline 2.3, V6).

The only module that imports `cryptography`. Ciphertext is `<key id>:<base64 nonce+ct>`; the tenant id is the
associated data, so a ciphertext copied into another tenant's row does not decrypt.
shortcut: one environment key (FH_DATA_KEY) for every tenant, not a per-tenant data key wrapped by KMS; upgrade
when the first hosted environment exists (ADR 0007 open question 5).
"""

import base64
import hashlib
import hmac
import os
from functools import cache
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.settings import DEV_DATA_KEY, get_settings

_KEY_ID = "k1"


@cache
def _key() -> bytes:
    raw = os.environ.get("FH_DATA_KEY")
    if not raw:
        if get_settings().env not in ("dev", "test"):
            raise RuntimeError("FH_DATA_KEY must be set outside dev and test")
        raw = DEV_DATA_KEY  # get_settings() refuses it (and an absent key) outside dev and test
    key = base64.b64decode(raw)
    if len(key) != 32:
        raise RuntimeError("FH_DATA_KEY must be 32 bytes, base64-encoded")
    return key


def encrypt(plaintext: str, tenant_id: UUID) -> str:
    nonce = os.urandom(12)
    sealed = AESGCM(_key()).encrypt(nonce, plaintext.encode(), tenant_id.bytes)
    return f"{_KEY_ID}:{base64.b64encode(nonce + sealed).decode()}"


def decrypt(ciphertext: str, tenant_id: UUID) -> str:
    key_id, _, body = ciphertext.partition(":")
    if key_id != _KEY_ID:
        raise ValueError(f"unknown data key {key_id}")
    raw = base64.b64decode(body)
    return AESGCM(_key()).decrypt(raw[:12], raw[12:], tenant_id.bytes).decode()


def mac(message: str) -> str:
    """HMAC-SHA256 under a key derived from FH_DATA_KEY: signs short-lived URLs such as file downloads."""
    key = hmac.new(_key(), b"facilityhub-url-mac-v1", hashlib.sha256).digest()
    return hmac.new(key, message.encode(), hashlib.sha256).hexdigest()
