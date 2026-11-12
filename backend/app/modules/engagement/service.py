"""engagement service (slice): communication preferences and the consent log (CLI-16, data-model-programs 3.2).

Every change appends a consent_event (append-only) and upserts the current communication_preference row,
which points at the event that set it. An absent row means the topic default: service topics are on,
marketing topics are off until the client opts in. Opting in on an email address needs that address to be
verified (double opt-in, CLI-02). The send gate other contexts call is `is_subscribed`.
"""

import re
from datetime import timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import any_, func, literal, or_, select, text, true, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core import audit, clock, events
from app.core.auth import Principal, authorize, authorize_tenant_wide, scope_query, system_principal, tokens
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.core.settings import get_settings
from app.modules import memberships, platform, scheduling
from app.modules.clients import households, merge
from app.modules.clients import service as clients
from app.modules.engagement.domain import rules
from app.modules.engagement.events import CampaignSent, ConsentChanged, MessageBounced
from app.modules.engagement.models import (
    AutomationRule,
    Campaign,
    CommunicationPreference,
    ConsentEvent,
    DeviceRegistration,
    InboxItem,
    Message,
    MessageTemplate,
    NotificationRoute,
    PortalSettings,
    ReminderRule,
    ScheduledNotification,
    Segment,
    Suppression,
    Video,
)
from app.modules.platform import privacy
from app.ports import notifications
from app.ports.email import EmailMessage, send_after_commit

TOPICS = {
    "email": ("session_reminders", "card_expiration", "email_campaigns", "league_alerts"),
    "sms": ("session_reminders", "sms_marketing", "league_alerts"),
    "push": ("push_announcements", "session_reminders", "league_alerts"),
}
MARKETING = frozenset({"email_campaigns", "sms_marketing", "push_announcements"})
IMPLIED = frozenset({"implied_purchase", "implied_inquiry"})  # not consent for marketing in GDPR mode (PLT-16)


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
    gdpr = privacy.is_gdpr_mode(session)
    for index, change in enumerate(changes):
        channel, topic = change["channel"], change["topic"]
        address = change.get("address")
        address = address.lower() if address and channel == "email" else address
        if topic not in TOPICS[channel]:
            raise ValidationFailed("This topic is not sent on this channel.", pointer=f"/changes/{index}/topic")
        if gdpr and change["is_subscribed"] and topic in MARKETING and basis in IMPLIED:
            raise ValidationFailed("GDPR mode needs express consent for marketing.", pointer="/basis",
                                   code="express-consent-required")  # fmt: skip
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
    if row is None:
        return topic not in MARKETING
    if row.is_subscribed and topic in MARKETING and privacy.is_gdpr_mode(session):
        # An implied opt-in recorded before GDPR mode was switched on does not count (PLT-16).
        return session.scalar(select(ConsentEvent.basis).where(ConsentEvent.id == row.consent_event_id)) not in IMPLIED
    return row.is_subscribed


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


# =============================================================================================================
# Build module 14: outbound messaging (MKT), inbox, reminders, automations, portal settings and videos (SSP).
# Rules: every send goes through _deliver(), which applies the gates in one place (inactive client, missing
# address, suppression, consent topic, verified address for marketing). Templates and segments are tenant-wide
# rows; campaigns, rules, routes, settings and videos belong to one location.
# =============================================================================================================

SYSTEM = system_principal("engagement")
_PROVIDER = "smtp"
INBOX_DAYS = 30
UNSUBSCRIBE_DAYS = 90


def _now():
    return clock.now()


def _location_name(session: Session, location_id: UUID | None) -> str:
    return platform.service.location_name(session, location_id) if location_id else ""


def _facility(session: Session) -> str:
    return platform.service.get_tenant(session).name


def _merge_data(session: Session, client=None, location_id: UUID | None = None, **extra) -> dict:
    data = {"facility_name": _facility(session), "location_name": _location_name(session, location_id)}
    if client is not None:
        data |= {"first_name": client.preferred_name or client.first_name, "last_name": client.last_name,
                 "full_name": clients.display_name(client)}  # fmt: skip
    return data | {k: v for k, v in extra.items() if v is not None}


def _local(session: Session, location_id: UUID | None, at) -> str | None:
    """A moment as wall time at the location, for message bodies (overview 3.7)."""
    if at is None or location_id is None:
        return None
    zone = ZoneInfo(platform.service.location_time_zone(session, location_id))
    return at.astimezone(zone).strftime("%a %d %b %Y, %H:%M")


def suppression_active(session: Session, address: str, channel: str = "email") -> bool:
    row = session.scalar(
        select(Suppression).where(Suppression.channel == channel, Suppression.address == address.lower())
    )
    return row is not None and (row.released_at is None or row.is_permanent)


def _footer(session: Session, raw_token: str) -> str:
    url = f"{get_settings().app.web_base_url}/unsubscribe#token={raw_token}"
    return (
        f"\n\n--\nYou receive this because you subscribed to news from {_facility(session)}.\n"
        f"Unsubscribe or change what you receive: {url}\n"
    )


def _deliver(
    session: Session,
    *,
    channel: str = "email",
    category: str,
    topic: str | None,
    subject: str | None,
    body: str,
    client=None,
    to_address: str | None = None,
    staff_user_id: UUID | None = None,
    location_id: UUID | None = None,
    campaign_id: UUID | None = None,
    template_id: UUID | None = None,
    sender_staff_user_id: UUID | None = None,
    source_event_type: str | None = None,
    dedupe_key: str | None = None,
    keep_body: bool = False,
    device_id: UUID | None = None,
) -> Message:
    """Create the message row and send it if every gate passes; otherwise record why it was skipped. A repeated
    dedupe key returns the first message unchanged, which makes event handlers and jobs idempotent."""
    if dedupe_key:
        found = session.scalar(select(Message).where(Message.dedupe_key == dedupe_key))
        if found is not None:
            return found
    if client is not None and to_address is None and channel == "email":
        to_address = client.primary_email
    to_address = to_address.lower() if to_address and channel == "email" else to_address
    row = Message(
        channel=channel, category=category, topic=topic, client_id=client.id if client else None,
        recipient_staff_user_id=staff_user_id, to_address=to_address, campaign_id=campaign_id,
        message_template_id=template_id, location_id=location_id, sender_staff_user_id=sender_staff_user_id,
        subject=subject, body_text=body if keep_body else None, source_event_type=source_event_type,
        dedupe_key=dedupe_key, device_registration_id=device_id, queued_at=_now(),
    )  # fmt: skip
    reason = None
    if client is not None and (client.erased_at or client.status != "active"):
        reason = "inactive_client"
    elif channel == "push":
        reason = None if is_subscribed(session, client.id, "push", topic or "push_announcements") else "unsubscribed"
        reason = reason or "channel_unavailable"  # shortcut: no push provider is wired; the inbox carries it
    elif not to_address or "@" not in to_address:
        reason = "invalid_address"
    elif suppression_active(session, to_address):
        reason = "suppressed"
    elif client is not None and topic and not is_subscribed(session, client.id, "email", topic, to_address):
        reason = "unsubscribed"
    elif (
        client is not None and category == "marketing" and not clients.email_is_verified(session, client.id, to_address)
    ):
        reason = "unverified"
    if reason:
        row.status, row.skip_reason = "skipped", reason
        session.add(row)
        session.flush()
        return row
    text_body = body
    if category == "marketing" and client is not None:
        raw, row.unsubscribe_token_hash = tokens.mint("fhu", session.info["tenant_id"])
        text_body = body + _footer(session, raw)
    row.status, row.sent_at, row.provider = "sent", _now(), _PROVIDER
    session.add(row)
    session.flush()
    send_after_commit(session, EmailMessage(to_address, subject or "", text_body))
    return row


class _Notifier:
    """The notification port's adapter once engagement is loaded: transactional notices from every context are
    logged as message rows (MKT-09) and a suppressed address is skipped. Sessions without a tenant (platform
    sign-in flows) send directly."""

    def deliver(self, session: Session, to: str, subject: str, body: str) -> None:
        if session.info.get("tenant_id") is None or session.info.get("actor") is None:
            send_after_commit(session, EmailMessage(to, subject, body))
            return
        _deliver(session, category="transactional", topic=None, subject=subject, body=body, to_address=to)


