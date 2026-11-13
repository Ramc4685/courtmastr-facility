"""Engagement's side of a client merge (CLI-13) and of a data subject request (security-baseline 4.2) for the
messaging tables. The delivery log keeps its rows (counts and campaign stats) but erasure clears the address,
subject and body; inbox items and devices are deleted; queued sends are cancelled."""

from uuid import UUID

from sqlalchemy import delete, select, tuple_, update
from sqlalchemy.orm import Session

from app.modules import clients, platform
from app.modules.engagement import member
from app.modules.engagement.models import (
    AppInquiry,
    ClientFavorite,
    DeviceRegistration,
    InboxItem,
    Message,
    PortalSignup,
    ScheduledNotification,
)

_TABLES = ("message", "device_registration", "inbox_item", "scheduled_notification")


def _repoint(session: Session, loser_id: UUID, survivor_id: UUID) -> None:
    held = select(InboxItem.campaign_id).where(InboxItem.client_id == survivor_id, InboxItem.campaign_id.is_not(None))
    session.execute(delete(InboxItem).where(InboxItem.client_id == loser_id, InboxItem.campaign_id.in_(held)))
    for model in (Message, DeviceRegistration, InboxItem, ScheduledNotification):
        session.execute(update(model).where(model.client_id == loser_id).values(client_id=survivor_id))


def _export(session: Session, client_id: UUID) -> dict:
    messages = session.scalars(select(Message).where(Message.client_id == client_id).order_by(Message.queued_at))
    inbox = session.scalars(select(InboxItem).where(InboxItem.client_id == client_id).order_by(InboxItem.published_at))
    devices = session.scalars(select(DeviceRegistration).where(DeviceRegistration.client_id == client_id))
    return {
        "messages": [{"channel": m.channel, "subject": m.subject, "to_address": m.to_address, "status": m.status,
                      "queued_at": m.queued_at.isoformat()} for m in messages],
        "inbox": [{"title": i.title, "published_at": i.published_at.isoformat()} for i in inbox],
        "devices": [{"platform": d.platform, "registered_at": d.created_at.isoformat()} for d in devices],
    }  # fmt: skip


def _erase(session: Session, client_id: UUID) -> dict:
    cleared = session.execute(update(Message).where(Message.client_id == client_id).values(
        to_address=None, subject=None, body_text=None, unsubscribe_token_hash=None))  # fmt: skip
    session.execute(update(ScheduledNotification).where(ScheduledNotification.client_id == client_id,
                    ScheduledNotification.status == "scheduled").values(status="cancelled", payload={}))  # fmt: skip
    inbox = session.execute(delete(InboxItem).where(InboxItem.client_id == client_id))
    session.execute(update(Message).where(Message.client_id == client_id).values(device_registration_id=None))
    devices = session.execute(delete(DeviceRegistration).where(DeviceRegistration.client_id == client_id))
    return {"messages_cleared": cleared.rowcount, "inbox_deleted": inbox.rowcount, "devices_deleted": devices.rowcount}


# Public sign-ups (SSP-05): the row holds a name, address and phone until it expires; a merge moves the link and
# an erasure deletes the client's rows.
def _repoint_signups(session: Session, loser_id: UUID, survivor_id: UUID) -> None:
    session.execute(update(PortalSignup).where(PortalSignup.client_id == loser_id).values(client_id=survivor_id))


def _export_signups(session: Session, client_id: UUID) -> dict:
    rows = session.scalars(select(PortalSignup).where(PortalSignup.client_id == client_id))
    return {"portal_signups": [{"email": r.email, "first_name": r.first_name, "last_name": r.last_name,
                                "status": r.status, "created_at": r.created_at.isoformat()} for r in rows]}  # fmt: skip


def _erase_signups(session: Session, client_id: UUID) -> dict:
    gone = session.execute(delete(PortalSignup).where(PortalSignup.client_id == client_id)).rowcount
    return {"portal_signups_deleted": gone}


# App feedback (APP-10): a merge moves it to the survivor; an erasure keeps the row (inbox counts, rating) and
# blanks the contact fields and the message.
def _repoint_inquiries(session: Session, loser_id: UUID, survivor_id: UUID) -> None:
    session.execute(update(AppInquiry).where(AppInquiry.client_id == loser_id).values(client_id=survivor_id))


def _export_inquiries(session: Session, client_id: UUID) -> dict:
    rows = session.scalars(select(AppInquiry).where(AppInquiry.client_id == client_id).order_by(AppInquiry.created_at))
    return {"app_feedback": [{"kind": r.kind, "message": r.message, "rating": r.rating, "status": r.status,
                              "created_at": r.created_at.isoformat()} for r in rows]}  # fmt: skip


def _erase_inquiries(session: Session, client_id: UUID) -> dict:
    cleared = session.execute(update(AppInquiry).where(AppInquiry.client_id == client_id).values(
        contact_name="", contact_email=None, contact_phone=None, interest=None, message=""))  # fmt: skip
    return {"app_feedback_cleared": cleared.rowcount}


# Favourites (APP-13): a merge moves them to the survivor, dropping any the survivor already has; an erasure
# deletes them.
def _repoint_favorites(session: Session, loser_id: UUID, survivor_id: UUID) -> None:
    held = select(ClientFavorite.kind, ClientFavorite.target_id).where(ClientFavorite.client_id == survivor_id)
    session.execute(delete(ClientFavorite).where(
        ClientFavorite.client_id == loser_id, tuple_(ClientFavorite.kind, ClientFavorite.target_id).in_(held)))  # fmt: skip
    session.execute(update(ClientFavorite).where(ClientFavorite.client_id == loser_id).values(client_id=survivor_id))


def _export_favorites(session: Session, client_id: UUID) -> dict:
    rows = session.scalars(select(ClientFavorite).where(ClientFavorite.client_id == client_id))
    return {"app_favorites": [{"kind": r.kind, "target_id": str(r.target_id),
                               "created_at": r.created_at.isoformat()} for r in rows]}  # fmt: skip


def _erase_favorites(session: Session, client_id: UUID) -> dict:
    gone = session.execute(delete(ClientFavorite).where(ClientFavorite.client_id == client_id)).rowcount
    return {"app_favorites_deleted": gone}


clients.merge.register_merge_handler("engagement_favorite", tables=("client_favorite",), repoint=_repoint_favorites)
platform.privacy.register_subject_handler(
    "engagement_favorite", tables=("client_favorite",), export=_export_favorites, erase=_erase_favorites
)
platform.retention.register_purge("engagement_app_usage_day", member.purge_usage)  # anonymous, so no erasure reaches it
clients.merge.register_merge_handler("engagement_app_inquiry", tables=("app_inquiry",), repoint=_repoint_inquiries)
platform.privacy.register_subject_handler(
    "engagement_app_inquiry", tables=("app_inquiry",), export=_export_inquiries, erase=_erase_inquiries
)
clients.merge.register_merge_handler("engagement_signup", tables=("portal_signup",), repoint=_repoint_signups)
platform.privacy.register_subject_handler(
    "engagement_signup", tables=("portal_signup",), export=_export_signups, erase=_erase_signups
)
clients.merge.register_merge_handler("engagement_messaging", tables=_TABLES, repoint=_repoint)
platform.privacy.register_subject_handler("engagement_messaging", tables=_TABLES, export=_export, erase=_erase)
