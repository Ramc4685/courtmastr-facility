"""Pure webhook rules: signatures, the SSRF address policy, retry schedule and payload redaction (ADR 0007 s.7)."""

import hashlib
import hmac
import ipaddress
import random
from datetime import timedelta

# Eight attempts: the first, then these waits (about 45 hours in all).
RETRY_DELAYS = [timedelta(minutes=m) for m in (1, 5, 30, 120, 360, 720, 1440)]
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1
DISABLE_AFTER_FAILED_DELIVERIES = 20
DISABLE_AFTER_SILENCE = timedelta(days=5)
SIGNATURE_TOLERANCE_SEC = 300


def sign(secret: str, timestamp: int, body: bytes) -> str:
    return hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()


def signature_header(secrets: list[str], timestamp: int, body: bytes) -> str:
    """`t=<unix>,v1=<hex>[,v1=<hex>]`: during a rotation both the new and the previous secret sign."""
    return ",".join([f"t={timestamp}", *(f"v1={sign(s, timestamp, body)}" for s in secrets)])


def verify(secret: str, header: str, body: bytes, now: int, tolerance: int = SIGNATURE_TOLERANCE_SEC) -> bool:
    """What a consumer runs (docs/api/public-api-guide.md): any v1 matches and t is recent."""
    parts = [p.split("=", 1) for p in header.split(",") if "=" in p]
    stamps = [v for k, v in parts if k == "t"]
    if len(stamps) != 1 or not stamps[0].isdigit() or abs(now - int(stamps[0])) > tolerance:
        return False
    expected = sign(secret, int(stamps[0]), body)
    return any(hmac.compare_digest(expected, v) for k, v in parts if k == "v1")


def blocked_reason(address: str, *, allow_loopback: bool = False) -> str | None:
    """Why an outbound target address is refused, or None. Anything not globally routable is refused:
    private, loopback, link-local (cloud metadata 169.254.169.254 included), shared, reserved, multicast."""
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped  # ::ffff:10.0.0.1 is 10.0.0.1
    if ip.is_loopback:
        return None if allow_loopback else "loopback"
    for reason, test in (
        ("unspecified", ip.is_unspecified),
        ("link-local", ip.is_link_local),
        ("multicast", ip.is_multicast),
        ("private", ip.is_private),
    ):
        if test:
            return reason
    return None if ip.is_global else "reserved"


def next_delay(attempt_count: int, rng: random.Random | None = None) -> timedelta:
    """Wait before attempt number attempt_count + 1, with up to 10% jitter so retries do not stampede."""
    base = RETRY_DELAYS[attempt_count - 1]
    return base + base * (rng or random).uniform(0, 0.1)


# Payload fields shown in the delivery log as values; everything else is masked. Events are thin by contract,
# but the log is read by people who may not hold the event's read permission, so it fails closed.
_VISIBLE_SUFFIXES = ("_id", "_ids", "_minor", "_at", "_on")
_VISIBLE = {"type", "schema_version", "source_context", "source_type", "failure_category", "reason"}


def redact(payload: dict) -> dict:
    return {
        key: value if key in _VISIBLE or key.endswith(_VISIBLE_SUFFIXES) else "[redacted]"
        for key, value in payload.items()
    }
