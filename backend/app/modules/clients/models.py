"""clients tables (docs/architecture/data-model-people.md section 1, the schema of record).

The kernel skeleton shipped `client` and `client_portal_access`; build module 4 adds the remaining columns and
tables without renaming anything. Columns that need platform file storage (`photo_file_id`, note and task
attachments) are not created yet: there is no `stored_file` table to point at (module README).
"""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import CHAR, CheckConstraint, Computed, Index, Numeric, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, JsonDict, TenantOwned, Timestamps, enum_check, enum_column, tenant_args, tfk

_E164 = r"^\+[1-9][0-9]{6,14}$"
_EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
_FLAG = {"audit": "flag"}  # listed PII: the audit trail records that it changed, never the value


class ClientStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class MemberNumberSource(StrEnum):
    GENERATED = "generated"
    MANUAL = "manual"
    SCANNED = "scanned"


class Gender(StrEnum):
    FEMALE = "female"
    MALE = "male"
    NON_BINARY = "non_binary"
    UNDISCLOSED = "undisclosed"


class CreatedVia(StrEnum):
    STAFF = "staff"
    PORTAL = "portal"
    REGISTRATION = "registration"
    KIOSK = "kiosk"
    API = "api"
    IMPORT = "import"
    PROVIDER = "provider"


class PortalAccessStatus(StrEnum):
    INVITED = "invited"
    ACTIVE = "active"
    REVOKED = "revoked"


class TagKind(StrEnum):
    SPORT = "sport"
    SEASON = "season"
    CUSTOM = "custom"


class FieldDataType(StrEnum):
    TEXT = "text"
    NUMBER = "number"
    DATE = "date"
    BOOLEAN = "boolean"
    CHOICE = "choice"


class CaptureContext(StrEnum):
    STAFF = "staff"
    REGISTRATION = "registration"
    PORTAL = "portal"


class Requirement(StrEnum):
    HIDDEN = "hidden"
    OPTIONAL = "optional"
    REQUIRED = "required"


class MemberNumberTrigger(StrEnum):
    CLIENT_CREATED = "client_created"
    MEMBERSHIP_SOLD = "membership_sold"


class RelationshipStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    DECLINED = "declined"
    ENDED = "ended"


class RelationshipCreatedVia(StrEnum):
    STAFF = "staff"
    PORTAL = "portal"
    REGISTRATION = "registration"
    PROVIDER = "provider"
    IMPORT = "import"


class NoteKind(StrEnum):
    CALL = "call"
    EMAIL = "email"
    TASK = "task"
    OTHER = "other"


class TaskStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


class AlertKind(StrEnum):
    GENERAL = "general"
    MEDICAL = "medical"
    INJURY = "injury"
    CONDUCT = "conduct"


class AlertSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


def _phone_check(column: str) -> CheckConstraint:
    return CheckConstraint(f"{column} ~ '{_E164}'", name=column)


# --- 1.1 client ----------------------------------------------------------------------------------------------


