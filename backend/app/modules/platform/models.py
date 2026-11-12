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
    LargeBinary,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import CIDR, CITEXT, INET
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
    MFA_CHALLENGE = "mfa_challenge"  # the pending sign-in between the first and second factor (S2)
    OIDC_STATE = "oidc_state"  # an OIDC round trip in flight: state, nonce and PKCE verifier (S3)
    OIDC_LINK = "oidc_link"  # an emailed confirmation of a first OIDC sign-in: issuer + subject to link (S3)


class SessionKind(StrEnum):
    WEB = "web"
    MOBILE = "mobile"
    IMPERSONATION = "impersonation"


def _false() -> Mapped[bool]:
    return mapped_column(server_default=text("false"))


# --- 2.1 Tenancy -----------------------------------------------------------------------------------------


class SubscriptionPlan(Timestamps, Base):
    """Global catalogue of our own tiers (PLT-14); no RLS, fh_app has SELECT only, rows come from migrations.
    `limits` maps a limit key to a count (a missing key is unlimited); `features` are feature keys. Both are
    validated against `platform.entitlements` in code."""

    __tablename__ = "subscription_plan"
    __table_args__ = (UniqueConstraint("code", name="uq_subscription_plan_code"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id, server_default=text("app.uuid_v7()"))
    code: Mapped[str]
    name: Mapped[str]
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    features: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    limits: Mapped[dict] = mapped_column(JsonDict, server_default=text("'{}'"))


class Tenant(Timestamps, Base):
    """Global row: id is the tenant id. Policy is id = app.current_tenant_id(); inserted only by fh_platform."""

    __tablename__ = "tenant"
    __pinned__ = True  # core.db.session._pin: kept for the session, read on every request
    __table_args__ = (
        UniqueConstraint("slug", name="uq_tenant_slug"),
        enum_check("status", TenantStatus),
        enum_check("staff_mfa_policy", MfaPolicy),
        CheckConstraint("staff_idle_timeout_min BETWEEN 15 AND 60", name="staff_idle_timeout_min"),
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
    # Staff may act only from these networks when it is non-empty; no role bypasses it (PLT-07).
    staff_ip_allowlist: Mapped[list[Any]] = mapped_column(ARRAY(CIDR), server_default=text("'{}'"))
    # Staff web idle limit in minutes, 15 to 60 (security-baseline 5.1); NULL is the configured default.
    staff_idle_timeout_min: Mapped[int | None] = mapped_column(info={"audit": "value"})
    # PLT-16: the stricter privacy defaults (explicit marketing consent, shorter retention); platform.privacy.
    is_gdpr_mode: Mapped[bool] = mapped_column(server_default=text("false"), info={"audit": "value"})


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
    __pinned__ = True  # core.db.session._pin
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
    failed_window_started_at: Mapped[datetime | None]  # failures count inside one lockout window
    locked_until_at: Mapped[datetime | None]
    lockout_count: Mapped[int] = mapped_column(server_default=text("0"))  # doubles the next lockout
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


class MfaFactor(TenantOwned, Timestamps, Base):
    """A second factor (ADR 0002 section 6). TOTP only; the secret is AES-GCM sealed with the tenant id as
    associated data and never logged or audited. Unconfirmed until the first code is checked."""

    __tablename__ = "mfa_factor"
    __table_args__ = tenant_args(
        *tfk("identity_id", "identity", ondelete="CASCADE", index=False),
        UniqueConstraint("tenant_id", "identity_id", "kind", name="uq_mfa_factor_identity_kind"),
        CheckConstraint("kind IN ('totp')", name="kind"),
    )

    identity_id: Mapped[UUID]
    kind: Mapped[str] = mapped_column(server_default=text("'totp'"))
    secret_encrypted: Mapped[str] = mapped_column(info={"audit": "never"})
    confirmed_at: Mapped[datetime | None]
    last_used_step: Mapped[int | None] = mapped_column(BigInteger)  # a used 30 s step is never accepted again
    # Wrong codes have their own lockout, apart from the password one, so password guessing cannot lock the
    # second factor and redeeming a link cannot reset code guessing (same thresholds as the password lockout).
    failed_attempt_count: Mapped[int] = mapped_column(server_default=text("0"))
    failed_window_started_at: Mapped[datetime | None]
    locked_until_at: Mapped[datetime | None]
    lockout_count: Mapped[int] = mapped_column(server_default=text("0"))


class MfaRecoveryCode(TenantOwned, Timestamps, Base):
    """One of ten single-use recovery codes, stored as a keyed HMAC bound to the identity (core.crypto.mac)."""

    __tablename__ = "mfa_recovery_code"
    __table_args__ = tenant_args(
        *tfk("identity_id", "identity", ondelete="CASCADE", index=False),
        UniqueConstraint("tenant_id", "identity_id", "code_hash", name="uq_mfa_recovery_code"),
    )

    identity_id: Mapped[UUID]
    code_hash: Mapped[str] = mapped_column(info={"audit": "never"})
    used_at: Mapped[datetime | None]


class AuthSession(TenantOwned, Timestamps, Base):
    """One row per sign-in, every secret hashed. Web: one sliding session token in the session cookie plus a
    CSRF token. Mobile: a short access token and a rotating refresh token."""

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
            "revoked_reason IN ('sign_out', 'rotation_reuse', 'password_reset', 'admin', 'expired', 'disabled', "
            "'step_up', 'mfa_change')",
            name="revoked_reason",
        ),
    )

    identity_id: Mapped[UUID]
    kind: Mapped[str] = enum_column()
    access_token_hash: Mapped[str] = mapped_column(info={"audit": "never"})
    access_expires_at: Mapped[datetime]
    csrf_token_hash: Mapped[str | None] = mapped_column(info={"audit": "never"})  # web sessions only
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


