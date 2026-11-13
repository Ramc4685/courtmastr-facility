"""Client and front-desk reports (phase 12 chip C): low usage (RPT-17), check-in summary (CHK-20), activity items
(RPT-18), contacts and export (RPT-19, IMP-03), demographics (RPT-19), referrals (RPT-20), trial conversions
(RPT-24), retention (RPT-25) and non-training clients (RPT-26). Clients are tenant-wide; their rows carry the
home location, so location scope means "clients whose home location you can see" (README assumptions)."""

from collections.abc import Sequence
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator
from sqlalchemy import case, exists, extract, func, literal, or_, select
from sqlalchemy.orm import Session

from app.core import clock
from app.modules.reporting import views as v
from app.modules.reporting.registry import (
    ENDED,
    MAX_ROWS,
    Col,
    Params,
    RangeParams,
    ReportSpec,
    Scope,
    _between,
    _key,
    _loc,
    _pct,
    too_large,
)

CLIENT, ATTENDANCE = "reporting.client.run", "reporting.attendance.run"
MembershipStatus = Literal["upcoming", "active", "frozen", "suspended", "expired", "cancelled"]
CANCELLED = ("early_cancel", "late_cancel")  # rpt_attendance statuses that are not a scheduled session
COUNTED = ("granted", "granted_override")  # a denied check-in is not a visit
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
GENDERS = {"female": "Female", "male": "Male", "non_binary": "Non-binary", "undisclosed": "Undisclosed"}


def _in(view, scope: Scope):
    """The location filter `_loc` applies, for a subquery (no row cap inside an aggregate)."""
    return view.c.location_id.in_(scope.location_ids) if scope.location_ids is not None else literal(True)


def _capped(rows: Sequence) -> Sequence:
    if len(rows) > MAX_ROWS:
        raise too_large()  # rows are reshaped in Python, so the service's count would miss the cap
    return rows


# --- RPT-17 low usage check-in -------------------------------------------------------------------------------


class LowUsageParams(RangeParams):
    min_check_ins: int = Field(0, ge=0, description="Fewest check-ins in the period to be listed")
    max_check_ins: int = Field(4, ge=0, description="Most check-ins in the period to be listed")
    client_category_ids: list[UUID] | None = None
    membership_statuses: list[MembershipStatus] | None = Field(
        None, description="Only clients holding a membership in one of these statuses"
    )
    membership_type_ids: list[UUID] | None = None

    @model_validator(mode="after")
    def _ordered(self):
        if self.max_check_ins < self.min_check_ins:
            raise ValueError("max_check_ins must not be below min_check_ins")
        return self


def _low_usage(session: Session, p: LowUsageParams, scope: Scope) -> dict:
    c, k, m = v.client.c, v.check_in.c, v.contract.c
    visits = (
        select(k.client_id, func.count().label("n"), func.max(k.check_in_on).label("last_on"))
        .where(k.result.in_(COUNTED), _between(k.check_in_on, p, scope), _in(v.check_in, scope))
        .group_by(k.client_id).subquery()
    )  # fmt: skip
    count = func.coalesce(visits.c.n, 0)
    where = [c.status == "active", count.between(p.min_check_ins, p.max_check_ins)]
    if p.client_category_ids:
        where.append(c.client_category_id.in_(p.client_category_ids))
    if p.membership_statuses or p.membership_type_ids:
        held = [m.client_id == c.client_id, _in(v.contract, scope)]
        if p.membership_statuses:
            held.append(m.status.in_(p.membership_statuses))
        if p.membership_type_ids:
            held.append(m.membership_type_id.in_(p.membership_type_ids))
        where.append(exists(select(m.membership_contract_id).where(*held)))
    rows = [dict(r._mapping) for r in session.execute(_loc(
        select(c.client_name, c.client_category_name, c.email, c.phone, count.label("check_in_count"),
               visits.c.last_on.label("last_check_in_on"))
        .select_from(v.client).outerjoin(visits, visits.c.client_id == c.client_id)
        .where(*where).order_by(count, c.last_name, c.first_name, c.client_id), v.client, scope,
    ))]  # fmt: skip
    return {"rows": rows, "totals": {"client_count": len(rows)}, "details": None}


