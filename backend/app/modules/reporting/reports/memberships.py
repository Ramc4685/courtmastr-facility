"""Membership reports (Phase 12 chip B): revenue by month (RPT-11), deferred revenue (MEM-21), actions (RPT-13),
attrition (RPT-14), expiring memberships (RPT-15) and referrals (RPT-16). Builders read the chip B views only,
every query goes through `_loc` and every date window through `_between` (ADR 0010 sections 1 and 2)."""

from datetime import date, timedelta
from types import SimpleNamespace
from typing import Literal
from uuid import UUID

from pydantic import Field
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session

from app.modules.reporting import views as v
from app.modules.reporting.registry import (
    MEMBERSHIP,
    Col,
    Params,
    RangeParams,
    ReportSpec,
    Scope,
    _between,
    _int,
    _key,
    _loc,
    _pct,
    _sum,
)


def _window(start: date | None, end: date | None) -> SimpleNamespace:
    """An explicit window for `_between` (which reads `from_on` and `to_on`)."""
    return SimpleNamespace(from_on=start or date.min, to_on=end or date.max)


def _month_start(day: date) -> date:
    return day.replace(day=1)


def _next_month(day: date) -> date:
    return (day.replace(day=28) + timedelta(days=4)).replace(day=1)


# --- revenue by month (RPT-11) -------------------------------------------------------------------------------


class TypeRangeParams(RangeParams):
    membership_type_ids: list[UUID] | None = None


def _revenue_by_month(session: Session, p: TypeRangeParams, scope: Scope) -> dict:
    b = v.membership_billing.c
    where = [_between(b.revenue_on, p, scope)]
    if p.membership_type_ids:
        where.append(b.membership_type_id.in_(p.membership_type_ids))
    month = func.to_char(b.revenue_on, "YYYY-MM")
    grouped = session.execute(_loc(
        select(month.label("month"), _sum(b.amount_minor, "total_minor"),
               func.coalesce(func.sum(b.amount_minor).filter(b.is_posted), 0).label("posted_minor"),
               func.count().label("period_count"))
        .where(*where).group_by(month).order_by(month), v.membership_billing, scope,
    )).all()  # fmt: skip
    rows = [{"group_key": r.month, "month": r.month, **_int(r, "period_count", "posted_minor", "total_minor"),
             "scheduled_minor": int(r.total_minor) - int(r.posted_minor)} for r in grouped]  # fmt: skip
    details = [dict(r._mapping) | {"group_key": r.month} for r in session.execute(_loc(
        select(month.label("month"), b.revenue_on, b.client_name, b.contract_name, b.membership_type_name,
               b.description, b.is_posted, b.amount_minor)
        .where(*where).order_by(b.revenue_on, b.billing_schedule_period_id), v.membership_billing, scope,
    ))]  # fmt: skip
    keys = ("period_count", "posted_minor", "scheduled_minor", "total_minor")
    return {"rows": rows, "totals": {k: sum(r[k] for r in rows) for k in keys}, "details": details}


# --- deferred membership revenue (MEM-21) --------------------------------------------------------------------


class DeferredParams(Params):
    as_of_on: date | None = Field(None, description="Recognised up to the end of this day; defaults to today")
    liable_only: bool = Field(False, description="Only contracts holding payments for revenue not yet earned")
    started_from_on: date | None = Field(None, description="Contracts starting on or after")
    started_to_on: date | None = Field(None, description="Contracts starting on or before")
    include_deleted_clients: bool = False
    membership_type_ids: list[UUID] | None = None


