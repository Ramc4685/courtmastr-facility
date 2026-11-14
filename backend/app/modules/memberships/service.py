"""memberships service: catalogue, the sale, the contract lifecycle and the daily job (ADR 0005, data-model-people
section 3).

Memberships owns time, billing owns money: a schedule period becomes a charge only through `billing.service`,
with the period id as the charge's origin, so re-running the billing step cannot bill twice. The stored status
is changed in one place (`_converge`), which moves it to the pure `domain.effective_status`; entitlement reads
use that function directly, so a late job can never admit or refuse anyone wrongly.

Staff commands take a principal and authorize it. `eligibility`, `is_member` and `record_visit` are the internal
interface for other contexts (ADR 0009 section 9): no principal, no permission check.
"""

from dataclasses import replace
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.core import audit, clock, events
from app.core.api import CONSTRAINT_CODES
from app.core.audit import AuditEvent
from app.core.auth import Principal, authorize
from app.core.errors import Conflict, DomainError, NotFound, PermissionDenied, ValidationFailed
from app.core.jobs import tenant_actor
from app.core.pagination import ListQuery, paginate
from app.modules import billing, clients, documents, platform
from app.modules.memberships.domain import schedule as domain
from app.modules.memberships.events import (
    ContractActivated,
    ContractCancelled,
    ContractExpired,
    ContractFrozen,
    ContractRenewed,
    ContractSuspended,
    ContractUnfrozen,
)
from app.modules.memberships.models import (
    LIVE,
    BillingSchedulePeriod,
    MembershipContract,
    MembershipContractAddon,
    MembershipFreeze,
    MembershipPlan,
    MembershipPlanAddon,
    MembershipSettings,
    MembershipShare,
    MembershipSuspension,
    MembershipType,
    MembershipVisit,
)
from app.ports import notifications

_READ, _SELL, _MANAGE = "memberships.contract.read", "memberships.contract.sell", "memberships.plan.manage"
_CUSTOMIZE, _UPDATE = "memberships.contract.customize_terms", "memberships.contract.update"
_RENEW, _FREEZE, _SUSPEND = "memberships.contract.renew", "memberships.contract.freeze", "memberships.contract.suspend"
_CANCEL, _SHARE, _VISITS = (
    "memberships.contract.cancel",
    "memberships.contract.share",
    "memberships.contract.adjust_visits",
)
_SOLD_BY, _SCHEDULE = "memberships.contract.edit_sold_by", "memberships.billing_schedule.update"
# shortcut: a fixed window for online start dates, no plan setting; make it a plan field when owners ask
ONLINE_START_WINDOW_DAYS = 30
_ONE_DAY = timedelta(days=1)
_SOURCE = ("memberships", "membership_contract")
Period = BillingSchedulePeriod

CONSTRAINT_CODES["ex_membership_contract_term_overlap"] = "membership-overlap"
CONSTRAINT_CODES["ex_membership_freeze_overlap"] = "freeze-overlap"
CONSTRAINT_CODES["ex_membership_suspension_overlap"] = "suspension-overlap"
CONSTRAINT_CODES["uq_membership_contract_previous"] = "already-renewed"

notifications.register_template(
    "memberships.auto_renew_disabled",
    subject="$app: automatic renewal is off",
    body="Hello $name,\n\nAutomatic renewal of your $membership membership has been switched off. Nothing changes "
    "today: your membership runs until $end_on and then ends.\n\nIf this was a mistake, contact the front desk.",
)


# --- small helpers -----------------------------------------------------------------------------------------------


def _staff_id(principal: Principal) -> UUID | None:
    return principal.staff_user_id if principal.kind == "staff" else None


def _today(session: Session, location_id: UUID) -> date:
    return platform.service.location_today(session, location_id)


def _range(first: date, last: date | None) -> Range:
    """[first day, last day] as the canonical half-open range; no last day = open-ended."""
    return Range(first, None if last is None else last + _ONE_DAY)


def _columns(row) -> dict:
    return {c.key: getattr(row, c.key) for c in row.__table__.columns}


def _get(session: Session, model, row_id: UUID, *, lock: bool = False):
    row = session.get(model, row_id, with_for_update=lock or None, populate_existing=lock)
    if row is None:
        raise NotFound()
    return row


def _ref(session: Session, model, row_id: UUID, pointer: str):
    row = session.get(model, row_id)
    if row is None:
        raise ValidationFailed(f"Unknown {model.__tablename__.replace('_', ' ')}.", pointer=pointer)
    return row


def _load(session: Session, principal: Principal, contract_id: UUID, key: str) -> MembershipContract:
    """The contract the caller may act on with `key`, row-locked for commands. Outside reach or location: 404."""
    contract = _get(session, MembershipContract, contract_id, lock=key != _READ)
    if key == _READ:
        clients.service.load(session, principal, contract.owner_client_id, key)
    else:
        authorize(principal, key, location_id=contract.location_id)
        _converge(session, contract, _today(session, contract.location_id))  # commands judge the true status
    return contract


def _apply(row, data: dict) -> None:
    for key, value in data.items():
        setattr(row, key, value)


# --- settings (MEM-05) -------------------------------------------------------------------------------------------


def settings_row(session: Session) -> MembershipSettings:
    row = session.scalar(select(MembershipSettings))
    if row is None:
        row = MembershipSettings()
        session.add(row)
        session.flush()
    return row


def get_settings(session: Session, principal: Principal) -> MembershipSettings:
    authorize(principal, _READ)
    return settings_row(session)


def update_settings(session: Session, principal: Principal, data: dict) -> MembershipSettings:
    authorize(principal, _MANAGE)
    row = settings_row(session)
    _apply(row, data)
    audit.record(session, _MANAGE, row, changes=audit.diff(row))
    session.flush()
    return row


def _require_remark(session: Session, verb: str, remarks: str | None) -> None:
    if getattr(settings_row(session), f"is_remark_required_on_{verb}") and not (remarks or "").strip():
        raise ValidationFailed("A remark is required.", pointer="/remarks", code="remark-required")


# --- membership types (MEM-01) -----------------------------------------------------------------------------------


def list_types(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, _READ)
    return paginate(
        session, select(MembershipType), query, id_column=MembershipType.id,
        sort_fields={"sort_order": MembershipType.sort_order, "name": MembershipType.name}, default_sort="sort_order",
        filter_fields={"is_active": MembershipType.is_active}, search=(MembershipType.name,),
    )  # fmt: skip


def create_type(session: Session, principal: Principal, data: dict) -> MembershipType:
    authorize(principal, _MANAGE)
    row = MembershipType(**data)
    session.add(row)
    session.flush()
    audit.record(session, _MANAGE, row, changes={"name": [None, row.name]})
    return row


def update_type(session: Session, principal: Principal, type_id: UUID, data: dict) -> MembershipType:
    authorize(principal, _MANAGE)
    row = _get(session, MembershipType, type_id)
    _apply(row, data)
    audit.record(session, _MANAGE, row, changes=audit.diff(row))
    session.flush()
    return row


# --- membership plans (MEM-02, MEM-03, MEM-04) -------------------------------------------------------------------


def _addons(session: Session, plan_id: UUID) -> list[MembershipPlanAddon]:
    stmt = select(MembershipPlanAddon).where(MembershipPlanAddon.membership_plan_id == plan_id)
    return list(session.scalars(stmt.order_by(MembershipPlanAddon.sort_order, MembershipPlanAddon.id)))


def plan_view(session: Session, plan: MembershipPlan) -> dict:
    return _columns(plan) | {"addons": _addons(session, plan.id)}


def _check_plan(session: Session, plan: MembershipPlan) -> None:
    """Rules the table checks cannot state."""
    _ref(session, MembershipType, plan.membership_type_id, "/membership_type_id")
    if plan.renews_as_plan_id is not None:
        _ref(session, MembershipPlan, plan.renews_as_plan_id, "/renews_as_plan_id")
    mode = plan.proration_mode or "none"  # None = the column default, when a caller leaves it out
    if mode != "none" and (plan.billing_interval_unit or "month") not in ("month", "year"):
        raise ValidationFailed(
            "Proration to the month start needs monthly or yearly billing.", pointer="/proration_mode"
        )
    if plan.fixed_start_on is not None and mode == "seller_choice":
        raise ValidationFailed(
            "A plan with a fixed start date cannot leave proration to the seller.", pointer="/proration_mode"
        )


def list_plans(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, _READ)
    page = paginate(
        session, select(MembershipPlan), query, id_column=MembershipPlan.id,
        sort_fields={"sort_order": MembershipPlan.sort_order, "name": MembershipPlan.name}, default_sort="sort_order",
        filter_fields={
            "membership_type_id": MembershipPlan.membership_type_id, "is_active": MembershipPlan.is_active,
            "is_sold_online": MembershipPlan.is_sold_online,
        },
        search=(MembershipPlan.name,),
    )  # fmt: skip
    return page | {"data": [plan_view(session, plan) for plan in page["data"]]}


def get_plan(session: Session, principal: Principal, plan_id: UUID) -> dict:
    authorize(principal, _READ)
    return plan_view(session, _get(session, MembershipPlan, plan_id))


def create_plan(session: Session, principal: Principal, data: dict) -> dict:
    authorize(principal, _MANAGE)
    plan = MembershipPlan(**data)
    _check_plan(session, plan)
    session.add(plan)
    session.flush()
    audit.record(
        session, _MANAGE, plan, changes={"name": [None, plan.name], "term_fee_minor": [None, plan.term_fee_minor]}
    )
    return plan_view(session, plan)


def update_plan(session: Session, principal: Principal, plan_id: UUID, data: dict) -> dict:
    """Edits reach later sales and renewals only: sold contracts keep their snapshot (MEM-02)."""
    authorize(principal, _MANAGE)
    plan = _get(session, MembershipPlan, plan_id, lock=True)
    _apply(plan, data)
    _check_plan(session, plan)
    plan.version += 1
    audit.record(session, _MANAGE, plan, changes=audit.diff(plan))
    session.flush()
    return plan_view(session, plan)


def duplicate_plan(session: Session, principal: Principal, plan_id: UUID) -> dict:
    authorize(principal, _MANAGE)
    source = _get(session, MembershipPlan, plan_id)
    skip = {"id", "tenant_id", "created_at", "updated_at", "version", "name", "is_sold_online"}
    copy = MembershipPlan(**{k: v for k, v in _columns(source).items() if k not in skip}, name=f"{source.name} (copy)")
    session.add(copy)
    session.flush()
    for addon in _addons(session, source.id):
        session.add(MembershipPlanAddon(
            membership_plan_id=copy.id, addon_kind=addon.addon_kind, package_plan_id=addon.package_plan_id,
            catalog_item_id=addon.catalog_item_id, quantity=addon.quantity, sort_order=addon.sort_order,
        ))  # fmt: skip
    session.flush()
    audit.record(session, _MANAGE, copy, changes={"name": [None, copy.name], "copied_from": [None, str(source.id)]})
    return plan_view(session, copy)


def replace_plan_addons(session: Session, principal: Principal, plan_id: UUID, addons: list[dict]) -> dict:
    """Bundled package plans and pre-defined billing items (MEM-04). An item add-on is billed with the dues:
    every period when the item recurs, once with the first when it is a one-off."""
    authorize(principal, _MANAGE)
    plan = _get(session, MembershipPlan, plan_id, lock=True)
    for row in _addons(session, plan.id):
        session.delete(row)
    session.flush()
    for order, addon in enumerate(addons):
        item_id = addon.get("catalog_item_id")
        if item_id is not None and not billing.catalog.item_is_active(session, item_id):
            raise ValidationFailed("Choose an active pre-defined item.", pointer=f"/addons/{order}/catalog_item_id")
        session.add(MembershipPlanAddon(
            membership_plan_id=plan.id, addon_kind=addon.get("addon_kind", "package_plan"),
            package_plan_id=addon.get("package_plan_id"), catalog_item_id=item_id, quantity=addon.get("quantity", 1),
            sort_order=order,
        ))  # fmt: skip
    audit.record(session, _MANAGE, plan, changes={"addons": [None, len(addons)]})
    session.flush()
    return plan_view(session, plan)


# --- the sale (MEM-06, MEM-07, MEM-08) ---------------------------------------------------------------------------


def _addon_dict(addon) -> dict:
    get = addon.get if isinstance(addon, dict) else lambda key: getattr(addon, key)
    keys = ("addon_kind", "package_plan_id", "catalog_item_id", "quantity")
    return {key: get(key) for key in keys} | {"quantity": get("quantity") or 1}


def _addon_periods(
    session: Session,
    addons: list[dict],
    periods: list[domain.Period],
    location_id: UUID,
    name: str,
    start: date,
    *,
    renewal: bool = False,
    lenient: bool = False,
) -> tuple[list[domain.Period], list[dict]]:
    """Item add-ons (MEM-04) as `addon_item` rows priced from the catalogue now: a recurring item is billed with
    every dues period, a one-off once with the first (or at the start when there are no dues). A renewal
    carries only recurring items still sold at the location. The plan's own add-ons (`lenient`) skip an item that
    is inactive or sold at another location, so one item never makes a tenant-wide plan unsellable; add-ons
    chosen for this sale are refused instead. Returns the rows and the add-ons they came from."""
    dues = [p for p in periods if p.kind == "dues"]
    rows, kept = [], []
    for addon in addons:
        if addon["addon_kind"] != "catalog_item":
            continue
        try:
            item = billing.catalog.addon_terms(session, addon["catalog_item_id"], location_id=location_id)
        except ValidationFailed:
            if renewal or lenient:
                continue
            raise
        if renewal and not item["is_recurring"]:
            continue
        kept.append(addon)
        amount = item["amount_minor"] * addon["quantity"]
        label = f"{name}: {item['description']}" + (f" x {addon['quantity']}" if addon["quantity"] > 1 else "")
        for period in (dues if item["is_recurring"] else dues[:1]) or [None]:
            rows.append(domain.Period(
                kind="addon_item", sequence_number=len(rows) + 1, starts_on=period and period.starts_on,
                ends_on=period and period.ends_on, due_on=period.due_on if period else start,
                list_amount_minor=amount, amount_minor=amount, catalog_item_id=item["catalog_item_id"], description=label,
            ))  # fmt: skip
    return rows, kept