# --- CHK-20 check-in summary ---------------------------------------------------------------------------------


class CheckInSummaryParams(RangeParams):
    client_category_ids: list[UUID] | None = None
    check_in_station_ids: list[UUID] | None = None


def _check_in_summary(session: Session, p: CheckInSummaryParams, scope: Scope) -> dict:
    k, c = v.check_in.c, v.client.c
    where = [k.result.in_(COUNTED), _between(k.check_in_on, p, scope)]
    if p.client_category_ids:
        where.append(c.client_category_id.in_(p.client_category_ids))
    if p.check_in_station_ids:
        where.append(k.check_in_station_id.in_(p.check_in_station_ids))
    base = select().select_from(v.check_in).outerjoin(v.client, c.client_id == k.client_id).where(*where)
    sections = (
        ("weekday", "By day of week", k.weekday, lambda x: WEEKDAYS[x - 1]),
        ("hour", "By hour of day", k.check_in_hour, lambda x: f"{x:02d}:00"),
        ("gender", "By gender", c.gender, lambda x: GENDERS.get(x, "Unknown")),
        ("category", "By client category", c.client_category_name, lambda x: x or "(no category)"),
        ("membership_type", "By membership type", k.membership_type_name, lambda x: x or "(no membership)"),
    )
    rows = []
    for key, title, column, label in sections:
        found = session.execute(_loc(
            base.add_columns(column.label("value"), func.count().label("check_ins"),
                             func.count(k.client_id.distinct()).label("unique_clients"))
            .group_by(column).order_by(column.nulls_last()), v.check_in, scope,
        )).all()  # fmt: skip
        rows += [{"group_key": _key(key, r.value), "section": title, "label": label(r.value),
                  "check_ins": int(r.check_ins), "unique_clients": int(r.unique_clients)} for r in found]  # fmt: skip
    total = session.execute(_loc(
        base.add_columns(func.count().label("n"), func.count(k.client_id.distinct()).label("u")), v.check_in, scope
    )).one()  # fmt: skip
    return {"rows": rows, "totals": {"check_ins": int(total.n), "unique_clients": int(total.u)}, "details": None}


# --- RPT-18 client activity items ----------------------------------------------------------------------------

TaskStatus = Literal["open", "in_progress", "done", "cancelled"]


class ActivityParams(Params):
    statuses: list[TaskStatus] | None = None
    note_subject_ids: list[UUID] | None = None
    assignee_staff_user_ids: list[UUID] | None = None
    due_by_on: date | None = Field(None, description="Latest due date; empty lists every task")


def _activity_items(session: Session, p: ActivityParams, scope: Scope) -> dict:
    t = v.client_task.c
    where = []
    if p.statuses:
        where.append(t.status.in_(p.statuses))
    if p.note_subject_ids:
        where.append(t.note_subject_id.in_(p.note_subject_ids))
    if p.assignee_staff_user_ids:
        where.append(t.assignee_staff_user_id.in_(p.assignee_staff_user_ids))
    if p.due_by_on:
        where.append(t.due_on <= p.due_by_on)
    rows = [dict(r._mapping) for r in session.execute(_loc(
        select(t.due_on, t.client_name, t.subject, t.status, t.assignee_name, t.created_on, t.completed_on)
        .where(*where).order_by(t.due_on.nulls_last(), t.client_name, t.client_task_id), v.client_task, scope,
    ))]  # fmt: skip
    open_count = sum(1 for r in rows if r["status"] in ("open", "in_progress"))
    return {"rows": rows, "totals": {"task_count": len(rows), "open_count": open_count}, "details": None}


