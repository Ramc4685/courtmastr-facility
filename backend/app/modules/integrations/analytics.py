"""Analytics on registration pages (INT-13): a tenant-wide `google_analytics` connection holds a measurement id
and the domains to link with, so a visit that starts on the facility's own site keeps its campaign through
the hosted portal and checkout. The id is public by design (it ships in every tagged page). The SPA does not
load the tag yet: security-baseline V10 and section 14 forbid third-party analytics in web and mobile (README)."""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFound, ValidationFailed
from app.modules.integrations.models import ConnectionStatus, ExternalConnection, Provider

KEYS = {"measurement_id", "linked_domains"}
_ID = re.compile(r"^G-[A-Z0-9]{4,16}$")
_DOMAIN = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
MAX_DOMAINS = 10


def clean(settings: dict) -> dict:
    """Validated settings: `measurement_id` (G-...) and `linked_domains` (comma-separated host names)."""
    unknown = set(settings) - KEYS
    if unknown:
        key = sorted(unknown)[0]
        raise ValidationFailed(f"Unknown setting {key}", pointer=f"/settings/{key}")
    measurement_id = str(settings.get("measurement_id") or "").strip().upper()
    if not _ID.match(measurement_id):
        raise ValidationFailed("A measurement id looks like G-XXXXXXX", pointer="/settings/measurement_id")
    raw = settings.get("linked_domains") or ""
    domains = sorted({d.strip().lower() for d in str(raw).split(",") if d.strip()})
    bad = [d for d in domains if not _DOMAIN.match(d)]
    if bad or len(domains) > MAX_DOMAINS:
        raise ValidationFailed(
            f"Linked domains are up to {MAX_DOMAINS} host names, comma-separated", pointer="/settings/linked_domains"
        )
    return {"measurement_id": measurement_id, "linked_domains": ",".join(domains)}


def connect(row: ExternalConnection) -> None:
    """Internal (service.create_external_connection): tenant-wide only, active at once."""
    if row.location_id is not None:
        raise ValidationFailed("Analytics covers every location; omit location_id", pointer="/location_id")
    row.settings = clean(row.settings or {})
    row.external_account_id = row.settings["measurement_id"]


def public_config(session: Session) -> dict:
    """Anonymous (tenant from the host): the tag settings, or 404 when the tenant has none active."""
    row = session.scalar(
        select(ExternalConnection).where(
            ExternalConnection.provider == Provider.GOOGLE_ANALYTICS,
            ExternalConnection.status == ConnectionStatus.ACTIVE,
        )
    )
    if row is None:
        raise NotFound()
    domains = row.settings.get("linked_domains") or ""
    return {"measurement_id": row.settings["measurement_id"], "linked_domains": [d for d in domains.split(",") if d]}
