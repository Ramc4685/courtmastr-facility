"""Duplicates and merge (CLI-13), and the clients side of GDPR erasure (security-baseline 4.2).

Merge runs in one transaction: every context that holds rows by client id registers a handler here
(`register_merge_handler`) that re-points the loser's rows to the survivor, and may veto with a precheck
blocker. A meta-test fails when a table with a foreign key to `client` is covered by no handler. The loser
stays as a tombstone (`merged_into_id`), never deleted, so the ledger and audit trail keep their subject.
"""

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session, aliased

from app.core import audit, clock, events
from app.core.auth import Principal, authorize
from app.core.errors import Conflict, ValidationFailed
from app.modules import platform
from app.modules.clients import files, households, service
from app.modules.clients.events import ClientMerged
from app.modules.clients.models import (
    Client,
    ClientAlert,
    ClientEmail,
    ClientEmergencyContact,
    ClientMerge,
    ClientNote,
    ClientPortalAccess,
    ClientRecentView,
    ClientRelationship,
    ClientTag,
    ClientTask,
)
from app.modules.platform import privacy


@dataclass(frozen=True)
class MergeHandler:
    context: str
    tables: tuple[str, ...]  # tables whose client foreign keys this handler re-points
    repoint: Callable[[Session, UUID, UUID], None]  # (session, loser_id, survivor_id)
    precheck: Callable[[Session, UUID, UUID], list[dict]] | None = None  # -> blockers {code, detail}


HANDLERS: dict[str, MergeHandler] = {}


def register_merge_handler(context: str, *, tables, repoint, precheck=None) -> None:
    HANDLERS[context] = MergeHandler(context, tuple(tables), repoint, precheck)


# --- duplicates (data-model 1.16) ----------------------------------------------------------------------------


def _list_item(client: Client) -> dict:
    return {c.key: getattr(client, c.key) for c in Client.__table__.columns}


def _reasons(session: Session, a: Client, b: Client) -> list[str]:
    reasons = []
    if a.birth_on and a.birth_on == b.birth_on:
        reasons.append("same_birth_date")
    if service.matchable_addresses(session, a) & service.matchable_addresses(session, b):
        reasons.append("shared_email")
    if a.phone_mobile and a.phone_mobile == b.phone_mobile:
        reasons.append("shared_mobile")
    return reasons or ["same_name"]


def list_duplicates(session: Session, principal: Principal, client_id: UUID | None = None, limit: int = 50) -> list:
    """Candidate groups: each live client with the others matching the duplicate predicate."""
    authorize(principal, "clients.client.merge")
    other, predicate = service._duplicate_of(aliased(Client))
    stmt = (
        select(Client, other)
        .join(other, predicate)
        .where(Client.merged_into_id.is_(None), Client.erased_at.is_(None))
        .order_by(func.lower(Client.last_name), Client.id, other.id)
        .limit(limit * 5)
    )
    if client_id is not None:
        stmt = stmt.where(Client.id == client_id)
    groups: dict[UUID, dict] = {}
    seen: set[frozenset] = set()
    for a, b in session.execute(stmt):
        pair = frozenset((a.id, b.id))
        if pair in seen and client_id is None:
            continue
        seen.add(pair)
        group = groups.setdefault(a.id, {"client": _list_item(a), "candidates": []})
        group["candidates"].append({"client": _list_item(b), "reasons": _reasons(session, a, b)})
    return list(groups.values())[:limit]


# --- merge ---------------------------------------------------------------------------------------------------

BACKFILL = (
    "preferred_name", "gender", "birth_on", "organization_name", "phone_mobile", "phone_home", "phone_work",
    "address_line1", "address_line2", "city", "region", "postal_code", "country_code", "client_category_id",
    "referral_category_id", "referral_source", "default_trainer_staff_user_id",
    "default_salesperson_staff_user_id", "comments", "medical_notes", "member_number",
    "photo_file_id",  # CLI-12: a survivor without a photo takes the loser's
)  # fmt: skip


