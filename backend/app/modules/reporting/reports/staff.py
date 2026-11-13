"""Staff reports (phase 12 chip D): time entries with their payroll state (STF-08), pay statements of payroll runs
(STF-09) and trainer performance (STF-11, with the RPT-40 trainer productivity figures). Payroll and trainer
performance support `own` reach: rows of the caller's linked trainer resource only (ADR 0010 section 6)."""

from typing import Literal
from uuid import UUID

from pydantic import Field
from sqlalchemy import false, func, select
from sqlalchemy.orm import Session

from app.modules.reporting import views as v
from app.modules.reporting.registry import (
    ATTENDANCE,
    MAX_ROWS,
    TIME_CLOCK,
    Col,
    RangeParams,
    ReportSpec,
    Scope,
    _between,
    _int,
    _key,
    _loc,
    _pct,
    _sum,
    too_large,
)

PAYROLL = "reporting.payroll.run"


def _own(column, scope: Scope) -> list:
    """`own` reach: only the caller's linked trainer resource; no linked resource means no rows."""
    if not scope.own_only:
        return []
    return [column == scope.own_resource_id if scope.own_resource_id else false()]


def _hours(minutes: int) -> float:
    return round(minutes / 60, 2)


# --- STF-08 time entries -------------------------------------------------------------------------------------


class TimeEntryParams(RangeParams):
    staff_user_ids: list[UUID] | None = None
    job_classification_ids: list[UUID] | None = None
    pay_statuses: list[Literal["open", "unpaid", "in_payroll", "paid"]] | None = None
    group_by: Literal["staff", "day", "staff_day"] = "staff"


def _time_entries(session: Session, p: TimeEntryParams, scope: Scope) -> dict:
    t = v.time_entry_pay.c
    where = [_between(t.work_on, p, scope)]
    for column, ids in ((t.staff_user_id, p.staff_user_ids), (t.job_classification_id, p.job_classification_ids),
                        (t.pay_status, p.pay_statuses)):  # fmt: skip
        if ids:
            where.append(column.in_(ids))
    details = [dict(r._mapping) for r in session.execute(_loc(
        select(t.staff_user_id, t.work_on, t.staff_name, t.job_name, t.clock_in_time, t.clock_out_time, t.minutes,
               t.paid_minutes, t.pay_status, t.source, t.is_edited)
        .where(*where).order_by(t.work_on, t.staff_name, t.clock_in_at, t.time_entry_id), v.time_entry_pay, scope,
    ))]  # fmt: skip
    if len(details) > MAX_ROWS:
        raise too_large()
    groups: dict[str, dict] = {}
    for d in details:
        staff, day = d.pop("staff_user_id"), d["work_on"]
        key, label = {"staff": (_key(staff), d["staff_name"]), "day": (_key(day), day.isoformat()),
                      "staff_day": (_key(staff, day), f"{d['staff_name']}, {day.isoformat()}")}[p.group_by]  # fmt: skip
        d["group_key"] = key
        row = groups.setdefault(key, {"group_key": key, "label": label, "entry_count": 0, "open_count": 0,
                                      "minutes": 0, "paid_minutes": 0})  # fmt: skip
        row["entry_count"] += 1
        row["open_count"] += d["pay_status"] == "open"
        row["minutes"] += d["minutes"] or 0
        row["paid_minutes"] += d["paid_minutes"] or 0
    rows = list(groups.values())
    for row in rows:
        row["hours"] = _hours(row["minutes"])
    totals = {k: sum(r[k] for r in rows) for k in ("entry_count", "open_count", "minutes", "paid_minutes")}
    totals["unpaid_count"] = sum(d["pay_status"] in ("unpaid", "in_payroll") for d in details)
    return {"rows": rows, "totals": totals | {"hours": _hours(totals["minutes"])}, "details": details}


# --- STF-09 trainer payroll and commission -------------------------------------------------------------------

_STATEMENT_MONEY = ("session_pay_minor", "commission_minor", "bonus_minor", "hourly_pay_minor", "additional_income_minor",
                    "total_minor")  # fmt: skip


class PayrollParams(RangeParams):
    finalized_only: bool = Field(False, description="Only runs that were finalized")


