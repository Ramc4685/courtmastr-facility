"""platform tables (docs/architecture/data-model-core.md section 2). Columns follow that document's order."""

from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    CHAR,
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, INET
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, JsonDict, TenantOwned, Timestamps, WallTime, enum_check, enum_column, tenant_args, tfk
from app.core.ids import new_id


class TenantStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"


class MfaPolicy(StrEnum):
    OPTIONAL = "optional"
    PRIVILEGED = "privileged"
    ALL = "all"


class LocationStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class IdentityKind(StrEnum):
    STAFF = "staff"
    CLIENT = "client"


class IdentityStatus(StrEnum):
    INVITED = "invited"
    ACTIVE = "active"
    DISABLED = "disabled"
    MERGED = "merged"


class IpPolicy(StrEnum):
    ANY = "any"
    FACILITY_NETWORKS = "facility_networks"


class TokenPurpose(StrEnum):
    MAGIC_LINK = "magic_link"
    PASSWORD_RESET = "password_reset"
    INVITE = "invite"
    EMAIL_VERIFY = "email_verify"
    EMAIL_CHANGE = "email_change"
    RELATIONSHIP_CONFIRM = "relationship_confirm"


class SessionKind(StrEnum):
    WEB = "web"
    MOBILE = "mobile"
    IMPERSONATION = "impersonation"


def _false() -> Mapped[bool]:
    return mapped_column(server_default=text("false"))


# --- 2.1 Tenancy -----------------------------------------------------------------------------------------


class SubscriptionPlan(Timestamps, Base):
    """Global catalogue of our own tiers; fh_app has SELECT only. Entitlements arrive with PLT-14."""

    __tablename__ = "subscription_plan"
    __table_args__ = (UniqueConstraint("code", name="uq_subscription_plan_code"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id, server_default=text("app.uuid_v7()"))
    code: Mapped[str]
    name: Mapped[str]
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))


class Tenant(Timestamps, Base):
    """Global row: id is the tenant id. Policy is id = app.current_tenant_id(); inserted only by fh_platform."""

    __tablename__ = "tenant"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_tenant_slug"),
        enum_check("status", TenantStatus),
        enum_check("staff_mfa_policy", MfaPolicy),
        CheckConstraint("billing_cycle IN ('monthly', 'annual')", name="billing_cycle"),
        CheckConstraint(
            "email_sending_state IN ('active', 'marketing_paused', 'suspended')", name="email_sending_state"
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id, server_default=text("app.uuid_v7()"))
    name: Mapped[str]
    slug: Mapped[str] = mapped_column(CITEXT)
    status: Mapped[str] = enum_column(server_default=text("'active'"))
    currency: Mapped[str] = mapped_column(CHAR(3), server_default=text("'USD'"), info={"audit": "value"})
    default_time_zone: Mapped[str] = mapped_column(info={"audit": "value"})
    locale: Mapped[str] = mapped_column(server_default=text("'en-US'"), info={"audit": "value"})
    subscription_plan_id: Mapped[UUID | None] = mapped_column(ForeignKey("subscription_plan.id", ondelete="RESTRICT"))
    billing_cycle: Mapped[str | None] = enum_column()
    trial_ends_on: Mapped[date | None]
    staff_mfa_policy: Mapped[str] = enum_column(server_default=text("'privileged'"))
    platform_billing_ref: Mapped[str | None]
    billing_locked_through_on: Mapped[date | None]
    email_sending_state: Mapped[str] = enum_column(server_default=text("'active'"))
    is_listed_in_app_directory: Mapped[bool] = _false()
    app_directory_name: Mapped[str | None]
    settings: Mapped[dict] = mapped_column(JsonDict, server_default=text("'{}'"))


class TenantDomain(TenantOwned, Timestamps, Base):
    __tablename__ = "tenant_domain"
    __table_args__ = tenant_args(
        UniqueConstraint("host", name="uq_tenant_domain_host"),  # global by nature
        Index("uq_tenant_domain_primary", "tenant_id", unique=True, postgresql_where=text("is_primary")),
        CheckConstraint("kind IN ('subdomain', 'custom')", name="kind"),
    )

    host: Mapped[str] = mapped_column(CITEXT)
    kind: Mapped[str] = enum_column(server_default=text("'subdomain'"))
    is_primary: Mapped[bool] = _false()
    verified_at: Mapped[datetime | None]


