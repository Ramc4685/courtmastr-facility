"""Virtual sessions (INT-09, SSP-18, CLS-08): a tenant's Zoom connection, the online meeting of a session, and
the member join. The join URL is sealed at rest, shown to staff only, and handed to a member only at click time
by the join command, which checks their place, opens 10 minutes before the start and marks them attended."""

import json
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core import audit, clock, crypto
from app.core.auth import Principal, authorize
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.settings import get_settings
from app.modules import programs, scheduling
from app.modules.integrations.models import (
    ConnectionStatus,
    ExternalConnection,
    MeetingProvider,
    MeetingStatus,
    Provider,
    VideoMeeting,
)

MANAGE = "scheduling.session.manage"
JOIN_OPENS = timedelta(minutes=10)
SIMULATED = "simulated"  # a client id that selects the simulated adapter, in dev and test only


# --- the Zoom connection -----------------------------------------------------------------------------------


def connector(app: dict) -> Any:
    """The VideoMeeting adapter for a tenant's Zoom app. shortcut: the simulated adapter is chosen by the client
    id `simulated` in dev and test, because core settings were frozen this phase; elsewhere it reaches Zoom."""
    from app.adapters.video import FakeVideo, ZoomVideo

    if app["client_id"] == SIMULATED and get_settings().env in ("dev", "test"):
        return FakeVideo()
    return ZoomVideo(account_id=app["account_id"], client_id=app["client_id"], client_secret=app["client_secret"])


def connect_zoom(session: Session, row: ExternalConnection, app: dict | None) -> None:
    """Internal (service.create_external_connection): verify the tenant's Server-to-Server app against Zoom,
    claim its account for this tenant, and seal the credentials. Errors: provider-unavailable, account-in-use."""
    if not app:
        raise ValidationFailed("A Zoom connection needs the app's account id, client id and secret", pointer="/zoom")
    try:
        connector(app).check_account()
    except Exception:  # the provider boundary: the reason stays out of the response
        raise ValidationFailed("Zoom refused these credentials", pointer="/zoom", code="provider-unavailable") from None
    claimed = session.scalar(
        text("SELECT app.claim_provider_account(:p, :r)"), {"p": Provider.ZOOM.value, "r": app["account_id"]}
    )
    if not claimed:
        raise Conflict("This Zoom account is connected to another account", code="account-in-use")
    tenant_id = session.info["tenant_id"]
    row.credentials_ciphertext = crypto.encrypt(json.dumps(app), tenant_id)
    row.external_account_id, row.status = app["account_id"], ConnectionStatus.ACTIVE


def _video(session: Session, connection: ExternalConnection) -> Any:
    from app.modules.integrations import service

    app = json.loads(crypto.decrypt(connection.credentials_ciphertext or "", session.info["tenant_id"]))
    return service.adapter_for(session, connector(app), "video_meeting", connection.location_id)


def _zoom_connection(session: Session, location_id: UUID) -> ExternalConnection:
    """The location's own active Zoom connection, else the tenant-wide one."""
    rows = session.scalars(
        select(ExternalConnection).where(
            ExternalConnection.provider == Provider.ZOOM, ExternalConnection.status == ConnectionStatus.ACTIVE,
            (ExternalConnection.location_id == location_id) | ExternalConnection.location_id.is_(None),
        )
    ).all()  # fmt: skip
    if not rows:
        raise ValidationFailed("Connect Zoom first", pointer="/provider", code="provider-unavailable")
    return sorted(rows, key=lambda r: r.location_id is None)[0]


# --- the meeting of a session ------------------------------------------------------------------------------


def _seat(session: Session, principal: Principal, session_id: UUID) -> dict:
    seat = scheduling.service.get_session(session, session_id)  # NotFound for another tenant's id (RLS)
    authorize(principal, MANAGE, location_id=seat["location_id"])
    return seat


def _open(session: Session, value: str | None) -> str | None:
    return crypto.decrypt(value, session.info["tenant_id"]) if value else None


def _seal(session: Session, value: str | None) -> str | None:
    return crypto.encrypt(value, session.info["tenant_id"]) if value else None


def view(session: Session, row: VideoMeeting) -> dict:
    return {
        "id": row.id, "session_id": row.session_id, "provider": row.provider, "status": row.status,
        "external_connection_id": row.external_connection_id, "join_url": _open(session, row.join_url_ciphertext),
        "has_passcode": row.passcode_ciphertext is not None, "last_error": row.last_error,
        "created_at": row.created_at, "updated_at": row.updated_at,
    }  # fmt: skip


