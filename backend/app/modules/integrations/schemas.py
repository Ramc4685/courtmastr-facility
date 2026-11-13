"""Request and response models for the integrations API (docs/api/openapi-programs.yaml, tag integrations).
Secrets appear only in the *Created / *SecretOut responses, once; list and get responses never carry them."""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.core.schemas import In, Out, Page  # noqa: F401  (Page is used by the router as s.Page)

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Url = Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=2000)]
Scope = Annotated[str, StringConstraints(pattern=r"^[a-z_]+\.[a-z_]+\.[a-z_]+$", max_length=100)]
EventTypeName = Annotated[str, StringConstraints(pattern=r"^(\*|[a-z_]+\.[a-z_]+\.[a-z_]+)$", max_length=100)]


class ApiKeyCreate(In):
    name: Name
    scopes: list[Scope] = Field(min_length=1, max_length=200)
    location_ids: list[UUID] | None = Field(None, max_length=500, description="Omit for every location")
    expires_at: datetime | None = None
    confirm_sensitive_scopes: bool = Field(False, description="Required for scopes that move money or set prices")


class ApiKeyRotate(In):
    grace_minutes: int = Field(1440, ge=0, le=10080, description="How long the old secret keeps working")


class ApiKeyOut(Out):
    id: UUID
    name: str
    key_prefix: str
    scopes: list[str]
    location_ids: list[UUID] | None
    status: Literal["active", "revoked"]
    expires_at: datetime | None
    last_used_at: datetime | None
    rotated_at: datetime | None
    previous_valid_until: datetime | None
    revoked_at: datetime | None
    created_by_staff_user_id: UUID
    created_at: datetime


class ApiKeyCreated(ApiKeyOut):
    secret: str = Field(description="Shown once. Send it as `Authorization: Bearer <secret>`.")


class WebhookEventTypeOut(Out):
    type: str
    context: str
    description: str
    required_permission: str | None
    allowed: bool = Field(description="Whether the caller may subscribe to it")


class WebhookEndpointCreate(In):
    url: Url
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None
    event_types: list[EventTypeName] = Field(min_length=1, max_length=100, description='`["*"]` for every type')


class WebhookEndpointUpdate(In):
    url: Url | None = None
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None
    event_types: list[EventTypeName] | None = Field(None, min_length=1, max_length=100)
    status: Literal["active", "paused"] | None = None


class WebhookEndpointOut(Out):
    id: UUID
    url: str
    description: str | None
    event_types: list[str]
    status: Literal["active", "paused", "disabled"]
    failure_count: int
    last_success_at: datetime | None
    disabled_at: datetime | None
    disabled_reason: str | None
    previous_secret_expires_at: datetime | None
    created_by_staff_user_id: UUID
    created_at: datetime


class WebhookEndpointSecretOut(WebhookEndpointOut):
    secret: str = Field(description="Shown once. Verify FH-Signature with it.")


class WebhookDeliveryOut(Out):
    id: UUID
    webhook_endpoint_id: UUID
    event_id: UUID
    event_type: str
    status: Literal["pending", "delivered", "failed", "abandoned"]
    attempt_count: int
    next_attempt_at: datetime | None
    last_response_status: int | None
    last_error: str | None
    last_duration_ms: int | None
    delivered_at: datetime | None
    created_at: datetime


class WebhookDeliveryDetail(WebhookDeliveryOut):
    payload_preview: dict = Field(description="Ids, amounts and dates only; free text is redacted")


class ExternalConnectionCreate(In):
    provider: Literal["accounting_file", "quickbooks_online"]
    location_id: UUID | None = Field(None, description="Omit for every location")
    settings: dict[str, str | dict[str, str]] | None = Field(
        None, description="`account_map` (posting key -> account) and `default_income_account`"
    )
    return_url: Url | None = Field(None, description="QuickBooks: where the browser lands after authorising")


class ExternalConnectionOut(Out):
    id: UUID
    location_id: UUID | None
    provider: str
    status: Literal["pending", "active", "error", "disconnected"]
    external_account_id: str | None
    external_account_name: str | None
    connected_at: datetime | None
    last_sync_at: datetime | None
    last_error: str | None
    created_at: datetime


class ExternalConnectionCreated(ExternalConnectionOut):
    authorize_url: str | None = Field(None, description="QuickBooks: send the browser here to authorise")


class ExternalConnectionUpdate(In):
    settings: dict[str, str | bool | None] = Field(
        description="Merge-patch: default_income_account, sync_from, auto_sync; null removes a key"
    )


