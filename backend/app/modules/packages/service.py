"""packages service: plans, the sale, the session-credit ledger, sharing, expiry and renewal (data-model-people
section 4).

The credit ledger is append-only and is the truth; the four counters on `client_package` cache it and change in
the same transaction, under the package's row lock. That lock is what makes credits safe under concurrency: two
bookings racing for the last credit are serialised, the second sees a zero balance and gets 409
`package-exhausted` (the table CHECK is the last line of defence). Every movement for a booking or enrolment is
keyed on that source, so a retried call or a redelivered event changes nothing.

Staff commands take a principal and authorize it. `sell`, `reserve_credit`, `settle_credit`, `restore_credit` and
`spendable_packages` are the internal interface for booking contexts and POS (ADR 0009 section 9).
"""

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import String, cast, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import audit, clock, events
from app.core.api import CONSTRAINT_CODES
from app.core.auth import Principal, authorize
from app.core.dates import add_interval
from app.core.errors import Conflict, DomainError, NotFound, ValidationFailed
from app.core.jobs import tenant_actor
from app.core.pagination import ListQuery, paginate
from app.modules import billing, clients, documents, memberships, platform
from app.modules.packages.events import (
    CreditConsumed,
    CreditReservationFailed,
    CreditRestored,
    PackageExhausted,
    PackageExpired,
    PackageRenewed,
    PackageSold,
)
from app.modules.packages.models import (
    ClientPackage,
    CreditLedgerEntry,
    PackagePlan,
    PackageSeries,
    PackageSettings,
    PackageShare,
)

_READ, _SELL, _MANAGE = "packages.package.read", "packages.package.sell", "packages.plan.manage"
_COMP, _UPDATE, _SHARE = "packages.package.grant_complimentary", "packages.package.update", "packages.package.share"
_REMOVE, _ADJUST = "packages.package.remove", "packages.credit.adjust"
_ONE_DAY = timedelta(days=1)
_OUTCOMES = {  # booking outcome -> (settings switch that makes it consume, ledger reason)
    "attended": (None, "attendance"),
    "no_show": ("is_no_show_charged", "no_show"),
    "late_cancel": ("is_late_cancel_charged", "cancellation_late"),
    "early_cancel": (False, "cancellation_early"),
}

CONSTRAINT_CODES["ck_client_package_balance"] = "package-exhausted"
CONSTRAINT_CODES["uq_client_package_previous"] = "already-renewed"


# --- small helpers -----------------------------------------------------------------------------------------------


def _staff_id(principal: Principal) -> UUID | None:
    return principal.staff_user_id if principal.kind == "staff" else None


def _today(session: Session, location_id: UUID) -> date:
    return platform.service.location_today(session, location_id)


def _columns(row) -> dict:
    return {c.key: getattr(row, c.key) for c in row.__table__.columns}


def _get(session: Session, model, row_id: UUID, *, lock: bool = False):
    row = session.get(model, row_id, with_for_update=lock or None, populate_existing=lock)
    if row is None:
        raise NotFound()
    return row


def _apply(row, data: dict) -> None:
    for key, value in data.items():
        setattr(row, key, value)


def _load(session: Session, principal: Principal, package_id: UUID, key: str) -> ClientPackage:
    """The package the caller may act on with `key`, row-locked for commands. Outside reach or location: 404."""
    package = _get(session, ClientPackage, package_id, lock=key != _READ)
    if key == _READ:
        clients.service.load(session, principal, package.owner_client_id, key)
    else:
        authorize(principal, key, location_id=package.location_id)
    return package


def available(package: ClientPackage) -> int:
    """Credits that can still be booked: granted minus scheduled, completed and forfeited."""
    return (
        package.sessions_granted_count - package.sessions_reserved_count - package.sessions_consumed_count
        - package.sessions_forfeited_count
    )  # fmt: skip


def _discounted(amount: int, plan: PackagePlan) -> int:
    if plan.discount_pct is not None:  # half-up on hundredths of a percent
        return amount - (2 * amount * int(plan.discount_pct * 100) + 10000) // 20000
    return max(amount - (plan.discount_minor or 0), 0)


def _same_length(span: Range, start: date) -> date | None:
    """The end of a window as long as `span` that begins on `start`: whole calendar months stay whole months
    (a one-month package renewed on 10 February ends 10 March, not 31 days later); anything else is day-exact."""
    if span.upper is None:
        return None
    months = (span.upper.year - span.lower.year) * 12 + span.upper.month - span.lower.month
    if months > 0 and add_interval(span.lower, "month", months) == span.upper:
        return add_interval(start, "month", months)
    return start + (span.upper - span.lower)


def _renew_on(package: ClientPackage) -> date | None:
    if package.valid_during.upper is None or package.auto_renew_lead_count is None:
        return None
    last_day = package.valid_during.upper - _ONE_DAY
    return add_interval(last_day, package.auto_renew_lead_unit, -package.auto_renew_lead_count)


# --- settings ----------------------------------------------------------------------------------------------------


def settings_row(session: Session) -> PackageSettings:
    row = session.scalar(select(PackageSettings))
    if row is None:
        row = PackageSettings()
        session.add(row)
        session.flush()
    return row


def get_settings(session: Session, principal: Principal) -> PackageSettings:
    authorize(principal, _READ)
    return settings_row(session)


def update_settings(session: Session, principal: Principal, data: dict) -> PackageSettings:
    authorize(principal, _MANAGE)
    row = settings_row(session)
    _apply(row, data)
    audit.record(session, _MANAGE, row, changes=audit.diff(row))
    session.flush()
    return row


# --- package plans (PKG-01 to PKG-06, PKG-10) --------------------------------------------------------------------


def _check_plan(session: Session, plan: PackagePlan) -> None:
    """Rules the table checks cannot state."""
    if plan.renews_as_plan_id is not None and session.get(PackagePlan, plan.renews_as_plan_id) is None:
        raise ValidationFailed("Unknown package plan.", pointer="/renews_as_plan_id")
    if plan.auto_renew_lead_count is not None:
        if plan.validity_count is None and plan.kind != "recurring":
            raise ValidationFailed("Time-based renewal needs a package length.", pointer="/auto_renew_lead_count")
        if plan.validity_count is not None:
            day = date(2001, 1, 1)
            lead = add_interval(day, plan.auto_renew_lead_unit, plan.auto_renew_lead_count)
            if lead > add_interval(day, plan.validity_unit, plan.validity_count):
                raise ValidationFailed(
                    "The renewal lead cannot be longer than the package.", pointer="/auto_renew_lead_count"
                )
    if plan.kind != "recurring" and plan.default_invoice_mode == "per_period":
        raise ValidationFailed("Only a recurring plan invoices per period.", pointer="/default_invoice_mode")
    if plan.online_sale_mode == "paid_in_full" and plan.default_invoice_mode == "deferred":
        raise ValidationFailed(
            "A plan paid in full online cannot defer its invoice.", pointer="/default_invoice_mode"
        )  # fmt: skip


def list_plans(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, _READ)
    p = PackagePlan
    return paginate(
        session, select(p), query, id_column=p.id, sort_fields={"sort_order": p.sort_order, "name": p.name},
        default_sort="sort_order",
        filter_fields={
            "reservation_type_id": p.reservation_type_id, "is_active": p.is_active, "kind": p.kind,
            "session_mode": p.session_mode, "pricing_category": p.pricing_category, "online_sale_mode": p.online_sale_mode,
        },
        search=(p.name,),
    )  # fmt: skip


def get_plan(session: Session, principal: Principal, plan_id: UUID) -> PackagePlan:
    authorize(principal, _READ)
    return _get(session, PackagePlan, plan_id)


def create_plan(session: Session, principal: Principal, data: dict) -> PackagePlan:
    authorize(principal, _MANAGE)
    plan = PackagePlan(**data)
    _check_plan(session, plan)
    session.add(plan)
    session.flush()
    audit.record(session, _MANAGE, plan, changes={"name": [None, plan.name], "session_mode": [None, plan.session_mode]})
    return plan


def update_plan(session: Session, principal: Principal, plan_id: UUID, data: dict) -> PackagePlan:
    """Edits reach later sales and renewals only: sold packages keep their snapshot."""
    authorize(principal, _MANAGE)
    plan = _get(session, PackagePlan, plan_id, lock=True)
    _apply(plan, data)
    _check_plan(session, plan)
    plan.version += 1
    audit.record(session, _MANAGE, plan, changes=audit.diff(plan))
    session.flush()
    return plan