def _draft(session: Session, principal: Principal, data: dict, channel: str) -> tuple[dict, list[domain.Period]]:
    """Resolve plan, per-sale customisation and proration into contract fields and the schedule. No writes."""
    location_id = data["location_id"]
    online = channel == "portal"  # the portal caller was checked with can_act_for; it holds no staff key
    if not online:
        authorize(principal, _SELL, location_id=location_id)
    try:
        if online:
            _today(session, location_id)
        else:
            platform.service.get_location(session, principal, location_id)
    except NotFound:
        raise ValidationFailed("Unknown location.", pointer="/location_id") from None
    client = clients.service.require_active(session, data["client_id"])
    plan = _ref(session, MembershipPlan, data["membership_plan_id"], "/membership_plan_id")
    if not plan.is_active or (online and not plan.is_sold_online):
        raise ValidationFailed("This plan is not sold here.", pointer="/membership_plan_id")
    kind = session.get(MembershipType, plan.membership_type_id)
    custom = {k: v for k, v in (data.get("customize") or {}).items() if v is not None}
    if custom:
        authorize(principal, _CUSTOMIZE, location_id=location_id)
    sold_by = data.get("sold_by_staff_user_id")
    if sold_by and not platform.service.staff_user_exists(session, sold_by):
        raise ValidationFailed("Unknown staff user.", pointer="/sold_by_staff_user_id")
    if data.get("referred_by_client_id"):
        try:
            clients.service.get(session, data["referred_by_client_id"])
        except NotFound:
            raise ValidationFailed("Unknown client.", pointer="/referred_by_client_id") from None

    today = _today(session, location_id)
    start = plan.fixed_start_on or data.get("start_on") or today
    unit, interval = plan.billing_interval_unit, plan.billing_interval_count
    occurrences = custom.get("billing_occurrences_count", plan.billing_occurrences_count)
    tail = {"none": None, "to_month_start": plan.proration_tail}.get(plan.proration_mode, data.get("proration_tail"))
    if "end_on" in custom:  # an edited end date is one period of exactly that many days (MEM-07)
        if custom["end_on"] < start:
            raise ValidationFailed("The end date cannot be before the start date.", pointer="/customize/end_on")
        unit, interval, occurrences, tail = "day", (custom["end_on"] - start).days + 1, 1, None
    has_discount = "discount_pct" in custom or "discount_minor" in custom
    terms = domain.Terms(
        start_on=start, unit=unit, interval=interval, occurrences=occurrences,
        fee_minor=custom.get("term_fee_minor", plan.term_fee_minor),
        initiation_fee_minor=custom.get("initiation_fee_minor", plan.initiation_fee_minor),
        payment_due_day=plan.payment_due_day,
        discount_pct=custom.get("discount_pct") if has_discount else plan.discount_pct,
        discount_minor=custom.get("discount_minor") if has_discount else plan.discount_minor,
        proration_tail=tail,
    )  # fmt: skip
    periods, end_on = domain.build_schedule(terms)
    # the enrolment fee is due at the sale, also when the membership starts later
    periods = [replace(p, due_on=min(p.due_on, today)) if p.kind == "initiation" else p for p in periods]
    addons = [_addon_dict(a) for a in _addons(session, plan.id)]
    lenient = True
    if data.get("addons") is not None:  # this sale's own add-ons (MEM-04)
        chosen = [_addon_dict(a) for a in data["addons"]]
        if chosen != addons:
            authorize(principal, _CUSTOMIZE, location_id=location_id)
            lenient = False
        addons = chosen
    extra, kept = _addon_periods(session, addons, periods, location_id, plan.name, start, lenient=lenient)
    addons = [a for a in addons if a["addon_kind"] != "catalog_item" or a in kept]
    periods = periods + extra
    invoice_mode = data.get("invoice_mode") or plan.default_invoice_mode
    if sum(p.amount_minor for p in periods) == 0:
        invoice_mode, periods = "none", []  # a record-only membership (MEM-06): no schedule, nothing to bill
    elif invoice_mode in ("ask", "none"):
        invoice_mode = "per_period"
    is_prorated = any(p.is_prorated for p in periods)
    lead = (plan.auto_renew_lead_count, plan.auto_renew_lead_unit)
    auto_renew = lead[0] is not None and data.get("is_auto_renew") is not False
    fields = {
        "owner_client_id": client.id, "location_id": location_id, "membership_plan_id": plan.id,
        "membership_type_id": kind.id, "name": plan.name, "invoice_description": plan.invoice_description,
        "revenue_category_id": plan.revenue_category_id or kind.revenue_category_id, "start_on": start,
        "end_on": end_on, "original_end_on": end_on, "billing_interval_unit": unit,
        "billing_interval_count": interval, "billing_occurrences_count": occurrences,
        "term_fee_minor": terms.fee_minor, "initiation_fee_minor": terms.initiation_fee_minor,
        "discount_pct": terms.discount_pct, "discount_minor": terms.discount_minor,
        "payment_due_day": plan.payment_due_day, "max_visits_count": custom.get("max_visits_count", plan.max_visits_count),
        "is_autopay": billing.catalogue.membership_autopay_default(
            session, location_id, channel=channel, plan_default=plan.is_autopay_default
        ) if data.get("is_autopay") is None else data["is_autopay"],
        "invoice_mode": invoice_mode, "is_prorated": is_prorated, "proration_tail": tail if is_prorated else None,
        "is_auto_renew": auto_renew, "auto_renew_lead_count": lead[0], "auto_renew_lead_unit": lead[1],
        "renew_on": domain.renew_on(end_on, *lead), "renewal_target": plan.renewal_target,
        "renews_as_plan_id": plan.renews_as_plan_id,
        "sold_by_staff_user_id": data.get("sold_by_staff_user_id") or _staff_id(principal),
        "referred_by_client_id": data.get("referred_by_client_id"), "sales_channel": channel,
        "internal_notes": data.get("internal_notes"), "status": "upcoming", "addons": addons,
    }  # fmt: skip
    return fields, periods


def _period_view(period: domain.Period) -> dict:
    return {
        "kind": period.kind, "sequence_number": period.sequence_number, "starts_on": period.starts_on,
        "ends_on": period.ends_on and period.ends_on - _ONE_DAY, "due_on": period.due_on,
        "list_amount_minor": period.list_amount_minor, "amount_minor": period.amount_minor,
        "is_prorated": period.is_prorated,
    }  # fmt: skip


def quote_contract(session: Session, principal: Principal, data: dict, channel: str = "staff") -> dict:
    """What a sale would create: dates, proration and every period, pre-tax (billing adds tax at charge time)."""
    fields, periods = _draft(session, principal, data, channel)
    today = _today(session, fields["location_id"])
    lead = timedelta(days=settings_row(session).billing_lead_days)
    due_now = periods if fields["invoice_mode"] == "single" else [p for p in periods if p.due_on - lead <= today]
    keys = (
        "start_on",
        "end_on",
        "is_prorated",
        "proration_tail",
        "invoice_mode",
        "is_autopay",
        "is_auto_renew",
        "renew_on",
    )
    return {k: fields[k] for k in keys} | {
        "periods": [_period_view(p) for p in periods],
        "total_minor": sum(p.amount_minor for p in periods),
        "due_now_minor": 0 if fields["invoice_mode"] == "deferred" else sum(p.amount_minor for p in due_now),
        "card_save_mode": settings_row(session).online_card_save_mode,
        "requirements": documents.service.requirements_for(
            session, "membership_plan", fields["membership_plan_id"], fields["owner_client_id"],
            online=channel == "portal",
        ),
    }  # fmt: skip


def _check_overlap(session: Session, contract: MembershipContract) -> None:
    """One live membership per owner at a time. The exclusion constraint is the rule; this is its readable
    error for the common case (the constraint still catches a race, as 409 membership-overlap)."""
    clash = session.scalar(
        select(MembershipContract.id).where(
            MembershipContract.owner_client_id == contract.owner_client_id, MembershipContract.id != contract.id,
            MembershipContract.status.in_(LIVE), MembershipContract.start_on <= contract.end_on,
            MembershipContract.end_on >= contract.start_on,
        ).limit(1)
    )  # fmt: skip
    if clash is not None:
        raise Conflict(
            "This client already holds a membership in these dates.", code="membership-overlap", contract_id=str(clash)
        )


def _describe(contract: MembershipContract, period: domain.Period) -> str:
    if period.description:
        return period.description
    if period.kind == "initiation":
        return f"{contract.name}: enrolment fee"
    last = period.ends_on - _ONE_DAY
    return f"{contract.name}: {period.starts_on.isoformat()} to {last.isoformat()}"


def _add_periods(session: Session, contract: MembershipContract, periods: list[domain.Period], today: date) -> None:
    lead = timedelta(days=settings_row(session).billing_lead_days)
    single_revenue = contract.revenue_on if contract.billing_occurrences_count == 1 else None
    for period in periods:
        session.add(Period(
            membership_contract_id=contract.id, kind=period.kind, sequence_number=period.sequence_number,
            service_during=Range(period.starts_on, period.ends_on) if period.starts_on else None,
            due_on=period.due_on, bill_on=max(period.due_on - lead, today),
            revenue_on=single_revenue or period.starts_on or period.due_on,
            list_amount_minor=period.list_amount_minor, amount_minor=period.amount_minor,
            is_prorated=period.is_prorated, description=_describe(contract, period),
            catalog_item_id=period.catalog_item_id,
        ))  # fmt: skip
    session.flush()


def _rows(session: Session, contract_id: UUID, *statuses: str) -> list[Period]:
    stmt = select(Period).where(Period.membership_contract_id == contract_id)
    if statuses:
        stmt = stmt.where(Period.status.in_(statuses))
    return list(session.scalars(stmt.order_by(Period.due_on, Period.kind, Period.sequence_number)))


def _bill_rows(session: Session, contract: MembershipContract, rows: list[Period], today: date):
    """Turn scheduled rows into charges and one invoice. The charge origin is (period id, charge_sequence), so
    a row is charged once however often this runs; a row re-billed after a reversal uses the next sequence."""
    charge_ids, due = [], None
    for row in rows:
        lower, upper = (row.service_during.lower, row.service_during.upper) if row.service_during else (None, None)
        charge = billing.service.post_charge(
            session, client_id=contract.owner_client_id, location_id=contract.location_id,
            description=row.description, unit_price_minor=row.amount_minor, source_context="memberships",
            source_type="billing_schedule_period", source_id=row.id, source_line_no=row.charge_sequence,
            revenue_category_id=(
                billing.catalog.revenue_category_of(session, row.catalog_item_id)
                if row.catalog_item_id else contract.revenue_category_id
            ),
            revenue_on=row.revenue_on,
            additional_description=contract.invoice_description, service_starts_on=lower,
            service_ends_on=upper and upper - _ONE_DAY,
        )  # fmt: skip
        row.status, row.charge_id, row.billed_at = "billed", charge.id, clock.now()
        if charge.total_minor > 0 and charge.invoice_id is None and charge.status == "active":
            charge_ids.append(charge.id)
            due = min(due or row.due_on, row.due_on)
    session.flush()
    if not charge_ids:
        return None
    return billing.service.create_invoice_for_charges(
        session, charge_ids, due_on=max(due, today), origin="system", is_autopay=contract.is_autopay
    )


def _add_share(session: Session, contract: MembershipContract, client_id: UUID, staff_id: UUID | None, origin="manual"):
    if client_id == contract.owner_client_id:
        raise ValidationFailed("The owner is already covered by the membership.", pointer="/client_id")
    clients.service.require_active(session, client_id)
    existing = session.scalar(
        select(MembershipShare).where(
            MembershipShare.membership_contract_id == contract.id, MembershipShare.client_id == client_id,
            MembershipShare.revoked_at.is_(None),
        )
    )  # fmt: skip
    if existing is not None:
        return existing
    share = MembershipShare(
        membership_contract_id=contract.id, client_id=client_id, origin=origin, added_by_staff_user_id=staff_id
    )
    session.add(share)
    session.flush()
    return share


def _sell(session: Session, principal: Principal, data: dict, channel: str):
    """The sale itself, shared by the desk and the portal. Returns (contract, invoice for what is due now)."""
    fields, periods = _draft(session, principal, data, channel)
    addons = fields.pop("addons")
    if (
        channel == "staff" and fields["is_autopay"] and settings_row(session).payment_method_capture == "required"
        and billing.methods.autopay_method(session, fields["owner_client_id"]) is None
    ):  # fmt: skip
        raise ValidationFailed(
            "Store the member's card or bank account first: an autopay membership needs one (membership preferences).",
            pointer="/is_autopay", code="payment-method-required",
        )  # fmt: skip
    if channel == "staff":  # what the sale carries is gated like the commands that would set it later
        if data.get("share_client_ids"):
            authorize(principal, _SHARE, location_id=fields["location_id"])
        sold_by = data.get("sold_by_staff_user_id")
        if sold_by and sold_by != _staff_id(principal):
            authorize(principal, _SOLD_BY, location_id=fields["location_id"])
    contract = MembershipContract(**fields)
    session.add(contract)
    session.flush()
    _check_overlap(session, contract)
    today = _today(session, contract.location_id)
    _add_periods(session, contract, periods, today)
    for addon in addons:
        session.add(MembershipContractAddon(membership_contract_id=contract.id, **addon))
    for client_id in data.get("share_client_ids") or []:
        _add_share(session, contract, client_id, _staff_id(principal))
    clients.service.ensure_member_number(session, contract.owner_client_id)
    source = (*_SOURCE, contract.id)
    for need in documents.service.requirements_for(
        session, "membership_plan", contract.membership_plan_id, contract.owner_client_id, source=source,
        online=channel == "portal",
    ):  # fmt: skip
        if need["is_satisfied"]:
            contract.client_document_id = need["satisfied_by_document_id"]
            documents.service.consume(session, [contract.client_document_id], source)
        elif need["is_blocking"]:  # the contract waits as `upcoming` until this document is accepted (MEM-08)
            pending = documents.service.ensure_pending(
                session, need["binding_id"], contract.owner_client_id, contract.location_id
            )
            contract.client_document_id = pending.id
    session.flush()
    audit.record(
        session, _SELL, contract, location_id=contract.location_id,
        changes={"start_on": [None, str(contract.start_on)], "end_on": [None, str(contract.end_on)],
                 "term_fee_minor": [None, contract.term_fee_minor], "invoice_mode": [None, contract.invoice_mode]},
    )  # fmt: skip
    _converge(session, contract, today)
    due = _rows(session, contract.id, "scheduled")
    if contract.invoice_mode == "per_period":
        due = [row for row in due if row.bill_on <= today]
    invoice = _bill_rows(session, contract, due, today) if contract.invoice_mode in ("single", "per_period") else None
    return contract, invoice


def _sale_view(session: Session, contract: MembershipContract, invoice, payment) -> dict:
    return contract_view(session, contract) | {
        "invoice_id": invoice and invoice.id, "payment_id": payment and payment.id,
        "payment_status": payment and payment.status,
    }  # fmt: skip


def sell_contract(session: Session, principal: Principal, data: dict, idempotency_key: str | None = None) -> dict:
    """Sell a membership (MEM-07): contract snapshot, full schedule, add-ons, shares, the plan's document, what
    is due now billed onto one invoice and, optionally, a payment. A contract that starts today and has no open
    document gate is active in this transaction. A retry with the Idempotency-Key of a sale that went through
    returns that sale and sells nothing new."""
    idempotency_key = billing.service.staff_key(principal, idempotency_key)  # this caller's, as staff payments
    if data.get("payment") and (replayed := _replayed_sale(session, principal, data, idempotency_key)) is not None:
        return replayed
    contract, invoice = _sell(session, principal, data, "staff")
    payment = None
    if data.get("payment"):
        if invoice is None:
            raise ValidationFailed("Nothing is due now, so there is nothing to pay.", pointer="/payment")
        payment = billing.service.take_payment(
            session, client_id=contract.owner_client_id, location_id=contract.location_id, invoice_id=invoice.id,
            idempotency_key=idempotency_key, sale=_sale_ref("memberships", data), **data["payment"],
        )  # fmt: skip
        if payment.status in ("succeeded", "processing") and not billing.service.paid_sources(session, payment.id):
            payment = billing.service.allocate(session, payment.id, invoice_id=invoice.id)  # the earlier charge pays
    return _sale_view(session, contract, invoice, payment)


