"""fh_platform (BYPASSRLS) access. Only tenant resolution, provisioning, the outbox relay and the shared-app
directory read (`search_app_directory`, called by engagement) may use it; modules import nothing else from here
(ADR 0001 section 2)."""

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
    return create_engine(get_settings().db_url("platform"), pool_size=2, pool_pre_ping=True)


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


@dataclass(frozen=True)
class DirectoryRow:
    tenant_id: UUID
    slug: str
    name: str
    city: str | None
    logo_object_key: str | None


def search_app_directory(prefix: str, limit: int) -> list[DirectoryRow]:
    """The shared app's facility search (APP-01): the one cross-tenant read. Only tenants that are active, whose
    app config is on and listed, and that have an enabled public portal location; the name or one of its words
    starts with `prefix`. Listing fields only. shortcut: first page only (limit <= 20), no cursor."""
    escaped = prefix.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    sql = """
        SELECT t.id, t.slug, coalesce(c.directory_name, t.name) AS name,
          (SELECT l.city FROM portal_settings p JOIN location l ON l.tenant_id = p.tenant_id AND l.id = p.location_id
            WHERE p.tenant_id = t.id AND p.is_enabled AND p.is_public ORDER BY l.city NULLS LAST LIMIT 1) AS city,
          (SELECT f.object_key FROM logo g JOIN stored_file f ON f.tenant_id = g.tenant_id AND f.id = g.file_id
            WHERE g.tenant_id = t.id AND g.location_id IS NULL) AS logo_object_key
        FROM tenant t JOIN app_config c ON c.tenant_id = t.id
        WHERE t.status = 'active' AND c.is_enabled AND c.is_listed_in_directory
          AND EXISTS (SELECT 1 FROM portal_settings p WHERE p.tenant_id = t.id AND p.is_enabled AND p.is_public)
          AND (lower(coalesce(c.directory_name, t.name)) LIKE :starts ESCAPE '\\'
               OR lower(coalesce(c.directory_name, t.name)) LIKE :word ESCAPE '\\')
        ORDER BY name, t.id LIMIT :limit
    """
    params = {"starts": f"{escaped}%", "word": f"% {escaped}%", "limit": limit}
    with platform_engine().connect() as conn:
        return [DirectoryRow(r.id, r.slug, r.name, r.city, r.logo_object_key) for r in conn.execute(text(sql), params)]
