"""engagement service (slice): communication preferences and the consent log (CLI-16, data-model-programs 3.2).

Every change appends a consent_event (append-only) and upserts the current communication_preference row,
which points at the event that set it. An absent row means the topic default: service topics are on,
marketing topics are off until the client opts in. Opting in on an email address needs that address to be
verified (double opt-in, CLI-02). The send gate other contexts call is `is_subscribed`.
"""

from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core import audit, clock
from app.core.auth import Principal
from app.core.errors import ValidationFailed
from app.modules.clients import households, merge
from app.modules.clients import service as clients
from app.modules.engagement.models import CommunicationPreference, ConsentEvent
from app.modules.platform import privacy

TOPICS = {
    "email": ("session_reminders", "card_expiration", "email_campaigns", "league_alerts"),
    "sms": ("session_reminders", "sms_marketing", "league_alerts"),
    "push": ("push_announcements", "session_reminders", "league_alerts"),
}
MARKETING = frozenset({"email_campaigns", "sms_marketing", "push_announcements"})


def _addresses(session: Session, client) -> dict[str, list[str | None]]:
    return {
        "email": clients.client_addresses(session, client.id),
        "sms": [client.phone_mobile] if client.phone_mobile else [],
        "push": [None],
    }


def preferences(session: Session, client) -> list[dict]:
    """The full matrix for the client's current addresses, stored rows over defaults."""
    stored = {
        (r.channel, r.address.lower() if r.address else None, r.topic): r
        for r in session.scalars(select(CommunicationPreference).where(CommunicationPreference.client_id == client.id))
    }
    out = []
    for channel, addresses in _addresses(session, client).items():
        for address in addresses:
            for topic in TOPICS[channel]:
                row = stored.get((channel, address.lower() if address else None, topic))
                out.append({
                    "channel": channel, "address": address, "topic": topic,
                    "is_subscribed": row.is_subscribed if row else topic not in MARKETING,
                    "is_default": row is None, "source": row.source if row else None,
                    "changed_at": row.changed_at if row else None,
                })  # fmt: skip
    return out


def _apply(session: Session, client, changes: list[dict], *, source: str, actor_type: str, actor_id, basis: str, note):
    current = _addresses(session, client)
    for index, change in enumerate(changes):
        channel, topic = change["channel"], change["topic"]
        address = change.get("address")
        address = address.lower() if address and channel == "email" else address
        if topic not in TOPICS[channel]:
            raise ValidationFailed("This topic is not sent on this channel.", pointer=f"/changes/{index}/topic")
        if address not in [a.lower() if a and channel == "email" else a for a in current[channel]]:
            raise ValidationFailed("Not one of the client's addresses.", pointer=f"/changes/{index}/address")
        if (
            change["is_subscribed"]
            and channel == "email"
            and not clients.email_is_verified(session, client.id, address)
        ):
            raise ValidationFailed(
                "Verify this address before subscribing it.",
                pointer=f"/changes/{index}/address",
                code="email-unverified",
            )
        now = clock.now()
        event = ConsentEvent(
            client_id=client.id, channel=channel, address=address, topic=topic,
            kind="opt_in" if change["is_subscribed"] else "opt_out", basis=basis, source=source,
            actor_type=actor_type, actor_id=actor_id, note=note, occurred_at=now,
        )  # fmt: skip
        session.add(event)
        session.flush()
        values = {
            "is_subscribed": change["is_subscribed"], "source": source, "changed_by_actor_type": actor_type,
            "changed_by_actor_id": actor_id, "changed_at": now, "consent_event_id": event.id,
        }  # fmt: skip
        session.execute(
            insert(CommunicationPreference)
            .values(
                tenant_id=session.info["tenant_id"],
                client_id=client.id,
                channel=channel,
                address=address,
                topic=topic,
                **values,
            )  # fmt: skip
            .on_conflict_do_update(constraint="uq_communication_preference", set_=values)
        )
    audit.record(session, "clients.consent.update", client, location_id=client.home_location_id,
                 changes={"communication_preferences": True})  # fmt: skip
    session.flush()


def get_client_preferences(session: Session, principal: Principal, client_id: UUID) -> list[dict]:
    client = clients.load(session, principal, client_id, "clients.client.read")
    return preferences(session, client)


