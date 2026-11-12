"""engagement consent tables (docs/architecture/data-model-programs.md sections 3.2 and 3.2a). Thin slice shipped
with build module 4 for CLI-16; build module 13 adds the rest of engagement around them."""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, Index, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, INET
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, JsonDict, TenantOwned, Timestamps, enum_check, enum_column, tenant_args, tfk


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


# --- module 14: outbound messaging, inbox, reminders, automations, portal content ---------------------------


class MessageChannel(StrEnum):
    EMAIL = "email"
    PUSH = "push"


class TemplateOrigin(StrEnum):
    PRESET = "preset"
    SAVED = "saved"
    SYSTEM = "system"


class CampaignStatus(StrEnum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    SENDING = "sending"
    SENT = "sent"
    CANCELLED = "cancelled"
    RECALLED = "recalled"


class MessageCategory(StrEnum):
    MARKETING = "marketing"
    TRANSACTIONAL = "transactional"
    OPERATIONAL = "operational"


class MessageStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    DELIVERED = "delivered"
    OPENED = "opened"
    CLICKED = "clicked"
    BOUNCED = "bounced"
    COMPLAINED = "complained"
    FAILED = "failed"
    SKIPPED = "skipped"


class SkipReason(StrEnum):
    UNVERIFIED = "unverified"
    UNSUBSCRIBED = "unsubscribed"
    SUPPRESSED = "suppressed"
    DUPLICATE = "duplicate"
    INVALID_ADDRESS = "invalid_address"
    INACTIVE_CLIENT = "inactive_client"
    CHANNEL_UNAVAILABLE = "channel_unavailable"


class SuppressionReason(StrEnum):
    BOUNCE = "bounce"
    COMPLAINT = "complaint"
    MANUAL = "manual"


class DevicePlatform(StrEnum):
    IOS = "ios"
    ANDROID = "android"


class NotificationKind(StrEnum):
    SESSION_REMINDER = "session_reminder"
    AUTOMATION = "automation"


class NotificationStatus(StrEnum):
    SCHEDULED = "scheduled"
    SENT = "sent"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class AlertKind(StrEnum):
    PAYMENT_DECLINED = "payment_declined"
    PORTAL_ACTION = "portal_action"
    INSTANT_BOOKING = "instant_booking"
    ONLINE_REGISTRATION = "online_registration"
    WAITLIST_PROMOTED = "waitlist_promoted"


class MessageTemplate(TenantOwned, Timestamps, Base):
    """Reusable content for campaigns, direct messages and system notices (MKT-05). Plain text with
    `$field` merge fields from a fixed catalogue; presets are read-only and edited by copying."""

    __tablename__ = "message_template"
    __table_args__ = tenant_args(
        *tfk("copied_from_id", "message_template"),
        enum_check("channel", MessageChannel),
        enum_check("origin", TemplateOrigin),
        CheckConstraint("channel <> 'push' OR char_length(body_text) <= 180", name="push_length"),
        CheckConstraint("(origin = 'system') = (system_key IS NOT NULL)", name="system_key"),
        Index("uq_message_template_name", "tenant_id", "channel", text("lower(name)"), unique=True,
              postgresql_where=text("origin <> 'system'")),
        Index("uq_message_template_system_key", "tenant_id", "channel", "system_key", unique=True,
              postgresql_where=text("system_key IS NOT NULL")),
    )  # fmt: skip

    channel: Mapped[str] = enum_column(server_default=text("'email'"))
    origin: Mapped[str] = enum_column(server_default=text("'saved'"))
    system_key: Mapped[str | None] = mapped_column(info={"audit": "value"})
    name: Mapped[str]
    category: Mapped[str | None]
    subject: Mapped[str | None]
    body_text: Mapped[str]
    copied_from_id: Mapped[UUID | None]
    is_active: Mapped[bool] = mapped_column(server_default=text("true"), info={"audit": "value"})


class Segment(TenantOwned, Timestamps, Base):
    """A saved audience definition, evaluated at send time (MKT-03)."""

    __tablename__ = "segment"
    __table_args__ = tenant_args(
        Index("uq_segment_name", "tenant_id", text("lower(name)"), unique=True),
    )

    name: Mapped[str]
    is_builtin: Mapped[bool] = mapped_column(server_default=text("false"), info={"audit": "value"})
    definition: Mapped[dict] = mapped_column(JsonDict)
    last_count: Mapped[int | None]
    last_counted_at: Mapped[datetime | None]


class Campaign(TenantOwned, Timestamps, Base):
    """A bulk send for one location on one channel: an email campaign (MKT-03) or an announcement that lands
    in members' inboxes and goes out as push where the member allows it (MKT-16)."""

    __tablename__ = "campaign"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        *tfk("message_template_id", "message_template"),
        *tfk("segment_id", "segment"),
        *tfk("sender_staff_user_id", "staff_user"),
        *tfk("copied_from_id", "campaign"),
        enum_check("channel", MessageChannel),
        enum_check("status", CampaignStatus),
        CheckConstraint("channel <> 'push' OR char_length(body_text) <= 180", name="push_length"),
        CheckConstraint("status <> 'scheduled' OR scheduled_at IS NOT NULL", name="scheduled_at"),
        Index("ix_campaign_list", "tenant_id", "location_id", "channel", "status", "id"),
        Index("ix_campaign_due", "scheduled_at", postgresql_where=text("status = 'scheduled'")),
    )  # fmt: skip

    location_id: Mapped[UUID]
    channel: Mapped[str] = enum_column()
    name: Mapped[str]
    subject: Mapped[str | None]
    body_text: Mapped[str] = mapped_column(server_default=text("''"))
    link_url: Mapped[str | None]
    message_template_id: Mapped[UUID | None]
    segment_id: Mapped[UUID | None]
    audience: Mapped[dict | None] = mapped_column(JsonDict, nullable=True)
    reply_to: Mapped[str | None] = mapped_column(CITEXT)
    sender_staff_user_id: Mapped[UUID | None]  # None when an API key sends
    status: Mapped[str] = enum_column(server_default=text("'draft'"))
    scheduled_at: Mapped[datetime | None]
    # PLT-06: did whoever scheduled it hold send_all? The send job refuses an all-clients audience without it.
    is_send_all_granted: Mapped[bool] = mapped_column(server_default=text("false"), info={"audit": "value"})
    hold_reason: Mapped[str | None]  # why the send job returned a scheduled campaign to draft
    started_at: Mapped[datetime | None]
    sent_at: Mapped[datetime | None]
    recalled_at: Mapped[datetime | None]
    attempted_count: Mapped[int] = mapped_column(server_default=text("0"))
    duplicate_count: Mapped[int] = mapped_column(server_default=text("0"))
    invalid_count: Mapped[int] = mapped_column(server_default=text("0"))
    unverified_count: Mapped[int] = mapped_column(server_default=text("0"))
    unsubscribed_skip_count: Mapped[int] = mapped_column(server_default=text("0"))
    suppressed_count: Mapped[int] = mapped_column(server_default=text("0"))
    sent_count: Mapped[int] = mapped_column(server_default=text("0"))
    delivered_count: Mapped[int] = mapped_column(server_default=text("0"))
    opened_count: Mapped[int] = mapped_column(server_default=text("0"))
    clicked_count: Mapped[int] = mapped_column(server_default=text("0"))
    bounced_count: Mapped[int] = mapped_column(server_default=text("0"))
    complaint_count: Mapped[int] = mapped_column(server_default=text("0"))
    unsubscribed_count: Mapped[int] = mapped_column(server_default=text("0"))
    inbox_count: Mapped[int] = mapped_column(server_default=text("0"))
    copied_from_id: Mapped[UUID | None]


