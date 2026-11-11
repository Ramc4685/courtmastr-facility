"""staff service: trainer and salesperson payees, pay and commission rules, job classifications, hourly rates,
the time clock, shifts, instructor assignment and payroll runs (build module 12, parity rows STF).

Staff users, roles and RBAC stay in `platform`; a trainer's calendar is a `resources` row and sessions are
`scheduling` bookings, reached only through those contexts' service functions. Payroll reads sale and charge
facts through the read functions packages, memberships, programs and billing expose for it (overview row
`staff`). Every command loads its row through a scoped loader (404 outside the caller's locations), then
authorizes the key on that row.
"""

import csv
import io
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from ipaddress import ip_address, ip_network
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core import audit, clock, context, events
from app.core.api import CONSTRAINT_CODES
from app.core.auth import Principal, authorize, scope_query
from app.core.auth.permissions import authorize_tenant_wide
from app.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.modules import billing, memberships, packages, platform, programs, resources, scheduling
from app.modules.platform import auth as platform_auth
from app.modules.staff.domain import pay
from app.modules.staff.events import PayrollRunFinalized, TimeEntryClosed, TrainerCreated
from app.modules.staff.models import (
    CommissionRule,
    JobClassification,
    PayRate,
    PayrollRun,
    PayStatement,
    PayStatementLine,
    Shift,
    StaffHourlyRate,
    StaffPayee,
    StaffSettings,
    TimeEntry,
)

PUNCH = "staff.time_entry.punch"
ENTRY_READ = "staff.time_entry.read"
ENTRY_MANAGE = "staff.time_entry.manage"
SHIFT_MANAGE = "staff.shift.manage"
PAY_READ = "staff.pay_rate.read"
PAY_MANAGE = "staff.pay_rate.manage"
STATEMENT_READ = "staff.pay_statement.read"
RUN_CREATE = "staff.payroll_run.create"
RUN_APPROVE = "staff.payroll_run.approve"
RUN_EXPORT = "staff.payroll_run.export"
PAYEE_MANAGE = "resources.resource.manage"  # a trainer payee is a calendar column (rbac-matrix 6.14 note)
SESSION_MANAGE = "scheduling.session.manage"
SCHEDULE_READ = "scheduling.booking.read"
MAX_WINDOW_DAYS = 62

CONSTRAINT_CODES["ex_time_entry_overlap"] = "time-entry-overlap"
CONSTRAINT_CODES["ex_shift_overlap"] = "shift-conflict"


def _everywhere(principal: Principal) -> bool:
    return principal.kind == "system" or principal.location_ids is None


def _scoped(session: Session, principal: Principal, model, row_id: UUID):
    """Load a location-owned row; missing or outside the caller's locations is 404. A tenant-wide row
    (location_id null) is visible only to a caller who reaches every location."""
    row = session.get(model, row_id)
    if row is None:
        raise NotFound()
    if not _everywhere(principal) and row.location_id not in principal.location_ids:
        raise NotFound()
    return row


def _location(session: Session, principal: Principal, location_id: UUID, pointer: str = "/location_id") -> None:
    try:
        platform.service.get_location(session, principal, location_id)
    except NotFound:
        raise ValidationFailed("Unknown location.", pointer=pointer) from None


def _is_own(principal: Principal, key: str) -> bool:
    return principal.kind == "staff" and principal.permissions.get(key) == "own"


def _employee(session: Session, staff_user_id: UUID, location_id: UUID, pointer: str = "/staff_user_id") -> None:
    if not platform.service.staff_user_works_at(session, staff_user_id, location_id):
        raise ValidationFailed("That staff user does not work at this location.", pointer=pointer)


def _window(starts_on: date, ends_on: date, zone: str) -> tuple[datetime, datetime]:
    """[local midnight of starts_on, local midnight after ends_on) as UTC instants."""
    tz = ZoneInfo(zone)
    return (datetime.combine(starts_on, time(), tz), datetime.combine(ends_on + timedelta(days=1), time(), tz))


def _check_span(starts_on: date, ends_on: date) -> None:
    if ends_on < starts_on:
        raise ValidationFailed("The end date is before the start date.", pointer="/to")
    if (ends_on - starts_on).days >= MAX_WINDOW_DAYS:
        raise ValidationFailed(f"Pick at most {MAX_WINDOW_DAYS} days.", pointer="/to")


# --- payees ------------------------------------------------------------------------------------------------


def list_payees(session: Session, principal: Principal, query: ListQuery) -> dict:
    return paginate(
        session, scope_query(select(StaffPayee), principal, StaffPayee.location_id), query,
        id_column=StaffPayee.id, sort_fields={"display_name": StaffPayee.display_name}, default_sort="display_name",
        filter_fields={"kind": StaffPayee.kind, "location_id": StaffPayee.location_id,
                       "is_active": StaffPayee.is_active, "staff_user_id": StaffPayee.staff_user_id},
        search=[StaffPayee.display_name],
    )  # fmt: skip


def get_payee(session: Session, principal: Principal, payee_id: UUID) -> StaffPayee:
    return _scoped(session, principal, StaffPayee, payee_id)


def _adopt_trainer(session: Session, resource_id: UUID, location_id: UUID) -> UUID:
    found = resources.service.get_many(session, [resource_id])
    if not found or found[0].kind != "trainer" or found[0].location_id != location_id:
        raise ValidationFailed("Pick a trainer resource at this location.", pointer="/resource_id")
    if session.scalar(select(StaffPayee.id).where(StaffPayee.resource_id == resource_id)):
        raise Conflict("That trainer already has a pay record.", code="already-exists")
    return resource_id


def create_payee(session: Session, principal: Principal, data: dict) -> StaffPayee:
    """A trainer payee adopts an existing trainer resource or creates the calendar column for it (STF-01);
    a salesperson is a staff user who sells (STF-05)."""
    location_id = data["location_id"]
    _location(session, principal, location_id)
    authorize(principal, PAYEE_MANAGE, location_id=location_id)
    staff_user_id = data.get("staff_user_id")
    if staff_user_id is not None:
        authorize(principal, PAY_MANAGE)  # the linked login gets the pay, as on update_payee (W2-03)
        _employee(session, staff_user_id, location_id)
    elif data["kind"] == "salesperson":
        raise ValidationFailed("A salesperson is a staff user.", pointer="/staff_user_id")
    resource_id = None
    if data["kind"] == "trainer":
        if data.get("resource_id"):
            resource_id = _adopt_trainer(session, data["resource_id"], location_id)
            if staff_user_id is not None:
                platform.service.set_linked_resource(session, staff_user_id, resource_id)
        else:
            group_id = data.get("resource_group_id") or resources.service.trainer_group(session, location_id)
            resource_id = resources.service.create_resource(session, principal, {
                "kind": "trainer", "name": data["display_name"], "location_id": location_id,
                "resource_group_id": group_id, "staff_user_id": staff_user_id,
            })["id"]  # fmt: skip
    elif data.get("resource_id") or data.get("resource_group_id"):
        raise ValidationFailed("Only a trainer has a calendar.", pointer="/resource_id")
    payee = StaffPayee(
        kind=data["kind"], display_name=data["display_name"], location_id=location_id, resource_id=resource_id,
        staff_user_id=staff_user_id, is_booking_alert_enabled=data.get("is_booking_alert_enabled", False),
        is_reminder_copy_enabled=data.get("is_reminder_copy_enabled", False),
    )  # fmt: skip
    session.add(payee)
    session.flush()
    audit.record(session, PAYEE_MANAGE, payee, location_id=location_id, changes={"kind": [None, payee.kind]})
    if resource_id is not None:
        events.publish(
            session, TrainerCreated(staff_payee_id=payee.id, resource_id=resource_id, location_id=location_id),
            payee.id,
        )  # fmt: skip
    return payee


