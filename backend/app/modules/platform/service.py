"""platform service: tenant profile, locations, facility hours, the audit trail and tenant onboarding.

Sign-in and sessions live in auth.py; staff users and roles in staff.py. Together these three files are the
only entry points for routers, jobs and other contexts.
"""

import re
from datetime import date
from uuid import UUID
from zoneinfo import ZoneInfo, available_timezones

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core import audit, clock, context, events, networks
from app.core.audit import AuditEvent
from app.core.auth import Principal, authorize, passwords, scope_query, system_principal
from app.core.db import platform as platform_db
from app.core.db.session import tenant_session
from app.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from app.core.ids import new_id
from app.core.pagination import ListQuery, paginate
from app.core.settings import get_settings
from app.modules.platform import entitlements, staff
from app.modules.platform.events import LocationCreated, TenantCreated
from app.modules.platform.models import (
    FacilityHours,
    Identity,
    Location,
    StaffUser,
    Tenant,
    TenantCounter,
    UserLocationAccess,
)

_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_DEFAULT_HOURS = ("06:00", "22:00")  # our default; the reference publishes none


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def check_time_zone(value: str, pointer: str) -> None:
    if value not in available_timezones():
        raise ValidationFailed(f"{value} is not an IANA time zone.", pointer=pointer)


def _check_slug(value: str) -> None:
    if not _SLUG.fullmatch(value) or len(value) > 63:
        raise ValidationFailed("Use lowercase letters, digits and single hyphens.", pointer="/slug")


# --- tenant ------------------------------------------------------------------------------------------------


def get_tenant(session: Session) -> Tenant:
    return session.get(Tenant, session.info["tenant_id"])


def update_tenant(session: Session, principal: Principal, data: dict) -> Tenant:
    authorize(principal, "platform.tenant.update")
    tenant = get_tenant(session)
    if "default_time_zone" in data:
        check_time_zone(data["default_time_zone"], "/default_time_zone")
    # currency becomes immutable once any charge exists; that guard arrives with the billing context.
    for field, value in data.items():
        setattr(tenant, field, value)
    audit.record(session, "platform.tenant.update", tenant, changes=audit.diff(tenant))
    session.flush()
    return tenant


def minor_age(session: Session) -> int:
    """Internal: under this age a client is a minor (key `minor_age` in tenant.settings, default 18; owner
    question 21). Written only through update_tenant; a missing or unusable value reads as 18."""
    value = (get_tenant(session).settings or {}).get("minor_age", 18)
    return value if type(value) is int and 1 <= value <= 99 else 18


# --- security settings (PLT-07) -----------------------------------------------------------------------------


_MFA_STRENGTH = {"optional": 0, "privileged": 1, "all": 2}


def _security_view(tenant) -> dict:
    return {
        "staff_ip_allowlist": [str(net) for net in tenant.staff_ip_allowlist],
        "staff_mfa_policy": tenant.staff_mfa_policy,
        "staff_idle_timeout_min": tenant.staff_idle_timeout_min or get_settings().auth.sessions["staff_web"].idle_min,
    }


def get_security_settings(session: Session, principal: Principal) -> dict:
    authorize(principal, "platform.security.manage")
    return _security_view(get_tenant(session))


def update_security_settings(session: Session, principal: Principal, data: dict) -> dict:
    """Staff IP allow-list, MFA policy and staff idle timeout. The key carries `+`, so the caller re-authenticated
    in the last 10 minutes. A non-empty allow-list must contain the caller's own address, so nobody can lock
    themselves (or an Owner) out from where they stand; an empty list lifts the restriction. Weakening the MFA
    policy is for an Owner only (owner decision 3)."""
    authorize(principal, "platform.security.manage")
    tenant = get_tenant(session)
    policy = data.get("staff_mfa_policy")
    if policy and _MFA_STRENGTH[policy] < _MFA_STRENGTH[tenant.staff_mfa_policy] and not principal.is_owner:
        raise PermissionDenied("Only an Owner can relax the two-step verification policy.", code="owner-only")
    policy_changes = {}  # policy values are not personal data: audited as values
    if policy and policy != tenant.staff_mfa_policy:
        policy_changes["staff_mfa_policy"] = [tenant.staff_mfa_policy, policy]
        tenant.staff_mfa_policy = policy
    idle = data.get("staff_idle_timeout_min")
    if idle is not None and idle != tenant.staff_idle_timeout_min:
        policy_changes["staff_idle_timeout_min"] = [tenant.staff_idle_timeout_min, idle]
        tenant.staff_idle_timeout_min = idle
    before = [str(net) for net in tenant.staff_ip_allowlist]
    if data.get("staff_ip_allowlist") is not None:
        allowed = networks.normalize(data["staff_ip_allowlist"], "/staff_ip_allowlist")
        if allowed and not networks.contains(allowed, context.client_ip.get()):
            raise ValidationFailed(
                f"Add the address you are using now ({context.client_ip.get() or 'unknown'}), or you would be locked out.",
                code="ip-allowlist-excludes-you", pointer="/staff_ip_allowlist",
            )  # fmt: skip
        tenant.staff_ip_allowlist = allowed
    after = [str(net) for net in tenant.staff_ip_allowlist]
    if after != before:
        policy_changes["staff_ip_allowlist"] = [before, after]
    if policy_changes:
        audit.record(session, "platform.security.manage", tenant, changes=policy_changes)
    session.flush()
    return _security_view(tenant)


