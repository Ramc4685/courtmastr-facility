"""Post-billed packages (PKG-11) and the period close (BIL-18).

A post-billed package is a `client_package` with `billing_mode = 'post_billed'`: unlimited, free at opening, open
ended. It is spent like any package, through `reserve_credit` and `settle_credit`, so a session counts as used when
its credit is consumed (attended, or a no-show or late cancel the package settings charge). A close bills, per
package, every used session not billed before whose credit was consumed on or before the closing date (the
location's calendar), at the rate tier reached by that count, through `billing.service.post_charge` and
`create_invoice_for_charges`. A held credit not yet settled is reported as unsettled and waits for a later close.

Idempotent per period: one close per location and closing date (a repeat returns the first close), each charge is
keyed on its line, and `post_billed_usage` keeps a session from being billed twice. A credit restored after it was
billed is credited at the next close: the line's charge is adjusted down (or reversed) through billing's public
functions. A package without auto-renew ends at a close that leaves nothing held and nothing used after the closing
date; one with auto-renew stays open. Each package bills in its own savepoint, so one failure is reported and the
rest of the close goes ahead; the failed package is billed at a later close.
"""

from datetime import date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import audit, clock, events
from app.core.api import CONSTRAINT_CODES
from app.core.auth import Principal, authorize, scope_query
from app.core.errors import DomainError, NotFound, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.modules import billing, clients, platform
from app.modules.packages import service
from app.modules.packages.events import PostBilledPeriodClosed
from app.modules.packages.models import (
    ClientPackage,
    CreditLedgerEntry,
    PostBilledClose,
    PostBilledLine,
    PostBilledRate,
    PostBilledUsage,
)

CLOSE = "packages.period.close"
CONSTRAINT_CODES["uq_post_billed_rate_tier"] = "rate-tier-exists"


# --- rates -------------------------------------------------------------------------------------------------------


def list_rates(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, service._MANAGE)
    r = PostBilledRate
    return paginate(
        session, select(r), query, id_column=r.id,
        sort_fields={"min_sessions": r.min_sessions, "created_at": r.created_at}, default_sort="min_sessions",
        filter_fields={"reservation_type_id": r.reservation_type_id, "is_active": r.is_active},
    )  # fmt: skip


def create_rate(session: Session, principal: Principal, data: dict) -> PostBilledRate:
    authorize(principal, service._MANAGE)
    rate = PostBilledRate(**data)
    session.add(rate)
    session.flush()
    _require_base_tier(session, rate.reservation_type_id)
    audit.record(session, service._MANAGE, rate, changes=audit.diff(rate))
    return rate


def update_rate(session: Session, principal: Principal, rate_id: UUID, data: dict) -> PostBilledRate:
    authorize(principal, service._MANAGE)
    rate = service._get(session, PostBilledRate, rate_id, lock=True)
    service._apply(rate, data)
    session.flush()
    _require_base_tier(session, rate.reservation_type_id)
    audit.record(session, service._MANAGE, rate, changes=audit.diff(rate))
    return rate


def _require_base_tier(session: Session, reservation_type_id: UUID) -> None:
    """Active tiers always start at one session, so every used session has a rate."""
    r = PostBilledRate
    tiers = set(
        session.scalars(select(r.min_sessions).where(r.reservation_type_id == reservation_type_id, r.is_active))
    )
    if tiers and 1 not in tiers:
        raise ValidationFailed("The first rate tier must start at one session.", pointer="/min_sessions")


def _tier(session: Session, reservation_type_id: UUID, count: int) -> PostBilledRate | None:
    """The active rate with the highest threshold the count reaches."""
    r = PostBilledRate
    stmt = select(r).where(r.reservation_type_id == reservation_type_id, r.is_active, r.min_sessions <= count)
    return session.scalar(stmt.order_by(r.min_sessions.desc()).limit(1))


# --- opening a package -------------------------------------------------------------------------------------------


