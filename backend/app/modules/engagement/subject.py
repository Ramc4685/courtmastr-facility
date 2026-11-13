"""Engagement's side of a client merge (CLI-13) and of a data subject request (security-baseline 4.2) for the
messaging tables. The delivery log keeps its rows (counts and campaign stats) but erasure clears the address,
subject and body; inbox items and devices are deleted; queued sends are cancelled."""

from datetime import timedelta
from uuid import UUID

from sqlalchemy import and_, delete, or_, select, tuple_, update
from sqlalchemy.orm import Session

from app.core import clock
from app.core.settings import get_settings
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


def _purge_bodies(session: Session) -> int:
    """Retention hook (platform.retention.register_purge, security-baseline 2.3 "bodies 90 days"): a
    message's rendered body goes after `retention.message_body_days`; the row (recipient, status, counts) stays.
    A message still queued keeps its body, which the send needs. One batch per run; idempotent."""
    cfg = get_settings().retention
    due = (
        select(Message.id)
        .where(Message.body_text.is_not(None), Message.status != "queued",
               Message.queued_at < clock.now() - timedelta(days=cfg.message_body_days))
        .limit(cfg.batch_rows).with_for_update(skip_locked=True)
    )  # fmt: skip
    return session.execute(update(Message).where(Message.id.in_(due)).values(body_text=None)).rowcount


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


# Retention for rows no erasure can reach because no client is linked. An unconfirmed sign-up goes a week after
# its link expires (the grace week keeps a late "my link expired" support call answerable). A trial request goes
# 180 days after it arrived, or 90 days after staff closed or converted it, whichever is first (a trial request
# never links a client: ck_app_inquiry_client).
SIGNUP_GRACE, TRIAL_MAX_AGE, TRIAL_AFTER_HANDLED = timedelta(days=7), timedelta(days=180), timedelta(days=90)


def _purge(session: Session, model, *where) -> int:
    ids = list(session.scalars(select(model.id).where(*where).limit(get_settings().retention.batch_rows)))
    if ids:
        session.execute(delete(model).where(model.id.in_(ids)))
    return len(ids)


def purge_signups(session: Session) -> int:
    expired = clock.now() - SIGNUP_GRACE
    return _purge(session, PortalSignup, PortalSignup.status != "confirmed", PortalSignup.expires_at < expired)


def purge_trials(session: Session) -> int:
    now = clock.now()
    handled = and_(AppInquiry.status.in_(("closed", "converted")), AppInquiry.handled_at < now - TRIAL_AFTER_HANDLED)
    return _purge(session, AppInquiry, AppInquiry.kind == "trial", or_(AppInquiry.created_at < now - TRIAL_MAX_AGE,
                                                                        handled))  # fmt: skip


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
platform.retention.register_purge("engagement_portal_signup", purge_signups)
platform.retention.register_purge("engagement_trial_inquiry", purge_trials)
clients.merge.register_merge_handler("engagement_signup", tables=("portal_signup",), repoint=_repoint_signups)
platform.privacy.register_subject_handler(
    "engagement_signup", tables=("portal_signup",), export=_export_signups, erase=_erase_signups
)
clients.merge.register_merge_handler("engagement_messaging", tables=_TABLES, repoint=_repoint)
platform.privacy.register_subject_handler("engagement_messaging", tables=_TABLES, export=_export, erase=_erase)
platform.retention.register_purge("engagement_message_bodies", _purge_bodies)
