"""Scheduled delivery of saved reports (RPT-01; ADR 0010 section 7 and open question 7, amended: in v1).

A schedule belongs to its creator, who must own or see the saved report and hold its family key and
`reporting.report.export`. Recipients are staff users who hold both keys too. On each due day, at the send time in
the schedule location's zone, the hourly `run_report_schedules` job gives every recipient their own run and export,
built with that recipient's permissions and locations (so a schedule never widens anyone's reach), and the finished
export emails them a sign-in link (service._send_link). A recipient who lost access, or whose locations no longer
cover the saved parameters, is skipped for that day."""

import logging
from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit, clock
from app.core.auth import Principal, authorize
from app.core.errors import DomainError, NotFound, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.modules import platform
from app.modules.reporting import service
from app.modules.reporting.catalogue import REGISTRY
from app.modules.reporting.models import ReportSchedule, SavedReport

log = logging.getLogger(__name__)
_FIELDS = ("location_id", "frequency", "weekday", "month_day", "send_time", "format", "includes_details",
           "recipient_staff_user_ids", "is_active")  # fmt: skip


def is_due(schedule: ReportSchedule, local_now: datetime) -> bool:
    """Due at the first check at or after the send time on a matching local day, once a day. A day the
    scheduler missed entirely is not caught up later (README)."""
    today = local_now.date()
    if schedule.last_run_on is not None and schedule.last_run_on >= today:
        return False
    if local_now.strftime("%H:%M") < schedule.send_time:
        return False
    if schedule.frequency == "weekly":
        return today.weekday() == schedule.weekday
    if schedule.frequency == "monthly":
        return today.day == schedule.month_day
    return True


def view(schedule: ReportSchedule) -> dict:
    return {c: getattr(schedule, c) for c in (
        "id", "saved_report_id", "owner_staff_user_id", *_FIELDS, "last_run_on", "created_at", "updated_at")}  # fmt: skip


def _holds_both(principal: Principal, report_key: str) -> bool:
    return service._holds(principal, REGISTRY[report_key].permission) and service._holds(principal, service.EXPORT)


def _check(session: Session, principal: Principal, saved: SavedReport, data: dict) -> None:
    """Shape rules the CHECK constraints also hold, as 422s with pointers; the location in the caller's set;
    every recipient an active staff user who may run and export this report."""
    if data["frequency"] == "weekly" and data.get("weekday") is None:
        raise ValidationFailed("A weekly schedule needs a weekday", pointer="/weekday")
    if data["frequency"] == "monthly" and data.get("month_day") is None:
        raise ValidationFailed("A monthly schedule needs a day of the month", pointer="/month_day")
    if data["frequency"] != "weekly":
        data["weekday"] = None
    if data["frequency"] != "monthly":
        data["month_day"] = None
    try:
        platform.service.get_location(session, principal, data["location_id"])
    except NotFound:
        raise ValidationFailed("Unknown location", pointer="/location_id") from None
    data["recipient_staff_user_ids"] = list(dict.fromkeys(data["recipient_staff_user_ids"]))
    for index, staff_user_id in enumerate(data["recipient_staff_user_ids"]):
        recipient = platform.staff.principal_for(session, staff_user_id)
        if recipient is None or not _holds_both(recipient, saved.report_key):
            raise ValidationFailed(
                "Each recipient must be an active staff user who can run and export this report",
                pointer=f"/recipient_staff_user_ids/{index}",
            )


def _load(session: Session, principal: Principal, schedule_id: UUID) -> ReportSchedule:
    schedule = session.get(ReportSchedule, schedule_id)
    if schedule is None or schedule.owner_staff_user_id != service._staff(principal):
        raise NotFound()
    authorize(principal, service.EXPORT, location_id=schedule.location_id)
    saved = session.get(SavedReport, schedule.saved_report_id)
    if saved is None or not service._holds(principal, REGISTRY[saved.report_key].permission):
        raise NotFound()
    return schedule


def create(session: Session, principal: Principal, data: dict) -> dict:
    owner = service._staff(principal)
    authorize(principal, service.EXPORT, location_id=data["location_id"])
    try:
        saved = service._load_saved(session, principal, data["saved_report_id"])
    except NotFound:
        raise ValidationFailed("Unknown saved report", pointer="/saved_report_id") from None
    _check(session, principal, saved, data)
    schedule = ReportSchedule(saved_report_id=saved.id, owner_staff_user_id=owner, **{f: data[f] for f in _FIELDS})
    session.add(schedule)
    session.flush()
    audit.record(session, "reporting.report_schedule.create", schedule, changes=audit.diff(schedule))
    return view(schedule)