# --- 2.4 OIDC sign-in (Phase 8 S3; ADR 0002 sections 3 and 9) ------------------------------------------------


class OidcPreset(StrEnum):
    GOOGLE = "google"
    MICROSOFT = "microsoft"
    GENERIC = "generic"


class IdentityProviderConfig(TenantOwned, Timestamps, Base):
    """A tenant's OpenID Connect provider for staff sign-in. The client secret is sealed with core.crypto (tenant
    id as associated data): never returned by the API, never logged or audited. Deviation from data-model-core:
    the sealed secret lives on the row, not as a secret-store reference (no secret store in v1), and the issuer
    is the natural key (one provider per issuer and audience) instead of a separate provider_key."""

    __tablename__ = "identity_provider_config"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", "audience", "issuer_url", name="uq_identity_provider_config"),
        CheckConstraint("audience IN ('staff', 'client')", name="audience"),
        enum_check("preset", OidcPreset),
    )

    audience: Mapped[str] = mapped_column(server_default=text("'staff'"))
    preset: Mapped[str] = enum_column()
    display_name: Mapped[str]
    issuer_url: Mapped[str] = mapped_column(info={"audit": "value"})
    client_id: Mapped[str] = mapped_column(info={"audit": "value"})
    client_secret_encrypted: Mapped[str] = mapped_column(info={"audit": "never"})
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{openid,email,profile}'"))
    allowed_email_domains: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))
    asserts_mfa: Mapped[bool] = _false()
    is_enabled: Mapped[bool] = mapped_column(server_default=text("true"))


class ExternalLogin(TenantOwned, Timestamps, Base):
    """An identity's link to an OIDC account: issuer and subject, stored on the first verified-email match and
    matched on afterwards. One link per identity and issuer, so a second account at the same provider that
    happens to carry the same email cannot take over."""

    __tablename__ = "external_login"
    __table_args__ = tenant_args(
        *tfk("identity_id", "identity", ondelete="CASCADE", index=False),
        UniqueConstraint("tenant_id", "issuer", "subject", name="uq_external_login"),
        UniqueConstraint("tenant_id", "identity_id", "issuer", name="uq_external_login_identity_issuer"),
    )

    identity_id: Mapped[UUID]
    issuer: Mapped[str] = mapped_column(info={"audit": "value"})
    subject: Mapped[str] = mapped_column(info={"audit": "flag"})
    last_used_at: Mapped[datetime | None]


# --- 2.6 Data-subject requests (IMP-04, PLT-16) --------------------------------------------------------------


class DsrKind(StrEnum):
    EXPORT = "export"
    ERASURE = "erasure"


class DsrStatus(StrEnum):
    REQUESTED = "requested"
    BLOCKED = "blocked"
    PROCESSING = "processing"
    COMPLETED = "completed"
    REJECTED = "rejected"
    FAILED = "failed"


