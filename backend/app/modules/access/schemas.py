"""Request and response models for check-in, credentials and kiosks (docs/api/openapi-money.yaml, tag access).

Portal app-card models and kiosk models are their own classes: the kiosk sees first names and alert codes only,
never amounts, plan names or staff notes (security-baseline 17.1)."""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

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


class AccessEvaluateRequest(In):
    client_id: UUID | None = None
    credential_value: Value | None = None
    location_id: UUID


class CheckInAlertOut(Out):
    code: Code


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


class AccessSettingsWrite(In):
    hidden_detail_fields: list[DetailField] | None = None
    staff_early_minutes: int | None = Field(None, ge=0, le=1440)
    staff_late_minutes: int | None = Field(None, ge=0, le=1440)


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
