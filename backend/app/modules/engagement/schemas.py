"""engagement request and response models: communication preferences (CLI-16)."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.core.schemas import In, Out, Page  # noqa: F401  (router uses s.Page)

ChannelValue = Literal["email", "sms", "push"]
TopicValue = Literal[
    "session_reminders", "card_expiration", "email_campaigns", "sms_marketing", "push_announcements", "league_alerts"
]


class PreferenceOut(Out):
    channel: str
    address: str | None
    topic: str
    is_subscribed: bool
    is_default: bool
    source: str | None
    changed_at: datetime | None


class Preferences(Out):
    data: list[PreferenceOut]


class PreferenceChange(In):
    channel: ChannelValue
    address: Annotated[str, StringConstraints(max_length=254)] | None = None  # email address or E.164 number
    topic: TopicValue
    is_subscribed: bool


class PreferencesReplace(In):
    """Staff changes record how the client gave consent (basis) and a note; the portal records `express`."""

    changes: Annotated[list[PreferenceChange], Field(min_length=1, max_length=60)]
    basis: Literal["express", "express_written", "express_verbal", "implied_purchase", "implied_inquiry"] = "express"
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)] | None = None


class PortalPreferencesReplace(In):
    changes: Annotated[list[PreferenceChange], Field(min_length=1, max_length=60)]


class ClientRef(Out):
    client_id: UUID


# --- module 14: messaging, inbox, reminders, automations, portal settings, videos -----------------------------

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Subject = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Body = Annotated[str, StringConstraints(min_length=1, max_length=20000)]
Url = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
Email = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+$")
]
MessageChannelValue = Literal["email", "push"]
CategoryValue = Literal["marketing", "transactional", "operational"]


class MessageTemplateOut(Out):
    id: UUID
    channel: str
    origin: str
    system_key: str | None
    name: str
    category: str | None
    subject: str | None
    body_text: str
    copied_from_id: UUID | None
    is_active: bool
    updated_at: datetime


class MessageTemplateCreate(In):
    name: Name
    channel: MessageChannelValue | None = None
    category: CategoryValue | None = None
    subject: Subject | None = None
    body_text: Body | None = None
    copied_from_id: UUID | None = None


class MessageTemplateUpdate(In):
    name: Name | None = None
    category: CategoryValue | None = None
    subject: Subject | None = None
    body_text: Body | None = None
    is_active: bool | None = None


class AudienceSource(In):
    kind: Literal["all_clients", "client_ids", "tag"]
    ids: Annotated[list[UUID], Field(max_length=5000)] | None = None


class AudienceFilter(In):
    kind: Literal["member", "birth_month", "gender", "age_range", "home_location"]
    negate: bool = False
    is_member: bool | None = None
    months: list[Annotated[int, Field(ge=1, le=12)]] | None = None
    values: list[str] | None = None
    min: Annotated[int, Field(ge=0, le=130)] | None = None
    max: Annotated[int, Field(ge=0, le=130)] | None = None
    include_unknown: bool | None = None
    ids: list[UUID] | None = None


class AudienceDefinition(In):
    sources: Annotated[list[AudienceSource], Field(min_length=1, max_length=20)]
    filters: Annotated[list[AudienceFilter], Field(max_length=20)] = []


class SegmentOut(Out):
    id: UUID
    name: str
    is_builtin: bool
    definition: dict
    last_count: int | None
    last_counted_at: datetime | None


class SegmentCreate(In):
    name: Name
    definition: AudienceDefinition


class SegmentUpdate(In):
    name: Name | None = None
    definition: AudienceDefinition | None = None


class SegmentPreviewIn(In):
    location_id: UUID
    segment_id: UUID | None = None
    definition: AudienceDefinition | None = None


class AudienceSampleItem(Out):
    client_id: UUID
    name: str


class SegmentPreviewOut(Out):
    count: int
    with_email_count: int
    sample: list[AudienceSampleItem]


class CampaignOut(Out):
    id: UUID
    location_id: UUID
    channel: str
    name: str
    subject: str | None
    body_text: str | None
    link_url: str | None
    message_template_id: UUID | None
    segment_id: UUID | None
    audience: dict | None
    status: str
    scheduled_at: datetime | None
    started_at: datetime | None
    sent_at: datetime | None
    recalled_at: datetime | None
    attempted_count: int
    sent_count: int
    inbox_count: int
    created_at: datetime


class CampaignCreate(In):
    location_id: UUID
    channel: MessageChannelValue = "email"
    name: Name
    subject: Subject | None = None
    body_text: Body | None = None
    link_url: Url | None = None
    message_template_id: UUID | None = None
    segment_id: UUID | None = None
    audience: AudienceDefinition | None = None


class CampaignUpdate(In):
    name: Name | None = None
    subject: Subject | None = None
    body_text: Body | None = None
    link_url: Url | None = None
    segment_id: UUID | None = None
    audience: AudienceDefinition | None = None


class CampaignSchedule(In):
    scheduled_at: datetime


class CampaignStatsOut(Out):
    campaign_id: UUID
    by_status: dict[str, int]
    attempted_count: int
    duplicate_count: int
    invalid_count: int
    unverified_count: int
    unsubscribed_skip_count: int
    suppressed_count: int
    sent_count: int
    delivered_count: int
    opened_count: int
    clicked_count: int
    bounced_count: int
    complaint_count: int
    unsubscribed_count: int
    inbox_count: int


class MessageOut(Out):
    """The delivery log. Bodies are kept only for direct messages; recipients' addresses are shown to staff."""

    id: UUID
    channel: str
    category: str
    topic: str | None
    client_id: UUID | None
    to_address: str | None
    campaign_id: UUID | None
    location_id: UUID | None
    subject: str | None
    body_text: str | None
    status: str
    skip_reason: str | None
    queued_at: datetime
    sent_at: datetime | None