# --- RPT-19 contacts and IMP-03 client export ----------------------------------------------------------------


class ClientExportParams(Params):
    statuses: list[Literal["active", "disabled"]] | None = None
    client_category_ids: list[UUID] | None = None
    include_memberships: bool = Field(False, description="Add each client's current membership")


def _client_export(session: Session, p: ClientExportParams, scope: Scope) -> dict:
    c = v.client.c
    where = []
    if p.statuses:
        where.append(c.status.in_(p.statuses))
    if p.client_category_ids:
        where.append(c.client_category_id.in_(p.client_category_ids))
    rows = [dict(r._mapping) for r in session.execute(_loc(
        select(c.client_id, c.client_name, c.first_name, c.last_name, c.member_number, c.status, c.email, c.phone,
               c.gender, c.client_category_name, c.referral_source, c.default_trainer_name, c.created_on)
        .where(*where).order_by(c.last_name, c.first_name, c.client_id), v.client, scope,
    ))]  # fmt: skip
    current: dict = {}
    if p.include_memberships and 0 < len(rows) <= MAX_ROWS:
        m = v.contract.c
        for r in session.execute(_loc(
            select(m.client_id, m.membership_type_name, m.status, m.end_on)
            .where(m.status.not_in(ENDED), m.client_id.in_([row["client_id"] for row in rows]))
            .order_by(m.start_on), v.contract, scope,
        )):  # fmt: skip
            current[r.client_id] = r  # the latest-starting live contract wins
    for row in rows:
        held = current.get(row.pop("client_id"))
        row |= {"membership_type": held and held.membership_type_name, "membership_status": held and held.status,
                "membership_end_on": held and held.end_on}  # fmt: skip
    return {"rows": rows, "totals": {"client_count": len(rows)}, "details": None}


# --- RPT-19 client demographics ------------------------------------------------------------------------------

AGE_BANDS = ((18, "Under 18"), (25, "18 to 24"), (35, "25 to 34"), (45, "35 to 44"), (55, "45 to 54"),
             (65, "55 to 64"))  # fmt: skip
_AGE_ORDER = {label: n for n, label in enumerate([*(b[1] for b in AGE_BANDS), "65 and over", "Unknown"])}


class DemographicsParams(Params):
    last_session_on: date | None = Field(
        None, description="Only clients with a scheduled class or appointment on or after this date"
    )


def _demographics(session: Session, p: DemographicsParams, scope: Scope) -> dict:
    c, a = v.client.c, v.attendance.c
    where = [c.status == "active"]
    if p.last_session_on:
        where.append(exists(select(a.enrollment_id).where(
            a.client_id == c.client_id, a.session_on >= p.last_session_on, a.status.not_in(CANCELLED),
            _in(v.attendance, scope),
        )))  # fmt: skip
    age = extract("year", func.age(literal(clock.now().date()), c.birth_on))
    band = case(*((age < upper, label) for upper, label in AGE_BANDS), (c.birth_on.is_not(None), "65 and over"),
                else_="Unknown")  # fmt: skip
    rows = []
    for key, title, column, label, order in (
        ("age", "By age band", band, lambda x: x, lambda r: _AGE_ORDER[r.value]),
        ("gender", "By gender", c.gender, lambda x: GENDERS.get(x, "Unknown"), lambda r: (r.value is None, r.value)),
    ):
        found = sorted(session.execute(_loc(
            select(column.label("value"), func.count().label("n")).where(*where).group_by(column), v.client, scope
        )).all(), key=order)  # fmt: skip
        total = sum(int(r.n) for r in found)
        rows += [{"group_key": _key(key, r.value), "section": title, "label": label(r.value), "client_count": int(r.n),
                  "share_pct": _pct(int(r.n), total)} for r in found]  # fmt: skip
    clients = sum(int(r["client_count"] or 0) for r in rows if str(r["group_key"]).startswith("age:"))
    return {"rows": rows, "totals": {"client_count": clients}, "details": None}