def _deferred(session: Session, p: DeferredParams, scope: Scope) -> dict:
    cut = p.as_of_on
    assert cut is not None  # the service fills the as-of default
    b, a = v.membership_billing.c, v.allocation.c
    paid = (
        select(a.charge_id, func.sum(a.amount_minor).label("paid_minor"))
        .where(a.applied_on <= cut, or_(a.released_on.is_(None), a.released_on > cut)).group_by(a.charge_id).subquery()
    )  # fmt: skip
    amount = func.coalesce(paid.c.paid_minor, 0)
    where = [b.is_posted]
    if p.started_from_on or p.started_to_on:
        where.append(_between(b.contract_start_on, _window(p.started_from_on, p.started_to_on), scope))
    if not p.include_deleted_clients:
        where.append(~b.is_client_deleted)
    if p.membership_type_ids:
        where.append(b.membership_type_id.in_(p.membership_type_ids))
    earned = _between(b.revenue_on, _window(None, cut), scope)
    this_month = _between(b.revenue_on, _window(_month_start(cut), cut), scope)
    grouped = session.execute(_loc(
        select(b.membership_contract_id, func.max(b.client_name).label("client_name"),
               func.max(b.contract_name).label("contract_name"), func.max(b.membership_type_name).label("membership_type"),
               func.min(b.contract_start_on).label("start_on"), func.max(b.contract_end_on).label("end_on"),
               _sum(b.billed_minor, "billed_minor"), _sum(amount, "paid_minor"),
               func.coalesce(func.sum(amount).filter(earned), 0).label("recognized_minor"),
               func.coalesce(func.sum(amount).filter(this_month), 0).label("recognized_month_minor"))
        .select_from(v.membership_billing).outerjoin(paid, paid.c.charge_id == b.charge_id).where(*where)
        .group_by(b.membership_contract_id).order_by(func.max(b.client_name), b.membership_contract_id),
        v.membership_billing, scope,
    )).all()  # fmt: skip
    rows = []
    for r in grouped:
        row = {"group_key": _key(r.membership_contract_id), "client_name": r.client_name,
               "contract_name": r.contract_name, "membership_type": r.membership_type, "start_on": r.start_on,
               "end_on": r.end_on, **_int(r, "billed_minor", "paid_minor", "recognized_minor", "recognized_month_minor")}  # fmt: skip
        row["remaining_minor"] = row["paid_minor"] - row["recognized_minor"]
        if row["remaining_minor"] > 0 or not p.liable_only:
            rows.append(row)
    keys = ("billed_minor", "paid_minor", "recognized_minor", "remaining_minor", "recognized_month_minor")
    return {"rows": rows, "totals": {k: sum(r[k] for r in rows) for k in keys}, "details": None}


# --- membership actions (RPT-13) -----------------------------------------------------------------------------


class ActionParams(TypeRangeParams):
    actions: list[Literal["cancelled", "frozen", "suspended"]] | None = None
    cancel_reasons: list[Literal["voluntary", "upgrade", "downgrade", "administrative_error", "other"]] | None = Field(
        None, description="Cancellations with these reasons"
    )
    date_by: Literal["action", "start", "end"] = Field("action", description="Which date falls in the period")


def _actions(session: Session, p: ActionParams, scope: Scope) -> dict:
    m = v.membership_action.c
    column = {"action": m.action_on, "start": m.starts_on, "end": m.ends_on}[p.date_by]
    where = [_between(column, p, scope)]
    if p.actions:
        where.append(m.action.in_(p.actions))
    if p.membership_type_ids:
        where.append(m.membership_type_id.in_(p.membership_type_ids))
    if p.cancel_reasons:
        where.append(or_(m.action != "cancelled", m.cancel_reason.in_(p.cancel_reasons)))
    grouped = session.execute(_loc(
        select(m.action, m.membership_type_id, func.max(m.membership_type_name).label("membership_type"),
               func.count().label("action_count"))
        .where(*where).group_by(m.action, m.membership_type_id).order_by(m.action, func.max(m.membership_type_name)),
        v.membership_action, scope,
    )).all()  # fmt: skip
    rows = [{"group_key": _key(r.action, r.membership_type_id), "action": r.action,
             "membership_type": r.membership_type, "action_count": int(r.action_count)} for r in grouped]  # fmt: skip
    details = [dict(r._mapping) | {"group_key": _key(r.action, r.membership_type_id)} for r in session.execute(_loc(
        select(m.action, m.membership_type_id, m.client_name, m.contract_name, m.action_on, m.starts_on, m.ends_on,
               m.cancel_reason).where(*where).order_by(m.action_on, m.action_id), v.membership_action, scope,
    ))]  # fmt: skip
    return {"rows": rows, "totals": {"action_count": sum(r["action_count"] for r in rows)}, "details": details}


