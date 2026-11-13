"""Money and package reports (Phase 12 chip B): receivables by instalment (RPT-06, BIL-19), unapplied payments
(RPT-07), income and balances (RPT-08), underpaid items (RPT-09), accrued session revenue (RPT-10), unused
session value (RPT-22), the package pipeline (RPT-23) and package sales (PKG-15). Builders read the chip B views
only, every query goes through `_loc` and every date window through `_between` (ADR 0010 sections 1 and 2)."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from types import SimpleNamespace
from typing import Literal
from uuid import UUID

from pydantic import Field
from sqlalchemy import BigInteger, and_, cast, false, func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import ValidationFailed
from app.modules.reporting import views as v
from app.modules.reporting.domain import periods
from app.modules.reporting.registry import (
    _BUCKET_COLS,
    ATTENDANCE,
    FINANCIAL,
    MAX_ROWS,
    Col,
    Params,
    RangeParams,
    ReportSpec,
    Scope,
    _between,
    _int,
    _key,
    _loc,
    _sum,
    too_large,
)


def _upto(cut: date, start: date | None = None) -> SimpleNamespace:
    """A window ending at an as-of cut, for `_between` (which reads `from_on` and `to_on`)."""
    return SimpleNamespace(from_on=start or date.min, to_on=cut)


def _paid_by(cut: date, key: str):
    """Allocations in force at the end of `cut`, summed per invoice or per charge (ADR 0010 as-of cut)."""
    a = v.allocation.c
    column = getattr(a, key)
    return (
        select(column.label("id"), func.sum(a.amount_minor).label("paid_minor"))
        .where(column.is_not(None), a.applied_on <= cut, or_(a.released_on.is_(None), a.released_on > cut))
        .group_by(column).subquery()
    )  # fmt: skip


def _fetch(session: Session, stmt, view, scope: Scope) -> list:
    found = list(session.execute(_loc(stmt, view, scope)).all())
    if len(found) > MAX_ROWS:
        raise too_large()  # rows are filtered or regrouped in Python, so the service's count would miss the cap
    return found


def _instalments(session: Session, scope: Scope, cut: date, ids: list[UUID]) -> dict[UUID, list[tuple[date, int]]]:
    """Instalments of the given invoices due on or before `cut`, oldest first, per invoice (basis `due`)."""
    i = v.instalment.c
    due: dict[UUID, list[tuple[date, int]]] = {}
    if not ids:
        return due
    for r in _fetch(session, select(i.invoice_id, i.due_on, i.amount_minor)
                    .where(i.invoice_id.in_(ids), _between(i.due_on, _upto(cut), scope))
                    .order_by(i.invoice_id, i.due_on, i.seq), v.instalment, scope):  # fmt: skip
        due.setdefault(r.invoice_id, []).append((r.due_on, int(r.amount_minor)))
    return due


def _due_position(
    instalments: list[tuple[date, int]], total: int, paid: int, cut: date
) -> tuple[int, int, date | None]:
    """ADR 0010 due-basis arithmetic: amount due as of the cut (instalments due less allocations, floored at zero),
    days past due from the oldest instalment the allocations have not covered, and its due date."""
    owed = min(sum(amount for _, amount in instalments), total)
    left = paid
    for due_on, amount in instalments:
        if left < amount:
            return max(owed - paid, 0), max((cut - due_on).days, 0), due_on
        left -= amount
    return max(owed - paid, 0), 0, None


# --- receivables (RPT-06 due-date mode, BIL-19) --------------------------------------------------------------


class ReceivableParams(Params):
    basis: Literal["due", "invoice"] = Field("due", description="Due: payment-schedule instalments; invoice: date")
    earliest_on: date | None = Field(None, description="Earliest due (or invoice) date; blank means no limit")
    as_of_on: date | None = Field(None, description="Cut-off; defaults to today. Payments on that day count.")
    invoices: Literal["all", "auto_pay_only", "non_auto_pay"] = "all"
    include_collections: bool = Field(True, description="Include clients in collections")
    include_paid: bool = Field(False, description="Include invoices with nothing due at the cut-off")
    clients: Literal["active", "deleted", "both"] = "both"


def _receivables(session: Session, p: ReceivableParams, scope: Scope) -> dict:
    cut = p.as_of_on
    assert cut is not None  # the service fills the as-of default
    if p.earliest_on and p.earliest_on > cut:
        raise ValidationFailed("The earliest date is after the cut-off", pointer="/params/earliest_on")
    r = v.receivable.c
    paid = _paid_by(cut, "invoice_id")
    where = [r.status != "voided", r.invoice_on <= cut]
    if p.basis == "invoice":
        where.append(_between(r.invoice_on, _upto(cut, p.earliest_on), scope))
    if p.invoices != "all":
        where.append(r.is_autopay if p.invoices == "auto_pay_only" else ~r.is_autopay)
    if not p.include_collections:
        where.append(~r.in_collections)
    if p.clients != "both":
        where.append(r.is_client_deleted if p.clients == "deleted" else ~r.is_client_deleted)
    if not p.include_paid:  # settled invoices never owe anything, so keep them out of the row cap
        where.append(r.total_minor > func.coalesce(paid.c.paid_minor, 0))
    found = _fetch(session, select(
        r.invoice_id, r.number, r.client_id, r.client_name, r.client_phone, r.invoice_on, r.due_on, r.total_minor,
        r.is_autopay, r.in_collections, r.collections_tag, r.last_decline_reason,
        func.coalesce(paid.c.paid_minor, 0).label("paid_minor"),
    ).select_from(v.receivable).outerjoin(paid, paid.c.id == r.invoice_id).where(*where)
        .order_by(r.client_name, r.due_on, r.number), v.receivable, scope)  # fmt: skip
    schedule = _instalments(session, scope, cut, [row.invoice_id for row in found]) if p.basis == "due" else {}
    customers: dict[str, dict] = {}
    details = []
    for row in found:
        total, paid_minor = int(row.total_minor), int(row.paid_minor)
        if p.basis == "due":
            instalments = schedule.get(row.invoice_id, [])
            if not any(due_on >= (p.earliest_on or date.min) for due_on, _ in instalments):
                continue  # nothing of it fell due inside the window
            balance, days, due_on = _due_position(instalments, total, paid_minor, cut)
        else:
            balance, days, due_on = max(total - paid_minor, 0), max((cut - row.due_on).days, 0), row.due_on
        if balance <= 0 and not p.include_paid:
            continue
        group = _key(row.client_id)
        details.append({
            "group_key": group, "number": row.number, "invoice_on": row.invoice_on, "due_on": due_on or row.due_on,
            "days_past_due": days if balance > 0 else 0, "total_minor": total, "paid_minor": paid_minor,
            "balance_minor": balance, "is_autopay": row.is_autopay, "last_decline_reason": row.last_decline_reason,
            "collections_tag": row.collections_tag,
        })  # fmt: skip
        customer = customers.setdefault(group, {
            "group_key": group, "client_name": row.client_name or "(no client)", "client_phone": row.client_phone,
            "invoice_count": 0, "total_minor": 0, "paid_minor": 0, "balance_minor": 0, "is_autopay": False,
            "in_collections": bool(row.in_collections), "days_past_due": 0, **dict.fromkeys(periods.BUCKETS, 0),
        })  # fmt: skip
        customer["invoice_count"] += 1
        customer["total_minor"] += total
        customer["paid_minor"] += paid_minor
        customer["balance_minor"] += balance
        customer["is_autopay"] |= bool(row.is_autopay)
        if balance > 0:
            customer["days_past_due"] = max(customer["days_past_due"], days)
            customer[periods.aging_bucket(days)] += balance
    rows = list(customers.values())
    keys = ("invoice_count", "total_minor", "paid_minor", "balance_minor", *periods.BUCKETS)
    return {"rows": rows, "totals": {k: sum(r[k] for r in rows) for k in keys}, "details": details}


# --- unapplied payments (RPT-07) and income and balances (RPT-08) --------------------------------------------


def _unapplied(session: Session, p: Params, scope: Scope) -> dict:
    a = v.client_account.c
    grouped = _fetch(session, select(a.client_id, a.client_name, _sum(a.unapplied_minor, "unapplied_minor"),
                                     _sum(a.unpaid_minor, "unpaid_minor"))
                     .group_by(a.client_id, a.client_name).having(func.sum(a.unapplied_minor) > 0)
                     .order_by(a.client_name), v.client_account, scope)  # fmt: skip
    rows = [{"group_key": _key(r.client_id), "client_name": r.client_name, **_int(r, "unapplied_minor", "unpaid_minor"),
             "liability_minor": int(r.unapplied_minor) - int(r.unpaid_minor)} for r in grouped]  # fmt: skip
    keys = ("unapplied_minor", "unpaid_minor", "liability_minor")
    return {"rows": rows, "totals": {k: sum(r[k] for r in rows) for k in keys}, "details": None}


def _income_balances(session: Session, p: RangeParams, scope: Scope) -> dict:
    i = v.invoice.c
    where = [i.status != "voided", _between(i.invoice_on, p, scope)]
    grouped = session.execute(_loc(
        select(i.client_id, func.max(i.client_name).label("client_name"), func.count().label("invoice_count"),
               _sum(i.total_minor, "total_minor"), _sum(i.balance_minor, "balance_minor"))
        .where(*where).group_by(i.client_id).order_by(func.max(i.client_name)), v.invoice, scope,
    )).all()  # fmt: skip
    rows = [{"group_key": _key(r.client_id), "client_name": r.client_name or "(no client)",
             **_int(r, "invoice_count", "total_minor", "balance_minor"),
             "paid_minor": int(r.total_minor) - int(r.balance_minor)} for r in grouped]  # fmt: skip
    details = [dict(r._mapping) | {"group_key": _key(r.client_id), "paid_minor": int(r.total_minor) - int(r.balance_minor)}
               for r in session.execute(_loc(
                   select(i.client_id, i.number, i.invoice_on, i.due_on, i.status, i.total_minor, i.balance_minor)
                   .where(*where).order_by(i.invoice_on, i.number), v.invoice, scope))]  # fmt: skip
    keys = ("invoice_count", "total_minor", "paid_minor", "balance_minor")
    return {"rows": rows, "totals": {k: sum(r[k] for r in rows) for k in keys}, "details": details}


# --- underpaid items (RPT-09) --------------------------------------------------------------------------------


class UnderpaidParams(Params):
    as_of_on: date | None = Field(None, description="Items not fully paid at the end of this day; defaults to today")
    include_uninvoiced: bool = Field(True, description="Include items not on an invoice yet")
    include_paid_to_date: bool = Field(True, description="Include items on invoices that are current on schedule")
    include_future_invoices: bool = Field(False, description="Include items on invoices dated after the cut-off")


def _underpaid(session: Session, p: UnderpaidParams, scope: Scope) -> dict:
    cut = p.as_of_on
    assert cut is not None
    c = v.charge_item.c
    paid = _paid_by(cut, "charge_id")
    where = [_between(c.revenue_on, _upto(cut), scope)]
    if not p.include_uninvoiced:
        where.append(c.invoice_id.is_not(None))
    if not p.include_future_invoices:
        where.append(or_(c.invoice_id.is_(None), c.invoice_on <= cut))
    found = _fetch(session, select(
        c.client_id, c.client_name, c.invoice_id, c.invoice_number, c.invoice_on, c.revenue_on, c.description,
        c.revenue_category_label, c.total_minor, func.coalesce(paid.c.paid_minor, 0).label("paid_minor"),
    ).select_from(v.charge_item).outerjoin(paid, paid.c.id == c.charge_id)
        .where(*where, c.total_minor > func.coalesce(paid.c.paid_minor, 0))
        .order_by(c.client_name, c.revenue_on, c.charge_id), v.charge_item, scope)  # fmt: skip
    current: set[UUID] = set()
    if not p.include_paid_to_date:
        # an invoice "paid to date" owes nothing as of the cut on its schedule, though items on it are unpaid
        invoice_ids = {r.invoice_id for r in found if r.invoice_id}
        schedule = _instalments(session, scope, cut, list(invoice_ids))
        invoice_paid = _paid_by(cut, "invoice_id")
        rv = v.receivable.c
        for r in _fetch(session, select(rv.invoice_id, rv.total_minor, func.coalesce(invoice_paid.c.paid_minor, 0)
                                        .label("paid_minor")).select_from(v.receivable)
                        .outerjoin(invoice_paid, invoice_paid.c.id == rv.invoice_id)
                        .where(rv.invoice_id.in_(invoice_ids)), v.receivable, scope):  # fmt: skip
            due, _, _ = _due_position(schedule.get(r.invoice_id, []), int(r.total_minor), int(r.paid_minor), cut)
            if due == 0:
                current.add(r.invoice_id)
    clients: dict[str, dict] = {}
    details = []
    for r in found:
        if r.invoice_id in current:
            continue
        group = _key(r.client_id)
        total, paid_minor = int(r.total_minor), int(r.paid_minor)
        details.append({"group_key": group, "invoice_number": r.invoice_number, "invoice_on": r.invoice_on,
                        "revenue_on": r.revenue_on, "description": r.description,
                        "revenue_category": r.revenue_category_label, "total_minor": total, "paid_minor": paid_minor,
                        "balance_minor": total - paid_minor})  # fmt: skip
        client = clients.setdefault(group, {"group_key": group, "client_name": r.client_name or "(no client)",
                                            "item_count": 0, "total_minor": 0, "paid_minor": 0, "balance_minor": 0})  # fmt: skip
        client["item_count"] += 1
        client["total_minor"] += total
        client["paid_minor"] += paid_minor
        client["balance_minor"] += total - paid_minor
    rows = list(clients.values())
    keys = ("item_count", "total_minor", "paid_minor", "balance_minor")
    return {"rows": rows, "totals": {k: sum(r[k] for r in rows) for k in keys}, "details": details}


# --- accrued session revenue (RPT-10) ------------------------------------------------------------------------


class AccruedParams(RangeParams):
    trainer_resource_ids: list[UUID] | None = None


def _accrued(session: Session, p: AccruedParams, scope: Scope) -> dict:
    k = v.package_credit.c
    where = [k.consumed_delta != 0, _between(k.session_on, p, scope)]
    if p.trainer_resource_ids:
        where.append(k.trainer_resource_id.in_(p.trainer_resource_ids))
    value = k.consumed_delta * k.unit_value_minor  # unrounded: rounded half-up once per line and per trainer
    grouped = session.execute(_loc(
        select(k.trainer_resource_id, func.max(k.trainer_name).label("trainer_name"),
               _sum(k.consumed_delta, "sessions"), func.round(func.coalesce(func.sum(value), 0)).label("value_minor"))
        .where(*where).group_by(k.trainer_resource_id).order_by(func.max(k.trainer_name)), v.package_credit, scope,
    )).all()  # fmt: skip
    rows = [{"group_key": _key(r.trainer_resource_id), "trainer": r.trainer_name or "(no trainer)",
             **_int(r, "sessions", "value_minor")} for r in grouped]  # fmt: skip
    details = [dict(r._mapping) | {"group_key": _key(r.trainer_resource_id)} for r in session.execute(_loc(
        select(k.trainer_resource_id, k.session_on, k.client_name, k.package_name, k.trainer_name,
               k.consumed_delta.label("sessions"), cast(func.round(k.unit_value_minor), BigInteger).label("unit_value_minor"),
               cast(func.round(value), BigInteger).label("value_minor"))
        .where(*where).order_by(k.session_on, k.credit_ledger_entry_id), v.package_credit, scope,
    ))]  # fmt: skip
    return {"rows": rows, "totals": {k: sum(r[k] for r in rows) for k in ("sessions", "value_minor")},
            "details": details}  # fmt: skip


# --- unused session value (RPT-22) ---------------------------------------------------------------------------


class UnusedParams(Params):
    as_of_on: date | None = Field(None, description="Value at the end of this day; sessions after it count as unused")
    ignore_expired: bool = Field(False, description="Leave out every package expired by the cut-off")


def _unused(session: Session, p: UnusedParams, scope: Scope) -> dict:
    cut = p.as_of_on
    assert cut is not None
    k, cp = v.package_credit.c, v.client_package.c
    window = _upto(cut)
    moved = (
        select(k.client_package_id,
               func.sum(k.granted_delta).filter(_between(k.occurred_on, window, scope)).label("granted"),
               func.sum(k.consumed_delta).filter(_between(k.session_on, window, scope)).label("used"),
               func.sum(k.forfeited_delta).filter(_between(k.occurred_on, window, scope)).label("forfeited"))
        .group_by(k.client_package_id).subquery()
    )  # fmt: skip
    unused = func.coalesce(moved.c.granted, 0) - func.coalesce(moved.c.used, 0) - func.coalesce(moved.c.forfeited, 0)
    expired = and_(cp.valid_to_on.is_not(None), cp.valid_to_on < cut)
    where = [~cp.is_unlimited, cp.status != "removed", unused > 0,
             ~expired if p.ignore_expired else or_(~expired, cp.allows_booking_after_expiry)]  # fmt: skip
    found = _fetch(session, select(
        cp.client_id, cp.client_name, cp.package_name, cp.reservation_type_name, cp.sold_on, cp.valid_to_on,
        cp.unit_value_minor, func.coalesce(moved.c.granted, 0).label("granted"),
        func.coalesce(moved.c.used, 0).label("used"), unused.label("unused"),
    ).select_from(v.client_package).join(moved, moved.c.client_package_id == cp.client_package_id).where(*where)
        .order_by(cp.client_name, cp.sold_on, cp.client_package_id), v.client_package, scope)  # fmt: skip
    clients: dict[str, dict] = {}
    details = []
    for r in found:
        group = _key(r.client_id)
        value = int((r.unused * r.unit_value_minor).quantize(Decimal(1), ROUND_HALF_UP))  # the one rounding
        details.append({"group_key": group, "package_name": r.package_name, "reservation_type": r.reservation_type_name,
                        "sold_on": r.sold_on, "valid_to_on": r.valid_to_on, **_int(r, "granted", "used", "unused"),
                        "unit_value_minor": int(r.unit_value_minor.quantize(Decimal(1), ROUND_HALF_UP)), "value_minor": value})  # fmt: skip
        client = clients.setdefault(group, {"group_key": group, "client_name": r.client_name, "package_count": 0,
                                            "unused": 0, "value_minor": 0})  # fmt: skip
        client["package_count"] += 1
        client["unused"] += int(r.unused)
        client["value_minor"] += value
    rows = list(clients.values())
    return {"rows": rows, "totals": {k: sum(r[k] for r in rows) for k in ("package_count", "unused", "value_minor")},
            "details": details}  # fmt: skip


# --- package pipeline (RPT-23) and package sales (PKG-15) ----------------------------------------------------


class PipelineParams(Params):
    trainer_staff_user_ids: list[UUID] | None = Field(None, description="Clients whose default trainer is one of these")
    reservation_type_ids: list[UUID] | None = None


def _pipeline_where(p: PipelineParams, scope: Scope) -> list:
    cp = v.client_package.c
    where = [cp.status == "active"]
    if p.trainer_staff_user_ids:
        where.append(cp.default_trainer_staff_user_id.in_(p.trainer_staff_user_ids))
    if p.reservation_type_ids:
        where.append(cp.reservation_type_id.in_(p.reservation_type_ids))
    if scope.own_only:  # a trainer sees the clients they are the default trainer of
        where.append(cp.default_trainer_resource_id == scope.own_resource_id if scope.own_resource_id else false())
    return where


_PACKAGE_COLS = ("client_name", "package_name", "reservation_type_name", "default_trainer_name",
                 "sessions_granted_count", "sessions_consumed_count", "sessions_reserved_count", "sessions_remaining",
                 "valid_from_on", "valid_to_on")  # fmt: skip


def _package_rows(session: Session, where: list, scope: Scope) -> dict:
    cp = v.client_package.c
    rows = [dict(r._mapping) for r in session.execute(_loc(
        select(*(getattr(cp, c) for c in _PACKAGE_COLS)).where(*where)
        .order_by(cp.client_name, cp.valid_to_on, cp.client_package_id), v.client_package, scope,
    ))]  # fmt: skip
    totals = {"package_count": len(rows), "sessions_remaining": sum(r["sessions_remaining"] or 0 for r in rows)}
    return {"rows": rows, "totals": totals, "details": None}


def _package_summary(session: Session, p: PipelineParams, scope: Scope) -> dict:
    return _package_rows(session, _pipeline_where(p, scope), scope)


class ExpiringPackageParams(RangeParams, PipelineParams):
    pass


def _expiring_packages(session: Session, p: ExpiringPackageParams, scope: Scope) -> dict:
    where = [*_pipeline_where(p, scope), _between(v.client_package.c.valid_to_on, p, scope)]
    return _package_rows(session, where, scope)


class RenewalParams(PipelineParams):
    min_remaining: int = Field(1, ge=1, description="Fewest sessions left across the client's open packages")
    max_remaining: int = Field(2, ge=1, description="Most sessions left")
    last_session_before_on: date | None = Field(
        None, description="Leave out clients whose latest booked session is before this date"
    )
    client_category_ids: list[UUID] | None = None


def _renewal_candidates(session: Session, p: RenewalParams, scope: Scope) -> dict:
    if p.max_remaining < p.min_remaining:
        raise ValidationFailed("The maximum is below the minimum", pointer="/params/max_remaining")
    cp, k = v.client_package.c, v.package_credit.c
    where = [*_pipeline_where(p, scope), ~cp.is_unlimited]
    if p.client_category_ids:
        where.append(cp.client_category_id.in_(p.client_category_ids))
    grouped = _fetch(session, select(
        cp.client_id, func.max(cp.client_name).label("client_name"), cp.reservation_type_id,
        func.max(cp.reservation_type_name).label("reservation_type_name"),
        func.max(cp.default_trainer_name).label("default_trainer_name"), func.count().label("package_count"),
        _sum(cp.sessions_remaining, "sessions_remaining"),
    ).where(*where).group_by(cp.client_id, cp.reservation_type_id)
        .having(func.sum(cp.sessions_remaining).between(p.min_remaining, p.max_remaining))
        .order_by(func.max(cp.client_name)), v.client_package, scope)  # fmt: skip
    last = {(r.client_id, r.reservation_type_id): r.last_on for r in _fetch(session, select(
        k.client_id, k.reservation_type_id, func.max(k.session_on).label("last_on"),
    ).where(k.entry_type == "reserve", k.client_id.in_({r.client_id for r in grouped}))
        .group_by(k.client_id, k.reservation_type_id), v.package_credit, scope)}  # fmt: skip
    rows = []
    for r in grouped:
        last_on = last.get((r.client_id, r.reservation_type_id))  # the same service, not any session
        if p.last_session_before_on and (last_on is None or last_on < p.last_session_before_on):
            continue
        rows.append({"client_id": r.client_id, "client_name": r.client_name, "reservation_type_name": r.reservation_type_name,
                     "default_trainer_name": r.default_trainer_name, **_int(r, "package_count", "sessions_remaining"),
                     "last_session_on": last_on})  # fmt: skip
    totals = {
        "client_count": len({r["client_id"] for r in rows}),
        "package_count": sum(r["package_count"] for r in rows),
    }
    return {"rows": rows, "totals": totals, "details": None}


def _package_sales(session: Session, p: RangeParams, scope: Scope) -> dict:
    cp = v.client_package.c
    where = [_between(cp.sold_on, p, scope)]
    grouped = session.execute(_loc(
        select(cp.reservation_type_id, func.max(cp.reservation_type_name).label("reservation_type"),
               func.count().label("package_count"), _sum(cp.sessions_granted_count, "sessions"),
               _sum(cp.cost_minor, "cost_minor"), _sum(cp.paid_minor, "paid_minor"))
        .where(*where).group_by(cp.reservation_type_id).order_by(func.max(cp.reservation_type_name)),
        v.client_package, scope,
    )).all()  # fmt: skip
    rows = [{"group_key": _key(r.reservation_type_id), "reservation_type": r.reservation_type,
             **_int(r, "package_count", "sessions", "cost_minor", "paid_minor"),
             "balance_minor": int(r.cost_minor) - int(r.paid_minor)} for r in grouped]  # fmt: skip
    details = [dict(r._mapping) | {"group_key": _key(r.reservation_type_id),
                                   "balance_minor": int(r.cost_minor) - int(r.paid_minor)}
               for r in session.execute(_loc(
                   select(cp.reservation_type_id, cp.sold_on, cp.client_name, cp.package_name, cp.sold_by_name,
                          cp.is_unlimited, cp.sessions_granted_count, cp.cost_minor, cp.paid_minor)
                   .where(*where).order_by(cp.sold_on, cp.client_package_id), v.client_package, scope))]  # fmt: skip
    keys = ("package_count", "sessions", "cost_minor", "paid_minor", "balance_minor")
    return {"rows": rows, "totals": {k: sum(r[k] for r in rows) for k in keys}, "details": details}


# --- the specs -----------------------------------------------------------------------------------------------

_PAID = (Col("total_minor", "Total", "money"), Col("paid_minor", "Paid", "money"),
         Col("balance_minor", "Balance", "money"))  # fmt: skip
_PACKAGE_COLUMNS = (
    Col("client_name", "Client"), Col("package_name", "Package"), Col("reservation_type_name", "Service"),
    Col("default_trainer_name", "Default trainer"), Col("sessions_granted_count", "Sessions", "count"),
    Col("sessions_consumed_count", "Used", "count"), Col("sessions_reserved_count", "Booked", "count"),
    Col("sessions_remaining", "Remaining", "count"), Col("valid_from_on", "Valid from", "date"),
    Col("valid_to_on", "Expires", "date"),
)  # fmt: skip
_PACKAGE_TOTALS = (Col("package_count", "Packages", "count"), Col("sessions_remaining", "Remaining", "count"))
PACKAGES = "packages"

SPECS = (
    ReportSpec(
        "receivables", "Receivables",
        "Everyone who owes money at the end of the cut-off date and how late it is. By due date each payment-plan "
        "instalment counts when it falls due and payments cover the oldest first; by invoice date the whole "
        "invoice counts. Shows auto-pay, the last auto-pay decline and the collections tag.",
        "financial", FINANCIAL, "due_date", ReceivableParams,
        (Col("client_name", "Customer"), Col("client_phone", "Phone"), Col("invoice_count", "Invoices", "count"),
         *_PAID, *_BUCKET_COLS, Col("days_past_due", "Days past due", "count"), Col("is_autopay", "Auto-pay", "bool"),
         Col("in_collections", "In collections", "bool")),
        (Col("invoice_count", "Invoices", "count"), *_PAID, *_BUCKET_COLS),
        _receivables,
        (Col("number", "Invoice", "number"), Col("invoice_on", "Invoice date", "date"),
         Col("due_on", "Due", "date"), Col("days_past_due", "Days past due", "count"), *_PAID,
         Col("is_autopay", "Auto-pay", "bool"), Col("last_decline_reason", "Last decline"),
         Col("collections_tag", "Collections")),
        ("RPT-06", "BIL-19"),
    ),
    ReportSpec(
        "unapplied_payments", "Unapplied payments by customer",
        "Money each client holds on account (payments neither applied nor refunded) against what they still owe "
        "on invoices. Liability above zero is the client's money; below zero they owe more than they hold.",
        "financial", FINANCIAL, "none", Params,
        (Col("client_name", "Customer"), Col("unapplied_minor", "Unapplied payments", "money"),
         Col("unpaid_minor", "Unpaid invoices", "money"), Col("liability_minor", "Liability", "money")),
        (Col("unapplied_minor", "Unapplied payments", "money"), Col("unpaid_minor", "Unpaid invoices", "money"),
         Col("liability_minor", "Liability", "money")),
        _unapplied, None, ("RPT-07",),
    ),
    ReportSpec(
        "income_balances", "Income and balances by customer",
        "Invoices raised in the period, on the invoice date, per client: what was invoiced, paid and still owed.",
        "financial", FINANCIAL, "invoice_date", RangeParams,
        (Col("client_name", "Customer"), Col("invoice_count", "Invoices", "count"), *_PAID),
        (Col("invoice_count", "Invoices", "count"), *_PAID),
        _income_balances,
        (Col("number", "Invoice", "number"), Col("invoice_on", "Invoice date", "date"),
         Col("due_on", "Due", "date"), Col("status", "Status"), Col("total_minor", "Total", "money"),
         Col("paid_minor", "Paid", "money"), Col("balance_minor", "Balance", "money")),
        ("RPT-08",),
    ),
    ReportSpec(
        "underpaid_items", "Underpaid items",
        "Items earned on or before the cut-off (revenue date) and not fully paid by its end. Payments after the "
        "cut-off do not count.",
        "financial", FINANCIAL, "as_of", UnderpaidParams,
        (Col("client_name", "Customer"), Col("item_count", "Items", "count"), *_PAID),
        (Col("item_count", "Items", "count"), *_PAID),
        _underpaid,
        (Col("invoice_number", "Invoice", "number"), Col("invoice_on", "Invoice date", "date"),
         Col("revenue_on", "Revenue date", "date"), Col("description", "Item"),
         Col("revenue_category", "Revenue category"), *_PAID),
        ("RPT-09",),
    ),
    ReportSpec(
        "accrued_session_revenue", "Accrued session revenue",
        "Package sessions delivered in the period, on the day of the session, valued at the package price over "
        "its sessions (or the per-session price). Credits returned later are netted.",
        "financial", FINANCIAL, "session_date", AccruedParams,
        (Col("trainer", "Trainer"), Col("sessions", "Sessions", "count"), Col("value_minor", "Value", "money")),
        (Col("sessions", "Sessions", "count"), Col("value_minor", "Value", "money")),
        _accrued,
        (Col("session_on", "Date", "date"), Col("client_name", "Client"), Col("package_name", "Package"),
         Col("sessions", "Sessions", "count"), Col("unit_value_minor", "Per session", "money"),
         Col("value_minor", "Value", "money")),
        ("RPT-10",),
    ),
    ReportSpec(
        "unused_session_value", "Unused session value",
        "Sessions bought and not yet used at the end of the cut-off date, at the package's value per session: "
        "what is still owed to clients. Sessions after the cut-off count as unused. Expired packages that "
        "cannot be booked any more are left out; the option leaves out every expired package.",
        PACKAGES, ATTENDANCE, "as_of", UnusedParams,
        (Col("client_name", "Client"), Col("package_count", "Packages", "count"),
         Col("unused", "Unused sessions", "count"), Col("value_minor", "Value", "money")),
        (Col("package_count", "Packages", "count"), Col("unused", "Unused sessions", "count"),
         Col("value_minor", "Value", "money")),
        _unused,
        (Col("package_name", "Package"), Col("reservation_type", "Service"), Col("sold_on", "Sold", "date"),
         Col("valid_to_on", "Expires", "date"), Col("granted", "Sessions", "count"), Col("used", "Used", "count"),
         Col("unused", "Unused", "count"), Col("unit_value_minor", "Per session", "money"),
         Col("value_minor", "Value", "money")),
        ("RPT-22",),
    ),
    ReportSpec(
        "package_summary", "Client package summary",
        "Every open package per client, with sessions used, booked and remaining.",
        PACKAGES, ATTENDANCE, "none", PipelineParams, _PACKAGE_COLUMNS, _PACKAGE_TOTALS, _package_summary, None,
        ("RPT-23", "PKG-15"), own_reach=True,
    ),
    ReportSpec(
        "expiring_packages", "Expiring packages",
        "Open packages whose last valid day falls in the period.",
        PACKAGES, ATTENDANCE, "expiry_date", ExpiringPackageParams, _PACKAGE_COLUMNS, _PACKAGE_TOTALS,
        _expiring_packages, None, ("RPT-23",), own_reach=True,
    ),
    ReportSpec(
        "renewal_candidates", "Renewal candidates",
        "Clients whose open packages for a service have few sessions left, to sell the renewal before they run out.",
        PACKAGES, ATTENDANCE, "none", RenewalParams,
        (Col("client_name", "Client"), Col("reservation_type_name", "Service"),
         Col("default_trainer_name", "Default trainer"), Col("package_count", "Packages", "count"),
         Col("sessions_remaining", "Remaining", "count"), Col("last_session_on", "Last booked session", "date")),
        (Col("client_count", "Clients", "count"), Col("package_count", "Packages", "count")),
        _renewal_candidates, None, ("RPT-23",), own_reach=True,
    ),
    ReportSpec(
        "package_sales", "Package sales",
        "Packages sold in the period, on the sale date, by service: sessions, cost, paid and still owed.",
        PACKAGES, ATTENDANCE, "sale_date", RangeParams,
        (Col("reservation_type", "Service"), Col("package_count", "Packages", "count"),
         Col("sessions", "Sessions", "count"), Col("cost_minor", "Cost", "money"), Col("paid_minor", "Paid", "money"),
         Col("balance_minor", "Balance", "money")),
        (Col("package_count", "Packages", "count"), Col("sessions", "Sessions", "count"),
         Col("cost_minor", "Cost", "money"), Col("paid_minor", "Paid", "money"),
         Col("balance_minor", "Balance", "money")),
        _package_sales,
        (Col("sold_on", "Sold", "date"), Col("client_name", "Client"), Col("package_name", "Package"),
         Col("sold_by_name", "Salesperson"), Col("sessions_granted_count", "Sessions", "count"),
         Col("cost_minor", "Cost", "money"), Col("paid_minor", "Paid", "money"),
         Col("balance_minor", "Balance", "money")),
        ("PKG-15",),
    ),
)  # fmt: skip
