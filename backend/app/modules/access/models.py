"""access tables, P0 subset (docs/architecture/data-model-money.md section 3): the check-in log and its attendance
marks, credentials, kiosk devices and kiosk settings. Stations, access rules and schedules, client access mode and
ID card templates (P1) are not created; their columns are added by the module that builds them."""

from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import ARRAY, CheckConstraint, Index, LargeBinary, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantOwned, Timestamps, enum_check, enum_column, tenant_args, tfk


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
        Index("ix_check_in_recent", "tenant_id", "location_id", text("checked_in_at DESC"), text("id DESC")),
        Index("ix_check_in_client", "tenant_id", "client_id", text("checked_in_at DESC")),
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