def _payroll(session: Session, p: PayrollParams, scope: Scope) -> dict:
    s, line = v.pay_statement.c, v.pay_line.c
    where = [_between(s.period_ends_on, p, scope), *_own(s.payee_resource_id, scope)]
    line_where = [_between(line.period_ends_on, p, scope), *_own(line.payee_resource_id, scope)]
    if p.finalized_only:
        where.append(s.run_status == "finalized")
        line_where.append(line.run_status == "finalized")
    rows = [dict(r._mapping) | {"group_key": _key(r.pay_statement_id)} for r in session.execute(_loc(
        select(s.pay_statement_id, s.payee_name, s.period_starts_on, s.period_ends_on, s.run_status, s.commission_basis,
               *(getattr(s, m) for m in _STATEMENT_MONEY))
        .where(*where).order_by(s.period_ends_on, s.payee_name, s.pay_statement_id), v.pay_statement, scope,
    ))]  # fmt: skip
    for row in rows:
        row.pop("pay_statement_id")
    details = []
    for r in session.execute(_loc(
        select(line.pay_statement_id, line.occurred_on, line.kind, line.description, line.quantity, line.rate_minor,
               line.commission_pct, line.base_minor, line.amount_minor, line.was_paid_before)
        .where(*line_where).order_by(line.pay_statement_id, line.occurred_on, line.pay_statement_line_id),
        v.pay_line, scope,
    )):  # fmt: skip
        d = dict(r._mapping)
        d["group_key"] = _key(d.pop("pay_statement_id"))
        for k in ("quantity", "commission_pct"):  # numeric; a commission line has no quantity rate and vice versa
            d[k] = None if d[k] is None else float(d[k])
        details.append(d)
    totals = {"statement_count": len(rows)} | {m: sum(int(r[m]) for r in rows) for m in _STATEMENT_MONEY}
    return {"rows": rows, "totals": totals, "details": details}


# --- STF-11 trainer performance (and RPT-40 trainer productivity) --------------------------------------------


class TrainerParams(RangeParams):
    trainer_resource_ids: list[UUID] | None = None


_CANCELLED = ("early_cancel", "late_cancel")


def _trainer_performance(session: Session, p: TrainerParams, scope: Scope) -> dict:
    a, h, sale, k = v.attendance.c, v.resource_hold.c, v.trainer_package_sale.c, v.package_credit.c
    picked = (lambda column: [column.in_(p.trainer_resource_ids)]) if p.trainer_resource_ids else (lambda column: [])
    trainers: dict = {}

    def row(resource_id, name) -> dict:
        found = trainers.setdefault(resource_id, {
            "group_key": _key(resource_id), "trainer": name, "booking_count": 0, "booked_hours": 0.0,
            "session_count": 0, "participant_count": 0, "attended": 0, "no_show": 0, "attended_pct": None,
            "package_count": 0, "package_sales_minor": 0, "session_value_minor": 0,
        })  # fmt: skip
        found["trainer"] = found["trainer"] or name
        return found

    for r in session.execute(_loc(
        select(h.resource_id, func.max(h.resource_name).label("name"), func.count(h.booking_id.distinct()).label("n"),
               _sum(h.held_minutes, "minutes"))
        .where(h.resource_kind == "trainer", _between(h.held_on, p, scope), *_own(h.resource_id, scope),
               *picked(h.resource_id)).group_by(h.resource_id), v.resource_hold, scope,
    )):  # fmt: skip
        row(r.resource_id, r.name).update(booking_count=int(r.n), booked_hours=_hours(int(r.minutes)))
    att_where = [a.trainer_resource_id.is_not(None), _between(a.session_on, p, scope), *_own(a.trainer_resource_id, scope),
                 *picked(a.trainer_resource_id)]  # fmt: skip
    details = []
    for r in session.execute(_loc(
        select(a.trainer_resource_id, func.max(a.trainer_name).label("trainer_name"), a.session_id,
               func.min(a.session_on).label("session_on"), func.min(a.start_time).label("start_time"),
               func.max(a.reservation_type_name).label("reservation_type_name"),
               func.count().filter(a.status.not_in(_CANCELLED)).label("participant_count"),
               func.count().filter(a.status == "attended").label("attended"),
               func.count().filter(a.status == "no_show").label("no_show"))
        .where(*att_where).group_by(a.trainer_resource_id, a.session_id)
        .order_by(func.min(a.session_on), func.min(a.start_time), a.session_id), v.attendance, scope,
    )):  # fmt: skip
        counts = _int(r, "participant_count", "attended", "no_show")
        found = row(r.trainer_resource_id, r.trainer_name)
        found["session_count"] += 1
        for name, n in counts.items():
            found[name] += n
        details.append({"group_key": found["group_key"], "session_on": r.session_on, "start_time": r.start_time,
                        "reservation_type_name": r.reservation_type_name, **counts})  # fmt: skip
    for r in session.execute(_loc(
        select(sale.trainer_resource_id, func.max(sale.trainer_name).label("name"), func.count().label("n"),
               _sum(sale.price_minor, "amount"))
        .where(_between(sale.sold_on, p, scope), *_own(sale.trainer_resource_id, scope),
               *picked(sale.trainer_resource_id)).group_by(sale.trainer_resource_id), v.trainer_package_sale, scope,
    )):  # fmt: skip
        row(r.trainer_resource_id, r.name).update(package_count=int(r.n), package_sales_minor=int(r.amount))
    for r in session.execute(_loc(
        select(k.trainer_resource_id, func.max(k.trainer_name).label("name"),
               func.round(func.coalesce(func.sum(k.consumed_delta * k.unit_value_minor), 0)).label("value"))
        .where(k.trainer_resource_id.is_not(None), k.consumed_delta != 0, _between(k.session_on, p, scope),
               *_own(k.trainer_resource_id, scope), *picked(k.trainer_resource_id))
        .group_by(k.trainer_resource_id), v.package_credit, scope,
    )):  # fmt: skip
        row(r.trainer_resource_id, r.name)["session_value_minor"] = int(r.value)
    rows = sorted(trainers.values(), key=lambda r: r["trainer"] or "")
    for r in rows:
        r["attended_pct"] = _pct(r["attended"], r["attended"] + r["no_show"])
    keys = ("booking_count", "session_count", "participant_count", "attended", "no_show", "package_count",
            "package_sales_minor", "session_value_minor")  # fmt: skip
    totals = {k: sum(r[k] for r in rows) for k in keys}
    totals |= {"booked_hours": round(sum(r["booked_hours"] for r in rows), 2),
               "attended_pct": _pct(totals["attended"], totals["attended"] + totals["no_show"])}  # fmt: skip
    return {"rows": rows, "totals": totals, "details": details}