class Client(TenantOwned, Timestamps, Base):
    """One row per person, never per family (CLI-01); shared across the tenant's locations (CLI-19)."""

    __tablename__ = "client"
    __table_args__ = tenant_args(
        *tfk("home_location_id", "location"),
        *tfk("client_category_id", "client_category", index=False),
        *tfk("referral_category_id", "referral_category"),
        *tfk("default_trainer_staff_user_id", "staff_user", index=False),
        *tfk("default_salesperson_staff_user_id", "staff_user", index=False),
        *tfk("disabled_by_staff_user_id", "staff_user"),
        *tfk("merged_into_id", "client", index=False),
        *tfk("created_by_staff_user_id", "staff_user"),
        *tfk("updated_by_staff_user_id", "staff_user"),
        *tfk("photo_file_id", "stored_file"),  # CLI-12, clients/files.py
        CheckConstraint("btrim(first_name) <> ''", name="first_name"),
        CheckConstraint("btrim(last_name) <> ''", name="last_name"),
        _phone_check("phone_mobile"),
        _phone_check("phone_home"),
        _phone_check("phone_work"),
        CheckConstraint(  # one constraint under the data model's name: the pair rule and the vocabulary
            "(member_number IS NULL AND member_number_source IS NULL) OR (member_number IS NOT NULL AND "
            f"member_number_source IN ({', '.join(repr(m.value) for m in MemberNumberSource)}))",
            name="member_number_source",
        ),
        enum_check("status", ClientStatus),
        enum_check("gender", Gender),
        enum_check("created_via", CreatedVia),
        CheckConstraint("(status = 'disabled') = (disabled_at IS NOT NULL)", name="disabled"),
        CheckConstraint("merged_into_id IS NULL OR (status = 'disabled' AND merged_into_id <> id)", name="merged"),
        CheckConstraint("jsonb_typeof(custom_values) = 'object'", name="custom_values"),
        CheckConstraint("discount_pct BETWEEN 0 AND 100", name="discount_pct"),
        CheckConstraint("country_code ~ '^[A-Z]{2}$'", name="country_code"),
        Index(
            "uq_client_tenant_id_member_number", "tenant_id", "member_number", unique=True,
            postgresql_where=text("member_number IS NOT NULL"),
        ),
        Index("ix_client_name", "tenant_id", func.lower(text("last_name")), func.lower(text("first_name")), "id"),
        Index("ix_client_status", "tenant_id", "status", "id"),
        Index("ix_client_category", "tenant_id", "client_category_id", "id"),
        Index("ix_client_search_text", "search_text", postgresql_using="gin", postgresql_ops={"search_text": "gin_trgm_ops"}),
        Index("ix_client_phone_digits", "phone_digits", postgresql_using="gin", postgresql_ops={"phone_digits": "gin_trgm_ops"}),
        Index(
            "ix_client_birthday", "tenant_id", text("(extract(month FROM birth_on))"), text("(extract(day FROM birth_on))")
        ),
        Index(
            "ix_client_default_trainer", "tenant_id", "default_trainer_staff_user_id",
            postgresql_where=text("default_trainer_staff_user_id IS NOT NULL"),
        ),
        Index(
            "ix_client_default_salesperson", "tenant_id", "default_salesperson_staff_user_id",
            postgresql_where=text("default_salesperson_staff_user_id IS NOT NULL"),
        ),
        Index("ix_client_duplicate_key", "tenant_id", func.lower(text("last_name")), "birth_on"),
        Index("ix_client_merged_into", "tenant_id", "merged_into_id", postgresql_where=text("merged_into_id IS NOT NULL")),
    )  # fmt: skip

    first_name: Mapped[str] = mapped_column(info=_FLAG)
    last_name: Mapped[str] = mapped_column(info=_FLAG)
    preferred_name: Mapped[str | None] = mapped_column(info=_FLAG)
    gender: Mapped[str | None] = enum_column()
    birth_on: Mapped[date | None] = mapped_column(info=_FLAG)
    organization_name: Mapped[str | None]
    phone_mobile: Mapped[str | None] = mapped_column(info=_FLAG)
    phone_home: Mapped[str | None] = mapped_column(info=_FLAG)
    phone_work: Mapped[str | None] = mapped_column(info=_FLAG)
    address_line1: Mapped[str | None] = mapped_column(info=_FLAG)
    address_line2: Mapped[str | None] = mapped_column(info=_FLAG)
    city: Mapped[str | None] = mapped_column(info=_FLAG)
    region: Mapped[str | None] = mapped_column(info=_FLAG)
    postal_code: Mapped[str | None] = mapped_column(info=_FLAG)
    country_code: Mapped[str | None] = mapped_column(CHAR(2), info={"audit": "value"})
    home_location_id: Mapped[UUID]
    client_category_id: Mapped[UUID | None]
    referral_category_id: Mapped[UUID | None]
    referral_source: Mapped[str | None]
    default_trainer_staff_user_id: Mapped[UUID | None]
    default_salesperson_staff_user_id: Mapped[UUID | None]
    # Denormalised copy of the primary client_email row, written only by clients.service.
    primary_email: Mapped[str | None] = mapped_column(CITEXT, info=_FLAG)
    custom_values: Mapped[dict] = mapped_column(JsonDict, server_default=text("'{}'"))
    discount_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default=text("0"), info={"audit": "value"})
    member_number: Mapped[str | None] = mapped_column(CITEXT, info={"audit": "value"})
    member_number_source: Mapped[str | None] = enum_column()
    comments: Mapped[str | None]
    medical_notes: Mapped[str | None] = mapped_column(info=_FLAG)
    status: Mapped[str] = enum_column(server_default=text("'active'"))
    disabled_at: Mapped[datetime | None]
    disabled_by_staff_user_id: Mapped[UUID | None]
    merged_into_id: Mapped[UUID | None]
    merged_at: Mapped[datetime | None]
    erased_at: Mapped[datetime | None]
    created_via: Mapped[str] = enum_column(server_default=text("'staff'"))
    created_by_staff_user_id: Mapped[UUID | None]
    updated_by_staff_user_id: Mapped[UUID | None]
    photo_file_id: Mapped[UUID | None] = mapped_column(info=_FLAG)
    phone_digits: Mapped[str | None] = mapped_column(
        Computed(
            "regexp_replace(coalesce(phone_mobile,'') || ' ' || coalesce(phone_home,'') || ' ' || "
            "coalesce(phone_work,''), '[^0-9 ]', '', 'g')",
            persisted=True,
        )
    )
    search_text: Mapped[str | None] = mapped_column(
        Computed(
            "lower(first_name || ' ' || last_name || ' ' || coalesce(preferred_name,'') || ' ' || "
            "coalesce(primary_email::text,'') || ' ' || coalesce(member_number::text,''))",
            persisted=True,
        )
    )
    version: Mapped[int] = mapped_column(server_default=text("1"))