class DirectMessageCreate(In):
    client_id: UUID
    location_id: UUID | None = None
    message_template_id: UUID | None = None
    subject: Subject | None = None
    body_text: Body | None = None


class SuppressionOut(Out):
    id: UUID
    channel: str
    address: str
    reason: str
    is_permanent: bool
    released_at: datetime | None
    release_count: int
    created_at: datetime


class SuppressionCreate(In):
    address: Email
    detail: Annotated[str, StringConstraints(max_length=500)] | None = None


class ReminderRuleOut(Out):
    id: UUID
    location_id: UUID
    is_enabled: bool
    first_offset_minutes: int
    second_offset_minutes: int | None


class ReminderRuleCreate(In):
    location_id: UUID
    is_enabled: bool = True
    first_offset_minutes: Annotated[int, Field(ge=15, le=20160)] = 1440
    second_offset_minutes: Annotated[int, Field(ge=15, le=20160)] | None = None


class ReminderRuleUpdate(In):
    is_enabled: bool | None = None
    first_offset_minutes: Annotated[int, Field(ge=15, le=20160)] | None = None
    second_offset_minutes: Annotated[int, Field(ge=15, le=20160)] | None = None


class AutomationRuleOut(Out):
    id: UUID
    name: str
    location_id: UUID | None
    trigger_event_type: str
    conditions: dict | None
    delay_minutes: int
    channel: str
    message_template_id: UUID
    topic: str | None
    exit_event_types: list[str]
    is_system: bool
    is_enabled: bool


class AutomationRuleCreate(In):
    name: Name
    location_id: UUID | None = None
    trigger_event_type: Annotated[str, StringConstraints(max_length=80)]
    conditions: dict[str, str] | None = None
    delay_minutes: Annotated[int, Field(ge=0, le=525600)] = 0
    channel: MessageChannelValue = "email"
    message_template_id: UUID
    topic: TopicValue | None = None
    exit_event_types: Annotated[list[str], Field(max_length=10)] = []
    is_enabled: bool = True


class AutomationRuleUpdate(In):
    name: Name | None = None
    conditions: dict[str, str] | None = None
    delay_minutes: Annotated[int, Field(ge=0, le=525600)] | None = None
    message_template_id: UUID | None = None
    topic: TopicValue | None = None
    exit_event_types: Annotated[list[str], Field(max_length=10)] | None = None
    is_enabled: bool | None = None


