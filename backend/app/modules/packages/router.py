"""packages HTTP surface (openapi-people.yaml, tag packages): staff and portal routes.

Differences from the YAML, by design. Path ids are named `package_plan_id` and `package_share_id` (the YAML's
`plan_id` and `share_id` also name membership ids, and the generated isolation tests key on the name). GET
operation ids start with get/list (a kernel rule for SameSite=Lax), so the portal reads are `listPortal*`.
Renewal settings are part of `updateClientPackage` (the YAML's separate `setClientPackageRenewal` is not built).
Shares return a plain array.
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
from app.modules.packages import postbilled, service
from app.modules.packages import schemas as s

router = APIRouter(
    route_class=TxRoute, tags=["packages"], generate_unique_id_function=camel_id, dependencies=[Depends(idempotency)]
)
public = APIRouter(route_class=TxRoute, tags=["packages"], generate_unique_id_function=camel_id)
Lists = Annotated[ListQuery, Depends(list_query)]
Key = Annotated[
    str | None, Header(max_length=255, pattern=KEY_PATTERN, description="Required with a card or bank payment.")
]
RequiredKey = Annotated[
    str, Header(min_length=8, max_length=255, pattern=KEY_PATTERN, description="Required; keys live 24 hours.")
]
Read = Annotated[Ctx, Depends(require("packages.package.read"))]
Sell = Annotated[Ctx, Depends(require("packages.package.sell"))]
Manage = Annotated[Ctx, Depends(require("packages.plan.manage"))]
Update = Annotated[Ctx, Depends(require("packages.package.update"))]
Share = Annotated[Ctx, Depends(require("packages.package.share"))]
Remove = Annotated[Ctx, Depends(require("packages.package.remove"))]
Close = Annotated[Ctx, Depends(require(postbilled.CLOSE))]
Portal = Annotated[Ctx, Depends(current_ctx)]
ActFor = Annotated[UUID | None, Query(alias="client_id")]


def _patch(body, nullable: set[str] = frozenset()) -> dict:
    return {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None or k in nullable}


# --- plans and settings ------------------------------------------------------------------------------------------


@router.get("/package-plans", response_model=s.Page[s.PackagePlanOut])
def list_package_plans(query: Lists, ctx: Read):
    """Filters: reservation_type_id, is_active, kind, session_mode, pricing_category, online_sale_mode. q searches
    the name. Sort: sort_order, name."""
    return service.list_plans(ctx.session, ctx.principal, query)


@router.post("/package-plans", response_model=s.PackagePlanOut, status_code=201)
def create_package_plan(body: s.PackagePlanCreate, ctx: Manage):
    return service.create_plan(ctx.session, ctx.principal, body.model_dump())


@router.get("/package-plans/{package_plan_id}", response_model=s.PackagePlanOut)
def get_package_plan(package_plan_id: UUID, ctx: Read):
    return service.get_plan(ctx.session, ctx.principal, package_plan_id)


@router.patch("/package-plans/{package_plan_id}", response_model=s.PackagePlanOut)
def update_package_plan(package_plan_id: UUID, body: s.PackagePlanUpdate, ctx: Manage):
    """Edits affect later sales and renewals only; sold packages keep their snapshot."""
    required = {
        "name", "session_mode", "pricing_category", "is_complimentary", "start_rule", "allows_booking_after_expiry",
        "renewal_target", "is_auto_renew_on_threshold", "share_mode", "is_series_auto_renew", "default_invoice_mode",
        "is_autopay_default", "online_sale_mode", "is_members_only_online", "is_members_only_at_desk", "sort_order",
        "is_active",
    }  # fmt: skip
    nullable = set(s.PackagePlanUpdate.model_fields) - required
    return service.update_plan(ctx.session, ctx.principal, package_plan_id, _patch(body, nullable))


@router.get("/package-settings", response_model=s.PackageSettingsOut)
def get_package_settings(ctx: Read):
    return service.get_settings(ctx.session, ctx.principal)


@router.patch("/package-settings", response_model=s.PackageSettingsOut)
def update_package_settings(body: s.PackageSettingsUpdate, ctx: Manage):
    return service.update_settings(ctx.session, ctx.principal, _patch(body))


# --- sale and reads ----------------------------------------------------------------------------------------------


@router.post("/client-packages/quote", response_model=s.PackageQuoteOut)
def quote_client_package(body: s.PackageQuote, ctx: Sell):
    """Dry run of a sale: credits, pre-tax price, validity and the documents still to accept."""
    return service.quote_package(ctx.session, ctx.principal, body.model_dump())


@router.post("/client-packages", response_model=s.PackageSaleOut, status_code=201)
def sell_client_package(body: s.PackageSell, ctx: Sell, idempotency_key: Key = None):
    """Errors: document-required (carries document_id), members-only, validation-failed."""
    if body.payment and body.payment.tender_kind in ("card", "bank_debit") and not idempotency_key:
        raise ValidationFailed("A card or bank payment needs an Idempotency-Key.", pointer="/payment")
    return service.sell_package(ctx.session, ctx.principal, body.model_dump(), idempotency_key)


@router.post("/client-packages/complimentary", response_model=s.PackageSaleOut, status_code=201)
def grant_complimentary_package(
    body: s.PackageGrant, ctx: Annotated[Ctx, Depends(require("packages.package.grant_complimentary"))]
):
    """Give a plan's package away: no charge, marked complimentary."""
    return service.grant_complimentary(ctx.session, ctx.principal, body.model_dump())


