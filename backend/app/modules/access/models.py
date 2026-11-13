"""access tables (docs/architecture/data-model-money.md section 3): the check-in log and its attendance marks,
credentials, kiosk devices and kiosk settings (module 10), and the access rules of Phase 10 chip B: check-in
settings, rule outcomes, client access mode, time-of-day schedules and membership-type access (CHK-02, CHK-08,
CHK-09, CHK-10), and the check-in desk of chip C: stations and check-out (CHK-07) and ID card templates (CHK-12,
MEM-19)."""

from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import ARRAY, CheckConstraint, Index, LargeBinary, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantOwned, Timestamps, WallTime, enum_check, enum_column, tenant_args, tfk


class CheckInChannel(StrEnum):
    STAFF_WINDOW = "staff_window"
    CLIENT_PROFILE = "client_profile"
    KIOSK = "kiosk"
    POS = "pos"
    DOOR = "door"
    API = "api"


class IdentifiedBy(StrEnum):
    CREDENTIAL = "credential"
    NAME_SEARCH = "name_search"
    CLIENT_RECORD = "client_record"


class CheckInResult(StrEnum):
    GRANTED = "granted"
    DENIED = "denied"
    GRANTED_OVERRIDE = "granted_override"


class CredentialKind(StrEnum):
    MEMBERSHIP_NUMBER = "membership_number"
    BARCODE = "barcode"
    APP_CARD = "app_card"
    WALLET_PASS = "wallet_pass"
    RFID = "rfid"
    BIOMETRIC_REF = "biometric_ref"


class CredentialStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"  # its window ended; the sealed copy is cleared


class CredentialSource(StrEnum):
    GENERATED = "generated"
    SCANNED = "scanned"
    TYPED = "typed"
    IMPORTED = "imported"
    APP_ISSUED = "app_issued"


class LookupMethod(StrEnum):
    NAME = "name"
    MEMBERSHIP_NUMBER = "membership_number"
    BOTH = "both"


class AccessCondition(StrEnum):
    """Membership states an access rule decides on (CHK-08); the evaluator's defaults apply without a row."""

    FROZEN = "frozen"
    SUSPENDED = "suspended"
    DEPLETED = "depleted"
    OVER_DAILY_LIMIT = "over_daily_limit"


