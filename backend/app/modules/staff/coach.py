"""Independent coaches' revenue share (staff README "Coach revenue share"): engagement, share rules, the earnings
ledger and payout statements. The software records what the facility owes and paid; it moves no money.

Internal functions (no principal): `reconcile_source` and `reconcile_package`, called by `handlers.py`. Everything
else is a staff command with both gates.
"""

import csv
import io
from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import audit, clock, pdf
from app.core.api import CONSTRAINT_CODES
from app.core.auth import Principal, authorize, scope_query
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.modules import billing, packages, platform, programs, scheduling
from app.modules.staff.domain import share
from app.modules.staff.models import (
    CoachEarning,
    CoachEngagement,
    CoachPayout,
    CoachPayoutLine,
    CoachShareRule,
    StaffPayee,
)
from app.modules.staff.service import (
    PAY_MANAGE,
    PAY_READ,
    _csv_safe,
    _engagements,
    _is_own,
    _not_own_payee,
    _scoped,
)

COACH_READ = "staff.coach_payout.read"
PAYOUT_CREATE = "staff.coach_payout.create"
PAYOUT_ADJUST = "staff.coach_payout.adjust"
PAYOUT_APPROVE = "staff.coach_payout.approve"
PAYOUT_PAY = "staff.coach_payout.pay"
NO_MONEY_MOVED = (
    "This statement records what the facility owes and paid. The software does not move money: pay the coach by "
    "bank transfer, cheque or another method, then record it here."
)

CONSTRAINT_CODES["uq_coach_payout_line_earning"] = "payout-conflict"


# --- engagement and tax form -------------------------------------------------------------------------------------


def _trainer(session: Session, principal: Principal, payee_id: UUID, key: str) -> StaffPayee:
    payee = _scoped(session, principal, StaffPayee, payee_id)
    authorize(principal, key, location_id=payee.location_id)
    if key == PAY_MANAGE:
        _not_own_payee(session, principal, payee)  # nobody below Admin sets their own terms
    if payee.kind != "trainer":
        raise ValidationFailed("Only a coach (a trainer payee) has an engagement.", pointer="/engagement")
    return payee


def list_engagements(session: Session, principal: Principal, payee_id: UUID) -> list[CoachEngagement]:
    payee = _trainer(session, principal, payee_id, PAY_READ)
    return list(session.scalars(
        select(CoachEngagement).where(CoachEngagement.staff_payee_id == payee.id)
        .order_by(CoachEngagement.effective_from_on)
    ))  # fmt: skip


def _refuse_backdated(session: Session, payees, day: date) -> None:
    """A change of terms dated before today at the coach's location, when the coach already has sessions on or after
    that date, would pay those lessons twice or not at all: the ledger is not re-run. Forward-dated is fine."""
    for payee in payees:
        if day >= platform.service.location_today(session, payee.location_id):
            continue
        zone = ZoneInfo(platform.service.location_time_zone(session, payee.location_id))
        since = datetime.combine(day, time(), zone)
        if session.scalar(select(scheduling.service.booking_ids(resource_id=payee.resource_id, starts_from=since)
                                 .exists())):  # fmt: skip
            raise ValidationFailed(
                f"{payee.display_name} already has sessions on or after this date: choose today or a later date.",
                pointer="/effective_from_on", code="effective-date-has-sessions",
            )


def set_engagement(session: Session, principal: Principal, payee_id: UUID, data: dict) -> CoachEngagement:
    """Staff coach (employee) or independent coach from a date on. A row for the same date is replaced."""
    payee = _trainer(session, principal, payee_id, PAY_MANAGE)
    _refuse_backdated(session, [payee], data["effective_from_on"])
    row = session.scalar(select(CoachEngagement).where(
        CoachEngagement.staff_payee_id == payee.id, CoachEngagement.effective_from_on == data["effective_from_on"]
    ))  # fmt: skip
    if row is None:
        row = CoachEngagement(staff_payee_id=payee.id, effective_from_on=data["effective_from_on"], engagement="")
        session.add(row)
    row.engagement = data["engagement"]
    changes = audit.diff(row)  # before the flush, so a replace logs the old and the new engagement
    session.flush()
    day = row.effective_from_on.isoformat()
    audit.record(session, PAY_MANAGE, row, location_id=payee.location_id,
                 changes={"effective_from_on": [day, day]} | changes)  # fmt: skip
    return row


