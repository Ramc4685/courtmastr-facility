"""Request and response models for check-in, credentials and kiosks (docs/api/openapi-money.yaml, tag access).

Portal app-card models and kiosk models are their own classes: the kiosk sees first names and alert codes only,
never amounts, plan names or staff notes (security-baseline 17.1)."""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, StringConstraints

from app.core.schemas import In, Out, Page  # noqa: F401  (Page is used by the router as s.Page)

Value = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Pin = Annotated[str, StringConstraints(pattern=r"^[0-9]{6,8}$")]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Code = Literal[
    "client_disabled", "access_denied", "membership_suspended", "membership_frozen", "membership_expired",
    "visits_depleted", "balance_due", "waiver_unsigned", "payment_method_expired", "staff_note", "birthday",
    "photo_missing", "over_daily_limit",
]  # fmt: skip


# --- staff check-in ------------------------------------------------------------------------------------------


class CheckInCreate(In):
    client_id: UUID | None = None
    credential_value: Value | None = None
    location_id: UUID
    channel: Literal["staff_window", "client_profile", "pos", "api"]
    override: bool = False
    override_reason: Reason | None = None
    check_in_station_id: UUID | None = None


class AccessEvaluateRequest(In):
    client_id: UUID | None = None
    credential_value: Value | None = None
    location_id: UUID


class CheckInAlertOut(Out):
    code: Code
    action: Literal["take_payment", "renew_membership", "sign_waiver", "update_payment_method", "none"]


class StaffAlertOut(Out):
    severity: str
    message: str


class CheckInMembershipOut(Out):
    contract_id: UUID
    name: str | None
    status: str
    end_on: date | None
    visits_remaining_count: int | None


class CheckInClientOut(Out):
    """The status card at the front desk (CHK-01)."""

    client_id: UUID
    first_name: str
    last_name: str
    display_name: str
    member_number: str | None
    status: str
    is_waiver_on_file: bool
    balance_due_minor: int | None  # None without access.checkin.read_full_details
    membership: CheckInMembershipOut | None
    staff_alerts: list[StaffAlertOut]


class AttendedOut(Out):
    target_type: str
    target_id: UUID
    session_id: UUID | None
    was_auto_booked: bool


class CheckInOut(Out):
    id: UUID
    client_id: UUID
    location_id: UUID
    kiosk_device_id: UUID | None
    channel: str
    identified_by: str
    credential_id: UUID | None
    checked_in_at: datetime
    local_on: date
    result: str
    denial_reason: str | None
    override_by_staff_user_id: UUID | None
    override_reason: str | None
    membership_contract_id: UUID | None
    is_visit_consumed: bool
    alert_codes: list[str]
    attended: list[AttendedOut]
    check_in_station_id: UUID | None
    checked_out_at: datetime | None


class CheckInRowOut(CheckInOut):
    client_name: str


class CheckInResult(Out):
    check_in: CheckInOut
    alerts: list[CheckInAlertOut]
    client: CheckInClientOut


class AccessDecision(Out):
    client_id: UUID
    location_id: UUID
    would_grant: bool
    denial_reason: str | None
    membership_contract_id: UUID | None
    would_consume_visit: bool
    alerts: list[CheckInAlertOut]
    client: CheckInClientOut


# --- credentials ---------------------------------------------------------------------------------------------


class CredentialResolveRequest(In):
    value: Value


class CredentialMatch(Out):
    credential_id: UUID | None
    kind: str
    client_id: UUID
    display_name: str
    is_client_disabled: bool


class CredentialCreate(In):
    kind: Literal["barcode", "rfid"]
    value: Value | None = None
    generate: bool = False
    source: Literal["scanned", "typed"] | None = None


class CredentialOut(Out):
    id: UUID | None
    client_id: UUID
    kind: str
    value: str
    status: str
    source: str
    is_primary: bool
    device_label: str | None
    issued_at: datetime
    revoked_at: datetime | None


class CredentialRevokeAllRequest(In):
    kind: Literal["app_card"]


# --- kiosk settings and devices ------------------------------------------------------------------------------