class AccessOutcome(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


class AccessMode(StrEnum):
    NORMAL = "normal"
    ALWAYS_ADMIT = "always_admit"
    ALWAYS_DENY = "always_deny"


# Status-card fields a location may hide from staff without access.checkin.read_full_details (CHK-02).
DETAIL_FIELDS = ("balance_due", "membership_dates", "visit_counts", "staff_notes")
# What an ID card may print (CHK-12): a fixed list, so a template is data, never markup or CSS.
CARD_FIELDS = ("name", "membership_number", "membership_type", "expires_on", "date_of_birth")


class CheckIn(TenantOwned, Timestamps, Base):
    """One identification attempt for a known client, granted or denied. Written once."""

    __tablename__ = "check_in"
    __table_args__ = tenant_args(
        *tfk("client_id", "client", index=False),
        *tfk("location_id", "location", index=False),
        *tfk("kiosk_device_id", "kiosk_device"),
        *tfk("credential_id", "credential"),
        *tfk("override_by_staff_user_id", "staff_user"),
        *tfk("created_by_staff_user_id", "staff_user"),
        *tfk("membership_contract_id", "membership_contract"),
        enum_check("channel", CheckInChannel),
        enum_check("identified_by", IdentifiedBy),
        enum_check("result", CheckInResult),
        CheckConstraint("(result = 'granted') = (denial_reason IS NULL)", name="denial"),
        CheckConstraint("(result = 'granted_override') = (override_by_staff_user_id IS NOT NULL)", name="override"),
        CheckConstraint("NOT is_visit_consumed OR result <> 'denied'", name="visit"),
        CheckConstraint(
            "checked_out_at IS NULL OR (checked_out_at >= checked_in_at AND result <> 'denied')", name="out"
        ),
        *tfk("check_in_station_id", "check_in_station"),
        Index("ix_check_in_recent", "tenant_id", "location_id", text("checked_in_at DESC"), text("id DESC")),
        Index("ix_check_in_client", "tenant_id", "client_id", text("checked_in_at DESC")),
        Index(
            "ix_check_in_open",
            "tenant_id",
            "location_id",
            "local_on",
            postgresql_where=text("checked_out_at IS NULL AND result <> 'denied'"),
        ),  # fmt: skip
    )

    client_id: Mapped[UUID]
    location_id: Mapped[UUID]
    kiosk_device_id: Mapped[UUID | None]
    channel: Mapped[str] = enum_column()
    identified_by: Mapped[str] = enum_column()
    credential_id: Mapped[UUID | None]
    checked_in_at: Mapped[datetime]
    local_on: Mapped[date]
    result: Mapped[str] = enum_column()
    denial_reason: Mapped[str | None] = mapped_column(info={"audit": "value"})
    override_by_staff_user_id: Mapped[UUID | None]
    override_reason: Mapped[str | None]
    membership_contract_id: Mapped[UUID | None]
    is_visit_consumed: Mapped[bool] = mapped_column(server_default=text("false"))
    alert_codes: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"), info={"audit": "value"})
    created_by_staff_user_id: Mapped[UUID | None]
    check_in_station_id: Mapped[UUID | None]  # CHK-07: the station the staff window recorded
    checked_out_at: Mapped[datetime | None]  # CHK-07: null is "still in" for the check-in's own local day only


class CheckInStation(TenantOwned, Timestamps, Base):
    """A named check-in point at a location (CHK-07): the front desk, the pool door. Occupancy counts by it."""

    __tablename__ = "check_in_station"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        UniqueConstraint("tenant_id", "location_id", "name", name="uq_check_in_station_name"),
    )

    location_id: Mapped[UUID]
    name: Mapped[str] = mapped_column(info={"audit": "value"})
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class IdCardTemplate(TenantOwned, Timestamps, Base):
    """What a printed member card shows (CHK-12, MEM-19): fields from CARD_FIELDS, a photo slot or not. The browser
    lays it out; nothing per printed card is stored. A null location is every location."""

    __tablename__ = "id_card_template"
    __table_args__ = tenant_args(
        *tfk("location_id", "location"),
        CheckConstraint(
            "shown_fields <@ ARRAY[" + ", ".join(f"'{f}'" for f in CARD_FIELDS) + "]::text[]", name="shown_fields"
        ),
        Index(
            "uq_id_card_template_default",
            "tenant_id",
            "location_id",
            unique=True,
            postgresql_where=text("is_default"),
            postgresql_nulls_not_distinct=True,
        ),  # fmt: skip
    )

    location_id: Mapped[UUID | None]
    name: Mapped[str] = mapped_column(info={"audit": "value"})
    shown_fields: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{name,membership_number}'"), info={"audit": "value"}
    )
    has_photo: Mapped[bool] = mapped_column(server_default=text("true"))
    is_default: Mapped[bool] = mapped_column(server_default=text("false"))


class CheckInAttendance(TenantOwned, Timestamps, Base):
    """A session place marked attended by a check-in (target is a programs enrolment)."""

    __tablename__ = "check_in_attendance"
    __table_args__ = tenant_args(
        *tfk("check_in_id", "check_in", ondelete="CASCADE", index=False),
        UniqueConstraint("tenant_id", "check_in_id", "target_type", "target_id", name="uq_check_in_attendance"),
        CheckConstraint("target_type IN ('enrollment', 'booking')", name="target_type"),
    )

    check_in_id: Mapped[UUID]
    target_type: Mapped[str] = mapped_column(server_default=text("'enrollment'"))
    target_id: Mapped[UUID]
    session_id: Mapped[UUID | None]
    was_auto_booked: Mapped[bool] = mapped_column(server_default=text("false"))