def set_tax_form(session: Session, principal: Principal, payee_id: UUID, data: dict) -> StaffPayee:
    """Records only whether a tax form is on file and since when; never a tax identifier."""
    payee = _trainer(session, principal, payee_id, PAY_MANAGE)
    payee.tax_form_on_file_on = data.get("tax_form_on_file_on")
    audit.record(session, PAY_MANAGE, payee, location_id=payee.location_id, changes=audit.diff(payee))
    session.flush()
    return payee


def engagement_on(session: Session, payee_id: UUID, day: date) -> str:
    return share.in_force(_engagements(session, [payee_id]).get(payee_id, []), day) or "employee"


# --- share rules -------------------------------------------------------------------------------------------------


def list_share_rules(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, PAY_READ)
    return paginate(
        session, select(CoachShareRule), query, id_column=CoachShareRule.id,
        sort_fields={"effective_from_on": CoachShareRule.effective_from_on}, default_sort="effective_from_on",
        filter_fields={"staff_payee_id": CoachShareRule.staff_payee_id,
                       "reservation_type_id": CoachShareRule.reservation_type_id},
    )  # fmt: skip


def put_share_rule(session: Session, principal: Principal, data: dict) -> CoachShareRule:
    """A default, per lesson type, per coach, or per coach and type share from a date; the same key and date is
    replaced. Earning lines keep the share they were made with."""
    authorize(principal, PAY_MANAGE)
    location_id = None
    if data.get("staff_payee_id"):
        try:
            payee = _trainer(session, principal, data["staff_payee_id"], PAY_MANAGE)
        except NotFound:
            raise ValidationFailed("Unknown coach.", pointer="/staff_payee_id") from None
        location_id = payee.location_id
        affected = [payee]
    else:  # a default or lesson-type rule reaches every coach who is, or was, independent
        affected = list(session.scalars(select(StaffPayee).where(StaffPayee.id.in_(
            select(CoachEngagement.staff_payee_id).where(CoachEngagement.engagement == "independent")
        )).order_by(StaffPayee.id)))  # fmt: skip
    _refuse_backdated(session, affected, data["effective_from_on"])
    if data.get("reservation_type_id"):
        try:
            scheduling.service.get_type(session, principal, data["reservation_type_id"])
        except NotFound:
            raise ValidationFailed("Unknown lesson type.", pointer="/reservation_type_id") from None
    key = {k: data.get(k) for k in ("staff_payee_id", "reservation_type_id")}
    row = session.scalar(select(CoachShareRule).where(
        CoachShareRule.staff_payee_id.is_not_distinct_from(key["staff_payee_id"]),
        CoachShareRule.reservation_type_id.is_not_distinct_from(key["reservation_type_id"]),
        CoachShareRule.effective_from_on == data["effective_from_on"],
    ))  # fmt: skip
    if row is None:
        row = CoachShareRule(**key, effective_from_on=data["effective_from_on"])
        session.add(row)
    for field in ("coach_share_pct", "court_fee_minor", "court_fee_basis", "court_fee_applies"):
        setattr(row, field, data[field])
    changes = audit.diff(row)  # before the flush: old and new percent, court fee and date (not personal data)
    session.flush()
    day = row.effective_from_on.isoformat()
    audit.record(session, PAY_MANAGE, row, location_id=location_id,
                 changes={"effective_from_on": [day, day]} | changes)  # fmt: skip
    return row


def delete_share_rule(session: Session, principal: Principal, rule_id: UUID) -> None:
    authorize(principal, PAY_MANAGE)
    row = session.get(CoachShareRule, rule_id)
    if row is None:
        raise NotFound()
    location_id = None
    if row.staff_payee_id is not None:
        location_id = _trainer(session, principal, row.staff_payee_id, PAY_MANAGE).location_id
    audit.record(session, PAY_MANAGE, row, location_id=location_id, changes={"deleted": True})
    session.delete(row)
    session.flush()


# --- the earnings ledger (internal: event handlers) --------------------------------------------------------------


