"""Plans and entitlements (PLT-14, PLT-09, PLT-13): the tenant's own read, and the operator's routes.

Operator routes follow `POST /operator/tenants`: no session, the X-Operator-Token secret, 404 when it is unset
or wrong (they are not TxRoute; the service opens the tenant's session itself)."""

import secrets
from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from pydantic import Field, StringConstraints

from app.core.api import TxRoute, camel_id
from app.core.auth.deps import Ctx, require
from app.core.errors import NotFound
from app.core.schemas import In, Out
from app.core.settings import get_settings
from app.modules.platform import entitlements
from app.modules.platform.schemas import MeEntitlements

router = APIRouter(route_class=TxRoute, tags=["platform"], generate_unique_id_function=camel_id)
operator = APIRouter(tags=["operator"], generate_unique_id_function=camel_id)


class TenantEntitlementOut(Out):
    id: UUID
    key: str
    is_enabled: bool
    limit_value: int | None
    source: Literal["addon", "promo", "flag", "manual"]
    starts_on: date
    ends_on: date | None


class FeatureState(Out):
    key: str
    label: str
    included: bool


class PlanUsage(MeEntitlements):
    """Plan, features, every limit with its current use, every known feature with whether the tenant has it, and
    the operator's overrides in date order."""

    feature_catalogue: list[FeatureState]
    overrides: list[TenantEntitlementOut]


class SubscriptionPlanOut(Out):
    id: UUID
    code: str
    name: str
    is_active: bool
    features: list[str]
    limits: dict[str, int]


class TenantPlanChange(In):
    plan_code: Annotated[str, StringConstraints(min_length=1, max_length=63)]


class TenantEntitlementCreate(In):
    """A feature key turns a feature on (is_enabled true: add-on, flag) or off (false); a limit key replaces that
    limit with limit_value (null = unlimited). starts_on defaults to today."""

    key: Annotated[str, StringConstraints(min_length=1, max_length=63)]
    is_enabled: bool = True
    limit_value: int | None = Field(None, ge=0)
    source: Literal["addon", "promo", "flag", "manual"] = "manual"
    starts_on: date | None = None
    ends_on: date | None = None


@router.get("/tenant/entitlements", response_model=PlanUsage)
def list_tenant_entitlements(ctx: Ctx = Depends(require("platform.tenant.update"))):
    """Settings, Plan and usage (Owner and Admin): the plan, its features and limits with current use."""
    return entitlements.plan_usage(ctx.session, ctx.principal)


def _operator(x_operator_token: str = Header("")) -> None:
    expected = get_settings().operator_token
    if not expected or not secrets.compare_digest(x_operator_token.encode(), expected.encode()):
        raise NotFound()


Operator = Depends(_operator)


@operator.get("/operator/plans", response_model=list[SubscriptionPlanOut], dependencies=[Operator])
def list_subscription_plans():
    """The plan catalogue (global data, maintained by migrations)."""
    return entitlements.list_plans()


@operator.get("/operator/tenants/{tenant_id}/entitlements", response_model=PlanUsage, dependencies=[Operator])
def get_operator_tenant_entitlements(tenant_id: UUID):
    return entitlements.tenant_detail(tenant_id)


@operator.put("/operator/tenants/{tenant_id}/plan", response_model=PlanUsage, dependencies=[Operator])
def change_operator_tenant_plan(tenant_id: UUID, body: TenantPlanChange):
    """Move the tenant to another plan; audited. Errors: unknown-plan. No charge is made (entitlements only)."""
    return entitlements.change_plan(tenant_id, body.plan_code)


@operator.post(
    "/operator/tenants/{tenant_id}/entitlements", response_model=PlanUsage, status_code=201, dependencies=[Operator]
)
def create_operator_tenant_entitlement(tenant_id: UUID, body: TenantEntitlementCreate):
    """Add an add-on, a feature flag (PLT-09) or a limit override. Errors: unknown-entitlement, already-exists."""
    return entitlements.add_entitlement(tenant_id, body.model_dump())


@operator.delete(
    "/operator/tenants/{tenant_id}/entitlements/{entitlement_id}", status_code=204, dependencies=[Operator]
)
def delete_operator_tenant_entitlement(tenant_id: UUID, entitlement_id: UUID) -> None:
    entitlements.remove_entitlement(tenant_id, entitlement_id)