# --- the specs -----------------------------------------------------------------------------------------------

_TIME_TOTALS = (Col("entry_count", "Entries", "count"), Col("open_count", "Still open", "count"),
                Col("minutes", "Clocked minutes", "minutes"), Col("paid_minutes", "Paid minutes", "minutes"),
                Col("hours", "Clocked hours", "number"))  # fmt: skip
_PAY_MONEY = (Col("session_pay_minor", "Session pay", "money"), Col("commission_minor", "Commission", "money"),
              Col("bonus_minor", "Bonuses", "money"), Col("hourly_pay_minor", "Hourly pay", "money"),
              Col("additional_income_minor", "Additional income", "money"), Col("total_minor", "Total", "money"))  # fmt: skip
_TRAINER_FIGURES = (
    Col("booking_count", "Calendar bookings", "count"), Col("booked_hours", "Booked hours", "number"),
    Col("session_count", "Sessions with participants", "count"), Col("participant_count", "Participants", "count"),
    Col("attended", "Attended", "count"), Col("no_show", "No-shows", "count"), Col("attended_pct", "Attended %", "pct"),
    Col("package_count", "Packages sold", "count"), Col("package_sales_minor", "Package sales", "money"),
    Col("session_value_minor", "Session value delivered", "money"),
)  # fmt: skip

SPECS = (
    ReportSpec(
        "time_entries", "Time entries",
        "Clocked time by employee, day or both, with each entry's payroll state: still open, not yet in a payroll "
        "run, in a run that is not finalized, or paid by a finalized run (and the minutes it paid). Voided entries "
        "are left out.",
        "time_clock", TIME_CLOCK, "work_date", TimeEntryParams,
        (Col("label", "Group"), *_TIME_TOTALS), (*_TIME_TOTALS, Col("unpaid_count", "Not yet paid", "count")),
        _time_entries,
        (Col("work_on", "Date", "date"), Col("staff_name", "Employee"), Col("job_name", "Job"),
         Col("clock_in_time", "In"), Col("clock_out_time", "Out"), Col("minutes", "Minutes", "minutes"),
         Col("paid_minutes", "Paid minutes", "minutes"), Col("pay_status", "Payroll state"), Col("source", "Source"),
         Col("is_edited", "Edited", "bool")),
        ("STF-08", "RPT-37"),
    ),
    ReportSpec(
        "payroll_statements", "Trainer payroll and commission",
        "Pay statements of the payroll runs whose period ends in the dates chosen, per payee: session pay, "
        "commissions, bonuses, hourly pay and additional income. Voided runs are left out; the lines are the detail.",
        "payroll", PAYROLL, "period_end_date", PayrollParams,
        (Col("payee_name", "Payee"), Col("period_starts_on", "Period from", "date"),
         Col("period_ends_on", "Period to", "date"), Col("run_status", "Run"),
         Col("commission_basis", "Commission on"), *_PAY_MONEY),
        (Col("statement_count", "Statements", "count"), *_PAY_MONEY),
        _payroll,
        (Col("occurred_on", "Date", "date"), Col("kind", "Kind"), Col("description", "Description"),
         Col("quantity", "Quantity", "number"), Col("rate_minor", "Rate", "money"),
         Col("commission_pct", "Commission %", "number"), Col("base_minor", "Commission base", "money"),
         Col("amount_minor", "Amount", "money"), Col("was_paid_before", "Paid in an earlier run", "bool")),
        ("STF-09",), own_reach=True,
    ),
    ReportSpec(
        "trainer_performance", "Trainer performance",
        "Per trainer: bookings and hours on their calendar, sessions with participants, attendance and no-shows, "
        "packages they sold and the package session value they delivered. Trainers see only their own row.",
        "programs", ATTENDANCE, "session_date", TrainerParams,
        (Col("trainer", "Trainer"), *_TRAINER_FIGURES), _TRAINER_FIGURES, _trainer_performance,
        (Col("session_on", "Date", "date"), Col("start_time", "Start"),
         Col("reservation_type_name", "Class or service"), Col("participant_count", "Participants", "count"),
         Col("attended", "Attended", "count"), Col("no_show", "No-shows", "count")),
        ("STF-11", "RPT-40"), own_reach=True,
    ),
)  # fmt: skip