class TenantCounter(TenantOwned, Timestamps, Base):
    """Gapless per-tenant numbers (booking, invoice, receipt, member number). Taken FOR UPDATE (overview 3.5)."""

    __tablename__ = "tenant_counter"
    __table_args__ = tenant_args(UniqueConstraint("tenant_id", "counter_key", name="uq_tenant_counter"))

    counter_key: Mapped[str] = mapped_column(info={"audit": "value"})
    next_value: Mapped[int] = mapped_column(BigInteger, server_default=text("1"))


# --- 2.2 Locations ---------------------------------------------------------------------------------------


class Location(TenantOwned, Timestamps, Base):
    __tablename__ = "location"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", "slug", name="uq_location_slug"),
        UniqueConstraint("tenant_id", "name", name="uq_location_name"),
        enum_check("status", LocationStatus),
        CheckConstraint("decline_email_mode IN ('digest', 'per_decline')", name="decline_email_mode"),
        CheckConstraint("time_clock_rounding IN ('none', 'up', 'down')", name="time_clock_rounding"),
        CheckConstraint("time_clock_rounding_min IN (5, 6, 10, 15, 30)", name="time_clock_rounding_min"),
    )

    slug: Mapped[str] = mapped_column(CITEXT)
    name: Mapped[str]
    public_name: Mapped[str]
    address_line1: Mapped[str | None]
    address_line2: Mapped[str | None]
    city: Mapped[str | None]
    region: Mapped[str | None]
    postal_code: Mapped[str | None]
    country_code: Mapped[str | None] = mapped_column(CHAR(2))
    phone: Mapped[str | None]
    email: Mapped[str | None] = mapped_column(CITEXT)
    alert_email: Mapped[str | None] = mapped_column(CITEXT)
    website_url: Mapped[str | None]
    time_zone: Mapped[str] = mapped_column(info={"audit": "value"})  # IANA; all "day" logic for this site
    membership_renewal_run_time: Mapped[str] = mapped_column(WallTime, server_default=text("'01:00'"))
    package_renewal_run_time: Mapped[str] = mapped_column(WallTime, server_default=text("'01:30'"))
    autopay_run_time: Mapped[str] = mapped_column(WallTime, server_default=text("'06:00'"))
    decline_email_mode: Mapped[str] = enum_column(server_default=text("'digest'"))
    time_clock_rounding: Mapped[str] = enum_column(server_default=text("'none'"))
    time_clock_rounding_min: Mapped[int] = mapped_column(SmallInteger, server_default=text("15"))
    is_time_clock_network_restricted: Mapped[bool] = _false()
    accepted_card_brands: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    is_gdpr_mode: Mapped[bool] = _false()
    status: Mapped[str] = enum_column(server_default=text("'active'"))
    sort_order: Mapped[int] = mapped_column(server_default=text("0"))


class FacilityHours(TenantOwned, Timestamps, Base):
    """Seven rows per location. Hours bound the calendar viewport; they never reject a staff booking."""

    __tablename__ = "facility_hours"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", ondelete="CASCADE", index=False),
        UniqueConstraint("tenant_id", "location_id", "weekday", name="uq_facility_hours"),
        CheckConstraint("weekday BETWEEN 1 AND 7", name="weekday"),
        CheckConstraint(
            "is_closed OR (opens_time IS NOT NULL AND closes_time IS NOT NULL AND closes_time > opens_time)",
            name="window",
        ),
    )

    location_id: Mapped[UUID]
    weekday: Mapped[int] = mapped_column(SmallInteger)  # ISO, 1 = Monday
    opens_time: Mapped[str | None] = mapped_column(WallTime)
    closes_time: Mapped[str | None] = mapped_column(WallTime)  # 24:00 allowed for a midnight close
    is_closed: Mapped[bool] = _false()


# --- 2.4 RBAC (declared before staff_user, which references role) ---------------------------------------


class Role(TenantOwned, Timestamps, Base):
    __tablename__ = "role"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", "name", name="uq_role_name"),
        Index(
            "uq_role_system_key",
            "tenant_id",
            "system_key",
            unique=True,
            postgresql_where=text("system_key IS NOT NULL"),
        ),  # fmt: skip
        CheckConstraint("(system_key IS NOT NULL) = is_system", name="system"),
        enum_check("default_ip_policy", IpPolicy),
        *tfk("cloned_from_role_id", "role"),
    )

    name: Mapped[str] = mapped_column(CITEXT)
    description: Mapped[str | None]
    is_system: Mapped[bool] = _false()  # system roles are locked and resolve their grants from code
    system_key: Mapped[str | None] = enum_column()
    cloned_from_role_id: Mapped[UUID | None]  # provenance only, no live inheritance
    default_ip_policy: Mapped[str] = enum_column(server_default=text("'any'"))