# --- the credit ledger (PKG-12, PKG-14) --------------------------------------------------------------------------


def _refresh(session: Session, package: ClientPackage) -> None:
    """Derive status and the renewal flag from the balance after any movement."""
    ref = {"client_package_id": package.id, "client_id": package.owner_client_id}
    left = available(package)
    if not package.is_unlimited and package.status in ("active", "exhausted"):
        status = "exhausted" if left <= 0 else "active"
        if status != package.status:
            package.status = status
            if status == "exhausted":
                events.publish(session, PackageExhausted(**ref), package.id)
    threshold = package.renewal_threshold_count
    if threshold is not None and not package.is_unlimited:
        if left > threshold:
            package.renewal_flagged_at = None
        elif package.renewal_flagged_at is None and package.status in ("active", "exhausted"):
            package.renewal_flagged_at = clock.now()
            used = package.sessions_reserved_count + package.sessions_consumed_count  # never on the grant itself
            if (
                used
                and package.is_auto_renew
                and package.is_auto_renew_on_threshold
                and _successor(session, package.id) is None
            ):
                _renew(session, package, _today(session, package.location_id), early=True)


def _entry(
    session: Session, package: ClientPackage, *, client_id: UUID, entry_type: str, reason: str, key: str,
    granted: int = 0, reserved: int = 0, consumed: int = 0, forfeited: int = 0,
    source: tuple[str, UUID] | None = None, note: str | None = None,
) -> CreditLedgerEntry:  # fmt: skip
    """Append one ledger entry and move the cached counters with it. The caller holds the package row lock."""
    actor = session.info["actor"]
    row = CreditLedgerEntry(
        client_package_id=package.id, client_id=client_id, entry_type=entry_type, reason=reason,
        granted_delta=granted, reserved_delta=reserved, consumed_delta=consumed, forfeited_delta=forfeited,
        source_type=source and source[0], source_id=source and source[1], idempotency_key=key,
        actor_type=actor.actor_type if actor.actor_type in ("staff", "client") else "system",
        actor_id=actor.actor_id, note=note, occurred_at=clock.now(),
    )  # fmt: skip
    session.add(row)
    package.sessions_granted_count += granted
    package.sessions_reserved_count += reserved
    package.sessions_consumed_count += consumed
    package.sessions_forfeited_count += forfeited
    _refresh(session, package)
    session.flush()
    return row


def _source_state(session: Session, source: tuple[str, UUID], package_id: UUID | None = None) -> dict:
    """Where a booking or enrolment stands in the ledger: the package holding or having consumed its credit,
    and how many entries it has (the next entry's key)."""
    e = CreditLedgerEntry
    stmt = select(
        e.client_package_id, func.max(cast(e.client_id, String)), func.sum(e.reserved_delta),
        func.sum(e.consumed_delta), func.count(),
    ).where(e.source_type == source[0], e.source_id == source[1]).group_by(e.client_package_id)  # fmt: skip
    state = {"package_id": None, "client_id": None, "held": 0, "consumed": 0, "count": 0}
    for found_id, client_id, held, consumed, count in session.execute(stmt):
        state["count"] += count
        if held or consumed or found_id == package_id:
            state |= {
                "package_id": found_id,
                "client_id": UUID(client_id),
                "held": int(held),
                "consumed": int(consumed),
            }
    return state


def _check_spendable(
    session: Session, package: ClientPackage, client_id: UUID, on: date, reservation_type_id: UUID | None
) -> None:
    """Eligibility to spend (data-model 4.4): usable status, matching reservation type, session date inside the
    validity window unless booking after expiry is allowed, spender is the owner or an active sharer, and a
    package bundled with a membership only while that membership is active."""
    if package.status == "removed" or (package.status == "expired" and not package.allows_booking_after_expiry):
        raise Conflict("This package can no longer be used.", code="package-not-usable")
    if reservation_type_id is not None and reservation_type_id != package.reservation_type_id:
        raise Conflict("This package does not cover that kind of session.", code="package-wrong-type")
    span = package.valid_during
    if on < span.lower or (span.upper is not None and on >= span.upper and not package.allows_booking_after_expiry):
        raise Conflict("The session date is outside the package's dates.", code="package-out-of-range")
    if client_id != package.owner_client_id:
        shared = select(PackageShare.id).where(
            PackageShare.client_package_id == package.id, PackageShare.client_id == client_id,
            PackageShare.revoked_at.is_(None),
        )  # fmt: skip
        if session.scalar(shared.limit(1)) is None:
            raise Conflict("This package is not shared with that client.", code="package-not-shared")
    if package.source_contract_id is not None:
        if memberships.service.status_of(session, package.source_contract_id) != "active":
            raise Conflict("The membership this package came with is not active.", code="membership-not-active")


def reserve_credit(
    session: Session, *, client_package_id: UUID, client_id: UUID, source_type: str, source_id: UUID,
    session_on: date | None = None, reservation_type_id: UUID | None = None,
) -> CreditLedgerEntry | None:  # fmt: skip
    """Hold one credit for a booking or enrolment (PKG-12). Internal. Idempotent per source: a repeat returns
    None and changes nothing. Raises 409 package-exhausted, package-not-usable, package-wrong-type,
    package-out-of-range, package-not-shared, membership-not-active or credit-already-reserved (the source
    already draws on another package)."""
    package = _get(session, ClientPackage, client_package_id, lock=True)
    source = (source_type, source_id)
    state = _source_state(session, source, package.id)
    if state["held"] or state["consumed"]:
        if state["package_id"] == package.id:
            return None
        raise Conflict("This booking already uses another package.", code="credit-already-reserved")
    _check_spendable(
        session, package, client_id, session_on or _today(session, package.location_id), reservation_type_id
    )
    if not package.is_unlimited and available(package) < 1:
        raise Conflict("No sessions are left on this package.", code="package-exhausted")
    key = f"{source_type}:{source_id}:reserve:{state['count'] + 1}"
    return _entry(
        session,
        package,
        client_id=client_id,
        entry_type="reserve",
        reason="booking",
        key=key,
        reserved=1,
        source=source,
    )


def settle_credit(session: Session, *, source_type: str, source_id: UUID, outcome: str) -> CreditLedgerEntry | None:
    """Close the credit a booking or enrolment holds. Internal. `outcome` is attended (consume), early_cancel
    (return the credit), or late_cancel / no_show (consume or return per package settings). Idempotent: with
    nothing held it returns None."""
    charged, reason = _OUTCOMES[outcome]
    source = (source_type, source_id)
    package_id = _source_state(session, source)["package_id"]
    if package_id is None:
        return None
    package = _get(session, ClientPackage, package_id, lock=True)
    state = _source_state(session, source, package.id)
    if not state["held"]:
        return None
    consume = charged is None or (charged is not False and getattr(settings_row(session), charged))
    verb = "consume" if consume else "release"
    row = _entry(
        session, package, client_id=state["client_id"], entry_type=verb, reason=reason, reserved=-1,
        consumed=1 if consume else 0, source=source, key=f"{source_type}:{source_id}:{verb}:{state['count'] + 1}",
    )  # fmt: skip
    if consume:
        events.publish(session, CreditConsumed(
            client_package_id=package.id, client_id=state["client_id"], source_type=source_type, source_id=source_id,
        ), package.id)  # fmt: skip
    return row


def restore_credit(session: Session, *, source_type: str, source_id: UUID) -> CreditLedgerEntry | None:
    """Give back a consumed credit (an attendance mark corrected). Internal; idempotent."""
    source = (source_type, source_id)
    package_id = _source_state(session, source)["package_id"]
    if package_id is None:
        return None
    package = _get(session, ClientPackage, package_id, lock=True)
    state = _source_state(session, source, package.id)
    if not state["consumed"]:
        return None
    row = _entry(
        session, package, client_id=state["client_id"], entry_type="restore", reason="attendance", consumed=-1,
        source=source, key=f"{source_type}:{source_id}:restore:{state['count'] + 1}",
    )  # fmt: skip
    events.publish(session, CreditRestored(
        client_package_id=package.id, client_id=state["client_id"], source_type=source_type, source_id=source_id,
    ), package.id)  # fmt: skip
    return row