AlertKindValue = Literal[
    "payment_declined", "portal_action", "instant_booking", "online_registration", "waitlist_promoted"
]


class NotificationRouteOut(Out):
    id: UUID
    location_id: UUID
    alert_kind: str
    is_enabled: bool
    staff_user_ids: list[UUID]
    emails: list[str]


class NotificationRouteCreate(In):
    location_id: UUID
    alert_kind: AlertKindValue
    is_enabled: bool = True
    staff_user_ids: Annotated[list[UUID], Field(max_length=50)] = []
    emails: Annotated[list[Email], Field(max_length=20)] = []


class NotificationRouteUpdate(In):
    is_enabled: bool | None = None
    staff_user_ids: Annotated[list[UUID], Field(max_length=50)] | None = None
    emails: Annotated[list[Email], Field(max_length=20)] | None = None


class PortalSettingsOut(Out):
    location_id: UUID
    is_enabled: bool
    is_public: bool
    slug: str
    welcome_text: str | None
    terms_text: str | None
    terms_version: int | None
    allows_online_rentals: bool
    allows_online_purchases: bool


class PortalSettingsUpdate(In):
    is_enabled: bool | None = None
    is_public: bool | None = None
    slug: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")] | None = None
    welcome_text: Annotated[str, StringConstraints(max_length=4000)] | None = None
    terms_text: Annotated[str, StringConstraints(max_length=20000)] | None = None
    allows_online_rentals: bool | None = None
    allows_online_purchases: bool | None = None


class PublicPortalLocation(Out):
    location_id: UUID
    name: str
    slug: str
    welcome_text: str | None
    terms_text: str | None
    terms_version: int
    allows_online_rentals: bool
    allows_online_purchases: bool


class PublicPortalConfig(Out):
    facility_name: str
    locations: list[PublicPortalLocation]


class VideoOut(Out):
    id: UUID
    location_id: UUID
    title: str
    description: str | None
    url: str
    is_published: bool
    sort_order: int


class VideoCreate(In):
    location_id: UUID
    title: Name
    description: Annotated[str, StringConstraints(max_length=2000)] | None = None
    url: Url
    is_published: bool = False
    sort_order: Annotated[int, Field(ge=0, le=10000)] = 0


class VideoUpdate(In):
    title: Name | None = None
    description: Annotated[str, StringConstraints(max_length=2000)] | None = None
    url: Url | None = None
    is_published: bool | None = None
    sort_order: Annotated[int, Field(ge=0, le=10000)] | None = None


# --- portal and public shapes (never the staff models above) ---


class PortalInboxItem(Out):
    """Matches the mobile adapter's InboxItem: body and created_at are the published text and time."""

    id: UUID
    campaign_id: UUID | None
    title: str
    body: str
    link_url: str | None
    read_at: datetime | None
    created_at: datetime


class PortalUnreadCount(Out):
    unread: int


class PortalDeviceIn(In):
    platform: Literal["ios", "android"]
    push_token: Annotated[str, StringConstraints(min_length=8, max_length=4096)]
    location_id: UUID | None = None
    app_version: Annotated[str, StringConstraints(max_length=40)] | None = None
    locale: Annotated[str, StringConstraints(max_length=20)] | None = None
    is_push_enabled: bool = True


class PortalDeviceOut(Out):
    id: UUID
    platform: str
    is_push_enabled: bool
    last_active_at: datetime | None


class PortalVideo(Out):
    id: UUID
    location_id: UUID
    title: str
    description: str | None
    url: str


class UnsubscribeTokenIn(In):
    token: Annotated[str, StringConstraints(min_length=10, max_length=200)]


class UnsubscribeOut(Out):
    topic: str
    unsubscribed: bool
    changed: bool


class PublicPreferenceItem(Out):
    channel: str
    address: str | None
    topic: str
    is_subscribed: bool


class PublicPreferencesOut(Out):
    facility_name: str
    address: str
    data: list[PublicPreferenceItem]


class PublicPreferencesReplace(In):
    token: Annotated[str, StringConstraints(min_length=10, max_length=200)]
    changes: Annotated[list[PreferenceChange], Field(min_length=1, max_length=20)]