class Message(TenantOwned, Timestamps, Base):
    """One outbound message to one recipient on one channel, whatever caused it: the per-client audit trail
    (MKT-09), campaign analytics (MKT-07) and suppression (MKT-08) read this one table."""

    __tablename__ = "message"
    __table_args__ = tenant_args(
        *tfk("client_id", "client", index=False),
        *tfk("recipient_staff_user_id", "staff_user"),
        *tfk("device_registration_id", "device_registration"),
        *tfk("campaign_id", "campaign", ondelete="CASCADE", index=False),
        *tfk("message_template_id", "message_template"),
        *tfk("location_id", "location"),
        *tfk("sender_staff_user_id", "staff_user"),
        enum_check("channel", MessageChannel),
        enum_check("category", MessageCategory),
        enum_check("status", MessageStatus),
        enum_check("skip_reason", SkipReason),
        CheckConstraint(
            "client_id IS NOT NULL OR recipient_staff_user_id IS NOT NULL OR to_address IS NOT NULL", name="recipient"
        ),
        CheckConstraint("(status = 'skipped') = (skip_reason IS NOT NULL)", name="skip_reason_set"),
        Index("uq_message_dedupe_key", "tenant_id", "dedupe_key", unique=True,
              postgresql_where=text("dedupe_key IS NOT NULL")),
        Index("uq_message_unsubscribe_token", "tenant_id", "unsubscribe_token_hash", unique=True,
              postgresql_where=text("unsubscribe_token_hash IS NOT NULL")),
        Index("ix_message_client_timeline", "tenant_id", "client_id", "id"),
        Index("ix_message_campaign_status", "tenant_id", "campaign_id", "status"),
        Index("ix_message_provider_id", "tenant_id", "provider", "provider_message_id"),
    )  # fmt: skip

    channel: Mapped[str] = enum_column()
    category: Mapped[str] = enum_column()
    topic: Mapped[str | None] = mapped_column(info={"audit": "value"})
    client_id: Mapped[UUID | None]
    recipient_staff_user_id: Mapped[UUID | None]
    to_address: Mapped[str | None] = mapped_column(CITEXT, info={"audit": "flag"})
    device_registration_id: Mapped[UUID | None]
    campaign_id: Mapped[UUID | None]
    message_template_id: Mapped[UUID | None]
    location_id: Mapped[UUID | None]
    sender_staff_user_id: Mapped[UUID | None]
    subject: Mapped[str | None]
    body_text: Mapped[str | None]
    source_event_type: Mapped[str | None] = mapped_column(info={"audit": "value"})
    dedupe_key: Mapped[str | None] = mapped_column(info={"audit": "value"})
    status: Mapped[str] = enum_column(server_default=text("'queued'"))
    skip_reason: Mapped[str | None] = enum_column()
    provider: Mapped[str | None] = mapped_column(info={"audit": "value"})
    provider_message_id: Mapped[str | None] = mapped_column(info={"audit": "value"})
    unsubscribe_token_hash: Mapped[str | None] = mapped_column(info={"audit": "never"})
    queued_at: Mapped[datetime] = mapped_column(server_default=func.now())
    sent_at: Mapped[datetime | None]
    last_event_at: Mapped[datetime | None]


