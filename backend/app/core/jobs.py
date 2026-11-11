"""Dramatiq wiring, @tenant_actor and @chunked_actor (overview 3.4, ADR 0008), and the dead-letter recorder.
A plain @dramatiq.actor must not touch tenant tables."""

import functools
import json
import logging
from collections.abc import Callable
from uuid import UUID

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.brokers.stub import StubBroker
from dramatiq.middleware import Middleware, Retries
from sqlalchemy import text
from sqlalchemy.exc import StatementError

from app.core.auth.principal import system_principal
from app.core.db.session import tenant_session
from app.core.settings import get_settings

log = logging.getLogger(__name__)
_DETAIL_CHARS = 500


def _error_detail(error: BaseException | None) -> str | None:
    """First line only: a database error's later lines (DETAIL, parameters) can quote row values."""
    if error is None:
        return None
    source = error.orig if isinstance(error, StatementError) and error.orig is not None else error
    lines = str(source).splitlines()
    return lines[0][:_DETAIL_CHARS] if lines else None


class FailedJobRecorder(Middleware):
    """ADR 0008 section 7: a message that is finally rejected (retries exhausted, or no retries) becomes a
    `failed_job` row in its tenant, so dead letters are queryable and survive Redis. Only tenant actors are
    recorded: their first argument is the tenant id. Requeue is safe because actors are idempotent."""

    def after_nack(self, broker, message) -> None:
        args = list(message.args)
        try:
            tenant_id = UUID(str(args[0]))
        except (IndexError, ValueError):
            log.error("dead letter outside a tenant", extra={"actor": message.actor_name})
            return
        error = message._exception  # set by the worker for the failed attempt; no public accessor in Dramatiq 2
        with tenant_session(tenant_id) as session:
            session.execute(
                text(
                    "INSERT INTO failed_job (tenant_id, actor_name, queue, message_id, args, error_class, "
                    "error_detail, attempts) VALUES (:tenant, :actor, :queue, :message, CAST(:args AS jsonb), "
                    ":cls, :detail, :attempts) ON CONFLICT ON CONSTRAINT uq_failed_job DO NOTHING"
                ),
                {
                    "tenant": tenant_id, "actor": message.actor_name, "queue": message.queue_name,
                    "message": message.message_id, "args": json.dumps(args[1:], default=str),
                    "cls": type(error).__name__ if error else "Unknown", "detail": _error_detail(error),
                    "attempts": max(message.options.get("retries", 0), 1),
                },
            )  # fmt: skip


_settings = get_settings()
# Set at import so every actor declared afterwards binds to it. Tests use the in-memory stub broker.
broker = StubBroker() if _settings.jobs.broker == "stub" else RedisBroker(url=_settings.redis.url)
if isinstance(broker, StubBroker):
    # Tests: a failing job dead-letters at once (fail_fast raises its error) instead of retrying with a backoff
    # that keeps every later queue drain waiting.
    for _middleware in broker.middleware:
        if isinstance(_middleware, Retries):
            _middleware.max_retries = 0
broker.add_middleware(FailedJobRecorder())
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


def chunked_actor(fn: Callable | None = None, **options):
    """Declare a chunked tenant actor (ADR 0008 section 3: bulk work is a chain, not a flood).

    `fn(session, *ids) -> bool` does ONE bounded chunk: lock its job row `FOR UPDATE`, read the cursor from the
    row, do the work, write the advanced cursor and counts back to the row, and return True while work remains.
    After that chunk commits the actor sends itself again with the same ids. Progress lives in Postgres, never in
    the message, so a crash or a redelivery repeats at most the chunk that did not commit, and a duplicate message
    only serialises on the row lock. How a context converts its own heavy work: platform README, "Chunked jobs"."""

    def decorate(fn: Callable):
        @functools.wraps(fn)
        def chunk(session, *ids) -> None:
            if fn(session, *ids):
                tenant_id = str(session.info["tenant_id"])
                session.info.setdefault("after_commit", []).append(lambda: actor.send(tenant_id, *ids))

        actor = tenant_actor(chunk, **options)
        return actor

    return decorate(fn) if fn else decorate