def _target(session: Session, source_type: str, source_id: UUID) -> dict | None:
    """What one lesson place should earn now, or None: the credit must be spent (attended, or a no-show the package
    charges), from a bought package, on a session whose trainer column belongs to a coach who was independent that
    day. With no share rule in force the line is still written, wholly the facility's, so the gap shows."""
    credit = packages.service.session_credit_facts(session, source_type, [source_id]).get(source_id)
    if credit is None or credit["is_complimentary"]:
        return None
    if source_type == "enrollment":
        place = programs.service.enrollment_facts(session, source_id)
        if place is None:
            return None
        booking_id = scheduling.service.get_session(session, place["session_id"])["booking_id"]
    else:
        booking_id = source_id
    view = scheduling.service.booking_views(session, [booking_id]).get(booking_id)
    if view is None:
        return None
    columns = [r["resource_id"] for r in view["resources"]]
    payee = session.scalar(select(StaffPayee).where(StaffPayee.resource_id.in_(columns)).order_by(StaffPayee.id))
    if payee is None:
        return None
    day = view["starts_at"].astimezone(ZoneInfo(platform.service.location_time_zone(session, view["location_id"])))
    day = day.date()
    if engagement_on(session, payee.id, day) != "independent":
        return None
    rule = share.pick_rule(list(session.scalars(select(CoachShareRule))), payee.id, view["reservation_type_id"], day)
    package_id = credit["client_package_id"]
    net = billing.service.source_totals(session, "packages", "client_package", [package_id])
    lessons = packages.service.package_lessons(session, package_id)
    number = lessons["lessons"].index((source_type, source_id)) + 1
    gross = share.lesson_value(net.get(package_id, {}).get("net_minor", 0), lessons["sold"], number)
    minutes = int((view["ends_at"] - view["starts_at"]).total_seconds() // 60)
    # The ledger is immutable and has no client id, so erasure and export could never reach a name: no client text.
    label, pct, fee, facility, coach = "Lesson", None, 0, gross, 0
    if rule is not None:  # no rule: the lesson is still recorded, all the facility's, so the gap shows on the statement
        pct = rule.coach_share_pct
        fee = share.court_fee(rule.court_fee_minor, rule.court_fee_basis, minutes)
        facility, coach = share.split(gross, rule.coach_share_pct, fee, rule.court_fee_applies)
    if rule is None:
        label = f"{label} (no share rule)"
    return {
        "location_id": view["location_id"], "staff_payee_id": payee.id, "earned_on": day,
        "reservation_type_id": view["reservation_type_id"], "description": label, "gross_minor": gross,
        "facility_share_minor": facility, "coach_share_minor": coach, "coach_share_pct": pct,
        "court_fee_minor": fee,
    }  # fmt: skip


def reconcile_source(session: Session, source_type: str, source_id: UUID) -> None:
    """Bring one lesson place's earning lines in line with its money: write the lesson line when it is recognised,
    a reversing line when the credit comes back or the package is refunded (then a new line at the new value).
    Idempotent: replaying an event finds nothing to change."""
    if source_type not in ("enrollment", "booking"):
        return
    # The ledger is append-only (no UPDATE grant, so no FOR UPDATE): serialise per source with an advisory lock.
    session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(f"coach-earning:{source_id}", 0))))
    lines = list(session.scalars(
        select(CoachEarning).where(CoachEarning.source_type == source_type, CoachEarning.source_id == source_id)
        .order_by(CoachEarning.created_at, CoachEarning.id)
    ))  # fmt: skip
    reversed_ids = {line.reverses_coach_earning_id for line in lines if line.kind == "reversal"}
    live = [line for line in lines if line.kind == "lesson" and line.id not in reversed_ids]
    target = _target(session, source_type, source_id)
    for line in live:
        if target is None or (line.staff_payee_id, line.gross_minor) != (
            target["staff_payee_id"],
            target["gross_minor"],
        ):
            _reverse(session, line)
        else:
            return  # already recognised at this value
    if target is not None and target["gross_minor"] > 0:
        session.add(CoachEarning(kind="lesson", source_type=source_type, source_id=source_id, **target))
        session.flush()


def _reverse(session: Session, line: CoachEarning) -> None:
    session.add(CoachEarning(
        kind="reversal", location_id=line.location_id, staff_payee_id=line.staff_payee_id,
        earned_on=platform.service.location_today(session, line.location_id), source_type=line.source_type,
        source_id=line.source_id, reservation_type_id=line.reservation_type_id,
        description=f"Reversed: {line.description}"[:200], gross_minor=-line.gross_minor,
        facility_share_minor=-line.facility_share_minor, coach_share_minor=-line.coach_share_minor,
        coach_share_pct=line.coach_share_pct, court_fee_minor=-line.court_fee_minor, reverses_coach_earning_id=line.id,
    ))  # fmt: skip
    session.flush()