# --- RPT-20 client referrals ---------------------------------------------------------------------------------


class ReferralParams(RangeParams):
    group_by: Literal["source", "category"] = Field("source", description="Referral source or referral category")


def _referrals(session: Session, p: ReferralParams, scope: Scope) -> dict:
    c = v.client.c
    column = c.referral_source if p.group_by == "source" else c.referral_category_name
    where = [_between(c.created_on, p, scope)]
    grouped = session.execute(_loc(
        select(column.label("value"), func.count().label("n")).where(*where).group_by(column), v.client, scope
    )).all()  # fmt: skip
    total = sum(int(r.n) for r in grouped)
    rows = [{"group_key": _key(r.value), "label": r.value or "(not recorded)", "client_count": int(r.n),
             "share_pct": _pct(int(r.n), total)} for r in grouped]  # fmt: skip
    rows.sort(key=lambda r: (-int(r["client_count"] or 0), str(r["label"])))
    details = []
    for r in session.execute(_loc(
        select(column.label("value"), c.created_on, c.client_name, c.referral_source, c.referral_category_name, c.email)
        .where(*where).order_by(c.created_on, c.client_id), v.client, scope,
    )):  # fmt: skip
        details.append({**r._mapping, "group_key": _key(r.value)})
        del details[-1]["value"]
    return {"rows": rows, "totals": {"client_count": total}, "details": details}


# --- RPT-24 trial conversions --------------------------------------------------------------------------------


class TrialParams(RangeParams):
    reservation_type_ids: list[UUID] | None = None
    trainer_staff_user_ids: list[UUID] | None = Field(None, description="Clients' default trainers")
    window_days: int = Field(90, ge=1, le=366, description="Days after the trial in which a paid package converts")
    same_reservation_type: bool = Field(False, description="Count only a paid package of the trial's type")


def _trials(session: Session, p: TrialParams, scope: Scope) -> dict:
    k, c = v.client_package.c, v.client.c
    where = [k.is_complimentary, k.status != "removed", _between(k.sold_on, p, scope)]
    if p.reservation_type_ids:
        where.append(k.reservation_type_id.in_(p.reservation_type_ids))
    if p.trainer_staff_user_ids:
        where.append(c.default_trainer_staff_user_id.in_(p.trainer_staff_user_ids))
    trials = _capped(session.execute(_loc(
        select(k.client_package_id, k.client_id, k.reservation_type_id, k.package_name, k.sold_on, c.client_name,
               c.default_trainer_staff_user_id.label("trainer_id"), c.default_trainer_name.label("trainer"))
        .select_from(v.client_package).join(v.client, c.client_id == k.client_id)
        .where(*where).order_by(k.sold_on, k.client_package_id), v.client_package, scope,
    )).all())  # fmt: skip
    paid: dict = {}
    if trials:
        for r in session.execute(_loc(
            select(k.client_id, k.reservation_type_id, k.package_name, k.sold_on)
            .where(~k.is_complimentary, k.status != "removed", k.client_id.in_({t.client_id for t in trials}))
            .order_by(k.sold_on, k.client_package_id), v.client_package, scope,
        )):  # fmt: skip
            paid.setdefault(r.client_id, []).append(r)
    groups: dict[str, dict] = {}
    details = []
    for t in trials:
        last = t.sold_on + timedelta(days=p.window_days)
        bought = next((b for b in paid.get(t.client_id, ()) if t.sold_on <= b.sold_on <= last and (
            not p.same_reservation_type or b.reservation_type_id == t.reservation_type_id)), None)  # fmt: skip
        group = _key(t.trainer_id)
        row = groups.setdefault(group, {"group_key": group, "trainer": t.trainer or "(no default trainer)",
                                        "trial_count": 0, "converted_count": 0})  # fmt: skip
        row["trial_count"] += 1
        row["converted_count"] += bought is not None
        details.append({"group_key": group, "sold_on": t.sold_on, "client_name": t.client_name,
                        "package_name": t.package_name, "converted_on": bought and bought.sold_on,
                        "paid_package": bought and bought.package_name})  # fmt: skip
    rows = sorted(groups.values(), key=lambda r: r["trainer"])
    for row in rows:
        row["conversion_pct"] = _pct(row["converted_count"], row["trial_count"])
    trial_count, converted = sum(r["trial_count"] for r in rows), sum(r["converted_count"] for r in rows)
    totals = {"trial_count": trial_count, "converted_count": converted, "conversion_pct": _pct(converted, trial_count)}
    return {"rows": rows, "totals": totals, "details": details}