# --- 1.2 to 1.8: contact data and configuration --------------------------------------------------------------


class ClientEmail(TenantOwned, Timestamps, Base):
    """Several addresses per client; one address may sit on several clients (parent and child, FAM-02).

    The verification token columns are ours (module README): the double opt-in link needs a single-use token and
    engagement's `email_verification` table does not exist yet.
    """

    __tablename__ = "client_email"
    __table_args__ = tenant_args(
        *tfk("client_id", "client", ondelete="CASCADE", index=False),
        CheckConstraint(f"email ~ '{_EMAIL}'", name="email"),
        UniqueConstraint("tenant_id", "client_id", "email", name="uq_client_email_client_email"),
        Index("uq_client_email_primary", "tenant_id", "client_id", unique=True, postgresql_where=text("is_primary")),
        Index("ix_client_email_email", "tenant_id", "email"),
        Index("ix_client_email_trgm", text("(email::text) gin_trgm_ops"), postgresql_using="gin"),
        Index(
            "uq_client_email_token", "tenant_id", "verification_token_hash", unique=True,
            postgresql_where=text("verification_token_hash IS NOT NULL"),
        ),
    )  # fmt: skip

    client_id: Mapped[UUID]
    email: Mapped[str] = mapped_column(CITEXT, info=_FLAG)
    is_primary: Mapped[bool] = mapped_column(server_default=text("false"))
    label: Mapped[str | None]
    verification_sent_at: Mapped[datetime | None]
    verified_at: Mapped[datetime | None]
    verification_token_hash: Mapped[str | None] = mapped_column(info={"audit": "never"})
    verification_expires_at: Mapped[datetime | None]


class ClientEmergencyContact(TenantOwned, Timestamps, Base):
    __tablename__ = "client_emergency_contact"
    __table_args__ = tenant_args(
        *tfk("client_id", "client", ondelete="CASCADE", index=False),
        UniqueConstraint("tenant_id", "client_id", "position", name="uq_client_emergency_contact_position"),
        CheckConstraint("position >= 1", name="position"),
    )

    client_id: Mapped[UUID]
    position: Mapped[int]
    name: Mapped[str] = mapped_column(info=_FLAG)
    relationship_label: Mapped[str | None]
    phone: Mapped[str | None] = mapped_column(info=_FLAG)
    phone_alt: Mapped[str | None] = mapped_column(info=_FLAG)
    email: Mapped[str | None] = mapped_column(CITEXT, info=_FLAG)
    notes: Mapped[str | None]


