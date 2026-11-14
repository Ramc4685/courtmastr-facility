"""Redis rate limits for the auth endpoints (security-baseline 6). Buckets and their defaults are configuration
(`rate_limit.buckets`); a bucket marked closed refuses while Redis is unreachable, the rest allow.

shortcut: fixed windows rather than the baseline's sliding window, so a burst straddling a window edge can
reach twice the limit once; move to a Lua sliding log if that ever matters.
"""

import logging
from functools import cache

import redis
from fastapi import Response

from app.core import clock, context
from app.core.auth.tokens import digest
from app.core.errors import DomainError
from app.core.settings import Bucket, get_settings

log = logging.getLogger(__name__)


@cache
def _redis() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis.url, socket_timeout=0.5)


def _bucket(name: str) -> Bucket:
    buckets = get_settings().rate_limit.buckets
    return buckets.get(name) or buckets["default"]


PREFIX = "rl"  # the test suite sets its own: lanes share one Redis and per-IP buckets are not tenant-scoped


def _key(name: str, subject: str, tenant: object, window: int) -> str:
    return f"{PREFIX}:{tenant}:{name}:{digest(subject.lower())[:32]}:{window}"


def hit(name: str, subject: str, response: Response | None = None, *, tenant: object = "-") -> None:
    """Count one request against `name` for `subject` (an IP, an email, an identity). Over the limit: 429 with
    Retry-After. Within it: RateLimit-* headers on `response`. Subjects are hashed: no addresses in Redis."""
    if not get_settings().rate_limit.enabled:
        return
    bucket = _bucket(name)
    now = clock.now().timestamp()
    window = int(now // bucket.window_sec)
    reset = max(int(bucket.window_sec - now % bucket.window_sec), 1)
    key = _key(name, subject, tenant, window)
    try:
        pipe = _redis().pipeline()
        pipe.incr(key)
        pipe.expire(key, bucket.window_sec)
        count = pipe.execute()[0]
    except redis.RedisError:
        log.warning("rate limit unavailable", extra={"bucket": name})
        if bucket.closed:
            raise DomainError(
                "This is briefly unavailable. Try again shortly.",
                status=503, code="rate-limit-unavailable", headers={"Retry-After": "30"},
            ) from None  # fmt: skip
        return
    headers = {
        "RateLimit-Limit": str(bucket.limit),
        "RateLimit-Remaining": str(max(bucket.limit - count, 0)),
        "RateLimit-Reset": str(reset),
    }
    if count > bucket.limit:
        raise DomainError(
            "Too many requests", status=429, code="rate-limited", headers=headers | {"Retry-After": str(reset)}
        )
    if response is not None:
        response.headers.update(headers)


def rate_limit(name: str):
    """Route dependency: one bucket keyed by the client IP (trusted-proxy aware, see core.api)."""

    def dependency(response: Response) -> None:
        hit(name, context.client_ip.get() or "unknown", response)

    return dependency
