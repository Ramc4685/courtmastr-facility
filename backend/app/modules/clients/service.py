"""clients service (skeleton): the client record other contexts reference, and its link to a sign-in identity.

Two kinds of function (ADR 0009 section 9): commands and queries take a principal and authorize it; the
functions under "internal" are the cross-context interface and trust that the calling use case authorized.
"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import audit, clock, events
from app.core.api import CONSTRAINT_FIELDS
from app.core.auth import Principal, authorize
from app.core.errors import NotFound, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.modules import platform
from app.modules.clients.events import ClientCreated
from app.modules.clients.models import Client, ClientPortalAccess

_READ = "clients.client.read"
CONSTRAINT_FIELDS["uq_client_tenant_id_member_number"] = "member_number"


def _reads_everyone(principal: Principal) -> bool:
    """`own` reach (coaches) needs the default-trainer and own-booking predicates of rbac-matrix 3.2, which
    arrive with build modules 2 and 4. Until then own reach sees no client: fail closed, never open."""
    authorize(principal, _READ)
    return principal.kind == "system" or principal.permissions.get(_READ) == "all"


def list_clients(session: Session, principal: Principal, query: ListQuery) -> dict:
    """Tenant-wide (CLI-19): the client record is not location-scoped. Default sort is by name."""
    stmt = select(Client)
    if not _reads_everyone(principal):
        stmt = stmt.where(Client.id.is_(None))
    return paginate(
        session, stmt, query, id_column=Client.id,
        sort_fields={
            "last_name": func.lower(Client.last_name), "first_name": func.lower(Client.first_name),
            "created_at": Client.created_at,
        },
        default_sort="last_name,first_name",
        filter_fields={"status": Client.status, "home_location_id": Client.home_location_id},
        search=(Client.first_name, Client.last_name, Client.primary_email, Client.member_number, Client.phone_mobile),
    )  # fmt: skip


def get_client(session: Session, principal: Principal, client_id: UUID) -> Client:
    if not _reads_everyone(principal):
        raise NotFound()
    return get(session, client_id)


def create_client(session: Session, principal: Principal, data: dict) -> Client:
    authorize(principal, "clients.client.create")
    try:
        platform.service.get_location(session, principal, data["home_location_id"])
    except NotFound:
        raise ValidationFailed("Unknown location.", pointer="/home_location_id") from None
    client = Client(**data, member_number_source="manual" if data.get("member_number") else None)
    session.add(client)
    session.flush()
    audit.record(
        session, "clients.client.create", client, location_id=client.home_location_id,
        changes={"home_location_id": [None, str(client.home_location_id)]},
    )  # fmt: skip
    events.publish(session, ClientCreated(client_id=client.id), client.id)
    return client


# --- internal: the cross-context interface -----------------------------------------------------------------


def get(session: Session, client_id: UUID) -> Client:
    """The client, or NotFound. Callers that sell or book should use require_active()."""
    client = session.get(Client, client_id)
    if client is None:
        raise NotFound()
    return client


def require_active(session: Session, client_id: UUID, *, pointer: str = "/client_id") -> Client:
    """The client a new booking, charge or contract may be created for: it exists and is not disabled.
    Raises ValidationFailed on the given body pointer, because the id normally arrives in a request body."""
    client = session.get(Client, client_id)
    if client is None or client.status != "active":
        raise ValidationFailed("Unknown or disabled client.", pointer=pointer)
    return client


def display_name(client: Client) -> str:
    return f"{client.first_name} {client.last_name}"


def link_identity(session: Session, client_id: UUID, identity_id: UUID, *, is_primary: bool = True) -> None:
    """Let a client-kind identity sign in as this client (`active` at once). Idempotent. The invitation flow
    with its emailed link is build module 4; this is the link itself, for seeds and self-registration."""
    exists = session.scalar(
        select(ClientPortalAccess.id).where(
            ClientPortalAccess.client_id == client_id, ClientPortalAccess.identity_id == identity_id
        )
    )
    if exists is None:
        session.add(
            ClientPortalAccess(
                client_id=client_id,
                identity_id=identity_id,
                is_primary=is_primary,
                status="active",
                activated_at=clock.now(),
            )  # fmt: skip
        )
        session.flush()


def client_ids_for_identity(session: Session, identity_id: UUID) -> list[UUID]:
    """The clients a signed-in client principal may act as directly (ADR 0009 section 8: can_act_for's first
    clause). Portal routers of every context resolve `ctx.principal.identity_id` through this."""
    return list(
        session.scalars(
            select(ClientPortalAccess.client_id)
            .where(ClientPortalAccess.identity_id == identity_id, ClientPortalAccess.status == "active")
            .order_by(ClientPortalAccess.is_primary.desc(), ClientPortalAccess.id)
        )
    )