# --- RPT-25 client retention ---------------------------------------------------------------------------------


class RetentionParams(Params):
    first_from_on: date = Field(description="Start of the earlier period")
    first_to_on: date
    second_from_on: date = Field(description="Start of the later period")
    second_to_on: date
    reservation_type_ids: list[UUID] | None = None

    @model_validator(mode="after")
    def _ordered(self):
        if self.first_to_on < self.first_from_on or self.second_to_on < self.second_from_on:
            raise ValueError("A period ends before it starts")
        return self


def _retention(session: Session, p: RetentionParams, scope: Scope) -> dict:
    a = v.attendance.c
    first = _between(a.session_on, SimpleNamespace(from_on=p.first_from_on, to_on=p.first_to_on), scope)
    second = _between(a.session_on, SimpleNamespace(from_on=p.second_from_on, to_on=p.second_to_on), scope)
    where = [or_(first, second), a.status.not_in(CANCELLED)]
    if p.reservation_type_ids:
        where.append(a.reservation_type_id.in_(p.reservation_type_ids))
    pairs = session.execute(_loc(
        select(a.trainer_resource_id, func.max(a.trainer_name).label("trainer"), a.client_id,
               func.max(a.client_name).label("client_name"), func.bool_or(first).label("in_first"),
               func.bool_or(second).label("in_second"))
        .where(*where).group_by(a.trainer_resource_id, a.client_id), v.attendance, scope,
    )).all()  # fmt: skip
    groups: dict[str, dict] = {}
    details = []
    for r in _capped(pairs):
        group = _key(r.trainer_resource_id)
        row = groups.setdefault(group, {"group_key": group, "trainer": r.trainer or "(no trainer)", "first_count": 0,
                                        "second_count": 0, "retained_count": 0})  # fmt: skip
        row["first_count"] += r.in_first
        row["second_count"] += r.in_second
        row["retained_count"] += r.in_first and r.in_second
        details.append({"group_key": group, "client_name": r.client_name, "in_first": r.in_first,
                        "in_second": r.in_second})  # fmt: skip
    rows = sorted(groups.values(), key=lambda r: r["trainer"])
    for row in rows:
        row["retention_pct"] = _pct(row["retained_count"], row["first_count"])
    details.sort(key=lambda d: (d["group_key"], d["client_name"] or ""))
    totals = {k: sum(r[k] for r in rows) for k in ("first_count", "second_count", "retained_count")}
    totals["retention_pct"] = _pct(totals["retained_count"], totals["first_count"])
    return {"rows": rows, "totals": totals, "details": details}


# --- RPT-26 non-training clients -----------------------------------------------------------------------------


class NonTrainingParams(Params):
    as_of_on: date | None = Field(None, description="Show clients with nothing scheduled after this date (today)")
    trainer_staff_user_ids: list[UUID] | None = Field(None, description="Clients' default trainers")
    client_category_ids: list[UUID] | None = None
    include_never_scheduled: bool = True
    include_without_packages: bool = True
    ignore_empty_packages: bool = Field(False, description="A package with no sessions left counts as none")