def install_notifier() -> None:
    """Called from bootstrap when notifications are not the no-op adapter."""
    notifications.configure(_Notifier())


# --- message templates (MKT-05) ------------------------------------------------------------------------------


def _check_fields(subject, body) -> None:
    unknown = rules.unknown_fields(subject, body)
    if unknown:
        raise ValidationFailed(f"Unknown merge fields: {', '.join(unknown)}.", pointer="/body_text",
                               code="unknown-merge-field")  # fmt: skip


def _template(session: Session, template_id: UUID) -> MessageTemplate:
    row = session.get(MessageTemplate, template_id)
    if row is None:
        raise NotFound()
    return row


def list_templates(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, "engagement.campaign.read")
    return paginate(
        session, select(MessageTemplate), query, id_column=MessageTemplate.id,
        sort_fields={"name": MessageTemplate.name, "updated_at": MessageTemplate.updated_at}, default_sort="name",
        filter_fields={"channel": MessageTemplate.channel, "origin": MessageTemplate.origin,
                       "is_active": MessageTemplate.is_active, "category": MessageTemplate.category},
        search=(MessageTemplate.name, MessageTemplate.subject),
    )  # fmt: skip


def get_template(session: Session, principal: Principal, template_id: UUID) -> MessageTemplate:
    authorize(principal, "engagement.campaign.read")
    return _template(session, template_id)


def create_template(session: Session, principal: Principal, data: dict) -> MessageTemplate:
    """A saved template; `copied_from_id` copies a preset or another template (copy-on-edit)."""
    authorize_tenant_wide(principal, "engagement.campaign.edit")
    if data.get("copied_from_id"):
        source = _template(session, data["copied_from_id"])
        for field in ("channel", "subject", "body_text", "category"):
            if data.get(field) is None:
                data[field] = getattr(source, field)
    if not data.get("body_text"):
        raise ValidationFailed("Write the message.", pointer="/body_text")
    _check_fields(data.get("subject"), data["body_text"])
    if data.get("channel") == "push" and len(data["body_text"]) > 180:
        raise ValidationFailed("A push message is at most 180 characters.", pointer="/body_text", code="push-too-long")
    row = MessageTemplate(origin="saved", **{k: v for k, v in data.items() if v is not None})
    session.add(row)
    session.flush()
    audit.record(session, "engagement.campaign.edit", row, changes=audit.diff(row))
    return row


def update_template(session: Session, principal: Principal, template_id: UUID, data: dict) -> MessageTemplate:
    authorize_tenant_wide(principal, "engagement.campaign.edit")
    row = _template(session, template_id)
    if row.origin == "preset":
        raise Conflict("Presets are read-only: copy it to edit.", code="template-read-only")
    if row.origin == "system":
        data.pop("name", None)
        data.pop("channel", None)
    for field, value in data.items():
        setattr(row, field, value)
    _check_fields(row.subject, row.body_text)
    if row.channel == "push" and len(row.body_text) > 180:
        raise ValidationFailed("A push message is at most 180 characters.", pointer="/body_text", code="push-too-long")
    audit.record(session, "engagement.campaign.edit", row, changes=audit.diff(row))
    session.flush()
    return row


def delete_template(session: Session, principal: Principal, template_id: UUID) -> None:
    """Presets and system templates stay; a template in use is retired instead of deleted."""
    authorize_tenant_wide(principal, "engagement.campaign.edit")
    row = _template(session, template_id)
    if row.origin != "saved":
        raise Conflict("Built-in templates cannot be deleted.", code="template-read-only")
    in_use = session.scalar(select(func.count()).select_from(Campaign).where(Campaign.message_template_id == row.id))
    in_use = in_use or session.scalar(
        select(func.count()).select_from(AutomationRule).where(AutomationRule.message_template_id == row.id)
    )
    in_use = in_use or session.scalar(
        select(func.count()).select_from(Message).where(Message.message_template_id == row.id)
    )
    audit.record(session, "engagement.campaign.edit", row, changes={"deleted": not in_use, "is_active": False})
    if in_use:
        row.is_active = False
    else:
        session.delete(row)
    session.flush()


SYSTEM_TEMPLATES = {
    "session_reminder": ("Reminder: $title", "Hi $first_name,\n\nThis is a reminder of $title on $starts_at at "
                         "$location_name.\n\nSee you soon,\n$facility_name"),
}  # fmt: skip


def system_template(session: Session, key: str) -> MessageTemplate:
    """The tenant's copy of a built-in notice, created on first use so the tenant can reword it."""
    row = session.scalar(
        select(MessageTemplate).where(MessageTemplate.system_key == key, MessageTemplate.channel == "email")
    )
    if row is None:
        subject, body = SYSTEM_TEMPLATES[key]
        row = MessageTemplate(origin="system", system_key=key, name=key.replace("_", " ").capitalize(),
                              subject=subject, body_text=body)  # fmt: skip
        session.add(row)
        session.flush()
    return row


# --- segments (MKT-03) ---------------------------------------------------------------------------------------


def _check_definition(definition: dict, pointer: str = "/definition") -> None:
    problems = rules.check_definition(definition)
    if problems:
        path, message = problems[0]
        raise ValidationFailed(message, pointer=pointer + path, code="invalid-audience")


def resolve_audience(session: Session, definition: dict, location_id: UUID | None) -> list:
    """Clients in the audience, always narrowed to the campaign's location (a location-limited sender reaches
    only that location's clients). Shortcut: membership is checked per client; batch it past ~10k clients."""
    sources = definition["sources"]
    filters = {f["kind"]: f for f in definition.get("filters") or []}
    homes = [location_id] if location_id else None
    if "home_location" in filters:
        wanted = [UUID(str(i)) for i in filters["home_location"]["ids"]]
        homes = [h for h in homes if h in wanted] if homes else wanted
    found = clients.audience(
        session, everyone=any(s["kind"] == "all_clients" for s in sources), home_location_ids=homes,
        client_ids=[UUID(str(i)) for s in sources if s["kind"] == "client_ids" for i in s["ids"]],
        tag_ids=[UUID(str(i)) for s in sources if s["kind"] == "tag" for i in s["ids"]],
    )  # fmt: skip
    today = platform.service.earliest_today(session)
    out = []
    for client in found:
        keep = True
        for kind, flt in filters.items():
            if kind == "birth_month":
                keep = client.birth_on is not None and client.birth_on.month in flt["months"]
            elif kind == "gender":
                keep = client.gender in flt["values"]
            elif kind == "age_range":
                if client.birth_on is None:
                    keep = bool(flt.get("include_unknown"))
                else:
                    age = rules.age_on(client.birth_on, today)
                    keep = (flt.get("min") is None or age >= flt["min"]) and (
                        flt.get("max") is None or age <= flt["max"]
                    )
            elif kind == "member":
                keep = memberships.service.is_member(session, client.id) == bool(flt.get("is_member", True))
            if flt.get("negate"):
                keep = not keep
            if not keep:
                break
        if keep:
            out.append(client)
    return out


def _segment(session: Session, segment_id: UUID) -> Segment:
    row = session.get(Segment, segment_id)
    if row is None:
        raise NotFound()
    return row


def list_segments(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, "engagement.campaign.read")
    return paginate(
        session, select(Segment), query, id_column=Segment.id, sort_fields={"name": Segment.name},
        default_sort="name", filter_fields={"is_builtin": Segment.is_builtin}, search=(Segment.name,),
    )  # fmt: skip


def get_segment(session: Session, principal: Principal, segment_id: UUID) -> Segment:
    authorize(principal, "engagement.campaign.read")
    return _segment(session, segment_id)


def create_segment(session: Session, principal: Principal, data: dict) -> Segment:
    authorize_tenant_wide(principal, "engagement.campaign.edit")
    _check_definition(data["definition"])
    row = Segment(name=data["name"], definition=data["definition"])
    session.add(row)
    session.flush()
    audit.record(session, "engagement.campaign.edit", row, changes=audit.diff(row))
    return row


def update_segment(session: Session, principal: Principal, segment_id: UUID, data: dict) -> Segment:
    authorize_tenant_wide(principal, "engagement.campaign.edit")
    row = _segment(session, segment_id)
    if row.is_builtin:
        raise Conflict("Built-in segments cannot be changed.", code="segment-read-only")
    if "definition" in data:
        _check_definition(data["definition"])
    for field, value in data.items():
        setattr(row, field, value)
    audit.record(session, "engagement.campaign.edit", row, changes=audit.diff(row))
    session.flush()
    return row