@router.post("/client-packages/post-billed", response_model=s.PackageOut, status_code=201)
def open_post_billed_package(body: s.PostBilledPackageOpen, ctx: Sell):
    """Open a post-billed package (PKG-11): nothing is charged now; used sessions are billed at a period close.
    The reservation type needs an active post-billed rate."""
    return postbilled.open_package(ctx.session, ctx.principal, body.model_dump())


@router.get("/client-packages", response_model=s.Page[s.PackageOut])
def list_client_packages(query: Lists, ctx: Read):
    """Filters: client_id (owner), usable_by_client_id (owned or shared), location_id, status,
    reservation_type_id, package_plan_id, package_series_id, source_contract_id, is_auto_renew,
    is_complimentary, expires_on_or_before (last valid day on or before this date). q searches the name.
    Sort: created_at, name."""
    return service.list_packages(ctx.session, ctx.principal, query)


@router.get("/client-packages/{package_id}", response_model=s.PackageOut)
def get_client_package(package_id: UUID, ctx: Read):
    return service.get_package(ctx.session, ctx.principal, package_id)


@router.patch("/client-packages/{package_id}", response_model=s.PackageOut)
def update_client_package(package_id: UUID, body: s.PackageUpdate, ctx: Update):
    """Expiry (null = never expires), booking after expiry, renewal settings and the renewal threshold."""
    nullable = {
        "valid_until_on", "internal_remarks", "auto_renew_lead_count", "auto_renew_lead_unit", "renews_as_plan_id",
        "renewal_threshold_count",
    }  # fmt: skip
    return service.update_package(ctx.session, ctx.principal, package_id, _patch(body, nullable))


@router.get("/client-packages/{package_id}/ledger", response_model=s.Page[s.CreditLedgerEntryOut])
def list_client_package_ledger(package_id: UUID, query: Lists, ctx: Read):
    """Every credit movement. Filters: entry_type, client_id, source_id, reason. Sort: occurred_at."""
    return service.list_ledger(ctx.session, ctx.principal, package_id, query)


@router.post("/client-packages/{package_id}/credit-adjustments", response_model=s.PackageOut)
def adjust_client_package_credits(
    package_id: UUID, body: s.CreditAdjust, ctx: Annotated[Ctx, Depends(require("packages.credit.adjust"))]
):
    """Errors: package-exhausted (the adjustment would take away credits already scheduled or used)."""
    if body.delta == 0:
        raise ValidationFailed("The adjustment cannot be zero.", pointer="/delta")
    return service.adjust_credits(ctx.session, ctx.principal, package_id, body.model_dump())


@router.get("/client-packages/{package_id}/shares", response_model=list[s.PackageShareOut])
def list_package_shares(package_id: UUID, ctx: Read):
    return service.list_shares(ctx.session, ctx.principal, package_id)


@router.post("/client-packages/{package_id}/shares", response_model=s.PackageShareOut, status_code=201)
def add_package_share(package_id: UUID, body: s.ShareIn, ctx: Share):
    return service.add_share(ctx.session, ctx.principal, package_id, body.client_id)


@router.delete("/client-packages/{package_id}/shares/{package_share_id}", status_code=204)
def revoke_package_share(package_id: UUID, package_share_id: UUID, ctx: Share):
    service.revoke_share(ctx.session, ctx.principal, package_id, package_share_id)
    return Response(status_code=204)


@router.post("/client-packages/{package_id}/renew", response_model=s.PackageOut, status_code=201)
def renew_client_package(package_id: UUID, ctx: Sell):
    """Returns the successor package. Errors: already-renewed."""
    return service.renew_package(ctx.session, ctx.principal, package_id)


@router.post("/client-packages/{package_id}/removal-quote", response_model=s.RemovalQuoteOut)
def quote_client_package_removal(package_id: UUID, ctx: Remove):
    return service.quote_removal(ctx.session, ctx.principal, package_id)


@router.post("/client-packages/{package_id}/remove", response_model=s.PackageOut)
def remove_client_package(package_id: UUID, body: s.PackageRemove, ctx: Remove):
    """Errors: package-in-use (billing_reversed once sessions were used)."""
    return service.remove_package(ctx.session, ctx.principal, package_id, body.model_dump())


@router.get("/package-series", response_model=s.Page[s.PackageSeriesOut])
def list_package_series(query: Lists, ctx: Read):
    """Filters: client_id, status, package_plan_id, location_id. Sort: created_at."""
    return service.list_series(ctx.session, ctx.principal, query)


@router.get("/package-series/{series_id}", response_model=s.PackageSeriesOut)
def get_package_series(series_id: UUID, ctx: Read):
    return service.get_series(ctx.session, ctx.principal, series_id)


