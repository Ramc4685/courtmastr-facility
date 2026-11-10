"""Households: relationship types, client relationships, portal access and acting rights (FAM-01..03, CLI-15).

can_act_for (ADR 0002 section 5, ADR 0009 section 8.2): an identity acts for a client as `self` (its primary
access row), `manager` (a non-primary access row) or, one hop away from one of its self clients, through an
active relationship whose type read from the actor's side grants acting rights: `guardian` when the type is a
guardianship and the other party is not an adult with their own login, otherwise `delegate`. Checked per
request; nothing is cached.
"""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core import audit, clock, events
from app.core.auth import Principal, authorize, tokens
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.settings import get_settings
from app.modules import platform
from app.modules.clients import service
from app.modules.clients.events import RelationshipChanged
from app.modules.clients.models import Client, ClientPortalAccess, ClientRelationship, RelationshipType
from app.ports import notifications

CONFIRM_TTL = timedelta(days=7)
EDIT = frozenset({"self", "manager", "guardian"})
CAPABILITIES = {
    "book": None, "buy": None, "view_schedule": None,  # every authority
    "edit_profile": EDIT, "consent": EDIT, "documents": EDIT, "invoices": EDIT,
}  # fmt: skip
_MANAGE = "clients.relationship.manage"

notifications.register_template(
    "clients.relationship_confirm",
    subject="$app: confirm a family link",
    body="Hello $name,\n\n$requester asked to be linked to you as $label. Open the link below to accept or "
    "decline.\n\n$url\n\nThe link expires in 7 days. If you do not know this person, decline or ignore it.",
)

# code: (label, inverse code, grants acting rights, is guardianship). Inverse None = symmetric.
SYSTEM_TYPES = {
    "parent_of": ("Parent of", "child_of", True, True),
    "child_of": ("Child of", "parent_of", False, False),
    "guardian_of": ("Guardian of", "ward_of", True, True),
    "ward_of": ("Ward of", "guardian_of", False, False),
    "spouse_of": ("Spouse of", None, True, False),
    "sibling_of": ("Sibling of", None, False, False),
    "other": ("Other", None, False, False),
}


# --- relationship types --------------------------------------------------------------------------------------


def ensure_relationship_types(session: Session) -> None:
    """The system types are seeded per tenant on first use."""
    if session.scalar(select(RelationshipType.id).where(RelationshipType.is_system).limit(1)):
        return
    rows = {}
    for code, (label, _, grants, guardian) in SYSTEM_TYPES.items():
        rows[code] = RelationshipType(
            code=code, label=label, grants_acting_rights=grants, is_guardianship=guardian, is_system=True
        )
        session.add(rows[code])
    session.flush()
    for code, (_, inverse, _, _) in SYSTEM_TYPES.items():
        if inverse:
            rows[code].inverse_type_id = rows[inverse].id
    session.flush()


def _types(session: Session) -> dict[UUID, RelationshipType]:
    ensure_relationship_types(session)
    return {t.id: t for t in session.scalars(select(RelationshipType))}


def type_view(row: RelationshipType, types: dict[UUID, RelationshipType]) -> dict:
    view = {c.key: getattr(row, c.key) for c in RelationshipType.__table__.columns}
    view["inverse_label"] = types[row.inverse_type_id].label if row.inverse_type_id else row.label
    return view


def list_relationship_types(session: Session, principal: Principal | None = None, *, portal: bool = False) -> list:
    if principal is not None and not portal:
        authorize(principal, "clients.client.read")
    types = _types(session)
    rows = sorted(types.values(), key=lambda t: (not t.is_system, t.label.lower()))
    if portal:
        rows = [t for t in rows if t.is_active and t.is_portal_selectable]
    return [type_view(t, types) for t in rows]


def create_relationship_type(session: Session, principal: Principal, data: dict) -> dict:
    authorize(principal, "clients.config.manage")
    types = _types(session)
    inverse = data.get("inverse_type_id")
    if inverse is not None and (inverse not in types or types[inverse].inverse_type_id is not None):
        raise ValidationFailed("The inverse must be an existing type without an inverse.", pointer="/inverse_type_id")
    row = RelationshipType(**data)
    session.add(row)
    session.flush()
    if inverse is not None:
        types[inverse].inverse_type_id = row.id
    types[row.id] = row
    audit.record(session, "clients.config.manage", row, changes={"code": [None, row.code]})
    session.flush()
    return type_view(row, types)