# --- locations ---------------------------------------------------------------------------------------------


def list_locations(session: Session, principal: Principal, query: ListQuery) -> dict:
    """Locations the caller may act in. Reading needs no key (configuration read)."""
    return paginate(
        session,
        scope_query(select(Location), principal, Location.id),
        query,
        id_column=Location.id,
        sort_fields={"name": Location.name, "sort_order": Location.sort_order, "created_at": Location.created_at},
        default_sort="sort_order,name",
        filter_fields={"status": Location.status},
        search=(Location.name, Location.public_name, Location.city),
    )


def list_public_locations(session: Session, query: ListQuery) -> dict:
    page = paginate(
        session, select(Location).where(Location.status == "active"), query, id_column=Location.id,
        sort_fields={"public_name": Location.public_name, "sort_order": Location.sort_order},
        default_sort="sort_order,public_name",
    )  # fmt: skip
    hours = _hours_by_location(session, [location.id for location in page["data"]])
    page["data"] = [
        {**{c.key: getattr(loc, c.key) for c in Location.__table__.columns}, "facility_hours": hours.get(loc.id, [])}
        for loc in page["data"]
    ]
    return page


def get_location(session: Session, principal: Principal, location_id: UUID) -> Location:
    location = session.get(Location, location_id)
    in_scope = principal.kind == "system" or principal.location_ids is None or location_id in principal.location_ids
    if location is None or not in_scope:
        raise NotFound()
    return location


def create_location(session: Session, principal: Principal, data: dict) -> Location:
    """Create a location and its seven facility_hours rows."""
    authorize(principal, "platform.location.create")
    entitlements.enforce_limit(session, "locations")
    check_time_zone(data["time_zone"], "/time_zone")
    data = {
        "public_name": data["name"],
        "slug": slugify(data["name"]),
        **{k: v for k, v in data.items() if v is not None},
    }
    _check_slug(data["slug"])
    location = Location(**data)
    session.add(location)
    session.flush()
    opens, closes = _DEFAULT_HOURS
    session.add_all(
        FacilityHours(location_id=location.id, weekday=day, opens_time=opens, closes_time=closes) for day in range(1, 8)
    )
    if principal.kind == "staff" and principal.location_ids is not None:
        # The creator is location-limited, so without this row the new location would be invisible to them.
        session.add(UserLocationAccess(staff_user_id=principal.staff_user_id, location_id=location.id))
    audit.record(
        session,
        "platform.location.create",
        location,
        location_id=location.id,
        changes={"time_zone": [None, location.time_zone]},
    )
    events.publish(session, LocationCreated(location_id=location.id), location.id)
    session.flush()
    return location


def update_location(session: Session, principal: Principal, location_id: UUID, data: dict) -> Location:
    location = get_location(session, principal, location_id)
    authorize(principal, "platform.location.update", location_id=location.id)
    if "time_zone" in data:
        check_time_zone(data["time_zone"], "/time_zone")
    if "slug" in data:
        _check_slug(data["slug"])
    for field, value in data.items():
        setattr(location, field, value)
    audit.record(session, "platform.location.update", location, location_id=location.id, changes=audit.diff(location))
    session.flush()
    return location


def archive_location(session: Session, principal: Principal, location_id: UUID) -> Location:
    """Set inactive; a location is never deleted once referenced."""
    location = get_location(session, principal, location_id)
    authorize(principal, "platform.location.archive")
    if location.status != "active":
        raise Conflict("This location is already archived.")
    # location-has-future-bookings is checked here once the scheduling context exists.
    location.status = "inactive"
    audit.record(
        session,
        "platform.location.archive",
        location,
        location_id=location.id,
        changes={"status": ["active", "inactive"]},
    )
    session.flush()
    return location


