"""Fixed-window Redis rate limit for the anonymous auth endpoints (ADR 0002 abuse controls)."""

import logging
from functools import cache

import redis
from fastapi import Request

from app.core import clock
from app.core.errors import DomainError
from app.core.settings import get_settings

log = logging.getLogger(__name__)


@cache
def _redis() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis.url, socket_timeout=0.5)


def rate_limit(name: str):
    def dependency(request: Request) -> None:
        cfg = get_settings().rate_limit
        if not cfg.enabled:
            return
        ip = request.client.host if request.client else "unknown"
        window = int(clock.now().timestamp() // 60)
        key = f"rl:{name}:{ip}:{window}"
        try:
            pipe = _redis().pipeline()
            pipe.incr(key)
            pipe.expire(key, 60)
            count = pipe.execute()[0]
        except redis.RedisError:
            # Fail open: sign-in must survive a Redis outage; per-identity lockout still applies.
            log.warning("rate limit unavailable")
            return
        if count > cfg.auth_per_minute:
            raise DomainError("Too many requests", status=429, code="rate-limited", headers={"Retry-After": "60"})

    return dependency