def _load_pair(session: Session, survivor_id: UUID, loser_ids: list[UUID]) -> tuple[Client, list[Client]]:
    survivor = session.get(Client, survivor_id)
    if survivor is None:
        service._not_found()
    service._require_live(survivor)
    if survivor_id in loser_ids or len(set(loser_ids)) != len(loser_ids):
        raise ValidationFailed("Each record can be merged once and not into itself.", pointer="/merged_client_ids")
    losers = []
    for index, loser_id in enumerate(loser_ids):
        loser = session.get(Client, loser_id)
        if loser is None or loser.merged_into_id or loser.erased_at:
            raise ValidationFailed("Unknown or already merged client.", pointer=f"/merged_client_ids/{index}")
        losers.append(loser)
    return survivor, losers


def _blockers(session: Session, survivor: Client, losers: list[Client]) -> list[dict]:
    blockers = []
    for loser in losers:
        if survivor.created_via == "portal" and loser.created_via != "portal":
            # the portal record's manager access would otherwise reach the real record's history (P-06)
            blockers.append({"context": "clients", "client_id": loser.id, "code": "survivor-portal-created",
                             "detail": "A record created in the portal cannot absorb one created by staff; "
                                       "keep the staff record as the survivor."})  # fmt: skip
        loser_holders = _holders(session, loser.id) | _own_login(session, loser.id)
        if loser_holders and _holders(session, survivor.id) - loser_holders:
            # the loser is someone else's dependent: its guardian loses it, the survivor's gains it (backlog 29).
            # A loser nobody acts for is a desk duplicate of the same person, and merges as before.
            blockers.append({"context": "clients", "client_id": loser.id, "code": "survivor-has-other-managers",
                             "detail": "Each record has its own managers or guardians; remove the access that "
                                       "should not carry over first."})  # fmt: skip
        for handler in HANDLERS.values():
            for b in handler.precheck(session, loser.id, survivor.id) if handler.precheck else []:
                blockers.append({"context": handler.context, "client_id": loser.id, **b})
    return blockers


def _backfill_fields(survivor: Client, losers: list[Client]) -> list[str]:
    return [f for f in BACKFILL if getattr(survivor, f) is None and any(getattr(x, f) is not None for x in losers)]


def _own_login(session: Session, client_id: UUID) -> set[tuple[str, UUID]]:
    """The client's own live portal sign-in: a record someone signs in to is held, even with no managers."""
    rows = session.scalars(select(ClientPortalAccess.identity_id).where(
        ClientPortalAccess.client_id == client_id, ClientPortalAccess.is_primary.is_(True),
        ClientPortalAccess.status != "revoked"))  # fmt: skip
    return {("identity", i) for i in rows}


def _carried_rights(session: Session, loser_id: UUID) -> tuple[list[ClientPortalAccess], list[ClientRelationship]]:
    """What a merge would otherwise carry over as acting rights: the loser's live manager access rows and its
    live relationships whose type grants acting rights from either side. Merge revokes or ends them."""
    access = list(
        session.scalars(
            select(ClientPortalAccess).where(
                ClientPortalAccess.client_id == loser_id,
                ClientPortalAccess.is_primary.is_(False),
                ClientPortalAccess.status != "revoked",
            )
        )
    )
    types = households._types(session)
    rels = [
        r
        for r in households.relationships_of(session, loser_id, live_only=True)
        if any(
            households._side_type(r, side, types).grants_acting_rights for side in (r.from_client_id, r.to_client_id)
        )
    ]
    return access, rels


def _holders(session: Session, client_id: UUID) -> set[tuple[str, UUID]]:
    """Everyone with acting rights over a client: manager logins and the other side of acting relationships."""
    access, rels = _carried_rights(session, client_id)
    return {("identity", a.identity_id) for a in access} | {
        ("client", r.to_client_id if r.from_client_id == client_id else r.from_client_id) for r in rels
    }


def _review(session: Session, losers: list[Client]) -> list[dict]:
    items = []
    for loser in losers:
        access, rels = _carried_rights(session, loser.id)
        items += [{"client_id": loser.id, "kind": "portal_access", "id": row.id,
                   "detail": "A manager's portal access to the merged record is revoked; grant it again if needed."}
                  for row in access]  # fmt: skip
        items += [{"client_id": loser.id, "kind": "relationship", "id": rel.id,
                   "detail": "A family link with acting rights on the merged record ends; link it again if needed."}
                  for rel in rels]  # fmt: skip
    return items