def update_payee(session: Session, principal: Principal, payee_id: UUID, data: dict) -> StaffPayee:
    payee = _scoped(session, principal, StaffPayee, payee_id)
    authorize(principal, PAYEE_MANAGE, location_id=payee.location_id)
    if "staff_user_id" in data and data["staff_user_id"] != payee.staff_user_id:
        # The linked login is who gets the payee's pay and commission, so relinking is a pay-rate change.
        authorize(principal, PAY_MANAGE)
        if data["staff_user_id"] is None:
            if payee.kind == "salesperson":
                raise ValidationFailed("A salesperson is a staff user.", pointer="/staff_user_id")
        else:
            _employee(session, data["staff_user_id"], payee.location_id)
            if payee.resource_id is not None:
                platform.service.set_linked_resource(session, data["staff_user_id"], payee.resource_id)
    for key, value in data.items():
        setattr(payee, key, value)
    audit.record(session, PAYEE_MANAGE, payee, location_id=payee.location_id, changes=audit.diff(payee))
    session.flush()
    return payee


# --- pay and commission rules (tenant-wide keys, held by Admin) --------------------------------------------


def _payee_for_rates(session: Session, principal: Principal, payee_id: UUID, key: str) -> StaffPayee:
    payee = _scoped(session, principal, StaffPayee, payee_id)
    authorize(principal, key, location_id=payee.location_id)
    return payee


def list_pay_rates(session: Session, principal: Principal, payee_id: UUID) -> list[PayRate]:
    payee = _payee_for_rates(session, principal, payee_id, PAY_READ)
    return list(session.scalars(
        select(PayRate).where(PayRate.staff_payee_id == payee.id)
        .order_by(PayRate.reservation_type_id.is_not(None), PayRate.id)
    ))  # fmt: skip


def put_default_pay_rate(session: Session, principal: Principal, payee_id: UUID, data: dict) -> PayRate:
    """The trainer's default session pay (STF-02); per-reservation-type overrides are P1 and not built."""
    payee = _payee_for_rates(session, principal, payee_id, PAY_MANAGE)
    if payee.kind != "trainer":
        raise ValidationFailed("Session pay is for trainers.", pointer="/pay_basis")
    row = session.scalar(
        select(PayRate).where(PayRate.staff_payee_id == payee.id, PayRate.reservation_type_id.is_(None))
    )
    if row is None:
        row = PayRate(staff_payee_id=payee.id, reservation_type_id=None, **data)
        session.add(row)
    else:
        for key, value in data.items():
            setattr(row, key, value)
    session.flush()
    audit.record(session, PAY_MANAGE, row, location_id=payee.location_id, changes=audit.diff(row) or {"rate": True})
    return row


def get_commission_rules(session: Session, principal: Principal, payee_id: UUID) -> dict:
    payee = _payee_for_rates(session, principal, payee_id, PAY_READ)
    return {"staff_payee_id": payee.id, "rules": _rules(session, payee.id)}


def _rules(session: Session, payee_id: UUID) -> list[CommissionRule]:
    return list(session.scalars(
        select(CommissionRule).where(CommissionRule.staff_payee_id == payee_id)
        .order_by(CommissionRule.applies_to, CommissionRule.id)
    ))  # fmt: skip


def put_commission_rules(session: Session, principal: Principal, payee_id: UUID, rules: list[dict]) -> dict:
    """Replace the payee's commission rules as a whole (STF-05, STF-10). A rule naming a reservation type is
    checked through scheduling's scoped loader; membership types are checked by the composite key."""
    payee = _payee_for_rates(session, principal, payee_id, PAY_MANAGE)
    for i, rule in enumerate(rules):
        if rule.get("reservation_type_id"):
            try:
                scheduling.service.get_type(session, principal, rule["reservation_type_id"])
            except NotFound:
                raise ValidationFailed("Unknown reservation type.", pointer=f"/rules/{i}/reservation_type_id") from None
    session.execute(delete(CommissionRule).where(CommissionRule.staff_payee_id == payee.id))
    session.add_all(CommissionRule(staff_payee_id=payee.id, **rule) for rule in rules)
    session.flush()
    audit.record(session, PAY_MANAGE, payee, location_id=payee.location_id, changes={"commission_rules": True})
    return {"staff_payee_id": payee.id, "rules": _rules(session, payee.id)}


# --- job classifications and hourly rates ------------------------------------------------------------------


def list_job_classifications(session: Session, principal: Principal, query: ListQuery) -> dict:
    return paginate(
        session, select(JobClassification), query, id_column=JobClassification.id,
        sort_fields={"name": JobClassification.name}, default_sort="name",
        filter_fields={"is_active": JobClassification.is_active}, search=[JobClassification.name],
    )  # fmt: skip


def create_job_classification(session: Session, principal: Principal, data: dict) -> JobClassification:
    authorize_tenant_wide(principal, ENTRY_MANAGE)
    row = JobClassification(**data)
    session.add(row)
    session.flush()
    audit.record(session, ENTRY_MANAGE, row, changes={"name": [None, row.name]})
    return row


def update_job_classification(session: Session, principal: Principal, row_id: UUID, data: dict) -> JobClassification:
    row = session.get(JobClassification, row_id)
    if row is None:
        raise NotFound()
    authorize_tenant_wide(principal, ENTRY_MANAGE)
    for key, value in data.items():
        setattr(row, key, value)
    audit.record(session, ENTRY_MANAGE, row, changes=audit.diff(row))
    session.flush()
    return row


def _active_classification(session: Session, row_id: UUID, pointer: str = "/job_classification_id"):
    row = session.get(JobClassification, row_id)
    if row is None or not row.is_active:
        raise ValidationFailed("Unknown or inactive job classification.", pointer=pointer)
    return row


def list_hourly_rates(session: Session, principal: Principal, staff_user_id: UUID) -> list[StaffHourlyRate]:
    authorize(principal, PAY_READ)
    if not platform.service.staff_user_exists(session, staff_user_id):
        raise NotFound()
    return list(session.scalars(
        select(StaffHourlyRate).where(StaffHourlyRate.staff_user_id == staff_user_id)
        .order_by(StaffHourlyRate.job_classification_id, StaffHourlyRate.effective_from_on)
    ))  # fmt: skip


