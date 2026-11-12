"""Tenant plans and entitlements (PLT-14), per-tenant feature flags (PLT-09) and the mobile-app user limit (PLT-13).

Where the data lives (forced RLS, ADR 0001): the plan catalogue is the global `subscription_plan` table (no RLS,
fh_app reads it, migrations write it). The tenant's plan is `tenant.subscription_plan_id`, and its overrides are
`tenant_entitlement` rows: both are tenant data, written only by the operator functions at the bottom of this
file, each inside that tenant's own session and audited. No billing of the tenant for its plan happens here.

Resolution: features = the plan's features, plus in-force rows that turn one on, minus in-force rows that turn
one off (a flag off wins). A limit = the most generous in-force row for it (null = unlimited), else the plan's
value (a missing key is unlimited). A tenant with no plan gets `entitlements.default_plan` from config.

Other contexts call `has_feature`, `require_feature`, `limit`, `check_limit` and `enforce_limit`; they are internal
(no principal): the command that calls them carries the permission gate.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core import audit, clock
from app.core.auth import Principal, authorize, system_principal
from app.core.db.session import app_engine, tenant_session
from app.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from app.core.settings import get_settings
from app.modules.platform.models import (
    AuthSession,
    Identity,
    Location,
    SubscriptionPlan,
    Tenant,
    TenantEntitlement,
)

# The catalogues are code. A key here is something the product actually gates; add one with its gate.
FEATURES = {
    "api_access": "API keys and integrations",
    "branded_app": "Branded mobile app",
}
LIMITS = {
    "locations": "Active locations",
    "clients": "Active clients",
    "app_users": "Members signed in to the mobile app",
}
_counters: dict[str, Callable[[Session], int]] = {}
_CACHE = "platform.entitlements"


@dataclass(frozen=True)
class Resolved:
    plan: SubscriptionPlan
    features: frozenset[str]
    limits: dict[str, int | None]


def register_usage_counter(key: str, counter: Callable[[Session], int]) -> None:
    """A context that owns a metered table registers how to count it (clients: active clients)."""
    assert key in LIMITS, key
    _counters[key] = counter


def live_app_session(now=None):
    """WHERE clause: a member's mobile session that can still be used or refreshed (PLT-13)."""
    now = now or clock.now()
    return (
        (AuthSession.kind == "mobile") & AuthSession.revoked_at.is_(None)
        & (AuthSession.idle_expires_at > now) & (AuthSession.absolute_expires_at > now)
        & AuthSession.identity_id.in_(select(Identity.id).where(Identity.kind == "client"))
    )  # fmt: skip


_counters |= {
    "locations": lambda s: s.execute(select(func.count()).where(Location.status == "active")).scalar_one(),
    "app_users": lambda s: s.execute(
        select(func.count(AuthSession.identity_id.distinct())).where(live_app_session())
    ).scalar_one(),
}


def _today(session: Session) -> date:
    from app.modules.platform.service import earliest_today  # service imports this module

    return earliest_today(session)


def default_plan(session: Session) -> SubscriptionPlan:
    code = get_settings().entitlements.default_plan
    plan = session.scalar(select(SubscriptionPlan).where(SubscriptionPlan.code == code))
    if plan is None:
        raise RuntimeError(f"entitlements.default_plan {code!r} is not in subscription_plan")
    return plan


def _in_force(today: date):
    return (TenantEntitlement.starts_on <= today) & or_(
        TenantEntitlement.ends_on.is_(None), TenantEntitlement.ends_on >= today
    )


def resolve(session: Session) -> Resolved:
    """The tenant's effective plan, features and limits. Cached on the session until an operator change."""
    if (hit := session.info.get(_CACHE)) is not None:
        return hit
    tenant = session.get_one(Tenant, session.info["tenant_id"])
    plan = session.get(SubscriptionPlan, tenant.subscription_plan_id) if tenant.subscription_plan_id else None
    plan = plan or default_plan(session)
    rows = session.scalars(select(TenantEntitlement).where(_in_force(_today(session)))).all()
    features = set(plan.features) | {r.key for r in rows if r.key in FEATURES and r.is_enabled}
    features -= {r.key for r in rows if r.key in FEATURES and not r.is_enabled}
    limits = {key: plan.limits.get(key) for key in LIMITS}
    for key in LIMITS:
        if values := [r.limit_value for r in rows if r.key == key]:
            limits[key] = None if None in values else max(v for v in values if v is not None)
    session.info[_CACHE] = resolved = Resolved(plan, frozenset(features & FEATURES.keys()), limits)
    return resolved


def has_feature(session: Session, key: str) -> bool:
    assert key in FEATURES, key
    return key in resolve(session).features


def require_feature(session: Session, key: str) -> None:
    if not has_feature(session, key):
        raise PermissionDenied(
            f"{FEATURES[key]} is not part of this account's plan.", code="feature-not-in-plan", feature=key
        )


def limit(session: Session, key: str) -> int | None:
    """The tenant's cap for a metered key; None is unlimited."""
    assert key in LIMITS, key
    return resolve(session).limits[key]