def _usable_by(client_id: UUID):
    shared = select(PackageShare.client_package_id).where(
        PackageShare.client_id == client_id, PackageShare.revoked_at.is_(None)
    )
    return or_(ClientPackage.owner_client_id == client_id, ClientPackage.id.in_(shared))


def package_for(session: Session, *, source_type: str, source_id: UUID) -> UUID | None:
    """The package a booking or enrolment last drew on, held or not. Internal: a corrected attendance mark
    re-holds its credit on the same package."""
    e = CreditLedgerEntry
    return session.scalar(
        select(e.client_package_id)
        .where(e.source_type == source_type, e.source_id == source_id)
        .order_by(e.id.desc())
        .limit(1)
    )


def spendable_packages(
    session: Session, client_id: UUID, reservation_type_id: UUID | None = None, on: date | None = None
) -> list[ClientPackage]:
    """The packages (owned or shared) that can pay for a session of this type on this date, soonest to expire
    first. Internal: the booking flow's "which package pays" picker."""
    p = ClientPackage
    stmt = select(p).where(_usable_by(client_id), p.status.in_(("active", "expired")))
    if reservation_type_id is not None:
        stmt = stmt.where(p.reservation_type_id == reservation_type_id)
    found = []
    for package in session.scalars(stmt.order_by(func.upper(p.valid_during).asc().nulls_last(), p.id)):
        try:
            _check_spendable(
                session, package, client_id, on or _today(session, package.location_id), reservation_type_id
            )
        except Conflict:
            continue
        if package.is_unlimited or available(package) > 0:
            found.append(package)
    return found


def booking_created(session: Session, payload: dict) -> None:
    """`scheduling.booking.created` with a `client_package_id`: hold a credit. A booking that cannot be paid by
    the package is reported back as `packages.credit.reservation_failed` (an event cannot refuse a booking)."""
    if not payload.get("client_package_id"):
        return
    ids = {k: UUID(payload[k]) for k in ("client_package_id", "client_id", "booking_id")}
    try:
        reserve_credit(
            session, client_package_id=ids["client_package_id"], client_id=ids["client_id"], source_type="booking",
            source_id=ids["booking_id"], session_on=payload.get("starts_on") and date.fromisoformat(payload["starts_on"]),
            reservation_type_id=payload.get("reservation_type_id") and UUID(payload["reservation_type_id"]),
        )  # fmt: skip
    except DomainError as exc:
        events.publish(session, CreditReservationFailed(
            client_package_id=ids["client_package_id"], client_id=ids["client_id"], source_type="booking",
            source_id=ids["booking_id"], code=exc.code,
        ), ids["client_package_id"])  # fmt: skip


# --- the sale (PKG-02, PKG-03, PKG-07, PKG-09, PKG-10) -----------------------------------------------------------


def _terms(plan: PackagePlan, quantity: int | None, start_on: date, multiplier: int = 1) -> dict:
    """Snapshot of a plan for one sold package: credits, price after discount, validity window."""
    if plan.session_mode == "range":
        if quantity is None or not plan.min_session_count <= quantity <= plan.max_session_count:
            raise ValidationFailed(
                f"Choose between {plan.min_session_count} and {plan.max_session_count} sessions.", pointer="/quantity"
            )
    granted = {"single": 1, "fixed": plan.session_count, "range": quantity, "unlimited": 0}[plan.session_mode]
    granted = (granted or 0) * multiplier
    price = 0
    if plan.pricing_category == "paid":
        price = _discounted(plan.fee_minor * (max(granted, 1) if plan.fee_basis == "per_session" else 1), plan)
    start = plan.fixed_start_on if plan.start_rule == "fixed_date" else start_on
    length = (
        (plan.recurrence_unit, plan.recurrence_interval_count)
        if plan.kind == "recurring"
        else (plan.validity_unit, plan.validity_count)
    )
    return {
        "package_plan_id": plan.id, "reservation_type_id": plan.reservation_type_id, "name": plan.name,
        "invoice_description": plan.invoice_description, "is_unlimited": plan.session_mode == "unlimited",
        "valid_during": Range(start, add_interval(start, *length) if length[0] else None),
        "allows_booking_after_expiry": plan.allows_booking_after_expiry, "price_minor": price,
        "fee_basis": plan.fee_basis, "unit_price_minor": (2 * price + granted) // (2 * granted) if granted else None,
        "is_complimentary": plan.is_complimentary, "revenue_category_id": plan.revenue_category_id,
        "is_autopay": plan.is_autopay_default, "share_mode": plan.share_mode,
        "is_auto_renew": plan.auto_renew_lead_count is not None or plan.is_auto_renew_on_threshold,
        "auto_renew_lead_count": plan.auto_renew_lead_count, "auto_renew_lead_unit": plan.auto_renew_lead_unit,
        "renewal_target": plan.renewal_target, "renews_as_plan_id": plan.renews_as_plan_id,
        "renewal_threshold_count": plan.renewal_threshold_count,
        "is_auto_renew_on_threshold": plan.is_auto_renew_on_threshold,
    }, granted  # fmt: skip


def _issue(
    session: Session, fields: dict, granted: int, *, reason: str = "purchase", charge_quantity: int = 1, share_with=()
):
    """Create the package row, its grant entry, shares and (when priced) its charge and invoice."""
    package = ClientPackage(**fields)
    package.renew_on = _renew_on(package)
    session.add(package)
    session.flush()
    if granted:
        _entry(session, package, client_id=package.owner_client_id, entry_type="grant", reason=reason,
               key=f"package:{package.id}:grant", granted=granted)  # fmt: skip
    for client_id, origin in share_with:
        if client_id != package.owner_client_id:
            session.add(PackageShare(client_package_id=package.id, client_id=client_id, origin=origin))
    invoice = None
    if package.price_minor and package.invoice_mode != "none" and charge_quantity:
        charge = billing.service.post_charge(
            session, client_id=package.owner_client_id, location_id=package.location_id, description=package.name,
            unit_price_minor=package.price_minor, quantity=charge_quantity, source_context="packages",
            source_type="client_package", source_id=package.id, revenue_category_id=package.revenue_category_id,
            additional_description=package.invoice_description,
            service_starts_on=package.valid_during.lower,
            service_ends_on=package.valid_during.upper and package.valid_during.upper - _ONE_DAY,
        )  # fmt: skip
        package.charge_id = charge.id
        if package.invoice_mode == "single" and charge.total_minor > 0:
            invoice = billing.service.create_invoice_for_charges(
                session, [charge.id], origin="system", is_autopay=package.is_autopay
            )
    session.flush()
    events.publish(session, PackageSold(client_package_id=package.id, client_id=package.owner_client_id), package.id)
    return package, invoice


def _related_ids(session: Session, client_id: UUID) -> list[UUID]:
    """The owner's active relatives: who a plan with share_mode all_related is shared with at sale."""
    return [
        rel.to_client_id if rel.from_client_id == client_id else rel.from_client_id
        for rel in clients.households.relationships_of(session, client_id, live_only=True)
        if rel.status == "active"
    ]


def offer(session: Session, package_plan_id: UUID, location_id: UUID) -> dict:
    """What a POS cart line for this plan shows (POS-19): name, pre-tax price and revenue category. Internal.
    Only a priced, one-off plan sells at the till: a free, recurring or choose-your-quantity plan is sold or
    granted from the client's profile, where its options are."""
    plan = session.get(PackagePlan, package_plan_id)
    if plan is None or not plan.is_active:
        raise ValidationFailed("Unknown or retired package plan.", pointer="/package_plan_id")
    if plan.kind == "recurring" or plan.session_mode == "range":
        raise ValidationFailed(
            "Sell this plan from the client's profile.", pointer="/package_plan_id", code="not-sold-at-register"
        )
    fields, _ = _terms(plan, None, _today(session, location_id))
    if fields["price_minor"] == 0 or fields["is_complimentary"]:
        raise ValidationFailed(
            "A free package is granted from the client's profile.", pointer="/package_plan_id",
            code="not-sold-at-register",
        )  # fmt: skip
    return {
        "package_plan_id": plan.id, "name": fields["name"], "price_minor": fields["price_minor"],
        "revenue_category_id": fields["revenue_category_id"],
    }  # fmt: skip