def precheck(session: Session, principal: Principal, survivor_id: UUID, loser_ids: list[UUID]) -> dict:
    authorize(principal, "clients.client.merge")
    survivor, losers = _load_pair(session, survivor_id, loser_ids)
    blockers = _blockers(session, survivor, losers)
    return {
        "survivor_client_id": survivor.id, "merged_client_ids": [x.id for x in losers], "blockers": blockers,
        "review": _review(session, losers), "backfill_fields": _backfill_fields(survivor, losers),
        "can_merge": not blockers,
    }  # fmt: skip


def merge(session: Session, principal: Principal, survivor_id: UUID, loser_ids: list[UUID]) -> Client:
    """Merge each loser into the survivor. Blank survivor fields take the first loser's value; every handler
    re-points; the loser becomes a tombstone; one client_merge row per loser; both aggregates audited."""
    authorize(principal, "clients.client.merge")
    if principal.staff_user_id is None:
        raise ValidationFailed("Only a staff user can merge clients.")
    survivor, losers = _load_pair(session, survivor_id, loser_ids)
    blockers = _blockers(session, survivor, losers)
    if blockers:
        raise Conflict("These records cannot be merged yet.", code="merge-blocked", blockers=[
            {**b, "client_id": str(b["client_id"])} for b in blockers
        ])  # fmt: skip
    now = clock.now()
    for loser in losers:
        filled = {}
        for field in _backfill_fields(survivor, [loser]):
            filled[field] = True  # names only: client_merge is append-only and erasure cannot clear values
            value = getattr(loser, field)
            if field == "member_number":  # unique per tenant: free it before the survivor takes it
                source, loser.member_number, loser.member_number_source = loser.member_number_source, None, None
                session.flush()
                survivor.member_number_source = source
            setattr(survivor, field, value)
        survivor.custom_values = loser.custom_values | survivor.custom_values
        session.flush()
        for handler in HANDLERS.values():
            handler.repoint(session, loser.id, survivor.id)
        loser.merged_into_id, loser.merged_at, loser.status = survivor.id, now, "disabled"
        loser.disabled_at = loser.disabled_at or now
        session.add(ClientMerge(
            survivor_client_id=survivor.id, merged_client_id=loser.id, performed_by_staff_user_id=principal.staff_user_id,
            performed_at=now, backfilled_fields=filled,
        ))  # fmt: skip
        session.flush()
        audit.record(session, "clients.client.merge", loser, location_id=loser.home_location_id,
                     changes={"merged_into_id": [None, str(survivor.id)]})  # fmt: skip
        events.publish(session, ClientMerged(client_id=loser.id, survivor_client_id=survivor.id), loser.id)
    survivor.version += 1
    audit.record(session, "clients.client.merge", survivor, location_id=survivor.home_location_id,
                 changes={"absorbed": [str(x.id) for x in losers]})  # fmt: skip
    events.publish(session, service.ClientUpdated(client_id=survivor.id), survivor.id)
    session.flush()
    return survivor


def _repoint_clients(session: Session, loser_id: UUID, survivor_id: UUID) -> None:
    """The clients context's own rows."""
    have = {e.email: e for e in session.scalars(select(ClientEmail).where(ClientEmail.client_id == survivor_id))}
    for row in session.scalars(select(ClientEmail).where(ClientEmail.client_id == loser_id)):
        if row.email in have:
            if row.verified_at and not have[row.email].verified_at:
                have[row.email].verified_at = row.verified_at
            session.delete(row)
        else:
            row.client_id, row.is_primary = survivor_id, False
    session.flush()
    if not any(e.is_primary for e in have.values()):
        first = session.scalar(
            select(ClientEmail).where(ClientEmail.client_id == survivor_id).order_by(ClientEmail.email)
        )
        if first is not None:
            first.is_primary = True
            session.get(Client, survivor_id).primary_email = first.email
    tags = set(session.scalars(select(ClientTag.tag_id).where(ClientTag.client_id == survivor_id)))
    session.execute(delete(ClientTag).where(ClientTag.client_id == loser_id, ClientTag.tag_id.in_(tags)))
    session.execute(update(ClientTag).where(ClientTag.client_id == loser_id).values(client_id=survivor_id))
    offset = session.scalar(
        select(func.coalesce(func.max(ClientEmergencyContact.position), 0)).where(
            ClientEmergencyContact.client_id == survivor_id
        )
    )
    session.execute(
        update(ClientEmergencyContact)
        .where(ClientEmergencyContact.client_id == loser_id)
        .values(client_id=survivor_id, position=ClientEmergencyContact.position + offset)  # fmt: skip
    )
    _repoint_relationships(session, loser_id, survivor_id)
    _repoint_access(session, loser_id, survivor_id)
    for model in (ClientNote, ClientTask, ClientAlert):
        session.execute(update(model).where(model.client_id == loser_id).values(client_id=survivor_id))
    session.execute(delete(ClientRecentView).where(ClientRecentView.client_id == loser_id))
    # earlier tombstones that pointed at the loser now point at the survivor (no chains to walk)
    session.execute(update(Client).where(Client.merged_into_id == loser_id).values(merged_into_id=survivor_id))
    session.flush()