class Suppression(TenantOwned, Timestamps, Base):
    """Addresses that must not be mailed (MKT-08), per tenant. Active while not released, or permanent."""

    __tablename__ = "suppression"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", "channel", "address", name="uq_suppression_address"),
        *tfk("released_by_staff_user_id", "staff_user"),
        enum_check("channel", MessageChannel),
        enum_check("reason", SuppressionReason),
    )

    channel: Mapped[str] = enum_column(server_default=text("'email'"))
    address: Mapped[str] = mapped_column(CITEXT, info={"audit": "flag"})
    reason: Mapped[str] = enum_column()
    detail: Mapped[str | None]
    last_failed_at: Mapped[datetime | None]
    released_at: Mapped[datetime | None]
    released_by_staff_user_id: Mapped[UUID | None]
    release_count: Mapped[int] = mapped_column(server_default=text("0"))
    is_permanent: Mapped[bool] = mapped_column(server_default=text("false"), info={"audit": "value"})


class DeviceRegistration(TenantOwned, Timestamps, Base):
    """A member device that can receive push (MKT-16); registered by the mobile app."""

    __tablename__ = "device_registration"
    __table_args__ = tenant_args(
        *tfk("client_id", "client", index=False),
        *tfk("location_id", "location", index=False),
        # One live registration per token; a revoked one stays as history when the phone changes hands (W2-08).
        Index("uq_device_registration_push_token", "tenant_id", "push_token", unique=True,
              postgresql_where=text("revoked_at IS NULL")),
        enum_check("platform", DevicePlatform),
        Index("ix_device_registration_client", "tenant_id", "client_id", postgresql_where=text("revoked_at IS NULL")),
        Index("ix_device_registration_location", "tenant_id", "location_id",
              postgresql_where=text("revoked_at IS NULL")),
    )  # fmt: skip

    identity_id: Mapped[UUID]
    client_id: Mapped[UUID]
    location_id: Mapped[UUID | None]
    platform: Mapped[str] = enum_column()
    push_token: Mapped[str] = mapped_column(info={"audit": "never"})
    is_push_enabled: Mapped[bool] = mapped_column(server_default=text("true"), info={"audit": "value"})
    app_version: Mapped[str | None]
    last_active_at: Mapped[datetime] = mapped_column(server_default=func.now())
    revoked_at: Mapped[datetime | None]


