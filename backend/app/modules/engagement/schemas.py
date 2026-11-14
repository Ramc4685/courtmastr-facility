"""engagement request and response models: communication preferences (CLI-16)."""

from datetime import date, datetime
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
    hold_reason: str | None = None
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


SocialNetwork = Literal["facebook", "instagram", "x", "youtube", "tiktok", "linkedin"]
HttpsUrl = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500, pattern=r"^https://[^\s]+$")]
Host = Annotated[
    str, StringConstraints(strip_whitespace=True, to_lower=True, max_length=253, pattern=r"^[a-z0-9.-]+\.[a-z]{2,}$")
]


class PortalMenuItem(In):
    """One portal section (SSP-13): shown or hidden, in list order, optionally renamed."""

    key: Annotated[str, StringConstraints(pattern=r"^[a-z_]{1,30}$")]
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)] | None = None
    is_visible: bool = True


class PortalMenuItemOut(Out):
    key: str
    label: str | None
    is_visible: bool


class PublicMenuItem(PortalMenuItemOut):
    """The same item on the public side: portal routes never share a staff model (test_portal_schemas)."""


class PortalSettingsOut(Out):
    location_id: UUID
    is_enabled: bool
    is_public: bool
    slug: str
    welcome_text: str | None
    allows_online_purchases: bool
    allows_self_signup: bool
    menu: list[PortalMenuItemOut]
    social_links: dict[str, str]
    redirect_url: str | None
    group_redirect_urls: dict[str, str]
    redirect_domains: list[str]


class PortalSettingsUpdate(In):
    is_enabled: bool | None = None
    is_public: bool | None = None
    slug: Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")] | None = None
    welcome_text: Annotated[str, StringConstraints(max_length=4000)] | None = None
    allows_online_purchases: bool | None = None
    allows_self_signup: bool | None = None  # SSP-05: off by default
    menu: Annotated[list[PortalMenuItem], Field(max_length=30)] | None = None
    social_links: dict[SocialNetwork, HttpsUrl] | None = None
    redirect_url: HttpsUrl | None = None  # SSP-07: after a successful checkout or sign-up; null clears
    group_redirect_urls: Annotated[dict[UUID, HttpsUrl], Field(max_length=200)] | None = None
    redirect_domains: Annotated[list[Host], Field(max_length=20)] | None = None


class PublicPortalLocation(Out):
    location_id: UUID
    name: str
    slug: str
    time_zone: str  # IANA; wall times on public pages are shown in it
    welcome_text: str | None
    allows_online_purchases: bool
    allows_self_signup: bool
    menu: list[PublicMenuItem]
    social_links: dict[str, str]
    redirect_url: str | None  # re-checked against the allow-list on every read
    group_redirect_urls: dict[str, str]


class PublicPortalConfig(Out):
    facility_name: str
    tenant_slug: str
    currency: str  # ISO 4217; public prices are shown in it
    locations: list[PublicPortalLocation]


class PortalSignupIn(In):
    """Public self-registration (SSP-05). The answer is the same whether or not the address is known."""

    location_id: UUID
    email: Email
    first_name: Name
    last_name: Name
    phone_mobile: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] | None = None
    birth_on: date  # required: the first entry code waits for staff to confirm it once (owner, 2026-11-13)
    birth_on_declared: Literal[True]  # the person declares the birth date is true


class PortalSignupConfirmIn(In):
    token: Annotated[str, StringConstraints(min_length=10, max_length=200)]
    client_kind: Literal["web", "mobile"] = "web"


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


class PortalSignupSession(Out):
    """The confirm answer, in the portal's own shape: `signed_in` (web: the session cookie is set and the CSRF
    token is here; mobile: the tokens are here) or `mfa_required` (202, finish with the MFA verify route)."""

    status: Literal["signed_in", "mfa_required"]
    csrf_token: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    mfa_token: str | None = None
    expires_at: datetime | None = None


# --- member app configuration (APP-01, APP-02, APP-04, APP-05, APP-18) ----------------------------------------


class AppTheme(Out):
    """The tenant brand colours (platform branding), as the app reads them."""

    primary: str | None = None
    accent: str | None = None