@router.post("/package-series/{series_id}/cancel", response_model=s.PackageSeriesOut)
def cancel_package_series(series_id: UUID, ctx: Remove):
    return service.cancel_series(ctx.session, ctx.principal, series_id)


# --- portal ------------------------------------------------------------------------------------------------------


@router.get("/portal/client-packages", response_model=s.Page[s.PortalPackageOut])
def list_portal_client_packages(query: Lists, ctx: Portal, client_id: ActFor = None):
    """Packages the signed-in client (or the client they act for) owns or may draw on. Filters: status,
    reservation_type_id."""
    return service.portal_list_packages(ctx.session, ctx.principal, client_id, query)


@router.post("/portal/client-packages", response_model=s.PortalPackageSaleOut, status_code=201)
def portal_buy_client_package(body: s.PortalPackageBuy, ctx: Portal, idempotency_key: RequiredKey):
    """Errors: payment-failed (a pay-in-full plan and the payment did not go through; nothing is sold),
    document-required, members-only."""
    return service.portal_buy(ctx.session, ctx.principal, body.model_dump(), idempotency_key)


@router.get("/portal/client-packages/{package_id}/ledger", response_model=s.Page[s.PortalCreditLedgerEntryOut])
def list_portal_client_package_ledger(package_id: UUID, query: Lists, ctx: Portal):
    return service.portal_list_ledger(ctx.session, ctx.principal, package_id, query)


@router.get("/portal/package-plans", response_model=s.Page[s.PortalPackagePlanOut])
def list_portal_package_plans(query: Lists, ctx: Portal, client_id: ActFor = None):
    """Plans sold online. Filters: reservation_type_id. q searches the name."""
    query.filters.pop("client_id", None)
    return service.portal_list_plans(ctx.session, ctx.principal, client_id, query)


@router.post("/portal/client-packages/{package_id}/auto-renew-opt-out", response_model=s.PortalPackageOut)
def portal_opt_out_package_auto_renew(package_id: UUID, ctx: Portal):
    return service.portal_disable_auto_renew(ctx.session, ctx.principal, package_id)


@router.post("/portal/package-series/{series_id}/auto-renew-opt-out", response_model=s.PortalPackageSeriesOut)
def portal_opt_out_series_auto_renew(series_id: UUID, ctx: Portal):
    return service.portal_disable_series_auto_renew(ctx.session, ctx.principal, series_id)


@public.get("/public/package-plans", response_model=s.Page[s.PortalPackagePlanOut])
def list_public_package_plans(query: Lists, session: Annotated[Session, Depends(public_session)]):
    """Plans sold online, for the tenant resolved from the host. Filters: reservation_type_id. q searches the
    name. `is_purchasable` is false for member-only plans until a signed-in member asks."""
    return service.public_list_plans(session, query)


# --- post-billed rates (PKG-11) and period closes (BIL-18) -------------------------------------------------------


@router.get("/post-billed-rates", response_model=s.Page[s.PostBilledRateOut])
def list_post_billed_rates(query: Lists, ctx: Manage):
    """Filters: reservation_type_id, is_active."""
    return postbilled.list_rates(ctx.session, ctx.principal, query)


@router.post("/post-billed-rates", response_model=s.PostBilledRateOut, status_code=201)
def create_post_billed_rate(body: s.PostBilledRateCreate, ctx: Manage):
    """One tier: every session of a close is billed at the tier with the highest min_sessions reached."""
    return postbilled.create_rate(ctx.session, ctx.principal, body.model_dump())


@router.patch("/post-billed-rates/{post_billed_rate_id}", response_model=s.PostBilledRateOut)
def update_post_billed_rate(post_billed_rate_id: UUID, body: s.PostBilledRateUpdate, ctx: Manage):
    return postbilled.update_rate(ctx.session, ctx.principal, post_billed_rate_id, body.model_dump(exclude_unset=True))


@router.post("/post-billed-closes/preview", response_model=s.PostBilledPreviewOut)
def preview_post_billed_close(body: s.PostBilledCloseIn, ctx: Close):
    """Every open post-billed package at the location with what a close on that date would bill."""
    return postbilled.preview_close(ctx.session, ctx.principal, body.model_dump())


@router.post("/post-billed-closes", response_model=s.PostBilledCloseOut, status_code=201)
def close_post_billed_period(body: s.PostBilledCloseIn, ctx: Close):
    """Bill used sessions up to closing_on (one charge and invoice per package). Idempotent per location and
    date: a repeat returns the first close."""
    return postbilled.close_period(ctx.session, ctx.principal, body.model_dump())


@router.get("/post-billed-closes", response_model=s.Page[s.PostBilledCloseOut])
def list_post_billed_closes(query: Lists, ctx: Close):
    """Past closes, newest first. Filters: location_id, closing_on."""
    return postbilled.list_closes(ctx.session, ctx.principal, query)


@router.get("/post-billed-closes/{post_billed_close_id}", response_model=s.PostBilledCloseOut)
def get_post_billed_close(post_billed_close_id: UUID, ctx: Close):
    return postbilled.get_close(ctx.session, ctx.principal, post_billed_close_id)