def require_documents(
    session: Session, package_plan_id: UUID, client_id: UUID, location_id: UUID, *, online: bool = False
) -> UUID | None:
    """The accepted document that satisfies the plan's binding, or 409 document-required with the pending
    document's id. Internal. The refusal commits (the document it just issued must survive), so a caller that
    sells inside a larger transaction (the POS cart) calls this before it writes anything else."""
    source = None
    for need in documents.service.requirements_for(session, "package_plan", package_plan_id, client_id, online=online):
        if need["is_blocking"] and not need["is_satisfied"]:
            pending = documents.service.ensure_pending(session, need["binding_id"], client_id, location_id)
            raise Conflict(  # persist: the pending document just issued must survive the refusal
                "The client must accept the plan's document first.",
                code="document-required",
                persist=True,
                document_id=str(pending.id),
            )
        source = need["satisfied_by_document_id"] or source
    return source


def sell(
    session: Session, *, client_id: UUID, location_id: UUID, package_plan_id: UUID, quantity: int | None = None,
    start_on: date | None = None, channel: str = "staff", online: bool = False, sold_by_staff_user_id: UUID | None = None,
    invoice_mode: str | None = None, is_complimentary: bool = False, internal_remarks: str | None = None,
    source_contract_id: UUID | None = None, source_contract_addon_id: UUID | None = None, multiplier: int = 1,
    payment: dict | None = None, idempotency_key: str | None = None,
) -> dict:  # fmt: skip
    """Sell (or grant) a package from a plan. Internal: staff sale, portal purchase, POS, complimentary grants
    and membership add-ons all come through here. Returns {"package", "invoice", "payment", "series"}.

    A plan bound to a document refuses the sale until the client has accepted it (409 document-required with the
    pending document id). A recurring plan creates its series and the first period; later periods come from the
    daily job. A complimentary grant or a membership add-on is free: no charge, no invoice.
    """
    try:
        today = _today(session, location_id)
    except NotFound:
        raise ValidationFailed("Unknown location.", pointer="/location_id") from None
    client = clients.service.require_active(session, client_id)
    plan = session.get(PackagePlan, package_plan_id)
    if plan is None or not plan.is_active:
        raise ValidationFailed("Unknown or retired package plan.", pointer="/package_plan_id")
    bundled = source_contract_addon_id is not None
    if not bundled:
        if online and plan.online_sale_mode == "off":
            raise ValidationFailed("This plan is not sold online.", pointer="/package_plan_id")
        if (
            plan.is_members_only_online if online else plan.is_members_only_at_desk
        ) and not memberships.service.is_member(session, client.id):
            raise Conflict("This plan is for members only.", code="members-only")
        source = require_documents(session, plan.id, client.id, location_id, online=online)
    fields, granted = _terms(plan, quantity, start_on or today, multiplier)
    free = bundled or is_complimentary or fields["price_minor"] == 0
    fields |= {
        "owner_client_id": client.id, "location_id": location_id, "sales_channel": channel,
        "sold_by_staff_user_id": sold_by_staff_user_id, "internal_remarks": internal_remarks,
        "source_contract_id": source_contract_id, "source_contract_addon_id": source_contract_addon_id,
        "is_complimentary": fields["is_complimentary"] or is_complimentary,
    }  # fmt: skip
    series, charge_quantity = None, 1
    mode = invoice_mode or plan.default_invoice_mode
    if free:
        fields |= {"price_minor": 0, "unit_price_minor": 0 if granted else None, "invoice_mode": "none"}
    elif plan.kind == "recurring":
        series_mode = mode if mode in ("single", "per_period", "deferred") else "per_period"
        # single: the whole series is charged on the first period's invoice
        charge_quantity = plan.recurrence_occurrences_count if series_mode == "single" else 1
        fields["invoice_mode"] = "deferred" if series_mode == "deferred" else "single"
    else:
        fields["invoice_mode"] = mode if mode in ("single", "deferred") else "single"
    if plan.kind == "recurring":
        series = PackageSeries(
            owner_client_id=client.id, package_plan_id=plan.id, location_id=location_id,
            occurrences_total_count=plan.recurrence_occurrences_count, occurrences_generated_count=1,
            next_period_start_on=fields["valid_during"].upper, is_auto_renew=plan.is_series_auto_renew,
            invoice_mode="single" if free else series_mode,
        )  # fmt: skip
        session.add(series)
        session.flush()
        fields |= {"package_series_id": series.id, "series_sequence_number": 1, "is_auto_renew": False}
    share_with = (
        [(cid, "plan_preset") for cid in _related_ids(session, client.id)] if plan.share_mode == "all_related" else []
    )
    package, invoice = _issue(
        session, fields, granted, reason="addon" if bundled else "purchase", charge_quantity=charge_quantity,
        share_with=share_with,
    )  # fmt: skip
    if not bundled and source is not None:
        package.client_document_id = source
        documents.service.consume(session, [source], ("packages", "client_package", package.id))
    paid = None
    if payment:
        if invoice is None:
            raise ValidationFailed("Nothing is due now, so there is nothing to pay.", pointer="/payment")
        paid = billing.service.take_payment(
            session, client_id=client.id, location_id=location_id, invoice_id=invoice.id,
            idempotency_key=idempotency_key, origin="portal" if online else "staff", **payment,
        )  # fmt: skip
    audit.record(
        session, _COMP if is_complimentary else _SELL, package, location_id=location_id,
        changes={"plan": [None, plan.name], "sessions_granted_count": [None, granted], "price_minor": [None, package.price_minor]},
    )  # fmt: skip
    session.flush()
    return {"package": package, "invoice": invoice, "payment": paid, "series": series}


def _sale_view(session: Session, sold: dict) -> dict:
    return package_view(session, sold["package"]) | {
        "invoice_id": sold["invoice"] and sold["invoice"].id, "payment_id": sold["payment"] and sold["payment"].id,
        "payment_status": sold["payment"] and sold["payment"].status,
    }  # fmt: skip


def quote_package(session: Session, principal: Principal, data: dict) -> dict:
    """What a sale would create: credits, price (pre-tax), validity and the documents still to accept."""
    authorize(principal, _SELL, location_id=data["location_id"])
    plan = session.get(PackagePlan, data["package_plan_id"])
    if plan is None:
        raise ValidationFailed("Unknown package plan.", pointer="/package_plan_id")
    client = clients.service.require_active(session, data["client_id"])
    try:
        today = _today(session, data["location_id"])
    except NotFound:
        raise ValidationFailed("Unknown location.", pointer="/location_id") from None
    fields, granted = _terms(plan, data.get("quantity"), data.get("start_on") or today)
    span = fields["valid_during"]
    return {
        "name": fields["name"], "is_unlimited": fields["is_unlimited"], "sessions_granted_count": granted,
        "price_minor": fields["price_minor"], "unit_price_minor": fields["unit_price_minor"],
        "valid_from_on": span.lower, "valid_until_on": span.upper and span.upper - _ONE_DAY,
        "occurrences_count": plan.recurrence_occurrences_count,
        "is_member_required": plan.is_members_only_at_desk,
        "is_member": memberships.service.is_member(session, client.id),
        "requirements": documents.service.requirements_for(session, "package_plan", plan.id, client.id),
    }  # fmt: skip


def sell_package(session: Session, principal: Principal, data: dict, idempotency_key: str | None = None) -> dict:
    """Staff sale from the client profile or administration (PKG-07)."""
    authorize(principal, _SELL, location_id=data["location_id"])
    try:
        platform.service.get_location(session, principal, data["location_id"])
    except NotFound:
        raise ValidationFailed("Unknown location.", pointer="/location_id") from None
    sold_by = data.get("sold_by_staff_user_id")
    if sold_by and not platform.service.staff_user_exists(session, sold_by):
        raise ValidationFailed("Unknown staff user.", pointer="/sold_by_staff_user_id")
    sold = sell(
        session, **{**data, "sold_by_staff_user_id": sold_by or _staff_id(principal)}, idempotency_key=idempotency_key
    )
    return _sale_view(session, sold)


def grant_complimentary(session: Session, principal: Principal, data: dict) -> dict:
    """Give a package away (PKG-02): any plan, no charge, marked complimentary for reporting."""
    authorize(principal, _COMP, location_id=data["location_id"])
    try:
        platform.service.get_location(session, principal, data["location_id"])
    except NotFound:
        raise ValidationFailed("Unknown location.", pointer="/location_id") from None
    sold = sell(session, **data, is_complimentary=True, sold_by_staff_user_id=_staff_id(principal))
    return _sale_view(session, sold)