def _hours_by_location(session: Session, location_ids: list[UUID]) -> dict[UUID, list[FacilityHours]]:
    grouped: dict[UUID, list[FacilityHours]] = {}
    rows = session.scalars(
        select(FacilityHours).where(FacilityHours.location_id.in_(location_ids)).order_by(FacilityHours.weekday)
    )
    for row in rows:
        grouped.setdefault(row.location_id, []).append(row)
    return grouped


def get_facility_hours(session: Session, principal: Principal, location_id: UUID) -> dict:
    location = get_location(session, principal, location_id)
    return {"location_id": location.id, "days": _hours_by_location(session, [location.id]).get(location.id, [])}


def replace_facility_hours(session: Session, principal: Principal, location_id: UUID, days: list[dict]) -> dict:
    """Replace the whole week: exactly one entry per ISO weekday."""
    location = get_location(session, principal, location_id)
    authorize(principal, "platform.location.update", location_id=location.id)
    if sorted(day["weekday"] for day in days) != list(range(1, 8)):
        raise ValidationFailed("Send exactly one entry for each weekday 1 to 7.", pointer="/days")
    for index, day in enumerate(days):
        opens, closes = day.get("opens_time"), day.get("closes_time")
        if not day["is_closed"] and not (opens and closes and closes > opens):  # HH:MM compares correctly as text
            raise ValidationFailed("An open day needs opens_time before closes_time.", pointer=f"/days/{index}")
    session.execute(delete(FacilityHours).where(FacilityHours.location_id == location.id))
    session.add_all(FacilityHours(location_id=location.id, **day) for day in days)
    audit.record(
        session, "platform.location.update", location, location_id=location.id, changes={"facility_hours": True}
    )
    session.flush()
    return get_facility_hours(session, principal, location_id)


def location_today(session: Session, location_id: UUID) -> date:
    """Today's date on the wall at a location (overview 3.7). Internal: for other contexts' date defaults."""
    location = session.get(Location, location_id)
    if location is None:
        raise NotFound()
    return clock.now().astimezone(ZoneInfo(location.time_zone)).date()


def earliest_today(session: Session) -> date:
    """The earliest "today" among the tenant's locations. Internal: a tenant-wide rule that takes effect
    "today" uses it, so it already holds at the location furthest behind UTC."""
    now = clock.now()
    zones = session.scalars(select(Location.time_zone).distinct())
    return min((now.astimezone(ZoneInfo(zone)).date() for zone in zones), default=now.date())


# --- counters ----------------------------------------------------------------------------------------------


def next_number(session: Session, counter_key: str) -> int:
    """The next value of a per-tenant counter (`booking_number`, `invoice`, `receipt`, `member_number`).
    Internal. The row lock is held to the end of the caller's transaction, so numbers are gapless: a rollback
    returns the number."""
    session.execute(
        pg_insert(TenantCounter)
        .values(id=new_id(), tenant_id=session.info["tenant_id"], counter_key=counter_key)
        .on_conflict_do_nothing(constraint="uq_tenant_counter")
    )
    counter = session.execute(
        select(TenantCounter).where(TenantCounter.counter_key == counter_key).with_for_update()
    ).scalar_one()
    value = counter.next_value
    counter.next_value = value + 1
    session.flush()
    return value


# --- audit trail -------------------------------------------------------------------------------------------


def list_audit_events(session: Session, principal: Principal, query: ListQuery) -> dict:
    """Staff activity trail (PLT-17), newest first. Location-limited callers see only their locations' rows;
    tenant-level rows (roles, settings) need all-location access."""
    authorize(principal, "platform.audit.read")
    return paginate(
        session,
        scope_query(select(AuditEvent), principal, AuditEvent.location_id),
        query,
        id_column=AuditEvent.id,
        sort_fields={"occurred_at": AuditEvent.occurred_at},
        default_sort="-occurred_at",
        filter_fields={
            "actor_id": AuditEvent.actor_id,
            "actor_type": AuditEvent.actor_type,
            "action": AuditEvent.action,
            "entity_type": AuditEvent.entity_type,
            "entity_id": AuditEvent.entity_id,
            "location_id": AuditEvent.location_id,
            "occurred_at": AuditEvent.occurred_at,
        },
    )