class RolePermission(TenantOwned, Timestamps, Base):
    """Grants of a custom role. A null subject is the default for every subject of the key."""

    __tablename__ = "role_permission"
    __table_args__ = tenant_args(
        *tfk("role_id", "role", ondelete="CASCADE", index=False),
        UniqueConstraint(
            "tenant_id",
            "role_id",
            "permission_key",
            "subject_id",
            name="uq_role_permission",
            postgresql_nulls_not_distinct=True,
        ),  # fmt: skip
        CheckConstraint("subject_id IS NULL OR subject_type IS NOT NULL", name="subject"),
    )

    role_id: Mapped[UUID]
    permission_key: Mapped[str] = mapped_column(info={"audit": "value"})
    subject_type: Mapped[str | None] = enum_column()
    subject_id: Mapped[UUID | None]
    is_allowed: Mapped[bool] = mapped_column(server_default=text("true"))


# --- 2.3 Identity and sessions ---------------------------------------------------------------------------


class Identity(TenantOwned, Timestamps, Base):
    """A sign-in identity. Staff and clients are different kinds of the same table (ADR 0002)."""

    __tablename__ = "identity"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", "kind", "email", name="uq_identity_kind_email"),
        enum_check("kind", IdentityKind),
        enum_check("status", IdentityStatus),
        *tfk("merged_into_identity_id", "identity"),
    )

    kind: Mapped[str] = enum_column()
    email: Mapped[str] = mapped_column(CITEXT)
    email_verified_at: Mapped[datetime | None]
    password_hash: Mapped[str | None] = mapped_column(info={"audit": "never"})
    status: Mapped[str] = enum_column(server_default=text("'invited'"))
    merged_into_identity_id: Mapped[UUID | None]
    failed_attempt_count: Mapped[int] = mapped_column(server_default=text("0"))
    locked_until_at: Mapped[datetime | None]
    password_changed_at: Mapped[datetime | None]
    last_sign_in_at: Mapped[datetime | None]


class StaffUser(TenantOwned, Timestamps, Base):
    __tablename__ = "staff_user"
    __table_args__ = tenant_args(
        *tfk("identity_id", "identity", index=False),
        UniqueConstraint("tenant_id", "identity_id", name="uq_staff_user_identity"),
        *tfk("role_id", "role"),
        Index(None, "tenant_id", "linked_resource_id"),
        *tfk("linked_resource_id", "resource", index=False),  # the trainer resource (data-model-core 9.8)
        enum_check("ip_policy", IpPolicy),
    )

    identity_id: Mapped[UUID]
    role_id: Mapped[UUID]  # exactly one role per user (PLT-05)
    first_name: Mapped[str]
    last_name: Mapped[str]
    mobile_phone: Mapped[str | None]
    linked_resource_id: Mapped[UUID | None]  # FK is added by the resources migration (data-model-core 9.8)
    is_attendance_notified: Mapped[bool] = _false()
    ip_policy: Mapped[str] = enum_column(server_default=text("'any'"))
    has_all_location_access: Mapped[bool] = _false()
    is_system_support: Mapped[bool] = _false()
    access_expires_on: Mapped[date | None]
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    preferences: Mapped[dict] = mapped_column(JsonDict, server_default=text("'{}'"))

    # Read-only joins for responses; writes always set the id columns.
    identity: Mapped[Identity] = relationship(viewonly=True, lazy="joined")
    role: Mapped[Role] = relationship(viewonly=True, lazy="joined")
    location_access: Mapped[list["UserLocationAccess"]] = relationship(viewonly=True, lazy="selectin")
    overrides: Mapped[list["UserPermissionOverride"]] = relationship(viewonly=True, lazy="selectin")

    @property
    def display_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    # Flattened fields of the StaffUser API resource.
    @property
    def email(self) -> str:
        return self.identity.email

    @property
    def identity_status(self) -> str:
        return self.identity.status

    @property
    def last_sign_in_at(self) -> datetime | None:
        return self.identity.last_sign_in_at

    @property
    def location_ids(self) -> list[UUID]:
        return [access.location_id for access in self.location_access]

    @property
    def primary_location_id(self) -> UUID | None:
        return next((access.location_id for access in self.location_access if access.is_primary), None)

    @property
    def has_permission_overrides(self) -> bool:
        return bool(self.overrides)