def _replayed_sale(session: Session, principal: Principal, data: dict, key: str | None) -> dict | None:
    """The sale a finished payment under `key` paid for, or None when the key took no payment yet (or only an
    `initiated` one, which this sale then finishes, or a settled one that pays for nothing yet: the request died
    after the charge and the sweep settled it, so this sale is sold and takes that payment). Selling again would
    add a contract the payment does not cover."""
    authorize(principal, _SELL, location_id=data["location_id"])
    prior = billing.service.find_payment(session, key) if key else None
    if prior is None or prior.status == "initiated":
        return None
    payment = billing.service.take_payment(  # the request-hash check only: a finished payment is replayed, never charged
        session, client_id=data["client_id"], location_id=data["location_id"], idempotency_key=key,
        sale=_sale_ref("memberships", data), **data["payment"],
    )  # fmt: skip
    sources = billing.service.paid_sources(session, payment.id)
    if not sources and payment.status in ("succeeded", "processing"):
        return None
    for context, kind, source_id, invoice_id in sources:
        period = (
            session.get(Period, source_id) if (context, kind) == ("memberships", "billing_schedule_period") else None
        )
        if period is not None:
            contract = session.get(MembershipContract, period.membership_contract_id)
            return contract_view(session, contract) | {
                "invoice_id": invoice_id, "payment_id": payment.id, "payment_status": payment.status,
            }  # fmt: skip
    raise Conflict(  # declined, cancelled or still unknown: it paid for nothing, so nothing to return or reuse
        "This Idempotency-Key already finished a sale. Check what happened to that attempt before selling again.",
        code="idempotency-key-reused",
    )  # fmt: skip


def _sale_ref(context: str, data: dict) -> str:
    """What a staff sale sells (the request body without its payment): each attempt raises a fresh invoice, so the
    payment's Idempotency-Key is bound to this instead (billing.take_payment `sale`)."""
    return repr((context, sorted((k, v) for k, v in data.items() if k != "payment")))


def import_contract(session: Session, data: dict) -> tuple[MembershipContract, bool]:
    """Internal (imports, MEM-23): a member's existing contract carried over from a spreadsheet. `data`: client_id,
    location_id, plan_name, start_on, and optionally end_on, next_bill_on, status, term_fee_minor (the price per
    period). The plan's terms are snapshotted as at a sale, with these differences: nothing before
    `next_bill_on` is scheduled (the old system billed it), so a contract without one is record-only; no
    enrolment fee, add-ons, shares or document gate; an expired contract does not renew. A contract with the same
    owner, plan and start already exists: returned with created False. `status`, when given, must be what the
    dates say (never guessed). Refused, never adjusted: a start date other than the plan's fixed start
    (`plan-fixed-start`), and a schedule whose first bill (due date less the billing lead) falls before
    `next_bill_on` (`bills-before-next-bill-date`). Caller runs it in a savepoint and authorizes the import."""
    matches = list(session.scalars(
        select(MembershipPlan).where(func.lower(MembershipPlan.name) == data["plan_name"].lower(),
                                     MembershipPlan.is_active).limit(2)
    ))  # fmt: skip
    if len(matches) != 1:
        problem = "No active membership plan has this name." if not matches else "Two active plans have this name."
        raise ValidationFailed(problem, pointer="/plan_name", code="unknown-plan")
    plan = matches[0]
    existing = session.scalar(select(MembershipContract).where(
        MembershipContract.owner_client_id == data["client_id"], MembershipContract.membership_plan_id == plan.id,
        MembershipContract.start_on == data["start_on"],
    ))  # fmt: skip
    if existing is not None:
        return existing, False
    if plan.fixed_start_on and plan.fixed_start_on != data["start_on"]:  # never silently replace the file's date
        raise ValidationFailed("This plan starts every membership on its own fixed date, not this start date.",
                               pointer="/start_on", code="plan-fixed-start")  # fmt: skip
    custom = {} if data.get("term_fee_minor") is None else {"term_fee_minor": data["term_fee_minor"]}
    draft = {"location_id": data["location_id"], "client_id": data["client_id"], "membership_plan_id": plan.id,
             "start_on": data["start_on"], "customize": custom}  # fmt: skip
    fields, periods = _draft(session, session.info["actor"], draft, "import")
    fields.pop("addons")  # an imported contract takes no add-ons; `keep` below holds dues only
    today = _today(session, data["location_id"])
    end = data.get("end_on") or fields["end_on"]
    if end < fields["start_on"]:
        raise ValidationFailed("The end date is before the start date.", pointer="/end_on")
    next_bill = data.get("next_bill_on")
    if next_bill is not None and not today <= next_bill <= end:
        raise ValidationFailed("The next bill date must be from today to the end date.", pointer="/next_bill_on")
    status = domain.effective_status("upcoming", fields["start_on"], end, [], [], today)
    if data.get("status") and data["status"] != status:
        raise ValidationFailed(f"The dates make this membership {status}.", pointer="/status", code="status-mismatch")
    keep = [p for p in periods if p.kind == "dues" and next_bill is not None and next_bill <= p.starts_on <= end]
    lead = timedelta(days=settings_row(session).billing_lead_days)
    if next_bill is not None and any(max(p.due_on - lead, today) < next_bill for p in keep):  # as _add_periods
        raise ValidationFailed(
            "This membership would first bill before its next bill date, because billing runs ahead of each due "
            "date here. Make the next bill date that much earlier than the period it pays for.",
            pointer="/next_bill_on", code="bills-before-next-bill-date",
        )  # fmt: skip
    renews = status != "expired" and fields["is_auto_renew"]
    fields |= {
        "end_on": end, "original_end_on": end, "initiation_fee_minor": 0, "is_auto_renew": renews,
        "renew_on": domain.renew_on(end, fields["auto_renew_lead_count"], fields["auto_renew_lead_unit"]) if renews else None,
        "invoice_mode": fields["invoice_mode"] if keep else "none", "is_prorated": False, "proration_tail": None,
    }  # fmt: skip
    contract = MembershipContract(**fields)
    session.add(contract)
    session.flush()
    _check_overlap(session, contract)
    _add_periods(session, contract, keep, today)
    clients.service.ensure_member_number(session, contract.owner_client_id)
    audit.record(
        session, "memberships.contract.import", contract, location_id=contract.location_id,
        changes={"start_on": [None, str(contract.start_on)], "end_on": [None, str(contract.end_on)],
                 "term_fee_minor": [None, contract.term_fee_minor], "invoice_mode": [None, contract.invoice_mode]},
    )  # fmt: skip
    _converge(session, contract, today, reason="import")
    return contract, True


# --- status: the one place it changes ----------------------------------------------------------------------------


def _spans(session: Session, contract_id: UUID) -> tuple[list[MembershipFreeze], list[MembershipSuspension]]:
    def live(model):
        stmt = select(model).where(model.membership_contract_id == contract_id, model.removed_at.is_(None))
        return list(session.scalars(stmt.order_by(model.id)))

    return live(MembershipFreeze), live(MembershipSuspension)


def _is_gated(session: Session, contract: MembershipContract) -> bool:
    """An accepted contract document is still missing (MEM-08)."""
    if contract.client_document_id is None or contract.membership_plan_id is None:
        return False
    needs = documents.service.requirements_for(
        session, "membership_plan", contract.membership_plan_id, contract.owner_client_id,
        source=(*_SOURCE, contract.id), online=contract.sales_channel == "portal",
    )  # fmt: skip
    return any(need["is_blocking"] and not need["is_satisfied"] for need in needs)


def effective_status(session: Session, contract: MembershipContract, on: date) -> str:
    freezes, suspensions = _spans(session, contract.id)
    return domain.effective_status(
        contract.status, contract.start_on, contract.end_on, [(f.during.lower, f.during.upper) for f in freezes],
        [(s.during.lower, s.during.upper) for s in suspensions], on,
        is_gated=contract.status == "upcoming" and _is_gated(session, contract),
    )  # fmt: skip


def _ended_freezes(contract_id: UUID, today: date):
    return select(MembershipFreeze.id).where(
        MembershipFreeze.membership_contract_id == contract_id, func.upper(MembershipFreeze.during) <= today
    )


def _converge(session: Session, contract: MembershipContract, today: date, *, reason: str = "start") -> int:
    """Move the stored status to what the dates say and emit the transition events. Idempotent: commands call
    it after changing dates or ranges, the daily job calls it for every live contract."""
    ref = {"contract_id": contract.id, "client_id": contract.owner_client_id}
    # A freeze that has ended hands its periods back to the billing run, unless it resumes "invoice later"
    # (`deferred`): those rows wait, still held, until staff invoice them (invoice_deferred).
    ended = _ended_freezes(contract.id, today).where(MembershipFreeze.resume_invoice_mode.is_distinct_from("deferred"))
    session.execute(
        update(Period).where(Period.withheld_by_freeze_id.in_(ended))
        .values(status="scheduled", withheld_by_freeze_id=None, pre_freeze=None)
    )  # fmt: skip
    changed = 0
    while (target := effective_status(session, contract, today)) != contract.status or (
        target == "expired" and contract.cancel_reason
    ):
        was = contract.status
        if target == "expired" and contract.cancel_reason:  # a scheduled cancel reached its date
            target, contract.cancelled_on, contract.cancelled_at = "cancelled", contract.end_on, clock.now()
        contract.status = target
        if was == "upcoming" and target in ("active", "frozen", "suspended"):
            contract.activated_at = clock.now()
            if contract.client_document_id is not None:
                documents.service.consume(session, [contract.client_document_id], (*_SOURCE, contract.id))
            # An imported contract that starts later still activates as an import (no welcome automation).
            why = "import" if contract.sales_channel == "import" else reason
            events.publish(session, ContractActivated(**ref, reason=why), contract.id)
        if target == "frozen":
            events.publish(session, ContractFrozen(**ref), contract.id)
        elif target == "suspended":
            events.publish(session, ContractSuspended(**ref), contract.id)
        elif target == "active" and was == "frozen":
            events.publish(session, ContractUnfrozen(**ref), contract.id)
        elif target == "active" and was == "suspended":
            events.publish(session, ContractActivated(**ref, reason="unsuspended"), contract.id)
        elif target == "expired":
            events.publish(session, ContractExpired(**ref), contract.id)
        elif target == "cancelled":
            events.publish(session, ContractCancelled(
                **ref, reason=contract.cancel_reason,
                cancel_packages=settings_row(session).is_addon_package_cancelled_with_contract,
            ), contract.id)  # fmt: skip
        contract.version += 1
        audit.record(
            session, "memberships.contract.transition", contract, location_id=contract.location_id,
            changes={"status": [was, target]},
        )  # fmt: skip
        session.flush()
        changed += 1
    session.flush()
    return changed


# --- reads (MEM-10) ----------------------------------------------------------------------------------------------


def _successor(session: Session, contract_id: UUID) -> MembershipContract | None:
    return session.scalar(select(MembershipContract).where(MembershipContract.previous_contract_id == contract_id))


def contract_view(session: Session, contract: MembershipContract) -> dict:
    successor = _successor(session, contract.id)
    covered = session.scalar(
        select(func.count()).select_from(MembershipShare).where(
            MembershipShare.membership_contract_id == contract.id, MembershipShare.revoked_at.is_(None)
        )
    )  # fmt: skip
    remaining = (
        None if contract.max_visits_count is None else max(contract.max_visits_count - contract.visits_used_count, 0)
    )
    return _columns(contract) | {
        "effective_status": effective_status(session, contract, _today(session, contract.location_id)),
        "successor_contract_id": successor and successor.id, "covered_client_count": covered + 1,
        "visits_remaining_count": remaining, "is_cancel_scheduled": contract.status != "cancelled" and bool(contract.cancel_reason),
    }  # fmt: skip


def list_contracts(session: Session, principal: Principal, query: ListQuery) -> dict:
    """Contracts across locations (a client-following key); location_id is a filter. Stored `upcoming` is the
    profile's "Upcoming" and the reports' "Pending"."""
    stmt = select(MembershipContract)
    if (reach := clients.service.reach_filter(principal, _READ, MembershipContract.owner_client_id)) is not None:
        stmt = stmt.where(reach)
    c = MembershipContract
    page = paginate(
        session, stmt, query, id_column=c.id,
        sort_fields={"start_on": c.start_on, "end_on": c.end_on, "created_at": c.created_at}, default_sort="-start_on",
        filter_fields={
            "client_id": c.owner_client_id, "location_id": c.location_id, "status": c.status,
            "membership_type_id": c.membership_type_id, "membership_plan_id": c.membership_plan_id,
            "is_auto_renew": c.is_auto_renew, "renew_on": c.renew_on, "start_on": c.start_on, "end_on": c.end_on,
            "previous_contract_id": c.previous_contract_id, "sales_channel": c.sales_channel,
        },
        search=(c.name,),
    )  # fmt: skip
    return page | {"data": [contract_view(session, row) for row in page["data"]]}


def get_contract(session: Session, principal: Principal, contract_id: UUID) -> dict:
    return contract_view(session, _load(session, principal, contract_id, _READ))


def list_schedule(session: Session, principal: Principal, contract_id: UUID) -> list[Period]:
    return _rows(session, _load(session, principal, contract_id, _READ).id)


def list_history(session: Session, principal: Principal, contract_id: UUID) -> list[AuditEvent]:
    """Status-change and edit history: the contract's audit trail, newest first (MEM-10)."""
    contract = _load(session, principal, contract_id, _READ)
    stmt = select(AuditEvent).where(
        AuditEvent.entity_type == "membership_contract", AuditEvent.entity_id == contract.id
    )
    return list(session.scalars(stmt.order_by(AuditEvent.id.desc()).limit(200)))


def list_upcoming_renewals(session: Session, principal: Principal, days: int, location_id: UUID | None) -> list[dict]:
    """The renewal work queue: contracts whose successor will be created within `days`, and successors already
    waiting to start. Each row carries the price the next term will bill."""
    c = MembershipContract
    horizon = clock.now().date() + timedelta(days=days + 1)  # a day of slack covers every time zone
    stmt = select(c).where(c.status.in_(("active", "suspended", "frozen")), c.cancel_reason.is_(None), c.is_auto_renew)
    stmt = stmt.where(c.renew_on <= horizon)
    if (reach := clients.service.reach_filter(principal, _READ, c.owner_client_id)) is not None:
        stmt = stmt.where(reach)
    if location_id is not None:
        stmt = stmt.where(c.location_id == location_id)
    out = []
    for contract in session.scalars(stmt.order_by(c.renew_on, c.id).limit(500)):
        successor = _successor(session, contract.id)
        fields = _columns(successor) if successor else _renewal_fields(session, contract)
        out.append({
            "contract_id": contract.id, "client_id": contract.owner_client_id, "name": contract.name,
            "location_id": contract.location_id, "end_on": contract.end_on, "renew_on": contract.renew_on,
            "successor_contract_id": successor and successor.id, "next_name": fields["name"],
            "next_start_on": fields["start_on"], "next_term_fee_minor": fields["term_fee_minor"],
            "next_discount_pct": fields["discount_pct"], "next_discount_minor": fields["discount_minor"],
        })  # fmt: skip
    return out


# --- edit (MEM-10, MEM-11, MEM-19) -------------------------------------------------------------------------------

_EDITABLE = {
    "is_autopay", "is_auto_renew", "auto_renew_lead_count", "auto_renew_lead_unit", "renewal_target", "renews_as_plan_id",
    "renewal_discount_pct", "renewal_discount_minor", "renewal_description", "renewal_remark", "max_visits_count",
    "internal_notes", "referred_by_client_id", "revenue_on", "invoice_description",
}  # fmt: skip