def put_client_preferences(session: Session, principal: Principal, client_id: UUID, data: dict) -> list[dict]:
    """Staff record a consent the client gave them: the note (how and when) is required."""
    client = clients.load(session, principal, client_id, "clients.consent.update")
    clients._require_live(client)
    if principal.kind == "staff" and not data.get("note"):
        raise ValidationFailed("Say how the client gave this consent.", pointer="/note")
    _apply(session, client, data["changes"], source="staff", actor_type="staff" if principal.kind == "staff" else "system",
           actor_id=principal.staff_user_id, basis=data.get("basis", "express"), note=data.get("note"))  # fmt: skip
    return preferences(session, client)


def _portal_client(session: Session, principal: Principal, client_id: UUID):
    if (
        principal.kind != "client"
        or households.can_act_for(session, principal.identity_id, client_id, "consent") is None
    ):
        from app.core.errors import NotFound  # noqa: PLC0415

        raise NotFound()
    return clients.get(session, client_id)


def get_portal_preferences(session: Session, principal: Principal, client_id: UUID) -> list[dict]:
    return preferences(session, _portal_client(session, principal, client_id))


def put_portal_preferences(session: Session, principal: Principal, client_id: UUID, data: dict) -> list[dict]:
    client = _portal_client(session, principal, client_id)
    _apply(session, client, data["changes"], source="portal", actor_type="client", actor_id=principal.identity_id,
           basis="express", note=None)  # fmt: skip
    return preferences(session, client)


def is_subscribed(session: Session, client_id: UUID, channel: str, topic: str, address: str | None = None) -> bool:
    """Internal send gate: may this message go to this address? Erased or disabled clients get nothing."""
    client = clients.get(session, client_id)
    if client.erased_at or client.status != "active":
        return False
    address = address.lower() if address and channel == "email" else address
    row = session.scalar(
        select(CommunicationPreference).where(
            CommunicationPreference.client_id == client_id,
            CommunicationPreference.channel == channel,
            CommunicationPreference.topic == topic,
            CommunicationPreference.address.is_(None)
            if address is None
            else CommunicationPreference.address == address,
        )  # fmt: skip
    )
    if row is not None:
        return row.is_subscribed
    return topic not in MARKETING


# --- merge and erasure handlers ------------------------------------------------------------------------------


def _repoint(session: Session, loser_id: UUID, survivor_id: UUID) -> None:
    """Consent history follows the person; a survivor row for the same address and topic wins over the
    loser's (the loser's is dropped, its history kept in consent_event)."""
    have = {
        (r.channel, r.address, r.topic)
        for r in session.scalars(
            select(CommunicationPreference).where(CommunicationPreference.client_id == survivor_id)
        )
    }
    for row in session.scalars(select(CommunicationPreference).where(CommunicationPreference.client_id == loser_id)):
        if (row.channel, row.address, row.topic) in have:
            session.delete(row)
        else:
            row.client_id = survivor_id
    session.flush()
    # consent_event is append-only for fh_app; the re-point runs through a narrow SECURITY DEFINER function
    session.execute(text("SELECT app.repoint_consent_event(:a, :b)"), {"a": loser_id, "b": survivor_id})


def _export(session: Session, client_id: UUID) -> dict:
    rows = session.scalars(
        select(ConsentEvent).where(ConsentEvent.client_id == client_id).order_by(ConsentEvent.occurred_at)
    )
    return {
        "consent_events": [
            {
                "channel": e.channel,
                "address": e.address,
                "topic": e.topic,
                "kind": e.kind,
                "basis": e.basis,
                "source": e.source,
                "occurred_at": e.occurred_at,
            }  # fmt: skip
            for e in rows
        ]
    }


def _erase(session: Session, client_id: UUID) -> dict:
    """Preferences go; the consent log keeps opt-outs as proof with the address hashed (opt-ins deleted)."""
    deleted = session.query(CommunicationPreference).filter(CommunicationPreference.client_id == client_id).delete()
    kept = session.execute(text("SELECT app.erase_consent_event(:c)"), {"c": client_id}).scalar()
    return {"communication_preference": deleted, "consent_event_kept_hashed": kept}


merge.register_merge_handler("engagement", tables=("communication_preference", "consent_event"), repoint=_repoint)
privacy.register_subject_handler(
    "engagement", tables=("communication_preference", "consent_event"), export=_export, erase=_erase
)