def _row(session: Session, session_id: UUID) -> VideoMeeting | None:
    return session.scalar(select(VideoMeeting).where(VideoMeeting.session_id == session_id).with_for_update())


def get_meeting(session: Session, principal: Principal, session_id: UUID) -> dict:
    _seat(session, principal, session_id)
    row = _row(session, session_id)
    if row is None:
        raise NotFound()
    return view(session, row)


def _drop_at_provider(session: Session, row: VideoMeeting) -> None:
    if row.provider == MeetingProvider.ZOOM and row.external_meeting_id and row.external_connection_id:
        connection = session.get(ExternalConnection, row.external_connection_id)
        if connection is not None and connection.status == ConnectionStatus.ACTIVE:
            try:
                _video(session, connection).delete_meeting(row.external_meeting_id)
            except Exception:  # best effort: the local row goes either way, so members lose access at once
                pass


def put_meeting(session: Session, principal: Principal, session_id: UUID, data: dict) -> dict:
    """Attach or replace the meeting. `manual` stores a pasted https link; `zoom` creates (or moves) the meeting
    through the location's Zoom connection. Errors: provider-unavailable."""
    seat = _seat(session, principal, session_id)
    if seat["status"] == "cancelled" or seat["ends_at"] <= clock.now():
        raise Conflict("A cancelled or finished session takes no meeting", code="invalid-state-transition")
    row = _row(session, session_id)
    if data["provider"] == MeetingProvider.MANUAL:
        if not data.get("join_url"):
            raise ValidationFailed("A pasted meeting needs its join link", pointer="/join_url")
        if row is not None and row.provider == MeetingProvider.ZOOM:
            _drop_at_provider(session, row)
        fields: dict[str, Any] = {"provider": MeetingProvider.MANUAL, "external_connection_id": None,
                  "external_meeting_id": None,
                  "join_url_ciphertext": _seal(session, data["join_url"]), "host_start_url_ciphertext": None,
                  "passcode_ciphertext": _seal(session, data.get("passcode"))}  # fmt: skip
    else:
        connection = _zoom_connection(session, seat["location_id"])
        video = _video(session, connection)
        minutes = max(int((seat["ends_at"] - seat["starts_at"]).total_seconds() // 60), 1)
        # move the existing meeting only when it lives on this same connection and keeps its host
        same = (
            row is not None and row.provider == MeetingProvider.ZOOM and row.external_meeting_id is not None
            and row.external_connection_id == connection.id and not data.get("host_external_user_id")
        )  # fmt: skip
        if row is not None and row.provider == MeetingProvider.ZOOM and not same:
            _drop_at_provider(session, row)
        try:
            if same and row is not None and row.external_meeting_id:
                video.update_meeting(row.external_meeting_id, starts_at=seat["starts_at"], minutes=minutes)
                made = None
            else:
                topic = seat.get("public_title") or "Session"
                made = video.create_meeting(topic=topic, starts_at=seat["starts_at"], minutes=minutes,
                                            host_user_id=data.get("host_external_user_id") or "me")  # fmt: skip
        except Exception:  # the provider boundary
            raise ValidationFailed(
                "Zoom could not schedule the meeting", pointer="/provider", code="provider-unavailable"
            ) from None
        fields = {"provider": MeetingProvider.ZOOM, "external_connection_id": connection.id}
        if made is not None:
            fields |= {"external_meeting_id": made.external_meeting_id,
                       "join_url_ciphertext": _seal(session, made.join_url),
                       "host_start_url_ciphertext": _seal(session, made.host_start_url),
                       "passcode_ciphertext": _seal(session, made.passcode)}  # fmt: skip
    if row is None:
        row = VideoMeeting(session_id=session_id, location_id=seat["location_id"], **fields)
        session.add(row)
    else:
        for key, value in fields.items():
            setattr(row, key, value)
    row.status, row.last_error = MeetingStatus.SCHEDULED, None
    session.flush()
    audit.record(session, "integrations.video_meeting.put", row, location_id=row.location_id,
                 changes=audit.diff(row))  # fmt: skip
    session.refresh(row)
    return view(session, row)


def delete_meeting(session: Session, principal: Principal, session_id: UUID) -> None:
    _seat(session, principal, session_id)
    row = _row(session, session_id)
    if row is None:
        raise NotFound()
    _drop_at_provider(session, row)
    audit.record(session, "integrations.video_meeting.delete", row, location_id=row.location_id, changes={})
    session.delete(row)
    session.flush()


def on_disconnect(session: Session, connection: ExternalConnection) -> None:
    """Internal (service.disconnect_external_connection): the meetings of a disconnected Zoom account stop being
    joinable at once. They are deleted at Zoom first, while the credentials still work, best effort."""
    rows = session.scalars(select(VideoMeeting).where(VideoMeeting.external_connection_id == connection.id)).all()
    for row in rows:
        _drop_at_provider(session, row)
        row.status, row.last_error = MeetingStatus.FAILED, "connection-disconnected"
        audit.record(session, "integrations.video_meeting.put", row, location_id=row.location_id,
                     changes=audit.diff(row))  # fmt: skip
    session.flush()


def on_session_moved(session: Session, booking_id: UUID) -> None:
    """Internal (handlers, after the booking's own commit): a rescheduled session's Zoom meeting moves with it.
    If Zoom refuses, the meeting is marked failed so staff see it. Re-running sends the same times again."""
    view = scheduling.service.booking_views(session, [booking_id]).get(booking_id)
    seat = view.get("session") if view else None
    row = _row(session, seat["id"]) if seat else None
    if view is None or row is None or row.provider != MeetingProvider.ZOOM or not row.external_meeting_id:
        return
    connection = session.get(ExternalConnection, row.external_connection_id) if row.external_connection_id else None
    if connection is None or connection.status != ConnectionStatus.ACTIVE or row.status != MeetingStatus.SCHEDULED:
        return
    minutes = max(int((view["ends_at"] - view["starts_at"]).total_seconds() // 60), 1)
    try:
        _video(session, connection).update_meeting(
            row.external_meeting_id, starts_at=view["starts_at"], minutes=minutes
        )
    except Exception:  # the provider boundary: staff re-save the meeting from the session panel
        row.status, row.last_error = MeetingStatus.FAILED, "reschedule-failed"
    audit.record(session, "integrations.video_meeting.put", row, location_id=row.location_id,
                 changes=audit.diff(row))  # fmt: skip
    session.flush()


def on_session_cancelled(session: Session, session_id: UUID) -> None:
    """Internal (handlers, after the cancellation's commit): the meeting is deleted at Zoom and here. Idempotent."""
    row = _row(session, session_id)
    if row is None:
        return
    _drop_at_provider(session, row)
    audit.record(session, "integrations.video_meeting.delete", row, location_id=row.location_id, changes={})
    session.delete(row)
    session.flush()


# --- the member join ---------------------------------------------------------------------------------------


def join(session: Session, principal: Principal, enrollment_id: UUID) -> dict:
    """The join URL for one's own confirmed place, from 10 minutes before the start until the end, and the
    attendance mark that goes with it. Errors: invalid-state-transition (not a booked place, or the session
    is cancelled), policy-violation (outside the join window)."""
    place = programs.selfservice.own_place(session, principal, enrollment_id)
    if place["session_id"] is None:
        raise NotFound()
    row = session.scalar(select(VideoMeeting).where(VideoMeeting.session_id == place["session_id"]))
    if row is None:
        raise NotFound()
    seat = scheduling.service.get_session(session, place["session_id"])
    if place["status"] != "enrolled" or seat["status"] != "confirmed" or row.status != MeetingStatus.SCHEDULED:
        raise Conflict("This place cannot join the session", code="invalid-state-transition")
    now = clock.now()
    if not (seat["starts_at"] - JOIN_OPENS <= now < seat["ends_at"]):
        raise Conflict("The session opens 10 minutes before it starts", code="policy-violation",
                       reason="outside-join-window")  # fmt: skip
    programs.service.mark_attended_by_check_in(
        session, client_id=place["client_id"], location_id=place["location_id"], at=now,
        early=seat["ends_at"] - seat["starts_at"], late=JOIN_OPENS, source="video_join", session_id=seat["id"],
    )  # fmt: skip
    return {"join_url": _open(session, row.join_url_ciphertext), "passcode": _open(session, row.passcode_ciphertext)}