def update_relationship_type(session: Session, principal: Principal, type_id: UUID, data: dict) -> dict:
    authorize(principal, "clients.config.manage")
    types = _types(session)
    row = types.get(type_id) or service._not_found()
    for key, value in data.items():
        if value is None:
            raise ValidationFailed(f"{key} cannot be null.", pointer=f"/{key}")
        setattr(row, key, value)
    audit.record(session, "clients.config.manage", row, changes=audit.diff(row))
    session.flush()
    return type_view(row, types)


# --- relationships -------------------------------------------------------------------------------------------


def _side_type(rel: ClientRelationship, client_id: UUID, types: dict) -> RelationshipType:
    """The type read from `client_id`'s side: the stored type for `from`, its inverse (or itself) for `to`."""
    stored = types[rel.relationship_type_id]
    if rel.from_client_id == client_id or stored.inverse_type_id is None:
        return stored
    return types[stored.inverse_type_id]


def relationship_view(session: Session, rel: ClientRelationship, client_id: UUID, types: dict) -> dict:
    other_id = rel.to_client_id if rel.from_client_id == client_id else rel.from_client_id
    other = session.get(Client, other_id)
    mine, theirs = _side_type(rel, client_id, types), _side_type(rel, other_id, types)
    rights = {(True, True): "both", (True, False): "this_for_other", (False, True): "other_for_this"}.get(
        (mine.grants_acting_rights, theirs.grants_acting_rights), "none"
    )
    return {
        "id": rel.id, "client_id": client_id, "other_client_id": other_id,
        "other_client_name": service.display_name(other), "relationship_type_id": mine.id, "label": mine.label,
        "direction": "outgoing" if rel.from_client_id == client_id else "incoming", "status": rel.status,
        "created_via": rel.created_via, "acting_rights": rights, "confirmed_at": rel.confirmed_at,
        "ended_at": rel.ended_at, "created_at": rel.created_at,
    }  # fmt: skip


def relationships_of(session: Session, client_id: UUID, *, live_only: bool = False) -> list[ClientRelationship]:
    stmt = select(ClientRelationship).where(
        or_(ClientRelationship.from_client_id == client_id, ClientRelationship.to_client_id == client_id)
    )
    if live_only:
        stmt = stmt.where(ClientRelationship.status.in_(("pending", "active")))
    return list(session.scalars(stmt.order_by(ClientRelationship.created_at)))


def list_relationships(session: Session, principal: Principal, client_id: UUID) -> list[dict]:
    client = service.load(session, principal, client_id, "clients.client.read")
    types = _types(session)
    return [relationship_view(session, r, client.id, types) for r in relationships_of(session, client.id)]


def _changed(session: Session, rel: ClientRelationship, action: str, changes: dict) -> None:
    audit.record(session, action, rel, changes=changes)
    events.publish(session, RelationshipChanged(relationship_id=rel.id, status=rel.status), rel.id)


def create_relationship(session: Session, principal: Principal, client_id: UUID, data: dict) -> dict:
    """Staff link (FAM-01): active at once. One live relationship per pair (uq_client_relationship_pair)."""
    authorize(principal, _MANAGE)
    client = service.load(session, principal, client_id, "clients.client.read")
    service._require_live(client)
    other = session.get(Client, data["other_client_id"])
    if other is None or other.id == client.id or other.merged_into_id or other.erased_at:
        raise ValidationFailed("Unknown client.", pointer="/other_client_id")
    types = _types(session)
    kind = types.get(data["relationship_type_id"])
    if kind is None or not kind.is_active:
        raise ValidationFailed("Unknown relationship type.", pointer="/relationship_type_id")
    rel = ClientRelationship(
        from_client_id=client.id, to_client_id=other.id, relationship_type_id=kind.id, status="active",
        created_via="staff", confirmed_at=clock.now(),
    )  # fmt: skip
    session.add(rel)
    session.flush()
    _changed(session, rel, _MANAGE, {"relationship_type_id": [None, str(kind.id)], "status": [None, "active"]})
    return relationship_view(session, rel, client.id, types)


def _live_rel(session: Session, rel_id: UUID) -> ClientRelationship:
    rel = session.get(ClientRelationship, rel_id)
    if rel is None:
        raise NotFound()
    return rel


