"""access check-in desk: stations, check-out and occupancy (CHK-07), booking a session from a check-in (CHK-04),
ID card templates and the member card (CHK-12, MEM-19).

CHK-21 (remediation) has no command here: the window takes the payment and the signature through billing's and
documents' own routes, under their own keys, and re-evaluates. Each alert carries the `action` that clears it
(`domain.evaluate.ALERT_ACTION`).

A visit nobody checks out ends at local midnight: it is open only while `local_on` is the location's today,
derived at read time, so no job writes anything (README, "Assumptions")."""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.core import audit, clock, events
from app.core.api import CONSTRAINT_CODES
from app.core.auth import Principal, authorize, authorize_tenant_wide
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.modules import clients, memberships, platform, programs, scheduling
from app.modules.access import events as ev
from app.modules.access.domain.evaluate import BOOK_EARLY, BOOK_LATE
from app.modules.access.models import (
    CARD_FIELDS,
    CheckIn,
    CheckInAttendance,
    CheckInStation,
    Credential,
    IdCardTemplate,
)

READ, CREATE, ASSIGN, SETTINGS = (
    "access.checkin.read", "access.checkin.create", "access.credential.assign", "access.settings.manage",
)  # fmt: skip
CHECK_OUT, ENROLL = "access.checkin.check_out", "scheduling.enrollment.create"
IS_OPEN = and_(CheckIn.checked_out_at.is_(None), CheckIn.result != "denied")  # and local_on is today
OCCUPANCY_LIMIT = 500  # people listed on the occupancy screen; the counts stay exact
CONSTRAINT_CODES["uq_check_in_station_name"] = "already-exists"
CONSTRAINT_CODES["uq_id_card_template_default"] = "already-exists"
# The card when no template is set up: the name and the number, with a photo slot.
BUILT_IN = {"id": None, "location_id": None, "name": "Standard", "shown_fields": ["name", "membership_number"],
            "has_photo": True, "is_default": True}  # fmt: skip


def _at_location(session: Session, principal: Principal, location_id: UUID) -> None:
    """A configuration read at one location: any staff working there; elsewhere or unknown, 404."""
    if principal.location_ids is not None and location_id not in principal.location_ids:
        raise NotFound()
    platform.service.location_time_zone(session, location_id)


def _known_location(session: Session, location_id: UUID) -> None:
    try:
        platform.service.location_time_zone(session, location_id)
    except NotFound:
        raise ValidationFailed("Unknown location.", pointer="/location_id") from None


def _check_in(session: Session, principal: Principal, check_in_id: UUID, key: str) -> CheckIn:
    row = session.get(CheckIn, check_in_id)
    if row is None:
        raise NotFound()
    authorize(principal, key, location_id=row.location_id)
    return row


def _today_or_ended(session: Session, row: CheckIn) -> None:
    if row.result == "denied":
        raise Conflict("This entry was denied, so there is no visit.", code="check-in-denied")
    if row.local_on != platform.service.location_today(session, row.location_id):
        raise Conflict("This visit ended at midnight.", code="visit-ended")


# --- stations (CHK-07) ---------------------------------------------------------------------------------------


def station_view(row: CheckInStation) -> dict:
    return {"id": row.id, "location_id": row.location_id, "name": row.name, "is_active": row.is_active}


def list_stations(session: Session, principal: Principal, location_id: UUID) -> list[dict]:
    _at_location(session, principal, location_id)
    rows = session.scalars(
        select(CheckInStation).where(CheckInStation.location_id == location_id).order_by(CheckInStation.name)
    )
    return [station_view(row) for row in rows]


def create_station(session: Session, principal: Principal, data: dict) -> dict:
    _known_location(session, data["location_id"])
    authorize(principal, SETTINGS, location_id=data["location_id"])
    row = CheckInStation(location_id=data["location_id"], name=data["name"], is_active=data["is_active"])
    session.add(row)
    session.flush()
    audit.record(session, SETTINGS, row, location_id=row.location_id, changes={"name": [None, row.name]})
    events.publish(session, ev.CheckInStationChanged(check_in_station_id=row.id, location_id=row.location_id), row.id)
    return station_view(row)


