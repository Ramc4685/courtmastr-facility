"""Member app favourites with a personal schedule (APP-13) and anonymous app usage counts (APP-17), Phase 11 C2.

A favourite is a reservation type or a program group a client marks; the personal schedule is the portal session
listing (programs.selfservice) narrowed to those. Usage counts are daily totals per screen or action in UTC days,
with nothing about who sent them: no client, no location, no audit row (anonymous counters).
"""

from collections import Counter
from datetime import date, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core import audit, clock
from app.core.auth import Principal, authorize
from app.core.errors import NotFound, ValidationFailed
from app.core.settings import get_settings
from app.modules import programs
from app.modules.clients import households
from app.modules.engagement.models import AppUsageDay, ClientFavorite

FAVORITE_ADD = "engagement.client_favorite.add"
FAVORITE_REMOVE = "engagement.client_favorite.remove"
USAGE_READ = "engagement.app_usage.read"
SCHEDULE_MAX_DAYS, USAGE_MAX_DAYS, USAGE_RETENTION_DAYS = 31, 90, 90


def _acting(session: Session, principal: Principal, client_id: UUID) -> UUID:
    """The signed-in client or one it may act for, else 404 (as feedback does)."""
    identity_id = principal.identity_id
    if (
        principal.kind != "client"
        or identity_id is None
        or households.can_act_for(session, identity_id, client_id) is None
    ):
        raise NotFound()
    return client_id


def _target_exists(session: Session, kind: str, target_id: UUID) -> bool:
    if kind == "program_group":
        group = programs.models.ProgramGroup
        found = select(group.id).where(group.id == target_id, group.deleted_at.is_(None))
        return session.scalar(found) is not None
    # scheduling is outside engagement's allowed imports; RLS keeps this read inside the tenant
    found_type = text("SELECT 1 FROM reservation_type WHERE id = :id AND is_active")
    return session.scalar(found_type, {"id": target_id}) is not None


def list_favorites(session: Session, principal: Principal, client_id: UUID) -> list[ClientFavorite]:
    _acting(session, principal, client_id)
    stmt = select(ClientFavorite).where(ClientFavorite.client_id == client_id)
    return list(session.scalars(stmt.order_by(ClientFavorite.created_at, ClientFavorite.id)))


def add_favorite(session: Session, principal: Principal, data: dict) -> ClientFavorite:
    """Idempotent: a repeat returns the existing row. Errors: unknown-target (not in this tenant, or gone)."""
    client_id = _acting(session, principal, data["client_id"])
    key = {"client_id": client_id, "kind": data["kind"], "target_id": data["target_id"]}
    existing = session.scalar(select(ClientFavorite).filter_by(**key))
    if existing is not None:
        return existing
    if not _target_exists(session, data["kind"], data["target_id"]):
        raise ValidationFailed(
            "Unknown reservation type or program group.", pointer="/target_id", code="unknown-target"
        )
    row = ClientFavorite(**key)
    session.add(row)
    changes = audit.diff(row)  # before the flush clears the history
    session.flush()
    audit.record(session, FAVORITE_ADD, row, changes=changes)
    return row


def remove_favorite(session: Session, principal: Principal, favorite_id: UUID) -> None:
    row = session.get(ClientFavorite, favorite_id)
    if row is None:
        raise NotFound()
    _acting(session, principal, row.client_id)
    audit.record(session, FAVORITE_REMOVE, row, changes={"deleted": True})
    session.delete(row)
    session.flush()


def favorite_schedule(session: Session, principal: Principal, client_id: UUID, start: datetime, end: datetime) -> list:
    """Upcoming sessions of the favourite program groups and of the favourite reservation types, as the portal
    listing shows them (its visibility rules apply). At most SCHEDULE_MAX_DAYS. Errors: invalid-range."""
    if end <= start or end - start > timedelta(days=SCHEDULE_MAX_DAYS):
        raise ValidationFailed(f"Send from < to, at most {SCHEDULE_MAX_DAYS} days apart.", pointer="/to",
                               code="invalid-range")  # fmt: skip
    favorites = list_favorites(session, principal, client_id)
    types = {f.target_id for f in favorites if f.kind == "reservation_type"}
    groups = {f.target_id for f in favorites if f.kind == "program_group"}
    if not favorites:
        return []
    link = programs.models.ProgramSession
    group_of = dict(session.execute(select(link.session_id, link.program_group_id).where(
        link.program_group_id.in_(groups))).all())  # fmt: skip
    listings = programs.selfservice.list_listings(session, principal, client_id,
                                                  {"starts_from": start, "starts_before": end})  # fmt: skip
    return [
        item | {"program_group_id": group_of.get(item["session_id"])}
        for item in listings
        if item["session_id"] in group_of or item["reservation_type_id"] in types
    ]


# --- anonymous usage counts (APP-17) --------------------------------------------------------------------------


def record_usage(session: Session, principal: Principal, items: list[dict]) -> None:
    """Adds each count to today's (UTC) row. Needs a signed-in portal principal but stores nothing about it."""
    if principal.kind != "client":
        raise NotFound()
    totals: Counter[tuple[str, str]] = Counter()
    for item in items:  # one row per key, or the upsert would touch a row twice
        totals[(item["kind"], item["name"])] += item["count"]
    if not totals:
        return
    day, tenant_id = clock.now().date(), session.info["tenant_id"]
    stmt = insert(AppUsageDay).values([
        {"tenant_id": tenant_id, "day": day, "kind": kind, "name": name, "count": count}
        for (kind, name), count in sorted(totals.items())
    ])  # fmt: skip
    session.execute(stmt.on_conflict_do_update(
        constraint="uq_app_usage_day_key",
        set_={"count": AppUsageDay.count + stmt.excluded.count, "updated_at": func.now()},
    ))  # fmt: skip


def list_usage(session: Session, principal: Principal, start: date, end: date, kind: str | None) -> list:
    """Daily rows from `start` to `end` inclusive, at most USAGE_MAX_DAYS. Errors: invalid-range."""
    authorize(principal, USAGE_READ)
    if end < start or (end - start).days >= USAGE_MAX_DAYS:
        raise ValidationFailed(f"Send from <= to, at most {USAGE_MAX_DAYS} days.", pointer="/to", code="invalid-range")
    stmt = select(AppUsageDay).where(AppUsageDay.day.between(start, end))
    if kind is not None:
        stmt = stmt.where(AppUsageDay.kind == kind)
    return list(session.scalars(stmt.order_by(AppUsageDay.day, AppUsageDay.kind, AppUsageDay.name)))


def purge_usage(session: Session) -> int:
    """Retention hook (platform.retention.register_purge): rows older than USAGE_RETENTION_DAYS go, a batch a run."""
    before = clock.now().date() - timedelta(days=USAGE_RETENTION_DAYS)
    old = select(AppUsageDay.id).where(AppUsageDay.day < before).limit(get_settings().retention.batch_rows)
    ids = list(session.scalars(old))
    if ids:
        session.execute(delete(AppUsageDay).where(AppUsageDay.id.in_(ids)))
    return len(ids)