def reconcile_package(session: Session, client_package_id: UUID) -> None:
    """A package's charge was reversed, voided or adjusted (a refund starts with a reversal): revalue every lesson
    it paid for."""
    for source_type, source_id in packages.service.consumed_sources(session, client_package_id):
        reconcile_source(session, source_type, source_id)


# --- reads (own reach: a coach sees only their own) --------------------------------------------------------------


def _own_payees(session: Session, principal: Principal):
    return select(StaffPayee.id).where(StaffPayee.staff_user_id == principal.staff_user_id)


def list_earnings(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, COACH_READ)
    stmt = scope_query(select(CoachEarning), principal, CoachEarning.location_id)
    if _is_own(principal, COACH_READ):
        stmt = stmt.where(CoachEarning.staff_payee_id.in_(_own_payees(session, principal)))
    page = paginate(
        session, stmt, query, id_column=CoachEarning.id, sort_fields={"earned_on": CoachEarning.earned_on},
        default_sort="-earned_on",
        filter_fields={"staff_payee_id": CoachEarning.staff_payee_id, "location_id": CoachEarning.location_id,
                       "earned_on": CoachEarning.earned_on, "kind": CoachEarning.kind},
    )  # fmt: skip
    paid = dict(session.execute(
        select(CoachPayoutLine.coach_earning_id, CoachPayoutLine.coach_payout_id)
        .where(CoachPayoutLine.coach_earning_id.in_([e.id for e in page["data"]]))
    ).all())  # fmt: skip
    page["data"] = [_earning_view(principal, e) | {"coach_payout_id": paid.get(e.id)} for e in page["data"]]
    return page


def _earning_view(principal: Principal, e: CoachEarning) -> dict:
    view = {c.key: getattr(e, c.key) for c in CoachEarning.__table__.columns}
    if not principal.has(PAY_READ):  # the percent and court fee would reveal the coach's own share rule
        view |= {"coach_share_pct": None, "court_fee_minor": None}
    return view


def _payout(session: Session, principal: Principal, payout_id: UUID, key: str, *, lock: bool = False) -> CoachPayout:
    payout = _scoped(session, principal, CoachPayout, payout_id)
    authorize(principal, key, location_id=payout.location_id)
    if _is_own(principal, key):
        payee = session.get_one(StaffPayee, payout.staff_payee_id)
        if payee.staff_user_id != principal.staff_user_id:
            raise NotFound()
    if lock:  # a state change: hold the row and read its state fresh, so callers check the state after the lock
        payout = session.scalar(select(CoachPayout).where(CoachPayout.id == payout.id).with_for_update()
                                .execution_options(populate_existing=True))  # fmt: skip
    return payout


def payout_view(session: Session, payout: CoachPayout) -> dict:
    payee = session.get_one(StaffPayee, payout.staff_payee_id)
    return {c.key: getattr(payout, c.key) for c in CoachPayout.__table__.columns} | {
        "coach_name": payee.display_name, "tax_form_on_file_on": payee.tax_form_on_file_on,
        "notice": NO_MONEY_MOVED,
    }  # fmt: skip


def list_payouts(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, COACH_READ)
    stmt = scope_query(select(CoachPayout), principal, CoachPayout.location_id)
    if _is_own(principal, COACH_READ):
        stmt = stmt.where(CoachPayout.staff_payee_id.in_(_own_payees(session, principal)))
    page = paginate(
        session, stmt, query, id_column=CoachPayout.id, sort_fields={"period_ends_on": CoachPayout.period_ends_on},
        default_sort="-period_ends_on",
        filter_fields={"staff_payee_id": CoachPayout.staff_payee_id, "location_id": CoachPayout.location_id,
                       "status": CoachPayout.status},
    )  # fmt: skip
    page["data"] = [payout_view(session, p) for p in page["data"]]
    return page


def get_payout(session: Session, principal: Principal, payout_id: UUID) -> dict:
    return payout_view(session, _payout(session, principal, payout_id, COACH_READ))


def _lines(session: Session, payout_id: UUID) -> list[CoachEarning]:
    return list(session.scalars(
        select(CoachEarning).join(CoachPayoutLine, CoachPayoutLine.coach_earning_id == CoachEarning.id)
        .where(CoachPayoutLine.coach_payout_id == payout_id).order_by(CoachEarning.earned_on, CoachEarning.id)
    ))  # fmt: skip


def list_payout_lines(session: Session, principal: Principal, payout_id: UUID) -> list[dict]:
    payout = _payout(session, principal, payout_id, COACH_READ)
    return [_earning_view(principal, e) | {"coach_payout_id": payout.id} for e in _lines(session, payout.id)]