class KioskSettingsOut(Out):
    location_id: UUID
    lookup_method: str
    early_window_minutes: int
    late_window_minutes: int
    welcome_message: str | None
    displayed_alert_codes: list[str]
    confirmation_timeout_seconds: int
    has_exit_pin: bool


class KioskSettingsWrite(In):
    lookup_method: Literal["name", "membership_number", "both"] | None = None
    early_window_minutes: int | None = Field(None, ge=0, le=1440)
    late_window_minutes: int | None = Field(None, ge=0, le=1440)
    welcome_message: Annotated[str, StringConstraints(max_length=500)] | None = None
    displayed_alert_codes: list[Code] | None = None
    confirmation_timeout_seconds: int | None = Field(None, ge=3, le=300)
    exit_pin: Pin | None = None  # write-only; stored as an argon2id hash


class KioskExitRequest(In):
    staff_pin: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=16)]


# --- access settings, rules, schedules (CHK-02, CHK-08, CHK-09, CHK-10) --------------------------------------

DetailField = Literal["balance_due", "membership_dates", "visit_counts", "staff_notes"]
Condition = Literal["frozen", "suspended", "depleted", "over_daily_limit"]
Wall = Annotated[str, StringConstraints(pattern=r"^(([01][0-9]|2[0-3]):[0-5][0-9]|24:00)$")]


class AccessSettingsOut(Out):
    location_id: UUID
    hidden_detail_fields: list[DetailField]
    staff_early_minutes: int
    staff_late_minutes: int
    entry_code_early_min: int
    entry_code_grace_min: int
    light_lead_in_min: int
    light_run_on_min: int
    requires_paid_entry: bool
    door_alert_bad_codes_per_hour: int


class AccessSettingsWrite(In):
    hidden_detail_fields: list[DetailField] | None = None
    staff_early_minutes: int | None = Field(None, ge=0, le=1440)
    staff_late_minutes: int | None = Field(None, ge=0, le=1440)
    entry_code_early_min: int | None = Field(None, ge=0, le=240)
    entry_code_grace_min: int | None = Field(None, ge=0, le=240)
    light_lead_in_min: int | None = Field(None, ge=0, le=120)
    light_run_on_min: int | None = Field(None, ge=0, le=120)
    requires_paid_entry: bool | None = None
    door_alert_bad_codes_per_hour: int | None = Field(None, ge=1, le=10000)


class AccessRuleIn(In):
    condition: Condition
    outcome: Literal["allow", "deny"]


class AccessRuleOut(Out):
    condition: Condition
    outcome: Literal["allow", "deny"]
    is_default: bool


class AccessRulesOut(Out):
    location_id: UUID
    rules: list[AccessRuleOut]


class AccessRulesWrite(In):
    rules: list[AccessRuleIn] = Field(max_length=4)


class ClientAccessOut(Out):
    client_id: UUID
    access_mode: Literal["normal", "always_admit", "always_deny"]


class ClientAccessWrite(In):
    access_mode: Literal["normal", "always_admit", "always_deny"]
    reason: Reason


class AccessScheduleRangeIn(In):
    weekday: int = Field(ge=1, le=7)
    starts_time: Wall
    ends_time: Wall


class AccessScheduleRangeOut(Out):
    weekday: int
    starts_time: str
    ends_time: str


class AccessScheduleCreate(In):
    name: Name
    is_active: bool = True
    ranges: list[AccessScheduleRangeIn] = Field(max_length=70)


class AccessScheduleUpdate(In):
    name: Name | None = None
    is_active: bool | None = None
    ranges: list[AccessScheduleRangeIn] | None = Field(None, max_length=70)


class AccessScheduleOut(Out):
    id: UUID
    name: str
    is_active: bool
    ranges: list[AccessScheduleRangeOut]


class MembershipTypeAccessWrite(In):
    access_schedule_id: UUID | None = None
    location_ids: list[UUID] = Field(default_factory=list, max_length=200)


class MembershipTypeAccessOut(Out):
    membership_type_id: UUID
    access_schedule_id: UUID | None
    location_ids: list[UUID]