class InboxItem(TenantOwned, Timestamps, Base):
    """One announcement or notice in one member's in-app inbox, with its read state (MKT-16)."""

    __tablename__ = "inbox_item"
    __table_args__ = tenant_args(
        *tfk("location_id", "location"),
        *tfk("client_id", "client", index=False),
        *tfk("campaign_id", "campaign", ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "campaign_id", "client_id", name="uq_inbox_item_campaign_client"),
        Index("ix_inbox_item_client", "tenant_id", "client_id", text("published_at DESC"), "id"),
    )

    location_id: Mapped[UUID]
    client_id: Mapped[UUID]
    campaign_id: Mapped[UUID | None]
    title: Mapped[str]
    body_text: Mapped[str]
    link_url: Mapped[str | None]
    published_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime]
    read_at: Mapped[datetime | None]
    recalled_at: Mapped[datetime | None]


class ReminderRule(TenantOwned, Timestamps, Base):
    """Session and appointment reminders for one location: at most two offsets (MKT-13)."""

    __tablename__ = "reminder_rule"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        UniqueConstraint("tenant_id", "location_id", name="uq_reminder_rule_location"),
        CheckConstraint("first_offset_minutes BETWEEN 15 AND 20160", name="first_offset"),
        CheckConstraint("second_offset_minutes IS NULL OR second_offset_minutes BETWEEN 15 AND 20160",
                        name="second_offset"),
        CheckConstraint("second_offset_minutes IS NULL OR second_offset_minutes <> first_offset_minutes",
                        name="distinct_offsets"),
    )  # fmt: skip

    location_id: Mapped[UUID]
    is_enabled: Mapped[bool] = mapped_column(server_default=text("true"), info={"audit": "value"})
    first_offset_minutes: Mapped[int] = mapped_column(info={"audit": "value"})
    second_offset_minutes: Mapped[int | None] = mapped_column(info={"audit": "value"})


class AutomationRule(TenantOwned, Timestamps, Base):
    """An event-triggered send with a delay and exit events (MKT-20); also how built-in notices such as the
    waitlist-promotion email are expressed, so a tenant can retime or switch them off."""

    __tablename__ = "automation_rule"
    __table_args__ = tenant_args(
        *tfk("location_id", "location"),
        *tfk("message_template_id", "message_template"),
        enum_check("channel", MessageChannel),
        CheckConstraint("delay_minutes >= 0", name="delay"),
        Index("ix_automation_rule_trigger", "tenant_id", "trigger_event_type", postgresql_where=text("is_enabled")),
        Index("uq_automation_rule_system", "tenant_id", "trigger_event_type", unique=True,
              postgresql_where=text("is_system")),
    )  # fmt: skip

    name: Mapped[str]
    location_id: Mapped[UUID | None]
    trigger_event_type: Mapped[str] = mapped_column(info={"audit": "value"})
    conditions: Mapped[dict] = mapped_column(JsonDict, server_default=text("'{}'"))
    delay_minutes: Mapped[int] = mapped_column(server_default=text("0"), info={"audit": "value"})
    channel: Mapped[str] = enum_column(server_default=text("'email'"))
    message_template_id: Mapped[UUID]
    topic: Mapped[str | None] = mapped_column(info={"audit": "value"})
    exit_event_types: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    is_system: Mapped[bool] = mapped_column(server_default=text("false"), info={"audit": "value"})
    is_enabled: Mapped[bool] = mapped_column(server_default=text("true"), info={"audit": "value"})