def get(session: Session, principal: Principal, schedule_id: UUID) -> dict:
    return view(_load(session, principal, schedule_id))


def list_mine(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, service.EXPORT)
    stmt = (
        select(ReportSchedule)
        .join(SavedReport, SavedReport.id == ReportSchedule.saved_report_id)
        .where(
            ReportSchedule.owner_staff_user_id == service._staff(principal),
            SavedReport.report_key.in_(service._permitted_keys(principal)),
        )
    )
    if principal.location_ids is not None:
        stmt = stmt.where(ReportSchedule.location_id.in_(principal.location_ids))
    page = paginate(
        session, stmt, query, id_column=ReportSchedule.id, sort_fields={"created_at": ReportSchedule.created_at},
        default_sort="created_at", filter_fields={"saved_report_id": ReportSchedule.saved_report_id,
                                                  "is_active": ReportSchedule.is_active},
    )  # fmt: skip
    page["data"] = [view(s) for s in page["data"]]
    return page


def update(session: Session, principal: Principal, schedule_id: UUID, data: dict) -> dict:
    schedule = _load(session, principal, schedule_id)
    merged = {f: getattr(schedule, f) for f in _FIELDS} | {k: v for k, v in data.items() if k in _FIELDS}
    if "location_id" in data:
        authorize(principal, service.EXPORT, location_id=merged["location_id"])
    _check(session, principal, session.get_one(SavedReport, schedule.saved_report_id), merged)
    for field in _FIELDS:
        setattr(schedule, field, merged[field])
    session.flush()
    audit.record(session, "reporting.report_schedule.update", schedule, changes=audit.diff(schedule))
    return view(schedule)


def delete(session: Session, principal: Principal, schedule_id: UUID) -> None:
    schedule = _load(session, principal, schedule_id)
    audit.record(session, "reporting.report_schedule.delete", schedule)
    session.delete(schedule)
    session.flush()


def recipients(session: Session, principal: Principal, report_key: str) -> dict:
    """Staff who may receive this report: active, holding its family key and the export key. Names only."""
    service._spec(principal, report_key)
    authorize(principal, service.EXPORT)
    staff = platform.models.StaffUser
    names = platform.service.staff_user_names(session, session.scalars(select(staff.id).where(staff.is_active)))
    found = []
    # shortcut: builds each active staff user's principal (one permission query each); fine for a facility's
    # staff list, page or cache it if a tenant has hundreds of staff users.
    for staff_user_id, name in sorted(names.items(), key=lambda item: item[1].lower()):
        recipient = platform.staff.principal_for(session, staff_user_id)
        if recipient is not None and _holds_both(recipient, report_key):
            found.append({"id": staff_user_id, "display_name": name})
    return {"data": found, "page": {"next_cursor": None, "has_more": False}}


# --- delivery ------------------------------------------------------------------------------------------------


def _deliver(session: Session, schedule: ReportSchedule, today: date) -> int:
    schedule.last_run_on = today
    saved = session.get_one(SavedReport, schedule.saved_report_id)
    sent = 0
    for staff_user_id in schedule.recipient_staff_user_ids:
        recipient = platform.staff.principal_for(session, staff_user_id)
        if recipient is None or not _holds_both(recipient, saved.report_key):
            continue
        try:
            with session.begin_nested():
                run = service.create_run(session, recipient, {"report_key": saved.report_key, "params": saved.params})
                service.create_export(session, recipient, {
                    "report_run_id": run["id"], "format": schedule.format,
                    "includes_details": schedule.includes_details, "notify_on_complete": True,
                })  # fmt: skip
            sent += 1
        except DomainError as error:  # outside the recipient's locations now, too many rows, and the like
            log.info("report schedule %s skipped a recipient: %s", schedule.id, error.detail)
    audit.record(
        session, "reporting.report_schedule.run", schedule, changes={"last_run_on": today.isoformat(), "sent": sent}
    )
    return sent


def run_due_schedule(session: Session) -> bool:
    """Internal, for the hourly chunked job: deliver the next due schedule; True while others may be due. The
    claim (`last_run_on`) is written under the row lock, so a repeated or concurrent tick sends nothing twice."""
    now = clock.now()
    stmt = (
        select(ReportSchedule).where(ReportSchedule.is_active).order_by(ReportSchedule.id)
        .with_for_update(skip_locked=True)
    )  # fmt: skip
    for schedule in session.scalars(stmt):
        local_now = now.astimezone(ZoneInfo(platform.service.location_time_zone(session, schedule.location_id)))
        if is_due(schedule, local_now):
            _deliver(session, schedule, local_now.date())
            session.flush()
            return True
    return False
