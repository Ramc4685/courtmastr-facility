"""Dramatiq wiring and @tenant_actor (overview 3.4). A plain @dramatiq.actor must not touch tenant tables."""

import functools
from collections.abc import Callable
from uuid import UUID

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.brokers.stub import StubBroker
from dramatiq.middleware import Retries

from app.core.auth.principal import system_principal
from app.core.db.session import tenant_session
from app.core.settings import get_settings

_settings = get_settings()
# Set at import so every actor declared afterwards binds to it. Tests use the in-memory stub broker.
broker = StubBroker() if _settings.jobs.broker == "stub" else RedisBroker(url=_settings.redis.url)
if isinstance(broker, StubBroker):
    # Tests: a failing job dead-letters at once (fail_fast raises its error) instead of retrying with a backoff
    # that keeps every later queue drain waiting.
    for _middleware in broker.middleware:
        if isinstance(_middleware, Retries):
            _middleware.max_retries = 0
dramatiq.set_broker(broker)


def tenant_actor(fn: Callable | None = None, **options):
    """Declare a tenant-scoped actor. Messages carry tenant_id first; the body receives a session already
    inside tenant_session(tenant_id, actor=system). Actors must be idempotent: delivery is at-least-once."""

    def decorate(fn: Callable):
        @functools.wraps(fn)
        def run(tenant_id: str, *args, **kwargs):
            with tenant_session(UUID(tenant_id), actor=system_principal(fn.__name__)) as session:
                return fn(session, *args, **kwargs)

        options.setdefault("actor_name", fn.__name__)
        return dramatiq.actor(run, **options)

    return decorate(fn) if fn else decorate
