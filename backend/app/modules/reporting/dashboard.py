"""The management dashboard (RPT-02; ADR 0010 section 7): a composition of existing report specs called through
the runner, never its own queries. Each tile is one spec's totals for a fixed period, built with the caller's
permissions, locations and reach exactly as a run would be; a spec the caller may not run is left out. Nothing is
stored. The result is cached in Redis for CACHE_SECONDS per tenant, staff user, location and permission set, so a
refresh storm costs one build a minute; a Redis outage only means no cache."""

import hashlib
import json
import logging
from uuid import UUID

import redis
from sqlalchemy.orm import Session

from app.core import clock
from app.core.auth import Principal, authorize
from app.core.errors import PermissionDenied, ValidationFailed
from app.core.settings import get_settings
from app.modules import platform
from app.modules.reporting import service
from app.modules.reporting.catalogue import REGISTRY
from app.modules.reporting.registry import MAX_ROWS

log = logging.getLogger(__name__)
KEY = "reporting.dashboard.read"
CACHE_SECONDS = 60
# (report key, relative period or None for an as-of report, the totals shown); each links to the full report.
TILES = (
    ("revenue_summary", "this_month", ("net_minor", "charge_count")),
    ("deposits", "today", ("net_minor", "payment_count")),
    ("open_invoices", None, ("balance_minor", "invoice_count", "days_over_90_minor")),
    ("memberships_by_status", None, ("member_count", "contract_count")),
    ("attendance_overview", "this_week", ("attended", "total", "attended_pct")),
    ("daily_register", "today", ("total_minor", "sale_count", "variance_minor")),
)


def _redis() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis.url, socket_timeout=0.5)


def _cache_key(principal: Principal, location_id: UUID | None, linked_resource_id: UUID | None) -> str:
    # the linked trainer resource decides own-reach tiles, so a relink must not serve the previous trainer's
    scope = json.dumps([sorted(principal.permissions.items()), sorted(map(str, principal.location_ids or [])),
                        str(linked_resource_id)])  # fmt: skip
    digest = hashlib.sha256(scope.encode()).hexdigest()[:16]
    return f"fh:dashboard:{principal.tenant_id}:{principal.staff_user_id}:{location_id or 'all'}:{digest}"


def _tile(session: Session, principal: Principal, tile: tuple, location_id: UUID | None) -> dict | None:
    report_key, period, shown = tile
    spec = REGISTRY[report_key]
    raw: dict = {"location_ids": [location_id]} if location_id else {}
    if period:
        raw["period"] = period
    try:
        params, scope = service.resolve(session, principal, spec, raw)
        result = spec.build(session, params, scope)
    except PermissionDenied:  # own reach on a report without own-reach support
        return None
    except ValidationFailed:  # too many rows for one run: the full report says so
        log.info("dashboard tile %s skipped", report_key)
        return None
    if len(result["rows"]) + len(result["details"] or []) > MAX_ROWS:
        return None
    totals = json.loads(json.dumps(result["totals"], default=str))
    return {
        "key": spec.key, "name": spec.name, "period": period,
        "totals": [c.out() | {"value": totals.get(c.key)} for key in shown for c in spec.totals if c.key == key],
    }  # fmt: skip


def get_dashboard(session: Session, principal: Principal, location_id: UUID | None = None) -> dict:
    authorize(principal, KEY)
    service._staff(principal)
    if location_id is not None:
        platform.service.get_location(session, principal, location_id)  # 404 outside the caller's set
    key = _cache_key(principal, location_id, platform.service.linked_resource_id(session, principal.staff_user_id))
    try:
        if cached := _redis().get(key):
            return json.loads(cached)
    except redis.RedisError:
        log.warning("dashboard cache unavailable")
    tiles = [
        built for tile in TILES
        if service._holds(principal, REGISTRY[tile[0]].permission)
        and (built := _tile(session, principal, tile, location_id)) is not None
    ]  # fmt: skip
    result = {"location_id": str(location_id) if location_id else None,
              "generated_at": clock.now().isoformat(), "tiles": tiles}  # fmt: skip
    try:
        _redis().set(key, json.dumps(result, default=str), ex=CACHE_SECONDS)
    except redis.RedisError:
        pass
    return result