# --- payout statements -------------------------------------------------------------------------------------------


def _total(payout: CoachPayout, lines: list[CoachEarning]) -> None:
    payout.line_count = len(lines)
    payout.gross_minor = sum(e.gross_minor for e in lines)
    payout.facility_share_minor = sum(e.facility_share_minor for e in lines)
    payout.coach_share_minor = sum(e.coach_share_minor for e in lines)
    payout.adjustment_minor = sum(e.coach_share_minor for e in lines if e.kind == "adjustment")


def create_payouts(session: Session, principal: Principal, data: dict) -> dict:
    """Gather every unpaid earning line up to the period's end into one draft statement per independent coach (one
    coach, or all of them at the location). Lines from before the period that were never paid are included, so
    nothing is lost; a coach with nothing unpaid gets no statement."""
    location_id = data["location_id"]
    try:
        platform.service.get_location(session, principal, location_id)
    except NotFound:
        raise ValidationFailed("Unknown location.", pointer="/location_id") from None
    authorize(principal, PAYOUT_CREATE, location_id=location_id)
    if data["period_ends_on"] < data["period_starts_on"]:
        raise ValidationFailed("The period ends before it starts.", pointer="/period_ends_on")
    payees = select(StaffPayee).where(StaffPayee.location_id == location_id, StaffPayee.kind == "trainer")
    if data.get("staff_payee_id"):
        payees = payees.where(StaffPayee.id == data["staff_payee_id"])
    gathered = select(CoachPayoutLine.coach_earning_id)
    made = []
    for payee in session.scalars(payees.order_by(StaffPayee.display_name, StaffPayee.id)):
        lines = list(session.scalars(
            select(CoachEarning).where(
                CoachEarning.staff_payee_id == payee.id, CoachEarning.location_id == location_id,
                CoachEarning.earned_on <= data["period_ends_on"], CoachEarning.id.not_in(gathered),
            ).order_by(CoachEarning.earned_on, CoachEarning.id)
        ))  # fmt: skip
        if not lines:
            continue
        payout = CoachPayout(
            location_id=location_id, staff_payee_id=payee.id, period_starts_on=data["period_starts_on"],
            period_ends_on=data["period_ends_on"], created_by_staff_user_id=principal.staff_user_id,
        )  # fmt: skip
        _total(payout, lines)
        session.add(payout)
        session.flush()
        session.add_all(CoachPayoutLine(coach_payout_id=payout.id, coach_earning_id=e.id) for e in lines)
        session.flush()
        audit.record(session, PAYOUT_CREATE, payout, location_id=location_id, changes={
            "status": [None, "draft"], "coach_share_minor": [None, payout.coach_share_minor],
            "gross_minor": [None, payout.gross_minor]})  # fmt: skip
        made.append(payout)
    if data.get("staff_payee_id") and not made:
        raise ValidationFailed("That coach has no unpaid earnings up to this date.", pointer="/staff_payee_id")
    return {"data": [payout_view(session, p) for p in made]}


def _draft(session: Session, principal: Principal, payout_id: UUID, key: str) -> CoachPayout:
    payout = _payout(session, principal, payout_id, key, lock=True)
    if payout.status != "draft":
        raise Conflict("Only a draft statement changes.", code="invalid-state-transition")
    return payout


def delete_payout(session: Session, principal: Principal, payout_id: UUID) -> None:
    """Discard a draft: its lines go back to unpaid. Adjustment lines stay in the ledger, unpaid."""
    payout = _draft(session, principal, payout_id, PAYOUT_CREATE)
    audit.record(session, PAYOUT_CREATE, payout, location_id=payout.location_id, changes={"deleted": True})
    session.delete(payout)
    session.flush()