def approve_relationship(session: Session, principal: Principal, rel_id: UUID) -> dict:
    """Staff approve a pending portal request on the other person's behalf."""
    authorize(principal, _MANAGE)
    rel = _live_rel(session, rel_id)
    if rel.status != "pending":
        raise Conflict("Only a pending relationship can be approved.")
    rel.status, rel.confirmed_at, rel.confirmation_token_hash = "active", clock.now(), None
    _changed(session, rel, _MANAGE, {"status": ["pending", "active"]})
    session.flush()
    return relationship_view(session, rel, rel.from_client_id, _types(session))


def _end(session: Session, rel: ClientRelationship, action: str) -> None:
    if rel.status not in ("pending", "active"):
        raise Conflict("This relationship has already ended.")
    old = rel.status
    rel.status = "declined" if old == "pending" else "ended"
    rel.ended_at, rel.confirmation_token_hash = clock.now(), None
    _changed(session, rel, action, {"status": [old, rel.status]})
    session.flush()


def end_relationship(session: Session, principal: Principal, rel_id: UUID) -> dict:
    authorize(principal, _MANAGE)
    rel = _live_rel(session, rel_id)
    _end(session, rel, _MANAGE)
    return relationship_view(session, rel, rel.from_client_id, _types(session))


# --- acting rights -------------------------------------------------------------------------------------------


def _access_rows(session: Session, identity_id: UUID) -> list[ClientPortalAccess]:
    return list(
        session.scalars(
            select(ClientPortalAccess).where(
                ClientPortalAccess.identity_id == identity_id, ClientPortalAccess.status == "active"
            )
        )
    )


def _has_own_login(session: Session, client_id: UUID) -> bool:
    return (
        session.scalar(
            select(ClientPortalAccess.id).where(
                ClientPortalAccess.client_id == client_id,
                ClientPortalAccess.is_primary,
                ClientPortalAccess.status == "active",
            )
        )
        is not None
    )


def authority(session: Session, identity_id: UUID, client_id: UUID) -> str | None:
    """self | manager | guardian | delegate | None."""
    rows = _access_rows(session, identity_id)
    for row in rows:
        if row.client_id == client_id:
            return "self" if row.is_primary else "manager"
    target = session.get(Client, client_id)
    if target is None or target.status != "active":
        return None
    types = None
    found = None
    for row in (r for r in rows if r.is_primary):
        for rel in session.scalars(
            select(ClientRelationship).where(
                ClientRelationship.status == "active",
                or_(
                    (ClientRelationship.from_client_id == row.client_id)
                    & (ClientRelationship.to_client_id == client_id),
                    (ClientRelationship.to_client_id == row.client_id)
                    & (ClientRelationship.from_client_id == client_id),
                ),
            )
        ):
            types = types or _types(session)
            kind = _side_type(rel, row.client_id, types)
            if not kind.grants_acting_rights:
                continue
            tenant = platform.service.get_tenant(session)
            age = int((tenant.settings or {}).get("age_of_majority", 18))
            adult_with_login = not service.is_minor(target, clock.now().date(), age) and _has_own_login(
                session, client_id
            )
            if kind.is_guardianship and not adult_with_login:
                return "guardian"
            found = "delegate"
    return found


def can_act_for(session: Session, identity_id: UUID, client_id: UUID, capability: str = "book") -> str | None:
    """The authority under which the identity may use `capability` for the client, else None. Internal: the
    portal surfaces of every context call this per request."""
    found = authority(session, identity_id, client_id)
    allowed = CAPABILITIES[capability]
    if found is None or (allowed is not None and found not in allowed):
        return None
    return found


def guardian_ids(session: Session, client_id: UUID) -> list[UUID]:
    """Clients holding an active guardianship relationship to `client_id` (they may sign for a minor, DOC-03).
    Internal: documents calls this when it records a guardian's signature."""
    types = _types(session)
    found = []
    for rel in relationships_of(session, client_id):
        other = rel.to_client_id if rel.from_client_id == client_id else rel.from_client_id
        if rel.status == "active" and _side_type(rel, other, types).is_guardianship:
            found.append(other)
    return found


def actable_client_ids(session: Session, identity_id: UUID) -> list[UUID]:
    """Every client the identity may act for: direct access rows first, then one-hop relationships."""
    rows = _access_rows(session, identity_id)
    ids = [r.client_id for r in sorted(rows, key=lambda r: (not r.is_primary, str(r.client_id)))]
    for row in (r for r in rows if r.is_primary):
        for rel in relationships_of(session, row.client_id, live_only=True):
            other = rel.to_client_id if rel.from_client_id == row.client_id else rel.from_client_id
            if other not in ids and authority(session, identity_id, other):
                ids.append(other)
    return ids


