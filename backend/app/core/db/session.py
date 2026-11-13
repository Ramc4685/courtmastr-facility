"""The one way to reach tenant data: a transaction whose first statement sets app.tenant_id (overview 3.4)."""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import cache
from typing import Any
from uuid import UUID

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session

from app.core.settings import get_settings


@cache
def app_engine() -> Engine:
    settings = get_settings()
    return create_engine(
        settings.db_url("app"), pool_size=settings.db.pool_size, pool_pre_ping=True, hide_parameters=True
    )  # bound values (names, emails, birth dates) stay out of error text and logs


def open_tenant_session(tenant_id: UUID, actor: Any = None) -> Session:
    """Caller owns commit/rollback/close. Prefer tenant_session(); the request pipeline uses this directly."""
    session = Session(app_engine(), expire_on_commit=False)
    # set_config(..., true) is SET LOCAL with a bind parameter; it dies with the transaction, so pooling is safe.
    session.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})
    session.info["tenant_id"], session.info["actor"] = tenant_id, actor
    event.listen(session, "loaded_as_persistent", _pin)
    return session


def _pin(session: Session, instance: Any) -> None:
    """Keep small reference rows (a model with `__pinned__ = True`: tenant, location) alive for the session. The
    identity map holds rows weakly, so `session.get` of a row nobody kept re-selected it: six times per POS sale
    (docs/ops/performance-budget.md)."""
    if getattr(instance, "__pinned__", False):
        session.info.setdefault("pinned", []).append(instance)


def run_after_commit(session: Session) -> None:
    for hook in session.info.pop("after_commit", []):
        hook()


@contextmanager
def tenant_session(tenant_id: UUID, actor: Any = None) -> Iterator[Session]:
    session = open_tenant_session(tenant_id, actor)
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
    run_after_commit(session)
