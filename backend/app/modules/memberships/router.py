"""memberships HTTP surface (openapi-people.yaml, tag memberships): staff and portal routes.

Differences from the YAML, by design. Path ids are named `membership_plan_id` and `membership_share_id` (the YAML's
`plan_id` and `share_id` also name package ids, and the generated isolation tests key on the name). GET operation
ids start with get/list (a kernel rule for SameSite=Lax), so the portal reads are `listPortalMembershipContracts`
and `getPortalMembershipStanding`. Added: `listUpcomingMembershipRenewals` and `repriceMembershipContract`.
Sub-resources that are always small (schedule, freezes, suspensions, shares, history) return plain arrays.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.orm import Session

from app.core.api import TxRoute, camel_id
from app.core.auth.deps import Ctx, current_ctx, public_session, require
from app.core.errors import ValidationFailed
from app.core.idempotency import KEY_PATTERN, idempotency
from app.core.pagination import ListQuery, list_query
from app.modules.memberships import schemas as s
from app.modules.memberships import service

router = APIRouter(
    route_class=TxRoute, tags=["memberships"], generate_unique_id_function=camel_id,
    dependencies=[Depends(idempotency)],
)  # fmt: skip
public = APIRouter(route_class=TxRoute, tags=["memberships"], generate_unique_id_function=camel_id)
Lists = Annotated[ListQuery, Depends(list_query)]
RequiredKey = Annotated[
    str, Header(min_length=8, max_length=255, pattern=KEY_PATTERN, description="Required; keys live 24 hours.")
]
Key = Annotated[
    str | None,
    Header(max_length=255, pattern=KEY_PATTERN, description="Required with a card or bank payment or a refund."),
]
Read = Annotated[Ctx, Depends(require("memberships.contract.read"))]
Sell = Annotated[Ctx, Depends(require("memberships.contract.sell"))]
Manage = Annotated[Ctx, Depends(require("memberships.plan.manage"))]
Update = Annotated[Ctx, Depends(require("memberships.contract.update"))]
Renew = Annotated[Ctx, Depends(require("memberships.contract.renew"))]
Freeze = Annotated[Ctx, Depends(require("memberships.contract.freeze"))]
Suspend = Annotated[Ctx, Depends(require("memberships.contract.suspend"))]
Cancel = Annotated[Ctx, Depends(require("memberships.contract.cancel"))]
Share = Annotated[Ctx, Depends(require("memberships.contract.share"))]
Schedule = Annotated[Ctx, Depends(require("memberships.billing_schedule.update"))]
Portal = Annotated[Ctx, Depends(current_ctx)]
ActFor = Annotated[UUID | None, Query(alias="client_id")]


def _patch(body, nullable: set[str] = frozenset()) -> dict:
    """Fields the client sent; an explicit null is kept only where null means "clear"."""
    return {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None or k in nullable}


# --- catalogue and settings --------------------------------------------------------------------------------------


@router.get("/membership-types", response_model=s.Page[s.MembershipTypeOut])
def list_membership_types(query: Lists, ctx: Read):
    """Filters: is_active. q searches the name. Sort: sort_order, name."""
    return service.list_types(ctx.session, ctx.principal, query)


@router.post("/membership-types", response_model=s.MembershipTypeOut, status_code=201)
def create_membership_type(body: s.MembershipTypeCreate, ctx: Manage):
    return service.create_type(ctx.session, ctx.principal, body.model_dump())


@router.patch("/membership-types/{membership_type_id}", response_model=s.MembershipTypeOut)
def update_membership_type(membership_type_id: UUID, body: s.MembershipTypeUpdate, ctx: Manage):
    return service.update_type(ctx.session, ctx.principal, membership_type_id, _patch(body))


@router.get("/membership-plans", response_model=s.Page[s.MembershipPlanOut])
def list_membership_plans(query: Lists, ctx: Read):
    """Filters: membership_type_id, is_active, is_sold_online. q searches the name. Sort: sort_order, name."""
    return service.list_plans(ctx.session, ctx.principal, query)


@router.post("/membership-plans", response_model=s.MembershipPlanOut, status_code=201)
def create_membership_plan(body: s.MembershipPlanCreate, ctx: Manage):
    return service.create_plan(ctx.session, ctx.principal, body.model_dump())


@router.get("/membership-plans/{membership_plan_id}", response_model=s.MembershipPlanOut)
def get_membership_plan(membership_plan_id: UUID, ctx: Read):
    return service.get_plan(ctx.session, ctx.principal, membership_plan_id)


@router.patch("/membership-plans/{membership_plan_id}", response_model=s.MembershipPlanOut)
def update_membership_plan(membership_plan_id: UUID, body: s.MembershipPlanUpdate, ctx: Manage):
    """Edits affect later sales and renewals only; sold contracts keep their snapshot."""
    nullable = {
        "invoice_description", "fixed_start_on", "auto_renew_lead_count", "auto_renew_lead_unit", "renews_as_plan_id",
        "max_visits_count", "payment_due_day", "discount_pct", "discount_minor", "revenue_category_id",
        "proration_tail",
    }  # fmt: skip
    return service.update_plan(ctx.session, ctx.principal, membership_plan_id, _patch(body, nullable))


@router.post("/membership-plans/{membership_plan_id}/duplicate", response_model=s.MembershipPlanOut, status_code=201)
def duplicate_membership_plan(membership_plan_id: UUID, ctx: Manage):
    return service.duplicate_plan(ctx.session, ctx.principal, membership_plan_id)


@router.put("/membership-plans/{membership_plan_id}/addons", response_model=s.MembershipPlanOut)
def replace_membership_plan_addons(membership_plan_id: UUID, body: s.PlanAddonsReplace, ctx: Manage):
    """The package plans bundled with this plan; granted to the member when a contract starts (MEM-04)."""
    return service.replace_plan_addons(ctx.session, ctx.principal, membership_plan_id, body.model_dump()["addons"])


@router.get("/membership-settings", response_model=s.MembershipSettingsOut)
def get_membership_settings(ctx: Read):
    return service.get_settings(ctx.session, ctx.principal)


@router.patch("/membership-settings", response_model=s.MembershipSettingsOut)
def update_membership_settings(body: s.MembershipSettingsUpdate, ctx: Manage):
    return service.update_settings(ctx.session, ctx.principal, _patch(body))


# --- sale and reads ----------------------------------------------------------------------------------------------


@router.post("/membership-contracts/quote", response_model=s.ContractQuoteOut)
def quote_membership_contract(body: s.ContractQuote, ctx: Sell):
    """Dry run of a sale: dates, proration and every billing period, pre-tax. Writes nothing."""
    return service.quote_contract(ctx.session, ctx.principal, body.model_dump())


@router.post("/membership-contracts", response_model=s.ContractSaleOut, status_code=201)
def sell_membership_contract(body: s.ContractSell, ctx: Sell, idempotency_key: Key = None):
    """Errors: membership-overlap (the client already holds a membership in these dates), validation-failed."""
    if body.payment and body.payment.tender_kind in ("card", "bank_debit") and not idempotency_key:
        raise ValidationFailed("A card or bank payment needs an Idempotency-Key.", pointer="/payment")
    return service.sell_contract(ctx.session, ctx.principal, body.model_dump(), idempotency_key)


@router.get("/membership-contracts", response_model=s.Page[s.ContractOut])
def list_membership_contracts(query: Lists, ctx: Read):
    """Filters: client_id, location_id, status, membership_type_id, membership_plan_id, is_auto_renew, renew_on,
    start_on, end_on, previous_contract_id, sales_channel. q searches the name. Sort: start_on, end_on,
    created_at."""
    return service.list_contracts(ctx.session, ctx.principal, query)


@router.get("/membership-contracts/upcoming-renewals", response_model=list[s.UpcomingRenewalOut])
def list_upcoming_membership_renewals(
    ctx: Read, days: Annotated[int, Query(ge=0, le=366)] = 30, location_id: UUID | None = None
):
    """Contracts that renew within `days`, with the name, start and price of the next term."""
    return service.list_upcoming_renewals(ctx.session, ctx.principal, days, location_id)


@router.get("/membership-standings", response_model=list[s.StandingOut])
def list_membership_standings(ctx: Read, client_ids: Annotated[list[UUID], Query(min_length=1, max_length=200)]):
    """Membership state per client (owner or sharer), from the dates, for check-in and the profile header."""
    return service.list_standings(ctx.session, ctx.principal, client_ids)


@router.get("/membership-contracts/{contract_id}", response_model=s.ContractOut)
def get_membership_contract(contract_id: UUID, ctx: Read):
    return service.get_contract(ctx.session, ctx.principal, contract_id)


@router.patch("/membership-contracts/{contract_id}", response_model=s.ContractOut)
def update_membership_contract(contract_id: UUID, body: s.ContractUpdate, ctx: Update):
    """Renewal settings (including the plan to renew into: the upgrade or downgrade path), autopay flag, visit
    cap, notes. Sold terms never change here."""
    nullable = set(s.ContractUpdate.model_fields) - {"is_autopay", "is_auto_renew", "renewal_target"}
    return service.update_contract(ctx.session, ctx.principal, contract_id, _patch(body, nullable))


@router.put("/membership-contracts/{contract_id}/sold-by", response_model=s.ContractOut)
def set_membership_contract_sold_by(
    contract_id: UUID, body: s.SoldByIn, ctx: Annotated[Ctx, Depends(require("memberships.contract.edit_sold_by"))]
):
    return service.set_sold_by(ctx.session, ctx.principal, contract_id, body.sold_by_staff_user_id)


@router.get("/membership-contracts/{contract_id}/billing-schedule", response_model=list[s.PeriodOut])
def list_membership_billing_schedule(contract_id: UUID, ctx: Read):
    return [service.span_view(row) for row in service.list_schedule(ctx.session, ctx.principal, contract_id)]


@router.post("/membership-contracts/{contract_id}/billing-schedule/invoice", response_model=s.InvoicePeriodsOut)
def invoice_deferred_schedule_periods(contract_id: UUID, ctx: Schedule, body: s.InvoicePeriodsIn | None = None):
    """Invoice scheduled periods now: all of them, or the listed ones."""
    return service.invoice_deferred(ctx.session, ctx.principal, contract_id, body and body.period_ids)


@router.post("/membership-contracts/{contract_id}/reprice", response_model=s.ContractOut)
def reprice_membership_contract(contract_id: UUID, body: s.RepriceIn, ctx: Schedule):
    """New dues for the not-yet-billed periods from `effective_on` (default today)."""
    return service.reprice_contract(ctx.session, ctx.principal, contract_id, body.model_dump())


@router.patch("/billing-schedule-periods/{period_id}", response_model=s.PeriodOut)
def update_billing_schedule_period(period_id: UUID, body: s.PeriodUpdate, ctx: Schedule):
    """Errors: period-not-editable (already billed, withheld or cancelled)."""
    return service.span_view(service.update_period(ctx.session, ctx.principal, period_id, _patch(body)))


@router.get("/membership-contracts/{contract_id}/history", response_model=list[s.ContractHistoryOut])
def list_membership_contract_history(contract_id: UUID, ctx: Read):
    return service.list_history(ctx.session, ctx.principal, contract_id)


# --- lifecycle ---------------------------------------------------------------------------------------------------


@router.post("/membership-contracts/{contract_id}/renew", response_model=s.ContractOut, status_code=201)
def renew_membership_contract(contract_id: UUID, ctx: Renew, body: s.RenewIn | None = None):
    """Returns the successor (status upcoming). Errors: already-renewed, invalid-state-transition."""
    return service.renew_contract(ctx.session, ctx.principal, contract_id, body.model_dump() if body else {})


@router.get("/membership-contracts/{contract_id}/freezes", response_model=list[s.FreezeOut])
def list_membership_freezes(contract_id: UUID, ctx: Read):
    return [service.span_view(row) for row in service.list_freezes(ctx.session, ctx.principal, contract_id)]


@router.post("/membership-contracts/{contract_id}/freezes", response_model=s.FreezeOut, status_code=201)
def freeze_membership_contract(contract_id: UUID, ctx: Freeze, body: s.FreezeIn | None = None):
    """Errors: freeze-overlap, freeze-suspension-overlap, remark-required, invalid-state-transition."""
    data = body.model_dump() if body else {}
    return service.span_view(service.freeze_contract(ctx.session, ctx.principal, contract_id, data))


@router.patch("/membership-freezes/{freeze_id}", response_model=s.FreezeOut)
def update_membership_freeze(freeze_id: UUID, body: s.SpanUpdate, ctx: Freeze):
    """Save or change the end date (null = open-ended again). Errors: freeze-ended, freeze-overlap."""
    return service.span_view(service.update_freeze(ctx.session, ctx.principal, freeze_id, _patch(body, {"end_on"})))


@router.post("/membership-freezes/{freeze_id}/remove", response_model=s.FreezeOut)
def remove_membership_freeze(freeze_id: UUID, ctx: Freeze, body: s.RemoveIn | None = None):
    """Unfreeze today (or withdraw a freeze that has not begun). Errors: freeze-ended."""
    data = body.model_dump() if body else {}
    return service.span_view(service.remove_freeze(ctx.session, ctx.principal, freeze_id, data))


@router.get("/membership-contracts/{contract_id}/suspensions", response_model=list[s.SuspensionOut])
def list_membership_suspensions(contract_id: UUID, ctx: Read):
    return [service.span_view(row) for row in service.list_suspensions(ctx.session, ctx.principal, contract_id)]


@router.post("/membership-contracts/{contract_id}/suspensions", response_model=s.SuspensionOut, status_code=201)
def suspend_membership_contract(contract_id: UUID, ctx: Suspend, body: s.SuspensionIn | None = None):
    """Errors: suspension-overlap, freeze-suspension-overlap, remark-required, invalid-state-transition."""
    data = body.model_dump() if body else {}
    return service.span_view(service.suspend_contract(ctx.session, ctx.principal, contract_id, data))


@router.patch("/membership-suspensions/{suspension_id}", response_model=s.SuspensionOut)
def update_membership_suspension(suspension_id: UUID, body: s.SpanUpdate, ctx: Suspend):
    data = _patch(body, {"end_on"})
    return service.span_view(service.update_suspension(ctx.session, ctx.principal, suspension_id, data))


@router.post("/membership-suspensions/{suspension_id}/remove", response_model=s.SuspensionOut)
def remove_membership_suspension(suspension_id: UUID, ctx: Suspend, body: s.RemoveIn | None = None):
    data = body.model_dump() if body else {}
    return service.span_view(service.remove_suspension(ctx.session, ctx.principal, suspension_id, data))


@router.post("/membership-contracts/{contract_id}/cancellation-quote", response_model=s.CancelQuoteOut)
def quote_membership_cancellation(contract_id: UUID, ctx: Cancel, body: s.CancelQuoteIn | None = None):
    """Dry run of a cancel on a date, with the pro-rata credit proposed for the current period."""
    return service.quote_cancellation(ctx.session, ctx.principal, contract_id, body and body.effective_on)


@router.post("/membership-contracts/{contract_id}/cancel", response_model=s.CancelOut)
def cancel_membership_contract(contract_id: UUID, body: s.CancelIn, ctx: Cancel, idempotency_key: Key = None):
    """`is_refunded` also needs billing.refund.create. Errors: remark-required, invalid-state-transition."""
    return service.cancel_contract(ctx.session, ctx.principal, contract_id, body.model_dump(), idempotency_key)


@router.post("/membership-contracts/{contract_id}/undo-cancel", response_model=s.ContractOut)
def undo_membership_cancel(contract_id: UUID, ctx: Cancel):
    """Errors: membership-overlap (the client holds another membership in those dates)."""
    return service.undo_cancel(ctx.session, ctx.principal, contract_id)


# --- sharing and visits ------------------------------------------------------------------------------------------


@router.get("/membership-contracts/{contract_id}/shares", response_model=list[s.MembershipShareOut])
def list_membership_shares(contract_id: UUID, ctx: Read):
    return service.list_shares(ctx.session, ctx.principal, contract_id)


@router.post("/membership-contracts/{contract_id}/shares", response_model=s.MembershipShareOut, status_code=201)
def add_membership_share(contract_id: UUID, body: s.ShareIn, ctx: Share):
    return service.add_share(ctx.session, ctx.principal, contract_id, body.client_id)


@router.delete("/membership-contracts/{contract_id}/shares/{membership_share_id}", status_code=204)
def revoke_membership_share(contract_id: UUID, membership_share_id: UUID, ctx: Share):
    service.revoke_share(ctx.session, ctx.principal, contract_id, membership_share_id)
    return Response(status_code=204)


@router.get("/membership-contracts/{contract_id}/visits", response_model=s.Page[s.VisitOut])
def list_membership_visits(contract_id: UUID, query: Lists, ctx: Read):
    """Filters: client_id, local_on. Sort: visited_at."""
    return service.list_visits(ctx.session, ctx.principal, contract_id, query)


@router.post("/membership-contracts/{contract_id}/visit-adjustments", response_model=s.ContractOut)
def adjust_membership_visits(
    contract_id: UUID, body: s.VisitAdjust, ctx: Annotated[Ctx, Depends(require("memberships.contract.adjust_visits"))]
):
    return service.adjust_visits(ctx.session, ctx.principal, contract_id, body.model_dump())


# --- portal ------------------------------------------------------------------------------------------------------


@router.get("/portal/membership-contracts", response_model=list[s.PortalContractOut])
def list_portal_membership_contracts(ctx: Portal, client_id: ActFor = None):
    """Memberships the signed-in client (or the client they act for) owns or is covered by."""
    return service.portal_list_contracts(ctx.session, ctx.principal, client_id)


@router.get("/portal/membership-standing", response_model=s.StandingOut)
def get_portal_membership_standing(ctx: Portal, client_id: ActFor = None):
    return service.portal_standing(ctx.session, ctx.principal, client_id)


@router.post("/portal/membership-contracts/{contract_id}/auto-renew-opt-out", response_model=s.PortalContractOut)
def portal_opt_out_membership_auto_renew(contract_id: UUID, ctx: Portal):
    """Click-to-cancel: switches automatic renewal off. The membership runs to its end date; nothing is
    refunded for the current term."""
    return service.portal_disable_auto_renew(ctx.session, ctx.principal, contract_id)


@router.post("/portal/membership-contracts/quote", response_model=s.ContractQuoteOut)
def portal_quote_membership_contract(body: s.PortalContractBuy, ctx: Portal):
    """Dry run of an online purchase of a plan that is sold online."""
    return service.portal_quote(ctx.session, ctx.principal, body.model_dump())


@router.post("/portal/membership-contracts", response_model=s.PortalContractSaleOut, status_code=201)
def portal_buy_membership_contract(body: s.PortalContractBuy, ctx: Portal, idempotency_key: RequiredKey):
    """What is due now must be paid and go through. Errors: payment-failed (nothing is sold),
    membership-overlap, validation-failed (plan not sold online, no payment method)."""
    return service.portal_buy(ctx.session, ctx.principal, body.model_dump(), idempotency_key)


@public.get("/public/membership-plans", response_model=s.Page[s.PublicPlanOut])
def list_public_membership_plans(query: Lists, session: Annotated[Session, Depends(public_session)]):
    """Plans sold online, for the tenant resolved from the host. Filters: membership_type_id. q searches the
    name."""
    return service.public_list_plans(session, query)