def update_contract(session: Session, principal: Principal, contract_id: UUID, data: dict) -> dict:
    """The mutable fields of a sold contract. Choosing another plan as the renewal target is how a member is
    upgraded or downgraded at the next term (MEM-11); sold terms themselves never change."""
    contract = _load(session, principal, contract_id, _UPDATE)
    if contract.status not in LIVE:
        raise Conflict("A contract that has ended can no longer be edited.")
    data = {k: v for k, v in data.items() if k in _EDITABLE}
    if "renews_as_plan_id" in data:
        data["renewal_target"] = "plan" if data["renews_as_plan_id"] else "same_terms"
    elif data.get("renewal_target") == "same_terms":
        data["renews_as_plan_id"] = None
    if data.get("renews_as_plan_id"):
        _ref(session, MembershipPlan, data["renews_as_plan_id"], "/renews_as_plan_id")
    if data.get("referred_by_client_id"):
        clients.service.require_active(session, data["referred_by_client_id"], pointer="/referred_by_client_id")
    if "revenue_on" in data and contract.billing_occurrences_count != 1:
        raise ValidationFailed("Only a single-period contract has one revenue date.", pointer="/revenue_on")
    was_renewing = contract.is_auto_renew
    _apply(contract, data)
    if (contract.auto_renew_lead_count is None) != (contract.auto_renew_lead_unit is None):
        raise ValidationFailed("Give the renewal lead as a count and a unit.", pointer="/auto_renew_lead_count")
    if contract.is_auto_renew and contract.auto_renew_lead_count is None:
        raise ValidationFailed("Automatic renewal needs a renewal lead.", pointer="/is_auto_renew")
    if was_renewing != contract.is_auto_renew:
        contract.auto_renew_disabled_by = None if contract.is_auto_renew else "staff"
        contract.auto_renew_disabled_at = None if contract.is_auto_renew else clock.now()
    contract.renew_on = domain.renew_on(contract.end_on, contract.auto_renew_lead_count, contract.auto_renew_lead_unit)
    if "revenue_on" in data:
        session.execute(
            update(Period).where(Period.membership_contract_id == contract.id, Period.status.in_(("scheduled", "withheld")))
            .values(revenue_on=data["revenue_on"])
        )  # fmt: skip
    contract.version += 1
    audit.record(session, _UPDATE, contract, location_id=contract.location_id, changes=audit.diff(contract))
    session.flush()
    return contract_view(session, contract)


def set_sold_by(session: Session, principal: Principal, contract_id: UUID, staff_user_id: UUID | None) -> dict:
    contract = _load(session, principal, contract_id, _SOLD_BY)
    if staff_user_id is not None and not platform.service.staff_user_exists(session, staff_user_id):
        raise ValidationFailed("Unknown staff user.", pointer="/sold_by_staff_user_id")
    contract.sold_by_staff_user_id = staff_user_id
    audit.record(session, _SOLD_BY, contract, location_id=contract.location_id, changes=audit.diff(contract))
    session.flush()
    return contract_view(session, contract)


def bind_agreement(session: Session, principal: Principal, contract_id: UUID, client_document_id: UUID) -> dict:
    """Bind a signed agreement to its contract (DOC-11): an accepted document of the owner's, issued from an
    agreement template that is not a waiver (422 otherwise). A signed binding is not replaced by a different
    document (409); binding the same one again changes nothing. The contract then shows it, and erasure keeps it as
    it keeps signed waivers. A contract still waiting on its gating document keeps that one until it is accepted."""
    contract = _load(session, principal, contract_id, _UPDATE)
    doc = documents.service.load_document(session, principal, client_document_id, "documents.document.read")
    signed = documents.service.is_signed(session, doc.id)
    if doc.client_id != contract.owner_client_id or not signed or not documents.service.is_agreement(session, doc):
        raise ValidationFailed("Bind a signed agreement of the contract's owner.", pointer="/client_document_id")
    if contract.client_document_id == doc.id:
        return contract_view(session, contract)
    if contract.client_document_id is not None and documents.service.is_signed(session, contract.client_document_id):
        raise Conflict("The contract already has a signed agreement.", code="invalid-state-transition")
    if contract.status == "upcoming" and _is_gated(session, contract):
        raise Conflict("The contract is waiting on its required document.", code="invalid-state-transition")
    contract.client_document_id = doc.id
    contract.version += 1
    audit.record(session, _UPDATE, contract, location_id=contract.location_id, changes=audit.diff(contract))
    session.flush()
    return contract_view(session, contract)


# --- price changes on a sold contract (MEM-13, ADR 0005 section 3) -----------------------------------------------


def _period(session: Session, principal: Principal, period_id: UUID) -> tuple[Period, MembershipContract]:
    period = _get(session, Period, period_id)
    return period, _load(session, principal, period.membership_contract_id, _SCHEDULE)


def update_period(session: Session, principal: Principal, period_id: UUID, data: dict) -> Period:
    """Edit one not-yet-billed row: amount, due date or text. A billed row changes only by reversal in billing."""
    period, contract = _period(session, principal, period_id)
    if period.status != "scheduled":
        raise Conflict("Only a scheduled period can be edited.", code="period-not-editable")
    today = _today(session, contract.location_id)
    _apply(period, data)
    if "due_on" in data:
        period.bill_on = max(period.due_on - timedelta(days=settings_row(session).billing_lead_days), today)
    audit.record(session, _SCHEDULE, contract, location_id=contract.location_id,
                 changes={"period": str(period.id), **audit.diff(period)})  # fmt: skip
    session.flush()
    return period


def reprice_contract(session: Session, principal: Principal, contract_id: UUID, data: dict) -> dict:
    """Change the dues of the remaining term: every not-yet-billed dues row due on or after `effective_on`
    keeps its proration and discount ratio at the new fee. Billed rows are untouched."""
    contract = _load(session, principal, contract_id, _SCHEDULE)
    if contract.status not in LIVE:
        raise Conflict("A contract that has ended cannot be repriced.")
    fee, effective = data["term_fee_minor"], data.get("effective_on") or _today(session, contract.location_id)
    changed = 0
    for row in _rows(session, contract.id, "scheduled", "withheld"):
        if row.kind != "dues" or row.due_on < effective:
            continue
        row.amount_minor = (
            domain.prorate(row.amount_minor, fee, row.list_amount_minor) if row.list_amount_minor else fee
        )
        row.list_amount_minor = fee
        changed += 1
    was, contract.term_fee_minor = contract.term_fee_minor, fee
    contract.version += 1
    audit.record(
        session, _SCHEDULE, contract, location_id=contract.location_id, reason=data.get("remarks"),
        changes={"term_fee_minor": [was, fee], "periods_repriced": [None, changed]},
    )  # fmt: skip
    session.flush()
    return contract_view(session, contract)


def invoice_deferred(session: Session, principal: Principal, contract_id: UUID, period_ids: list[UUID] | None) -> dict:
    """Invoice scheduled rows now ("invoice later" contracts, or billing a period ahead of its date), and the
    rows a freeze that resumed "invoice later" still holds."""
    contract = _load(session, principal, contract_id, _SCHEDULE)
    today = _today(session, contract.location_id)
    held = set(session.scalars(
        _ended_freezes(contract.id, today).where(MembershipFreeze.resume_invoice_mode == "deferred")
    ))  # fmt: skip
    rows = [
        r for r in _rows(session, contract.id, "scheduled", "withheld")
        if (r.status == "scheduled" or r.withheld_by_freeze_id in held) and (period_ids is None or r.id in period_ids)
    ]  # fmt: skip
    if not rows or (period_ids is not None and len(rows) != len(set(period_ids))):
        raise ValidationFailed("Choose scheduled periods of this contract.", pointer="/period_ids")
    for row in rows:
        row.status, row.withheld_by_freeze_id, row.pre_freeze = "scheduled", None, None
    session.flush()
    invoice = _bill_rows(session, contract, rows, today)
    audit.record(
        session, _SCHEDULE, contract, location_id=contract.location_id, changes={"periods_billed": [None, len(rows)]}
    )
    return {"invoice_id": invoice and invoice.id, "period_ids": [row.id for row in rows]}


# --- freeze (MEM-12, MEM-13; ADR 0005 section 4) -----------------------------------------------------------------


def _clash(session: Session, model, contract_id: UUID, during: Range) -> bool:
    return session.scalar(
        select(model.id).where(
            model.membership_contract_id == contract_id, model.removed_at.is_(None), model.during.overlaps(during)
        ).limit(1)
    ) is not None  # fmt: skip


def _unpaid(session: Session, charge_id: UUID) -> bool:
    charge = billing.service.get_charge(session, charge_id)
    return charge.status == "active" and charge.applied_minor == 0


def _starts(row: Period) -> date:
    return row.service_during.lower if row.service_during else row.due_on


def _unbill(session: Session, row: Period, reason: str) -> None:
    """Reverse the row's charge; the row can be billed again under the next origin line."""
    billing.service.reverse(session, row.charge_id, reason=reason)
    row.status, row.charge_id, row.billed_at, row.charge_sequence = "scheduled", None, None, row.charge_sequence + 1


def _withhold(session: Session, contract: MembershipContract, freeze: MembershipFreeze) -> None:
    """Hold back everything not yet billed from the freeze start, and un-bill unpaid periods that start inside
    it. Paid periods are never touched: a freeze moves time, not money."""
    start = freeze.during.lower
    for row in _rows(session, contract.id, "scheduled", "billed"):
        if row.status == "billed":
            if _starts(row) < start or not _unpaid(session, row.charge_id):
                continue
            _unbill(session, row, "Membership frozen")
            if contract.invoice_mode == "single":
                contract.invoice_mode = "per_period"
        elif row.due_on < start:
            continue
        span = row.service_during
        row.pre_freeze = {
            "due_on": row.due_on.isoformat(), "bill_on": row.bill_on.isoformat(), "revenue_on": row.revenue_on.isoformat(),
            "lower": span and span.lower.isoformat(), "upper": span and span.upper.isoformat(),
        }  # fmt: skip
        row.status, row.withheld_by_freeze_id = "withheld", freeze.id
    session.flush()