class KioskDeviceCreate(In):
    location_id: UUID
    name: Name


class KioskDeviceOut(Out):
    id: UUID
    location_id: UUID
    name: str
    status: Literal["pending_pairing", "active", "revoked"]
    last_seen_at: datetime | None
    paired_at: datetime | None
    created_at: datetime


class KioskPairingCode(Out):
    kiosk_device_id: UUID
    pairing_code: str
    expires_at: datetime


# --- check-in desk: stations, check-out, occupancy, booking, ID cards (CHK-04, CHK-07, CHK-12, MEM-19) --------

CardField = Literal["name", "membership_number", "membership_type", "expires_on", "date_of_birth"]


class CheckInStationCreate(In):
    location_id: UUID
    name: Name
    is_active: bool = True


class CheckInStationUpdate(In):
    name: Name | None = None
    is_active: bool | None = None


class CheckInStationOut(Out):
    id: UUID
    location_id: UUID
    name: str
    is_active: bool


class CheckOutRequest(In):
    checked_out_at: AwareDatetime | None = None  # default now; between the check-in and now


class CheckInAttendanceCreate(In):
    session_id: UUID
    client_package_id: UUID | None = None


class OccupancyPersonOut(Out):
    check_in_id: UUID
    client_id: UUID
    client_name: str
    checked_in_at: datetime
    check_in_station_id: UUID | None
    station_name: str | None


class OccupancyStationOut(Out):
    check_in_station_id: UUID | None
    station_name: str | None
    count: int


class OccupancyOut(Out):
    location_id: UUID
    local_on: date
    count: int
    by_station: list[OccupancyStationOut]
    present: list[OccupancyPersonOut]  # the newest OCCUPANCY_LIMIT people in
    is_capped: bool  # true when count is larger than present


class IdCardTemplateCreate(In):
    location_id: UUID | None = None  # none: every location
    name: Name
    shown_fields: list[CardField] = Field(min_length=1, max_length=5)
    has_photo: bool = True
    is_default: bool = False


class IdCardTemplateUpdate(In):
    name: Name | None = None
    shown_fields: list[CardField] | None = Field(None, min_length=1, max_length=5)
    has_photo: bool | None = None
    is_default: bool | None = None


class IdCardTemplateOut(Out):
    id: UUID | None  # none: the built-in card
    location_id: UUID | None
    name: str
    shown_fields: list[CardField]
    has_photo: bool
    is_default: bool


class IdCardFieldOut(Out):
    field: CardField
    value: str | None


class ClientIdCardOut(Out):
    client_id: UUID
    template: IdCardTemplateOut
    fields: list[IdCardFieldOut]
    code_value: str | None
    photo_url: str | None


# --- the kiosk -----------------------------------------------------------------------------------------------


class KioskPairRequest(In):
    pairing_code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=4, max_length=16)]


class KioskConfig(Out):
    kiosk_device_id: UUID
    location_id: UUID
    location_name: str
    time_zone: str
    settings: KioskSettingsOut


class KioskLookupRequest(In):
    credential_value: Value | None = None
    last_name_prefix: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=60)] | None = (
        None
    )


class KioskMatch(Out):
    match_token: str
    first_name: str
    last_initial: str


class KioskLookupResult(Out):
    matches: list[KioskMatch]


class KioskCheckInCreate(In):
    match_token: Annotated[str, StringConstraints(max_length=200)] | None = None
    card_payload: Annotated[str, StringConstraints(max_length=200)] | None = None


class KioskAttendedOut(Out):
    target_type: str
    session_id: UUID | None


class KioskCheckInResult(Out):
    check_in_id: UUID
    status: Literal["admitted", "see_staff"]
    first_name: str
    displayed_alert_codes: list[str]
    attended: list[KioskAttendedOut]
    welcome_message: str | None


# --- portal app cards ----------------------------------------------------------------------------------------


class PortalAppCardCreate(In):
    client_id: UUID
    device_label: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None