# --- signed-in profile -------------------------------------------------------------------------------------


def get_me(session: Session, principal: Principal) -> dict:
    """Everything the web app needs to route by role. Role and permissions are null for client principals."""
    me: dict = {
        "principal": principal,
        "tenant": get_tenant(session),
        "role": None,
        "permissions": None,
        # Usage counts are tenant figures, so only staff see the limits; everyone sees the features.
        "entitlements": entitlements.summary(session, limits=principal.kind == "staff"),
    }
    if principal.kind != "staff":
        if principal.kind == "client" and _client_ids_resolver is not None:
            me["principal"] = {
                "kind": "client", "identity_id": principal.identity_id, "email": principal.email,
                "display_name": principal.display_name,
                "client_ids": _client_ids_resolver(session, principal.identity_id),
            }  # fmt: skip
        return me
    staff_user = session.get(StaffUser, principal.staff_user_id)
    locations = session.scalars(
        scope_query(select(Location), principal, Location.id).order_by(Location.sort_order, Location.name)
    )
    view = staff._permissions_view(session, staff_user)
    return me | {
        "role": staff_user.role,
        "permissions": view["effective"],
        "has_all_location_access": principal.location_ids is None,
        "locations": list(locations),
        "primary_location_id": next((a.location_id for a in staff_user.location_access if a.is_primary), None),
        "linked_resource_id": staff_user.linked_resource_id,
    }


# --- onboarding --------------------------------------------------------------------------------------------


def onboard_tenant(
    *,
    name: str,
    slug: str,
    default_time_zone: str,
    owner_email: str,
    owner_first_name: str,
    owner_last_name: str,
    owner_password: str | None = None,
    currency: str = "USD",
    locale: str = "en-US",
) -> dict:
    """Create a tenant and its first Owner. Opens its own transactions: the global rows go in as fh_platform,
    then roles and the owner are seeded inside tenant_session (ADR 0001 section 4).

    With a password the owner is active at once; without one they receive an invite link.
    """
    _check_slug(slug)
    check_time_zone(default_time_zone, "/default_time_zone")
    if owner_password:
        passwords.check_policy(owner_password, forbidden=(owner_email, owner_first_name, owner_last_name))
    tenant_id = new_id()
    platform_db.provision_tenant(
        tenant_id, name=name, slug=slug, time_zone=default_time_zone, currency=currency, locale=locale
    )
    try:
        with tenant_session(tenant_id, actor=system_principal("platform.onboard_tenant")) as session:
            get_tenant(session).subscription_plan_id = entitlements.default_plan(session).id
            roles = staff.ensure_system_roles(session)
            identity = Identity(kind="staff", email=owner_email, status="invited")
            if owner_password:
                identity.status, identity.email_verified_at = "active", clock.now()
                identity.password_hash, identity.password_changed_at = (
                    passwords.hash_password(owner_password),
                    clock.now(),
                )
            session.add(identity)
            session.flush()
            owner = StaffUser(
                identity_id=identity.id, role_id=roles["owner"].id, first_name=owner_first_name,
                last_name=owner_last_name, has_all_location_access=True,
            )  # fmt: skip
            session.add(owner)
            session.flush()
            if not owner_password:
                staff._send_invite(session, identity)
            tenant = get_tenant(session)
            audit.record(session, "platform.tenant.create", tenant)
            events.publish(session, TenantCreated(tenant_id=tenant_id), tenant_id)
            return {
                "tenant_id": tenant_id,
                "slug": slug,
                "owner_staff_user_id": owner.id,
                "owner_identity_id": identity.id,
            }
    except BaseException:
        platform_db.unprovision_tenant(tenant_id)
        raise


# --- internal: for the clients context ---------------------------------------------------------------------

_client_ids_resolver = None


def register_client_ids_resolver(resolver) -> None:
    """clients registers how a client identity maps to client ids, so /me can fill PrincipalOut.client_ids."""
    global _client_ids_resolver
    _client_ids_resolver = resolver


def location_exists(session: Session, location_id: UUID) -> bool:
    return session.get(Location, location_id) is not None


def staff_user_exists(session: Session, staff_user_id: UUID) -> bool:
    return session.get(StaffUser, staff_user_id) is not None


def staff_user_works_at(session: Session, staff_user_id: UUID, location_id: UUID) -> bool:
    """Whether an active staff user may work at a location (all-location access or an access row). Internal:
    staff checks a shift's or time entry's employee against the record's location."""
    user = session.get(StaffUser, staff_user_id)
    if user is None or not user.is_active:
        return False
    return user.has_all_location_access or location_id in user.location_ids