def delete_segment(session: Session, principal: Principal, segment_id: UUID) -> None:
    authorize_tenant_wide(principal, "engagement.campaign.edit")
    row = _segment(session, segment_id)
    if row.is_builtin:
        raise Conflict("Built-in segments cannot be deleted.", code="segment-read-only")
    if session.scalar(select(func.count()).select_from(Campaign).where(Campaign.segment_id == row.id)):
        raise Conflict("A campaign uses this segment.", code="segment-in-use")
    audit.record(session, "engagement.campaign.edit", row, changes={"deleted": True})
    session.delete(row)
    session.flush()


def preview_segment(session: Session, principal: Principal, data: dict) -> dict:
    """Audience size at a location, before saving or sending. A saved segment's last count is refreshed."""
    authorize(principal, "engagement.campaign.read", location_id=data["location_id"])
    platform.service.get_location(session, principal, data["location_id"])
    definition = data.get("definition")
    segment = None
    if data.get("segment_id"):
        segment = _segment(session, data["segment_id"])
        definition = segment.definition
    if definition is None:
        raise ValidationFailed("Give a segment or a definition.", pointer="/definition")
    _check_definition(definition)
    people = resolve_audience(session, definition, data["location_id"])
    with_email = sum(1 for c in people if c.primary_email)
    if segment is not None:
        segment.last_count, segment.last_counted_at = len(people), _now()
    return {"count": len(people), "with_email_count": with_email,
            "sample": [{"client_id": c.id, "name": clients.display_name(c)} for c in people[:10]]}  # fmt: skip


BUILTIN_SEGMENTS = {
    "All contacts": {"sources": [{"kind": "all_clients"}]},
    "All members": {"sources": [{"kind": "all_clients"}], "filters": [{"kind": "member", "is_member": True}]},
    "Non-members": {"sources": [{"kind": "all_clients"}], "filters": [{"kind": "member", "is_member": False}]},
}


def ensure_builtin_segments(session: Session) -> None:
    have = set(session.scalars(select(Segment.name).where(Segment.is_builtin)))
    for name, definition in BUILTIN_SEGMENTS.items():
        if name not in have:
            session.add(Segment(name=name, definition=definition, is_builtin=True))
    session.flush()


# --- campaigns (MKT-03, MKT-07, MKT-16) ----------------------------------------------------------------------


def _campaign(session: Session, principal: Principal, campaign_id: UUID, key: str, *, lock: bool = False) -> Campaign:
    stmt = select(Campaign).where(Campaign.id == campaign_id)
    row = session.scalar(stmt.with_for_update() if lock else stmt)
    if row is None or not (principal.kind == "system" or principal.location_ids is None
                           or row.location_id in principal.location_ids):  # fmt: skip
        raise NotFound()
    authorize(principal, key, location_id=row.location_id)
    return row


def _check_campaign(session: Session, row: Campaign) -> None:
    if row.segment_id:
        _segment(session, row.segment_id)
    if row.audience is not None:
        _check_definition(row.audience, "/audience")
    if row.message_template_id:
        _template(session, row.message_template_id)
    _check_fields(row.subject, row.body_text)
    if row.link_url and not rules.is_https_url(row.link_url):
        raise ValidationFailed("Links must be https.", pointer="/link_url")
    if row.channel == "push" and len(row.body_text or "") > 180:
        raise ValidationFailed("A push message is at most 180 characters.", pointer="/body_text", code="push-too-long")


def list_campaigns(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, "engagement.campaign.read")
    return paginate(
        session, scope_query(select(Campaign), principal, Campaign.location_id), query, id_column=Campaign.id,
        sort_fields={"created_at": Campaign.created_at, "name": Campaign.name}, default_sort="-created_at",
        filter_fields={"channel": Campaign.channel, "status": Campaign.status, "location_id": Campaign.location_id},
        search=(Campaign.name, Campaign.subject),
    )  # fmt: skip


def get_campaign(session: Session, principal: Principal, campaign_id: UUID) -> Campaign:
    return _campaign(session, principal, campaign_id, "engagement.campaign.read")


def create_campaign(session: Session, principal: Principal, data: dict) -> Campaign:
    authorize(principal, "engagement.campaign.create", location_id=data["location_id"])
    platform.service.get_location(session, principal, data["location_id"])
    if data.get("message_template_id") and not data.get("body_text"):
        template = _template(session, data["message_template_id"])
        data.setdefault("subject", template.subject)
        data["subject"] = data["subject"] or template.subject
        data["body_text"] = template.body_text
    row = Campaign(sender_staff_user_id=principal.staff_user_id, **{k: v for k, v in data.items() if v is not None})
    _check_campaign(session, row)
    session.add(row)
    session.flush()
    audit.record(session, "engagement.campaign.create", row, location_id=row.location_id, changes=audit.diff(row))
    return row


def update_campaign(session: Session, principal: Principal, campaign_id: UUID, data: dict) -> Campaign:
    row = _campaign(session, principal, campaign_id, "engagement.campaign.create", lock=True)
    if row.status not in ("draft", "scheduled"):
        raise Conflict("Only a draft or scheduled campaign can change.", code="campaign-not-editable")
    data.pop("location_id", None)
    for field, value in data.items():
        setattr(row, field, value)
    if row.status == "scheduled":  # an edit needs a fresh schedule by someone holding the send key
        row.status, row.scheduled_at = "draft", None
    _check_campaign(session, row)
    audit.record(session, "engagement.campaign.create", row, location_id=row.location_id, changes=audit.diff(row))
    session.flush()
    return row


def delete_campaign(session: Session, principal: Principal, campaign_id: UUID) -> None:
    row = _campaign(session, principal, campaign_id, "engagement.campaign.create", lock=True)
    if row.status != "draft":
        raise Conflict("Only a draft can be deleted; cancel a scheduled campaign.", code="campaign-not-editable")
    audit.record(session, "engagement.campaign.create", row, location_id=row.location_id, changes={"deleted": True})
    session.delete(row)
    session.flush()


def _audience_of(session: Session, row: Campaign) -> dict:
    if row.segment_id:
        return _segment(session, row.segment_id).definition
    if row.audience is None:
        raise ValidationFailed("Choose who receives it.", pointer="/segment_id", code="audience-required")
    return row.audience


def _send_key(row: Campaign) -> str:
    return "engagement.push.send" if row.channel == "push" else "engagement.campaign.send"


def _authorize_send(session: Session, principal: Principal, row: Campaign) -> None:
    """PLT-06, after the channel's send key: an audience of every client (no filter) also needs send_all."""
    audience = _audience_of(session, row)
    if any(s["kind"] == "all_clients" for s in audience["sources"]) and not audience.get("filters"):
        authorize(principal, "engagement.campaign.send_all", location_id=row.location_id)


def send_campaign(session: Session, principal: Principal, campaign_id: UUID) -> Campaign:
    """Send now. Consent, suppression and verification are applied per recipient by _deliver."""
    row = _campaign(session, principal, campaign_id, "engagement.campaign.read", lock=True)
    authorize(principal, _send_key(row), location_id=row.location_id)
    if row.status not in ("draft", "scheduled"):
        raise Conflict("This campaign has already gone out.", code="campaign-not-editable")
    _authorize_send(session, principal, row)
    _fan_out(session, row)
    audit.record(session, _send_key(row), row, location_id=row.location_id, changes=audit.diff(row))
    session.flush()
    return row


def schedule_campaign(session: Session, principal: Principal, campaign_id: UUID, data: dict) -> Campaign:
    row = _campaign(session, principal, campaign_id, "engagement.campaign.read", lock=True)
    authorize(principal, _send_key(row), location_id=row.location_id)
    if row.status not in ("draft", "scheduled"):
        raise Conflict("This campaign has already gone out.", code="campaign-not-editable")
    if data["scheduled_at"] <= _now():
        raise ValidationFailed("Pick a time in the future.", pointer="/scheduled_at")
    _authorize_send(session, principal, row)
    row.status, row.scheduled_at = "scheduled", data["scheduled_at"]
    audit.record(session, _send_key(row), row, location_id=row.location_id, changes=audit.diff(row))
    session.flush()
    return row