class Credential(TenantOwned, Timestamps, Base):
    """Anything that resolves to a client at a scan. Active values are unique per tenant across all kinds."""

    __tablename__ = "credential"
    __table_args__ = tenant_args(
        *tfk("client_id", "client"),
        *tfk("revoked_by_staff_user_id", "staff_user"),
        enum_check("kind", CredentialKind),
        enum_check("status", CredentialStatus),
        enum_check("source", CredentialSource),
        # A live app card holds its secret; revoking it wipes the secret.
        CheckConstraint(
            "CASE WHEN kind = 'app_card' AND status = 'active' THEN secret_ciphertext IS NOT NULL"
            " WHEN kind = 'app_card' THEN true ELSE secret_ciphertext IS NULL END",
            name="secret",
        ),
        CheckConstraint("(status = 'revoked') = (revoked_at IS NOT NULL)", name="revoked"),
        Index("uq_credential_value", "tenant_id", "value", unique=True, postgresql_where=text("status = 'active'")),
    )

    client_id: Mapped[UUID]
    kind: Mapped[str] = enum_column()
    value: Mapped[str] = mapped_column(info={"audit": "flag"})  # stored upper-cased: scans are case-insensitive
    status: Mapped[str] = enum_column(server_default=text("'active'"))
    source: Mapped[str] = enum_column()
    # shortcut: the app-card HMAC secret is stored as raw bytes under RLS; envelope-encrypt it with the tenant
    # data key when that key exists (the integrations lane brings `cryptography`).
    secret_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, info={"audit": "never"})
    device_label: Mapped[str | None]
    issued_at: Mapped[datetime]
    revoked_at: Mapped[datetime | None]
    revoked_by_staff_user_id: Mapped[UUID | None]


class KioskDevice(TenantOwned, Timestamps, Base):
    """A self check-in device. Paired with a single-use code; its token lives in an HttpOnly cookie and is stored
    here only as a SHA-256 hash. Overview section 2 lists this table under platform; it lives here (README)."""

    __tablename__ = "kiosk_device"
    __table_args__ = tenant_args(
        *tfk("location_id", "location"),
        *tfk("enrolled_by_staff_user_id", "staff_user"),
        Index("uq_kiosk_device_token", "tenant_id", "token_hash", unique=True),
        Index("uq_kiosk_device_pairing", "tenant_id", "pairing_code_hash", unique=True),
    )

    location_id: Mapped[UUID]
    name: Mapped[str]
    token_hash: Mapped[str | None] = mapped_column(info={"audit": "never"})
    pairing_code_hash: Mapped[str | None] = mapped_column(info={"audit": "never"})
    pairing_expires_at: Mapped[datetime | None]
    paired_at: Mapped[datetime | None]
    enrolled_by_staff_user_id: Mapped[UUID | None]  # None: registered by a seed or job
    last_seen_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
    # Wrong kiosk exit PINs since the last right one; the fifth revokes the device (KIOSK_EXIT_ATTEMPTS).
    exit_pin_failure_count: Mapped[int] = mapped_column(server_default=text("0"))


class KioskMatch(TenantOwned, Timestamps, Base):
    """A name-search result handed to a kiosk: an opaque token (stored hashed) that checks the client in once,
    within two minutes, on that device only."""

    __tablename__ = "kiosk_match"
    __table_args__ = tenant_args(
        *tfk("kiosk_device_id", "kiosk_device"),
        *tfk("client_id", "client"),
        Index("uq_kiosk_match_token", "tenant_id", "token_hash", unique=True),
    )

    kiosk_device_id: Mapped[UUID]
    client_id: Mapped[UUID]
    token_hash: Mapped[str] = mapped_column(info={"audit": "never"})
    expires_at: Mapped[datetime]


class KioskSettings(TenantOwned, Timestamps, Base):
    """Self check-in behaviour of one location (CHK-06). A missing row reads as the defaults."""

    __tablename__ = "kiosk_settings"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        UniqueConstraint("tenant_id", "location_id", name="uq_kiosk_settings_location"),
        enum_check("lookup_method", LookupMethod),
        CheckConstraint("early_window_minutes BETWEEN 0 AND 1440", name="early"),
        CheckConstraint("late_window_minutes BETWEEN 0 AND 1440", name="late"),
        CheckConstraint("confirmation_timeout_seconds BETWEEN 3 AND 300", name="timeout"),
    )

    location_id: Mapped[UUID]
    lookup_method: Mapped[str] = enum_column(server_default=text("'both'"))
    early_window_minutes: Mapped[int] = mapped_column(server_default=text("60"))
    late_window_minutes: Mapped[int] = mapped_column(server_default=text("30"))
    welcome_message: Mapped[str | None]
    displayed_alert_codes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{balance_due,membership_expired,visits_depleted}'"), info={"audit": "value"}
    )
    confirmation_timeout_seconds: Mapped[int] = mapped_column(server_default=text("10"))
    exit_pin_hash: Mapped[str | None] = mapped_column(info={"audit": "never"})  # argon2id; required to leave kiosk mode