def _non_training(session: Session, p: NonTrainingParams, scope: Scope) -> dict:
    c, a, k = v.client.c, v.attendance.c, v.client_package.c
    last = (
        select(a.client_id, func.max(a.session_on).label("last_on"))
        .where(a.status.not_in(CANCELLED), _in(v.attendance, scope)).group_by(a.client_id).subquery()
    )  # fmt: skip
    live = [k.client_id == c.client_id, k.status == "active", _in(v.client_package, scope)]
    if p.ignore_empty_packages:
        live.append(or_(k.is_unlimited, k.sessions_remaining > 0))
    has_package = exists(select(k.client_package_id).where(*live))
    lapsed = last.c.last_on <= p.as_of_on
    where = [c.status == "active", or_(lapsed, last.c.last_on.is_(None)) if p.include_never_scheduled else lapsed]
    if not p.include_without_packages:
        where.append(has_package)
    if p.trainer_staff_user_ids:
        where.append(c.default_trainer_staff_user_id.in_(p.trainer_staff_user_ids))
    if p.client_category_ids:
        where.append(c.client_category_id.in_(p.client_category_ids))
    rows = [dict(r._mapping) for r in session.execute(_loc(
        select(c.client_name, last.c.last_on.label("last_session_on"), c.default_trainer_name, c.client_category_name,
               has_package.label("has_package"), c.email, c.phone)
        .select_from(v.client).outerjoin(last, last.c.client_id == c.client_id)
        .where(*where).order_by(last.c.last_on.nulls_first(), c.last_name, c.first_name, c.client_id),
        v.client, scope,
    ))]  # fmt: skip
    return {"rows": rows, "totals": {"client_count": len(rows)}, "details": None}


# --- the specs -----------------------------------------------------------------------------------------------

_CONTACT = (Col("email", "Email"), Col("phone", "Phone"))
_SECTION = (Col("section", "Section"), Col("label", "Group"))