def cancel_campaign(session: Session, principal: Principal, campaign_id: UUID) -> Campaign:
    row = _campaign(session, principal, campaign_id, "engagement.campaign.create", lock=True)
    if row.status != "scheduled":
        raise Conflict("Only a scheduled campaign can be cancelled.", code="campaign-not-editable")
    row.status = "cancelled"
    audit.record(session, "engagement.campaign.create", row, location_id=row.location_id, changes=audit.diff(row))
    session.flush()
    return row


def recall_campaign(session: Session, principal: Principal, campaign_id: UUID) -> Campaign:
    """Take a sent announcement out of every inbox."""
    row = _campaign(session, principal, campaign_id, "engagement.push.send", lock=True)
    if row.channel != "push" or row.status != "sent":
        raise Conflict("Only a sent announcement can be recalled.", code="campaign-not-recallable")
    now = _now()
    row.status, row.recalled_at = "recalled", now
    session.execute(
        update(InboxItem)
        .where(InboxItem.campaign_id == row.id, InboxItem.recalled_at.is_(None))
        .values(recalled_at=now)
    )
    audit.record(session, "engagement.push.send", row, location_id=row.location_id, changes=audit.diff(row))
    session.flush()
    return row


def test_send_campaign(session: Session, principal: Principal, campaign_id: UUID) -> Message:
    """Send the campaign to the requesting staff member only, marked as a test."""
    row = _campaign(session, principal, campaign_id, "engagement.campaign.edit")
    email = platform.service.active_staff_emails(session, [principal.staff_user_id]).get(principal.staff_user_id)
    data = _merge_data(session, None, row.location_id, first_name="(test)")
    message = _deliver(
        session, category="operational", topic=None, subject=f"[TEST] {rules.render(row.subject, data)}",
        body=rules.render(row.body_text, data), to_address=email, staff_user_id=principal.staff_user_id,
        location_id=row.location_id, sender_staff_user_id=principal.staff_user_id,
    )  # fmt: skip
    audit.record(session, "engagement.campaign.edit", row, location_id=row.location_id, changes={"test_sent": True})
    return message


_COUNTER = {
    "unverified": "unverified_count", "unsubscribed": "unsubscribed_skip_count", "suppressed": "suppressed_count",
    "invalid_address": "invalid_count", "inactive_client": "invalid_count", "duplicate": "duplicate_count",
}  # fmt: skip


def _fan_out(session: Session, row: Campaign) -> None:
    """One message per recipient (and one inbox item per member for an announcement), then the counters.
    Shortcut: runs in the caller's transaction; move to a chunked job past a few thousand recipients."""
    people = resolve_audience(session, _audience_of(session, row), row.location_id)
    now = _now()
    row.status, row.started_at, row.attempted_count = "sending", now, len(people)
    seen: set[str] = set()
    for client in people:
        data = _merge_data(session, client, row.location_id)
        subject, body = rules.render(row.subject, data), rules.render(row.body_text, data)
        if row.channel == "push":
            session.add(InboxItem(
                location_id=row.location_id, client_id=client.id, campaign_id=row.id, title=subject or row.name,
                body_text=body, link_url=row.link_url, published_at=now, expires_at=now + timedelta(days=INBOX_DAYS),
            ))  # fmt: skip
            row.inbox_count += 1
            for device in session.scalars(select(DeviceRegistration).where(
                DeviceRegistration.client_id == client.id, DeviceRegistration.revoked_at.is_(None),
                DeviceRegistration.is_push_enabled,
            )):  # fmt: skip
                _deliver(session, channel="push", category="marketing", topic="push_announcements", subject=subject,
                         body=body, client=client, location_id=row.location_id, campaign_id=row.id,
                         device_id=device.id, dedupe_key=f"campaign:{row.id}:{device.id}")  # fmt: skip
            continue
        address = (client.primary_email or "").lower()
        if address and address in seen:
            message = Message(channel="email", category="marketing", topic="email_campaigns", client_id=client.id,
                              to_address=address, campaign_id=row.id, location_id=row.location_id, status="skipped",
                              skip_reason="duplicate", queued_at=now)  # fmt: skip
            session.add(message)
        else:
            seen.add(address)
            message = _deliver(
                session, category="marketing", topic="email_campaigns", subject=subject, body=body, client=client,
                location_id=row.location_id, campaign_id=row.id, template_id=row.message_template_id,
                sender_staff_user_id=row.sender_staff_user_id, dedupe_key=f"campaign:{row.id}:{client.id}",
            )  # fmt: skip
        if message.status == "sent":
            row.sent_count += 1
        else:
            setattr(row, _COUNTER[message.skip_reason], getattr(row, _COUNTER[message.skip_reason]) + 1)
    row.status, row.sent_at = "sent", _now()
    events.publish(session, CampaignSent(campaign_id=row.id, location_id=row.location_id, channel=row.channel), row.id)
    session.flush()


def send_due_campaigns(session: Session) -> int:
    """Per-minute job: scheduled campaigns whose time has come. Locked, so two runs never send one twice."""
    due = list(session.scalars(
        select(Campaign).where(Campaign.status == "scheduled", Campaign.scheduled_at <= _now())
        .with_for_update(skip_locked=True)
    ))  # fmt: skip
    for row in due:
        _fan_out(session, row)
        audit.record(session, _send_key(row), row, location_id=row.location_id, changes={"status": "sent"})
    return len(due)


def campaign_stats(session: Session, principal: Principal, campaign_id: UUID) -> dict:
    row = _campaign(session, principal, campaign_id, "engagement.campaign.read")
    by_status = dict(session.execute(
        select(Message.status, func.count()).where(Message.campaign_id == row.id).group_by(Message.status)
    ).all())  # fmt: skip
    return {"campaign_id": row.id, "by_status": {k: int(v) for k, v in by_status.items()}} | {
        field: getattr(row, field) for field in (
            "attempted_count", "duplicate_count", "invalid_count", "unverified_count", "unsubscribed_skip_count",
            "suppressed_count", "sent_count", "delivered_count", "opened_count", "clicked_count", "bounced_count",
            "complaint_count", "unsubscribed_count", "inbox_count",
        )
    }  # fmt: skip


def list_campaign_recipients(session: Session, principal: Principal, campaign_id: UUID, query: ListQuery) -> dict:
    row = _campaign(session, principal, campaign_id, "engagement.campaign.read")
    return paginate(
        session, select(Message).where(Message.campaign_id == row.id), query, id_column=Message.id,
        sort_fields={"queued_at": Message.queued_at}, default_sort="queued_at",
        filter_fields={"status": Message.status, "skip_reason": Message.skip_reason},
    )  # fmt: skip


# --- messages: direct email and the per-client log (MKT-09, MKT-10) ------------------------------------------


def _visible(principal: Principal):
    if principal.kind == "system" or principal.location_ids is None:
        return true()
    # location-less rows (password resets, receipts from other contexts) are for tenant-wide staff only
    return Message.location_id.in_(principal.location_ids)


def list_messages(session: Session, principal: Principal, query: ListQuery) -> dict:
    """Everything sent or skipped; with `client_id`, that client's communication log."""
    authorize(principal, "engagement.campaign.read")
    stmt = select(Message).where(_visible(principal))
    if query.filters.get("client_id"):
        try:
            client_id = UUID(query.filters.pop("client_id"))
        except ValueError as error:
            raise ValidationFailed("Not a valid id.", pointer="/client_id") from error
        clients.load(session, principal, client_id, "clients.client.read")
        stmt = stmt.where(Message.client_id == client_id)
    return paginate(
        session, stmt, query, id_column=Message.id, sort_fields={"queued_at": Message.queued_at},
        default_sort="-queued_at", filter_fields={"status": Message.status, "channel": Message.channel,
        "category": Message.category, "campaign_id": Message.campaign_id},
    )  # fmt: skip


def get_message(session: Session, principal: Principal, message_id: UUID) -> Message:
    authorize(principal, "engagement.campaign.read")
    row = session.scalar(select(Message).where(Message.id == message_id, _visible(principal)))
    if row is None:
        raise NotFound()
    return row