def check_limit(session: Session, key: str, current: int) -> None:
    """`current` is the count before the one being added. Raise before any write.
    shortcut: two concurrent creates can both pass and overshoot by one each; lock if a cap must be exact."""
    cap = limit(session, key)
    if cap is not None and current >= cap:
        raise Conflict(
            f"This account's plan allows {cap} {LIMITS[key].lower()}. Ask us to change the plan to add more.",
            code="plan-limit-reached", limit_key=key, limit=cap,
        )  # fmt: skip


def usage(session: Session, key: str) -> int:
    return _counters[key](session)


def enforce_limit(session: Session, key: str) -> None:
    """check_limit with the registered counter, counting only when the key is capped."""
    if limit(session, key) is not None:
        check_limit(session, key, usage(session, key))


def summary(session: Session, *, limits: bool = True, count_all: bool = False) -> dict:
    """Me.entitlements and the plan screen. Usage is counted for capped keys, or for every key with count_all."""
    resolved = resolve(session)
    rows = [
        {"key": key, "label": label, "limit": resolved.limits[key],
         "used": usage(session, key) if count_all or resolved.limits[key] is not None else None}
        for key, label in LIMITS.items()
    ] if limits else []  # fmt: skip
    return {
        "plan": {"code": resolved.plan.code, "name": resolved.plan.name},
        "features": sorted(resolved.features),
        "limits": rows,
    }


def plan_usage(session: Session, principal: Principal) -> dict:
    """Settings, "Plan and usage" (Owner and Admin): plan, features, every limit with its use, and overrides."""
    authorize(principal, "platform.tenant.update")
    return _detail(session)


def _detail(session: Session) -> dict:
    overrides = session.scalars(select(TenantEntitlement).order_by(TenantEntitlement.starts_on, TenantEntitlement.key))
    features = resolve(session).features
    catalogue = [{"key": key, "label": label, "included": key in features} for key, label in FEATURES.items()]
    return summary(session, count_all=True) | {"overrides": list(overrides), "feature_catalogue": catalogue}


# --- operator (X-Operator-Token routes): change a tenant's plan and overrides ----------------------------------

_OPERATOR = "platform.operator"
_ACTION = "platform.tenant.manage_subscription"


def list_plans() -> list[SubscriptionPlan]:
    with Session(app_engine()) as session:  # global table: no tenant context needed
        return list(session.scalars(select(SubscriptionPlan).order_by(SubscriptionPlan.code)))


def _operator_session(tenant_id: UUID):
    return tenant_session(tenant_id, actor=system_principal(_OPERATOR))


def _tenant(session: Session, tenant_id: UUID) -> Tenant:
    tenant = session.get(Tenant, tenant_id)  # RLS hides every other tenant, so an unknown id is None too
    if tenant is None:
        raise NotFound()
    return tenant


def tenant_detail(tenant_id: UUID) -> dict:
    with _operator_session(tenant_id) as session:
        _tenant(session, tenant_id)
        return _detail(session)


def change_plan(tenant_id: UUID, plan_code: str) -> dict:
    with _operator_session(tenant_id) as session:
        tenant = _tenant(session, tenant_id)
        plan = session.scalar(
            select(SubscriptionPlan).where(SubscriptionPlan.code == plan_code, SubscriptionPlan.is_active)
        )
        if plan is None:
            raise ValidationFailed("Unknown plan.", pointer="/plan_code", code="unknown-plan")
        before = resolve(session).plan.code
        tenant.subscription_plan_id = plan.id
        session.info.pop(_CACHE, None)
        audit.record(session, _ACTION, tenant, changes={"plan": [before, plan.code]})
        return _detail(session)


def add_entitlement(tenant_id: UUID, data: dict) -> dict:
    """A feature on or off, or a limit replaced, from starts_on (default today) to ends_on."""
    key = data["key"]
    if key not in FEATURES and key not in LIMITS:
        raise ValidationFailed(f"Unknown entitlement {key}.", pointer="/key", code="unknown-entitlement")
    if key in FEATURES and data.get("limit_value") is not None:
        raise ValidationFailed("A feature takes no limit.", pointer="/limit_value")
    if key in LIMITS and not data.get("is_enabled", True):
        raise ValidationFailed("A limit cannot be turned off; set limit_value.", pointer="/is_enabled")
    with _operator_session(tenant_id) as session:
        _tenant(session, tenant_id)
        row = TenantEntitlement(
            key=key, is_enabled=data.get("is_enabled", True), limit_value=data.get("limit_value"),
            source=data.get("source") or "manual", starts_on=data.get("starts_on") or _today(session),
            ends_on=data.get("ends_on"),
        )  # fmt: skip
        session.add(row)
        session.flush()  # dates and duplicates surface here as 422 / 409
        session.info.pop(_CACHE, None)
        audit.record(session, _ACTION, row, changes=audit.diff(row))
        return _detail(session)


def remove_entitlement(tenant_id: UUID, entitlement_id: UUID) -> None:
    with _operator_session(tenant_id) as session:
        _tenant(session, tenant_id)
        row = session.get(TenantEntitlement, entitlement_id)
        if row is None:
            raise NotFound()
        audit.record(session, _ACTION, row, changes={"key": [row.key, None]}, reason="removed")
        session.delete(row)