class AccessSettings(TenantOwned, Timestamps, Base):
    """Staff check-in behaviour of one location (CHK-02). A missing row reads as the defaults."""

    __tablename__ = "access_settings"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        UniqueConstraint("tenant_id", "location_id", name="uq_access_settings_location"),
        CheckConstraint(
            "hidden_detail_fields <@ ARRAY[" + ", ".join(f"'{f}'" for f in DETAIL_FIELDS) + "]::text[]",
            name="hidden_fields",
        ),
        CheckConstraint("staff_early_minutes BETWEEN 0 AND 1440", name="early"),
        CheckConstraint("staff_late_minutes BETWEEN 0 AND 1440", name="late"),
        CheckConstraint(
            "entry_code_early_min BETWEEN 0 AND 240 AND entry_code_grace_min BETWEEN 0 AND 240"
            " AND light_lead_in_min BETWEEN 0 AND 120 AND light_run_on_min BETWEEN 0 AND 120",
            name="building",
        ),
        CheckConstraint("door_alert_bad_codes_per_hour BETWEEN 1 AND 10000", name="door_alert"),
    )

    location_id: Mapped[UUID]
    hidden_detail_fields: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{balance_due,membership_dates,visit_counts}'"), info={"audit": "value"}
    )
    staff_early_minutes: Mapped[int] = mapped_column(server_default=text("180"))
    staff_late_minutes: Mapped[int] = mapped_column(server_default=text("300"))
    # Building control (CHK-15, CHK-16): an entry code opens from early before the booking to grace after it;
    # court lights come on lead-in before and go off run-on after; a balance due refuses the code when required.
    entry_code_early_min: Mapped[int] = mapped_column(server_default=text("15"))
    entry_code_grace_min: Mapped[int] = mapped_column(server_default=text("10"))
    light_lead_in_min: Mapped[int] = mapped_column(server_default=text("5"))
    light_run_on_min: Mapped[int] = mapped_column(server_default=text("5"))
    requires_paid_entry: Mapped[bool] = mapped_column(server_default=text("true"))
    door_alert_bad_codes_per_hour: Mapped[int] = mapped_column(server_default=text("20"))  # staff emailed above it


class AccessRule(TenantOwned, Timestamps, Base):
    """The outcome a location chose for one membership condition (CHK-08)."""

    __tablename__ = "access_rule"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        UniqueConstraint("tenant_id", "location_id", "condition", name="uq_access_rule"),
        enum_check("condition", AccessCondition),
        enum_check("outcome", AccessOutcome),
    )

    location_id: Mapped[UUID]
    condition: Mapped[str] = enum_column()
    outcome: Mapped[str] = enum_column()


class ClientAccess(TenantOwned, Timestamps, Base):
    """A client's access mode (CHK-08). A missing row is `normal`: the rules decide."""

    __tablename__ = "client_access"
    __table_args__ = tenant_args(
        *tfk("client_id", "client", index=False),
        UniqueConstraint("tenant_id", "client_id", name="uq_client_access_client"),
        enum_check("access_mode", AccessMode),
    )

    client_id: Mapped[UUID]
    access_mode: Mapped[str] = enum_column()


class AccessSchedule(TenantOwned, Timestamps, Base):
    """Named weekly opening windows for members of mapped membership types (CHK-09)."""

    __tablename__ = "access_schedule"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "name", name="uq_access_schedule_name"))

    name: Mapped[str]
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class AccessScheduleRange(TenantOwned, Timestamps, Base):
    """One weekday window, in the zone of the location being entered. Across midnight is two rows."""

    __tablename__ = "access_schedule_range"
    __table_args__ = tenant_args(
        *tfk("access_schedule_id", "access_schedule", ondelete="CASCADE"),
        CheckConstraint("weekday BETWEEN 1 AND 7", name="weekday"),
        CheckConstraint("ends_time > starts_time", name="order"),
    )

    access_schedule_id: Mapped[UUID]
    weekday: Mapped[int]
    starts_time: Mapped[str] = mapped_column(WallTime)
    ends_time: Mapped[str] = mapped_column(WallTime)