def add_hourly_rate(session: Session, principal: Principal, staff_user_id: UUID, data: dict) -> StaffHourlyRate:
    authorize(principal, PAY_MANAGE)
    if not platform.service.staff_user_exists(session, staff_user_id):
        raise NotFound()
    _active_classification(session, data["job_classification_id"])
    row = StaffHourlyRate(staff_user_id=staff_user_id, **data)
    session.add(row)
    session.flush()
    audit.record(session, PAY_MANAGE, row, changes={"rate_minor": True})
    return row


def delete_hourly_rate(session: Session, principal: Principal, staff_user_id: UUID, rate_id: UUID) -> None:
    """Only a rate no time entry has used yet goes; a used one is superseded by a later-dated row."""
    row = session.get(StaffHourlyRate, rate_id)
    if row is None or row.staff_user_id != staff_user_id:
        raise NotFound()
    authorize(principal, PAY_MANAGE)
    used = session.scalar(select(TimeEntry.id).where(
        TimeEntry.staff_user_id == row.staff_user_id, TimeEntry.job_classification_id == row.job_classification_id,
        TimeEntry.voided_at.is_(None),
        TimeEntry.clock_in_at >= datetime.combine(row.effective_from_on - timedelta(days=1), time(), ZoneInfo("UTC")),
    ).limit(1))  # fmt: skip
    if used is not None:
        raise Conflict("Time entries already use this rate; add a new dated rate instead.", code="rate-in-use")
    audit.record(session, PAY_MANAGE, row, changes={"deleted": True})
    session.delete(row)
    session.flush()


def _hourly_rates(session: Session, staff_user_ids) -> dict[tuple[UUID, UUID], list[tuple[date, int]]]:
    found: dict[tuple[UUID, UUID], list[tuple[date, int]]] = defaultdict(list)
    ids = list(staff_user_ids)
    if ids:
        for row in session.scalars(select(StaffHourlyRate).where(StaffHourlyRate.staff_user_id.in_(ids))):
            found[(row.staff_user_id, row.job_classification_id)].append((row.effective_from_on, row.rate_minor))
    return found


# --- settings ----------------------------------------------------------------------------------------------


def _settings_row(session: Session, location_id: UUID | None) -> StaffSettings | None:
    stmt = select(StaffSettings)
    stmt = stmt.where(
        StaffSettings.location_id.is_(None) if location_id is None else StaffSettings.location_id == location_id
    )
    return session.scalar(stmt)


def effective_settings(session: Session, location_id: UUID | None) -> dict:
    """The location's override if one exists, else the tenant row, else the defaults."""
    row = (_settings_row(session, location_id) if location_id else None) or _settings_row(session, None)
    return {
        "location_id": location_id,
        "is_override": bool(row is not None and row.location_id is not None),
        "is_time_clock_network_restricted": bool(row and row.is_time_clock_network_restricted),
        "time_clock_networks": [str(n) for n in (row.time_clock_networks if row else [])],
        "default_commission_basis": row.default_commission_basis if row else "paid",
        "pay_period": row.pay_period if row else "biweekly",
        "pay_period_anchor_on": row.pay_period_anchor_on if row else None,
    }


def get_settings(session: Session, principal: Principal, location_id: UUID | None) -> dict:
    if location_id is not None:
        _location(session, principal, location_id)
    return effective_settings(session, location_id)


def put_settings(session: Session, principal: Principal, location_id: UUID | None, data: dict) -> dict:
    if location_id is None:
        authorize_tenant_wide(principal, ENTRY_MANAGE)
    else:
        _location(session, principal, location_id)
        authorize(principal, ENTRY_MANAGE, location_id=location_id)
    data = data | {"time_clock_networks": [str(n) for n in data.get("time_clock_networks", [])]}
    row = _settings_row(session, location_id)
    if row is None:
        row = StaffSettings(location_id=location_id, **data)
        session.add(row)
    else:
        for key, value in data.items():
            setattr(row, key, value)
    session.flush()
    audit.record(session, ENTRY_MANAGE, row, location_id=location_id, changes={"settings": True})
    return effective_settings(session, location_id)


def _network_allowed(session: Session, location_id: UUID | None) -> bool:
    settings = effective_settings(session, location_id)
    if not settings["is_time_clock_network_restricted"]:
        return True
    raw = context.client_ip.get()
    if not raw:
        return False
    try:
        address = ip_address(raw)
    except ValueError:
        return False
    return any(address in ip_network(net, strict=False) for net in settings["time_clock_networks"])


# --- time clock --------------------------------------------------------------------------------------------


def _open_entry(session: Session, staff_user_id: UUID, *, lock: bool = False) -> TimeEntry | None:
    stmt = select(TimeEntry).where(
        TimeEntry.staff_user_id == staff_user_id, TimeEntry.clock_out_at.is_(None), TimeEntry.voided_at.is_(None)
    )
    return session.scalar(stmt.with_for_update() if lock else stmt)


def _punch_classifications(session: Session, staff_user_id: UUID, day: date) -> list[JobClassification]:
    rates = {key[1]: value for key, value in _hourly_rates(session, [staff_user_id]).items()}
    rows = session.scalars(
        select(JobClassification).where(JobClassification.is_active).order_by(JobClassification.name)
    )
    return [row for row in rows if row.id in rates and pay.rate_on(rates[row.id], day) is not None]


def clock_state(session: Session, principal: Principal, location_id: UUID | None) -> dict:
    """The signed-in user's own clock: the open entry, what they can clock in as, and whether this network may
    punch (STF-07). Any staff user reads their own state."""
    if principal.staff_user_id is None:
        raise PermissionDenied("Staff users only.")
    authorize(principal, PUNCH, location_id=location_id)
    if location_id is not None:
        _location(session, principal, location_id)
    day = (
        platform.service.location_today(session, location_id)
        if location_id
        else platform.service.earliest_today(session)
    )
    return {
        "open_entry": _entry_view(entry) if (entry := _open_entry(session, principal.staff_user_id)) else None,
        "job_classifications": _punch_classifications(session, principal.staff_user_id, day),
        "is_network_allowed": _network_allowed(session, location_id),
    }


def clock_in(session: Session, principal: Principal, data: dict) -> dict:
    """Self clock-in (STF-07). The password check runs first: a wrong password is recorded and raised before
    anything else is written. One open entry per user is also the exclusion constraint's job."""
    if principal.staff_user_id is None:
        raise PermissionDenied("Staff users only.")
    platform_auth.reauthenticate(session, principal, data["password"])
    location_id = data["location_id"]
    _location(session, principal, location_id)
    authorize(principal, PUNCH, location_id=location_id)
    _active_classification(session, data["job_classification_id"])
    day = platform.service.location_today(session, location_id)
    if data["job_classification_id"] not in {
        c.id for c in _punch_classifications(session, principal.staff_user_id, day)
    }:
        raise ValidationFailed("You have no pay rate for that job.", pointer="/job_classification_id")
    if not _network_allowed(session, location_id):
        raise PermissionDenied("Clock in from the facility's network.", code="network-not-allowed")
    if _open_entry(session, principal.staff_user_id) is not None:
        raise Conflict("You are already clocked in.", code="already-clocked-in")
    entry = TimeEntry(
        staff_user_id=principal.staff_user_id, location_id=location_id,
        job_classification_id=data["job_classification_id"], clock_in_at=clock.now(), source="self",
        source_ip=context.client_ip.get(),
    )  # fmt: skip
    session.add(entry)
    session.flush()
    audit.record(session, PUNCH, entry, location_id=location_id, changes={"clock_in_at": True})
    return _entry_view(entry)