def _repoint_relationships(session: Session, loser_id: UUID, survivor_id: UUID) -> None:
    now = clock.now()
    carried = {r.id for r in _carried_rights(session, loser_id)[1]}
    for rel in session.scalars(
        select(ClientRelationship).where(
            or_(ClientRelationship.from_client_id == loser_id, ClientRelationship.to_client_id == loser_id)
        )
    ):
        other = rel.to_client_id if rel.from_client_id == loser_id else rel.from_client_id
        live = rel.status in ("pending", "active")
        duplicate = live and session.scalar(
            select(ClientRelationship.id).where(
                ClientRelationship.status.in_(("pending", "active")),
                or_(
                    (ClientRelationship.from_client_id == survivor_id) & (ClientRelationship.to_client_id == other),
                    (ClientRelationship.to_client_id == survivor_id) & (ClientRelationship.from_client_id == other),
                ),
            )
        )
        if other == survivor_id or duplicate or rel.id in carried:
            if live:  # a link between the pair, one the survivor has, or one granting acting rights, ends
                rel.status, rel.ended_at, rel.confirmation_token_hash = "ended", now, None
            continue  # ended history stays on the tombstone
        if rel.from_client_id == loser_id:
            rel.from_client_id = survivor_id
        else:
            rel.to_client_id = survivor_id
        session.flush()


def _repoint_access(session: Session, loser_id: UUID, survivor_id: UUID) -> None:
    """A survivor with its own login keeps it: the loser's login is retired (identity `merged`, signed out).
    Otherwise the loser's login moves over. Manager rows never move: they are revoked (staff re-grant them)."""
    survivor_has_self = session.scalar(
        select(ClientPortalAccess.id).where(
            ClientPortalAccess.client_id == survivor_id,
            ClientPortalAccess.is_primary,
            ClientPortalAccess.status != "revoked",
        )  # fmt: skip
    )
    for row in session.scalars(select(ClientPortalAccess).where(ClientPortalAccess.client_id == loser_id)):
        taken = session.scalar(
            select(ClientPortalAccess.id).where(
                ClientPortalAccess.client_id == survivor_id, ClientPortalAccess.identity_id == row.identity_id
            )
        )
        if taken or not row.is_primary or (survivor_has_self and row.status != "revoked"):
            if row.status != "revoked":
                row.status, row.revoked_at = "revoked", clock.now()
                session.flush()
                if row.is_primary and not taken:
                    platform.service.disable_client_identity(session, row.identity_id, status="merged")
            continue
        row.client_id = survivor_id
        session.flush()


register_merge_handler(
    "clients",
    tables=(
        "client",
        "client_email",
        "client_emergency_contact",
        "client_tag",
        "client_relationship",
        "client_portal_access",
        "client_note",
        "client_task",
        "client_alert",
        "client_merge",
        "client_recent_view",
    ),  # fmt: skip
    repoint=_repoint_clients,
)


# --- GDPR erasure: the clients handler (security-baseline 4.2) -----------------------------------------------