class PortalAppCardIssued(Out):
    credential_id: UUID
    client_id: UUID
    device_label: str | None
    card_payload: str
    issued_at: datetime
    expires_at: datetime | None


class PortalAppCardOut(Out):
    credential_id: UUID
    client_id: UUID
    device_label: str | None
    issued_at: datetime


class PortalWalletPassCreate(In):
    client_id: UUID
    device_label: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None


class PortalWalletPassIssued(Out):
    """The pass document, returned once. `is_signed` is false while only the fake issuer exists (CHK-13 partial)."""

    credential_id: UUID
    client_id: UUID
    device_label: str | None
    issued_at: datetime
    format: str
    media_type: str
    content: str
    is_signed: bool


class PortalWalletPassOut(Out):
    credential_id: UUID
    client_id: UUID
    device_label: str | None
    issued_at: datetime


# --- building control (CHK-15, CHK-16) ------------------------------------------------------------------------

DeviceRef = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class DoorDeviceCreate(In):
    location_id: UUID
    name: Name
    device_ref: DeviceRef
    unlock_seconds: int = Field(5, ge=1, le=60)


class DoorDeviceUpdate(In):
    name: Name | None = None
    device_ref: DeviceRef | None = None
    unlock_seconds: int | None = Field(None, ge=1, le=60)
    is_active: bool | None = None


class DoorDeviceOut(Out):
    id: UUID
    location_id: UUID
    name: str
    device_ref: str
    unlock_seconds: int
    is_active: bool
    has_credential: bool
    last_seen_at: datetime | None
    created_at: datetime


class DoorDeviceIssued(DoorDeviceOut):
    credential: str  # shown once: the controller sends it as `Authorization: Bearer`


class DoorUnlockRequest(In):
    reason: Reason


class LightingZoneCreate(In):
    location_id: UUID
    name: Name
    zone_ref: DeviceRef
    resource_ids: list[UUID] = Field(min_length=1, max_length=50)


class LightingZoneUpdate(In):
    name: Name | None = None
    zone_ref: DeviceRef | None = None
    is_active: bool | None = None
    resource_ids: list[UUID] | None = Field(None, min_length=1, max_length=50)


class LightingZoneOut(Out):
    id: UUID
    location_id: UUID
    name: str
    zone_ref: str
    is_active: bool
    resource_ids: list[UUID]
    override_is_on: bool | None
    override_until_at: datetime | None
    commanded_is_on: bool | None
    commanded_at: datetime | None
    failure_count: int
    created_at: datetime


class LightingZoneOverride(In):
    is_on: bool | None  # null clears the override (back to the bookings)
    until_at: AwareDatetime | None = None
    reason: Reason | None = None  # required to hold a zone on or off
    confirm_in_progress: bool = False  # required to hold a zone off while a booking is in play on it


class BuildingEventOut(Out):
    id: UUID
    location_id: UUID
    occurred_at: datetime
    local_on: date
    kind: str
    door_device_id: UUID | None
    lighting_zone_id: UUID | None
    entry_code_id: UUID | None
    check_in_id: UUID | None
    staff_user_id: UUID | None
    detail: str | None
    created_at: datetime


class LightingZoneStatus(LightingZoneOut):
    should_be_on: bool
    reason: str  # override, booking:<number>, idle or inactive
    is_in_sync: bool  # the last command matches what should be on now


class BuildingStatusOut(Out):
    location_id: UUID
    as_of: datetime
    adapter: str
    zones: list[LightingZoneStatus]
    doors: list[DoorDeviceOut]


class DoorVerifyRequest(In):
    code: Annotated[str, StringConstraints(pattern=r"^[0-9]{4,12}$")]


class DoorVerifyResult(Out):
    result: Literal["allow", "deny"]
    unlock_seconds: int


class PortalEntryCodeOut(Out):
    booking_id: UUID
    location_id: UUID
    location_phone: str | None  # call it when the code fails: staff unlock remotely
    code: str
    valid_from_at: datetime
    valid_until_at: datetime
    is_open_now: bool


class PortalDoorUnlockResult(Out):
    result: Literal["allow"]
    occurred_at: datetime