class SyncMappingIn(In):
    kind: Literal["ledger_account", "tender_account", "tax_account", "revenue_account", "revenue_class"]
    local_key: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    external_id: Annotated[str, StringConstraints(min_length=1, max_length=50)]
    external_name: Annotated[str, StringConstraints(max_length=200)] | None = None


class SyncMappingsIn(In):
    mappings: list[SyncMappingIn] = Field(max_length=500)


class SyncMappingsOut(Out):
    mappings: list[SyncMappingIn]
    unmapped: list[dict]
    external_options: dict


class SyncRun(In):
    from_: date | None = Field(None, alias="from")
    to: date | None = None
    location_id: UUID | None = Field(None, description="Required when the connection serves every location")
    retries_failed: bool = False


class OAuthCallbackIn(In):
    state: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    code: Annotated[str, StringConstraints(max_length=1000)] | None = None
    realm_id: Annotated[str, StringConstraints(max_length=50)] | None = None
    error: Annotated[str, StringConstraints(max_length=200)] | None = None


class OAuthCallbackOut(Out):
    external_connection_id: UUID
    status: Literal["connected", "error"]
    return_url: str


class InboundAck(Out):
    stored: int


class SyncRunOut(Out):
    status: str
    counts: dict[str, int]
    status_url: str


class AccountingExportRun(In):
    external_connection_id: UUID
    location_id: UUID
    business_on: date


class AccountingExportOut(Out):
    id: UUID
    external_connection_id: UUID
    location_id: UUID
    business_on: date
    status: Literal["pending", "posted", "completed_with_warnings", "failed", "skipped"]
    totals: dict
    external_id: str | None
    doc_number: str | None
    attempt_count: int
    last_error: str | None
    posted_at: datetime | None


class ApiOperationOut(Out):
    method: str
    path: str
    operation_id: str
    summary: str
    tag: str
    scopes: list[str] = Field(description="Any one of these on the key opens the operation")


class AdapterOut(Out):
    port: str
    label: str
    adapter: str | None
    status: Literal["connected", "simulated", "not_configured"]
    detail: str


class AdapterCommandOut(Out):
    id: UUID
    port: str
    adapter: str
    location_id: UUID | None
    command: str
    arguments: dict
    outcome: str
    occurred_at: datetime


# --- calendar feeds and the public schedule ----------------------------------------------------------------


class CalendarFeedCreate(In):
    kind: Literal["staff_schedule", "team_schedule"]
    name: Name
    location_id: UUID | None = Field(None, description="Staff feeds: only this location's bookings")
    competition_team_id: UUID | None = Field(None, description="Team feeds: the team")
    include_shifts: bool = Field(False, description="Staff feeds: add your published shifts")


class PortalCalendarFeedCreate(In):
    name: Name | None = None


class CalendarFeedUpdate(In):
    name: Name | None = None
    include_shifts: bool | None = None
    status: Literal["active", "disabled"] | None = Field(None, description="Re-enabling mints a new URL")


class CalendarFeedOut(Out):
    id: UUID
    kind: Literal["staff_schedule", "team_schedule", "member_schedule"]
    name: str
    status: Literal["active", "disabled"]
    owner_staff_user_id: UUID | None
    location_id: UUID | None
    competition_team_id: UUID | None
    include_shifts: bool
    last_fetched_at: datetime | None
    created_at: datetime


class CalendarFeedCreated(CalendarFeedOut):
    url_token: str | None = Field(description="Shown once: subscribe to /api/v1/public/calendar-feeds/{url_token}")


class PublicScheduleSettingsOut(Out):
    location_id: UUID
    is_enabled: bool
    days_ahead: int
    show_sessions: bool
    show_busy: bool


class PublicScheduleSettingsUpdate(In):
    location_id: UUID
    is_enabled: bool | None = None
    days_ahead: int | None = Field(None, ge=1, le=31)
    show_sessions: bool | None = None
    show_busy: bool | None = None


class PublicSessionOut(Out):
    starts_at: datetime
    ends_at: datetime
    title: str
    seats_left: int
    is_full: bool


class PublicBusyOut(Out):
    resource_id: UUID
    starts_at: datetime
    ends_at: datetime


class PublicScheduleOut(Out):
    location_id: UUID
    from_on: date
    to_on: date
    time_zone: str
    sessions: list[PublicSessionOut]
    busy: list[PublicBusyOut]