# --- portal access (CLI-15) ----------------------------------------------------------------------------------


def access_view(session: Session, row: ClientPortalAccess) -> dict:
    identity = session.get(platform.models.Identity, row.identity_id)
    return {
        "id": row.id, "identity_id": row.identity_id, "email": identity.email, "is_primary": row.is_primary,
        "status": row.status, "identity_status": identity.status, "invited_at": row.invited_at,
        "activated_at": row.activated_at, "revoked_at": row.revoked_at,
    }  # fmt: skip


def list_portal_access(session: Session, principal: Principal, client_id: UUID) -> list[dict]:
    authorize(principal, "clients.portal_access.manage")
    client = service.load(session, principal, client_id, "clients.client.read")
    rows = session.scalars(
        select(ClientPortalAccess)
        .where(ClientPortalAccess.client_id == client.id)
        .order_by(ClientPortalAccess.created_at)
    )
    return [access_view(session, r) for r in rows]


def invite_to_portal(session: Session, principal: Principal, client_id: UUID, data: dict) -> list[dict]:
    """Invite the client to the portal with one of their addresses (CLI-15). A new identity gets an invitation
    link (platform auth); an address that is already someone's login can only be attached as `manager`, so
    a parent's address on a child's record never merges two people (FAM-02)."""
    authorize(principal, "clients.portal_access.manage")
    client = service.load(session, principal, client_id, "clients.client.read")
    service._require_live(client)
    if client.status != "active":
        raise Conflict("A disabled client cannot be invited.")
    addresses = service.client_addresses(session, client.id)
    email = (data.get("email") or client.primary_email or "").lower()
    if not email or email not in addresses:
        raise ValidationFailed("Choose one of the client's email addresses.", pointer="/email")
    identity = platform.service.find_client_identity(session, email)
    is_primary = True
    if identity is None:
        identity = platform.service.create_client_identity(session, email)
    elif session.scalar(
        select(ClientPortalAccess.id).where(
            ClientPortalAccess.identity_id == identity.id,
            ClientPortalAccess.is_primary,
            ClientPortalAccess.client_id != client.id,
            ClientPortalAccess.status != "revoked",
        )  # fmt: skip
    ):
        if not data.get("attach_as_manager"):
            raise Conflict(
                "This address already signs in as another person. Attach it as a manager instead.",
                code="identity-in-use",
            )
        is_primary = False
    if is_primary and _has_own_login(session, client.id):
        raise Conflict("This client already has a portal login.", code="already-invited")
    row = session.scalar(
        select(ClientPortalAccess).where(
            ClientPortalAccess.identity_id == identity.id, ClientPortalAccess.client_id == client.id
        )
    )
    live = identity.status == "active"
    if row is None:
        row = ClientPortalAccess(identity_id=identity.id, client_id=client.id, is_primary=is_primary)
        session.add(row)
    row.status, row.revoked_at = ("active" if live else "invited"), None
    row.invited_at, row.invited_by_staff_user_id = clock.now(), principal.staff_user_id
    row.activated_at = row.activated_at or (clock.now() if live else None)
    session.flush()
    if identity.status == "invited":
        platform.auth.issue_link(session, identity, platform.models.TokenPurpose.INVITE, timedelta(days=7))
    audit.record(
        session, "clients.portal_access.manage", client, location_id=client.home_location_id,
        changes={"portal_invited": email, "is_primary": is_primary},
    )  # fmt: skip
    return list_portal_access(session, principal, client.id)


def revoke_portal_access(session: Session, principal: Principal, client_id: UUID) -> list[dict]:
    """Revoke every access row to this client; identities left with nothing are disabled and signed out."""
    authorize(principal, "clients.portal_access.manage")
    client = service.load(session, principal, client_id, "clients.client.read")
    rows = list(
        session.scalars(
            select(ClientPortalAccess).where(
                ClientPortalAccess.client_id == client.id, ClientPortalAccess.status != "revoked"
            )
        )
    )
    if not rows:
        raise Conflict("This client has no portal access to revoke.")
    for row in rows:
        row.status, row.revoked_at = "revoked", clock.now()
    session.flush()
    for row in rows:
        if not _access_rows(session, row.identity_id):
            platform.service.disable_client_identity(session, row.identity_id)
    audit.record(
        session, "clients.portal_access.manage", client, location_id=client.home_location_id,
        changes={"portal_revoked": True},
    )  # fmt: skip
    return list_portal_access(session, principal, client.id)