ERASED_FIRST, ERASED_LAST = "Erased", "Client"
_ERASE_NULL = (
    "preferred_name", "gender", "birth_on", "organization_name", "primary_email", "phone_mobile", "phone_home",
    "phone_work", "address_line1", "address_line2", "city", "region", "postal_code", "country_code",
    "referral_source", "comments", "medical_notes", "member_number", "member_number_source",
    "photo_file_id",  # its stored_file row is marked purged first (files.purge_rows); bytes wait for K1
)  # fmt: skip


def _subject_ids(session: Session, client_id: UUID) -> list[UUID]:
    """The client and every tombstone merged into it: erasure follows the merge chain."""
    return [client_id, *session.scalars(select(Client.id).where(Client.merged_into_id == client_id))]


def _export_clients(session: Session, client_id: UUID) -> dict:
    out = {}
    for cid in _subject_ids(session, client_id):
        client = session.get(Client, cid)
        out[str(cid)] = {
            "profile": {c.key: getattr(client, c.key) for c in Client.__table__.columns},
            "emails": [{"email": e.email, "verified_at": e.verified_at} for e in
                       session.scalars(select(ClientEmail).where(ClientEmail.client_id == cid))],
            "emergency_contacts": [{"name": e.name, "phone": e.phone, "relationship": e.relationship_label}
                                   for e in service.emergency_contacts(session, cid)],
            "alerts": [{"message": a.message, "created_at": a.created_at} for a in
                       session.scalars(select(ClientAlert).where(ClientAlert.client_id == cid))],
            "notes": [{"kind": n.kind, "subject": n.subject_text, "body": n.body, "occurred_at": n.occurred_at,
                       "attachments": files.export_attachments(session, n.id)}
                      for n in session.scalars(select(ClientNote).where(ClientNote.client_id == cid))],
        }  # fmt: skip
    return out


def _erase_clients(session: Session, client_id: UUID) -> dict:
    """Anonymise the record (names become constants, PII nulled) and delete the rows that only describe the
    person. Billing rows keep their subject id and amounts: the ledger is retained (4.3)."""
    identities = set()
    counts = {}
    subjects = _subject_ids(session, client_id)
    for cid in subjects:
        client = session.get(Client, cid)
        ids = files.file_ids_of(session, client)  # before the photo id and notes go
        # A merge can leave a survivor outside this erasure showing the same photo: that file stays.
        shared = set(session.scalars(
            select(Client.photo_file_id).where(Client.photo_file_id.in_(ids), Client.id.not_in(subjects))
        ))  # fmt: skip
        files.purge_rows(session, [i for i in ids if i not in shared])
        client.first_name, client.last_name = ERASED_FIRST, ERASED_LAST
        for field in _ERASE_NULL:
            setattr(client, field, None)
        client.custom_values, client.status = {}, "disabled"
        client.erased_at = clock.now()
        client.disabled_at = client.disabled_at or clock.now()
        for row in session.scalars(select(ClientPortalAccess).where(ClientPortalAccess.client_id == cid)):
            identities.add(row.identity_id)
        for model in (ClientEmail, ClientEmergencyContact, ClientTag, ClientNote, ClientTask, ClientAlert,
                      ClientRecentView, ClientPortalAccess):  # fmt: skip
            result = session.execute(delete(model).where(model.client_id == cid))
            counts[model.__tablename__] = counts.get(model.__tablename__, 0) + result.rowcount
        result = session.execute(
            delete(ClientRelationship).where(
                or_(ClientRelationship.from_client_id == cid, ClientRelationship.to_client_id == cid)
            )
        )
        counts["client_relationship"] = counts.get("client_relationship", 0) + result.rowcount
    session.flush()
    for identity_id in identities:
        if not session.scalar(select(ClientPortalAccess.id).where(ClientPortalAccess.identity_id == identity_id)):
            platform.service.delete_client_identity(session, identity_id)
    return counts


privacy.register_subject_handler(
    "clients",
    tables=(
        "client",
        "client_email",
        "client_emergency_contact",
        "client_tag",
        "client_relationship",
        "client_portal_access",
        "client_note",
        "client_task",
        "client_alert",
        "client_merge",
        "client_recent_view",
    ),  # fmt: skip
    export=_export_clients,
    erase=_erase_clients,
)