class ClientCategory(TenantOwned, Timestamps, Base):
    __tablename__ = "client_category"
    __table_args__ = tenant_args(Index("uq_client_category_name", "tenant_id", func.lower(text("name")), unique=True))

    name: Mapped[str] = mapped_column(info={"audit": "value"})
    sort_order: Mapped[int] = mapped_column(server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class ReferralCategory(TenantOwned, Timestamps, Base):
    __tablename__ = "referral_category"
    __table_args__ = tenant_args(Index("uq_referral_category_name", "tenant_id", func.lower(text("name")), unique=True))

    name: Mapped[str] = mapped_column(info={"audit": "value"})
    sort_order: Mapped[int] = mapped_column(server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class Tag(TenantOwned, Timestamps, Base):
    __tablename__ = "tag"
    __table_args__ = tenant_args(
        enum_check("kind", TagKind),
        Index("uq_tag_kind_label", "tenant_id", "kind", func.lower(text("label")), unique=True),
    )

    kind: Mapped[str] = enum_column()
    label: Mapped[str] = mapped_column(info={"audit": "value"})
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class ClientTag(TenantOwned, Timestamps, Base):
    __tablename__ = "client_tag"
    __table_args__ = tenant_args(
        *tfk("client_id", "client", ondelete="CASCADE", index=False),
        *tfk("tag_id", "tag", index=False),
        UniqueConstraint("tenant_id", "client_id", "tag_id", name="uq_client_tag_client_tag"),
        Index("ix_client_tag_tag", "tenant_id", "tag_id", "client_id"),
    )

    client_id: Mapped[UUID]
    tag_id: Mapped[UUID]


class CustomField(TenantOwned, Timestamps, Base):
    __tablename__ = "custom_field"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", "key", name="uq_custom_field_key"),
        CheckConstraint("key ~ '^[a-z][a-z0-9_]{0,39}$'", name="key"),
        enum_check("data_type", FieldDataType),
        CheckConstraint("(data_type = 'choice') = (choices IS NOT NULL)", name="choices"),
    )

    key: Mapped[str] = mapped_column(info={"audit": "value"})
    label: Mapped[str] = mapped_column(info={"audit": "value"})
    data_type: Mapped[str] = enum_column(server_default=text("'text'"))
    choices: Mapped[list | None] = mapped_column(JsonDict)
    sort_order: Mapped[int] = mapped_column(server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class ClientFieldPolicy(TenantOwned, Timestamps, Base):
    __tablename__ = "client_field_policy"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", "field_key", "capture_context", name="uq_client_field_policy_field_context"),
        enum_check("capture_context", CaptureContext),
        enum_check("requirement", Requirement),
    )

    field_key: Mapped[str] = mapped_column(info={"audit": "value"})
    capture_context: Mapped[str] = enum_column()
    requirement: Mapped[str] = enum_column()


class ClientSettings(TenantOwned, Timestamps, Base):
    __tablename__ = "client_settings"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", name="uq_client_settings_tenant"),
        enum_check("default_gender", Gender),
        enum_check("member_number_trigger", MemberNumberTrigger),
    )

    default_gender: Mapped[str | None] = enum_column()
    is_member_number_auto_generated: Mapped[bool] = mapped_column(server_default=text("false"))
    member_number_trigger: Mapped[str] = enum_column(server_default=text("'membership_sold'"))
    member_number_prefix: Mapped[str] = mapped_column(server_default=text("''"), info={"audit": "value"})
    is_verification_email_enabled: Mapped[bool] = mapped_column(server_default=text("true"))
    is_own_clients_scope_enabled: Mapped[bool] = mapped_column(server_default=text("false"))


class ClientLocationSettings(TenantOwned, Timestamps, Base):
    __tablename__ = "client_location_settings"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        UniqueConstraint("tenant_id", "location_id", name="uq_client_location_settings_location"),
    )

    location_id: Mapped[UUID]
    is_portal_photo_edit_enabled: Mapped[bool] = mapped_column(server_default=text("true"))


# --- 1.9 to 1.11: households and portal access ---------------------------------------------------------------