# --- portal surface ------------------------------------------------------------------------------------------

PORTAL_FIELDS = (
    "member_number", "gender", "birth_on", "primary_email", "phone_mobile", "phone_home", "phone_work",
    "address_line1", "address_line2", "city", "region", "postal_code", "country_code", "custom_values",
)  # fmt: skip


def _portal_principal(principal: Principal) -> UUID:
    if principal.kind != "client" or principal.identity_id is None:
        raise NotFound()  # staff tokens never reach a client's portal view
    return principal.identity_id


def _portal_load(session: Session, principal: Principal, client_id: UUID, capability: str) -> tuple[Client, str]:
    identity_id = _portal_principal(principal)
    found = can_act_for(session, identity_id, client_id, capability)
    if found is None:
        raise NotFound()
    return session.get(Client, client_id), found


def portal_view(client: Client, found: str) -> dict:
    """Delegates see names only; self, manager and guardian see the profile they may edit."""
    view = {
        "id": client.id, "first_name": client.first_name, "last_name": client.last_name,
        "preferred_name": client.preferred_name, "authority": found, "can_edit": found in EDIT,
    }  # fmt: skip
    if found in EDIT:
        view.update({f: getattr(client, f) for f in PORTAL_FIELDS})
    else:
        view["member_number"] = None
    return view


def portal_list_clients(session: Session, principal: Principal) -> list[dict]:
    identity_id = _portal_principal(principal)
    out = []
    for client_id in actable_client_ids(session, identity_id):
        found = authority(session, identity_id, client_id)
        out.append(portal_view(session.get(Client, client_id), found))
    return out


def portal_get_client(session: Session, principal: Principal, client_id: UUID) -> dict:
    client, found = _portal_load(session, principal, client_id, "book")
    return portal_view(client, found)


def portal_update_client(session: Session, principal: Principal, client_id: UUID, data: dict) -> dict:
    client, found = _portal_load(session, principal, client_id, "edit_profile")
    changes = service.apply_update(session, client, data, context="portal", actor_staff_id=None)
    if changes:
        audit.record(session, "clients.client.update", client, location_id=client.home_location_id, changes=changes)
        events.publish(session, service.ClientUpdated(client_id=client.id), client.id)
    session.flush()
    return portal_view(client, found)


def portal_get_emergency_contacts(session: Session, principal: Principal, client_id: UUID) -> list:
    client, _ = _portal_load(session, principal, client_id, "edit_profile")
    return service.emergency_contacts(session, client.id)


def portal_replace_emergency_contacts(session: Session, principal: Principal, client_id: UUID, contacts: list) -> list:
    client, _ = _portal_load(session, principal, client_id, "edit_profile")
    rows = service.write_emergency_contacts(session, client, contacts)
    audit.record(
        session, "clients.client.update", client, location_id=client.home_location_id,
        changes={"emergency_contacts": True},
    )  # fmt: skip
    return rows


def _self_client(session: Session, principal: Principal) -> Client:
    identity_id = _portal_principal(principal)
    row = next((r for r in _access_rows(session, identity_id) if r.is_primary), None)
    if row is None:
        raise Conflict("Only an account holder can manage family links.", code="no-self-client")
    return session.get(Client, row.client_id)


def portal_list_relationships(session: Session, principal: Principal) -> list[dict]:
    me = _self_client(session, principal)
    types = _types(session)
    return [relationship_view(session, r, me.id, types) for r in relationships_of(session, me.id)]


def _portal_type(session: Session, type_id: UUID) -> tuple[RelationshipType, dict]:
    types = _types(session)
    kind = types.get(type_id)
    if kind is None or not kind.is_active or not kind.is_portal_selectable:
        raise ValidationFailed("Unknown relationship type.", pointer="/relationship_type_id")
    return kind, types