class DataSubjectRequest(TenantOwned, Timestamps, Base):
    """A personal-data export or erasure for one client; each context contributes through registered handlers
    (app.modules.platform.privacy). `result_file_id` waits for stored_file: the export bundle is built on read."""

    __tablename__ = "data_subject_request"
    __table_args__ = tenant_args(
        *tfk("client_id", "client"),
        *tfk("requested_by_staff_user_id", "staff_user"),
        enum_check("kind", DsrKind),
        enum_check("status", DsrStatus),
        CheckConstraint(
            "kind <> 'erasure' OR status IN ('requested', 'blocked', 'rejected') OR confirmed_at IS NOT NULL",
            name="confirm",
        ),
    )

    client_id: Mapped[UUID]
    kind: Mapped[str] = enum_column()
    status: Mapped[str] = enum_column(server_default=text("'requested'"))
    requested_by_staff_user_id: Mapped[UUID]
    reason: Mapped[str | None]
    confirmed_at: Mapped[datetime | None]
    blockers: Mapped[list] = mapped_column(JsonDict, server_default=text("'[]'"))
    is_blocker_override: Mapped[bool] = mapped_column(server_default=text("false"))
    handler_results: Mapped[dict] = mapped_column(JsonDict, server_default=text("'{}'"))
    completed_at: Mapped[datetime | None]


class StoredFileStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    PURGED = "purged"


class UploaderType(StrEnum):
    STAFF = "staff"
    CLIENT = "client"
    API_KEY = "api_key"
    SYSTEM = "system"


class StoredFile(TenantOwned, Timestamps, Base):
    """Metadata of one object in file storage (data-model-core 2.2). Bytes live behind app.ports.storage under
    `object_key`; rows are written through app.modules.platform.files. Image variants and expiry columns are not
    created yet: nothing renders variants or expires files (README)."""

    __tablename__ = "stored_file"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", "object_key"),
        enum_check("status", StoredFileStatus),
        enum_check("uploaded_by_type", UploaderType),
        CheckConstraint("size_bytes >= 0", name="size_bytes"),
    )

    object_key: Mapped[str]
    purpose: Mapped[str] = enum_column()
    content_type: Mapped[str] = enum_column()
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str | None] = mapped_column(info={"audit": "value"})
    original_name: Mapped[str | None]
    status: Mapped[str] = enum_column(server_default=text("'pending'"))
    uploaded_by_type: Mapped[str] = enum_column()
    uploaded_by_id: Mapped[UUID | None]


# --- 2.5 Dead letters (ADR 0008 section 7) --------------------------------------------------------------------


class FailedJobResolution(StrEnum):
    REQUEUED = "requeued"
    DISCARDED = "discarded"


class FailedJob(TenantOwned, Timestamps, Base):
    """A background message that exhausted its retries, written by `core.jobs.FailedJobRecorder`. Args are ids
    and dates only (ADR 0008 section 2); the error is its class and first line, never a payload. Deviation from
    data-model-core 2.5: created_at and updated_at as on other mutable tables (resolution updates the row)."""

    __tablename__ = "failed_job"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", "message_id", name="uq_failed_job"),
        Index("ix_failed_job_open", "tenant_id", "failed_at", postgresql_where=text("resolved_at IS NULL")),
        enum_check("resolution", FailedJobResolution),
    )

    actor_name: Mapped[str] = mapped_column(info={"audit": "value"})
    queue: Mapped[str] = mapped_column(info={"audit": "value"})
    message_id: Mapped[str] = mapped_column(info={"audit": "value"})
    args: Mapped[list] = mapped_column(JsonDict)
    error_class: Mapped[str] = mapped_column(info={"audit": "value"})
    error_detail: Mapped[str | None]
    attempts: Mapped[int]
    failed_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    resolved_at: Mapped[datetime | None]
    resolution: Mapped[str | None] = enum_column()


# --- 2.1 Entitlements (PLT-14, PLT-09, PLT-13; platform/entitlements.py) --------------------------------------


class EntitlementSource(StrEnum):
    ADDON = "addon"  # bought on top of the plan
    PROMO = "promo"  # time-limited offer
    FLAG = "flag"  # per-tenant feature flag (PLT-09)
    MANUAL = "manual"  # the operator's own adjustment