def send_direct_message(session: Session, principal: Principal, data: dict) -> Message:
    """One email from staff to one client, logged on the client's record (MKT-10). Service mail: no topic, so
    an opt-out of campaigns does not block it, but suppression and a missing address do."""
    client = clients.load(session, principal, data["client_id"], "engagement.message.send_direct")
    clients._require_live(client)
    if data.get("location_id"):
        platform.service.get_location(session, principal, data["location_id"])
    subject, body = data.get("subject"), data.get("body_text")
    if data.get("message_template_id"):
        template = _template(session, data["message_template_id"])
        subject, body = subject or template.subject, body or template.body_text
    if not subject or not body:
        raise ValidationFailed("Write a subject and a message.", pointer="/subject")
    _check_fields(subject, body)
    merged = _merge_data(session, client, data.get("location_id") or client.home_location_id)
    row = _deliver(
        session, category="transactional", topic=None, subject=rules.render(subject, merged),
        body=rules.render(body, merged), client=client, location_id=data.get("location_id") or client.home_location_id,
        template_id=data.get("message_template_id"), sender_staff_user_id=principal.staff_user_id, keep_body=True,
    )  # fmt: skip
    audit.record(session, "engagement.message.send_direct", row, location_id=row.location_id,
                 changes={"client_id": str(client.id), "status": row.status, "skip_reason": row.skip_reason})  # fmt: skip
    return row


# --- suppression and provider events (MKT-07, MKT-08) --------------------------------------------------------


def suppress(session: Session, address: str, reason: str, detail: str | None = None) -> Suppression:
    """Internal: block an address. Failing again after a release makes the block permanent."""
    address = address.lower()
    row = session.scalar(select(Suppression).where(Suppression.channel == "email", Suppression.address == address))
    if row is None:
        row = Suppression(address=address, reason=reason, detail=detail, last_failed_at=_now())
        session.add(row)
    else:
        if row.released_at is not None:
            row.is_permanent = True
            row.released_at = None
        row.reason, row.detail, row.last_failed_at = reason, detail, _now()
    session.flush()
    audit.record(session, "engagement.suppression.manage", row, changes=audit.diff(row))
    return row


def list_suppressions(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, "engagement.campaign.read")
    return paginate(
        session, select(Suppression), query, id_column=Suppression.id,
        sort_fields={"created_at": Suppression.created_at}, default_sort="-created_at",
        filter_fields={"reason": Suppression.reason, "is_permanent": Suppression.is_permanent},
        search=(Suppression.address,),
    )  # fmt: skip


def create_suppression(session: Session, principal: Principal, data: dict) -> Suppression:
    authorize(principal, "engagement.suppression.manage")
    return suppress(session, data["address"], "manual", data.get("detail"))


def release_suppression(session: Session, principal: Principal, suppression_id: UUID) -> Suppression:
    authorize(principal, "engagement.suppression.manage")
    row = session.get(Suppression, suppression_id)
    if row is None:
        raise NotFound()
    if row.is_permanent:
        raise Conflict("This address failed again after a release; it stays blocked.", code="suppression-permanent")
    if row.released_at is not None:
        raise Conflict("Already released.", code="invalid-state-transition")
    row.released_at, row.released_by_staff_user_id = _now(), principal.staff_user_id
    row.release_count += 1
    audit.record(session, "engagement.suppression.manage", row, changes=audit.diff(row))
    session.flush()
    return row


_STATUS_COUNTER = {"delivered": "delivered_count", "opened": "opened_count", "clicked": "clicked_count",
                   "bounced": "bounced_count", "complained": "complaint_count"}  # fmt: skip


def record_delivery_event(session: Session, provider: str, provider_message_id: str, event_type: str,
                          detail: str | None = None) -> Message | None:  # fmt: skip
    """Internal, for an email provider's webhook adapter: apply one event to its message. Replays and
    out-of-order events are harmless (the status only moves forward); a bounce or complaint suppresses the
    address and an unsubscribe opts the client out of campaigns."""
    row = session.scalar(
        select(Message).where(Message.provider == provider, Message.provider_message_id == provider_message_id)
    )
    if row is None:
        return None
    campaign = session.get(Campaign, row.campaign_id) if row.campaign_id else None
    before = row.status
    row.status, row.last_event_at = rules.advance(row.status, event_type), _now()
    if row.status != before and campaign is not None:
        # an open implies delivery and a click implies both: count every step crossed, once per recipient
        steps = ["delivered", "opened", "clicked"]
        if row.status in steps:
            start = steps.index(before) + 1 if before in steps else 0
            crossed = steps[start : steps.index(row.status) + 1]
        else:
            crossed = [row.status]
        for status in crossed:
            if status in _STATUS_COUNTER:
                setattr(campaign, _STATUS_COUNTER[status], getattr(campaign, _STATUS_COUNTER[status]) + 1)
    if row.status in ("bounced", "complained") and before != row.status and row.to_address:
        suppress(session, row.to_address, "bounce" if row.status == "bounced" else "complaint", detail)
        events.publish(session, MessageBounced(message_id=row.id, client_id=row.client_id), row.id)
    if event_type == "unsubscribe":
        _unsubscribe(session, row, source="one_click")
    session.flush()
    return row


def _unsubscribe(session: Session, row: Message, *, source: str) -> bool:
    if row.client_id is None or row.to_address is None:
        return False
    client = clients.get(session, row.client_id)
    topic = row.topic or "email_campaigns"
    if not is_subscribed(session, client.id, "email", topic, row.to_address):
        return False
    _apply(session, client, [{"channel": "email", "address": row.to_address, "topic": topic, "is_subscribed": False}],
           source=source, actor_type="client", actor_id=None, basis="express", note=None)  # fmt: skip
    if row.campaign_id:
        session.execute(update(Campaign).where(Campaign.id == row.campaign_id)
                        .values(unsubscribed_count=Campaign.unsubscribed_count + 1))  # fmt: skip
    events.publish(session, ConsentChanged(client_id=client.id, source=source), client.id)
    return True


# --- public preference centre and one-click unsubscribe (MKT-02) ---------------------------------------------


def _by_token(session: Session, raw: str) -> Message:
    row = session.scalar(select(Message).where(Message.unsubscribe_token_hash == tokens.digest(raw)))
    if (
        row is None
        or row.client_id is None
        or (row.sent_at and row.sent_at < _now() - timedelta(days=UNSUBSCRIBE_DAYS))
    ):
        raise NotFound("This link is not valid or has expired.", code="token-invalid")
    return row


def public_unsubscribe(session: Session, raw: str) -> dict:
    row = _by_token(session, raw)
    changed = _unsubscribe(session, row, source="one_click")
    return {"topic": row.topic or "email_campaigns", "unsubscribed": True, "changed": changed}


def public_preferences(session: Session, raw: str) -> dict:
    """The preferences for the one address the link was sent to: no other personal data is shown."""
    row = _by_token(session, raw)
    client = clients.get(session, row.client_id)
    items = [p for p in preferences(session, client) if p["channel"] == "email" and p["address"] == row.to_address]
    return {"facility_name": _facility(session), "address": row.to_address, "data": items}


def put_public_preferences(session: Session, raw: str, changes: list[dict]) -> dict:
    row = _by_token(session, raw)
    client = clients.get(session, row.client_id)
    for index, change in enumerate(changes):
        if change["channel"] != "email" or (change.get("address") or "").lower() != row.to_address:
            raise ValidationFailed("This link only manages the address it was sent to.",
                                   pointer=f"/changes/{index}/address")  # fmt: skip
    _apply(session, client, changes, source="preference_center", actor_type="client", actor_id=None,
           basis="express", note=None)  # fmt: skip
    events.publish(session, ConsentChanged(client_id=client.id, source="preference_center"), client.id)
    return public_preferences(session, raw)


# --- portal: inbox and devices (MKT-16) ----------------------------------------------------------------------


def _identity_clients(session: Session, principal: Principal) -> list[UUID]:
    if principal.kind != "client":
        raise NotFound()
    return clients.client_ids_for_identity(session, principal.identity_id)


def list_portal_inbox(session: Session, principal: Principal, query: ListQuery) -> dict:
    """Announcements and notices for the clients this login holds directly, newest first."""
    ids = _identity_clients(session, principal)
    stmt = select(InboxItem).where(
        InboxItem.client_id.in_(ids), InboxItem.recalled_at.is_(None), InboxItem.expires_at > _now()
    )
    query.filters.pop("client_id", None)
    return paginate(session, stmt, query, id_column=InboxItem.id,
                    sort_fields={"published_at": InboxItem.published_at}, default_sort="-published_at")  # fmt: skip