class MembershipTypeAccess(TenantOwned, Timestamps, Base):
    """The schedule a membership type is limited to (CHK-09); no row or no schedule is unrestricted hours."""

    __tablename__ = "membership_type_access"
    __table_args__ = tenant_args(
        *tfk("membership_type_id", "membership_type", index=False),
        *tfk("access_schedule_id", "access_schedule"),
        UniqueConstraint("tenant_id", "membership_type_id", name="uq_membership_type_access"),
    )

    membership_type_id: Mapped[UUID]
    access_schedule_id: Mapped[UUID | None]


class MembershipTypeLocation(TenantOwned, Timestamps, Base):
    """A further location a membership type admits at (CHK-10). No rows: only the contract's own location."""

    __tablename__ = "membership_type_location"
    __table_args__ = tenant_args(
        *tfk("membership_type_id", "membership_type", index=False),
        *tfk("location_id", "location"),
        UniqueConstraint("tenant_id", "membership_type_id", "location_id", name="uq_membership_type_location"),
    )

    membership_type_id: Mapped[UUID]
    location_id: Mapped[UUID]


# --- building control (CHK-15, CHK-16): doors, court lights, entry codes, their activity log ----------------


class EntryCodeStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class BuildingEventKind(StrEnum):
    ENTRY_GRANTED = "entry_granted"
    ENTRY_DENIED = "entry_denied"
    REMOTE_UNLOCK = "remote_unlock"
    MEMBER_UNLOCK = "member_unlock"
    LIGHT_ON = "light_on"
    LIGHT_OFF = "light_off"
    OVERRIDE = "override"
    CODE_ISSUED = "code_issued"
    CODE_REVOKED = "code_revoked"
    COMMAND_FAILED = "command_failed"
    CODE_WITHHELD = "code_withheld"  # a rental held by a minor or someone of unknown age
    BAD_CODE_ALERT = "bad_code_alert"  # a door passed the location's wrong codes per hour; staff were emailed