class RelationshipType(TenantOwned, Timestamps, Base):
    """Read from the `from` side: "from is <label> to". Null inverse means symmetric (FAM-01)."""

    __tablename__ = "relationship_type"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", "code", name="uq_relationship_type_code"),
        *tfk("inverse_type_id", "relationship_type"),
    )

    code: Mapped[str] = mapped_column(info={"audit": "value"})
    label: Mapped[str] = mapped_column(info={"audit": "value"})
    inverse_type_id: Mapped[UUID | None]
    grants_acting_rights: Mapped[bool] = mapped_column(server_default=text("false"))
    is_guardianship: Mapped[bool] = mapped_column(server_default=text("false"))
    is_portal_selectable: Mapped[bool] = mapped_column(server_default=text("true"))
    is_system: Mapped[bool] = mapped_column(server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class ClientRelationship(TenantOwned, Timestamps, Base):
    """One row per unordered pair; the inverse is rendered, never stored (FAM-01)."""

    __tablename__ = "client_relationship"
    __table_args__ = tenant_args(
        *tfk("from_client_id", "client", index=False),
        *tfk("to_client_id", "client", index=False),
        *tfk("relationship_type_id", "relationship_type"),
        *tfk("requested_by_identity_id", "identity"),
        CheckConstraint("from_client_id <> to_client_id", name="distinct"),
        enum_check("status", RelationshipStatus),
        enum_check("created_via", RelationshipCreatedVia),
        Index(
            "uq_client_relationship_pair", "tenant_id", func.least(text("from_client_id"), text("to_client_id")),
            func.greatest(text("from_client_id"), text("to_client_id")), unique=True,
            postgresql_where=text("status IN ('pending', 'active')"),
        ),
        Index(
            "uq_client_relationship_token", "tenant_id", "confirmation_token_hash", unique=True,
            postgresql_where=text("confirmation_token_hash IS NOT NULL"),
        ),
        Index("ix_client_relationship_from", "tenant_id", "from_client_id", "status"),
        Index("ix_client_relationship_to", "tenant_id", "to_client_id", "status"),
    )  # fmt: skip

    from_client_id: Mapped[UUID]
    to_client_id: Mapped[UUID]
    relationship_type_id: Mapped[UUID]
    status: Mapped[str] = enum_column(server_default=text("'active'"))
    created_via: Mapped[str] = enum_column(server_default=text("'staff'"))
    requested_by_identity_id: Mapped[UUID | None]
    confirmation_token_hash: Mapped[str | None] = mapped_column(info={"audit": "never"})
    confirmation_expires_at: Mapped[datetime | None]
    confirmed_at: Mapped[datetime | None]
    ended_at: Mapped[datetime | None]


class ClientPortalAccess(TenantOwned, Timestamps, Base):
    """Which client records a client-kind identity signs in as. Email is not an identity key here (CLI-15).
    `is_primary` = the identity is this person (`self`); false rows are managed profiles (`manager`)."""

    __tablename__ = "client_portal_access"
    __table_args__ = tenant_args(
        *tfk("identity_id", "identity"),
        *tfk("client_id", "client"),
        *tfk("invited_by_staff_user_id", "staff_user"),
        UniqueConstraint("tenant_id", "identity_id", "client_id", name="uq_client_portal_access_identity_client"),
        Index(
            "uq_client_portal_access_primary", "tenant_id", "client_id", unique=True,
            postgresql_where=text("is_primary AND status <> 'revoked'"),
        ),
        enum_check("status", PortalAccessStatus),
    )  # fmt: skip

    identity_id: Mapped[UUID]
    client_id: Mapped[UUID]
    is_primary: Mapped[bool] = mapped_column(server_default=text("true"))
    status: Mapped[str] = enum_column(server_default=text("'invited'"))
    invited_at: Mapped[datetime | None]
    invited_by_staff_user_id: Mapped[UUID | None]
    activated_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]


# --- 1.12 to 1.17: activity, merge, recents ------------------------------------------------------------------


class NoteSubject(TenantOwned, Timestamps, Base):
    __tablename__ = "note_subject"
    __table_args__ = tenant_args(Index("uq_note_subject_label", "tenant_id", func.lower(text("label")), unique=True))

    label: Mapped[str] = mapped_column(info={"audit": "value"})
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class ClientNote(TenantOwned, Timestamps, Base):
    """Logged interaction (CLI-09). Staff only; never on the portal surface."""

    __tablename__ = "client_note"
    __table_args__ = tenant_args(
        *tfk("client_id", "client", index=False),
        *tfk("note_subject_id", "note_subject"),
        *tfk("staff_user_id", "staff_user"),
        *tfk("location_id", "location"),
        enum_check("kind", NoteKind),
        CheckConstraint("num_nonnulls(note_subject_id, subject_text) = 1", name="subject"),
        Index("ix_client_note_client", "tenant_id", "client_id", text("occurred_at DESC")),
    )

    client_id: Mapped[UUID]
    kind: Mapped[str] = enum_column()
    note_subject_id: Mapped[UUID | None]
    subject_text: Mapped[str | None]
    body: Mapped[str | None]
    occurred_at: Mapped[datetime] = mapped_column(server_default=func.now())
    staff_user_id: Mapped[UUID]
    location_id: Mapped[UUID | None]