def _iso(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _shift_successor(session: Session, contract: MembershipContract, days: int) -> None:
    successor = _successor(session, contract.id)
    if successor is None or successor.status != "upcoming" or days == 0:
        return
    delta = timedelta(days=days)
    successor.start_on, successor.end_on = successor.start_on + delta, successor.end_on + delta
    successor.original_end_on += delta
    successor.renew_on = successor.renew_on and successor.renew_on + delta
    for row in _rows(session, successor.id, "scheduled"):
        row.due_on, row.bill_on, row.revenue_on = row.due_on + delta, row.bill_on + delta, row.revenue_on + delta
        if row.service_during:
            row.service_during = Range(row.service_during.lower + delta, row.service_during.upper + delta)


def _settle(session: Session, contract: MembershipContract, freeze: MembershipFreeze, last_day: date | None) -> None:
    """Make the contract match a freeze that ends on `last_day` (None or before the start = no frozen days).
    Recomputed from the pre-freeze dates each time, so saving, editing and removing an end date are all exact:
    the term moves out by the frozen days, the withheld periods restart on the resume date and step by cadence,
    and an upcoming successor moves with the term."""
    start = freeze.during.lower
    days = 0 if last_day is None else max((last_day - start).days + 1, 0)
    delta = days - freeze.extended_days_count
    contract.end_on += timedelta(days=delta)
    contract.renew_on = domain.renew_on(contract.end_on, contract.auto_renew_lead_count, contract.auto_renew_lead_unit)
    freeze.extended_days_count = days
    _shift_successor(session, contract, delta)
    rows = list(session.scalars(select(Period).where(Period.withheld_by_freeze_id == freeze.id)))
    before = [
        domain.Period(
            row.kind, row.sequence_number, _iso(row.pre_freeze["lower"]), _iso(row.pre_freeze["upper"]),
            _iso(row.pre_freeze["due_on"]), row.list_amount_minor, row.amount_minor, row.is_prorated,
        )
        for row in rows
    ]  # fmt: skip
    after = before
    if days:
        after = domain.redate_after_freeze(
            before, start + timedelta(days=days), contract.billing_interval_unit, contract.billing_interval_count
        )
    lead = timedelta(days=settings_row(session).billing_lead_days)
    # MEM-05/MEM-13 `single`: everything left is billed together on the resume day (one invoice). `deferred` is
    # applied when the freeze ends (_converge keeps the rows held until staff invoice them).
    together = (
        max(start + timedelta(days=days) - lead, start) if days and freeze.resume_invoice_mode == "single" else None
    )
    for row, was, now in zip(rows, before, after, strict=True):
        moved = now.due_on != was.due_on
        row.due_on = now.due_on
        row.bill_on = max(now.due_on - lead, start) if moved else _iso(row.pre_freeze["bill_on"])
        if together and moved:
            row.bill_on = together
        row.revenue_on = (now.starts_on or now.due_on) if moved else _iso(row.pre_freeze["revenue_on"])
        row.service_during = Range(now.starts_on, now.ends_on) if now.starts_on else None
    session.flush()


def freeze_contract(session: Session, principal: Principal, contract_id: UUID, data: dict) -> MembershipFreeze:
    """Freeze from `start_on`, optionally to `end_on` (open-ended otherwise). Billing pauses, the end date moves
    out by the frozen days, and autopay and auto-renew keep their settings for the resume."""
    contract = _load(session, principal, contract_id, _FREEZE)
    _require_remark(session, "freeze", data.get("remarks"))
    today = _today(session, contract.location_id)
    start, end = data.get("start_on") or today, data.get("end_on")
    if contract.status != "active" or contract.cancel_reason:
        raise Conflict("Only an active membership can be frozen.")
    if start < today or start > contract.end_on:
        raise ValidationFailed("A freeze starts today or later, inside the term.", pointer="/start_on")
    if end is not None and end < start:
        raise ValidationFailed("The freeze cannot end before it starts.", pointer="/end_on")
    during = _range(start, end)
    if _clash(session, MembershipFreeze, contract.id, during):
        raise Conflict("The membership is already frozen in these dates.", code="freeze-overlap")
    if _clash(session, MembershipSuspension, contract.id, during):
        raise Conflict("A freeze cannot overlap a suspension.", code="freeze-suspension-overlap")
    freeze = MembershipFreeze(
        membership_contract_id=contract.id, during=during, remarks=data.get("remarks"),
        resume_invoice_mode=data.get("resume_invoice_mode") or settings_row(session).freeze_resume_invoice_mode,
        created_by_staff_user_id=_staff_id(principal),
    )  # fmt: skip
    session.add(freeze)
    session.flush()
    _withhold(session, contract, freeze)
    _settle(session, contract, freeze, end)
    contract.version += 1
    audit.record(
        session, _FREEZE, contract, location_id=contract.location_id, reason=data.get("remarks"),
        changes={"freeze": [None, [str(start), end and str(end)]], "end_on": [str(contract.original_end_on), str(contract.end_on)]},
    )  # fmt: skip
    _converge(session, contract, today)
    return freeze


def _freeze(
    session: Session, principal: Principal, freeze_id: UUID
) -> tuple[MembershipFreeze, MembershipContract, date]:
    freeze = _get(session, MembershipFreeze, freeze_id)
    contract = _load(session, principal, freeze.membership_contract_id, _FREEZE)
    today = _today(session, contract.location_id)
    if freeze.removed_at is not None or (freeze.during.upper is not None and freeze.during.upper <= today):
        raise Conflict("This freeze has already ended.", code="freeze-ended")
    if contract.status not in ("active", "frozen"):
        raise Conflict("The membership is no longer active.")
    return freeze, contract, today


def update_freeze(session: Session, principal: Principal, freeze_id: UUID, data: dict) -> MembershipFreeze:
    """Save or change the end date of a freeze that has not ended (MEM-13). The schedule simply resumes on the
    day after; nobody re-invoices by hand."""
    freeze, contract, today = _freeze(session, principal, freeze_id)
    if "end_on" in data:
        end = data["end_on"]
        if end is not None and end < freeze.during.lower:
            raise ValidationFailed("The freeze cannot end before it starts.", pointer="/end_on")
        during = _range(freeze.during.lower, end)
        other = MembershipFreeze.id != freeze.id
        if session.scalar(select(MembershipFreeze.id).where(
            MembershipFreeze.membership_contract_id == contract.id, MembershipFreeze.removed_at.is_(None), other,
            MembershipFreeze.during.overlaps(during),
        ).limit(1)) is not None:  # fmt: skip
            raise Conflict("The membership is already frozen in these dates.", code="freeze-overlap")
        if _clash(session, MembershipSuspension, contract.id, during):
            raise Conflict("A freeze cannot overlap a suspension.", code="freeze-suspension-overlap")
        freeze.during = during
        _settle(session, contract, freeze, end)
    if "remarks" in data:
        freeze.remarks = data["remarks"]
    contract.version += 1
    audit.record(session, _FREEZE, contract, location_id=contract.location_id, reason=data.get("remarks"),
                 changes={"freeze_end_on": [None, data.get("end_on") and str(data["end_on"])], "end_on": [None, str(contract.end_on)]})  # fmt: skip
    _converge(session, contract, today)
    return freeze


def remove_freeze(session: Session, principal: Principal, freeze_id: UUID, data: dict) -> MembershipFreeze:
    """Unfreeze. Before the freeze has begun this undoes it completely (dates and schedule as sold). Once it
    has begun it ends as of yesterday: the days already frozen stay frozen, and billing resumes today."""
    freeze, contract, today = _freeze(session, principal, freeze_id)
    last_day = today - _ONE_DAY
    if last_day < freeze.during.lower:
        _settle(session, contract, freeze, None)
        session.execute(
            update(Period).where(Period.withheld_by_freeze_id == freeze.id)
            .values(status="scheduled", withheld_by_freeze_id=None, pre_freeze=None)
        )  # fmt: skip
        freeze.removed_at, freeze.removed_by_staff_user_id = clock.now(), _staff_id(principal)
    else:
        freeze.during = _range(freeze.during.lower, last_day)
        _settle(session, contract, freeze, last_day)
    freeze.removal_remarks = data.get("removal_remarks")
    contract.version += 1
    audit.record(session, _FREEZE, contract, location_id=contract.location_id, reason=data.get("removal_remarks"),
                 changes={"freeze_removed": [None, str(freeze.id)], "end_on": [None, str(contract.end_on)]})  # fmt: skip
    _converge(session, contract, today)
    return freeze


def list_freezes(session: Session, principal: Principal, contract_id: UUID) -> list[MembershipFreeze]:
    contract = _load(session, principal, contract_id, _READ)
    stmt = select(MembershipFreeze).where(MembershipFreeze.membership_contract_id == contract.id)
    return list(session.scalars(stmt.order_by(MembershipFreeze.id)))


# --- suspension (MEM-14; ADR 0005 section 5) ---------------------------------------------------------------------


def _sync_fee_rows(
    session: Session, contract: MembershipContract, suspension: MembershipSuspension, today: date
) -> None:
    """One fee row beside each dues period that falls due inside the suspension, and one at its start when no
    dues fall due that day. Re-run after any change of the range: rows no longer wanted are cancelled."""
    lower, upper = suspension.during.lower, suspension.during.upper
    live = suspension.removed_at is None and suspension.fee_minor
    wanted = set()
    if live:
        for row in _rows(session, contract.id, "scheduled", "billed", "withheld"):
            if row.kind == "dues" and lower <= row.due_on and (upper is None or row.due_on < upper):
                wanted.add(row.due_on)
        wanted.add(lower)
    fees = session.scalars(select(Period).where(Period.suspension_id == suspension.id)).all()
    for row in fees:
        if row.status != "cancelled":
            if row.due_on in wanted or row.status == "billed":
                wanted.discard(row.due_on)
            else:
                row.status, row.cancelled_reason, row.withheld_by_freeze_id = "cancelled", "suspension_ended", None
    number = session.scalar(
        select(func.coalesce(func.max(Period.sequence_number), 0)).where(
            Period.membership_contract_id == contract.id, Period.kind == "suspension_fee"
        )
    )  # fmt: skip
    lead = timedelta(days=settings_row(session).billing_lead_days)
    for offset, due in enumerate(sorted(wanted), start=1):
        session.add(Period(
            membership_contract_id=contract.id, kind="suspension_fee", sequence_number=number + offset, due_on=due,
            bill_on=max(due - lead, today), revenue_on=due, list_amount_minor=suspension.fee_minor,
            amount_minor=suspension.fee_minor, description=f"{contract.name}: suspension fee",
            suspension_id=suspension.id,
        ))  # fmt: skip
    session.flush()


def suspend_contract(session: Session, principal: Principal, contract_id: UUID, data: dict) -> MembershipSuspension:
    """Suspend: access is denied, dues keep billing, no dates move, and the optional fee is billed per period."""
    contract = _load(session, principal, contract_id, _SUSPEND)
    _require_remark(session, "suspend", data.get("remarks"))
    today = _today(session, contract.location_id)
    start, end = data.get("start_on") or today, data.get("end_on")
    if contract.status != "active" or contract.cancel_reason:
        raise Conflict("Only an active membership can be suspended.")
    if start < today or start > contract.end_on:
        raise ValidationFailed("A suspension starts today or later, inside the term.", pointer="/start_on")
    if end is not None and end < start:
        raise ValidationFailed("The suspension cannot end before it starts.", pointer="/end_on")
    during = _range(start, end)
    if _clash(session, MembershipSuspension, contract.id, during):
        raise Conflict("The membership is already suspended in these dates.", code="suspension-overlap")
    if _clash(session, MembershipFreeze, contract.id, during):
        raise Conflict("A suspension cannot overlap a freeze.", code="freeze-suspension-overlap")
    suspension = MembershipSuspension(
        membership_contract_id=contract.id, during=during, fee_minor=data.get("fee_minor") or None,
        remarks=data.get("remarks"), created_by_staff_user_id=_staff_id(principal),
    )  # fmt: skip
    session.add(suspension)
    session.flush()
    _sync_fee_rows(session, contract, suspension, today)
    contract.version += 1
    audit.record(
        session, _SUSPEND, contract, location_id=contract.location_id, reason=data.get("remarks"),
        changes={"suspension": [None, [str(start), end and str(end)]], "fee_minor": [None, suspension.fee_minor]},
    )  # fmt: skip
    _converge(session, contract, today)
    return suspension


def _suspension(session: Session, principal: Principal, suspension_id: UUID):
    suspension = _get(session, MembershipSuspension, suspension_id)
    contract = _load(session, principal, suspension.membership_contract_id, _SUSPEND)
    today = _today(session, contract.location_id)
    if suspension.removed_at is not None or (suspension.during.upper is not None and suspension.during.upper <= today):
        raise Conflict("This suspension has already ended.", code="suspension-ended")
    return suspension, contract, today


def update_suspension(session: Session, principal: Principal, suspension_id: UUID, data: dict) -> MembershipSuspension:
    suspension, contract, today = _suspension(session, principal, suspension_id)
    if "end_on" in data:
        end = data["end_on"]
        if end is not None and end < suspension.during.lower:
            raise ValidationFailed("The suspension cannot end before it starts.", pointer="/end_on")
        during = _range(suspension.during.lower, end)
        if _clash(session, MembershipFreeze, contract.id, during):
            raise Conflict("A suspension cannot overlap a freeze.", code="freeze-suspension-overlap")
        suspension.during = during
    if "remarks" in data:
        suspension.remarks = data["remarks"]
    session.flush()
    _sync_fee_rows(session, contract, suspension, today)
    audit.record(session, _SUSPEND, contract, location_id=contract.location_id, reason=data.get("remarks"),
                 changes={"suspension_end_on": [None, data.get("end_on") and str(data["end_on"])]})  # fmt: skip
    _converge(session, contract, today)
    return suspension


def remove_suspension(session: Session, principal: Principal, suspension_id: UUID, data: dict) -> MembershipSuspension:
    """Unsuspend: not yet begun, it is withdrawn with its fee rows; begun, it ends as of yesterday and fee rows
    due from today on are cancelled."""
    suspension, contract, today = _suspension(session, principal, suspension_id)
    _lift(session, contract, suspension, today, staff_id=_staff_id(principal), remarks=data.get("removal_remarks"))
    audit.record(session, _SUSPEND, contract, location_id=contract.location_id, reason=data.get("removal_remarks"),
                 changes={"suspension_removed": [None, str(suspension.id)]})  # fmt: skip
    _converge(session, contract, today)
    return suspension


def _lift(
    session: Session,
    contract: MembershipContract,
    suspension: MembershipSuspension,
    today: date,
    *,
    staff_id: UUID | None,
    remarks: str | None,
) -> None:
    """End a suspension as of yesterday, or withdraw it with its fee rows when it has not begun yet."""
    last_day = today - _ONE_DAY
    if last_day < suspension.during.lower:
        suspension.removed_at, suspension.removed_by_staff_user_id = clock.now(), staff_id
    else:
        suspension.during = _range(suspension.during.lower, last_day)
    suspension.removal_remarks = remarks
    session.flush()
    _sync_fee_rows(session, contract, suspension, today)


def list_suspensions(session: Session, principal: Principal, contract_id: UUID) -> list[MembershipSuspension]:
    contract = _load(session, principal, contract_id, _READ)
    stmt = select(MembershipSuspension).where(MembershipSuspension.membership_contract_id == contract.id)
    return list(session.scalars(stmt.order_by(MembershipSuspension.id)))


# --- renewal (MEM-11; ADR 0005 section 6) ------------------------------------------------------------------------


def _renewal_fields(session: Session, contract: MembershipContract, plan_id: UUID | None = None) -> dict:
    """The successor's terms: a copy of the contract as sold (price lock), or the named plan read now, so plan
    edits and intro-into-full-price chains flow through. Never prorated, no enrolment fee."""
    plan_id = plan_id or (contract.renews_as_plan_id if contract.renewal_target == "plan" else None)
    keep = (
        "owner_client_id", "location_id", "is_autopay", "is_auto_renew", "sold_by_staff_user_id", "referred_by_client_id",
    )  # fmt: skip
    same = (
        "membership_plan_id", "membership_type_id", "name", "invoice_description", "revenue_category_id",
        "billing_interval_unit", "billing_interval_count", "billing_occurrences_count", "term_fee_minor",
        "discount_pct", "discount_minor", "payment_due_day", "max_visits_count", "auto_renew_lead_count",
        "auto_renew_lead_unit", "renewal_target", "renews_as_plan_id",
    )  # fmt: skip
    fields = {key: getattr(contract, key) for key in keep}
    if plan_id is None:
        fields |= {key: getattr(contract, key) for key in same}
    else:
        plan = _ref(session, MembershipPlan, plan_id, "/renews_as_plan_id")
        kind = session.get(MembershipType, plan.membership_type_id)
        fields |= {key: getattr(plan, key) for key in same if hasattr(plan, key)} | {
            "membership_plan_id": plan.id, "revenue_category_id": plan.revenue_category_id or kind.revenue_category_id,
        }  # fmt: skip
    if contract.renewal_discount_pct is not None or contract.renewal_discount_minor is not None:
        fields |= {"discount_pct": contract.renewal_discount_pct, "discount_minor": contract.renewal_discount_minor}
    if contract.renewal_description:
        fields["invoice_description"] = contract.renewal_description[:100]
    fields |= {
        "start_on": contract.end_on + _ONE_DAY, "initiation_fee_minor": 0, "is_prorated": False, "status": "upcoming",
        "invoice_mode": contract.invoice_mode if contract.invoice_mode in ("deferred", "none") else "per_period",
        "previous_contract_id": contract.id, "sales_channel": "renewal", "internal_notes": contract.renewal_remark,
        "is_auto_renew": contract.is_auto_renew and fields["auto_renew_lead_count"] is not None,
    }  # fmt: skip
    return fields


def _renew(
    session: Session, contract: MembershipContract, today: date, plan_id: UUID | None = None
) -> MembershipContract:
    """Create the successor. At most one exists per contract (`uq_membership_contract_previous`); the caller
    holds the contract's row lock, so a second caller sees the first one's successor."""
    fields = _renewal_fields(session, contract, plan_id)
    terms = domain.Terms(
        fields["start_on"], fields["billing_interval_unit"], fields["billing_interval_count"],
        fields["billing_occurrences_count"], fields["term_fee_minor"], 0, fields["payment_due_day"],
        fields["discount_pct"], fields["discount_minor"],
    )  # fmt: skip
    periods, end_on = domain.build_schedule(terms)
    lead = (fields["auto_renew_lead_count"], fields["auto_renew_lead_unit"])
    successor = MembershipContract(
        **fields, end_on=end_on, original_end_on=end_on, renew_on=domain.renew_on(end_on, *lead)
    )
    session.add(successor)
    session.flush()
    _check_overlap(session, successor)
    item_addons = select(MembershipContractAddon).where(
        MembershipContractAddon.membership_contract_id == contract.id,
        MembershipContractAddon.catalog_item_id.is_not(None),
    )
    extra, kept = _addon_periods(
        session, [_addon_dict(a) for a in session.scalars(item_addons)], periods, successor.location_id, successor.name,
        successor.start_on, renewal=True,
    )  # fmt: skip
    for addon in kept:  # recurring item add-ons ride along; one-offs were billed once, with the first term
        session.add(MembershipContractAddon(membership_contract_id=successor.id, **addon))
    if successor.invoice_mode != "none":
        _add_periods(session, successor, periods + extra, today)
    shares = select(MembershipShare).where(
        MembershipShare.membership_contract_id == contract.id, MembershipShare.revoked_at.is_(None)
    )
    for share in session.scalars(shares):
        session.add(MembershipShare(
            membership_contract_id=successor.id, client_id=share.client_id, origin="carried_from_previous"
        ))  # fmt: skip
    # A suspension that runs past the term end is inherited: the successor starts suspended, dues plus fee.
    for suspension in _spans(session, contract.id)[1]:
        if suspension.during.upper is None or suspension.during.upper > successor.start_on:
            carried = MembershipSuspension(
                membership_contract_id=successor.id, during=Range(successor.start_on, suspension.during.upper),
                fee_minor=suspension.fee_minor, remarks=suspension.remarks,
            )  # fmt: skip
            session.add(carried)
            session.flush()
            _sync_fee_rows(session, successor, carried, today)
    audit.record(
        session, _RENEW, contract, location_id=contract.location_id,
        changes={"successor": [None, str(successor.id)], "term_fee_minor": [contract.term_fee_minor, successor.term_fee_minor]},
    )  # fmt: skip
    events.publish(
        session,
        ContractRenewed(
            contract_id=contract.id, client_id=contract.owner_client_id, successor_contract_id=successor.id,
            start_on=successor.start_on, term_fee_minor=successor.term_fee_minor,
        ),
        contract.id,
    )  # fmt: skip
    session.flush()
    return successor


def renew_contract(session: Session, principal: Principal, contract_id: UUID, data: dict) -> dict:
    """Renew now (the same command the daily job runs). `renews_as_plan_id` renews into another plan for this
    renewal only: the upgrade or downgrade path."""
    contract = _load(session, principal, contract_id, _RENEW)
    if contract.status not in ("active", "suspended") or contract.cancel_reason:
        raise Conflict("Only an active or suspended membership can be renewed.")
    if _successor(session, contract.id) is not None:
        raise Conflict("This membership has already been renewed.", code="already-renewed")
    successor = _renew(session, contract, _today(session, contract.location_id), data.get("renews_as_plan_id"))
    return contract_view(session, successor)


# --- cancel (MEM-15, MEM-16; ADR 0005 section 6) -----------------------------------------------------------------


def _cancel_plan(session: Session, contract: MembershipContract, effective_on: date) -> dict:
    """What cancelling on `effective_on` (the last day of membership) does to each period."""
    if not contract.start_on <= effective_on <= contract.end_on:
        raise ValidationFailed("The cancel date must fall inside the term.", pointer="/effective_on")
    whole = effective_on == contract.start_on
    void, reverse, current = [], [], None
    for row in _rows(session, contract.id, "scheduled", "withheld", "billed"):
        later = whole or _starts(row) > effective_on
        if row.status == "billed":
            if later:
                reverse.append(row)
            elif row.kind == "dues" and row.service_during.upper > effective_on + _ONE_DAY:
                current = row
        elif later:
            void.append(row)
    proposed = 0
    if current is not None:
        span = current.service_during
        proposed = domain.unused_credit(current.amount_minor, span.lower, span.upper, effective_on)
    return {"void": void, "reverse": reverse, "current": current, "proposed_credit_minor": proposed}


def quote_cancellation(session: Session, principal: Principal, contract_id: UUID, effective_on: date | None) -> dict:
    """Dry run of a cancel: what is voided and reversed, and the pro-rata credit proposed for the period the
    date falls in. The command applies whatever `credit_minor` staff confirm; the default is none (MEM-16)."""
    contract = _load(session, principal, contract_id, _CANCEL)
    effective_on = effective_on or _today(session, contract.location_id)
    plan = _cancel_plan(session, contract, effective_on)
    paid = sum(sum(a for _, a in billing.service.charge_payments(session, row.charge_id)) for row in plan["reverse"])
    return {
        "effective_on": effective_on, "is_full_reversal": effective_on == contract.start_on,
        "periods_voided": [row.id for row in plan["void"]], "periods_reversed": [row.id for row in plan["reverse"]],
        "reversed_minor": sum(row.amount_minor for row in plan["reverse"]), "paid_on_reversed_minor": paid,
        "current_period_id": plan["current"] and plan["current"].id,
        "proposed_credit_minor": plan["proposed_credit_minor"],
        "max_credit_minor": plan["current"].amount_minor if plan["current"] else 0,
    }  # fmt: skip


def _end(
    session: Session, contract: MembershipContract, effective_on: date, plan: dict, *, credit_minor: int = 0
) -> dict[UUID, int]:
    """Apply a cancel plan to the receivables. Returns payment id -> money the reversals released from it and
    that was not re-applied: the client's account credit, which the caller may refund."""
    released: dict[UUID, int] = {}
    for row in plan["void"]:
        row.status, row.cancelled_reason, row.withheld_by_freeze_id, row.pre_freeze = (
            "cancelled",
            "contract_cancelled",
            None,
            None,
        )
    for row in plan["reverse"]:
        for payment_id, amount in billing.service.charge_payments(session, row.charge_id):
            released[payment_id] = released.get(payment_id, 0) + amount
        billing.service.reverse(session, row.charge_id, reason="Membership cancelled")
        row.status, row.cancelled_reason = "cancelled", "contract_cancelled"
    row = plan["current"]
    if credit_minor and row is not None:
        # Partial credit: reverse the period and bill the used part again; money already paid moves across.
        paid = billing.service.charge_payments(session, row.charge_id)
        _unbill(session, row, "Membership cancelled part-way through the period")
        row.amount_minor -= credit_minor
        used = billing.service.post_charge(
            session, client_id=contract.owner_client_id, location_id=contract.location_id,
            description=f"{row.description} (ended {effective_on.isoformat()})", unit_price_minor=row.amount_minor,
            source_context="memberships", source_type="billing_schedule_period", source_id=row.id,
            source_line_no=row.charge_sequence, revenue_category_id=contract.revenue_category_id,
            revenue_on=row.revenue_on,
        )  # fmt: skip
        row.status, row.charge_id, row.billed_at = "billed", used.id, clock.now()
        session.flush()
        if used.total_minor > 0:
            billing.service.create_invoice_for_charges(session, [used.id], origin="system")
        owed = used.total_minor
        for payment_id, amount in paid:
            again = min(amount, owed)
            if again:
                billing.service.allocate(session, payment_id, allocations=[(used.id, again)])
                owed -= again
            if amount > again:
                released[payment_id] = released.get(payment_id, 0) + amount - again
    session.flush()
    return released


def _cancel_successor(
    session: Session, contract: MembershipContract, staff_id: UUID | None, today: date
) -> dict[UUID, int]:
    """An upcoming successor never starts: everything billed for it is reversed. It is detached from the chain
    so the contract can be renewed again later (after an undo, or when staff re-enable renewal)."""
    successor = _successor(session, contract.id)
    if successor is None or successor.status != "upcoming":
        return {}
    successor = _get(session, MembershipContract, successor.id, lock=True)
    released = _end(session, successor, successor.start_on, _cancel_plan(session, successor, successor.start_on))
    successor.end_on_before_cancel, successor.end_on = successor.end_on, successor.start_on
    successor.status, successor.cancelled_on, successor.cancelled_at = "cancelled", successor.start_on, clock.now()
    successor.cancel_reason, successor.cancelled_by_staff_user_id = "other", staff_id
    successor.cancel_remarks, successor.previous_contract_id = "Cancelled with the membership it renewed.", None
    successor.is_auto_renew = False
    audit.record(
        session, _CANCEL, successor, location_id=successor.location_id, changes={"status": ["upcoming", "cancelled"]}
    )
    events.publish(session, ContractCancelled(
        contract_id=successor.id, client_id=successor.owner_client_id, reason="other"), successor.id)  # fmt: skip
    session.flush()
    return released


def _refund(
    session: Session,
    released: dict[UUID, int],
    reason: str,
    idempotency_key: str | None,
    *,
    processed_only: bool = False,
) -> list:
    refunds = []
    for payment_id, amount in sorted(released.items()):
        try:
            refunds.append(billing.service.refund(
                session, payment_id, amount_minor=amount, reason=reason, method="original" if processed_only else None,
                idempotency_key=idempotency_key and f"{idempotency_key}:{payment_id}",
            ))  # fmt: skip
        except ValidationFailed:
            if not processed_only:  # money we never processed cannot go back to a card: it stays account credit
                raise
    return refunds


def cancel_contract(
    session: Session, principal: Principal, contract_id: UUID, data: dict, idempotency_key: str | None = None
) -> dict:
    """Cancel on `effective_on`, the last day of membership (default today).

    On the start date everything billed is reversed (a full un-sell). Later: periods that have not started are
    voided or reversed, and the period the date falls in is credited by `credit_minor` (staff's choice, default
    none; the quote proposes the pro-rata amount). Money that paid reversed items becomes account credit, or is
    refunded when `is_refunded` (which also needs billing.refund.create). A future date schedules the cancel:
    the term is cut now and the daily job closes the contract on the day.
    """
    contract = _load(session, principal, contract_id, _CANCEL)
    _require_remark(session, "cancel", data.get("remarks"))
    today = _today(session, contract.location_id)
    if contract.status not in LIVE or contract.cancel_reason:
        raise Conflict("This membership has already ended or is already being cancelled.")
    effective_on = contract.start_on if contract.status == "upcoming" else data.get("effective_on") or today
    credit = data.get("credit_minor") or 0
    plan = _cancel_plan(session, contract, effective_on)
    if effective_on > today and contract.status != "upcoming" and (credit or contract.status == "frozen"):
        raise ValidationFailed(
            "A scheduled cancel cannot carry a credit, and a frozen membership cancels today or earlier.",
            pointer="/effective_on",
        )
    if credit and (plan["current"] is None or credit > plan["current"].amount_minor):
        raise ValidationFailed("The credit cannot exceed the current period's amount.", pointer="/credit_minor")
    if data.get("is_refunded"):
        authorize(principal, "billing.refund.create", location_id=contract.location_id)
    staff_id = _staff_id(principal)
    released = _end(session, contract, effective_on, plan, credit_minor=credit)
    for payment_id, amount in _cancel_successor(session, contract, staff_id, today).items():
        released[payment_id] = released.get(payment_id, 0) + amount
    was = contract.status
    contract.end_on_before_cancel, contract.end_on = contract.end_on, effective_on
    contract.cancel_reason, contract.cancel_remarks = data["reason"], data.get("remarks")
    contract.cancelled_by_staff_user_id = staff_id
    if contract.is_auto_renew:
        contract.is_auto_renew, contract.auto_renew_disabled_by, contract.auto_renew_disabled_at = (
            False,
            "staff",
            clock.now(),
        )
    contract.renew_on = domain.renew_on(contract.end_on, contract.auto_renew_lead_count, contract.auto_renew_lead_unit)
    cancel_packages = data.get("cancel_bundled_packages")
    if cancel_packages is None:
        cancel_packages = settings_row(session).is_addon_package_cancelled_with_contract
    if effective_on <= today or was == "upcoming":
        contract.status, contract.cancelled_on, contract.cancelled_at = "cancelled", effective_on, clock.now()
        events.publish(session, ContractCancelled(
            contract_id=contract.id, client_id=contract.owner_client_id, reason=contract.cancel_reason,
            cancel_packages=cancel_packages), contract.id)  # fmt: skip
    contract.version += 1
    audit.record(
        session, _CANCEL, contract, location_id=contract.location_id, reason=data.get("remarks"),
        changes={"status": [was, contract.status], "effective_on": [None, str(effective_on)],
                 "cancel_reason": [None, contract.cancel_reason], "credit_minor": [None, credit]},
    )  # fmt: skip
    session.flush()
    refunds = _refund(session, released, "Membership cancelled", idempotency_key) if data.get("is_refunded") else []
    return contract_view(session, contract) | {
        "released_minor": sum(released.values()), "credit_minor": credit,
        "refunds": [{"refund_id": r.id, "payment_id": r.payment_id, "amount_minor": r.amount_minor, "status": r.status} for r in refunds],
    }  # fmt: skip


def undo_cancel(session: Session, principal: Principal, contract_id: UUID) -> dict:
    """Bring a cancelled (or cancel-scheduled) contract back with its original end date. Periods the cancel
    voided or reversed return to the schedule and are billed afresh; nothing is un-reversed, and a credit that
    was given stays given. Refused when the client holds another membership in those dates."""
    contract = _load(session, principal, contract_id, _CANCEL)
    if not contract.cancel_reason or contract.end_on_before_cancel is None:
        raise Conflict("This membership is not cancelled.")
    contract.end_on, contract.end_on_before_cancel = contract.end_on_before_cancel, None
    if contract.status == "cancelled":
        contract.status = "upcoming"  # not terminal; _converge puts it where the dates say
    contract.cancelled_on = contract.cancel_reason = contract.cancel_remarks = contract.cancelled_at = None
    contract.cancelled_by_staff_user_id = None
    _check_overlap(session, contract)
    contract.renew_on = domain.renew_on(contract.end_on, contract.auto_renew_lead_count, contract.auto_renew_lead_unit)
    for row in _rows(session, contract.id, "cancelled"):
        if row.cancelled_reason == "contract_cancelled":
            if row.charge_id is not None:
                row.charge_id, row.billed_at, row.charge_sequence = None, None, row.charge_sequence + 1
            row.status, row.cancelled_reason = "scheduled", None
    contract.version += 1
    audit.record(session, "memberships.contract.undo_cancel", contract, location_id=contract.location_id,
                 changes={"end_on": [None, str(contract.end_on)]})  # fmt: skip
    session.flush()
    _converge(session, contract, _today(session, contract.location_id), reason="undo_cancel")
    return contract_view(session, contract)


# --- sharing (MEM-17, FAM-04) ------------------------------------------------------------------------------------


def list_shares(session: Session, principal: Principal, contract_id: UUID) -> list[MembershipShare]:
    contract = _load(session, principal, contract_id, _READ)
    stmt = select(MembershipShare).where(MembershipShare.membership_contract_id == contract.id)
    return list(session.scalars(stmt.order_by(MembershipShare.id)))


def add_share(session: Session, principal: Principal, contract_id: UUID, client_id: UUID) -> MembershipShare:
    """Cover another client, related or not, with this contract. Billing stays with the owner."""
    contract = _load(session, principal, contract_id, _SHARE)
    if contract.status not in LIVE:
        raise Conflict("A membership that has ended cannot be shared.")
    share = _add_share(session, contract, client_id, _staff_id(principal))
    audit.record(
        session, _SHARE, contract, location_id=contract.location_id, changes={"shared_with": [None, str(client_id)]}
    )
    return share


def revoke_share(session: Session, principal: Principal, contract_id: UUID, share_id: UUID) -> None:
    contract = _load(session, principal, contract_id, _SHARE)
    share = _get(session, MembershipShare, share_id)
    if share.membership_contract_id != contract.id:
        raise NotFound()
    if share.revoked_at is None:
        share.revoked_at, share.revoked_by_staff_user_id = clock.now(), _staff_id(principal)
        audit.record(session, _SHARE, contract, location_id=contract.location_id,
                     changes={"shared_with": [str(share.client_id), None]})  # fmt: skip
    session.flush()


# --- entitlement and visits (MEM-19, MEM-20): the interface for access, packages and rentals ---------------------


def _covering(session: Session, client_id: UUID, on: date | None) -> tuple[MembershipContract, str, str] | None:
    """The contract that covers the client (as owner or sharer) with its effective status and how it covers."""
    c = MembershipContract
    shared = select(MembershipShare.membership_contract_id).where(
        MembershipShare.client_id == client_id, MembershipShare.revoked_at.is_(None)
    )
    stmt = select(c).where(c.status.in_(LIVE), or_(c.owner_client_id == client_id, c.id.in_(shared)))
    order = {"active": 0, "suspended": 1, "frozen": 2, "upcoming": 3}
    best, best_rank = None, None
    for contract in session.scalars(stmt.order_by(c.start_on, c.id)):
        status = effective_status(session, contract, on or _today(session, contract.location_id))
        if status not in order:
            continue
        # Same status: a contract with visits left beats an earlier used-up pass (an owner pass and a share).
        used_up = contract.max_visits_count is not None and contract.visits_used_count >= contract.max_visits_count
        rank = (order[status], used_up)
        if best_rank is None or rank < best_rank:
            best, best_rank = (contract, status, "owner" if contract.owner_client_id == client_id else "share"), rank
    return best


def eligibility(session: Session, client_id: UUID, on: date | None = None) -> dict:
    """Whether the client is a member on a date (default: today at the contract's location), from the pure
    status function, so it is right even when the daily job is late. Internal. `reason` is None when entry is
    allowed, else frozen | suspended | upcoming | depleted | daily_limit_reached | none."""
    found = _covering(session, client_id, on)
    if found is None:
        return {"client_id": client_id, "is_member": False, "status": "none", "reason": "none", "contract_id": None}
    contract, status, via = found
    reason = None if status == "active" else status
    remaining = (
        None if contract.max_visits_count is None else max(contract.max_visits_count - contract.visits_used_count, 0)
    )
    if reason is None and remaining == 0:
        reason = "depleted"
    elif (
        reason is None and settings_row(session).is_daily_visit_limit_enabled and contract.max_visits_count is not None
    ):
        today = on or _today(session, contract.location_id)
        counted = select(MembershipVisit.id).where(
            MembershipVisit.membership_contract_id == contract.id, MembershipVisit.client_id == client_id,
            MembershipVisit.local_on == today, MembershipVisit.is_counted,
        )  # fmt: skip
        if session.scalar(counted.limit(1)) is not None:
            reason = "daily_limit_reached"
    return {
        "client_id": client_id, "is_member": status == "active", "status": status, "reason": reason,
        "contract_id": contract.id, "via": via, "membership_name": contract.name,
        "membership_type_id": contract.membership_type_id, "end_on": contract.end_on,
        "max_visits_count": contract.max_visits_count, "visits_used_count": contract.visits_used_count,
        "visits_remaining_count": remaining,
    }  # fmt: skip


def is_member(session: Session, client_id: UUID, on: date | None = None) -> bool:
    """Holds an active membership, as owner or through a share. Internal (member-only pricing and plans)."""
    return eligibility(session, client_id, on)["is_member"]


def member_on(session: Session, client_id: UUID, on: date) -> dict | None:
    """Internal (no principal): the contract that made the client a member on the date `on`, for pricing what
    happens on that date. Unlike `eligibility` (today's standing) it also answers for a past date a since-cancelled
    or expired contract covered (arrears billing), and treats an auto-renewing live contract as covering past its
    `end_on` until it is cancelled or a renewal fails (the failed renewal ends it, and later dates are not covered).
    Freezes, suspensions and an unmet activation gate still exclude a date. Shares count while not revoked.
    A contract cancelled on or before its start date was un-sold (everything billed reversed): it never made the
    client a member. Returns {"contract_id", "membership_type_id"} or None."""
    c = MembershipContract
    shared = select(MembershipShare.membership_contract_id).where(
        MembershipShare.client_id == client_id, MembershipShare.revoked_at.is_(None)
    )
    stmt = select(c).where(c.start_on <= on, or_(c.owner_client_id == client_id, c.id.in_(shared)))
    for contract in session.scalars(stmt.order_by(c.start_on, c.id)):
        if contract.cancel_reason and contract.end_on <= contract.start_on:
            continue  # un-sold, not a one-day membership
        renewing = contract.is_auto_renew and contract.status in LIVE and not contract.cancel_reason
        end = date.max if renewing else contract.end_on
        if on > end:
            continue
        freezes, suspensions = _spans(session, contract.id)
        status = domain.effective_status(
            contract.status if contract.status in LIVE else "active", contract.start_on, end,
            [(f.during.lower, f.during.upper) for f in freezes], [(s.during.lower, s.during.upper) for s in suspensions],
            on, is_gated=contract.status == "upcoming" and _is_gated(session, contract),
        )  # fmt: skip
        if status == "active":
            return {"contract_id": contract.id, "membership_type_id": contract.membership_type_id}
    return None


def list_standings(session: Session, principal: Principal, client_ids: list[UUID]) -> list[dict]:
    out = []
    for client_id in client_ids:
        try:
            clients.service.load(session, principal, client_id, _READ)
        except NotFound:
            continue
        out.append(eligibility(session, client_id))
    return out


def record_visit(session: Session, *, client_id: UUID, check_in_id: UUID, location_id: UUID) -> dict:
    """Count a granted check-in against the covering contract (MEM-20). Internal: `access` calls it once per
    check-in, and a repeat with the same check_in_id changes nothing. With the tenant's daily rule on, a
    client's second entry on the same local day is recorded but not counted."""
    seen = session.scalar(select(MembershipVisit).where(MembershipVisit.check_in_id == check_in_id))
    if seen is None:
        found = _covering(session, client_id, None)
        if found is None or found[1] != "active":
            return {"contract_id": None, "is_counted": False}
        contract = _get(session, MembershipContract, found[0].id, lock=True)
        local_on = _today(session, location_id)
        counted = True
        if settings_row(session).is_daily_visit_limit_enabled:
            earlier = select(MembershipVisit.id).where(
                MembershipVisit.membership_contract_id == contract.id, MembershipVisit.client_id == client_id,
                MembershipVisit.local_on == local_on, MembershipVisit.is_counted,
            )  # fmt: skip
            counted = session.scalar(earlier.limit(1)) is None
        # A staff override past a used-up limit is recorded, never counted beyond the cap.
        counted = counted and (
            contract.max_visits_count is None or contract.visits_used_count < contract.max_visits_count
        )
        seen = MembershipVisit(
            membership_contract_id=contract.id, client_id=client_id, check_in_id=check_in_id, location_id=location_id,
            visited_at=clock.now(), local_on=local_on, is_counted=counted,
        )  # fmt: skip
        session.add(seen)
        if counted:
            contract.visits_used_count += 1
        session.flush()
    return {"contract_id": seen.membership_contract_id, "is_counted": seen.is_counted}


def list_visits(session: Session, principal: Principal, contract_id: UUID, query: ListQuery) -> dict:
    contract = _load(session, principal, contract_id, _READ)
    stmt = select(MembershipVisit).where(MembershipVisit.membership_contract_id == contract.id)
    return paginate(
        session, stmt, query, id_column=MembershipVisit.id, sort_fields={"visited_at": MembershipVisit.visited_at},
        default_sort="-visited_at", filter_fields={"client_id": MembershipVisit.client_id, "local_on": MembershipVisit.local_on},
    )  # fmt: skip


def adjust_visits(session: Session, principal: Principal, contract_id: UUID, data: dict) -> dict:
    """Correct the visit count by a signed delta, with a reason."""
    contract = _load(session, principal, contract_id, _VISITS)
    was = contract.visits_used_count
    if was + data["delta"] < 0:
        raise ValidationFailed("The visit count cannot go below zero.", pointer="/delta")
    contract.visits_used_count = was + data["delta"]
    audit.record(session, _VISITS, contract, location_id=contract.location_id, reason=data["reason"],
                 changes={"visits_used_count": [was, contract.visits_used_count]})  # fmt: skip
    session.flush()
    return contract_view(session, contract)


# --- derived client alerts (CLI-20) ------------------------------------------------------------------------------

EXPIRING_SOON_DAYS = 14  # assumption (README): how early "membership expiring" shows


def client_alerts(session: Session, principal: Principal, client_id: UUID) -> list[dict]:
    """System alerts on a client, computed on read from their owners: balance due (billing), membership expiring or
    expired (here), waiver missing (documents). Here and not in `clients`, which may not call those contexts
    (overview section 2). Staff only; each alert shows only to a caller holding its owning context's read key."""
    client = clients.service.load(session, principal, client_id, "clients.client.read")
    today = platform.service.location_today(session, client.home_location_id)

    def reaches(key: str) -> bool:  # the section's own key and reach (own = their clients), not mere possession
        try:
            clients.service.load(session, principal, client_id, key)
        except (NotFound, PermissionDenied):
            return False
        return True

    out = []
    if reaches("billing.invoice.read"):
        money = billing.documents.billing_summary(session, client.id)
        due = money["open_balance_minor"] + money["uninvoiced_minor"]
        if due > 0:
            late = money["past_due_minor"] > 0
            out.append({"code": "balance_due", "severity": "danger" if late else "warning", "amount_minor": due,
                        "on": money["oldest_past_due_on"], "message": "Past-due balance" if late else "Balance due"})  # fmt: skip
    if reaches(_READ):
        standing = eligibility(session, client.id, today)
        end_on = standing.get("end_on")
        if standing["contract_id"] is not None:
            if end_on is not None and end_on <= today + timedelta(days=EXPIRING_SOON_DAYS):
                out.append({"code": "membership_expiring", "severity": "warning", "on": end_on, "amount_minor": None,
                            "message": f"{standing['membership_name']} ends {end_on.isoformat()}"})  # fmt: skip
        else:
            c = MembershipContract
            last = session.scalar(
                select(c)
                .where(c.owner_client_id == client.id, c.status == "expired")
                .order_by(c.end_on.desc())
                .limit(1)
            )
            if last is not None:
                out.append({"code": "membership_expired", "severity": "warning", "on": last.end_on, "amount_minor": None,
                            "message": f"{last.name} expired"})  # fmt: skip
    if reaches("documents.document.read"):
        rules = documents.service.settings_row(session)
        required = rules.is_waiver_required_for_check_in or rules.is_waiver_required_for_booking
        if required and not documents.service.has_valid_waiver(session, client.id):
            out.append({"code": "waiver_missing", "severity": "danger", "on": None, "amount_minor": None,
                        "message": "No valid waiver on file"})  # fmt: skip
    return out


# --- portal (MEM-10, MEM-18) -------------------------------------------------------------------------------------


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


def portal_list_contracts(session: Session, principal: Principal, client_id: UUID | None) -> list[dict]:
    """Memberships the acting client owns or is covered by."""
    subject = _portal_client(session, principal, client_id)
    c = MembershipContract
    shared = select(MembershipShare.membership_contract_id).where(
        MembershipShare.client_id == subject, MembershipShare.revoked_at.is_(None)
    )
    stmt = select(c).where(or_(c.owner_client_id == subject, c.id.in_(shared))).order_by(c.start_on.desc(), c.id)
    return [contract_view(session, row) for row in session.scalars(stmt.limit(100))]


def portal_standing(session: Session, principal: Principal, client_id: UUID | None) -> dict:
    return eligibility(session, _portal_client(session, principal, client_id))


def public_list_plans(session: Session, query: ListQuery) -> dict:
    """Plans published for online sale (MEM-09): the anonymous price list."""
    p = MembershipPlan
    page = paginate(
        session, select(p).where(p.is_active, p.is_sold_online), query, id_column=p.id,
        sort_fields={"sort_order": p.sort_order, "name": p.name}, default_sort="sort_order",
        filter_fields={"membership_type_id": p.membership_type_id}, search=(p.name,),
    )  # fmt: skip
    return page | {"data": [plan_view(session, plan) for plan in page["data"]]}


def _portal_sale(session: Session, principal: Principal, data: dict) -> dict:
    """The sale a portal caller may ask for. The server decides autopay (the plan, else the billing setting for
    online sales, BIL-17) and the start date stays within ONLINE_START_WINDOW_DAYS from today."""
    subject = _portal_client(session, principal, data.get("client_id"), "buy")
    start_on = data.get("start_on")
    if start_on is not None:
        try:
            today = _today(session, data["location_id"])
        except NotFound:
            raise ValidationFailed("Unknown location.", pointer="/location_id") from None
        if not today <= start_on <= today + timedelta(days=ONLINE_START_WINDOW_DAYS):
            raise ValidationFailed(
                f"An online membership starts within {ONLINE_START_WINDOW_DAYS} days from today.",
                pointer="/start_on",
            )  # fmt: skip
    keys = ("location_id", "membership_plan_id", "start_on", "proration_tail", "is_auto_renew")
    return {key: data.get(key) for key in keys} | {"client_id": subject}


def portal_quote(session: Session, principal: Principal, data: dict) -> dict:
    return quote_contract(session, principal, _portal_sale(session, principal, data), "portal")


def portal_buy(session: Session, principal: Principal, data: dict, idempotency_key: str) -> dict:
    """Buy a membership online, for oneself or a client one may buy for (MEM-09). Whatever is due now must be
    paid by card or bank debit and go through, or nothing is sold; with nothing due now, the card or bank
    account is stored as the owner's autopay method for what falls due later. A plan whose document is
    enforced online leaves the contract `upcoming` until that document is accepted in the portal (MEM-08)."""
    sale = _portal_sale(session, principal, data)
    clients.terms.acknowledge(session, client_id=sale["client_id"], terms_version_id=data.get("terms_version_id"),
                              sale_kind="membership", subject_id=sale["membership_plan_id"])  # fmt: skip
    contract, invoice = _sell(session, principal, sale, "portal")
    token, tender = data.get("method_token"), data.get("tender_kind") or "card"
    mode = settings_row(session).online_card_save_mode
    paying_now = invoice is not None and invoice.balance_minor > 0
    # MEM-05: keep the card that pays now (with nothing due now checkout always stores it). An autopay contract
    # always keeps it, or its later dues would have no method to collect from. The processor saves it with the
    # charge (save during payment), so a timeout stays recoverable on retry.
    save = (
        token is not None
        and tender == "card"
        and paying_now
        and (mode == "always" or contract.is_autopay or (mode == "ask" and bool(data.get("save_method"))))
    )
    payment = billing.checkout.secure_online_checkout(
        session, client_id=contract.owner_client_id, location_id=contract.location_id,
        total_minor=sum(row.amount_minor for row in _rows(session, contract.id)), invoice=invoice,
        idempotency_key=idempotency_key, method_token=token, tender_kind=tender,
        payment_method_id=data.get("payment_method_id"), must_pay_now=False, coupon_code=data.get("coupon_code"),
        save_method=save, save_as_autopay=True if contract.is_autopay else None,
    )  # fmt: skip
    return _sale_view(session, contract, invoice, payment)


def portal_disable_auto_renew(session: Session, principal: Principal, contract_id: UUID) -> dict:
    """Click-to-cancel (MEM-18): one way from the portal, whatever the sale channel. Access runs to the end
    date and nothing for the current term is refunded. A successor already waiting is cancelled; what was paid
    for it by card or bank debit goes back to that method, other money stays as account credit."""
    contract = _get(session, MembershipContract, contract_id, lock=True)
    _portal_client(session, principal, contract.owner_client_id, "edit_profile")
    if contract.status not in LIVE:
        raise Conflict("This membership has already ended.")
    today = _today(session, contract.location_id)
    released = _cancel_successor(session, contract, None, today)
    if contract.is_auto_renew:
        contract.is_auto_renew, contract.auto_renew_disabled_by, contract.auto_renew_disabled_at = (
            False,
            "client",
            clock.now(),
        )
        contract.version += 1
        audit.record(session, "memberships.contract.disable_auto_renew", contract, location_id=contract.location_id,
                     changes={"is_auto_renew": [True, False]})  # fmt: skip
        owner = clients.service.get(session, contract.owner_client_id)
        if owner.primary_email:
            notifications.send(session, "memberships.auto_renew_disabled", owner.primary_email, {
                "app": platform.service.get_tenant(session).name, "name": owner.first_name,
                "membership": contract.name, "end_on": contract.end_on.isoformat(),
            })  # fmt: skip
    session.flush()
    _refund(session, released, "Renewal cancelled by the member", f"optout:{contract.id}", processed_only=True)
    return contract_view(session, contract)


# --- the daily job (ADR 0005 section 8) --------------------------------------------------------------------------


def _due_for_renewal(session: Session, contract: MembershipContract, today: date) -> bool:
    return (
        contract.is_auto_renew and contract.status in ("active", "suspended") and not contract.cancel_reason
        and contract.renew_on is not None and contract.renew_on <= today
        and _successor(session, contract.id) is None
    )  # fmt: skip


def run_daily(session: Session) -> dict:
    """Lifecycle, renewal and billing for every live contract, in that order, each contract in its own
    savepoint so one failure never blocks the rest. "Today" is the wall date at the contract's location, and
    everything is selected with "on or before today", so a missed run is caught up by the next one. Safe to run
    any number of times: transitions converge, a contract has one successor (unique index), and a period is
    charged once (billing's origin key)."""
    result = {"transitions": 0, "renewed": 0, "periods_billed": 0, "failed": []}
    c = MembershipContract
    todays: dict[UUID, date] = {}
    for contract_id in list(session.scalars(select(c.id).where(c.status.in_(LIVE)).order_by(c.start_on, c.id))):
        try:
            with session.begin_nested():
                contract = _get(session, c, contract_id, lock=True)
                today = todays.get(contract.location_id) or todays.setdefault(
                    contract.location_id, _today(session, contract.location_id)
                )
                result["transitions"] += _converge(session, contract, today)
                if _due_for_renewal(session, contract, today):
                    _renew(session, contract, today)
                    result["renewed"] += 1
                if contract.status in ("upcoming", "active", "suspended") and contract.invoice_mode in (
                    "per_period",
                    "single",
                ):
                    rows = [row for row in _rows(session, contract.id, "scheduled") if row.bill_on <= today]
                    if rows:
                        _bill_rows(session, contract, rows, today)
                        audit.record(session, "memberships.billing_schedule.bill", contract,
                                     location_id=contract.location_id, changes={"periods_billed": [None, len(rows)]})  # fmt: skip
                        result["periods_billed"] += len(rows)
        except (DomainError, IntegrityError) as exc:
            result["failed"].append({"contract_id": str(contract_id), "error": getattr(exc, "code", "integrity-error")})
    return result


@tenant_actor
def run_membership_day(session: Session) -> dict:
    """The queued form of run_daily, one message per tenant. Nothing schedules it yet (the kernel has no
    scheduler): enqueue it daily per tenant, after each location's `membership_renewal_run_time`. Until then
    entitlement is still exact, because reads use the date-derived status; only stored statuses, successors and
    invoices wait for the run."""
    return run_daily(session)


# --- merge and data-subject handlers (CLI-13, security-baseline 4.3) ---------------------------------------------


def _live_owned(session: Session, client_id: UUID) -> list[MembershipContract]:
    stmt = select(MembershipContract).where(
        MembershipContract.owner_client_id == client_id, MembershipContract.status.in_(LIVE)
    )
    return list(session.scalars(stmt))


def _merge_precheck(session: Session, loser_id: UUID, survivor_id: UUID) -> list[dict]:
    """A merge that would give one client two live memberships in the same dates is refused up front (ADR 0005
    reconciliation: no merge_lane): staff end or re-date one first."""
    for mine in _live_owned(session, loser_id):
        for theirs in _live_owned(session, survivor_id):
            if mine.start_on <= theirs.end_on and theirs.start_on <= mine.end_on:
                return [{"code": "membership-overlap", "detail": "Both clients hold a membership in the same dates."}]
    return []


def _repoint(session: Session, loser_id: UUID, survivor_id: UUID) -> None:
    c, share = MembershipContract, MembershipShare
    session.execute(update(c).where(c.owner_client_id == loser_id).values(owner_client_id=survivor_id))
    session.execute(update(c).where(c.referred_by_client_id == loser_id).values(referred_by_client_id=survivor_id))
    session.execute(update(MembershipVisit).where(MembershipVisit.client_id == loser_id).values(client_id=survivor_id))
    for row in session.scalars(select(share).where(share.client_id == loser_id)):
        duplicate = session.scalar(select(share.id).where(
            share.membership_contract_id == row.membership_contract_id, share.client_id == survivor_id,
            share.revoked_at.is_(None),
        ))  # fmt: skip
        if row.revoked_at is None and duplicate is not None:
            row.revoked_at = clock.now()  # the survivor already holds this share
        session.flush()
        row.client_id = survivor_id
    session.flush()
    own = select(c.owner_client_id).where(c.id == share.membership_contract_id).scalar_subquery()
    session.execute(  # a share with oneself ends
        update(share).where(share.client_id == survivor_id, share.revoked_at.is_(None), share.client_id == own)
        .values(revoked_at=clock.now())
    )  # fmt: skip


def _export(session: Session, client_id: UUID) -> dict:
    rows = session.scalars(select(MembershipContract).where(MembershipContract.owner_client_id == client_id))
    return {"memberships": [
        {"name": r.name, "status": r.status, "start_on": r.start_on.isoformat(), "end_on": r.end_on.isoformat(),
         "term_fee_minor": r.term_fee_minor, "visits_used_count": r.visits_used_count}
        for r in rows
    ]}  # fmt: skip


def _erase_precheck(session: Session, client_id: UUID) -> list[dict]:
    if _live_owned(session, client_id):
        return [{"code": "live-membership", "detail": "The client holds a membership that has not ended."}]
    return []


def _erase(session: Session, client_id: UUID) -> dict:
    """Contracts are financial records and stay, without their free text; shares held by the client end."""
    c, share = MembershipContract, MembershipShare
    cleared = session.execute(
        update(c).where(c.owner_client_id == client_id)
        .values(internal_notes=None, cancel_remarks=None, renewal_remark=None, renewal_description=None)
    ).rowcount  # fmt: skip
    session.execute(update(c).where(c.referred_by_client_id == client_id).values(referred_by_client_id=None))
    revoked = session.execute(
        update(share).where(share.client_id == client_id, share.revoked_at.is_(None)).values(revoked_at=clock.now())
    ).rowcount
    return {"retained_contracts": cleared, "revoked_shares": revoked}


_TABLES = ("membership_contract", "membership_share", "membership_visit")
clients.merge.register_merge_handler("memberships", tables=_TABLES, repoint=_repoint, precheck=_merge_precheck)
platform.privacy.register_subject_handler(
    "memberships", tables=_TABLES, export=_export, erase=_erase, precheck=_erase_precheck
)


# --- views and event entry points ------------------------------------------------------------------------------


def span_view(row) -> dict:
    """A period, freeze or suspension with its date range as inclusive start_on / end_on."""
    data = _columns(row)
    span = data.pop("during" if "during" in data else "service_during")
    return data | {
        "start_on": None if span is None else span.lower,
        "end_on": None if span is None or span.upper is None else span.upper - _ONE_DAY,
    }


def document_accepted(session: Session, client_document_id: UUID) -> int:
    """`documents.document.accepted`: a contract that was waiting for this document may now start (MEM-08)."""
    c = MembershipContract
    waiting = list(
        session.scalars(select(c.id).where(c.client_document_id == client_document_id, c.status == "upcoming"))
    )
    for contract_id in waiting:
        contract = _get(session, c, contract_id, lock=True)
        _converge(session, contract, _today(session, contract.location_id), reason="document_accepted")
    return len(waiting)


def status_of(session: Session, contract_id: UUID, on: date | None = None) -> str:
    """The date-derived status of one contract. Internal: `packages` asks before spending a bundled package."""
    contract = _get(session, MembershipContract, contract_id)
    return effective_status(session, contract, on or _today(session, contract.location_id))


def addon_grants(session: Session, contract_id: UUID) -> dict:
    """Who and what a contract's bundled packages are for. Internal: read by the packages handler for
    `memberships.contract.activated` (memberships never calls packages)."""
    contract = _get(session, MembershipContract, contract_id)
    addons = session.scalars(
        select(MembershipContractAddon).where(
            MembershipContractAddon.membership_contract_id == contract.id,
            MembershipContractAddon.package_plan_id.is_not(None),
        ).order_by(MembershipContractAddon.id)
    )  # fmt: skip
    return {
        "client_id": contract.owner_client_id, "location_id": contract.location_id, "start_on": contract.start_on,
        "is_live": contract.status in ("active", "frozen", "suspended"),
        "addons": [{"id": a.id, "package_plan_id": a.package_plan_id, "quantity": a.quantity} for a in addons],
    }  # fmt: skip


# --- internal: payroll facts (staff, STF-10) ---------------------------------------------------------------------


def seller_periods(session: Session, staff_user_id: UUID, starts_on: date, ends_on: date, location_ids=None) -> list:
    """Billed periods, with a bill date in [starts_on, ends_on], of contracts a staff user sold: the facts a
    membership-sale commission needs. `is_first` marks the first bill of a contract that is not a renewal."""
    p, c = BillingSchedulePeriod, MembershipContract
    inner = aliased(BillingSchedulePeriod)
    first = select(func.min(inner.sequence_number)).where(inner.membership_contract_id == c.id).scalar_subquery()
    stmt = (
        select(p.id, p.bill_on, p.sequence_number == first, c.id, c.location_id, c.membership_type_id, c.name,
               c.previous_contract_id)
        .join(c, c.id == p.membership_contract_id)
        .where(c.sold_by_staff_user_id == staff_user_id, p.charge_id.is_not(None), p.bill_on >= starts_on,
               p.bill_on <= ends_on)
    )  # fmt: skip
    if location_ids is not None:
        stmt = stmt.where(c.location_id.in_(list(location_ids)))
    return [
        {"period_id": r[0], "bill_on": r[1], "is_first": bool(r[2]) and r[7] is None, "contract_id": r[3],
         "location_id": r[4], "membership_type_id": r[5], "name": r[6]}
        for r in session.execute(stmt.order_by(p.bill_on, p.id))
    ]  # fmt: skip


# --- suspension for non-payment (MEM-14, owner decision Q13) ------------------------------------------------------

_AUTO_REMARK = "Suspended automatically: invoice past due"
_LIFT_REMARK = "Lifted automatically: the invoice was settled"


def _open_auto(session: Session, *where) -> list[MembershipSuspension]:
    """Automatic suspensions still in force somewhere: not removed and not ended before yesterday (any
    location's day), so lifted or finished ones are not rescanned and relocked every hour."""
    s = MembershipSuspension
    since = platform.service.earliest_today(session) - _ONE_DAY
    return list(session.scalars(select(s).where(
        s.past_due_invoice_id.is_not(None), s.removed_at.is_(None),
        or_(func.upper(s.during).is_(None), func.upper(s.during) > since), *where,
    )))  # fmt: skip


def _lift_settled(session: Session, suspensions: list[MembershipSuspension], failed: list | None = None) -> int:
    """Lift automatic suspensions whose invoice no longer owes (paid, reversed or voided), each in its own
    savepoint so one refusal does not stop the others (it lands in `failed`)."""
    owing = billing.collections.still_owing(session, [row.past_due_invoice_id for row in suspensions])
    lifted = 0
    for suspension in suspensions:
        if suspension.past_due_invoice_id in owing:
            continue
        try:
            with session.begin_nested():
                contract = _get(session, MembershipContract, suspension.membership_contract_id, lock=True)
                session.refresh(suspension)  # loaded before the contract lock: staff may have changed it since
                today = _today(session, contract.location_id)
                if suspension.removed_at is not None or (suspension.during.upper and suspension.during.upper <= today):
                    continue
                _lift(session, contract, suspension, today, staff_id=None, remarks=_LIFT_REMARK)
                contract.version += 1
                audit.record(session, _SUSPEND, contract, location_id=contract.location_id, reason=_LIFT_REMARK,
                             changes={"suspension_removed": [None, str(suspension.id)]})  # fmt: skip
                _converge(session, contract, today)
                lifted += 1
        except (DomainError, IntegrityError) as exc:
            if failed is None:
                raise
            failed.append({"suspension_id": str(suspension.id), "error": getattr(exc, "code", "integrity-error")})
    return lifted


def _suspend_for(session: Session, contract: MembershipContract, invoice_id: UUID, today: date) -> bool:
    """Suspend from today until the next freeze or suspension already planned (or open-ended)."""
    freezes, suspensions = _spans(session, contract.id)
    spans = [row.during for row in (*freezes, *suspensions)]
    if any(today in span for span in spans):
        return False
    later = [span.lower for span in spans if span.lower > today]
    suspension = MembershipSuspension(
        membership_contract_id=contract.id, during=_range(today, min(later) - _ONE_DAY if later else None),
        remarks=_AUTO_REMARK, past_due_invoice_id=invoice_id,
    )  # fmt: skip
    session.add(suspension)
    session.flush()
    contract.version += 1
    audit.record(
        session, _SUSPEND, contract, location_id=contract.location_id, reason=_AUTO_REMARK,
        changes={"suspension": [None, [str(today), None]], "past_due_invoice_id": [None, str(invoice_id)]},
    )  # fmt: skip
    _converge(session, contract, today)
    return True


def sweep_past_due(session: Session) -> dict:
    """The daily rule (off unless `membership_suspend_after_days` is set in billing settings): an active
    membership with an invoice for it past due by that many days on the location's day is suspended (access
    denied, dues keep billing), and the suspension is lifted once that invoice is settled. One automatic
    suspension per contract and invoice, ever (unique index): once lifted, by payment or by staff, that invoice
    never suspends the contract again; another overdue invoice can. Each contract in its own savepoint."""
    result = {"suspended": 0, "lifted": 0, "failed": []}
    result["lifted"] = _lift_settled(session, _open_auto(session), result["failed"])
    if not billing.collections.is_suspension_rule_on(session):
        return result
    c = MembershipContract
    for contract_id in list(session.scalars(select(c.id).where(c.status == "active", c.cancel_reason.is_(None)))):
        try:
            with session.begin_nested():
                contract = _get(session, c, contract_id, lock=True)
                after_days = billing.catalogue.settings_for(session, contract.location_id).membership_suspend_after_days
                if not after_days or contract.status != "active":
                    continue
                today = _today(session, contract.location_id)
                charge_ids = [row.charge_id for row in _rows(session, contract.id, "billed")]
                overdue = billing.collections.unpaid_past_due(
                    session, charge_ids, since_on_or_before=today - timedelta(days=after_days)
                )
                tried = set(session.scalars(select(MembershipSuspension.past_due_invoice_id).where(
                    MembershipSuspension.membership_contract_id == contract.id,
                    MembershipSuspension.past_due_invoice_id.is_not(None),
                )))  # fmt: skip
                invoice_id = next((i for i in overdue if i not in tried), None)
                if invoice_id is not None and _suspend_for(session, contract, invoice_id, today):
                    result["suspended"] += 1
        except (DomainError, IntegrityError) as exc:
            result["failed"].append({"contract_id": str(contract_id), "error": getattr(exc, "code", "integrity-error")})
    return result


def invoice_settled(session: Session, invoice_id: UUID) -> int:
    """Lift, now, the automatic suspensions an invoice caused once it is paid or voided (event handler)."""
    rows = _open_auto(session, MembershipSuspension.past_due_invoice_id == invoice_id)
    return _lift_settled(session, rows) if rows else 0


@tenant_actor
def suspend_past_due_memberships(session: Session) -> dict:
    """The hourly job behind the non-payment rule (scheduler); each location acts on its own day."""
    return sweep_past_due(session)