def mark_portal_inbox_read(session: Session, principal: Principal, item_id: UUID) -> InboxItem:
    ids = _identity_clients(session, principal)
    row = session.scalar(select(InboxItem).where(InboxItem.id == item_id, InboxItem.client_id.in_(ids)))
    if row is None or row.recalled_at is not None:
        raise NotFound()
    if row.read_at is None:
        row.read_at = _now()
        audit.record(session, "engagement.inbox.read", row, location_id=row.location_id, changes={"read": True})
        session.flush()
    return row


def unread_count(session: Session, principal: Principal) -> int:
    ids = _identity_clients(session, principal)
    return int(session.scalar(select(func.count()).select_from(InboxItem).where(
        InboxItem.client_id.in_(ids), InboxItem.read_at.is_(None), InboxItem.recalled_at.is_(None),
        InboxItem.expires_at > _now(),
    )) or 0)  # fmt: skip


def register_portal_device(session: Session, principal: Principal, data: dict) -> DeviceRegistration:
    """Register (or re-register) this device for push. The client is the login's own record."""
    ids = _identity_clients(session, principal)
    if not ids:
        raise NotFound()
    if data.get("location_id") and not platform.service.location_exists(session, data["location_id"]):
        raise ValidationFailed("Unknown location.", pointer="/location_id")
    row = session.scalar(
        select(DeviceRegistration)
        .where(DeviceRegistration.push_token == data["push_token"], DeviceRegistration.revoked_at.is_(None))
        .with_for_update()
    )
    if row is not None and row.identity_id != principal.identity_id:
        # The phone changed hands (W2-08): end the other login's registration, never move it silently.
        row.revoked_at = _now()
        audit.record(
            session, "engagement.device.unregister", row, location_id=row.location_id, changes={"revoked": True}
        )
        session.flush()
        row = None
    if row is None:
        row = DeviceRegistration(push_token=data["push_token"], identity_id=principal.identity_id, client_id=ids[0],
                                 platform=data["platform"])  # fmt: skip
        session.add(row)
    row.identity_id, row.client_id, row.platform = principal.identity_id, ids[0], data["platform"]
    row.location_id, row.app_version = data.get("location_id"), data.get("app_version")
    row.is_push_enabled = data.get("is_push_enabled", True)
    row.last_active_at, row.revoked_at = _now(), None
    session.flush()
    audit.record(session, "engagement.device.register", row, location_id=row.location_id, changes=audit.diff(row))
    return row


def unregister_portal_device(session: Session, principal: Principal, device_id: UUID) -> None:
    _identity_clients(session, principal)
    row = session.scalar(select(DeviceRegistration).where(
        DeviceRegistration.id == device_id, DeviceRegistration.identity_id == principal.identity_id))  # fmt: skip
    if row is None:
        raise NotFound()
    row.revoked_at = row.revoked_at or _now()
    audit.record(session, "engagement.device.unregister", row, location_id=row.location_id, changes={"revoked": True})
    session.flush()


# --- reminder rules and the send queue (MKT-13) --------------------------------------------------------------


def _located(session: Session, principal: Principal, model, row_id: UUID, key: str):
    row = session.get(model, row_id)
    if row is None or not (principal.kind == "system" or principal.location_ids is None
                           or row.location_id in principal.location_ids):  # fmt: skip
        raise NotFound()
    authorize(principal, key, location_id=row.location_id)
    return row


_RULES = "engagement.notification_rule.manage"


def list_reminder_rules(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, _RULES)
    return paginate(session, scope_query(select(ReminderRule), principal, ReminderRule.location_id), query,
                    id_column=ReminderRule.id, sort_fields={"created_at": ReminderRule.created_at},
                    filter_fields={"location_id": ReminderRule.location_id})  # fmt: skip


def get_reminder_rule(session: Session, principal: Principal, rule_id: UUID) -> ReminderRule:
    return _located(session, principal, ReminderRule, rule_id, _RULES)


def create_reminder_rule(session: Session, principal: Principal, data: dict) -> ReminderRule:
    authorize(principal, _RULES, location_id=data["location_id"])
    platform.service.get_location(session, principal, data["location_id"])
    if session.scalar(select(ReminderRule.id).where(ReminderRule.location_id == data["location_id"])):
        raise Conflict("This location already has reminder settings.", code="reminder-rule-exists")
    row = ReminderRule(**data)
    session.add(row)
    session.flush()
    audit.record(session, _RULES, row, location_id=row.location_id, changes=audit.diff(row))
    return row


def update_reminder_rule(session: Session, principal: Principal, rule_id: UUID, data: dict) -> ReminderRule:
    row = _located(session, principal, ReminderRule, rule_id, _RULES)
    data.pop("location_id", None)
    for field, value in data.items():
        setattr(row, field, value)
    audit.record(session, _RULES, row, location_id=row.location_id, changes=audit.diff(row))
    session.flush()
    return row


def delete_reminder_rule(session: Session, principal: Principal, rule_id: UUID) -> None:
    row = _located(session, principal, ReminderRule, rule_id, _RULES)
    audit.record(session, _RULES, row, location_id=row.location_id, changes={"deleted": True})
    session.delete(row)
    session.flush()


def schedule_reminders(session: Session, *, subject_type: str, subject_id: UUID, client_id: UUID | None,
                       location_id: UUID, starts_at, title: str | None) -> int:  # fmt: skip
    """Internal (event handlers): materialise the reminders for one booking or enrollment. Re-running is a
    no-op for rows already queued; a new start time moves rows that have not gone out."""
    rule = session.scalar(select(ReminderRule).where(ReminderRule.location_id == location_id, ReminderRule.is_enabled))
    if rule is None or client_id is None:
        return 0
    made = 0
    for number, send_at in rules.reminder_times(starts_at, [rule.first_offset_minutes, rule.second_offset_minutes],
                                                _now()):  # fmt: skip
        key = f"session_reminder:{number}:{subject_id}:{client_id}"
        row = session.scalar(select(ScheduledNotification).where(ScheduledNotification.dedupe_key == key))
        if row is None:
            session.add(ScheduledNotification(
                location_id=location_id, kind="session_reminder", reminder_no=number, subject_type=subject_type,
                subject_id=subject_id, client_id=client_id, subject_starts_at=starts_at, send_at=send_at,
                dedupe_key=key, payload={"title": title or "your booking"},
            ))  # fmt: skip
            made += 1
        elif row.status == "scheduled":
            row.send_at, row.subject_starts_at = send_at, starts_at
    session.flush()
    return made


def cancel_notifications(session: Session, *, subject_type: str | None = None, subject_id: UUID | None = None,
                         client_id: UUID | None = None, rule_ids=None) -> int:  # fmt: skip
    """Internal: stop queued sends for a subject (a cancelled booking) or a client (an automation exit)."""
    stmt = update(ScheduledNotification).where(ScheduledNotification.status == "scheduled")
    if subject_id is not None:
        stmt = stmt.where(
            ScheduledNotification.subject_type == subject_type, ScheduledNotification.subject_id == subject_id
        )
    if client_id is not None:
        stmt = stmt.where(ScheduledNotification.client_id == client_id)
    if rule_ids is not None:
        stmt = stmt.where(ScheduledNotification.automation_rule_id.in_(list(rule_ids)))
    return session.execute(stmt.values(status="cancelled")).rowcount


def _still_on(session: Session, row: ScheduledNotification) -> bool:
    if row.subject_type == "booking":
        try:
            booking = scheduling.service.get_booking(session, row.subject_id)
        except NotFound:
            return False
        return booking.status == "confirmed" and booking.starts_at > _now()
    return row.subject_starts_at is None or row.subject_starts_at > _now()