# --- reads (PKG-14) ----------------------------------------------------------------------------------------------


def package_view(session: Session, package: ClientPackage) -> dict:
    data = _columns(package)
    span = data.pop("valid_during")
    shares = session.scalar(
        select(func.count()).select_from(PackageShare).where(
            PackageShare.client_package_id == package.id, PackageShare.revoked_at.is_(None)
        )
    )  # fmt: skip
    return data | {
        "valid_from_on": span.lower, "valid_until_on": span.upper and span.upper - _ONE_DAY,
        "sessions_available_count": None if package.is_unlimited else available(package), "share_count": shares,
        "is_renewal_due": package.renewal_flagged_at is not None,
    }  # fmt: skip


def _page(session: Session, stmt, query: ListQuery) -> dict:
    p = ClientPackage
    page = paginate(
        session, stmt, query, id_column=p.id, sort_fields={"created_at": p.created_at, "name": p.name},
        default_sort="-created_at",
        filter_fields={
            "client_id": p.owner_client_id, "location_id": p.location_id, "status": p.status,
            "reservation_type_id": p.reservation_type_id, "package_plan_id": p.package_plan_id,
            "package_series_id": p.package_series_id, "source_contract_id": p.source_contract_id,
            "is_auto_renew": p.is_auto_renew, "is_complimentary": p.is_complimentary,
        },
        search=(p.name,),
    )  # fmt: skip
    return page | {"data": [package_view(session, row) for row in page["data"]]}


def list_packages(session: Session, principal: Principal, query: ListQuery) -> dict:
    """Sold packages across locations (a client-following key). `usable_by_client_id` lists what a client can
    spend: packages they own and packages shared with them. `expires_on_or_before` (a date) keeps packages whose
    last valid day is on or before it: the expiring-packages list."""
    stmt = select(ClientPackage)
    if (reach := clients.service.reach_filter(principal, _READ, ClientPackage.owner_client_id)) is not None:
        stmt = stmt.where(reach)
    filters = dict(query.filters)
    if spender := filters.pop("usable_by_client_id", None):
        try:
            stmt = stmt.where(_usable_by(UUID(spender)))
        except ValueError:
            raise ValidationFailed("Invalid client id.", pointer="/usable_by_client_id") from None
    if by := filters.pop("expires_on_or_before", None):
        try:
            last = date.fromisoformat(by)
        except ValueError:
            raise ValidationFailed("Invalid date.", pointer="/expires_on_or_before") from None
        # valid_during is half-open: the last valid day is upper - 1. Never-expiring packages are left out.
        stmt = stmt.where(func.upper(ClientPackage.valid_during) <= last + _ONE_DAY)
    return _page(session, stmt, ListQuery(query.limit, query.cursor, query.sort, query.include_total, query.q, filters))


def get_package(session: Session, principal: Principal, package_id: UUID) -> dict:
    return package_view(session, _load(session, principal, package_id, _READ))


def _ledger(session: Session, package_id: UUID, query: ListQuery) -> dict:
    e = CreditLedgerEntry
    return paginate(
        session, select(e).where(e.client_package_id == package_id), query, id_column=e.id,
        sort_fields={"occurred_at": e.occurred_at}, default_sort="-occurred_at",
        filter_fields={"entry_type": e.entry_type, "client_id": e.client_id, "source_id": e.source_id, "reason": e.reason},
    )  # fmt: skip


def list_ledger(session: Session, principal: Principal, package_id: UUID, query: ListQuery) -> dict:
    return _ledger(session, _load(session, principal, package_id, _READ).id, query)


# --- edit, adjust, share (PKG-04, PKG-05, PKG-06, PKG-14) --------------------------------------------------------


def update_package(session: Session, principal: Principal, package_id: UUID, data: dict) -> dict:
    """Extend or shorten the expiry, allow booking after it, and set how the package renews."""
    package = _load(session, principal, package_id, _UPDATE)
    if package.status == "removed":
        raise Conflict("A removed package cannot be edited.")
    data = dict(data)
    if "valid_until_on" in data:
        until = data.pop("valid_until_on")
        if until is not None and until < package.valid_during.lower:
            raise ValidationFailed("The package cannot end before it starts.", pointer="/valid_until_on")
        package.valid_during = Range(package.valid_during.lower, until and until + _ONE_DAY)
        today = _today(session, package.location_id)
        if package.status == "expired" and (until is None or until >= today):
            package.status = "active"  # an extended package is usable again; credits already forfeited stay so
    if "renews_as_plan_id" in data:
        if data["renews_as_plan_id"] and session.get(PackagePlan, data["renews_as_plan_id"]) is None:
            raise ValidationFailed("Unknown package plan.", pointer="/renews_as_plan_id")
        data["renewal_target"] = "plan" if data["renews_as_plan_id"] else "same_terms"
    was_renewing = package.is_auto_renew
    _apply(package, data)
    if (package.auto_renew_lead_count is None) != (package.auto_renew_lead_unit is None):
        raise ValidationFailed("Give the renewal lead as a count and a unit.", pointer="/auto_renew_lead_count")
    if was_renewing != package.is_auto_renew:
        package.auto_renew_disabled_by = None if package.is_auto_renew else "staff"
    package.renew_on = _renew_on(package)
    package.version += 1
    audit.record(session, _UPDATE, package, location_id=package.location_id, changes=audit.diff(package))
    _refresh(session, package)
    session.flush()
    return package_view(session, package)


def adjust_credits(session: Session, principal: Principal, package_id: UUID, data: dict) -> dict:
    """Add or take away credits by hand, with a note. Cannot take away credits already scheduled or used."""
    package = _load(session, principal, package_id, _ADJUST)
    delta = data["delta"]
    if package.is_unlimited or package.status == "removed":
        raise Conflict("This package has no credit balance to adjust.")
    if available(package) + delta < 0:
        raise Conflict("Sessions already scheduled or used cannot be taken away.", code="package-exhausted")
    count = session.scalar(
        select(func.count()).select_from(CreditLedgerEntry).where(CreditLedgerEntry.client_package_id == package.id)
    )
    _entry(session, package, client_id=package.owner_client_id, entry_type="adjust", reason="staff_adjustment",
           key=f"package:{package.id}:adjust:{count + 1}", granted=delta, note=data["note"])  # fmt: skip
    audit.record(session, _ADJUST, package, location_id=package.location_id, reason=data["note"],
                 changes={"sessions_granted_count": [package.sessions_granted_count - delta, package.sessions_granted_count]})  # fmt: skip
    return package_view(session, package)


def list_shares(session: Session, principal: Principal, package_id: UUID) -> list[PackageShare]:
    package = _load(session, principal, package_id, _READ)
    return list(
        session.scalars(
            select(PackageShare).where(PackageShare.client_package_id == package.id).order_by(PackageShare.id)
        )
    )


def add_share(session: Session, principal: Principal, package_id: UUID, client_id: UUID) -> PackageShare:
    """Authorise another client, related or not, to draw on this package's balance (PKG-06)."""
    package = _load(session, principal, package_id, _SHARE)
    if package.status == "removed":
        raise Conflict("A removed package cannot be shared.")
    if client_id == package.owner_client_id:
        raise ValidationFailed("The owner already uses this package.", pointer="/client_id")
    clients.service.require_active(session, client_id)
    share = session.scalar(select(PackageShare).where(
        PackageShare.client_package_id == package.id, PackageShare.client_id == client_id, PackageShare.revoked_at.is_(None)
    ))  # fmt: skip
    if share is None:
        share = PackageShare(
            client_package_id=package.id, client_id=client_id, added_by_staff_user_id=_staff_id(principal)
        )
        session.add(share)
        if package.share_mode == "none":
            package.share_mode = "explicit"
        audit.record(
            session, _SHARE, package, location_id=package.location_id, changes={"shared_with": [None, str(client_id)]}
        )
        session.flush()
    return share


def revoke_share(session: Session, principal: Principal, package_id: UUID, share_id: UUID) -> None:
    package = _load(session, principal, package_id, _SHARE)
    share = _get(session, PackageShare, share_id)
    if share.client_package_id != package.id:
        raise NotFound()
    if share.revoked_at is None:
        share.revoked_at = clock.now()
        audit.record(
            session,
            _SHARE,
            package,
            location_id=package.location_id,
            changes={"shared_with": [str(share.client_id), None]},
        )
    session.flush()