def open_package(session: Session, principal: Principal, data: dict) -> dict:
    """Open a post-billed package for a client: nothing is charged now; sessions are billed at a close."""
    location_id = data["location_id"]
    authorize(principal, service._SELL, location_id=location_id)
    clients.service.require_active(session, data["client_id"])
    has_rate = select(PostBilledRate.id).where(
        PostBilledRate.reservation_type_id == data["reservation_type_id"], PostBilledRate.is_active
    )
    if session.scalar(has_rate.limit(1)) is None:
        raise ValidationFailed(
            "Set a post-billed rate for this reservation type first.", pointer="/reservation_type_id"
        )
    related = service._related_ids(session, data["client_id"]) if data["share_with_related"] else []
    fields = {
        "owner_client_id": data["client_id"], "location_id": location_id,
        "reservation_type_id": data["reservation_type_id"], "name": data.get("name") or "Post-billed sessions",
        "is_unlimited": True, "valid_during": Range(service._today(session, location_id), None), "price_minor": 0,
        "invoice_mode": "none", "is_autopay": data["is_autopay"], "is_auto_renew": data["is_auto_renew"],
        "share_mode": "all_related" if related else "none", "billing_mode": "post_billed",
        "sold_by_staff_user_id": service._staff_id(principal), "sales_channel": "staff",
    }  # fmt: skip
    package, _ = service._issue(session, fields, 0, share_with=[(cid, "manual") for cid in related])
    audit.record(
        session, service._SELL, package, location_id=location_id, changes={"billing_mode": [None, "post_billed"]}
    )
    return service.package_view(session, package)


# --- usage and the close -----------------------------------------------------------------------------------------


def _local(at: datetime, zone: ZoneInfo) -> date:
    return at.astimezone(zone).date()


def _usage(session: Session, package: ClientPackage, closing_on: date, zone: ZoneInfo) -> list[tuple[str, UUID]]:
    """The sources (booking or enrolment) that used a session and are billable at this close."""
    e = CreditLedgerEntry
    u = PostBilledUsage
    billed = select(u.source_id).where(u.client_package_id == package.id, u.credited_at.is_(None))
    rows = session.execute(
        select(e.source_type, e.source_id, func.max(e.occurred_at).filter(e.entry_type == "consume"))
        .where(e.client_package_id == package.id, e.source_id.is_not(None), e.source_id.not_in(billed))
        .group_by(e.source_type, e.source_id)
        .having(func.sum(e.consumed_delta) > 0)
        .order_by(e.source_type, e.source_id)
    )  # fmt: skip
    return [(kind, source_id) for kind, source_id, at in rows if kind and source_id and _local(at, zone) <= closing_on]


def _restored(session: Session, package: ClientPackage) -> list[PostBilledUsage]:
    """Billed usage whose credit has since gone back to the package (net consumed is no longer positive)."""
    u, e = PostBilledUsage, CreditLedgerEntry
    net = (
        select(func.coalesce(func.sum(e.consumed_delta), 0))
        .where(e.client_package_id == package.id, e.source_type == u.source_type, e.source_id == u.source_id)
        .scalar_subquery()
    )
    stmt = select(u).where(u.client_package_id == package.id, u.credited_at.is_(None), net <= 0)
    return list(session.scalars(stmt.order_by(u.id)))


def _plan(session: Session, location_id: UUID, closing_on: date, *, lock: bool) -> list[dict]:
    """Every open post-billed package at the location, plus any other (ended, removed) with usage still to bill or
    a billed credit to give back: owed usage is billed once, through `post_billed_usage`."""
    p = ClientPackage
    stmt = select(p).where(p.location_id == location_id, p.billing_mode == "post_billed")
    packages = list(session.scalars((stmt.with_for_update() if lock else stmt).order_by(p.id)))
    zone = ZoneInfo(platform.service.location_time_zone(session, location_id))
    usage = {pkg.id: _usage(session, pkg, closing_on, zone) for pkg in packages}
    credits = {pkg.id: _restored(session, pkg) for pkg in packages}
    packages = [pkg for pkg in packages if pkg.status == "active" or usage[pkg.id] or credits[pkg.id]]
    names = clients.service.display_names(session, [pkg.owner_client_id for pkg in packages])
    lines = []
    for package in packages:
        used = usage[package.id]
        rate = _tier(session, package.reservation_type_id, len(used)) if used else None
        lines.append({
            "package": package, "used": used, "rate": rate, "credits": credits[package.id], "zone": zone,
            "client_package_id": package.id,
            "client_id": package.owner_client_id, "client_name": names.get(package.owner_client_id),
            "package_name": package.name, "session_count": len(used),
            "unsettled_count": package.sessions_reserved_count,
            "per_session_minor": rate.per_session_minor if rate else None,
            "total_minor": rate.per_session_minor * len(used) if rate else 0,
            "skipped_reason": None if rate else ("no-usage" if not used else "no-rate"),
        })  # fmt: skip
    return lines