class UserLocationAccess(TenantOwned, Timestamps, Base):
    __tablename__ = "user_location_access"
    __table_args__ = tenant_args(
        *tfk("staff_user_id", "staff_user", ondelete="CASCADE", index=False),
        *tfk("location_id", "location"),
        UniqueConstraint("tenant_id", "staff_user_id", "location_id", name="uq_user_location_access"),
        Index(
            "uq_user_location_access_primary",
            "tenant_id",
            "staff_user_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),  # fmt: skip
    )

    staff_user_id: Mapped[UUID]
    location_id: Mapped[UUID]
    is_primary: Mapped[bool] = _false()


class UserPermissionOverride(TenantOwned, Timestamps, Base):
    """Sparse delta against the role; any row marks the user as diverged (PLT-05)."""

    __tablename__ = "user_permission_override"
    __table_args__ = tenant_args(
        *tfk("staff_user_id", "staff_user", ondelete="CASCADE", index=False),
        UniqueConstraint(
            "tenant_id",
            "staff_user_id",
            "permission_key",
            "subject_id",
            name="uq_user_permission_override",
            postgresql_nulls_not_distinct=True,
        ),  # fmt: skip
    )

    staff_user_id: Mapped[UUID]
    permission_key: Mapped[str] = mapped_column(info={"audit": "value"})
    subject_type: Mapped[str | None] = enum_column()
    subject_id: Mapped[UUID | None]
    is_allowed: Mapped[bool]


class AuthToken(TenantOwned, Timestamps, Base):
    """Single-use emailed link. Only the hash is stored."""

    __tablename__ = "auth_token"
    __table_args__ = tenant_args(
        *tfk("identity_id", "identity", ondelete="CASCADE", index=False),
        UniqueConstraint("tenant_id", "token_hash", name="uq_auth_token_hash"),
        enum_check("purpose", TokenPurpose),
        Index(
            "ix_auth_token_pending",
            "tenant_id",
            "identity_id",
            "purpose",
            postgresql_where=text("consumed_at IS NULL"),
        ),  # fmt: skip
    )

    identity_id: Mapped[UUID | None]
    purpose: Mapped[str] = enum_column()
    token_hash: Mapped[str] = mapped_column(info={"audit": "never"})
    payload: Mapped[dict] = mapped_column(JsonDict, server_default=text("'{}'"))
    expires_at: Mapped[datetime]
    consumed_at: Mapped[datetime | None]


class AuthSession(TenantOwned, Timestamps, Base):
    """One row per sign-in: a 30-minute access token and a rotating refresh token, both hashed."""

    __tablename__ = "auth_session"
    __table_args__ = tenant_args(
        *tfk("identity_id", "identity", index=False),
        *tfk("impersonator_staff_user_id", "staff_user"),
        UniqueConstraint("tenant_id", "access_token_hash", name="uq_auth_session_access"),
        UniqueConstraint("tenant_id", "refresh_token_hash", name="uq_auth_session_refresh"),
        Index("ix_auth_session_live", "tenant_id", "identity_id", postgresql_where=text("revoked_at IS NULL")),
        Index(
            "ix_auth_session_previous_refresh",
            "tenant_id",
            "previous_refresh_token_hash",
            postgresql_where=text("previous_refresh_token_hash IS NOT NULL"),
        ),  # fmt: skip
        Index("ix_auth_session_purge", "absolute_expires_at"),
        enum_check("kind", SessionKind),
        CheckConstraint("(kind = 'impersonation') = (impersonator_staff_user_id IS NOT NULL)", name="impersonation"),
        CheckConstraint(
            "revoked_reason IN ('sign_out', 'rotation_reuse', 'password_reset', 'admin', 'expired', 'disabled')",
            name="revoked_reason",
        ),
    )

    identity_id: Mapped[UUID]
    kind: Mapped[str] = enum_column()
    access_token_hash: Mapped[str] = mapped_column(info={"audit": "never"})
    access_expires_at: Mapped[datetime]
    refresh_token_hash: Mapped[str | None] = mapped_column(info={"audit": "never"})
    previous_refresh_token_hash: Mapped[str | None] = mapped_column(info={"audit": "never"})
    refresh_rotated_at: Mapped[datetime | None]
    idle_expires_at: Mapped[datetime]
    absolute_expires_at: Mapped[datetime]
    mfa_verified_at: Mapped[datetime | None]
    elevated_until_at: Mapped[datetime | None]
    impersonator_staff_user_id: Mapped[UUID | None]
    target_client_id: Mapped[UUID | None]  # FK is added with the clients context
    revoked_at: Mapped[datetime | None]
    revoked_reason: Mapped[str | None] = enum_column()
    ip: Mapped[Any | None] = mapped_column(INET)
    user_agent: Mapped[str | None]
    last_seen_at: Mapped[datetime | None]