def update_station(session: Session, principal: Principal, station_id: UUID, data: dict) -> dict:
    row = session.get(CheckInStation, station_id)
    if row is None:
        raise NotFound()
    authorize(principal, SETTINGS, location_id=row.location_id)
    for key, value in data.items():
        if value is not None:
            setattr(row, key, value)
    audit.record(session, SETTINGS, row, location_id=row.location_id, changes=audit.diff(row))
    session.flush()
    events.publish(session, ev.CheckInStationChanged(check_in_station_id=row.id, location_id=row.location_id), row.id)
    return station_view(row)


def station_for_check_in(session: Session, station_id: UUID | None, location_id: UUID) -> UUID | None:
    """The station a staff check-in names: an active one at the check-in's location (422 otherwise)."""
    if station_id is None:
        return None
    row = session.get(CheckInStation, station_id)
    if row is None or row.location_id != location_id or not row.is_active:
        raise ValidationFailed("Unknown or inactive station at this location.", pointer="/check_in_station_id")
    return row.id


# --- check-out and occupancy (CHK-07) ------------------------------------------------------------------------


def check_out(session: Session, principal: Principal, check_in_id: UUID, data: dict) -> CheckIn:
    """Close the visit: every open entry of the client at the location today (a repeat scan is the same visit)."""
    row = _check_in(session, principal, check_in_id, CHECK_OUT)
    _today_or_ended(session, row)
    if row.checked_out_at is not None:
        raise Conflict("Already checked out.", code="already-checked-out")
    now = clock.now()
    at = data.get("checked_out_at") or now
    if not row.checked_in_at <= at <= now:
        raise ValidationFailed("Check-out falls between the check-in and now.", pointer="/checked_out_at")
    rows = session.scalars(
        select(CheckIn).where(
            CheckIn.client_id == row.client_id, CheckIn.location_id == row.location_id,
            CheckIn.local_on == row.local_on, IS_OPEN,
        ).with_for_update()
    )  # fmt: skip
    for entry in rows:
        entry.checked_out_at = max(at, entry.checked_in_at)
        audit.record(session, CHECK_OUT, entry, location_id=entry.location_id, changes={"checked_out_at": [None, True]})
        events.publish(session, ev.CheckedOut(
            check_in_id=entry.id, client_id=entry.client_id, location_id=entry.location_id), entry.id)  # fmt: skip
    session.flush()
    return row


def occupancy(session: Session, principal: Principal, location_id: UUID) -> dict:
    """Who is in now (the latest open entry per client today), the count, and the count per station."""
    platform.service.location_time_zone(session, location_id)
    authorize(principal, READ, location_id=location_id)
    today = platform.service.location_today(session, location_id)
    latest = (
        select(CheckIn.id, CheckIn.client_id, CheckIn.check_in_station_id, CheckIn.checked_in_at)
        .where(CheckIn.location_id == location_id, CheckIn.local_on == today, IS_OPEN)
        .ext(distinct_on(CheckIn.client_id))
        .order_by(CheckIn.client_id, CheckIn.checked_in_at.desc(), CheckIn.id.desc())
        .subquery()
    )
    names = {
        s.id: s.name for s in session.scalars(select(CheckInStation).where(CheckInStation.location_id == location_id))
    }
    counts = session.execute(
        select(latest.c.check_in_station_id, func.count()).group_by(latest.c.check_in_station_id)
    ).all()
    by_station = [{"check_in_station_id": k, "station_name": names.get(k), "count": n} for k, n in counts]
    by_station.sort(key=lambda s: (s["station_name"] is None, s["station_name"] or ""))
    rows = session.execute(
        select(latest).order_by(latest.c.checked_in_at.desc(), latest.c.id.desc()).limit(OCCUPANCY_LIMIT)
    ).all()
    people = clients.service.display_names(session, [r.client_id for r in rows])
    present = [
        {"check_in_id": r.id, "client_id": r.client_id, "checked_in_at": r.checked_in_at,
         "client_name": people.get(r.client_id, ""), "check_in_station_id": r.check_in_station_id,
         "station_name": names.get(r.check_in_station_id)}
        for r in rows
    ]  # fmt: skip
    count = sum(s["count"] for s in by_station)
    return {"location_id": location_id, "local_on": today, "count": count, "by_station": by_station,
            "present": present, "is_capped": count > len(present)}  # fmt: skip