def _send_one(session: Session, row: ScheduledNotification) -> None:
    client = clients.get(session, row.client_id)
    if row.kind == "session_reminder":
        if not _still_on(session, row):
            row.status = "cancelled"
            return
        template, topic, channel = system_template(session, "session_reminder"), "session_reminders", "email"
        category = "transactional"
    else:
        rule = session.get(AutomationRule, row.automation_rule_id)
        if rule is None or not rule.is_enabled:
            row.status = "cancelled"
            return
        template, topic, channel = session.get(MessageTemplate, rule.message_template_id), rule.topic, rule.channel
        # automations are marketing unless the template says otherwise, so consent and verification apply
        category = template.category or "marketing"
        topic = topic or ("email_campaigns" if category == "marketing" else None)
    data = _merge_data(session, client, row.location_id, title=row.payload.get("title"),
                       starts_at=_local(session, row.location_id, row.subject_starts_at))  # fmt: skip
    subject, body = rules.render(template.subject, data), rules.render(template.body_text, data)
    if channel == "push":
        now = _now()
        session.add(InboxItem(location_id=row.location_id or client.home_location_id, client_id=client.id,
                              title=subject or template.name, body_text=body, published_at=now,
                              expires_at=now + timedelta(days=INBOX_DAYS)))  # fmt: skip
        row.status = "sent"
        return
    message = _deliver(
        session, category=category, topic=topic, subject=subject, body=body, client=client,
        location_id=row.location_id, template_id=template.id, source_event_type=row.payload.get("event_type"),
        dedupe_key=row.dedupe_key,
    )  # fmt: skip
    row.message_id, row.status = message.id, "sent" if message.status == "sent" else "skipped"


def send_due_notifications(session: Session, limit: int = 500) -> int:
    """Per-minute job: send reminders and delayed automations whose time has come. Rows are locked and skipped
    by a concurrent run; each send re-checks the subject, consent and suppression."""
    due = list(session.scalars(
        select(ScheduledNotification)
        .where(ScheduledNotification.status == "scheduled", ScheduledNotification.send_at <= _now())
        .order_by(ScheduledNotification.send_at).limit(limit).with_for_update(skip_locked=True)
    ))  # fmt: skip
    for row in due:
        _send_one(session, row)
    session.flush()
    return len(due)


# --- automations (MKT-20; gap B8: rules on programs.waitlist.promoted) ---------------------------------------------

# event type -> (payload field naming the client, payload field naming the subject)
TRIGGERS = {
    "programs.waitlist.promoted": ("client_id", "waitlist_entry_id"),
    "programs.enrollment.created": ("client_id", "enrollment_id"),
    "clients.client.created": ("client_id", "client_id"),
    "memberships.contract.activated": ("client_id", "contract_id"),
    "memberships.contract.renewed": ("client_id", "successor_contract_id"),
    "billing.payment.failed": ("client_id", "payment_id"),
}
_AUTO = "engagement.automation.manage"


def _check_rule(session: Session, data: dict) -> None:
    if "trigger_event_type" in data and data["trigger_event_type"] not in TRIGGERS:
        raise ValidationFailed("Unknown trigger.", pointer="/trigger_event_type", code="unknown-trigger")
    if set(data.get("exit_event_types") or ()) - set(TRIGGERS):
        raise ValidationFailed("Unknown exit event.", pointer="/exit_event_types", code="unknown-trigger")
    if data.get("message_template_id"):
        _template(session, data["message_template_id"])
    if data.get("topic") and data["topic"] not in TOPICS.get(data.get("channel", "email"), ()):
        raise ValidationFailed("This topic is not sent on this channel.", pointer="/topic")


def list_automation_rules(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, _AUTO)
    stmt = select(AutomationRule)
    if principal.kind != "system" and principal.location_ids is not None:
        stmt = stmt.where(
            or_(AutomationRule.location_id.is_(None), AutomationRule.location_id.in_(principal.location_ids))
        )
    return paginate(session, stmt, query, id_column=AutomationRule.id, sort_fields={"name": AutomationRule.name},
                    default_sort="name", filter_fields={"trigger_event_type": AutomationRule.trigger_event_type})  # fmt: skip


def _rule(session: Session, principal: Principal, rule_id: UUID) -> AutomationRule:
    row = session.get(AutomationRule, rule_id)
    if row is None or (row.location_id is not None and principal.kind != "system"
                       and principal.location_ids is not None and row.location_id not in principal.location_ids):  # fmt: skip
        raise NotFound()
    if row.location_id is None:
        authorize_tenant_wide(principal, _AUTO)
    else:
        authorize(principal, _AUTO, location_id=row.location_id)
    return row


def create_automation_rule(session: Session, principal: Principal, data: dict) -> AutomationRule:
    if data.get("location_id"):
        authorize(principal, _AUTO, location_id=data["location_id"])
        platform.service.get_location(session, principal, data["location_id"])
    else:
        authorize_tenant_wide(principal, _AUTO)
    _check_rule(session, data)
    row = AutomationRule(**data)
    session.add(row)
    session.flush()
    audit.record(session, _AUTO, row, location_id=row.location_id, changes=audit.diff(row))
    return row


def update_automation_rule(session: Session, principal: Principal, rule_id: UUID, data: dict) -> AutomationRule:
    row = _rule(session, principal, rule_id)
    if row.is_system:
        data = {k: v for k, v in data.items() if k in ("is_enabled", "delay_minutes", "message_template_id")}
    data.pop("location_id", None)
    _check_rule(session, data | {"channel": data.get("channel", row.channel)})
    for field, value in data.items():
        setattr(row, field, value)
    audit.record(session, _AUTO, row, location_id=row.location_id, changes=audit.diff(row))
    session.flush()
    return row


def delete_automation_rule(session: Session, principal: Principal, rule_id: UUID) -> None:
    row = _rule(session, principal, rule_id)
    if row.is_system:
        raise Conflict("A built-in rule can be switched off, not deleted.", code="automation-system")
    audit.record(session, _AUTO, row, location_id=row.location_id, changes={"deleted": True})
    session.delete(row)
    session.flush()


def _subject_details(session: Session, event_type: str, payload: dict) -> dict:
    """Title, start time and location for the message, where the event names a session."""
    session_id = payload.get("session_id")
    if not session_id:
        return {}
    try:
        seat = scheduling.service.get_session(session, UUID(session_id))
    except NotFound:
        return {}
    return {"title": seat.get("public_title") or seat.get("title"), "starts_at": seat.get("starts_at"),
            "location_id": seat.get("location_id")}  # fmt: skip


def on_trigger(session: Session, event_type: str, payload: dict) -> int:
    """Internal (event handlers): queue every enabled rule for this event, and stop queued sends of rules that
    this event ends for the same client. Delay zero sends in this transaction."""
    client_field, subject_field = TRIGGERS[event_type]
    if not payload.get(client_field):
        return 0
    client_id = UUID(str(payload[client_field]))
    exiting = session.scalars(
        select(AutomationRule.id).where(literal(event_type) == any_(AutomationRule.exit_event_types))
    )
    cancel_notifications(session, client_id=client_id, rule_ids=list(exiting))
    details = _subject_details(session, event_type, payload)
    location_id = details.get("location_id") or (UUID(payload["location_id"]) if payload.get("location_id") else None)
    queued = 0
    for rule in session.scalars(select(AutomationRule).where(
        AutomationRule.trigger_event_type == event_type, AutomationRule.is_enabled
    )):  # fmt: skip
        if rule.location_id and rule.location_id != location_id:
            continue
        if any(str(payload.get(k)) != str(v) for k, v in (rule.conditions or {}).items()):
            continue
        key = f"automation:{rule.id}:{payload[subject_field]}:{client_id}"
        if session.scalar(select(ScheduledNotification.id).where(ScheduledNotification.dedupe_key == key)):
            continue
        row = ScheduledNotification(
            location_id=location_id, kind="automation", automation_rule_id=rule.id, subject_type=event_type,
            subject_id=UUID(str(payload[subject_field])), client_id=client_id, subject_starts_at=details.get("starts_at"),
            send_at=_now() + timedelta(minutes=rule.delay_minutes), dedupe_key=key,
            payload={"title": details.get("title"), "event_type": event_type},
        )  # fmt: skip
        session.add(row)
        session.flush()
        if rule.delay_minutes == 0:
            _send_one(session, row)
        queued += 1
    session.flush()
    return queued


# --- staff alert routes (MKT-14) -----------------------------------------------------------------------------


def list_notification_routes(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, _RULES)
    return paginate(session, scope_query(select(NotificationRoute), principal, NotificationRoute.location_id), query,
                    id_column=NotificationRoute.id, sort_fields={"alert_kind": NotificationRoute.alert_kind},
                    default_sort="alert_kind", filter_fields={"location_id": NotificationRoute.location_id})  # fmt: skip


