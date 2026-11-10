"""engagement consent tables (docs/architecture/data-model-programs.md sections 3.2 and 3.2a). Thin slice shipped
with build module 4 for CLI-16; build module 13 adds the rest of engagement around them."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, Index, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import CITEXT, INET
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantOwned, Timestamps, enum_check, enum_column, tenant_args, tfk


class Channel(StrEnum):
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"


class Topic(StrEnum):
    SESSION_REMINDERS = "session_reminders"
    CARD_EXPIRATION = "card_expiration"
    EMAIL_CAMPAIGNS = "email_campaigns"
    SMS_MARKETING = "sms_marketing"
    PUSH_ANNOUNCEMENTS = "push_announcements"
    LEAGUE_ALERTS = "league_alerts"


class Source(StrEnum):
    VERIFICATION_STEP = "verification_step"
    PREFERENCE_CENTER = "preference_center"
    ONE_CLICK = "one_click"
    STAFF = "staff"
    SMS_KEYWORD = "sms_keyword"
    IMPORT = "import"
    PORTAL = "portal"


class ActorType(StrEnum):
    CLIENT = "client"
    STAFF = "staff"
    SYSTEM = "system"


class ConsentKind(StrEnum):
    OPT_IN = "opt_in"
    OPT_OUT = "opt_out"


class Basis(StrEnum):
    EXPRESS = "express"
    EXPRESS_WRITTEN = "express_written"
    EXPRESS_VERBAL = "express_verbal"
    IMPLIED_PURCHASE = "implied_purchase"
    IMPLIED_INQUIRY = "implied_inquiry"


class ConsentEvent(TenantOwned, Base):
    """Append-only consent proof. Every change to communication_preference inserts one row here."""

    __tablename__ = "consent_event"
    __table_args__ = tenant_args(
        *tfk("client_id", "client", index=False),
        enum_check("channel", Channel),
        enum_check("topic", Topic),
        enum_check("kind", ConsentKind),
        enum_check("basis", Basis),
        enum_check("source", Source),
        enum_check("actor_type", ActorType),
        CheckConstraint("actor_type <> 'staff' OR note IS NOT NULL", name="note"),
        Index(
            "ix_consent_event_subject", "tenant_id", "client_id", "channel", "address", "topic",
            text("occurred_at DESC"),
        ),
    )  # fmt: skip

    client_id: Mapped[UUID]
    channel: Mapped[str] = enum_column()
    address: Mapped[str | None] = mapped_column(CITEXT, info={"audit": "flag"})
    topic: Mapped[str] = enum_column()
    kind: Mapped[str] = enum_column()
    basis: Mapped[str] = enum_column()
    source: Mapped[str] = enum_column()
    actor_type: Mapped[str] = enum_column()
    actor_id: Mapped[UUID | None]
    ip: Mapped[str | None] = mapped_column(INET)
    expires_at: Mapped[datetime | None]
    note: Mapped[str | None]
    occurred_at: Mapped[datetime] = mapped_column(server_default=func.now())


class CommunicationPreference(TenantOwned, Timestamps, Base):
    """Current subscription per client, channel, address and topic; absent row = the topic default (MKT-02)."""

    __tablename__ = "communication_preference"
    __table_args__ = tenant_args(
        *tfk("client_id", "client", index=False),
        *tfk("consent_event_id", "consent_event"),
        UniqueConstraint(
            "tenant_id", "client_id", "channel", "address", "topic", name="uq_communication_preference",
            postgresql_nulls_not_distinct=True,
        ),
        enum_check("channel", Channel),
        enum_check("topic", Topic),
        enum_check("source", Source),
        enum_check("changed_by_actor_type", ActorType),
    )  # fmt: skip

    client_id: Mapped[UUID]
    channel: Mapped[str] = enum_column()
    address: Mapped[str | None] = mapped_column(CITEXT, info={"audit": "flag"})
    topic: Mapped[str] = enum_column()
    is_subscribed: Mapped[bool] = mapped_column(info={"audit": "value"})
    source: Mapped[str] = enum_column()
    changed_by_actor_type: Mapped[str] = enum_column()
    changed_by_actor_id: Mapped[UUID | None]
    changed_at: Mapped[datetime] = mapped_column(server_default=func.now())
    consent_event_id: Mapped[UUID | None]