# --- renewal (PKG-05) --------------------------------------------------------------------------------------------


def _successor(session: Session, package_id: UUID) -> ClientPackage | None:
    return session.scalar(select(ClientPackage).where(ClientPackage.previous_package_id == package_id))


def _renew(session: Session, package: ClientPackage, today: date, *, early: bool = False) -> ClientPackage:
    """Create the successor package and charge it. At most one per package (`uq_client_package_previous`); the
    caller holds the package row lock. `same_terms` re-sells the package as it was sold; a plan target (and any
    package that came free with a membership) is read from the plan now, at the plan's price."""
    plan_id = package.renews_as_plan_id if package.renewal_target == "plan" else None
    if plan_id is None and package.source_contract_id is not None:
        plan_id = package.package_plan_id
    upper = package.valid_during.upper
    start = today if early or upper is None else max(upper, today)
    if plan_id is not None:
        plan = _get(session, PackagePlan, plan_id)
        quantity = package.sessions_granted_count if plan.session_mode == "range" else None
        fields, granted = _terms(plan, quantity, start)
        fields["invoice_mode"] = "none" if fields["price_minor"] == 0 else "single"
    else:
        granted = session.scalar(
            select(CreditLedgerEntry.granted_delta).where(
                CreditLedgerEntry.client_package_id == package.id, CreditLedgerEntry.entry_type == "grant"
            )
        ) or 0  # fmt: skip
        copy = (
            "package_plan_id", "reservation_type_id", "name", "invoice_description", "is_unlimited", "price_minor",
            "allows_booking_after_expiry", "fee_basis", "unit_price_minor", "is_complimentary", "revenue_category_id",
            "invoice_mode", "is_autopay", "share_mode", "is_auto_renew", "auto_renew_lead_count", "auto_renew_lead_unit",
            "renewal_target", "renews_as_plan_id", "renewal_threshold_count", "is_auto_renew_on_threshold",
        )  # fmt: skip
        fields = {key: getattr(package, key) for key in copy}
        fields["valid_during"] = Range(start, _same_length(package.valid_during, start))
    fields |= {
        "owner_client_id": package.owner_client_id, "location_id": package.location_id, "sales_channel": "renewal",
        "previous_package_id": package.id, "sold_by_staff_user_id": package.sold_by_staff_user_id,
    }  # fmt: skip
    shares = select(PackageShare.client_id).where(
        PackageShare.client_package_id == package.id, PackageShare.revoked_at.is_(None)
    )
    carried = [(client_id, "carried_from_previous") for client_id in session.scalars(shares)]
    successor, _ = _issue(session, fields, granted, reason="renewal", share_with=carried)
    audit.record(session, "packages.package.renew", package, location_id=package.location_id,
                 changes={"successor": [None, str(successor.id)]})  # fmt: skip
    events.publish(session, PackageRenewed(
        client_package_id=package.id, client_id=package.owner_client_id, successor_package_id=successor.id,
    ), package.id)  # fmt: skip
    session.flush()
    return successor


def renew_package(session: Session, principal: Principal, package_id: UUID) -> dict:
    """Renew now: the successor starts when this package ends (or today when it has no end or has ended)."""
    package = _load(session, principal, package_id, _SELL)
    if package.status == "removed" or package.package_series_id is not None:
        raise Conflict("This package cannot be renewed.")
    if _successor(session, package.id) is not None:
        raise Conflict("This package has already been renewed.", code="already-renewed")
    return package_view(session, _renew(session, package, _today(session, package.location_id)))


# --- remove (PKG-13) ---------------------------------------------------------------------------------------------


def _open_sources(session: Session, package_id: UUID) -> list[tuple[str, UUID, UUID]]:
    """(source_type, source_id, client_id) for every booking still holding a credit of this package."""
    e = CreditLedgerEntry
    stmt = (
        select(e.source_type, e.source_id, func.max(cast(e.client_id, String)))
        .where(e.client_package_id == package_id, e.source_id.is_not(None))
        .group_by(e.source_type, e.source_id).having(func.sum(e.reserved_delta) > 0)
    )  # fmt: skip
    return [(kind, source_id, UUID(client_id)) for kind, source_id, client_id in session.execute(stmt)]


def quote_removal(session: Session, principal: Principal, package_id: UUID) -> dict:
    package = _load(session, principal, package_id, _REMOVE)
    charge = billing.service.get_charge(session, package.charge_id) if package.charge_id else None
    billed = bool(charge and charge.status == "active")
    return {
        "sessions_consumed_count": package.sessions_consumed_count, "open_reservations_count": len(_open_sources(session, package.id)),
        "sessions_forfeited_on_removal_count": 0 if package.is_unlimited else available(package) + package.sessions_reserved_count,
        "charge_id": package.charge_id, "charge_total_minor": charge.total_minor if billed else 0,
        "paid_minor": charge.applied_minor if billed else 0,
        "can_reverse_billing": billed and package.sessions_consumed_count == 0,
    }  # fmt: skip


def _remove(session: Session, package: ClientPackage, mode: str, staff_id: UUID | None) -> None:
    package.is_auto_renew = False  # before the ledger moves: an emptied package must not renew itself
    for kind, source_id, client_id in _open_sources(session, package.id):
        count = _source_state(session, (kind, source_id))["count"]
        _entry(session, package, client_id=client_id, entry_type="release", reason="removal", reserved=-1,
               source=(kind, source_id), key=f"{kind}:{source_id}:release:{count + 1}")  # fmt: skip
    if not package.is_unlimited and available(package) > 0:
        _entry(session, package, client_id=package.owner_client_id, entry_type="forfeit", reason="removal",
               forfeited=available(package), key=f"package:{package.id}:removal")  # fmt: skip
    if mode == "billing_reversed" and package.charge_id:
        if billing.service.get_charge(session, package.charge_id).status == "active":
            billing.service.reverse(session, package.charge_id, reason="Package removed")
    package.status, package.removed_at, package.removal_mode = "removed", clock.now(), mode
    package.removed_by_staff_user_id, package.is_auto_renew = staff_id, False
    package.version += 1
    audit.record(
        session,
        _REMOVE,
        package,
        location_id=package.location_id,
        changes={"status": [None, "removed"], "removal_mode": [None, mode]},
    )
    session.flush()


def remove_package(session: Session, principal: Principal, package_id: UUID, data: dict) -> dict:
    """Remove a sold package: open reservations are released and what is left is forfeited. `billing_reversed`
    reverses its charge (money already paid becomes account credit; a refund is then a billing action) and is
    refused once sessions have been used; `billing_kept` leaves the billing as it is."""
    package = _load(session, principal, package_id, _REMOVE)
    if package.status == "removed":
        raise Conflict("This package was already removed.")
    if data["removal_mode"] == "billing_reversed" and package.sessions_consumed_count > 0:
        raise Conflict("Sessions were used: remove the package and keep its billing.", code="package-in-use")
    _remove(session, package, data["removal_mode"], _staff_id(principal))
    return package_view(session, package)


# --- series (PKG-03) ---------------------------------------------------------------------------------------------


def list_series(session: Session, principal: Principal, query: ListQuery) -> dict:
    s = PackageSeries
    stmt = select(s)
    if (reach := clients.service.reach_filter(principal, _READ, s.owner_client_id)) is not None:
        stmt = stmt.where(reach)
    return paginate(
        session, stmt, query, id_column=s.id, sort_fields={"created_at": s.created_at}, default_sort="-created_at",
        filter_fields={"client_id": s.owner_client_id, "status": s.status, "package_plan_id": s.package_plan_id, "location_id": s.location_id},
    )  # fmt: skip


def get_series(session: Session, principal: Principal, series_id: UUID) -> PackageSeries:
    series = _get(session, PackageSeries, series_id)
    clients.service.load(session, principal, series.owner_client_id, _READ)
    return series


def cancel_series(session: Session, principal: Principal, series_id: UUID) -> PackageSeries:
    """Stop generating further periods. Periods already sold stay as they are."""
    series = _get(session, PackageSeries, series_id, lock=True)
    authorize(principal, _REMOVE, location_id=series.location_id)
    if series.status != "active":
        raise Conflict("This series has already ended.")
    series.status, series.next_period_start_on, series.is_auto_renew = "cancelled", None, False
    audit.record(session, _REMOVE, series, location_id=series.location_id, changes={"status": ["active", "cancelled"]})
    session.flush()
    return series