# --- attrition (RPT-14) --------------------------------------------------------------------------------------


class AttritionParams(Params):
    as_of_on: date | None = Field(None, description="The last month of the series: the month holding this date")
    months: int = Field(12, ge=1, le=24, description="Number of months")
    count_frozen_as_active: bool = False
    count_suspended_as_active: bool = False
    include_deleted_clients: bool = False
    membership_type_ids: list[UUID] | None = None


def _attrition(session: Session, p: AttritionParams, scope: Scope) -> dict:
    """ADR 0010: at start = contracts active on the month's first day (frozen or suspended ones only if asked);
    lost = voluntary cancellations, and expiries without a renewal, in the month."""
    assert p.as_of_on is not None
    t, act = v.membership_term.c, v.membership_action.c
    base = []
    if not p.include_deleted_clients:
        base.append(~t.is_client_deleted)
    if p.membership_type_ids:
        base.append(t.membership_type_id.in_(p.membership_type_ids))
    paused = [a for a, counted in (("frozen", p.count_frozen_as_active), ("suspended", p.count_suspended_as_active))
              if not counted]  # fmt: skip
    first = _month_start(p.as_of_on)
    for _ in range(p.months - 1):
        first = _month_start(first - timedelta(days=1))
    rows: list[dict] = []
    details: list[dict] = []
    while first <= p.as_of_on:
        last = _next_month(first) - timedelta(days=1)
        month = first.strftime("%Y-%m")
        active = [t.start_on <= first, t.end_on >= first, or_(t.cancelled_on.is_(None), t.cancelled_on >= first)]
        if paused:
            active.append(~exists().where(
                act.membership_contract_id == t.membership_contract_id, act.action.in_(paused),
                act.starts_on <= first, or_(act.ends_on.is_(None), act.ends_on >= first),
            ))  # fmt: skip
        at_start = session.scalar(_loc(select(func.count()).where(*base, *active), v.membership_term, scope)) or 0
        in_month = _window(first, last)
        lost_where = or_(
            and_(t.cancel_reason == "voluntary", _between(t.cancelled_on, in_month, scope)),
            and_(t.status == "expired", ~t.is_renewed, _between(t.end_on, in_month, scope)),
        )
        lost = [dict(r._mapping) | {"group_key": month} for r in session.execute(_loc(
            select(t.client_name, t.contract_name, t.membership_type_name, t.status, t.end_on, t.cancelled_on,
                   t.cancel_reason).where(*base, lost_where).order_by(t.client_name, t.membership_contract_id),
            v.membership_term, scope,
        ))]  # fmt: skip
        details += lost
        rows.append({"group_key": month if lost else None, "month": month, "at_start": int(at_start), "lost": len(lost),
                     "attrition_pct": _pct(len(lost), int(at_start))})  # fmt: skip
        first = _next_month(first)
    starts, losses = sum(r["at_start"] for r in rows), sum(r["lost"] for r in rows)
    totals = {
        "at_start": starts,
        "lost": losses,
        "average_pct": _pct(losses, starts),
        "total_pct": _pct(losses * len(rows), starts),
    }  # sum(lost) / mean(at start)
    return {"rows": rows, "totals": totals, "details": details}


# --- expiring memberships (RPT-15) and referrals (RPT-16) ----------------------------------------------------


class ExpiringParams(TypeRangeParams):
    include_auto_renew: bool = Field(False, description="Include contracts set to renew automatically")
    include_superseded: bool = Field(False, description="Include contracts even if the owner has a newer one")