def get_notification_route(session: Session, principal: Principal, route_id: UUID) -> NotificationRoute:
    return _located(session, principal, NotificationRoute, route_id, _RULES)


def _check_recipients(session: Session, data: dict) -> None:
    if data.get("emails") is not None:
        data["emails"] = sorted({e.lower() for e in data["emails"]})
    ids = data.get("staff_user_ids") or []
    if ids and len(platform.service.active_staff_emails(session, ids)) != len(set(ids)):
        raise ValidationFailed("Every recipient must be an active staff user.", pointer="/staff_user_ids")


def create_notification_route(session: Session, principal: Principal, data: dict) -> NotificationRoute:
    authorize(principal, _RULES, location_id=data["location_id"])
    platform.service.get_location(session, principal, data["location_id"])
    _check_recipients(session, data)
    if session.scalar(select(NotificationRoute.id).where(NotificationRoute.location_id == data["location_id"],
                                                         NotificationRoute.alert_kind == data["alert_kind"])):  # fmt: skip
        raise Conflict("This alert already has a route at this location.", code="notification-route-exists")
    row = NotificationRoute(**data)
    session.add(row)
    session.flush()
    audit.record(session, _RULES, row, location_id=row.location_id, changes=audit.diff(row))
    return row


def update_notification_route(session: Session, principal: Principal, route_id: UUID, data: dict) -> NotificationRoute:
    row = _located(session, principal, NotificationRoute, route_id, _RULES)
    _check_recipients(session, data)
    for field in ("location_id", "alert_kind"):
        data.pop(field, None)
    for field, value in data.items():
        setattr(row, field, value)
    audit.record(session, _RULES, row, location_id=row.location_id, changes=audit.diff(row))
    session.flush()
    return row


def delete_notification_route(session: Session, principal: Principal, route_id: UUID) -> None:
    row = _located(session, principal, NotificationRoute, route_id, _RULES)
    audit.record(session, _RULES, row, location_id=row.location_id, changes={"deleted": True})
    session.delete(row)
    session.flush()


def alert_staff(session: Session, location_id: UUID | None, alert_kind: str, subject: str, body: str,
                dedupe: str) -> int:  # fmt: skip
    """Internal: send an operational alert to the route's recipients at the location; no route, no alert."""
    if location_id is None:
        return 0
    route = session.scalar(select(NotificationRoute).where(
        NotificationRoute.location_id == location_id, NotificationRoute.alert_kind == alert_kind,
        NotificationRoute.is_enabled,
    ))  # fmt: skip
    if route is None:
        return 0
    targets = [
        (sid, email) for sid, email in platform.service.active_staff_emails(session, route.staff_user_ids).items()
    ]
    targets += [(None, email) for email in route.emails]
    for staff_id, email in targets:
        _deliver(session, category="operational", topic=None, subject=subject, body=body, to_address=email,
                 staff_user_id=staff_id, location_id=location_id, source_event_type=alert_kind,
                 dedupe_key=f"alert:{alert_kind}:{dedupe}:{email.lower()}")  # fmt: skip
    return len(targets)


# --- portal settings (SSP-01, SSP-14) ------------------------------------------------------------------------

_PORTAL = "engagement.portal_settings.manage"


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60]
    return slug if len(slug) >= 2 else f"site-{slug}".strip("-")


def _settings_for(session: Session, location_id: UUID) -> PortalSettings:
    row = session.scalar(select(PortalSettings).where(PortalSettings.location_id == location_id))
    if row is None:
        row = PortalSettings(
            location_id=location_id,
            slug=_slug(platform.service.location_name(session, location_id)),
            is_enabled=False,
            is_public=False,
            allows_online_rentals=True,
            allows_online_purchases=True,
        )  # off until staff switch it on
        taken = set(session.scalars(select(PortalSettings.slug)))
        base, n = row.slug, 2
        while row.slug in taken:
            row.slug, n = f"{base[:56]}-{n}", n + 1
    return row


def get_portal_settings(session: Session, principal: Principal, location_id: UUID) -> PortalSettings:
    platform.service.get_location(session, principal, location_id)
    authorize(principal, _PORTAL, location_id=location_id)
    return _settings_for(session, location_id)


def put_portal_settings(session: Session, principal: Principal, location_id: UUID, data: dict) -> PortalSettings:
    platform.service.get_location(session, principal, location_id)
    authorize(principal, _PORTAL, location_id=location_id)
    row = _settings_for(session, location_id)
    if data.get("terms_text") is not None and data["terms_text"] != row.terms_text and row.id is not None:
        row.terms_version = (row.terms_version or 1) + 1
    for field, value in data.items():
        setattr(row, field, value)
    if row.id is None:
        session.add(row)
    taken = session.scalar(select(PortalSettings.id).where(func.lower(PortalSettings.slug) == row.slug.lower(),
                                                           PortalSettings.location_id != location_id))  # fmt: skip
    if taken:
        raise Conflict("Another location uses this address.", code="portal-slug-taken")
    session.flush()
    audit.record(session, _PORTAL, row, location_id=location_id, changes=audit.diff(row))
    return row


def public_portal_config(session: Session) -> dict:
    """What an anonymous visitor may see: enabled, public locations and their landing content."""
    rows = session.scalars(select(PortalSettings).where(PortalSettings.is_enabled, PortalSettings.is_public))
    return {"facility_name": _facility(session), "locations": [
        {"location_id": r.location_id, "name": platform.service.location_name(session, r.location_id), "slug": r.slug,
         "welcome_text": r.welcome_text, "terms_text": r.terms_text, "terms_version": r.terms_version or 1,
         "allows_online_rentals": r.allows_online_rentals, "allows_online_purchases": r.allows_online_purchases}
        for r in rows
    ]}  # fmt: skip


# --- videos (SSP-16) -----------------------------------------------------------------------------------------

_CONTENT = "engagement.app_content.manage"


def _check_video(data: dict) -> None:
    if "url" in data and not rules.is_allowed_video_url(data["url"]):
        raise ValidationFailed("Use an https YouTube or Vimeo link.", pointer="/url", code="video-host-not-allowed")


def list_videos(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, _CONTENT)
    return paginate(session, scope_query(select(Video), principal, Video.location_id), query, id_column=Video.id,
                    sort_fields={"sort_order": Video.sort_order, "title": Video.title}, default_sort="sort_order",
                    filter_fields={"location_id": Video.location_id, "is_published": Video.is_published},
                    search=(Video.title,))  # fmt: skip


def get_video(session: Session, principal: Principal, video_id: UUID) -> Video:
    return _located(session, principal, Video, video_id, _CONTENT)


def create_video(session: Session, principal: Principal, data: dict) -> Video:
    authorize(principal, _CONTENT, location_id=data["location_id"])
    platform.service.get_location(session, principal, data["location_id"])
    _check_video(data)
    row = Video(**data)
    session.add(row)
    session.flush()
    audit.record(session, _CONTENT, row, location_id=row.location_id, changes=audit.diff(row))
    return row


def update_video(session: Session, principal: Principal, video_id: UUID, data: dict) -> Video:
    row = _located(session, principal, Video, video_id, _CONTENT)
    _check_video(data)
    data.pop("location_id", None)
    for field, value in data.items():
        setattr(row, field, value)
    audit.record(session, _CONTENT, row, location_id=row.location_id, changes=audit.diff(row))
    session.flush()
    return row


def delete_video(session: Session, principal: Principal, video_id: UUID) -> None:
    row = _located(session, principal, Video, video_id, _CONTENT)
    audit.record(session, _CONTENT, row, location_id=row.location_id, changes={"deleted": True})
    session.delete(row)
    session.flush()


def list_portal_videos(session: Session, principal: Principal, query: ListQuery) -> dict:
    _identity_clients(session, principal)
    return paginate(session, select(Video).where(Video.is_published), query, id_column=Video.id,
                    sort_fields={"sort_order": Video.sort_order}, default_sort="sort_order",
                    filter_fields={"location_id": Video.location_id})  # fmt: skip


def get_portal_video(session: Session, principal: Principal, video_id: UUID) -> Video:
    _identity_clients(session, principal)
    row = session.scalar(select(Video).where(Video.id == video_id, Video.is_published))
    if row is None:
        raise NotFound()
    return row