def _next_period(session: Session, series: PackageSeries, today: date) -> str | None:
    """Materialise the series' next period when its start date has arrived (returns "generated"); close, or
    restart, a series whose last period has ended ("completed"). None when nothing is due."""
    p = ClientPackage
    last = session.scalar(
        select(p).where(p.package_series_id == series.id).order_by(p.series_sequence_number.desc()).limit(1)
    )
    if series.next_period_start_on is None or series.next_period_start_on > today:
        return None
    if series.occurrences_generated_count >= series.occurrences_total_count:
        series.status, series.next_period_start_on = "completed", None
        if series.is_auto_renew:  # a new series on the plan's current terms, starting where this one ended
            sell(session, client_id=series.owner_client_id, location_id=series.location_id,
                 package_plan_id=series.package_plan_id, start_on=last.valid_during.upper, channel="renewal",
                 invoice_mode=series.invoice_mode)  # fmt: skip
        session.flush()
        return "completed"
    skip = {
        "id",
        "tenant_id",
        "created_at",
        "updated_at",
        "version",
        "charge_id",
        "status",
        "renewal_flagged_at",
        "renew_on",
    }
    fields = {
        k: v
        for k, v in _columns(last).items()
        if k not in skip and not k.startswith(("sessions_", "removed", "removal"))
    }
    start = series.next_period_start_on
    fields |= {
        "valid_during": Range(start, _same_length(last.valid_during, start)),
        "series_sequence_number": last.series_sequence_number + 1, "sales_channel": "renewal",
    }  # fmt: skip
    granted = session.scalar(
        select(CreditLedgerEntry.granted_delta).where(
            CreditLedgerEntry.client_package_id == last.id, CreditLedgerEntry.entry_type == "grant"
        )
    ) or 0  # fmt: skip
    shares = select(PackageShare.client_id).where(
        PackageShare.client_package_id == last.id, PackageShare.revoked_at.is_(None)
    )
    carried = [(client_id, "carried_from_previous") for client_id in session.scalars(shares)]
    # single: the first period's invoice already charged the whole series
    package, _ = _issue(session, fields, granted, reason="renewal", share_with=carried,
                        charge_quantity=0 if series.invoice_mode == "single" else 1)  # fmt: skip
    series.occurrences_generated_count += 1
    series.next_period_start_on = package.valid_during.upper
    session.flush()
    return "generated"


# --- portal (PKG-09, PKG-14, MEM-18) -----------------------------------------------------------------------------


def _portal_client(session: Session, principal: Principal, client_id: UUID | None, capability: str = "book") -> UUID:
    if principal.kind != "client" or principal.identity_id is None:
        raise NotFound()
    if client_id is None:
        own = clients.service.client_ids_for_identity(session, principal.identity_id)
        if not own:
            raise NotFound()
        client_id = own[0]
    if clients.households.can_act_for(session, principal.identity_id, client_id, capability) is None:
        raise NotFound()
    return client_id


def portal_list_packages(session: Session, principal: Principal, client_id: UUID | None, query: ListQuery) -> dict:
    """Packages the acting client owns or may draw on."""
    subject = _portal_client(session, principal, client_id)
    filters = {k: v for k, v in query.filters.items() if k in ("status", "reservation_type_id")}
    query = ListQuery(query.limit, query.cursor, query.sort, query.include_total, query.q, filters)
    return _page(session, select(ClientPackage).where(_usable_by(subject), ClientPackage.status != "removed"), query)


def _portal_package(
    session: Session, principal: Principal, package_id: UUID, capability: str = "book"
) -> ClientPackage:
    package = _get(session, ClientPackage, package_id, lock=capability != "book")
    if principal.kind != "client" or principal.identity_id is None:
        raise NotFound()
    actable = set(clients.households.actable_client_ids(session, principal.identity_id))
    if capability == "book":  # reading: the owner or anyone the package is shared with
        users = {package.owner_client_id, *session.scalars(select(PackageShare.client_id).where(
            PackageShare.client_package_id == package.id, PackageShare.revoked_at.is_(None)))}  # fmt: skip
        if not actable & users:
            raise NotFound()
    else:
        _portal_client(session, principal, package.owner_client_id, capability)
    return package


def portal_list_ledger(session: Session, principal: Principal, package_id: UUID, query: ListQuery) -> dict:
    return _ledger(session, _portal_package(session, principal, package_id).id, query)


def portal_list_plans(session: Session, principal: Principal, client_id: UUID | None, query: ListQuery) -> dict:
    """Plans sold online, each marked with whether the acting client may buy it (member-only plans, PKG-10)."""
    subject = _portal_client(session, principal, client_id, "buy")
    p = PackagePlan
    page = paginate(
        session, select(p).where(p.is_active, p.online_sale_mode != "off"), query, id_column=p.id,
        sort_fields={"sort_order": p.sort_order, "name": p.name}, default_sort="sort_order",
        filter_fields={"reservation_type_id": p.reservation_type_id}, search=(p.name,),
    )  # fmt: skip
    member = memberships.service.is_member(session, subject)
    return page | {
        "data": [
            _columns(plan) | {"is_purchasable": member or not plan.is_members_only_online} for plan in page["data"]
        ]
    }


def public_list_plans(session: Session, query: ListQuery) -> dict:
    """Plans published for online sale (PKG-09, PKG-16): the anonymous price list."""
    p = PackagePlan
    page = paginate(
        session, select(p).where(p.is_active, p.online_sale_mode != "off"), query, id_column=p.id,
        sort_fields={"sort_order": p.sort_order, "name": p.name}, default_sort="sort_order",
        filter_fields={"reservation_type_id": p.reservation_type_id}, search=(p.name,),
    )  # fmt: skip
    return page | {
        "data": [_columns(plan) | {"is_purchasable": not plan.is_members_only_online} for plan in page["data"]]
    }


def portal_buy(session: Session, principal: Principal, data: dict, idempotency_key: str) -> dict:
    """Buy a plan online for oneself or a client one may buy for (PKG-09). A `paid_in_full` plan needs a card or
    bank payment that goes through, or nothing is sold; `balance_allowed` plans may be bought on account.
    Online, what is due is invoiced at once (a deferred plan default never applies), so there is always
    something to pay."""
    data = dict(data)
    subject = _portal_client(session, principal, data.pop("client_id", None), "buy")
    token = data.pop("method_token", None)
    tender = data.pop("tender_kind", "card")
    plan = session.get(PackagePlan, data["package_plan_id"])
    if plan is not None and plan.default_invoice_mode == "deferred":
        data["invoice_mode"] = "per_period" if plan.kind == "recurring" else "single"
    sold = sell(session, client_id=subject, channel="portal", online=True, **data)
    package, invoice = sold["package"], sold["invoice"]
    sold["payment"] = billing.checkout.secure_online_checkout(
        session, client_id=subject, location_id=package.location_id, total_minor=package.price_minor,
        invoice=invoice, idempotency_key=idempotency_key, method_token=token, tender_kind=tender,
        must_pay_now=True, on_account_ok=plan.online_sale_mode == "balance_allowed",
    )  # fmt: skip
    return _sale_view(session, sold)


def portal_disable_auto_renew(session: Session, principal: Principal, package_id: UUID) -> dict:
    """Click-to-cancel for a package (MEM-18): one way from the portal; the package runs to its end."""
    package = _portal_package(session, principal, package_id, "edit_profile")
    if package.is_auto_renew:
        package.is_auto_renew, package.auto_renew_disabled_by = False, "client"
        package.version += 1
        audit.record(session, "packages.package.disable_auto_renew", package, location_id=package.location_id,
                     changes={"is_auto_renew": [True, False]})  # fmt: skip
        session.flush()
    return package_view(session, package)


def portal_disable_series_auto_renew(session: Session, principal: Principal, series_id: UUID) -> PackageSeries:
    series = _get(session, PackageSeries, series_id, lock=True)
    _portal_client(session, principal, series.owner_client_id, "edit_profile")
    if series.is_auto_renew:
        series.is_auto_renew = False
        audit.record(session, "packages.package.disable_auto_renew", series, location_id=series.location_id,
                     changes={"is_auto_renew": [True, False]})  # fmt: skip
        session.flush()
    return series


# --- membership add-ons (MEM-04): driven by memberships events ---------------------------------------------------