def add_adjustment(session: Session, principal: Principal, payout_id: UUID, data: dict) -> dict:
    """A manual line on a draft (a correction, a bonus, a deduction): the coach's share moves by the amount and the
    facility's by its opposite, so the gross is unchanged. Needs a reason and its own permission."""
    payout = _draft(session, principal, payout_id, PAYOUT_ADJUST)
    payee = session.get_one(StaffPayee, payout.staff_payee_id)
    _not_own_payee(session, principal, payee)
    if not data["amount_minor"]:
        raise ValidationFailed("An adjustment is not zero.", pointer="/amount_minor")
    line = CoachEarning(
        kind="adjustment", location_id=payout.location_id, staff_payee_id=payout.staff_payee_id,
        earned_on=platform.service.location_today(session, payout.location_id), description="Adjustment",
        reason=data["reason"], gross_minor=0, facility_share_minor=-data["amount_minor"],
        coach_share_minor=data["amount_minor"], created_by_staff_user_id=principal.staff_user_id,
    )  # fmt: skip
    session.add(line)
    session.flush()
    session.add(CoachPayoutLine(coach_payout_id=payout.id, coach_earning_id=line.id))
    session.flush()
    _total(payout, _lines(session, payout.id))
    audit.record(session, PAYOUT_ADJUST, payout, location_id=payout.location_id,
                 changes=audit.diff(payout) | {"amount_minor": [None, data["amount_minor"]]})  # fmt: skip
    session.flush()
    return payout_view(session, payout)


def approve_payout(session: Session, principal: Principal, payout_id: UUID) -> dict:
    payout = _draft(session, principal, payout_id, PAYOUT_APPROVE)
    payout.status, payout.approved_at, payout.approved_by_staff_user_id = (
        "approved",
        clock.now(),
        principal.staff_user_id,
    )
    audit.record(session, PAYOUT_APPROVE, payout, location_id=payout.location_id, changes=audit.diff(payout))
    session.flush()
    return payout_view(session, payout)


def mark_paid(session: Session, principal: Principal, payout_id: UUID, data: dict) -> dict:
    """Record how and when the facility paid an approved statement. Nothing is transferred by the software. A paid
    statement is final."""
    payout = _payout(session, principal, payout_id, PAYOUT_PAY, lock=True)
    if payout.status != "approved":
        raise Conflict("Only an approved statement is marked paid.", code="invalid-state-transition")
    payout.status, payout.paid_at, payout.paid_by_staff_user_id = "paid", clock.now(), principal.staff_user_id
    payout.paid_on, payout.payment_method = data["paid_on"], data["payment_method"]
    payout.payment_reference = data.get("payment_reference")
    audit.record(session, PAYOUT_PAY, payout, location_id=payout.location_id, changes=audit.diff(payout))
    session.flush()
    return payout_view(session, payout)


# --- documents ---------------------------------------------------------------------------------------------------


def _money(minor: int) -> str:
    return f"{Decimal(minor) / 100:.2f}"


def export_payout(session: Session, principal: Principal, payout_id: UUID, fmt: str) -> tuple[str, str, bytes]:
    """The statement as CSV or PDF: (filename, content type, bytes)."""
    payout = _payout(session, principal, payout_id, COACH_READ)
    view, lines = payout_view(session, payout), _lines(session, payout.id)
    name = f"coach-statement-{payout.period_ends_on.isoformat()}-{payout.id.hex[:8]}"
    audit.record(session, COACH_READ, payout, location_id=payout.location_id, changes={"exported": True})
    header = ("Date", "Kind", "Description", "Gross", "Facility share", "Coach share")
    rows = [(e.earned_on.isoformat(), e.kind, e.description, _money(e.gross_minor), _money(e.facility_share_minor),
             _money(e.coach_share_minor)) for e in lines]  # fmt: skip
    totals = ("Total", "", "", _money(payout.gross_minor), _money(payout.facility_share_minor),
              _money(payout.coach_share_minor))  # fmt: skip
    if fmt == "csv":
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(header)
        for row in (*rows, totals):
            writer.writerow([_csv_safe(str(cell)) for cell in row])
        return f"{name}.csv", "text/csv", out.getvalue().encode()
    tenant = platform.service.get_tenant(session)
    doc = pdf.Document("Coach payout statement", organization=tenant.name, subtitle=view["coach_name"],
                       footer=NO_MONEY_MOVED)  # fmt: skip
    doc.fields([("Period", f"{payout.period_starts_on.isoformat()} to {payout.period_ends_on.isoformat()}"),
                ("Status", payout.status), ("Paid on", payout.paid_on.isoformat() if payout.paid_on else "-"),
                ("Method", payout.payment_method or "-"), ("Reference", payout.payment_reference or "-")])  # fmt: skip
    widths = (24, 22, 0, 24, 28, 26)
    doc.table([pdf.Column(t, w, "R" if i >= 3 else "L") for i, (t, w) in enumerate(zip(header, widths, strict=True))],
              [*rows, totals])  # fmt: skip
    doc.text(NO_MONEY_MOVED, size=8)
    return f"{name}.pdf", "application/pdf", doc.output()
