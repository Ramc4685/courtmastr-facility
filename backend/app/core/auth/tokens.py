"""Opaque tokens: <prefix>_<tenant hex>_<256-bit secret>, stored only as SHA-256 (security-baseline 5.1).

The tenant in the prefix is an address, not a credential: the hash is then verified under that tenant's RLS.
Prefixes: fhs access, fhr refresh, fhl emailed link.
"""

import hashlib
import secrets
from uuid import UUID


def mint(prefix: str, tenant_id: UUID) -> tuple[str, str]:
    raw = f"{prefix}_{tenant_id.hex}_{secrets.token_urlsafe(32)}"
    return raw, digest(raw)


def digest(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def tenant_of(raw: str | None, prefix: str) -> UUID | None:
    parts = (raw or "").split("_", 2)
    if len(parts) != 3 or parts[0] != prefix:
        return None
    try:
        return UUID(hex=parts[1])
    except ValueError:
        return None


def csrf_for(access_token: str) -> str:
    """Session-bound CSRF token. Derived from the HttpOnly access token, so it rotates with the session
    and needs no column; page scripts cannot compute it without being handed it by GET /auth/session."""
    return digest(f"csrf:{access_token}")