def portal_request_relationship(session: Session, principal: Principal, data: dict) -> None:
    """Ask another account holder to confirm a link (FAM-03). Always answers the same way, so the portal
    cannot be used to find out who has an account. Matches one active client with that address, those names
    and their own login; sends them a single-use confirmation link."""
    me = _self_client(session, principal)
    kind, _ = _portal_type(session, data["relationship_type_id"])
    email = data["email"].lower()
    candidates = [
        c
        for c in session.scalars(
            select(Client).where(
                Client.status == "active",
                Client.merged_into_id.is_(None),
                Client.id != me.id,
                Client.id.in_(select(service.ClientEmail.client_id).where(service.ClientEmail.email == email)),
            )
        )
        if c.first_name.lower() == data["first_name"].lower()
        and c.last_name.lower() == data["last_name"].lower()
        and _has_own_login(session, c.id)
    ]
    if len(candidates) != 1:
        return
    other = candidates[0]
    live = session.scalar(
        select(ClientRelationship.id).where(
            ClientRelationship.status.in_(("pending", "active")),
            or_(
                (ClientRelationship.from_client_id == me.id) & (ClientRelationship.to_client_id == other.id),
                (ClientRelationship.from_client_id == other.id) & (ClientRelationship.to_client_id == me.id),
            ),
        )
    )
    if live:
        return
    raw, hashed = tokens.mint("fhr", session.info["tenant_id"])
    rel = ClientRelationship(
        from_client_id=me.id, to_client_id=other.id, relationship_type_id=kind.id, status="pending",
        created_via="portal", requested_by_identity_id=principal.identity_id,
        confirmation_token_hash=hashed, confirmation_expires_at=clock.now() + CONFIRM_TTL,
    )  # fmt: skip
    session.add(rel)
    session.flush()
    _changed(session, rel, "clients.relationship.request", {"status": [None, "pending"]})
    settings = get_settings()
    notifications.send(
        session, "clients.relationship_confirm", other.primary_email or email,
        {
            "app": settings.app.display_name, "name": other.first_name, "requester": service.display_name(me),
            "label": kind.label.lower(), "url": f"{settings.app.web_base_url}/relationship-confirm#token={raw}",
        },
    )  # fmt: skip


def decide_relationship(session: Session, token: str, decision: str) -> dict:
    """Public: the emailed link's token is the other person's answer. Single use, expires in 7 days."""
    rel = session.scalar(
        select(ClientRelationship)
        .where(ClientRelationship.confirmation_token_hash == tokens.digest(token))
        .with_for_update()
    )
    if rel is None or rel.status != "pending" or rel.confirmation_expires_at <= clock.now():
        raise NotFound("This link is not valid or has expired.", code="token-invalid")
    if decision == "accept":
        rel.status, rel.confirmed_at, rel.confirmation_token_hash = "active", clock.now(), None
        _changed(session, rel, "clients.relationship.confirm", {"status": ["pending", "active"]})
    else:
        _end(session, rel, "clients.relationship.confirm")
    session.flush()
    return {"status": rel.status}


def portal_create_dependent(session: Session, principal: Principal, data: dict) -> dict:
    """A family member without a login of their own (FAM-02): a client record created by the account holder,
    linked at once and managed through a non-primary access row. The email may repeat the parent's."""
    me = _self_client(session, principal)
    kind, _ = _portal_type(session, data["relationship_type_id"])
    if not kind.grants_acting_rights:
        raise ValidationFailed(
            "Choose a relationship that lets you manage this person.", pointer="/relationship_type_id"
        )
    body = {k: data.get(k) for k in ("first_name", "last_name", "birth_on", "gender")}
    body["home_location_id"] = me.home_location_id
    if data.get("email"):
        body["emails"] = [{"email": data["email"], "is_primary": True}]
    child = service._create(session, principal, body, context="portal", created_via="portal", verify=False)
    rel = ClientRelationship(
        from_client_id=me.id, to_client_id=child.id, relationship_type_id=kind.id, status="active",
        created_via="portal", requested_by_identity_id=principal.identity_id, confirmed_at=clock.now(),
    )  # fmt: skip
    session.add(rel)
    session.add(
        ClientPortalAccess(
            identity_id=principal.identity_id,
            client_id=child.id,
            is_primary=False,
            status="active",
            invited_at=clock.now(),
            activated_at=clock.now(),
        )  # fmt: skip
    )
    session.flush()
    _changed(session, rel, "clients.relationship.request", {"status": [None, "active"]})
    return portal_view(child, "manager")


def portal_end_relationship(session: Session, principal: Principal, rel_id: UUID) -> dict:
    me = _self_client(session, principal)
    rel = session.get(ClientRelationship, rel_id)
    if rel is None or me.id not in (rel.from_client_id, rel.to_client_id):
        raise NotFound()
    _end(session, rel, "clients.relationship.end")
    return relationship_view(session, rel, me.id, _types(session))
