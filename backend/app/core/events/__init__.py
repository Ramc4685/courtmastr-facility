"""Domain events through a transactional outbox (overview 3.11). Nothing is sent to Redis from request code."""

from collections import defaultdict
from collections.abc import Callable
from datetime import datetime
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Index, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.db.base import Base, JsonDict, TenantOwned, tenant_args
from app.core.ids import new_id
from app.core.jobs import tenant_actor


class OutboxEvent(TenantOwned, Base):
    __tablename__ = "outbox_event"
    __table_args__ = tenant_args(
        Index("ix_outbox_event_unpublished", "occurred_at", postgresql_where=text("published_at IS NULL")),
        Index("ix_outbox_event_aggregate", "tenant_id", "aggregate_type", "aggregate_id"),
    )

    event_type: Mapped[str]
    aggregate_type: Mapped[str]
    aggregate_id: Mapped[UUID]
    payload: Mapped[dict] = mapped_column(JsonDict)
    occurred_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    published_at: Mapped[datetime | None]
    attempts: Mapped[int] = mapped_column(server_default=text("0"))


class ProcessedEvent(TenantOwned, Base):
    __tablename__ = "processed_event"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "consumer_name", "event_id", name="uq_processed_event"))

    consumer_name: Mapped[str]
    event_id: Mapped[UUID]
    processed_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class Event(BaseModel):
    """Thin, frozen payload: ids plus the transition. Subclasses set `type` (a Literal default) and
    `aggregate_type`. Removing or retyping a field bumps schema_version: payloads are a public contract."""

    model_config = ConfigDict(frozen=True)
    aggregate_type: ClassVar[str]
    type: str
    schema_version: int = 1


# event type -> actors enqueued by the relay
SUBSCRIBERS: dict[str, list] = defaultdict(list)


def publish(session: Session, event: Event, aggregate_id: UUID) -> None:
    """Insert the outbox row in the caller's transaction; a rollback leaves no event."""
    session.add(
        OutboxEvent(
            event_type=event.type,
            aggregate_type=event.aggregate_type,
            aggregate_id=aggregate_id,
            payload=event.model_dump(mode="json"),
        )
    )


def handles(event_type: str):
    """Subscribe a handler `fn(session, payload)`. It runs as a @tenant_actor and at most once per event:
    (consumer, event_id) is inserted in the handler's transaction and a duplicate delivery is skipped."""

    def decorate(fn: Callable):
        consumer = f"{fn.__module__}.{fn.__name__}"

        def run(session: Session, event_id: str, payload: dict) -> None:
            first_delivery = session.execute(
                pg_insert(ProcessedEvent)
                .values(
                    id=new_id(), tenant_id=session.info["tenant_id"], consumer_name=consumer, event_id=UUID(event_id)
                )
                .on_conflict_do_nothing()
                .returning(ProcessedEvent.id)
            ).first()
            if first_delivery:
                fn(session, payload)

        run.__name__ = consumer
        actor = tenant_actor(run, actor_name=consumer)
        SUBSCRIBERS[event_type].append(actor)
        return actor

    return decorate