def grant_contract_addons(session: Session, contract_id: UUID) -> int:
    """`memberships.contract.activated`: grant each bundled package plan once, free, tied to the contract.
    Idempotent through `uq_client_package_contract_addon` (checked first, so a redelivery does nothing)."""
    grant = memberships.service.addon_grants(session, contract_id)
    made = 0
    for addon in grant["addons"] if grant["is_live"] else []:
        exists = select(ClientPackage.id).where(ClientPackage.source_contract_addon_id == addon["id"])
        if session.scalar(exists) is None:
            sell(session, client_id=grant["client_id"], location_id=grant["location_id"],
                 package_plan_id=addon["package_plan_id"], channel="membership_addon", multiplier=addon["quantity"],
                 source_contract_id=contract_id, source_contract_addon_id=addon["id"])  # fmt: skip
            made += 1
    return made


def remove_contract_addons(session: Session, contract_id: UUID) -> int:
    """`memberships.contract.cancelled` with cancel_packages: the packages that came with the contract go too."""
    p = ClientPackage
    ids = list(session.scalars(select(p.id).where(p.source_contract_id == contract_id, p.status != "removed")))
    for package_id in ids:
        _remove(session, _get(session, p, package_id, lock=True), "billing_kept", None)
    return len(ids)


# --- the daily job -----------------------------------------------------------------------------------------------


def _expire(session: Session, package: ClientPackage) -> None:
    package.status = "expired"
    if not package.allows_booking_after_expiry and not package.is_unlimited and available(package) > 0:
        _entry(session, package, client_id=package.owner_client_id, entry_type="forfeit", reason="expiry",
               forfeited=available(package), key=f"package:{package.id}:expiry")  # fmt: skip
    audit.record(
        session,
        "packages.package.expire",
        package,
        location_id=package.location_id,
        changes={"status": [None, "expired"]},
    )
    events.publish(session, PackageExpired(client_package_id=package.id, client_id=package.owner_client_id), package.id)
    session.flush()


def run_daily(session: Session) -> dict:
    """Renewals, expiries and recurring periods, each item in its own savepoint. "Today" is the wall date at
    the package's location; a missed run is caught up by the next. Safe to run any number of times: a package
    has one successor and a series one package per sequence number (unique indexes), and an expired package is
    not live."""
    result = {"renewed": 0, "expired": 0, "periods_generated": 0, "failed": []}
    p, s = ClientPackage, PackageSeries
    todays: dict[UUID, date] = {}

    def today_at(location_id: UUID) -> date:
        return todays.get(location_id) or todays.setdefault(location_id, _today(session, location_id))

    def each(model, ids, work) -> None:
        for row_id in ids:
            try:
                with session.begin_nested():
                    work(_get(session, model, row_id, lock=True))
            except (DomainError, IntegrityError) as exc:
                result["failed"].append({"id": str(row_id), "error": getattr(exc, "code", "integrity-error")})

    def renew(package: ClientPackage) -> None:
        today = today_at(package.location_id)
        due = package.is_auto_renew and package.renew_on is not None and package.renew_on <= today
        if due and package.status in ("active", "exhausted") and _successor(session, package.id) is None:
            _renew(session, package, today)
            result["renewed"] += 1

    def expire(package: ClientPackage) -> None:
        upper = package.valid_during.upper
        if package.status in ("active", "exhausted") and upper is not None and upper <= today_at(package.location_id):
            _expire(session, package)
            result["expired"] += 1

    def period(series: PackageSeries) -> None:
        while series.status == "active" and (done := _next_period(session, series, today_at(series.location_id))):
            result["periods_generated"] += done == "generated"

    live = p.status.in_(("active", "exhausted"))
    each(
        p,
        list(session.scalars(select(p.id).where(live, p.is_auto_renew, p.renew_on.is_not(None)).order_by(p.id))),
        renew,
    )
    each(s, list(session.scalars(select(s.id).where(s.status == "active").order_by(s.id))), period)
    each(  # last, so a period generated late by this run is also expired by it
        p,
        list(session.scalars(select(p.id).where(live, func.upper(p.valid_during).is_not(None)).order_by(p.id))),
        expire,
    )
    return result


@tenant_actor
def run_package_day(session: Session) -> dict:
    """The queued form of run_daily, one message per tenant. Nothing schedules it yet (the kernel has no
    scheduler): enqueue it daily per tenant, after each location's `package_renewal_run_time`. Until then
    spending is still exact, because every reserve checks the validity dates; only stored statuses, successors
    and the next recurring periods wait for the run."""
    return run_daily(session)


# --- merge and data-subject handlers (CLI-13, security-baseline 4.3) ---------------------------------------------


def _repoint(session: Session, loser_id: UUID, survivor_id: UUID) -> None:
    p, share = ClientPackage, PackageShare
    session.execute(update(p).where(p.owner_client_id == loser_id).values(owner_client_id=survivor_id))
    session.execute(
        update(PackageSeries).where(PackageSeries.owner_client_id == loser_id).values(owner_client_id=survivor_id)
    )
    session.execute(text("SELECT app.repoint_credit_ledger_client(:a, :b)"), {"a": loser_id, "b": survivor_id})
    for row in session.scalars(select(share).where(share.client_id == loser_id)):
        duplicate = session.scalar(select(share.id).where(
            share.client_package_id == row.client_package_id, share.client_id == survivor_id, share.revoked_at.is_(None)
        ))  # fmt: skip
        if row.revoked_at is None and duplicate is not None:
            row.revoked_at = clock.now()  # the survivor already holds this share
        session.flush()
        row.client_id = survivor_id
    session.flush()
    own = select(p.owner_client_id).where(p.id == share.client_package_id).scalar_subquery()
    session.execute(  # a share with oneself ends
        update(share).where(share.client_id == survivor_id, share.revoked_at.is_(None), share.client_id == own)
        .values(revoked_at=clock.now())
    )  # fmt: skip


def _export(session: Session, client_id: UUID) -> dict:
    rows = session.scalars(select(ClientPackage).where(ClientPackage.owner_client_id == client_id))
    return {"packages": [
        {"name": r.name, "status": r.status, "sessions_granted_count": r.sessions_granted_count,
         "sessions_consumed_count": r.sessions_consumed_count, "price_minor": r.price_minor,
         "valid_from_on": r.valid_during.lower.isoformat()}
        for r in rows
    ]}  # fmt: skip


def _erase(session: Session, client_id: UUID) -> dict:
    """Sold packages and their ledger are financial records and stay, without free text; shares held by the
    client end and nothing renews for them."""
    p, share = ClientPackage, PackageShare
    kept = session.execute(
        update(p).where(p.owner_client_id == client_id).values(internal_remarks=None, is_auto_renew=False)
    ).rowcount
    session.execute(update(PackageSeries).where(PackageSeries.owner_client_id == client_id).values(is_auto_renew=False))
    revoked = session.execute(
        update(share).where(share.client_id == client_id, share.revoked_at.is_(None)).values(revoked_at=clock.now())
    ).rowcount
    return {"retained_packages": kept, "revoked_shares": revoked}


_TABLES = ("client_package", "package_series", "package_share", "credit_ledger_entry")
clients.merge.register_merge_handler("packages", tables=_TABLES, repoint=_repoint)
platform.privacy.register_subject_handler("packages", tables=_TABLES, export=_export, erase=_erase)


# --- internal: payroll facts (staff, STF-10) ---------------------------------------------------------------------


def sales_by_seller(session: Session, staff_user_id: UUID, starts_at, ends_at, location_ids=None) -> list[dict]:
    """Packages a staff user sold in [starts_at, ends_at): the facts a package-sale commission needs."""
    stmt = select(ClientPackage).where(
        ClientPackage.sold_by_staff_user_id == staff_user_id, ClientPackage.created_at >= starts_at,
        ClientPackage.created_at < ends_at, ClientPackage.is_complimentary.is_(False),
    )  # fmt: skip
    if location_ids is not None:
        stmt = stmt.where(ClientPackage.location_id.in_(list(location_ids)))
    return [
        {"id": p.id, "location_id": p.location_id, "sold_at": p.created_at, "name": p.name,
         "reservation_type_id": p.reservation_type_id, "price_minor": p.price_minor}
        for p in session.scalars(stmt.order_by(ClientPackage.created_at, ClientPackage.id))
    ]  # fmt: skip