class ClientTask(TenantOwned, Timestamps, Base):
    __tablename__ = "client_task"
    __table_args__ = tenant_args(
        *tfk("client_id", "client", index=False),
        *tfk("note_subject_id", "note_subject"),
        *tfk("assignee_staff_user_id", "staff_user", index=False),
        *tfk("completed_by_staff_user_id", "staff_user"),
        enum_check("status", TaskStatus),
        CheckConstraint("num_nonnulls(note_subject_id, subject_text) = 1", name="subject"),
        CheckConstraint("(status = 'done') = (completed_at IS NOT NULL)", name="completed"),
        Index(
            "ix_client_task_assignee_open", "tenant_id", "assignee_staff_user_id", "due_on",
            postgresql_where=text("status IN ('open', 'in_progress')"),
        ),
        Index("ix_client_task_client", "tenant_id", "client_id", "id"),
    )  # fmt: skip

    client_id: Mapped[UUID]
    note_subject_id: Mapped[UUID | None]
    subject_text: Mapped[str | None]
    body: Mapped[str | None]
    assignee_staff_user_id: Mapped[UUID]
    status: Mapped[str] = enum_column(server_default=text("'open'"))
    due_on: Mapped[date | None]
    completed_at: Mapped[datetime | None]
    completed_by_staff_user_id: Mapped[UUID | None]
    has_email_reminder: Mapped[bool] = mapped_column(server_default=text("false"))
    reminder_sent_at: Mapped[datetime | None]


class ClientAlert(TenantOwned, Timestamps, Base):
    """Staff-authored alert shown on the profile, at check-in or while booking (CLI-20)."""

    __tablename__ = "client_alert"
    __table_args__ = tenant_args(
        *tfk("client_id", "client", index=False),
        *tfk("created_by_staff_user_id", "staff_user"),
        enum_check("kind", AlertKind),
        enum_check("severity", AlertSeverity),
        CheckConstraint("ends_on IS NULL OR starts_on IS NULL OR ends_on >= starts_on", name="dates"),
        Index("ix_client_alert_client_active", "tenant_id", "client_id", postgresql_where=text("is_active")),
    )

    client_id: Mapped[UUID]
    kind: Mapped[str] = enum_column(server_default=text("'general'"))
    severity: Mapped[str] = enum_column(server_default=text("'info'"))
    message: Mapped[str]
    shows_on_profile: Mapped[bool] = mapped_column(server_default=text("true"))
    shows_on_check_in: Mapped[bool] = mapped_column(server_default=text("true"))
    shows_on_booking: Mapped[bool] = mapped_column(server_default=text("false"))
    starts_on: Mapped[date | None]
    ends_on: Mapped[date | None]
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    created_by_staff_user_id: Mapped[UUID]


class ClientMerge(TenantOwned, Base):
    """One row per losing record (CLI-13). Append-only."""

    __tablename__ = "client_merge"
    __table_args__ = tenant_args(
        *tfk("survivor_client_id", "client"),
        *tfk("merged_client_id", "client", index=False),
        *tfk("performed_by_staff_user_id", "staff_user"),
        UniqueConstraint("tenant_id", "merged_client_id", name="uq_client_merge_merged"),
    )

    survivor_client_id: Mapped[UUID]
    merged_client_id: Mapped[UUID]
    performed_by_staff_user_id: Mapped[UUID]
    performed_at: Mapped[datetime] = mapped_column(server_default=func.now())
    backfilled_fields: Mapped[dict] = mapped_column(JsonDict, server_default=text("'{}'"))
    precheck: Mapped[dict] = mapped_column(JsonDict, server_default=text("'{}'"))


class ClientRecentView(TenantOwned, Timestamps, Base):
    """Per staff user "recently accessed" (CLI-03): upserted on profile open, pruned to 50 rows per user."""

    __tablename__ = "client_recent_view"
    __table_args__ = tenant_args(
        *tfk("staff_user_id", "staff_user", index=False),
        *tfk("client_id", "client", ondelete="CASCADE"),
        UniqueConstraint("tenant_id", "staff_user_id", "client_id", name="uq_client_recent_view_user_client"),
        Index("ix_client_recent_view_user", "tenant_id", "staff_user_id", text("viewed_at DESC")),
    )

    staff_user_id: Mapped[UUID]
    client_id: Mapped[UUID]
    viewed_at: Mapped[datetime] = mapped_column(server_default=func.now())


# --- client files (phase 10 chip F): note attachments (CLI-09); the photo is client.photo_file_id (CLI-12) -----


class ClientNoteAttachment(TenantOwned, Timestamps, Base):
    """A stored file on an activity note. Deleting the note deletes the link (the bytes wait for a purge job)."""

    __tablename__ = "client_note_attachment"
    __table_args__ = tenant_args(
        *tfk("client_note_id", "client_note", ondelete="CASCADE"),
        *tfk("stored_file_id", "stored_file"),
    )

    client_note_id: Mapped[UUID]
    stored_file_id: Mapped[UUID]