class ScheduledNotification(TenantOwned, Timestamps, Base):
    """The materialised send queue for reminders and delayed automations; the per-minute job sends due rows."""

    __tablename__ = "scheduled_notification"
    __table_args__ = tenant_args(
        *tfk("location_id", "location"),
        *tfk("automation_rule_id", "automation_rule", ondelete="CASCADE"),
        *tfk("client_id", "client", index=False),
        *tfk("message_id", "message"),
        enum_check("kind", NotificationKind),
        enum_check("status", NotificationStatus),
        UniqueConstraint("tenant_id", "dedupe_key", name="uq_scheduled_notification_dedupe"),
        Index("ix_scheduled_notification_due", "send_at", postgresql_where=text("status = 'scheduled'")),
        Index("ix_scheduled_notification_subject", "tenant_id", "subject_type", "subject_id"),
        Index("ix_scheduled_notification_client", "tenant_id", "client_id", postgresql_where=text("status = 'scheduled'")),
    )  # fmt: skip

    location_id: Mapped[UUID | None]
    kind: Mapped[str] = enum_column()
    automation_rule_id: Mapped[UUID | None]
    reminder_no: Mapped[int | None]
    subject_type: Mapped[str] = mapped_column(info={"audit": "value"})
    subject_id: Mapped[UUID]
    client_id: Mapped[UUID]
    subject_starts_at: Mapped[datetime | None]
    payload: Mapped[dict] = mapped_column(JsonDict, server_default=text("'{}'"))
    send_at: Mapped[datetime]
    status: Mapped[str] = enum_column(server_default=text("'scheduled'"))
    dedupe_key: Mapped[str] = mapped_column(info={"audit": "value"})
    message_id: Mapped[UUID | None]


class NotificationRoute(TenantOwned, Timestamps, Base):
    """Where one kind of staff-facing alert goes at one location (MKT-14)."""

    __tablename__ = "notification_route"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        UniqueConstraint("tenant_id", "location_id", "alert_kind", name="uq_notification_route_location_kind"),
        enum_check("alert_kind", AlertKind),
    )

    location_id: Mapped[UUID]
    alert_kind: Mapped[str] = enum_column()
    is_enabled: Mapped[bool] = mapped_column(server_default=text("true"), info={"audit": "value"})
    staff_user_ids: Mapped[list[UUID]] = mapped_column(ARRAY(PgUUID(as_uuid=True)), server_default=text("'{}'"))
    emails: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))  # stored lower-case


class PortalSettings(TenantOwned, Timestamps, Base):
    """Member-portal switches and content for one location (SSP-01, SSP-14)."""

    __tablename__ = "portal_settings"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        UniqueConstraint("tenant_id", "location_id", name="uq_portal_settings_location"),
        Index("uq_portal_settings_slug", "tenant_id", text("lower(slug)"), unique=True),
        CheckConstraint("slug ~ '^[a-z0-9][a-z0-9-]{1,62}$'", name="slug"),
    )

    location_id: Mapped[UUID]
    is_enabled: Mapped[bool] = mapped_column(server_default=text("true"), info={"audit": "value"})
    is_public: Mapped[bool] = mapped_column(server_default=text("true"), info={"audit": "value"})
    slug: Mapped[str] = mapped_column(info={"audit": "value"})
    welcome_text: Mapped[str | None]
    terms_text: Mapped[str | None]
    terms_version: Mapped[int] = mapped_column(server_default=text("1"), info={"audit": "value"})
    allows_online_rentals: Mapped[bool] = mapped_column(server_default=text("true"), info={"audit": "value"})
    allows_online_purchases: Mapped[bool] = mapped_column(server_default=text("true"), info={"audit": "value"})


class Video(TenantOwned, Timestamps, Base):
    """A video in the member portal's library (SSP-16): a link to an allow-listed host, shown embedded."""

    __tablename__ = "video"
    __table_args__ = tenant_args(*tfk("location_id", "location"))

    location_id: Mapped[UUID]
    title: Mapped[str]
    description: Mapped[str | None]
    url: Mapped[str]
    is_published: Mapped[bool] = mapped_column(server_default=text("true"), info={"audit": "value"})
    sort_order: Mapped[int] = mapped_column(server_default=text("0"))