SPECS = (
    ReportSpec(
        "low_usage_check_ins", "Low usage check-in",
        "Active clients whose check-ins in the period fall between a minimum and a maximum: members who barely "
        "visit. Denied check-ins do not count.",
        "clients", CLIENT, "check_in_date", LowUsageParams,
        (Col("client_name", "Client"), Col("client_category_name", "Category"), *_CONTACT,
         Col("check_in_count", "Check-ins", "count"), Col("last_check_in_on", "Last check-in", "date")),
        (Col("client_count", "Clients", "count"),), _low_usage, None, ("RPT-17",),
    ),
    ReportSpec(
        "check_in_summary", "Check-in summary",
        "Check-ins in the period by day of week, hour, gender, client category and membership type, each with the "
        "number of distinct clients. Hours are the location's local time.",
        "clients", ATTENDANCE, "check_in_date", CheckInSummaryParams,
        (*_SECTION, Col("check_ins", "Check-ins", "count"), Col("unique_clients", "Unique clients", "count")),
        (Col("check_ins", "Check-ins", "count"), Col("unique_clients", "Unique clients", "count")),
        _check_in_summary, None, ("CHK-20",),
    ),
    ReportSpec(
        "client_activity_items", "Client activity items",
        "Client follow-up tasks by status, subject, assignee and due date.",
        "clients", CLIENT, "none", ActivityParams,
        (Col("due_on", "Due", "date"), Col("client_name", "Client"), Col("subject", "Subject"),
         Col("status", "Status"), Col("assignee_name", "Assigned to"), Col("created_on", "Created", "date"),
         Col("completed_on", "Completed", "date")),
        (Col("task_count", "Tasks", "count"), Col("open_count", "Open", "count")), _activity_items, None, ("RPT-18",),
    ),
    ReportSpec(
        "client_export", "Client contacts and export",
        "Every client with contact details, optionally with their current membership, for mail merge and outside "
        "analysis.",
        "clients", CLIENT, "none", ClientExportParams,
        (Col("client_name", "Client"), Col("first_name", "First name"), Col("last_name", "Last name"),
         Col("member_number", "Member number"), Col("status", "Status"), *_CONTACT, Col("gender", "Gender"),
         Col("client_category_name", "Category"), Col("referral_source", "Referral source"),
         Col("default_trainer_name", "Default trainer"), Col("created_on", "Created", "date"),
         Col("membership_type", "Membership"), Col("membership_status", "Membership status"),
         Col("membership_end_on", "Membership ends", "date")),
        (Col("client_count", "Clients", "count"),), _client_export, None, ("RPT-19", "IMP-03"),
    ),
    ReportSpec(
        "client_demographics", "Client demographics",
        "Active clients by age band and gender, optionally only those with a session on or after a date.",
        "clients", CLIENT, "none", DemographicsParams,
        (*_SECTION, Col("client_count", "Clients", "count"), Col("share_pct", "Share", "pct")),
        (Col("client_count", "Clients", "count"),), _demographics, None, ("RPT-19",),
    ),
    ReportSpec(
        "client_referrals", "Client referrals",
        "Clients created in the period by how they heard of you: referral source or referral category.",
        "clients", CLIENT, "created_date", ReferralParams,
        (Col("label", "Referred by"), Col("client_count", "Clients", "count"), Col("share_pct", "Share", "pct")),
        (Col("client_count", "Clients", "count"),), _referrals,
        (Col("created_on", "Created", "date"), Col("client_name", "Client"), Col("referral_source", "Source"),
         Col("referral_category_name", "Category"), Col("email", "Email")),
        ("RPT-20",),
    ),
    ReportSpec(
        "trial_conversions", "Trial conversions",
        "Complimentary packages given in the period, by the client's default trainer, and whether the client bought "
        "a paid package within the window that follows.",
        "clients", CLIENT, "sold_date", TrialParams,
        (Col("trainer", "Default trainer"), Col("trial_count", "Trials", "count"),
         Col("converted_count", "Converted", "count"), Col("conversion_pct", "Conversion", "pct")),
        (Col("trial_count", "Trials", "count"), Col("converted_count", "Converted", "count"),
         Col("conversion_pct", "Conversion", "pct")),
        _trials,
        (Col("sold_on", "Trial given", "date"), Col("client_name", "Client"), Col("package_name", "Trial"),
         Col("converted_on", "Converted", "date"), Col("paid_package", "Paid package")),
        ("RPT-24",),
    ),
    ReportSpec(
        "client_retention", "Client retention",
        "Per trainer: distinct clients with a scheduled session in each of two periods, and the share of the "
        "earlier period's clients scheduled again in the later one. Cancelled bookings do not count.",
        "clients", CLIENT, "session_date", RetentionParams,
        (Col("trainer", "Trainer"), Col("first_count", "Earlier period", "count"),
         Col("second_count", "Later period", "count"), Col("retained_count", "In both", "count"),
         Col("retention_pct", "Retention", "pct")),
        (Col("first_count", "Earlier period", "count"), Col("second_count", "Later period", "count"),
         Col("retained_count", "In both", "count"), Col("retention_pct", "Retention", "pct")),
        _retention,
        (Col("client_name", "Client"), Col("in_first", "Earlier period", "bool"),
         Col("in_second", "Later period", "bool")),
        ("RPT-25",),
    ),
    ReportSpec(
        "non_training_clients", "Non-training clients",
        "Active clients with nothing scheduled after a date, to win back. The trainer filter uses the client's "
        "default trainer.",
        "clients", CLIENT, "as_of", NonTrainingParams,
        (Col("client_name", "Client"), Col("last_session_on", "Last session", "date"),
         Col("default_trainer_name", "Default trainer"), Col("client_category_name", "Category"),
         Col("has_package", "Has a package", "bool"), *_CONTACT),
        (Col("client_count", "Clients", "count"),), _non_training, None, ("RPT-26",),
    ),
)  # fmt: skip