def clock_out(session: Session, principal: Principal, data: dict) -> dict:
    if principal.staff_user_id is None:
        raise PermissionDenied("Staff users only.")
    platform_auth.reauthenticate(session, principal, data["password"])
    entry = _open_entry(session, principal.staff_user_id, lock=True)
    if entry is None:
        raise Conflict("You are not clocked in.", code="not-clocked-in")
    authorize(principal, PUNCH, location_id=entry.location_id)
    if not _network_allowed(session, entry.location_id):
        raise PermissionDenied("Clock out from the facility's network.", code="network-not-allowed")
    now = clock.now()
    if now <= entry.clock_in_at:
        raise Conflict("Clock out after you clock in.", code="not-clocked-in")
    entry.clock_out_at = now
    session.flush()
    audit.record(session, PUNCH, entry, location_id=entry.location_id, changes={"clock_out_at": True})
    _closed(session, entry)
    return _entry_view(entry)


def _closed(session: Session, entry: TimeEntry) -> None:
    events.publish(
        session, TimeEntryClosed(time_entry_id=entry.id, staff_user_id=entry.staff_user_id,
                                 location_id=entry.location_id), entry.id,
    )  # fmt: skip


def _minutes(starts: datetime, ends: datetime | None) -> int | None:
    return None if ends is None else int((ends - starts).total_seconds() // 60)


def _entry_view(entry: TimeEntry) -> dict:
    return {c.key: getattr(entry, c.key) for c in TimeEntry.__table__.columns if c.key != "source_ip"} | {
        "duration_minutes": _minutes(entry.clock_in_at, entry.clock_out_at)
    }


# --- time entries (managers) -------------------------------------------------------------------------------


def list_time_entries(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, ENTRY_READ)
    stmt = scope_query(select(TimeEntry), principal, TimeEntry.location_id)
    if _is_own(principal, ENTRY_READ):
        stmt = stmt.where(TimeEntry.staff_user_id == principal.staff_user_id)
    page = paginate(
        session, stmt, query, id_column=TimeEntry.id, sort_fields={"clock_in_at": TimeEntry.clock_in_at},
        default_sort="-clock_in_at",
        filter_fields={"staff_user_id": TimeEntry.staff_user_id, "location_id": TimeEntry.location_id,
                       "job_classification_id": TimeEntry.job_classification_id},
    )  # fmt: skip
    page["data"] = [_entry_view(row) for row in page["data"]]
    return page


def _not_self(principal: Principal, staff_user_id: UUID) -> None:
    """A manager never edits their own hours; Owner and Admin may (STF-08)."""
    if (
        principal.kind == "staff" and staff_user_id == principal.staff_user_id
        and principal.role_system_key not in ("owner", "admin")
    ):  # fmt: skip
        raise PermissionDenied("Ask another manager to change your own hours.", code="own-time-entry")


def _managed_entry(session: Session, principal: Principal, entry_id: UUID) -> TimeEntry:
    entry = _scoped(session, principal, TimeEntry, entry_id)
    authorize(principal, ENTRY_MANAGE, location_id=entry.location_id)
    _not_self(principal, entry.staff_user_id)
    if entry.voided_at is not None:
        raise Conflict("This entry is voided.", code="time-entry-voided")
    return entry


def create_time_entry(session: Session, principal: Principal, data: dict) -> dict:
    location_id = data["location_id"]
    _location(session, principal, location_id)
    authorize(principal, ENTRY_MANAGE, location_id=location_id)
    _not_self(principal, data["staff_user_id"])
    _employee(session, data["staff_user_id"], location_id)
    _active_classification(session, data["job_classification_id"])
    if data["clock_out_at"] <= data["clock_in_at"]:
        raise ValidationFailed("Clock-out must be after clock-in.", pointer="/clock_out_at")
    entry = TimeEntry(**data, source="manager", edited_by_staff_user_id=principal.staff_user_id)
    session.add(entry)
    session.flush()
    audit.record(session, ENTRY_MANAGE, entry, location_id=location_id, changes={"created": True})
    _closed(session, entry)
    return _entry_view(entry)


def update_time_entry(session: Session, principal: Principal, entry_id: UUID, data: dict) -> dict:
    entry = _managed_entry(session, principal, entry_id)
    was_open = entry.clock_out_at is None
    if data.get("job_classification_id"):
        _active_classification(session, data["job_classification_id"])
    for key, value in data.items():
        if value is not None:
            setattr(entry, key, value)
    if entry.clock_out_at is not None and entry.clock_out_at <= entry.clock_in_at:
        raise ValidationFailed("Clock-out must be after clock-in.", pointer="/clock_out_at")
    entry.edited_by_staff_user_id = principal.staff_user_id
    audit.record(session, ENTRY_MANAGE, entry, location_id=entry.location_id, changes=audit.diff(entry))
    session.flush()
    if was_open and entry.clock_out_at is not None:
        _closed(session, entry)
    return _entry_view(entry)


def void_time_entry(session: Session, principal: Principal, entry_id: UUID, data: dict) -> dict:
    entry = _managed_entry(session, principal, entry_id)
    entry.voided_at = clock.now()
    entry.edit_reason = data["edit_reason"]
    entry.edited_by_staff_user_id = principal.staff_user_id
    audit.record(session, ENTRY_MANAGE, entry, location_id=entry.location_id, changes={"voided_at": True})
    session.flush()
    return _entry_view(entry)


def time_summary(
    session: Session, principal: Principal, starts_on: date, ends_on: date, location_id: UUID | None = None
) -> list[dict]:
    """Hours per employee, job and location over a date range (STF-08), with pay when the caller may see
    rates. Closed, unvoided entries count on the local date they started."""
    authorize(principal, ENTRY_READ)
    _check_span(starts_on, ends_on)
    if location_id is not None:
        _location(session, principal, location_id)
    stmt = scope_query(select(TimeEntry), principal, TimeEntry.location_id).where(
        TimeEntry.voided_at.is_(None), TimeEntry.clock_out_at.is_not(None),
        TimeEntry.clock_in_at >= datetime.combine(starts_on - timedelta(days=1), time(), ZoneInfo("UTC")),
        TimeEntry.clock_in_at < datetime.combine(ends_on + timedelta(days=2), time(), ZoneInfo("UTC")),
    )  # fmt: skip
    if location_id is not None:
        stmt = stmt.where(TimeEntry.location_id == location_id)
    if _is_own(principal, ENTRY_READ):
        stmt = stmt.where(TimeEntry.staff_user_id == principal.staff_user_id)
    entries = list(session.scalars(stmt))
    zones: dict[UUID, ZoneInfo] = {}
    show_pay = principal.has(PAY_READ)
    rates = _hourly_rates(session, {e.staff_user_id for e in entries}) if show_pay else {}
    rows: dict[tuple, dict] = {}
    for entry in entries:
        if entry.location_id not in zones:
            zones[entry.location_id] = ZoneInfo(platform.service.location_time_zone(session, entry.location_id))
        day = entry.clock_in_at.astimezone(zones[entry.location_id]).date()
        if not starts_on <= day <= ends_on:
            continue
        key = (entry.staff_user_id, entry.job_classification_id, entry.location_id)
        row = rows.setdefault(key, {"staff_user_id": key[0], "job_classification_id": key[1], "location_id": key[2],
                                    "entry_count": 0, "minutes": 0, "pay_minor": 0 if show_pay else None})  # fmt: skip
        minutes = _minutes(entry.clock_in_at, entry.clock_out_at) or 0
        row["entry_count"] += 1
        row["minutes"] += minutes
        if show_pay:
            rate = pay.rate_on(rates.get((entry.staff_user_id, entry.job_classification_id), []), day) or 0
            row["pay_minor"] += pay.per_hour(rate, minutes)
    names = platform.service.staff_user_names(session, {key[0] for key in rows})
    return sorted(
        ({**row, "display_name": names.get(row["staff_user_id"], "")} for row in rows.values()),
        key=lambda r: (r["display_name"], str(r["job_classification_id"])),
    )


# --- shifts ------------------------------------------------------------------------------------------------


def list_shifts(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, SHIFT_MANAGE)
    return paginate(
        session, scope_query(select(Shift), principal, Shift.location_id), query, id_column=Shift.id,
        sort_fields={"starts_at": Shift.starts_at}, default_sort="starts_at",
        filter_fields={"staff_user_id": Shift.staff_user_id, "location_id": Shift.location_id, "status": Shift.status},
    )  # fmt: skip


def list_my_shifts(session: Session, principal: Principal, query: ListQuery) -> dict:
    """Any staff user's own published shifts (the implicit self rule of rbac-matrix section 3)."""
    if principal.staff_user_id is None:
        raise PermissionDenied("Staff users only.")
    stmt = select(Shift).where(Shift.staff_user_id == principal.staff_user_id, Shift.status == "published")
    return paginate(session, stmt, query, id_column=Shift.id, sort_fields={"starts_at": Shift.starts_at},
                    default_sort="starts_at", filter_fields={"location_id": Shift.location_id})  # fmt: skip


def _check_shift(session: Session, shift: Shift) -> None:
    if shift.ends_at <= shift.starts_at:
        raise ValidationFailed("A shift ends after it starts.", pointer="/ends_at")
    if shift.ends_at - shift.starts_at > timedelta(hours=24):
        raise ValidationFailed("A shift is at most 24 hours.", pointer="/ends_at")
    if shift.job_classification_id is not None:
        _active_classification(session, shift.job_classification_id)


def create_shift(session: Session, principal: Principal, data: dict) -> Shift:
    _location(session, principal, data["location_id"])
    authorize(principal, SHIFT_MANAGE, location_id=data["location_id"])
    _employee(session, data["staff_user_id"], data["location_id"])
    shift = Shift(**data)
    _check_shift(session, shift)
    session.add(shift)
    session.flush()
    audit.record(session, SHIFT_MANAGE, shift, location_id=shift.location_id, changes={"created": True})
    return shift


def _managed_shift(session: Session, principal: Principal, shift_id: UUID) -> Shift:
    shift = _scoped(session, principal, Shift, shift_id)
    authorize(principal, SHIFT_MANAGE, location_id=shift.location_id)
    if shift.status == "cancelled":
        raise Conflict("This shift is cancelled.", code="shift-cancelled")
    return shift


def update_shift(session: Session, principal: Principal, shift_id: UUID, data: dict) -> Shift:
    shift = _managed_shift(session, principal, shift_id)
    if data.get("staff_user_id"):
        _employee(session, data["staff_user_id"], shift.location_id)
    for key, value in data.items():
        if value is not None or key in ("note", "job_classification_id"):
            setattr(shift, key, value)
    _check_shift(session, shift)
    audit.record(session, SHIFT_MANAGE, shift, location_id=shift.location_id, changes=audit.diff(shift))
    session.flush()
    return shift


def cancel_shift(session: Session, principal: Principal, shift_id: UUID) -> Shift:
    shift = _managed_shift(session, principal, shift_id)
    shift.status = "cancelled"
    audit.record(session, SHIFT_MANAGE, shift, location_id=shift.location_id, changes=audit.diff(shift))
    session.flush()
    return shift


def publish_shifts(session: Session, principal: Principal, data: dict) -> dict:
    """Publish draft shifts by id, or every draft at a location in a time window (STF-15)."""
    if data.get("shift_ids"):
        shifts = [_managed_shift(session, principal, shift_id) for shift_id in data["shift_ids"]]
    elif data.get("location_id") and data.get("starts_from") and data.get("starts_to"):
        _location(session, principal, data["location_id"])
        authorize(principal, SHIFT_MANAGE, location_id=data["location_id"])
        shifts = list(session.scalars(select(Shift).where(
            Shift.location_id == data["location_id"], Shift.status == "draft",
            Shift.starts_at >= data["starts_from"], Shift.starts_at < data["starts_to"],
        )))  # fmt: skip
    else:
        raise ValidationFailed("Name the shifts, or a location and a time window.", pointer="/shift_ids")
    count = 0
    for shift in shifts:
        if shift.status == "draft":
            shift.status = "published"
            audit.record(session, SHIFT_MANAGE, shift, location_id=shift.location_id, changes=audit.diff(shift))
            count += 1
    session.flush()
    return {"published_count": count}


# --- instructors (sessions are scheduling bookings) --------------------------------------------------------


def payee_sessions(
    session: Session, principal: Principal, payee_id: UUID, starts_on: date | None, ends_on: date | None
) -> list:
    """A trainer's sessions in a local date range (STF-01): the bookings their calendar column holds."""
    payee = _scoped(session, principal, StaffPayee, payee_id)
    authorize(principal, SCHEDULE_READ, location_id=payee.location_id)
    starts_on = starts_on or platform.service.location_today(session, payee.location_id)
    ends_on = ends_on or starts_on + timedelta(days=6)
    _check_span(starts_on, ends_on)
    if payee.resource_id is None:
        return []
    start, end = _window(starts_on, ends_on, platform.service.location_time_zone(session, payee.location_id))
    ids = scheduling.service.booking_ids(resource_id=payee.resource_id, starts_from=start, starts_to=end)
    views = scheduling.service.booking_views(session, session.scalars(ids))
    return sorted(
        ({"booking_id": v["id"], "session_id": v["session"]["id"], "location_id": v["location_id"],
          "reservation_type_id": v["reservation_type_id"], "title": v["title"] or "", "starts_at": v["starts_at"],
          "ends_at": v["ends_at"], "status": v["status"], "capacity": v["session"]["capacity"],
          "booked_count": v["session"]["booked_count"]}
         for v in views.values() if v["session"] is not None),
        key=lambda row: row["starts_at"],
    )  # fmt: skip


def assign_instructor(session: Session, principal: Principal, session_id: UUID, payee_id: UUID | None) -> dict:
    """Put a trainer on a session, or take them off (STF-01). The trainer's calendar column replaces the
    session's other trainer columns; scheduling re-derives the holds, so a clash is a booking-conflict."""
    seat = scheduling.service.get_session(session, session_id)
    if not _everywhere(principal) and seat["location_id"] not in principal.location_ids:
        raise NotFound()
    booking = scheduling.service.authorize_reach(session, principal, SESSION_MANAGE, seat["booking_id"])
    view = scheduling.service.booking_views(session, [booking.id])[booking.id]
    current = [r["resource_id"] for r in view["resources"]]
    trainers = {r.id for r in resources.service.get_many(session, current) if r.kind == "trainer"}
    keep = [rid for rid in current if rid not in trainers]
    if payee_id is not None:
        try:
            payee = _scoped(session, principal, StaffPayee, payee_id)
        except NotFound:
            raise ValidationFailed("Unknown trainer.", pointer="/staff_payee_id") from None
        if payee.resource_id is None or not payee.is_active or payee.location_id != booking.location_id:
            raise ValidationFailed("Pick an active trainer at this location.", pointer="/staff_payee_id")
        keep.append(payee.resource_id)
    if principal.permissions.get(SESSION_MANAGE) == "own" and (
        payee_id is None or payee.resource_id != platform.service.linked_resource_id(session, principal.staff_user_id)
    ):
        raise PermissionDenied("You can only put yourself on a session.", code="own-sessions-only")
    if not keep:
        raise Conflict("A session needs a court, room or trainer.", code="session-needs-resource")
    scheduling.service.reschedule_booking(
        session, booking, starts_at=booking.starts_at, ends_at=booking.ends_at, resource_ids=keep
    )
    audit.record(session, SESSION_MANAGE, booking, location_id=booking.location_id,
                 changes={"instructor": [None, str(payee_id) if payee_id else None]})  # fmt: skip
    return {"session_id": session_id, "booking_id": booking.id, "staff_payee_id": payee_id, "resource_ids": keep}


# --- payroll runs ------------------------------------------------------------------------------------------


def _run(session: Session, principal: Principal, run_id: UUID, key: str) -> PayrollRun:
    run = _scoped(session, principal, PayrollRun, run_id)
    if run.location_id is None and key != STATEMENT_READ:
        authorize_tenant_wide(principal, key)
    else:
        authorize(principal, key, location_id=run.location_id)
    return run


def list_runs(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, RUN_CREATE)
    page = paginate(
        session, scope_query(select(PayrollRun), principal, PayrollRun.location_id), query, id_column=PayrollRun.id,
        sort_fields={"period_starts_on": PayrollRun.period_starts_on, "created_at": PayrollRun.created_at},
        default_sort="-period_starts_on",
        filter_fields={"location_id": PayrollRun.location_id, "status": PayrollRun.status},
    )  # fmt: skip
    page["data"] = [run_view(session, run) for run in page["data"]]
    return page


def run_view(session: Session, run: PayrollRun) -> dict:
    totals = session.scalars(select(PayStatement.total_minor).where(PayStatement.payroll_run_id == run.id)).all()
    return {c.key: getattr(run, c.key) for c in PayrollRun.__table__.columns} | {
        "total_minor": sum(totals), "statement_count": len(totals),
    }  # fmt: skip


def get_run(session: Session, principal: Principal, run_id: UUID) -> dict:
    return run_view(session, _run(session, principal, run_id, RUN_CREATE))


def create_run(session: Session, principal: Principal, data: dict) -> dict:
    """Compute a pay report for a date range now (STF-09, STF-10); it stays editable until finalized."""
    location_id = data.get("location_id")
    if location_id is None:
        authorize_tenant_wide(principal, RUN_CREATE)
    else:
        _location(session, principal, location_id)
        authorize(principal, RUN_CREATE, location_id=location_id)
    if data["period_ends_on"] < data["period_starts_on"]:
        raise ValidationFailed("The period ends before it starts.", pointer="/period_ends_on")
    if (data["period_ends_on"] - data["period_starts_on"]).days >= MAX_WINDOW_DAYS:
        raise ValidationFailed(f"A pay period is at most {MAX_WINDOW_DAYS} days.", pointer="/period_ends_on")
    if data.get("scope_staff_payee_id"):
        try:
            payee = _scoped(session, principal, StaffPayee, data["scope_staff_payee_id"])
        except NotFound:
            raise ValidationFailed("Unknown payee.", pointer="/scope_staff_payee_id") from None
        if location_id is not None and payee.location_id != location_id:
            raise ValidationFailed("That payee works at another location.", pointer="/scope_staff_payee_id")
    basis = data.get("commission_basis") or effective_settings(session, location_id)["default_commission_basis"]
    run = PayrollRun(
        location_id=location_id, period_starts_on=data["period_starts_on"], period_ends_on=data["period_ends_on"],
        commission_basis=basis, includes=list(dict.fromkeys(data["includes"])),
        scope_staff_payee_id=data.get("scope_staff_payee_id"), requested_by_staff_user_id=principal.staff_user_id,
        status="calculating",
    )  # fmt: skip
    session.add(run)
    session.flush()
    _calculate(session, run)
    audit.record(session, RUN_CREATE, run, location_id=location_id, changes={"status": [None, run.status]})
    return run_view(session, run)


def recalculate_run(session: Session, principal: Principal, run_id: UUID) -> dict:
    run = _run(session, principal, run_id, RUN_CREATE)
    if run.status != "calculated":
        raise Conflict("Only an unfinalized run is recalculated.", code="payroll-run-frozen")
    session.execute(delete(PayStatement).where(PayStatement.payroll_run_id == run.id))
    _calculate(session, run)
    audit.record(session, RUN_CREATE, run, location_id=run.location_id, changes={"recalculated": True})
    return run_view(session, run)


def finalize_run(session: Session, principal: Principal, run_id: UUID) -> dict:
    run = _run(session, principal, run_id, RUN_APPROVE)
    if run.status != "calculated":
        raise Conflict("Only a calculated run is finalized.", code="payroll-run-frozen")
    run.status, run.finalized_at, run.finalized_by_staff_user_id = "finalized", clock.now(), principal.staff_user_id
    audit.record(session, RUN_APPROVE, run, location_id=run.location_id, changes=audit.diff(run))
    session.flush()
    events.publish(session, PayrollRunFinalized(payroll_run_id=run.id), run.id)
    return run_view(session, run)


def void_run(session: Session, principal: Principal, run_id: UUID) -> dict:
    run = _run(session, principal, run_id, RUN_APPROVE)
    if run.status not in ("calculated", "finalized"):
        raise Conflict("This run is already voided.", code="payroll-run-frozen")
    run.status = "voided"
    audit.record(session, RUN_APPROVE, run, location_id=run.location_id, changes=audit.diff(run))
    session.flush()
    return run_view(session, run)


def _statement(session: Session, principal: Principal, statement_id: UUID, key: str) -> PayStatement:
    """Load a statement through its run's location scope; `own` reach sees only its own, finalized ones."""
    statement = session.get(PayStatement, statement_id)
    if statement is None:
        raise NotFound()
    run = _run(session, principal, statement.payroll_run_id, key)
    if _is_own(principal, key) and (run.status != "finalized" or statement.staff_user_id != principal.staff_user_id):
        raise NotFound()
    return statement


def list_pay_statements(session: Session, principal: Principal, run_id: UUID, query: ListQuery) -> dict:
    """A run's statements. With `own` reach a user sees only their own statement, and only once finalized."""
    run = _run(session, principal, run_id, STATEMENT_READ)
    stmt = select(PayStatement).where(PayStatement.payroll_run_id == run.id)
    if _is_own(principal, STATEMENT_READ):
        if run.status != "finalized":
            raise NotFound()
        stmt = stmt.where(PayStatement.staff_user_id == principal.staff_user_id)
    return paginate(
        session, stmt, query, id_column=PayStatement.id, sort_fields={"display_name": PayStatement.display_name},
        default_sort="display_name",
        filter_fields={"staff_payee_id": PayStatement.staff_payee_id, "staff_user_id": PayStatement.staff_user_id},
    )  # fmt: skip


def get_pay_statement(session: Session, principal: Principal, statement_id: UUID) -> PayStatement:
    return _statement(session, principal, statement_id, STATEMENT_READ)


def update_pay_statement(session: Session, principal: Principal, statement_id: UUID, data: dict) -> PayStatement:
    """The manual "additional income" a manager adds before finalizing (STF-09)."""
    statement = _statement(session, principal, statement_id, RUN_CREATE)
    payee = session.get(StaffPayee, statement.staff_payee_id) if statement.staff_payee_id else None
    # W2-05: nobody below Admin adds income to their own pay, as an employee or as a linked payee.
    _not_self(principal, statement.staff_user_id or (payee and payee.staff_user_id))
    run = session.get(PayrollRun, statement.payroll_run_id)
    if run.status != "calculated":
        raise Conflict("A finalized or voided run is frozen.", code="invalid-state-transition")
    statement.total_minor += data["additional_income_minor"] - statement.additional_income_minor
    statement.additional_income_minor = data["additional_income_minor"]
    statement.additional_income_note = data.get("additional_income_note")
    audit.record(session, RUN_CREATE, statement, location_id=run.location_id, changes=audit.diff(statement))
    session.flush()
    return statement


def list_pay_statement_lines(session: Session, principal: Principal, statement_id: UUID, query: ListQuery) -> dict:
    statement = _statement(session, principal, statement_id, STATEMENT_READ)
    return paginate(
        session, select(PayStatementLine).where(PayStatementLine.pay_statement_id == statement.id), query,
        id_column=PayStatementLine.id, sort_fields={"occurred_on": PayStatementLine.occurred_on},
        default_sort="occurred_on", filter_fields={"kind": PayStatementLine.kind},
    )  # fmt: skip


def _csv_safe(value: str) -> str:
    """Spreadsheet formula injection guard: a cell never starts with = + - @."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


def export_run(session: Session, principal: Principal, run_id: UUID) -> str:
    """The run as CSV, one row per statement, for an outside payroll provider (STF-09)."""
    run = _run(session, principal, run_id, RUN_EXPORT)
    out = io.StringIO()
    writer = csv.writer(out)
    sections = ("session_pay_minor", "commission_minor", "bonus_minor", "hourly_pay_minor",
                "additional_income_minor", "total_minor")  # fmt: skip
    writer.writerow(["name", "session_pay", "commission", "bonus", "hourly_pay", "additional_income", "total"])
    rows = session.scalars(
        select(PayStatement).where(PayStatement.payroll_run_id == run.id).order_by(PayStatement.display_name)
    )
    for row in rows:
        writer.writerow([_csv_safe(row.display_name)] + [f"{Decimal(getattr(row, k)) / 100:.2f}" for k in sections])
    audit.record(session, RUN_EXPORT, run, location_id=run.location_id, changes={"exported": True})
    return out.getvalue()


# --- payroll calculation -----------------------------------------------------------------------------------


class _Sheet:
    """Statements being built for one run, keyed by subject (the payee, else the hourly employee)."""

    def __init__(self, session: Session, run: PayrollRun):
        self.session, self.run = session, run
        self.statements: dict[tuple, PayStatement] = {}

    def statement(self, *, payee: StaffPayee | None = None, staff_user_id: UUID | None = None, name: str = ""):
        key = ("payee", payee.id) if payee else ("user", staff_user_id)
        if key not in self.statements:
            row = PayStatement(
                payroll_run_id=self.run.id, staff_payee_id=payee.id if payee else None,
                staff_user_id=payee.staff_user_id if payee else staff_user_id,
                display_name=payee.display_name if payee else name, session_pay_minor=0, commission_minor=0,
                bonus_minor=0, hourly_pay_minor=0, additional_income_minor=0, total_minor=0,
            )  # fmt: skip
            self.session.add(row)
            self.session.flush()
            self.statements[key] = row
        return self.statements[key]

    def line(self, statement: PayStatement, section: str, **fields) -> None:
        self.session.add(PayStatementLine(pay_statement_id=statement.id, **fields))
        setattr(statement, section, getattr(statement, section) + fields["amount_minor"])
        statement.total_minor += fields["amount_minor"]


def _paid_before(session: Session, kind: str, source_type: str, source_ids) -> set[UUID]:
    ids = list(source_ids)
    if not ids:
        return set()
    return set(session.scalars(
        select(PayStatementLine.source_id)
        .join(PayStatement, PayStatement.id == PayStatementLine.pay_statement_id)
        .join(PayrollRun, PayrollRun.id == PayStatement.payroll_run_id)
        .where(PayrollRun.status == "finalized", PayStatementLine.kind == kind,
               PayStatementLine.source_type == source_type, PayStatementLine.source_id.in_(ids))
    ))  # fmt: skip


def _calculate(session: Session, run: PayrollRun) -> None:
    payees_stmt = select(StaffPayee).where(StaffPayee.is_active)
    if run.location_id is not None:
        payees_stmt = payees_stmt.where(StaffPayee.location_id == run.location_id)
    if run.scope_staff_payee_id is not None:
        payees_stmt = payees_stmt.where(StaffPayee.id == run.scope_staff_payee_id)
    payees = list(session.scalars(payees_stmt.order_by(StaffPayee.display_name, StaffPayee.id)))
    sheet = _Sheet(session, run)
    zones: dict[UUID, str] = {}

    def zone(location_id: UUID) -> str:
        if location_id not in zones:
            zones[location_id] = platform.service.location_time_zone(session, location_id)
        return zones[location_id]

    if "sessions" in run.includes:
        for payee in payees:
            if payee.resource_id is not None:
                _session_pay(session, sheet, payee, zone(payee.location_id))
    if "commissions" in run.includes:
        for payee in payees:
            if payee.staff_user_id is not None:
                _commissions(session, sheet, payee, zone(payee.location_id))
    if "hourly" in run.includes:
        _hourly_pay(session, sheet, payees, zone)
    run.status, run.calculated_at = "calculated", clock.now()
    session.flush()


def _session_pay(session: Session, sheet: _Sheet, payee: StaffPayee, tz: str) -> None:
    """Completed, confirmed bookings on the trainer's calendar in the period, paid by the pay-rate row for
    the booking's reservation type (a P1 override), else the default row (STF-02, STF-03)."""
    run = sheet.run
    rates = {
        r.reservation_type_id: r for r in session.scalars(select(PayRate).where(PayRate.staff_payee_id == payee.id))
    }
    if not rates:
        return
    start, end = _window(run.period_starts_on, run.period_ends_on, tz)
    ids = scheduling.service.booking_ids(
        resource_id=payee.resource_id, status="confirmed", starts_from=start, starts_to=end
    )
    now = clock.now()
    views = [v for v in scheduling.service.booking_views(session, session.scalars(ids)).values()
             if v["ends_at"] <= now and v["kind"] in ("session", "rental")]  # fmt: skip
    attended = programs.service.attended_counts(session, [v["session"]["id"] for v in views if v["session"]])
    for view in sorted(views, key=lambda v: (v["starts_at"], v["id"])):
        rate = rates.get(view["reservation_type_id"]) or rates.get(None)
        if rate is None:
            continue
        minutes = int((view["ends_at"] - view["starts_at"]).total_seconds() // 60)
        attendees = attended.get(view["session"]["id"], 0) if view["session"] else int(bool(view.get("client_id")))
        fact = pay.session_line(rate, minutes, attendees)
        if fact is None:
            continue
        sheet.line(
            sheet.statement(payee=payee), "session_pay_minor", kind=fact["kind"],
            occurred_on=view["starts_at"].astimezone(ZoneInfo(tz)).date(), source_type="booking",
            source_id=view["id"], reservation_type_id=view["reservation_type_id"],
            description=view["title"] or "Session", quantity=Decimal(fact["quantity"]).quantize(Decimal("0.01")),
            rate_minor=fact["rate_minor"], amount_minor=fact["amount_minor"],
        )  # fmt: skip


def _commissions(session: Session, sheet: _Sheet, payee: StaffPayee, tz: str) -> None:
    """Package and membership sale commission on the invoiced or paid amount (STF-05, STF-10). A sale already
    on a finalized run is flagged `was_paid_before` and still listed, so the manager decides."""
    run = sheet.run
    rules = _rules(session, payee.id)
    if not rules:
        return
    where = None if run.location_id is None else [run.location_id]
    basis = "paid_minor" if run.commission_basis == "paid" else "invoiced_minor"
    start, end = _window(run.period_starts_on, run.period_ends_on, tz)

    sales = packages.service.sales_by_seller(session, payee.staff_user_id, start, end, where)
    totals = billing.service.source_totals(session, "packages", "client_package", [s["id"] for s in sales])
    before = _paid_before(session, "package_sale_commission", "client_package", [s["id"] for s in sales])
    for sale in sales:
        rule = pay.pick_rule(rules, "package_sale", reservation_type_id=sale["reservation_type_id"])
        base = totals.get(sale["id"], {}).get(basis, 0)
        if rule is None or not (amount := pay.commission(base, rule.commission_pct, rule.flat_minor)):
            continue
        sheet.line(
            sheet.statement(payee=payee), "commission_minor", kind="package_sale_commission",
            occurred_on=sale["sold_at"].astimezone(ZoneInfo(tz)).date(), source_type="client_package",
            source_id=sale["id"], reservation_type_id=sale["reservation_type_id"], description=sale["name"],
            commission_pct=rule.commission_pct, base_minor=base, amount_minor=amount,
            was_paid_before=sale["id"] in before,
        )  # fmt: skip

    periods = memberships.service.seller_periods(
        session, payee.staff_user_id, run.period_starts_on, run.period_ends_on, where
    )
    period_ids = [p["period_id"] for p in periods]
    totals = billing.service.source_totals(session, "memberships", "billing_schedule_period", period_ids)
    before = _paid_before(session, "membership_sale_commission", "billing_schedule_period", period_ids)
    for period in periods:
        rule = pay.pick_rule(rules, "membership_sale", membership_type_id=period["membership_type_id"])
        if rule is None or (rule.is_first_invoice_only and not period["is_first"]):
            continue
        base = totals.get(period["period_id"], {}).get(basis, 0)
        if not (amount := pay.commission(base, rule.commission_pct, rule.flat_minor)):
            continue
        sheet.line(
            sheet.statement(payee=payee), "commission_minor", kind="membership_sale_commission",
            occurred_on=period["bill_on"], source_type="billing_schedule_period", source_id=period["period_id"],
            description=period["name"], commission_pct=rule.commission_pct, base_minor=base, amount_minor=amount,
            was_paid_before=period["period_id"] in before,
        )  # fmt: skip


def _hourly_pay(session: Session, sheet: _Sheet, payees: list[StaffPayee], zone) -> None:
    """Closed, unvoided time entries that started in the period, at the rate in force that day (STF-06)."""
    run = sheet.run
    stmt = select(TimeEntry).where(TimeEntry.voided_at.is_(None), TimeEntry.clock_out_at.is_not(None))
    if run.location_id is not None:
        stmt = stmt.where(TimeEntry.location_id == run.location_id)
    by_user = {p.staff_user_id: p for p in payees if p.staff_user_id is not None}
    if run.scope_staff_payee_id is not None:
        if not by_user:
            return
        stmt = stmt.where(TimeEntry.staff_user_id.in_(list(by_user)))
    utc = ZoneInfo("UTC")
    lo = datetime.combine(run.period_starts_on - timedelta(days=1), time(), utc)
    hi = datetime.combine(run.period_ends_on + timedelta(days=2), time(), utc)
    entries = list(session.scalars(stmt.where(TimeEntry.clock_in_at >= lo, TimeEntry.clock_in_at < hi)
                                   .order_by(TimeEntry.clock_in_at, TimeEntry.id)))  # fmt: skip
    rates = _hourly_rates(session, {e.staff_user_id for e in entries})
    names = platform.service.staff_user_names(session, {e.staff_user_id for e in entries})
    jobs = {j.id: j.name for j in session.scalars(select(JobClassification))}
    for entry in entries:
        day = entry.clock_in_at.astimezone(ZoneInfo(zone(entry.location_id))).date()
        if not run.period_starts_on <= day <= run.period_ends_on:
            continue
        rate = pay.rate_on(rates.get((entry.staff_user_id, entry.job_classification_id), []), day)
        if rate is None:
            continue
        minutes = _minutes(entry.clock_in_at, entry.clock_out_at) or 0
        payee = by_user.get(entry.staff_user_id)
        statement = sheet.statement(payee=payee) if payee else sheet.statement(
            staff_user_id=entry.staff_user_id, name=names.get(entry.staff_user_id, "")
        )  # fmt: skip
        sheet.line(
            statement, "hourly_pay_minor", kind="hourly", occurred_on=day, source_type="time_entry",
            source_id=entry.id, description=jobs.get(entry.job_classification_id, ""),
            quantity=(Decimal(minutes) / 60).quantize(Decimal("0.01")), rate_minor=rate,
            amount_minor=pay.per_hour(rate, minutes),
        )  # fmt: skip