class AppTile(In):
    type: Annotated[str, StringConstraints(max_length=32)]
    caption: Annotated[str, StringConstraints(max_length=40)] | None = None
    style: Literal["large", "small"] = "small"


class AppDesign(In):
    columns: Literal[1, 2] = 2
    corners: Literal["rounded", "square"] = "rounded"


class AppHomeScreen(In):
    """APP-04: ordered tiles from the tile catalogue (`tile_types`) and the global design."""

    tiles: Annotated[list[AppTile], Field(max_length=12)] = []
    design: AppDesign = AppDesign()


class AppSchedule(In):
    """APP-18: narrows each session booking policy in the member listing; never loosens it."""

    shows_spots_left: bool = True
    shows_full_sessions: bool = True
    days_ahead: Annotated[int, Field(ge=1, le=365)] | None = None


class AppFeatures(In):
    booking: bool = True
    purchases: bool = True
    membership_card: bool = True
    wallet_pass: bool = True


class AppConfigReplace(In):
    """PUT replaces: an omitted field returns to its default."""

    mode: Literal["shared", "branded"] = "shared"
    is_enabled: bool = False
    app_name: Annotated[str, StringConstraints(max_length=60)] | None = None
    is_listed_in_directory: bool = False
    directory_name: Annotated[str, StringConstraints(max_length=80)] | None = None
    card_number_mode: Literal["auto_generate", "manual_entry"] = "auto_generate"
    features: AppFeatures = AppFeatures()
    home_screen: AppHomeScreen | None = None
    schedule: AppSchedule = AppSchedule()


class AppConfigOut(Out):
    mode: str
    is_enabled: bool
    app_name: str | None
    is_listed_in_directory: bool
    directory_name: str | None
    card_number_mode: str
    features: AppFeatures
    home_screen: AppHomeScreen | None
    schedule: AppSchedule
    tile_types: list[str]
    updated_at: datetime | None


class PublicAppTile(Out):
    type: str
    caption: str | None = None
    style: str


class PublicAppDesign(Out):
    columns: int
    corners: str


class PublicAppHomeScreen(Out):
    tiles: list[PublicAppTile]
    design: PublicAppDesign


class PublicAppSchedule(Out):
    shows_spots_left: bool
    shows_full_sessions: bool
    days_ahead: int | None = None


class PublicAppFeatures(Out):
    booking: bool
    purchases: bool
    membership_card: bool
    wallet_pass: bool


class PublicAppConfig(Out):
    """The public answer has its own models: it never reuses the staff config shapes."""

    app_name: str
    theme: AppTheme
    icon_url: str | None
    features: PublicAppFeatures
    home_screen: PublicAppHomeScreen | None
    schedule: PublicAppSchedule
    portal: PublicPortalConfig


class AppDirectoryEntry(Out):
    slug: str  # the app opens the facility by its slug (X-Tenant-Slug)
    name: str
    city: str | None
    icon_url: str | None


class AppDirectoryPage(Out):
    data: list[AppDirectoryEntry]


# --- Phase 11 C2: member app content (APP-07..APP-14) -------------------------------------------------------

AppContentKindValue = Literal["news", "info_page", "announcement", "promotion", "gallery"]
ContentTitle = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
ContentBody = Annotated[str, StringConstraints(max_length=10000)]
SortOrder = Annotated[int, Field(ge=0, le=10000)]
ContactKindValue = Literal["department", "service"]
ContactName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
ContactRole = Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)]
Phone = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
InquiryStatusValue = Literal["new", "in_progress", "closed", "converted"]


class AppContentOut(Out):
    id: UUID
    location_id: UUID | None
    kind: str
    title: str
    body_text: str
    link_url: str | None
    has_image: bool
    publish_at: datetime
    expires_at: datetime | None
    sort_order: int
    version: int
    created_at: datetime
    updated_at: datetime


class AppContentCreate(In):
    """Plain text with links: HTML is refused. `location_id` null shows the item at every location."""

    location_id: UUID | None = None
    kind: AppContentKindValue
    title: ContentTitle
    body_text: ContentBody = ""
    link_url: HttpsUrl | None = None
    publish_at: datetime
    expires_at: datetime | None = None
    sort_order: SortOrder = 0