def _expiring(session: Session, p: ExpiringParams, scope: Scope) -> dict:
    t = v.membership_term.c
    newer = v.membership_term.alias("newer").c
    where = [t.status.not_in(("cancelled", "upcoming")), _between(t.end_on, p, scope)]
    if p.membership_type_ids:
        where.append(t.membership_type_id.in_(p.membership_type_ids))
    if not p.include_auto_renew:
        where.append(~t.is_auto_renew)
    if not p.include_superseded:
        later = [newer.client_id == t.client_id, newer.end_on > t.end_on, newer.status != "cancelled"]
        if p.membership_type_ids:
            later.append(newer.membership_type_id.in_(p.membership_type_ids))
        where.append(~exists().where(*later))
    rows = [dict(r._mapping) for r in session.execute(_loc(
        select(t.client_name, t.client_email, t.client_phone, t.contract_name, t.membership_type_name, t.status,
               t.end_on, t.is_auto_renew).where(*where).order_by(t.end_on, t.client_name, t.membership_contract_id),
        v.membership_term, scope,
    ))]  # fmt: skip
    return {"rows": rows, "totals": {"contract_count": len(rows)}, "details": None}


def _referrals(session: Session, p: RangeParams, scope: Scope) -> dict:
    t = v.membership_term.c
    where = [t.referred_by_client_id.is_not(None), _between(t.sold_on, p, scope)]
    grouped = session.execute(_loc(
        select(t.referred_by_client_id, func.max(t.referrer_name).label("referrer_name"),
               func.count().label("contract_count"), _sum(t.contract_value_minor, "value_minor"))
        .where(*where).group_by(t.referred_by_client_id).order_by(func.max(t.referrer_name)), v.membership_term, scope,
    )).all()  # fmt: skip
    rows = [{"group_key": _key(r.referred_by_client_id), "referrer_name": r.referrer_name,
             **_int(r, "contract_count", "value_minor")} for r in grouped]  # fmt: skip
    details = [dict(r._mapping) | {"group_key": _key(r.referred_by_client_id)} for r in session.execute(_loc(
        select(t.referred_by_client_id, t.sold_on, t.client_name, t.contract_name, t.membership_type_name,
               t.sold_by_name, t.contract_value_minor.label("value_minor"))
        .where(*where).order_by(t.sold_on, t.membership_contract_id), v.membership_term, scope,
    ))]  # fmt: skip
    return {"rows": rows, "totals": {k: sum(r[k] for r in rows) for k in ("contract_count", "value_minor")},
            "details": details}  # fmt: skip


# --- the specs -----------------------------------------------------------------------------------------------