class TenantEntitlement(TenantOwned, Timestamps, Base):
    """A per-tenant override of the plan, set by the operator: a feature turned on (or off, `is_enabled` false)
    or a limit replaced (`limit_value`, null = unlimited), in force from `starts_on` to `ends_on` inclusive.
    Tenant data under RLS; written only by the operator functions in `platform.entitlements`."""

    __tablename__ = "tenant_entitlement"
    __table_args__ = tenant_args(
        UniqueConstraint("tenant_id", "key", "source", "starts_on", name="uq_tenant_entitlement"),
        enum_check("source", EntitlementSource),
        CheckConstraint("ends_on IS NULL OR ends_on >= starts_on", name="dates"),
        CheckConstraint("limit_value IS NULL OR limit_value >= 0", name="limit_value"),
    )

    key: Mapped[str] = mapped_column(info={"audit": "value"})
    is_enabled: Mapped[bool] = mapped_column(server_default=text("true"), info={"audit": "value"})
    limit_value: Mapped[int | None] = mapped_column(info={"audit": "value"})
    source: Mapped[str] = enum_column()
    starts_on: Mapped[date] = mapped_column(info={"audit": "value"})
    ends_on: Mapped[date | None] = mapped_column(info={"audit": "value"})


# --- Phase 8 T2: logos (PLT-08), the tenant export bundle (IMP-04), support requests (ONB-03) -----------------


class Logo(TenantOwned, Timestamps, Base):
    """The tenant's logo (location_id NULL) or one location's (PLT-08). The image is a stored file under the public
    prefix, the only public-read objects (platform.branding)."""

    __tablename__ = "logo"
    __table_args__ = tenant_args(
        *tfk("location_id", "location", index=False),
        *tfk("file_id", "stored_file"),
        Index("uq_logo_tenant", "tenant_id", unique=True, postgresql_where=text("location_id IS NULL")),
        Index("uq_logo_location", "tenant_id", "location_id", unique=True,
              postgresql_where=text("location_id IS NOT NULL")),
    )  # fmt: skip

    location_id: Mapped[UUID | None]
    file_id: Mapped[UUID]


class TenantExportStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXPIRED = "expired"


class TenantExport(TenantOwned, Timestamps, Base):
    """A tenant-wide data export (IMP-04): a zip of one CSV per table, built by the chunked `run_tenant_export`
    job and kept as a stored file until `expires_at` (platform.tenant_export)."""

    __tablename__ = "tenant_export"
    __table_args__ = tenant_args(
        *tfk("requested_by_staff_user_id", "staff_user", index=False),
        *tfk("file_id", "stored_file"),
        enum_check("status", TenantExportStatus),
    )

    status: Mapped[str] = enum_column(server_default=text("'queued'"))
    requested_by_staff_user_id: Mapped[UUID]
    progress: Mapped[dict] = mapped_column(JsonDict, server_default=text("'{}'"))
    partial: Mapped[bytes | None] = mapped_column(LargeBinary, info={"audit": "never"})
    file_id: Mapped[UUID | None]
    row_count: Mapped[int | None] = mapped_column(info={"audit": "value"})
    error: Mapped[str | None]
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    expires_at: Mapped[datetime | None]


class SupportCategory(StrEnum):
    QUESTION = "question"
    PROBLEM = "problem"
    BILLING = "billing"
    IMPORT = "import"
    FEEDBACK = "feedback"


class SupportStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class SupportRequest(TenantOwned, Timestamps, Base):
    """A staff "Contact support" message (ONB-03), emailed to the operator address; the requester sees their own."""

    __tablename__ = "support_request"
    __table_args__ = tenant_args(
        *tfk("requested_by_staff_user_id", "staff_user", index=False),
        *tfk("screenshot_file_id", "stored_file"),
        enum_check("category", SupportCategory),
        enum_check("status", SupportStatus),
        Index("ix_support_request_mine", "tenant_id", "requested_by_staff_user_id", "id"),
    )

    requested_by_staff_user_id: Mapped[UUID]
    category: Mapped[str] = enum_column()
    message: Mapped[str]
    screenshot_file_id: Mapped[UUID | None]
    status: Mapped[str] = enum_column(server_default=text("'open'"))
    closed_at: Mapped[datetime | None]