class AppContentUpdate(In):
    kind: AppContentKindValue | None = None
    title: ContentTitle | None = None
    body_text: ContentBody | None = None
    link_url: HttpsUrl | None = None
    publish_at: datetime | None = None
    expires_at: datetime | None = None
    sort_order: SortOrder | None = None
    version: int | None = None


class LocationContactOut(Out):
    id: UUID
    location_id: UUID
    kind: str
    name: str
    role: str | None
    phone: str | None
    email: str | None
    sort_order: int


class LocationContactCreate(In):
    location_id: UUID
    kind: ContactKindValue
    name: ContactName
    role: ContactRole | None = None
    phone: Phone | None = None
    email: Email | None = None
    sort_order: SortOrder = 0


class LocationContactUpdate(In):
    kind: ContactKindValue | None = None
    name: ContactName | None = None
    role: ContactRole | None = None
    phone: Phone | None = None
    email: Email | None = None
    sort_order: SortOrder | None = None


class AppInquiryOut(Out):
    id: UUID
    location_id: UUID
    kind: str
    client_id: UUID | None
    contact_name: str
    contact_email: str | None
    contact_phone: str | None
    interest: str | None
    message: str
    rating: int | None
    status: str
    handled_at: datetime | None
    handled_by_staff_user_id: UUID | None
    created_at: datetime


class AppInquiryUpdate(In):
    status: InquiryStatusValue


# portal and public shapes for C2 (never the staff models above)


class PortalAppContent(Out):
    id: UUID
    location_id: UUID | None
    kind: str
    title: str
    body_text: str
    link_url: str | None
    has_image: bool
    publish_at: datetime
    expires_at: datetime | None
    sort_order: int


class PublicLocationContact(Out):
    id: UUID
    kind: str
    name: str
    role: str | None
    phone: str | None
    email: str | None


class PublicLocationContacts(Out):
    data: list[PublicLocationContact]


class PublicTrialRequestIn(In):
    """ "Try us" (APP-12). The answer is the same whether or not anything was stored."""

    location_id: UUID
    name: Name
    email: Email
    phone: Phone | None = None
    interest: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] | None = None
    message: Annotated[str, StringConstraints(max_length=2000)] | None = None


class PortalFeedbackIn(In):
    """In-app feedback (APP-10) for the signed-in client or one it may act for; goes to the staff inbox."""

    client_id: UUID
    location_id: UUID | None = None
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    rating: Annotated[int, Field(ge=1, le=5)] | None = None


class PortalFeedbackOut(Out):
    id: UUID


# --- Phase 11 C2 part 2: favourites (APP-13) and app usage counts (APP-17) ------------------------------------

FavoriteKindValue = Literal["reservation_type", "program_group"]
UsageKindValue = Literal["screen", "action"]


class PortalFavoriteIn(In):
    client_id: UUID
    kind: FavoriteKindValue
    target_id: UUID


class PortalFavorite(Out):
    id: UUID
    client_id: UUID
    kind: str
    target_id: UUID
    created_at: datetime


class PortalFavorites(Out):
    data: list[PortalFavorite]


class PortalFavoriteScheduleItem(Out):
    """A session from the portal listing that matches a favourite; `program_group_id` set when it came from one."""

    session_id: UUID
    location_id: UUID
    time_zone: str
    title: str | None
    starts_at: datetime
    ends_at: datetime
    spots_left: int | None
    is_bookable: bool
    can_join_waitlist: bool
    reason: str | None
    reservation_type_id: UUID | None
    program_group_id: UUID | None


class PortalFavoriteSchedule(Out):
    data: list[PortalFavoriteScheduleItem]


class PortalAppUsageItem(In):
    kind: UsageKindValue
    name: Annotated[str, StringConstraints(min_length=1, max_length=60, pattern=r"^[a-z0-9_.-]+$")]
    count: Annotated[int, Field(ge=1, le=100)]


class PortalAppUsageIn(In):
    """Anonymous counts from the member app; nothing about the sender is stored."""

    items: Annotated[list[PortalAppUsageItem], Field(min_length=1, max_length=50)]


class AppUsageDayOut(Out):
    day: date
    kind: str
    name: str
    count: int


class AppUsageDays(Out):
    data: list[AppUsageDayOut]
