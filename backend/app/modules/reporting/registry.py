"""The report registry (ADR 0010 section 1; RPT-01): one `ReportSpec` per report, keyed as in openapi-programs.yaml
`x-report-families`. Each spec names its family permission, date basis, parameter model (served as JSON
Schema), columns, and a builder that queries the `rpt_*` views only. Builders receive a resolved `Scope` (the
caller's location set and, for `own` reach, their linked trainer resource) and apply it in the query, before
any aggregation, never afterwards (rbac-matrix 6.17). Money is summed in SQL in minor units."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, false, func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import ValidationFailed
from app.modules.reporting import views as v
from app.modules.reporting.domain import periods


@dataclass(frozen=True)
class Col:
    key: str
    label: str
    type: str = "text"  # text, money, count, number, pct, minutes, date, bool

    def out(self) -> dict:
        return {"key": self.key, "label": self.label, "type": self.type}


@dataclass(frozen=True)
class Scope:
    location_ids: tuple[UUID, ...] | None  # None: every location of the tenant
    own_only: bool = False  # `own` reach: rows of the caller's linked trainer resource only
    own_resource_id: UUID | None = None
    # A relative period over locations whose "today" differs, resolved at each location (service.resolve);
    # None when one range fits every location.
    day_ranges: dict[UUID, tuple[date, date]] | None = None


class Params(BaseModel):
    model_config = ConfigDict(extra="forbid")
    location_ids: list[UUID] | None = Field(None, description="Locations to include; empty means all you can see")


class RangeParams(Params):
    period: Literal[periods.PERIODS] | None = Field(None, description="Relative period, resolved at each run")
    from_on: date | None = None
    to_on: date | None = None


@dataclass(frozen=True)
class ReportSpec:
    key: str
    name: str
    description: str
    category: str
    permission: str
    date_basis: str
    params: type[Params]
    columns: tuple[Col, ...]
    totals: tuple[Col, ...]
    build: Callable[[Session, Params, Scope], dict]
    detail_columns: tuple[Col, ...] | None = None
    features: tuple[str, ...] = ()
    own_reach: bool = False

    @property
    def is_ranged(self) -> bool:
        return issubclass(self.params, RangeParams)


MAX_ROWS = 50_000  # rows in one snapshot (summary plus detail); a larger ask must narrow dates or locations


def too_large() -> ValidationFailed:
    return ValidationFailed(f"More than {MAX_ROWS} rows: narrow the dates or locations", code="report-too-large")


def _loc(stmt, view, scope: Scope):
    """Every report query goes through here: the caller's locations in the WHERE clause, and a row cap in SQL so
    an oversized report fails on MAX_ROWS + 1 fetched rows (the service rejects it) instead of loading them all."""
    if scope.location_ids is not None:
        stmt = stmt.where(view.c.location_id.in_(scope.location_ids))
    return stmt.limit(MAX_ROWS + 1)


def _between(column, p, scope: Scope):
    """`column` (a local date in a view with `location_id`) inside the run's period. With per-location ranges
    each location's rows use its own, so an eastern location keeps the first hour of its day while a central
    one is still on the day before."""
    if scope.day_ranges is None:
        return column.between(p.from_on, p.to_on)
    location = column.table.c.location_id
    return or_(*(and_(location == lid, column.between(start, end)) for lid, (start, end) in scope.day_ranges.items()))


def _sum(column, name: str):
    return func.coalesce(func.sum(column), 0).label(name)


def _int(row, *names: str) -> dict:
    return {name: int(getattr(row, name) or 0) for name in names}


def _pct(part: int, whole: int) -> float | None:
    return round(part * 100 / whole, 1) if whole else None


def _key(*parts) -> str:
    return ":".join("none" if part is None else str(part) for part in parts)


# --- financial: revenue (RPT-03) -----------------------------------------------------------------------------

COUNTED_PAYMENTS = ("succeeded", "disputed", "charged_back")


class RevenueParams(RangeParams):
    revenue_category_ids: list[UUID] | None = None
    goal_minor: int | None = Field(None, ge=0, description="Revenue goal for the period, in minor units")


def _revenue(session: Session, p: RevenueParams, scope: Scope) -> dict:
    c = v.charge.c
    where = [c.status != "voided", _between(c.revenue_on, p, scope)]
    if p.revenue_category_ids:
        where.append(c.revenue_category_id.in_(p.revenue_category_ids))
    money = ("discount_minor", "net_minor", "tax_minor", "total_minor")
    summary = session.execute(_loc(
        select(c.revenue_category_id, c.revenue_category_label, func.count().label("charge_count"),
               *(_sum(getattr(c, m), m) for m in money))
        .where(*where).group_by(c.revenue_category_id, c.revenue_category_label).order_by(c.revenue_category_label),
        v.charge, scope,
    )).all()  # fmt: skip
    net = sum(int(r.net_minor) for r in summary)
    rows = [{"group_key": _key(r.revenue_category_id), "revenue_category": r.revenue_category_label,
             **_int(r, "charge_count", *money), "share_pct": _pct(int(r.net_minor), net)} for r in summary]  # fmt: skip
    details = [dict(r._mapping) | {"group_key": _key(r.revenue_category_id)} for r in session.execute(_loc(
        select(c.revenue_category_id, c.revenue_on, c.description, c.kind, c.quantity, c.discount_minor, c.net_minor,
               c.tax_minor, c.total_minor).where(*where).order_by(c.revenue_on, c.charge_id),
        v.charge, scope,
    ))]  # fmt: skip
    pay, ref = v.payment.c, v.refund.c
    received = session.execute(_loc(
        select(_sum(pay.amount_minor, "received"), _sum(pay.unapplied_minor, "unapplied"))
        .where(pay.status.in_(COUNTED_PAYMENTS), _between(pay.received_on, p, scope)), v.payment, scope,
    )).one()  # fmt: skip
    refunded = session.scalar(_loc(
        select(_sum(ref.amount_minor, "refunded")).where(ref.status == "succeeded", _between(ref.refund_on, p, scope)),
        v.refund, scope,
    ))  # fmt: skip
    totals = {k: sum(row[k] for row in rows) for k in ("charge_count", *money)} | {
        "goal_minor": p.goal_minor, "goal_pct": _pct(net, p.goal_minor or 0),
        "payments_received_minor": int(received.received), "payments_unapplied_minor": int(received.unapplied),
        "refunds_minor": int(refunded),
    }  # fmt: skip
    return {"rows": rows, "totals": totals, "details": details}


_MONEY = (Col("discount_minor", "Discounts", "money"), Col("net_minor", "Net revenue", "money"),
          Col("tax_minor", "Tax", "money"), Col("total_minor", "Total", "money"))  # fmt: skip


# --- financial: deposits (RPT-04) ----------------------------------------------------------------------------


def _deposits(session: Session, p: RangeParams, scope: Scope) -> dict:
    pay, ref = v.payment.c, v.refund.c
    in_range = _between(pay.received_on, p, scope)
    by = (pay.tender_kind, pay.tender_label)
    found: dict[tuple, dict] = {}

    def row(kind, label) -> dict:
        return found.setdefault((kind, label), {
            "group_key": _key(kind, label), "tender_label": label, "tender_kind": kind, "payment_count": 0,
            "received_minor": 0, "refunded_minor": 0, "net_minor": 0, "voided_count": 0, "voided_minor": 0,
        })  # fmt: skip

    for r in session.execute(
        _loc(
            select(*by, func.count().label("n"), _sum(pay.amount_minor, "amount"))
            .where(in_range, pay.status.in_(COUNTED_PAYMENTS))
            .group_by(*by),
            v.payment,
            scope,
        )
    ):
        row(r.tender_kind, r.tender_label).update(payment_count=r.n, received_minor=int(r.amount))
    for r in session.execute(
        _loc(
            select(*by, func.count().label("n"), _sum(pay.amount_minor, "amount"))
            .where(in_range, pay.is_voided)
            .group_by(*by),
            v.payment,
            scope,
        )
    ):
        row(r.tender_kind, r.tender_label).update(voided_count=r.n, voided_minor=int(r.amount))
    for r in session.execute(
        _loc(
            select(ref.tender_kind, ref.tender_label, _sum(ref.amount_minor, "amount"))
            .where(ref.status == "succeeded", _between(ref.refund_on, p, scope))
            .group_by(ref.tender_kind, ref.tender_label),
            v.refund,
            scope,
        )
    ):
        row(r.tender_kind, r.tender_label)["refunded_minor"] = int(r.amount)
    rows = sorted(found.values(), key=lambda r: r["tender_label"] or "")
    for r in rows:
        r["net_minor"] = r["received_minor"] - r["refunded_minor"]
    details = [dict(r._mapping) | {"group_key": _key(r.tender_kind, r.tender_label)} for r in session.execute(_loc(
        select(pay.tender_kind, pay.tender_label, pay.receipt_number, pay.received_on, pay.status, pay.amount_minor,
               pay.refunded_minor, pay.unapplied_minor, pay.is_voided, pay.provider_payment_ref)
        .where(in_range, or_(pay.status.in_(COUNTED_PAYMENTS), pay.is_voided)).order_by(pay.received_at, pay.payment_id),
        v.payment, scope,
    ))]  # fmt: skip
    keys = ("payment_count", "received_minor", "refunded_minor", "net_minor", "voided_minor")
    return {"rows": rows, "totals": {k: sum(r[k] for r in rows) for k in keys}, "details": details}


# --- financial: invoices (RPT-05) and open invoices by customer (RPT-06) --------------------------------------

INVOICE_STATUSES = ("open", "payment_pending", "partially_paid", "paid", "voided")


class InvoiceParams(RangeParams):
    statuses: list[Literal[INVOICE_STATUSES]] | None = None


def _invoices(session: Session, p: InvoiceParams, scope: Scope) -> dict:
    i = v.invoice.c
    stmt = select(i.invoice_id, i.number, i.invoice_on, i.due_on, i.client_name, i.organization_name, i.origin,
                  i.status, i.total_minor, i.balance_minor).where(_between(i.invoice_on, p, scope))  # fmt: skip
    if p.statuses:
        stmt = stmt.where(i.status.in_(p.statuses))
    rows = [dict(r._mapping) for r in session.execute(_loc(stmt.order_by(i.invoice_on, i.number), v.invoice, scope))]
    totals = {"invoice_count": len(rows), **{k: sum(int(r[k]) for r in rows) for k in ("total_minor", "balance_minor")}}
    return {"rows": rows, "totals": totals, "details": None}


class OpenInvoiceParams(Params):
    as_of_on: date | None = Field(None, description="Cut-off date; defaults to today. Payments on that day count.")


def _open_invoices(session: Session, p: OpenInvoiceParams, scope: Scope) -> dict:
    i, a = v.invoice.c, v.allocation.c
    cut = p.as_of_on
    paid = (
        select(a.invoice_id, func.sum(a.amount_minor).label("paid_minor"))
        .where(a.invoice_id.is_not(None), a.applied_on <= cut, or_(a.released_on.is_(None), a.released_on > cut))
        .group_by(a.invoice_id).subquery()
    )  # fmt: skip
    found = session.execute(_loc(
        select(i.invoice_id, i.number, i.client_id, i.client_name, i.invoice_on, i.due_on, i.total_minor,
               func.coalesce(paid.c.paid_minor, 0).label("paid_minor"))
        .select_from(v.invoice).outerjoin(paid, paid.c.invoice_id == i.invoice_id)
        .where(i.status != "voided", i.invoice_on <= cut).order_by(i.client_name, i.due_on, i.number),
        v.invoice, scope,
    )).all()  # fmt: skip
    if len(found) > MAX_ROWS:
        raise too_large()  # rows are filtered below, so the service's count would miss the cap
    customers: dict[str, dict] = {}
    details = []
    for r in found:
        balance = int(r.total_minor) - int(r.paid_minor)
        if balance <= 0:
            continue
        days = (cut - r.due_on).days
        group = _key(r.client_id)
        details.append({"group_key": group, "number": r.number, "client_name": r.client_name, "invoice_on": r.invoice_on,
                        "due_on": r.due_on, "days_past_due": max(days, 0), "total_minor": int(r.total_minor),
                        "paid_minor": int(r.paid_minor), "balance_minor": balance})  # fmt: skip
        customer = customers.setdefault(group, {"group_key": group, "client_name": r.client_name or "(no client)",
                                                "invoice_count": 0, "balance_minor": 0, **dict.fromkeys(periods.BUCKETS, 0)})  # fmt: skip
        customer["invoice_count"] += 1
        customer["balance_minor"] += balance
        customer[periods.aging_bucket(days)] += balance
    rows = list(customers.values())
    keys = ("invoice_count", "balance_minor", *periods.BUCKETS)
    return {"rows": rows, "totals": {k: sum(r[k] for r in rows) for k in keys}, "details": details}


_BUCKET_COLS = (Col("current_minor", "Current", "money"), Col("days_1_30_minor", "1 to 30 days", "money"),
                Col("days_31_60_minor", "31 to 60 days", "money"), Col("days_61_90_minor", "61 to 90 days", "money"),
                Col("days_over_90_minor", "Over 90 days", "money"))  # fmt: skip


# --- membership: memberships by status (RPT-12) --------------------------------------------------------------

ENDED = ("expired", "cancelled")


class MembershipStatusParams(Params):
    membership_type_ids: list[UUID] | None = None
    include_ended: bool = Field(False, description="Count expired and cancelled contracts too")
    include_sharers: bool = Field(False, description="Count people sharing a contract as members")


def _memberships_by_status(session: Session, p: MembershipStatusParams, scope: Scope) -> dict:
    m = v.contract.c
    where = [] if p.include_ended else [m.status.not_in(ENDED)]
    if p.membership_type_ids:
        where.append(m.membership_type_id.in_(p.membership_type_ids))
    grouped = session.execute(_loc(
        select(m.status, m.membership_type_id, m.membership_type_name, func.count().label("contract_count"),
               _sum(m.sharer_count, "sharer_count"))
        .where(*where).group_by(m.status, m.membership_type_id, m.membership_type_name)
        .order_by(m.status, m.membership_type_name), v.contract, scope,
    )).all()  # fmt: skip
    rows = []
    for r in grouped:
        counts = _int(r, "contract_count", "sharer_count")
        rows.append({"group_key": _key(r.status, r.membership_type_id), "status": r.status,
                     "membership_type": r.membership_type_name, **counts,
                     "member_count": counts["contract_count"] + (counts["sharer_count"] if p.include_sharers else 0)})  # fmt: skip
    details = [dict(r._mapping) | {"group_key": _key(r.status, r.membership_type_id)} for r in session.execute(_loc(
        select(m.status, m.membership_type_id, m.client_name, m.contract_name, m.start_on, m.end_on, m.is_auto_renew,
               m.sharer_count).where(*where).order_by(m.client_name, m.start_on), v.contract, scope,
    ))]  # fmt: skip
    keys = ("contract_count", "sharer_count", "member_count")
    return {"rows": rows, "totals": {k: sum(r[k] for r in rows) for k in keys}, "details": details}


# --- attendance (RPT-21) -------------------------------------------------------------------------------------

ATTENDANCE_STATUSES = ("scheduled", "attended", "no_show", "excused", "early_cancel", "late_cancel")


class AttendanceParams(RangeParams):
    statuses: list[Literal[ATTENDANCE_STATUSES]] | None = None
    reservation_type_ids: list[UUID] | None = None
    trainer_resource_ids: list[UUID] | None = None
    starts_from: time | None = Field(None, description="Sessions starting at or after this local time")
    starts_to: time | None = Field(None, description="Sessions starting at or before this local time")


def _attendance_where(p: AttendanceParams, scope: Scope) -> list:
    a = v.attendance.c
    where = [_between(a.session_on, p, scope)]
    if p.statuses:
        where.append(a.status.in_(p.statuses))
    if p.reservation_type_ids:
        where.append(a.reservation_type_id.in_(p.reservation_type_ids))
    if p.trainer_resource_ids:
        where.append(a.trainer_resource_id.in_(p.trainer_resource_ids))
    if p.starts_from:
        where.append(a.start_time >= p.starts_from.strftime("%H:%M"))
    if p.starts_to:
        where.append(a.start_time <= p.starts_to.strftime("%H:%M"))
    if scope.own_only:
        where.append(a.trainer_resource_id == scope.own_resource_id if scope.own_resource_id else false())
    return where


def _status_counts(rows: list[dict]) -> dict:
    counts = {s: sum(1 for r in rows if r["status"] == s) for s in ATTENDANCE_STATUSES}
    return counts | {
        "total": len(rows),
        "attended_pct": _pct(counts["attended"], counts["attended"] + counts["no_show"]),
    }


def _attendance_rows(session: Session, p: AttendanceParams, scope: Scope) -> list[dict]:
    a = v.attendance.c
    return [dict(r._mapping) for r in session.execute(_loc(
        select(a.reservation_type_id, a.trainer_resource_id, a.session_on, a.start_time, a.reservation_type_name,
               a.trainer_name, a.client_name, a.status)
        .where(*_attendance_where(p, scope)).order_by(a.session_on, a.start_time, a.client_name, a.enrollment_id),
        v.attendance, scope,
    ))]  # fmt: skip


def _attendance(session: Session, p: AttendanceParams, scope: Scope) -> dict:
    rows = _attendance_rows(session, p, scope)
    return {"rows": rows, "totals": _status_counts(rows), "details": None}


def _attendance_overview(session: Session, p: AttendanceParams, scope: Scope) -> dict:
    details = _attendance_rows(session, p, scope)
    groups: dict[str, list[dict]] = {}
    for row in details:
        row["group_key"] = _key(row["reservation_type_id"], row["trainer_resource_id"])
        groups.setdefault(row["group_key"], []).append(row)
    rows = [{"group_key": key, "reservation_type": items[0]["reservation_type_name"],
             "trainer": items[0]["trainer_name"], **_status_counts(items)} for key, items in groups.items()]  # fmt: skip
    rows.sort(key=lambda r: (r["reservation_type"] or "", r["trainer"] or ""))
    return {"rows": rows, "totals": _status_counts(details), "details": details}


_STATUS_COLS = (Col("scheduled", "Scheduled", "count"), Col("attended", "Attended", "count"),
                Col("no_show", "No-show", "count"), Col("excused", "Excused", "count"),
                Col("early_cancel", "Early cancel", "count"), Col("late_cancel", "Late cancel", "count"),
                Col("total", "Total", "count"), Col("attended_pct", "Attended %", "pct"))  # fmt: skip
_ATTENDEE_COLS = (Col("session_on", "Date", "date"), Col("start_time", "Start"),
                  Col("reservation_type_name", "Class or service"), Col("trainer_name", "Instructor"),
                  Col("client_name", "Client"), Col("status", "Status"))  # fmt: skip


# --- point of sale: sales (RPT-30) and daily register (RPT-32) -----------------------------------------------

SALES_GROUPS = {
    "category": ("product_category_id", "category_name"), "employee": ("cashier_staff_user_id", "cashier_name"),
    "register": ("register_id", "register_name"), "product": ("product_id", "description"),
    "brand": ("product_brand_id", "brand_name"), "supplier": ("product_supplier_id", "supplier_name"),
}  # fmt: skip
_PRODUCT_GROUPS = ("category", "product", "brand", "supplier")
_LINE_SUMS = ("quantity", "gross_minor", "discount_minor", "net_minor", "tax_minor", "total_minor", "returned_quantity")


class PosSalesParams(RangeParams):
    group_by: Literal[tuple(SALES_GROUPS)] = "category"


def _pos_sales(session: Session, p: PosSalesParams, scope: Scope) -> dict:
    s = v.sale_line.c
    key_name, label_name = SALES_GROUPS[p.group_by]
    key, label = getattr(s, key_name), getattr(s, label_name)
    where = [_between(s.sold_on, p, scope)]
    if p.group_by in _PRODUCT_GROUPS:
        where.append(s.line_kind == "product")
    grouped = session.execute(_loc(
        select(key.label("key"), func.max(label).label("label"), func.count(s.pos_sale_id.distinct()).label("sale_count"),
               *(_sum(getattr(s, n), n) for n in _LINE_SUMS)).where(*where).group_by(key),
        v.sale_line, scope,
    )).all()  # fmt: skip
    rows = [{"group_key": _key(r.key), "label": r.label or "(none)", **_int(r, "sale_count", *_LINE_SUMS)}
            for r in grouped]  # fmt: skip
    rows.sort(key=lambda r: (-r["total_minor"], r["label"]))
    details = [dict(r._mapping) | {"group_key": _key(r.key)} for r in session.execute(_loc(
        select(key.label("key"), s.sold_on, s.register_name, s.cashier_name, s.description, s.quantity, s.net_minor,
               s.tax_minor, s.total_minor).where(*where).order_by(s.sold_on, s.pos_sale_id, s.pos_sale_line_id),
        v.sale_line, scope,
    ))]  # fmt: skip
    keys = ("quantity", "gross_minor", "discount_minor", "net_minor", "tax_minor", "total_minor")
    return {"rows": rows, "totals": {k: sum(r[k] for r in rows) for k in keys}, "details": details}


def _daily_register(session: Session, p: RangeParams, scope: Scope) -> dict:
    sale, tender, ret, drawer = v.sale.c, v.tender.c, v.pos_return.c, v.drawer.c
    registers: dict = {}

    def row(register_id, name=None) -> dict:
        found = registers.setdefault(register_id, {
            "group_key": _key(register_id), "register": name, "sale_count": 0, "total_minor": 0, "tax_minor": 0,
            "discount_minor": 0, "cash_minor": 0, "card_minor": 0, "other_payment_minor": 0, "account_credit_minor": 0,
            "pay_later_minor": 0, "return_count": 0, "refunded_minor": 0, "cash_refunded_minor": 0,
            "drawer_count": 0, "expected_cash_minor": 0, "counted_cash_minor": 0, "variance_minor": 0,
        })  # fmt: skip
        found["register"] = found["register"] or name
        return found

    for r in session.execute(_loc(
        select(sale.register_id, sale.register_name, func.count().label("sale_count"), _sum(sale.total_minor, "total_minor"),
               _sum(sale.tax_minor, "tax_minor"), _sum(sale.discount_minor, "discount_minor"))
        .where(_between(sale.sold_on, p, scope)).group_by(sale.register_id, sale.register_name), v.sale, scope,
    )):  # fmt: skip
        row(r.register_id, r.register_name).update(_int(r, "sale_count", "total_minor", "tax_minor", "discount_minor"))
    for r in session.execute(_loc(
        select(tender.register_id, tender.tender, tender.tender_kind, _sum(tender.amount_minor, "amount"))
        .where(_between(tender.sold_on, p, scope))
        .group_by(tender.register_id, tender.tender, tender.tender_kind), v.tender, scope,
    )):  # fmt: skip
        if r.tender == "payment":
            column = {"cash": "cash_minor", "card": "card_minor"}.get(r.tender_kind, "other_payment_minor")
        else:
            column = f"{r.tender}_minor"
        row(r.register_id)[column] += int(r.amount)
    for r in session.execute(_loc(
        select(ret.register_id, ret.register_name, func.count().label("return_count"),
               _sum(ret.refunded_minor, "refunded_minor"), _sum(ret.cash_refunded_minor, "cash_refunded_minor"))
        .where(_between(ret.processed_on, p, scope)).group_by(ret.register_id, ret.register_name),
        v.pos_return, scope,
    )):  # fmt: skip
        row(r.register_id, r.register_name).update(_int(r, "return_count", "refunded_minor", "cash_refunded_minor"))
    for r in session.execute(_loc(
        select(drawer.register_id, drawer.register_name, func.count().label("drawer_count"),
               _sum(drawer.expected_cash_minor, "expected_cash_minor"), _sum(drawer.counted_cash_minor, "counted_cash_minor"),
               _sum(drawer.variance_minor, "variance_minor"))
        .where(_between(drawer.opened_on, p, scope), drawer.status == "closed")
        .group_by(drawer.register_id, drawer.register_name), v.drawer, scope,
    )):  # fmt: skip
        row(r.register_id, r.register_name).update(
            _int(r, "drawer_count", "expected_cash_minor", "counted_cash_minor", "variance_minor")
        )
    rows = sorted(registers.values(), key=lambda r: r["register"] or "")
    keys = [c.key for c in _REGISTER_TOTALS]
    return {"rows": rows, "totals": {k: sum(r[k] for r in rows) for k in keys}, "details": None}


_REGISTER_TOTALS = (Col("sale_count", "Sales", "count"), Col("total_minor", "Sales total", "money"),
                    Col("cash_minor", "Cash", "money"), Col("card_minor", "Card", "money"),
                    Col("other_payment_minor", "Other tenders", "money"),
                    Col("account_credit_minor", "Account credit", "money"), Col("pay_later_minor", "Pay later", "money"),
                    Col("refunded_minor", "Refunded", "money"), Col("cash_refunded_minor", "Cash refunded", "money"),
                    Col("variance_minor", "Drawer variance", "money"))  # fmt: skip


# --- time clock (RPT-37) -------------------------------------------------------------------------------------


class TimeClockParams(RangeParams):
    staff_user_ids: list[UUID] | None = None


def _time_clock(session: Session, p: TimeClockParams, scope: Scope) -> dict:
    t = v.time_entry.c
    where = [_between(t.work_on, p, scope)]
    if p.staff_user_ids:
        where.append(t.staff_user_id.in_(p.staff_user_ids))
    grouped = session.execute(_loc(
        select(t.staff_user_id, t.staff_name, func.count().label("entry_count"),
               func.count().filter(t.clock_out_at.is_(None)).label("open_count"), _sum(t.minutes, "minutes"))
        .where(*where).group_by(t.staff_user_id, t.staff_name).order_by(t.staff_name), v.time_entry, scope,
    )).all()  # fmt: skip
    rows = [{"group_key": _key(r.staff_user_id), "staff_name": r.staff_name,
             **_int(r, "entry_count", "open_count", "minutes"), "hours": round(int(r.minutes) / 60, 2)}
            for r in grouped]  # fmt: skip
    details = [dict(r._mapping) | {"group_key": _key(r.staff_user_id)} for r in session.execute(_loc(
        select(t.staff_user_id, t.work_on, t.staff_name, t.clock_in_time, t.clock_out_time, t.job_name, t.minutes,
               t.source, t.is_edited).where(*where).order_by(t.work_on, t.clock_in_at, t.time_entry_id),
        v.time_entry, scope,
    ))]  # fmt: skip
    minutes = sum(r["minutes"] for r in rows)
    totals = {"entry_count": sum(r["entry_count"] for r in rows), "minutes": minutes, "hours": round(minutes / 60, 2)}
    return {"rows": rows, "totals": totals, "details": details}


# --- the registry --------------------------------------------------------------------------------------------

FINANCIAL, MEMBERSHIP, ATTENDANCE = "reporting.financial.run", "reporting.membership.run", "reporting.attendance.run"
POS, TIME_CLOCK = "reporting.pos.run", "reporting.time_clock.run"

SPECS = (
    ReportSpec(
        "revenue_summary",
        "Revenue summary",
        "Earned revenue by revenue category on the revenue date, against an optional goal. The payment figures "
        "below it use the payment date, so the two halves are not expected to tie.",
        "financial",
        FINANCIAL,
        "revenue_date",
        RevenueParams,
        (
            Col("revenue_category", "Revenue category"),
            Col("charge_count", "Charges", "count"),
            *_MONEY,
            Col("share_pct", "Share of net", "pct"),
        ),
        (
            Col("charge_count", "Charges", "count"),
            *_MONEY,
            Col("goal_minor", "Goal", "money"),
            Col("goal_pct", "Goal reached", "pct"),
            Col("payments_received_minor", "Payments received", "money"),
            Col("payments_unapplied_minor", "Of which unapplied", "money"),
            Col("refunds_minor", "Refunds", "money"),
        ),
        _revenue,
        (
            Col("revenue_on", "Revenue date", "date"),
            Col("description", "Item"),
            Col("kind", "Kind"),
            Col("quantity", "Qty", "number"),
            *_MONEY,
        ),
        ("RPT-03",),
    ),  # fmt: skip
    ReportSpec(
        "deposits",
        "Deposits",
        "Money received by tender on the payment date, less refunds issued in the period. Voided payments are "
        "listed and flagged, and left out of the totals.",
        "financial",
        FINANCIAL,
        "payment_date",
        RangeParams,
        (
            Col("tender_label", "Tender"),
            Col("payment_count", "Payments", "count"),
            Col("received_minor", "Received", "money"),
            Col("refunded_minor", "Refunded", "money"),
            Col("net_minor", "Net", "money"),
            Col("voided_count", "Voided", "count"),
            Col("voided_minor", "Voided amount", "money"),
        ),
        (
            Col("payment_count", "Payments", "count"),
            Col("received_minor", "Received", "money"),
            Col("refunded_minor", "Refunded", "money"),
            Col("net_minor", "Net", "money"),
            Col("voided_minor", "Voided (excluded)", "money"),
        ),
        _deposits,
        (
            Col("receipt_number", "Receipt", "number"),
            Col("received_on", "Received", "date"),
            Col("status", "Status"),
            Col("amount_minor", "Amount", "money"),
            Col("refunded_minor", "Refunded", "money"),
            Col("unapplied_minor", "Unapplied", "money"),
            Col("is_voided", "Voided", "bool"),
            Col("provider_payment_ref", "Processor reference"),
        ),
        ("RPT-04",),
    ),  # fmt: skip
    ReportSpec(
        "invoices",
        "Invoices",
        "Invoices raised in the period, on the invoice date, with their current balance.",
        "financial",
        FINANCIAL,
        "invoice_date",
        InvoiceParams,
        (
            Col("number", "Invoice", "number"),
            Col("invoice_on", "Invoice date", "date"),
            Col("due_on", "Due", "date"),
            Col("client_name", "Bill to"),
            Col("organization_name", "Organization"),
            Col("status", "Status"),
            Col("total_minor", "Total", "money"),
            Col("balance_minor", "Balance", "money"),
        ),
        (
            Col("invoice_count", "Invoices", "count"),
            Col("total_minor", "Total", "money"),
            Col("balance_minor", "Balance", "money"),
        ),
        _invoices,
        None,
        ("RPT-05",),
    ),  # fmt: skip
    ReportSpec(
        "open_invoices",
        "Open invoices by customer",
        "What each customer owed at the end of the cut-off date, aged from each invoice's due date. Payments "
        "applied on or before the cut-off count; later ones do not.",
        "financial",
        FINANCIAL,
        "as_of",
        OpenInvoiceParams,
        (
            Col("client_name", "Customer"),
            Col("invoice_count", "Invoices", "count"),
            *_BUCKET_COLS,
            Col("balance_minor", "Balance", "money"),
        ),
        (Col("invoice_count", "Invoices", "count"), *_BUCKET_COLS, Col("balance_minor", "Balance", "money")),
        _open_invoices,
        (
            Col("number", "Invoice", "number"),
            Col("invoice_on", "Invoice date", "date"),
            Col("due_on", "Due", "date"),
            Col("days_past_due", "Days past due", "count"),
            Col("total_minor", "Total", "money"),
            Col("paid_minor", "Paid by cut-off", "money"),
            Col("balance_minor", "Balance", "money"),
        ),
        ("RPT-06",),
    ),  # fmt: skip
    ReportSpec(
        "memberships_by_status",
        "Memberships by status",
        "Membership contracts by their current status and type.",
        "membership",
        MEMBERSHIP,
        "none",
        MembershipStatusParams,
        (
            Col("status", "Status"),
            Col("membership_type", "Membership type"),
            Col("contract_count", "Contracts", "count"),
            Col("sharer_count", "Sharers", "count"),
            Col("member_count", "Members", "count"),
        ),
        (
            Col("contract_count", "Contracts", "count"),
            Col("sharer_count", "Sharers", "count"),
            Col("member_count", "Members", "count"),
        ),
        _memberships_by_status,
        (
            Col("client_name", "Owner"),
            Col("contract_name", "Membership"),
            Col("start_on", "Starts", "date"),
            Col("end_on", "Ends", "date"),
            Col("is_auto_renew", "Auto-renews", "bool"),
            Col("sharer_count", "Sharers", "count"),
        ),
        ("RPT-12",),
    ),  # fmt: skip
    ReportSpec(
        "attendance",
        "Attendance",
        "Every booked participant of every session in the period, with their attendance status.",
        "programs",
        ATTENDANCE,
        "none",
        AttendanceParams,
        _ATTENDEE_COLS,
        _STATUS_COLS,
        _attendance,
        None,
        ("RPT-21",),
        own_reach=True,
    ),  # fmt: skip
    ReportSpec(
        "attendance_overview",
        "Attendance overview",
        "Attendance counts by class or service and instructor, with the share of participants who attended.",
        "programs",
        ATTENDANCE,
        "none",
        AttendanceParams,
        (Col("reservation_type", "Class or service"), Col("trainer", "Instructor"), *_STATUS_COLS),
        _STATUS_COLS,
        _attendance_overview,
        _ATTENDEE_COLS,
        ("RPT-21",),
        own_reach=True,
    ),  # fmt: skip
    ReportSpec(
        "pos_sales",
        "Point of sale sales",
        "Completed sales in the period grouped by category, employee, register, product, brand or supplier.",
        "pos",
        POS,
        "none",
        PosSalesParams,
        (
            Col("label", "Group"),
            Col("sale_count", "Sales", "count"),
            Col("quantity", "Units", "number"),
            Col("gross_minor", "Gross", "money"),
            *_MONEY,
            Col("returned_quantity", "Units returned", "number"),
        ),
        (Col("quantity", "Units", "number"), Col("gross_minor", "Gross", "money"), *_MONEY),
        _pos_sales,
        (
            Col("sold_on", "Date", "date"),
            Col("register_name", "Register"),
            Col("cashier_name", "Employee"),
            Col("description", "Item"),
            Col("quantity", "Qty", "number"),
            Col("net_minor", "Net", "money"),
            Col("tax_minor", "Tax", "money"),
            Col("total_minor", "Total", "money"),
        ),
        ("RPT-30",),
    ),  # fmt: skip
    ReportSpec(
        "daily_register",
        "Daily register",
        "Per register: sales, tenders collected, refunds and closed drawer counts for the period.",
        "pos",
        POS,
        "none",
        RangeParams,
        (
            Col("register", "Register"),
            Col("sale_count", "Sales", "count"),
            Col("total_minor", "Sales total", "money"),
            Col("tax_minor", "Tax", "money"),
            Col("discount_minor", "Discounts", "money"),
            Col("cash_minor", "Cash", "money"),
            Col("card_minor", "Card", "money"),
            Col("other_payment_minor", "Other tenders", "money"),
            Col("account_credit_minor", "Account credit", "money"),
            Col("pay_later_minor", "Pay later", "money"),
            Col("return_count", "Returns", "count"),
            Col("refunded_minor", "Refunded", "money"),
            Col("cash_refunded_minor", "Cash refunded", "money"),
            Col("drawer_count", "Drawers closed", "count"),
            Col("expected_cash_minor", "Expected cash", "money"),
            Col("counted_cash_minor", "Counted cash", "money"),
            Col("variance_minor", "Variance", "money"),
        ),
        _REGISTER_TOTALS,
        _daily_register,
        None,
        ("RPT-32",),
    ),  # fmt: skip
    ReportSpec(
        "time_clock",
        "Time clock",
        "Clocked time per employee in the period, from time clock entries (voided entries excluded, no rounding).",
        "time_clock",
        TIME_CLOCK,
        "none",
        TimeClockParams,
        (
            Col("staff_name", "Employee"),
            Col("entry_count", "Entries", "count"),
            Col("open_count", "Still open", "count"),
            Col("minutes", "Minutes", "minutes"),
            Col("hours", "Hours", "number"),
        ),
        (Col("entry_count", "Entries", "count"), Col("minutes", "Minutes", "minutes"), Col("hours", "Hours", "number")),
        _time_clock,
        (
            Col("work_on", "Date", "date"),
            Col("clock_in_time", "In"),
            Col("clock_out_time", "Out"),
            Col("job_name", "Job"),
            Col("minutes", "Minutes", "minutes"),
            Col("source", "Source"),
            Col("is_edited", "Edited", "bool"),
        ),
        ("RPT-37",),
    ),  # fmt: skip
)