SPECS = (
    ReportSpec(
        "membership_revenue_by_month", "Membership revenue by month",
        "Membership revenue per month on the revenue date: dues already billed plus those still scheduled, so "
        "future months forecast recurring income. Choose dates ahead of today to look forward.",
        "membership", MEMBERSHIP, "revenue_date", TypeRangeParams,
        (Col("month", "Month"), Col("period_count", "Items", "count"), Col("posted_minor", "Billed", "money"),
         Col("scheduled_minor", "Scheduled", "money"), Col("total_minor", "Total", "money")),
        (Col("posted_minor", "Billed", "money"), Col("scheduled_minor", "Scheduled", "money"),
         Col("total_minor", "Total", "money")),
        _revenue_by_month,
        (Col("revenue_on", "Revenue date", "date"), Col("client_name", "Member"), Col("contract_name", "Membership"),
         Col("description", "Item"), Col("is_posted", "Billed", "bool"), Col("amount_minor", "Amount", "money")),
        ("RPT-11", "MEM-21"),
    ),
    ReportSpec(
        "deferred_membership_revenue", "Deferred membership revenue",
        "Per contract: what was billed and paid, how much of the payments is earned (applied to items whose "
        "revenue date is on or before the cut-off) and how much is still unearned.",
        "membership", MEMBERSHIP, "as_of", DeferredParams,
        (Col("client_name", "Member"), Col("contract_name", "Membership"), Col("membership_type", "Type"),
         Col("start_on", "Starts", "date"), Col("end_on", "Ends", "date"), Col("billed_minor", "Billed", "money"),
         Col("paid_minor", "Paid", "money"), Col("recognized_minor", "Recognised", "money"),
         Col("remaining_minor", "Unearned", "money"), Col("recognized_month_minor", "Recognised this month", "money")),
        (Col("billed_minor", "Billed", "money"), Col("paid_minor", "Paid", "money"),
         Col("recognized_minor", "Recognised", "money"), Col("remaining_minor", "Unearned", "money"),
         Col("recognized_month_minor", "Recognised this month", "money")),
        _deferred, None, ("MEM-21",),
    ),
    ReportSpec(
        "membership_actions", "Membership actions",
        "Cancellations, freezes and suspensions whose action, start or end date falls in the period.",
        "membership", MEMBERSHIP, "action_date", ActionParams,
        (Col("action", "Action"), Col("membership_type", "Membership type"), Col("action_count", "Count", "count")),
        (Col("action_count", "Count", "count"),),
        _actions,
        (Col("client_name", "Member"), Col("contract_name", "Membership"), Col("action_on", "Action date", "date"),
         Col("starts_on", "From", "date"), Col("ends_on", "To", "date"), Col("cancel_reason", "Reason")),
        ("RPT-13", "MEM-21"),
    ),
    ReportSpec(
        "membership_attrition", "Membership attrition",
        "Month by month: memberships active on the first day, memberships lost in the month (voluntary "
        "cancellations and expiries without a renewal) and the attrition rate.",
        "membership", MEMBERSHIP, "as_of", AttritionParams,
        (Col("month", "Month"), Col("at_start", "At start", "count"), Col("lost", "Lost", "count"),
         Col("attrition_pct", "Attrition", "pct")),
        (Col("at_start", "At start", "count"), Col("lost", "Lost", "count"), Col("average_pct", "Average", "pct"),
         Col("total_pct", "Total for period", "pct")),
        _attrition,
        (Col("client_name", "Member"), Col("contract_name", "Membership"), Col("status", "Status"),
         Col("end_on", "Ends", "date"), Col("cancelled_on", "Cancelled", "date"), Col("cancel_reason", "Reason")),
        ("RPT-14", "MEM-21"),
    ),
    ReportSpec(
        "expiring_memberships", "Expiring memberships",
        "Contracts ending in the period whose owner has not renewed: a renewal call list. Auto-renewing contracts "
        "and those superseded by a newer contract of the same owner are left out unless asked for.",
        "membership", MEMBERSHIP, "end_date", ExpiringParams,
        (Col("client_name", "Member"), Col("client_email", "Email"), Col("client_phone", "Phone"),
         Col("contract_name", "Membership"), Col("membership_type_name", "Type"), Col("status", "Status"),
         Col("end_on", "Ends", "date"), Col("is_auto_renew", "Auto-renews", "bool")),
        (Col("contract_count", "Contracts", "count"),),
        _expiring, None, ("RPT-15", "MEM-21"),
    ),
    ReportSpec(
        "membership_referrals", "Membership referrals",
        "Memberships sold in the period that name a referring client, with the contract value per referrer.",
        "membership", MEMBERSHIP, "sale_date", RangeParams,
        (Col("referrer_name", "Referred by"), Col("contract_count", "Memberships", "count"),
         Col("value_minor", "Value", "money")),
        (Col("contract_count", "Memberships", "count"), Col("value_minor", "Value", "money")),
        _referrals,
        (Col("sold_on", "Sold", "date"), Col("client_name", "Member"), Col("contract_name", "Membership"),
         Col("membership_type_name", "Type"), Col("sold_by_name", "Sold by"), Col("value_minor", "Value", "money")),
        ("RPT-16",),
    ),
)  # fmt: skip
