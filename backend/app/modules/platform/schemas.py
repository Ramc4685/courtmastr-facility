"""Request and response models for the platform API (docs/api/openapi-core.yaml, tag platform)."""

from datetime import date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints, field_validator

Audience = Literal["staff", "client"]
ClientKind = Literal["web", "mobile"]
IpPolicy = Literal["any", "facility_networks"]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
WallTime = Annotated[str, StringConstraints(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]  # location-local HH:MM
ClosingTime = Annotated[str, StringConstraints(pattern=r"^(([01]\d|2[0-3]):[0-5]\d|24:00)$")]
CountryCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PageInfo(BaseModel):
    next_cursor: str | None
    has_more: bool
    total: int | None = None


class Page[T](BaseModel):
    data: list[T]
    page: PageInfo


class HealthStatus(BaseModel):
    status: Literal["ok", "degraded", "unavailable"]
    checks: dict[str, str] | None = None


# --- auth --------------------------------------------------------------------------------------------------


class SignInRequest(In):
    email: EmailStr
    password: str = Field(max_length=1024)
    audience: Audience = "staff"
    client_kind: ClientKind = "web"


class EmailLinkRequest(In):
    email: EmailStr
    audience: Audience = "staff"
    redirect_path: str | None = Field(None, max_length=500)


class TokenConsumeRequest(In):
    token: str = Field(max_length=200)
    new_password: str | None = Field(None, max_length=1024)
    client_kind: ClientKind = "web"


class RefreshRequest(In):
    refresh_token: str | None = Field(None, max_length=200)


class PasswordChange(In):
    current_password: str | None = Field(None, max_length=1024)
    new_password: str = Field(max_length=1024)


class PrincipalOut(Out):
    kind: Literal["staff", "client"]
    identity_id: UUID
    staff_user_id: UUID | None = None
    client_ids: list[UUID] = []  # filled by the clients context
    email: str
    display_name: str


class AuthSessionOut(Out):
    """Tokens appear in the body only for bearer clients (mobile); web gets HttpOnly cookies plus csrf_token."""

    id: UUID
    kind: Literal["web", "mobile", "impersonation"]
    principal: PrincipalOut
    access_token: str | None = None
    access_expires_at: datetime
    refresh_token: str | None = None
    idle_expires_at: datetime
    absolute_expires_at: datetime
    mfa_verified_at: datetime | None = None
    mfa_required: bool = False
    csrf_token: str | None = None


class OwnSession(Out):
    id: UUID
    kind: str
    created_at: datetime
    last_seen_at: datetime | None
    idle_expires_at: datetime
    absolute_expires_at: datetime
    ip: str | None
    user_agent: str | None
    is_current: bool = False

    @field_validator("ip", mode="before")
    @classmethod
    def _ip_text(cls, value: Any) -> str | None:
        return None if value is None else str(value)


# --- tenant ------------------------------------------------------------------------------------------------


class TenantOut(Out):
    id: UUID
    name: str
    slug: str
    status: str
    currency: str
    default_time_zone: str
    locale: str
    staff_mfa_policy: str
    trial_ends_on: date | None
    settings: dict[str, Any]


class TenantUpdate(In):
    name: Name | None = None
    default_time_zone: str | None = None
    locale: str | None = Field(None, pattern=r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
    currency: str | None = Field(None, pattern=r"^[A-Z]{3}$")
    settings: dict[str, Any] | None = None


class TenantOnboard(In):
    name: Name
    slug: str = Field(min_length=3, max_length=63)
    default_time_zone: str
    owner_email: EmailStr
    owner_first_name: Name
    owner_last_name: Name
    owner_password: str | None = Field(None, max_length=1024)
    currency: str = Field("USD", pattern=r"^[A-Z]{3}$")
    locale: str = "en-US"


class TenantOnboarded(BaseModel):
    tenant_id: UUID
    slug: str
    owner_staff_user_id: UUID
    owner_identity_id: UUID


# --- locations ---------------------------------------------------------------------------------------------


class LocationFields(In):
    public_name: Name | None = None
    slug: str | None = Field(None, max_length=63)
    address_line1: str | None = None
    address_line2: str | None = None
    city: str | None = None
    region: str | None = None
    postal_code: str | None = None
    phone: str | None = None
    email: EmailStr | None = None
    alert_email: EmailStr | None = None
    website_url: str | None = None
    membership_renewal_run_time: WallTime | None = None
    package_renewal_run_time: WallTime | None = None
    autopay_run_time: WallTime | None = None
    decline_email_mode: Literal["digest", "per_decline"] | None = None
    time_clock_rounding: Literal["none", "up", "down"] | None = None
    time_clock_rounding_min: Literal[5, 6, 10, 15, 30] | None = None
    accepted_card_brands: list[str] | None = None
    is_gdpr_mode: bool | None = None
    sort_order: int | None = None


class LocationCreate(LocationFields):
    name: Name
    time_zone: str
    country_code: CountryCode


class LocationUpdate(LocationFields):
    name: Name | None = None
    time_zone: str | None = None
    country_code: CountryCode | None = None


class LocationRef(Out):
    id: UUID
    name: str
    slug: str
    time_zone: str


class LocationOut(LocationRef):
    public_name: str
    address_line1: str | None
    address_line2: str | None
    city: str | None
    region: str | None
    postal_code: str | None
    country_code: str | None
    phone: str | None
    email: str | None
    alert_email: str | None
    website_url: str | None
    membership_renewal_run_time: str
    package_renewal_run_time: str
    autopay_run_time: str
    decline_email_mode: str
    time_clock_rounding: str
    time_clock_rounding_min: int | None
    accepted_card_brands: list[str]
    is_gdpr_mode: bool
    sort_order: int
    status: Literal["active", "inactive"]
    created_at: datetime
    updated_at: datetime


class FacilityHoursDay(Out):
    weekday: int = Field(ge=1, le=7, description="ISO, 1 = Monday")
    opens_time: WallTime | None = None
    closes_time: ClosingTime | None = None
    is_closed: bool


class FacilityHoursOut(Out):
    location_id: UUID
    days: list[FacilityHoursDay]


class FacilityHoursReplace(In):
    days: list[FacilityHoursDay]


class PublicLocation(Out):
    id: UUID
    slug: str
    public_name: str
    time_zone: str
    city: str | None
    region: str | None
    phone: str | None
    email: str | None
    facility_hours: list[FacilityHoursDay]
    logo_url: str | None = None


# --- RBAC --------------------------------------------------------------------------------------------------


class RoleRef(Out):
    id: UUID
    name: str
    system_key: str | None = None


class PermissionGrant(Out):
    """A null subject is the default for every subject of the key."""

    permission_key: str
    is_allowed: bool
    subject_type: Literal["reservation_type"] | None = None
    subject_id: UUID | None = None


class PermissionGrantsReplace(In):
    grants: list[PermissionGrant]


class EffectivePermission(BaseModel):
    key: str
    reach: Literal["all", "own"]
    subject_type: str | None = None
    subject_ids: list[UUID] | None = None  # null = all subjects
    source: Literal["role", "override"] = "role"


class PermissionDefinition(Out):
    key: str
    context: str
    label: str
    scope: Literal["tenant", "location", "client"]
    flags: list[str]
    accepts_own_reach: bool
    subject_type: str | None
    entitlement: str | None


class RoleOut(RoleRef):
    description: str | None
    is_system: bool
    cloned_from_role_id: UUID | None
    default_ip_policy: IpPolicy
    staff_user_count: int | None = None
    permissions: list[PermissionGrant] | None = None  # only on the single-resource read


class RoleCreate(In):
    name: Name
    description: str | None = None
    clone_from_role_id: UUID | None = None
    default_ip_policy: IpPolicy = "any"


class RoleUpdate(In):
    name: Name | None = None
    description: str | None = None
    default_ip_policy: IpPolicy | None = None


# --- staff users -------------------------------------------------------------------------------------------


class StaffUserOut(Out):
    id: UUID
    identity_id: UUID
    email: str
    first_name: str
    last_name: str
    mobile_phone: str | None
    role: RoleRef
    identity_status: str
    is_active: bool
    has_all_location_access: bool
    location_ids: list[UUID]
    primary_location_id: UUID | None
    linked_resource_id: UUID | None
    is_attendance_notified: bool
    ip_policy: IpPolicy
    access_expires_on: date | None
    has_permission_overrides: bool
    last_sign_in_at: datetime | None
    created_at: datetime


class StaffUserInvite(In):
    email: EmailStr
    first_name: Name
    last_name: Name
    mobile_phone: str | None = None
    role_id: UUID
    has_all_location_access: bool = False
    location_ids: list[UUID] = []
    primary_location_id: UUID | None = None
    linked_resource_id: UUID | None = None
    access_expires_on: date | None = None


class StaffUserUpdate(In):
    first_name: Name | None = None
    last_name: Name | None = None
    mobile_phone: str | None = None
    linked_resource_id: UUID | None = None
    is_attendance_notified: bool | None = None
    ip_policy: IpPolicy | None = None
    access_expires_on: date | None = None


class StaffUserRoleAssign(In):
    role_id: UUID
    reset_overrides: bool = True


class StaffUserLocationsAssign(In):
    has_all_location_access: bool
    location_ids: list[UUID] = []
    primary_location_id: UUID | None = None


class StaffUserPermissions(Out):
    staff_user_id: UUID
    role: RoleRef
    effective: list[EffectivePermission]
    overrides: list[PermissionGrant]
    is_diverged_from_role: bool


class Me(Out):
    principal: PrincipalOut
    tenant: TenantOut
    role: RoleRef | None
    permissions: list[EffectivePermission] | None
    has_all_location_access: bool | None = None
    locations: list[LocationRef] | None = None
    primary_location_id: UUID | None = None
    entitlements: list[str] = []
    linked_resource_id: UUID | None = None


# --- audit -------------------------------------------------------------------------------------------------


class AuditEventOut(Out):
    id: UUID
    occurred_at: datetime
    actor_type: str
    actor_id: UUID | None
    actor_label: str
    location_id: UUID | None
    action: str
    entity_type: str
    entity_id: UUID
    changes: dict[str, Any]
    reason: str | None
    request_id: str | None
