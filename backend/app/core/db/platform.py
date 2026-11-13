"""fh_platform (BYPASSRLS) access. Only tenant resolution, provisioning and the outbox relay may use it;
modules never import this (ADR 0001 section 2)."""

import time
from dataclasses import dataclass
from functools import cache
from uuid import UUID

from sqlalchemy import Engine, create_engine, text

from app.core.settings import get_settings

_CACHE_SECONDS = 60
_CACHE_MAX = 10_000
_resolved: dict[tuple[str, str], tuple[float, "TenantRef | None"]] = {}


@dataclass(frozen=True)
class TenantRef:
    id: UUID
    status: str


@cache
def platform_engine() -> Engine:
    return create_engine(get_settings().db_url("platform"), pool_size=2, pool_pre_ping=True, hide_parameters=True)


def resolve_tenant(*, host: str | None = None, slug: str | None = None) -> TenantRef | None:
    """Tenant for a request host or a slug. Cached in process for 60 seconds, misses included."""
    key = ("host", host) if host else ("slug", slug or "")
    hit = _resolved.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    if host:
        sql = (
            "SELECT t.id, t.status FROM tenant_domain d JOIN tenant t ON t.id = d.tenant_id "
            "WHERE d.host = :v AND (d.kind = 'subdomain' OR d.verified_at IS NOT NULL)"
        )
    else:
        sql = "SELECT id, status FROM tenant WHERE slug = :v"
    with platform_engine().connect() as conn:
        row = conn.execute(text(sql), {"v": key[1]}).first()
    ref = TenantRef(row.id, row.status) if row else None
    if len(_resolved) >= _CACHE_MAX:  # the Host header is attacker-controlled; never let misses grow unbounded
        _resolved.clear()
    _resolved[key] = (time.monotonic() + _CACHE_SECONDS, ref)
    return ref


def provision_tenant(tenant_id: UUID, *, name: str, slug: str, time_zone: str, currency: str, locale: str) -> None:
    """Insert the global rows. Everything tenant-owned is then seeded inside tenant_session."""
    host = f"{slug}.{get_settings().app.base_domain}"
    with platform_engine().begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tenant (id, name, slug, default_time_zone, currency, locale) "
                "VALUES (:id, :name, :slug, :tz, :currency, :locale)"
            ),
            {"id": tenant_id, "name": name, "slug": slug, "tz": time_zone, "currency": currency, "locale": locale},
        )
        conn.execute(
            text(
                "INSERT INTO tenant_domain (tenant_id, host, kind, is_primary) VALUES (:id, :host, 'subdomain', true)"
            ),
            {"id": tenant_id, "host": host},
        )
    _resolved.pop(("slug", slug), None)
    _resolved.pop(("host", host), None)


def unprovision_tenant(tenant_id: UUID) -> None:
    """Compensation when seeding a freshly provisioned tenant fails; never for a tenant with data."""
    with platform_engine().begin() as conn:
        conn.execute(text("DELETE FROM tenant_domain WHERE tenant_id = :id"), {"id": tenant_id})
        conn.execute(text("DELETE FROM tenant WHERE id = :id"), {"id": tenant_id})
