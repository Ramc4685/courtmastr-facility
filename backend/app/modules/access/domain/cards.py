"""Digital member cards (CHK-13): a rotating QR the app derives offline from its card seed, verified by the
server at scan. QR text is `fhq.<credential id>.<time step>.<hmac>`; the current and previous step are accepted,
so a code is good for 30 to 60 seconds. State (revocation) stays on the server."""

import base64
import hashlib
import hmac
from datetime import datetime
from uuid import UUID

STEP_SECONDS = 30
PREFIX = "fhq"


def step_of(at: datetime) -> int:
    return int(at.timestamp()) // STEP_SECONDS


def _mac(secret: bytes, credential_id: UUID, step: int) -> str:
    digest = hmac.new(secret, f"{credential_id}.{step}".encode(), hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def seed(credential_id: UUID, secret: bytes) -> str:
    """What the app keeps to render codes offline (returned once, at issue)."""
    return f"{credential_id}.{base64.urlsafe_b64encode(secret).decode().rstrip('=')}"


def qr_text(card_seed: str, at: datetime) -> str:
    """The code the app shows at `at` (mirrors the app; used by tests and the web preview)."""
    credential_id, encoded = card_seed.split(".", 1)
    secret = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    step = step_of(at)
    return f"{PREFIX}.{credential_id}.{step}.{_mac(secret, UUID(credential_id), step)}"


def parse(text: str) -> tuple[UUID, int, str] | None:
    parts = text.strip().split(".")
    if len(parts) != 4 or parts[0].lower() != PREFIX:
        return None
    try:
        return UUID(parts[1]), int(parts[2]), parts[3]
    except ValueError:
        return None


def is_authentic(secret: bytes, credential_id: UUID, step: int, mac: str) -> bool:
    """The card's own signature for that step, whatever its age (a stale screenshot is authentic, not current)."""
    return hmac.compare_digest(mac, _mac(secret, credential_id, step))


def verify(secret: bytes, credential_id: UUID, step: int, mac: str, at: datetime) -> bool:
    now = step_of(at)
    return step in (now, now - 1) and is_authentic(secret, credential_id, step, mac)
