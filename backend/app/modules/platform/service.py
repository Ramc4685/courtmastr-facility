"""platform service: tenant profile, locations, facility hours, the audit trail and tenant onboarding.

Sign-in and sessions live in auth.py; staff users and roles in staff.py. Together these three files are the
only entry points for routers, jobs and other contexts.
"""

import re
from uuid import UUID
from zoneinfo import available_timezones

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core import audit, clock, events
from app.core.audit import AuditEvent
from app.core.auth import Principal, authorize, passwords, scope_query, system_principal
from app.core.db import platform as platform_db
from app.core.db.session import tenant_session
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.ids import new_id
from app.core.pagination import ListQuery, paginate
from app.modules.platform import staff
from app.modules.platform.events import LocationCreated, TenantCreated
from app.modules.platform.models import FacilityHours, Identity, Location, StaffUser, Tenant, UserLocationAccess

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
        "entitlements": [],
    }
    if principal.kind != "staff":
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