def _check_date(session: Session, location_id: UUID, closing_on: date) -> None:
    if closing_on > service._today(session, location_id):
        raise ValidationFailed("A period can be closed up to today only.", pointer="/closing_on")


def _existing(session: Session, location_id: UUID, closing_on: date) -> PostBilledClose | None:
    c = PostBilledClose
    return session.scalar(select(c).where(c.location_id == location_id, c.closing_on == closing_on))


def _close_view(session: Session, close: PostBilledClose) -> dict:
    line = PostBilledLine
    lines = list(session.scalars(select(line).where(line.post_billed_close_id == close.id).order_by(line.id)))
    names = clients.service.display_names(session, [row.client_id for row in lines])
    return {c.key: getattr(close, c.key) for c in PostBilledClose.__table__.columns} | {
        "lines": [
            {c.key: getattr(row, c.key) for c in line.__table__.columns} | {"client_name": names.get(row.client_id)}
            for row in lines
        ]
    }


def preview_close(session: Session, principal: Principal, data: dict) -> dict:
    """What a close would bill: every package the close would cover, billable or not (credit-backs are not
    shown). Writes nothing."""
    location_id, closing_on = data["location_id"], data["closing_on"]
    authorize(principal, CLOSE, location_id=location_id)
    _check_date(session, location_id, closing_on)
    done = _existing(session, location_id, closing_on)
    lines = _plan(session, location_id, closing_on, lock=False)
    hidden = ("package", "used", "rate")
    return {
        "location_id": location_id, "closing_on": closing_on, "post_billed_close_id": done.id if done else None,
        "lines": [{k: v for k, v in line.items() if k not in hidden} for line in lines],
    }  # fmt: skip


def close_period(session: Session, principal: Principal, data: dict) -> dict:
    """Bill the period up to the closing date. A close already made for that location and date is returned as
    it is, so a retried or repeated run never bills twice."""
    location_id, closing_on = data["location_id"], data["closing_on"]
    authorize(principal, CLOSE, location_id=location_id)
    _check_date(session, location_id, closing_on)
    if (done := _existing(session, location_id, closing_on)) is not None:
        return _close_view(session, done)
    close = PostBilledClose(
        location_id=location_id, closing_on=closing_on, closed_by_staff_user_id=service._staff_id(principal)
    )
    try:
        with session.begin_nested():
            session.add(close)
            session.flush()
    except IntegrityError:  # a concurrent close of the same period won
        won = _existing(session, location_id, closing_on)
        assert won is not None
        return _close_view(session, won)
    billable, failed = [], []
    for line in _plan(session, location_id, closing_on, lock=True):
        if not (line["rate"] or line["credits"]):
            continue
        try:
            with session.begin_nested():
                _credit_back(session, line)
                if line["rate"]:
                    _bill(session, close, line, closing_on)
        except (DomainError, IntegrityError) as exc:  # this package waits for a later close
            failed.append({"client_package_id": line["client_package_id"], "code": getattr(exc, "code", "conflict")})
            continue
        if line["rate"]:
            billable.append(line)
    close.package_count = len(billable)
    close.session_count = sum(line["session_count"] for line in billable)
    close.total_minor = sum(line["total_minor"] for line in billable)
    audit.record(
        session, CLOSE, close, location_id=location_id,
        changes={"closing_on": closing_on.isoformat(), "package_count": close.package_count, "total_minor": close.total_minor},
    )  # fmt: skip
    closed = PostBilledPeriodClosed(post_billed_close_id=close.id, location_id=location_id, package_count=len(billable))
    events.publish(session, closed, close.id)
    session.flush()
    return _close_view(session, close) | {"failed": failed}