# --- book a session from the window (CHK-04) -----------------------------------------------------------------


def book_session(session: Session, principal: Principal, check_in_id: UUID, data: dict) -> CheckIn:
    """Enrol the checked-in client into a session starting soon at the location and mark the place attended.
    The booking is programs' own (its gates: the place, the SCH-05 grant, free booking, the package)."""
    row = _check_in(session, principal, check_in_id, ENROLL)
    clients.service.load(session, principal, row.client_id, CREATE)
    _today_or_ended(session, row)
    if row.checked_out_at is not None:
        raise Conflict("Already checked out.", code="already-checked-out")
    try:
        seat = scheduling.service.get_session(session, data["session_id"])
    except NotFound:
        raise ValidationFailed("Unknown session.", pointer="/session_id") from None
    now = clock.now()
    if seat["location_id"] != row.location_id or seat["status"] != "confirmed":
        raise ValidationFailed("Choose a confirmed session at this location.", pointer="/session_id")
    if not now - BOOK_EARLY <= seat["starts_at"] <= now + BOOK_LATE:
        raise ValidationFailed("Choose a session starting soon.", pointer="/session_id")
    enrollment = programs.service.create_enrollment(session, principal, {
        "session_id": seat["id"], "client_id": row.client_id, "client_package_id": data.get("client_package_id"),
    })  # fmt: skip
    marked = programs.service.mark_attended_by_check_in(
        session, client_id=row.client_id, location_id=row.location_id, at=seat["starts_at"], early=timedelta(0),
        late=timedelta(0), source="check_in", staff_user_id=principal.staff_user_id, session_id=seat["id"],
    )  # fmt: skip
    for enrollment_id, session_id in marked:
        session.add(CheckInAttendance(
            check_in_id=row.id, target_id=enrollment_id, session_id=session_id,
            was_auto_booked=enrollment_id == enrollment.id,
        ))  # fmt: skip
    audit.record(
        session, ENROLL, row, location_id=row.location_id, changes={"booked_session_id": [None, str(seat["id"])]}
    )
    events.publish(session, ev.CheckInSessionBooked(
        check_in_id=row.id, client_id=row.client_id, location_id=row.location_id, enrollment_id=enrollment.id,
        session_id=seat["id"],
    ), row.id)  # fmt: skip
    session.flush()
    return row


# --- ID card templates and the member card (CHK-12, MEM-19) ----------------------------------------------------


def template_view(row: IdCardTemplate) -> dict:
    return {
        "id": row.id, "location_id": row.location_id, "name": row.name, "shown_fields": list(row.shown_fields),
        "has_photo": row.has_photo, "is_default": row.is_default,
    }  # fmt: skip


def _gate_template(principal: Principal, location_id: UUID | None) -> None:
    if location_id is None:
        authorize_tenant_wide(principal, SETTINGS)  # a tenant-wide card governs every location
    else:
        authorize(principal, SETTINGS, location_id=location_id)


def _fields(shown: list[str]) -> list[str]:
    return [f for f in CARD_FIELDS if f in set(shown)]  # one order on every card


def _clear_default(session: Session, location_id: UUID | None, own_id: UUID) -> None:
    where = IdCardTemplate.location_id.is_(None) if location_id is None else IdCardTemplate.location_id == location_id
    for row in session.scalars(
        select(IdCardTemplate).where(where, IdCardTemplate.id != own_id, IdCardTemplate.is_default)
    ):
        row.is_default = False
        audit.record(session, SETTINGS, row, location_id=row.location_id, changes={"is_default": [True, False]})
    session.flush()


def list_templates(session: Session, principal: Principal) -> list[dict]:
    """Tenant-wide templates and those of the caller's locations."""
    stmt = select(IdCardTemplate).order_by(IdCardTemplate.name, IdCardTemplate.id)
    if principal.location_ids is not None:
        stmt = stmt.where(IdCardTemplate.location_id.is_(None) | IdCardTemplate.location_id.in_(principal.location_ids))
    return [template_view(row) for row in session.scalars(stmt)]