class DoorDevice(TenantOwned, Timestamps, Base):
    """A door controller or keypad at a location. It calls POST /door/verify with its own bearer credential
    (`fhb_...`, shown once, SHA-256 stored); `device_ref` is the address the controller adapter understands."""

    __tablename__ = "door_device"
    __table_args__ = tenant_args(
        *tfk("location_id", "location"),
        Index("uq_door_device_token", "tenant_id", "token_hash", unique=True),
        CheckConstraint("unlock_seconds BETWEEN 1 AND 60", name="unlock_seconds"),
    )

    location_id: Mapped[UUID]
    name: Mapped[str] = mapped_column(info={"audit": "value"})
    device_ref: Mapped[str] = mapped_column(info={"audit": "value"})
    unlock_seconds: Mapped[int] = mapped_column(server_default=text("5"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    token_hash: Mapped[str | None] = mapped_column(info={"audit": "never"})
    last_seen_at: Mapped[datetime | None]


class LightingZone(TenantOwned, Timestamps, Base):
    """One switchable light circuit at a location, lit while a booking holds any of its resources (courts). Keeps
    the last state we commanded, so the tick only sends changes, and a staff override for a period."""

    __tablename__ = "lighting_zone"
    __table_args__ = tenant_args(
        *tfk("location_id", "location"),
        UniqueConstraint("tenant_id", "location_id", "name", name="uq_lighting_zone_name"),
        CheckConstraint("(override_is_on IS NULL) = (override_until_at IS NULL)", name="override"),
    )

    location_id: Mapped[UUID]
    name: Mapped[str] = mapped_column(info={"audit": "value"})
    zone_ref: Mapped[str] = mapped_column(info={"audit": "value"})
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    override_is_on: Mapped[bool | None] = mapped_column(info={"audit": "value"})
    override_until_at: Mapped[datetime | None] = mapped_column(info={"audit": "value"})
    override_reason: Mapped[str | None]
    commanded_is_on: Mapped[bool | None]  # None: never commanded
    commanded_at: Mapped[datetime | None]
    failure_count: Mapped[int] = mapped_column(server_default=text("0"))  # failed commands in a row
    lit_until_at: Mapped[datetime | None]  # a booking last wanted it on: stays on until here (run-on, never cut)


class LightingZoneResource(TenantOwned, Timestamps, Base):
    """A resource whose bookings light the zone. A parent court and its halves may all map to one zone."""

    __tablename__ = "lighting_zone_resource"
    __table_args__ = tenant_args(
        *tfk("lighting_zone_id", "lighting_zone", ondelete="CASCADE", index=False),
        *tfk("resource_id", "resource"),
        UniqueConstraint("tenant_id", "lighting_zone_id", "resource_id", name="uq_lighting_zone_resource"),
    )

    lighting_zone_id: Mapped[UUID]
    resource_id: Mapped[UUID]


class EntryCode(TenantOwned, Timestamps, Base):
    """One person's door code for one booking: a rental's holder, or one participant of a session. Only a keyed
    hash (lookup) and the AES-GCM sealed code (shown again to its owner) are stored; both are never audited. One
    active code per booking and person."""

    __tablename__ = "entry_code"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        *tfk("booking_id", "booking"),
        *tfk("client_id", "client"),
        enum_check("status", EntryCodeStatus),
        CheckConstraint("valid_until_at > valid_from_at", name="window"),
        CheckConstraint("status <> 'active' OR client_id IS NOT NULL", name="person"),
        CheckConstraint("(status = 'revoked') = (revoked_at IS NOT NULL)", name="revoked"),
        CheckConstraint("status <> 'active' OR code_ciphertext IS NOT NULL", name="sealed"),
        Index(
            "ix_entry_code_open",
            "tenant_id",
            "location_id",
            "valid_until_at",
            postgresql_where=text("status = 'active'"),
        ),  # fmt: skip
        Index(
            "uq_entry_code_active",
            "tenant_id",
            "location_id",
            "code_hash",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),  # fmt: skip
        Index(
            "uq_entry_code_booking",
            "tenant_id",
            "booking_id",
            "client_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),  # fmt: skip
    )

    location_id: Mapped[UUID]
    booking_id: Mapped[UUID]
    client_id: Mapped[UUID | None]  # whose code it is (a minor's goes to their adult guardians); None only on old rows
    code_hash: Mapped[str] = mapped_column(info={"audit": "never"})
    code_ciphertext: Mapped[str | None] = mapped_column(info={"audit": "never"})  # cleared once revoked or expired
    valid_from_at: Mapped[datetime]
    valid_until_at: Mapped[datetime]
    status: Mapped[str] = enum_column(server_default=text("'active'"))
    revoked_at: Mapped[datetime | None]
    revoke_reason: Mapped[str | None] = mapped_column(info={"audit": "value"})
    pushed_at: Mapped[datetime | None]  # the controller holds it (adapters that store codes)
    notified_at: Mapped[datetime | None]


class BuildingEvent(TenantOwned, Timestamps, Base):
    """Activity log of the building: entries and denials at the door, unlocks, light switches, overrides, code
    issue and revoke, failed commands. Append-only; never holds a code."""

    __tablename__ = "building_event"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        *tfk("door_device_id", "door_device"),
        *tfk("lighting_zone_id", "lighting_zone"),
        *tfk("entry_code_id", "entry_code"),
        *tfk("check_in_id", "check_in"),
        *tfk("staff_user_id", "staff_user"),
        enum_check("kind", BuildingEventKind),
        Index("ix_building_event_recent", "tenant_id", "location_id", text("occurred_at DESC"), text("id DESC")),
    )

    location_id: Mapped[UUID]
    occurred_at: Mapped[datetime]
    local_on: Mapped[date]
    kind: Mapped[str] = enum_column()
    door_device_id: Mapped[UUID | None]
    lighting_zone_id: Mapped[UUID | None]
    entry_code_id: Mapped[UUID | None]
    check_in_id: Mapped[UUID | None]
    staff_user_id: Mapped[UUID | None]
    detail: Mapped[str | None] = mapped_column(info={"audit": "value"})  # a reason code, never free text or a code