def location_name(session: Session, location_id: UUID) -> str:
    """Internal: the display name for messages and notices."""
    name = session.scalar(select(Location.name).where(Location.id == location_id))
    if name is None:
        raise NotFound()
    return name


def active_staff_emails(session: Session, staff_user_ids) -> dict[UUID, str]:
    """Internal: sign-in email of each active staff user among the ids (engagement's staff alerts)."""
    rows = session.execute(
        select(StaffUser.id, Identity.email)
        .join(Identity, Identity.id == StaffUser.identity_id)
        .where(StaffUser.id.in_(list(staff_user_ids)), StaffUser.is_active)
    )
    return {row.id: row.email for row in rows}


def disable_client_identity(session: Session, identity_id: UUID, status: str = "disabled") -> None:
    """A client identity with no active access row left is disabled (or marked merged) and signed out."""
    from app.modules.platform import auth

    identity = session.get(Identity, identity_id)
    if identity is not None and identity.kind == "client" and identity.status in ("active", "invited"):
        identity.status = status
        auth.revoke_sessions(session, identity_id, "disabled")


def enable_client_identity(session: Session, identity_id: UUID) -> None:
    identity = session.get(Identity, identity_id)
    if identity is not None and identity.kind == "client" and identity.status == "disabled":
        identity.status = "active" if identity.email_verified_at else "invited"


def is_staff_address(session: Session, email: str) -> bool:
    """Whether a staff login uses this address (internal: engagement keeps staff mail off client records)."""
    return (
        session.scalar(select(Identity.id).where(Identity.kind == "staff", Identity.email == email).limit(1))
        is not None
    )


def find_client_identity(session: Session, email: str) -> Identity | None:
    return session.scalar(select(Identity).where(Identity.kind == "client", Identity.email == email))


def create_client_identity(session: Session, email: str) -> Identity:
    identity = Identity(kind="client", email=email, status="invited")
    session.add(identity)
    session.flush()
    return identity


def delete_client_identity(session: Session, identity_id: UUID) -> None:
    """GDPR erasure: the sign-in identity of an erased client goes, with its sessions and link tokens."""
    from app.modules.platform.models import AuthSession, AuthToken

    session.execute(delete(AuthSession).where(AuthSession.identity_id == identity_id))
    session.execute(delete(AuthToken).where(AuthToken.identity_id == identity_id))
    session.execute(delete(Identity).where(Identity.id == identity_id, Identity.kind == "client"))


# --- staff user <-> trainer resource (internal; used by resources and scheduling for `own` reach) ----------


def linked_resource_id(session: Session, staff_user_id: UUID | None) -> UUID | None:
    """The trainer resource a staff user's own calendar is (rbac-matrix 3.2). Internal."""
    from app.modules.platform.models import StaffUser

    return session.scalar(select(StaffUser.linked_resource_id).where(StaffUser.id == staff_user_id))


def set_linked_resource(session: Session, staff_user_id: UUID, resource_id: UUID) -> None:
    """Point a staff user at their trainer resource. Internal: resources.create_resource authorizes. An existing
    link to another resource is never overwritten silently (W2-03): unlink it first."""
    from app.modules.platform.models import StaffUser

    user = session.get(StaffUser, staff_user_id)
    if user is None:
        raise ValidationFailed("Unknown staff user.", pointer="/staff_user_id")
    if user.linked_resource_id not in (None, resource_id):
        raise Conflict("That staff user already has a trainer calendar.", code="already-linked")
    user.linked_resource_id = resource_id
    session.flush()


def staff_user_names(session: Session, staff_user_ids) -> dict[UUID, str]:
    """Display names of staff users by id, for another context's read model (payroll, shifts). Internal."""
    ids = list(staff_user_ids)
    rows = session.execute(
        select(StaffUser.id, StaffUser.first_name, StaffUser.last_name).where(StaffUser.id.in_(ids))
    ).all() if ids else []  # fmt: skip
    return {row[0]: f"{row[1]} {row[2]}" for row in rows}


def location_time_zone(session: Session, location_id: UUID) -> str:
    """IANA zone of a location (overview 3.7). Internal: every "day" and wall-time rule of a context uses it."""
    zone = session.scalar(select(Location.time_zone).where(Location.id == location_id))
    if zone is None:
        raise NotFound()
    return zone
