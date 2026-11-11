"""Engagement's side of a client merge (CLI-13) and of a data subject request (security-baseline 4.2) for the
messaging tables. The delivery log keeps its rows (counts and campaign stats) but erasure clears the address,
subject and body; inbox items and devices are deleted; queued sends are cancelled."""

from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.modules import clients, platform
from app.modules.engagement.models import DeviceRegistration, InboxItem, Message, ScheduledNotification

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
    devices = session.execute(delete(DeviceRegistration).where(DeviceRegistration.client_id == client_id))
    return {"messages_cleared": cleared.rowcount, "inbox_deleted": inbox.rowcount, "devices_deleted": devices.rowcount}


clients.merge.register_merge_handler("engagement_messaging", tables=_TABLES, repoint=_repoint)
platform.privacy.register_subject_handler("engagement_messaging", tables=_TABLES, export=_export, erase=_erase)