def create_template(session: Session, principal: Principal, data: dict) -> dict:
    if data["location_id"] is not None:
        _known_location(session, data["location_id"])
    _gate_template(principal, data["location_id"])
    row = IdCardTemplate(
        location_id=data["location_id"], name=data["name"], shown_fields=_fields(data["shown_fields"]),
        has_photo=data["has_photo"], is_default=False,
    )  # fmt: skip
    session.add(row)
    session.flush()
    if data["is_default"]:
        _clear_default(session, row.location_id, row.id)
        row.is_default = True
    audit.record(session, SETTINGS, row, location_id=row.location_id, changes={"name": [None, row.name]})
    session.flush()
    events.publish(session, ev.IdCardTemplateChanged(id_card_template_id=row.id), row.id)
    return template_view(row)


def update_template(session: Session, principal: Principal, template_id: UUID, data: dict) -> dict:
    row = session.get(IdCardTemplate, template_id)
    if row is None:
        raise NotFound()
    _gate_template(principal, row.location_id)
    if data.get("shown_fields") is not None:
        data["shown_fields"] = _fields(data["shown_fields"])
    if data.get("is_default"):
        _clear_default(session, row.location_id, row.id)
    for key, value in data.items():
        if value is not None:
            setattr(row, key, value)
    audit.record(session, SETTINGS, row, location_id=row.location_id, changes=audit.diff(row))
    session.flush()
    events.publish(session, ev.IdCardTemplateChanged(id_card_template_id=row.id), row.id)
    return template_view(row)


def _template(session: Session, principal: Principal, template_id: UUID | None, location_id: UUID) -> dict:
    """The named template if the caller reaches it (404 otherwise), else the location's default, the tenant's,
    then the built-in card."""
    if template_id is not None:
        row = session.get(IdCardTemplate, template_id)
        reach = principal.location_ids
        if row is None or row.location_id is not None and reach is not None and row.location_id not in reach:
            raise NotFound()
        return template_view(row)
    for where in (IdCardTemplate.location_id == location_id, IdCardTemplate.location_id.is_(None)):
        row = session.scalar(select(IdCardTemplate).where(where, IdCardTemplate.is_default))
        if row is not None:
            return template_view(row)
    return dict(BUILT_IN)


def client_id_card(
    session: Session, principal: Principal, client_id: UUID, location_id: UUID | None, template_id: UUID | None
) -> dict:
    """The printable member card (MEM-19) as printed at `location_id` (default: the client's home location): the
    template's fields only, and the value its barcode encodes (the member number, else the newest active barcode
    credential)."""
    client = clients.service.load(session, principal, client_id, ASSIGN)
    location_id = location_id or client.home_location_id
    _at_location(session, principal, location_id)
    template = _template(session, principal, template_id, location_id)
    shown = template["shown_fields"]
    standing = (
        memberships.service.eligibility(session, client.id, platform.service.location_today(session, location_id))
        if {"membership_type", "expires_on"} & set(shown) else {}
    )  # fmt: skip
    # The same masking as the check-in card: the birth date needs the sensitive key, and the location's hidden
    # details need read_full_details (service._visible).
    from app.modules.access.service import FULL, access_settings_view  # service imports desk

    hidden = set() if principal.has(FULL) else set(access_settings_view(session, location_id)["hidden_detail_fields"])
    values = {
        "name": clients.service.display_name(client), "membership_number": client.member_number,
        "membership_type": standing.get("membership_name"),
        "expires_on": None if "membership_dates" in hidden else standing.get("end_on"),
        "date_of_birth": client.birth_on if principal.has("clients.client.read_sensitive") else None,
    }  # fmt: skip
    code = client.member_number or session.scalar(
        select(Credential.value)
        .where(Credential.client_id == client.id, Credential.kind == "barcode", Credential.status == "active")
        .order_by(Credential.issued_at.desc())
        .limit(1)
    )
    return {
        "client_id": client.id, "template": template, "code_value": code,
        "fields": [{"field": f, "value": None if values[f] is None else str(values[f])} for f in shown],
        # The clients photo route does its own permission check when the browser loads it (CLI-12).
        "photo_url": f"/api/v1/clients/{client.id}/photo" if template["has_photo"] and client.photo_file_id else None,
    }  # fmt: skip