def _credit_back(session: Session, line: dict) -> None:
    """Give back billed sessions whose credit was restored: adjust each line's charge down, or reverse it."""
    by_line: dict[UUID, list[PostBilledUsage]] = {}
    for usage in line["credits"]:
        by_line.setdefault(usage.post_billed_line_id, []).append(usage)
    now = clock.now()
    for line_id, rows in by_line.items():
        billed = session.get_one(PostBilledLine, line_id)
        if billed.charge_id is not None:
            charge = billing.service.get_charge(session, billed.charge_id)
            left, reason = charge.quantity - len(rows), "Post-billed sessions credited back"
            if left > 0:
                billed.charge_id = billing.service.adjust_charge(session, charge.id, reason=reason, quantity=left).id
            else:
                billing.service.reverse(session, charge.id, reason=reason)
        for usage in rows:
            usage.credited_at = now
        audit.record(session, CLOSE, billed, changes={"credited_sessions": len(rows)})
    session.flush()


def _bill(session: Session, close: PostBilledClose, line: dict, closing_on: date) -> None:
    package, rate = line["package"], line["rate"]
    row = PostBilledLine(
        post_billed_close_id=close.id, client_package_id=package.id, client_id=package.owner_client_id,
        session_count=line["session_count"], per_session_minor=rate.per_session_minor, total_minor=line["total_minor"],
    )  # fmt: skip
    session.add(row)
    session.flush()
    charge = billing.service.post_charge(
        session, client_id=package.owner_client_id, location_id=package.location_id,
        description=f"{package.name}: {row.session_count} sessions", unit_price_minor=rate.per_session_minor,
        quantity=row.session_count, source_context="packages", source_type="post_billed_line", source_id=row.id,
        revenue_category_id=rate.revenue_category_id or package.revenue_category_id, service_ends_on=closing_on,
    )  # fmt: skip
    row.charge_id = charge.id
    if charge.total_minor > 0:
        invoice = billing.service.create_invoice_for_charges(
            session, [charge.id], origin="system", is_autopay=package.is_autopay
        )
        row.invoice_id = invoice.id
    u = PostBilledUsage
    credited = {
        (r.source_type, r.source_id): r
        for r in session.scalars(select(u).where(u.client_package_id == package.id, u.credited_at.is_not(None)))
    }
    for kind, sid in line["used"]:
        if (again := credited.get((kind, sid))) is not None:  # used again after a credit-back: one row per source
            again.post_billed_line_id, again.credited_at = row.id, None
        else:
            session.add(u(post_billed_line_id=row.id, client_package_id=package.id, source_type=kind, source_id=sid))
    session.flush()
    settled = package.sessions_reserved_count == 0 and not _usage(session, package, date.max, line["zone"])
    if not package.is_auto_renew and package.status == "active" and settled:
        last = max(package.valid_during.lower, closing_on)
        package.valid_during = Range(package.valid_during.lower, last + timedelta(days=1))
        service._expire(session, package)
    session.flush()


def list_closes(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, CLOSE)
    c = PostBilledClose
    page = paginate(
        session, scope_query(select(c), principal, c.location_id), query, id_column=c.id,
        sort_fields={"closing_on": c.closing_on, "created_at": c.created_at}, default_sort="-closing_on",
        filter_fields={"location_id": c.location_id, "closing_on": c.closing_on},
    )  # fmt: skip
    return page | {"data": [_close_view(session, row) for row in page["data"]]}


def get_close(session: Session, principal: Principal, close_id: UUID) -> dict:
    close = session.get(PostBilledClose, close_id)
    if close is None or not (principal.location_ids is None or close.location_id in principal.location_ids):
        raise NotFound()
    authorize(principal, CLOSE, location_id=close.location_id)
    return _close_view(session, close)
