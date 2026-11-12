"""Client files (phase 10 chip F): the client photo (CLI-12) and attachments on activity notes (CLI-09).

Bytes go through platform.files: `clean` sniffs the type (never the extension or declared type alone) and
re-encodes images, `store` keeps them under a generated key, never the user's filename. A file is served only
through the record that points at it, after both gates, so a file id that is not this client's photo or this
note's attachment is 404. Attachments follow their note's reach (`clients.activity.read`); none reach the portal.

TODO(Phase 8 chip K1): swap `files.read` for `files.load`/`files.download_url`, and purge the bytes of a replaced
or removed photo or attachment with `files.remove`; until then the stored_file row stays, unreferenced. A purge
must first check for other references: merge backfills the photo, so a survivor and its tombstone can share one
stored_file. Erasure already marks the rows `purged` with no name (`purge_rows`); only their bytes remain.
"""

from typing import ClassVar, Literal
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core import audit, events
from app.core.auth import Principal
from app.core.errors import Conflict, NotFound
from app.core.events import Event
from app.core.settings import get_settings
from app.modules.clients import activity, service
from app.modules.clients.events import ClientUpdated
from app.modules.clients.models import Client, ClientNote, ClientNoteAttachment
from app.modules.platform import files
from app.modules.platform.models import StoredFile

PHOTO_MAX_BYTES = 5_242_880  # 5 MiB before re-encoding; a desk webcam still is far smaller
MAX_ATTACHMENTS_PER_NOTE = 5
PHOTO, ATTACHMENT = "client_photo", "client_attachment"


class NoteAttachmentChanged(Event):
    aggregate_type: ClassVar[str] = "client_note"
    type: Literal["clients.note.attachment_changed"] = "clients.note.attachment_changed"
    note_id: UUID
    attachment_id: UUID
    change: str  # added | removed


def _read(session: Session, file_id: UUID, purpose: str) -> tuple[StoredFile, bytes]:
    row, data = files.read(session, file_id)
    if row.purpose != purpose:
        raise NotFound()
    return row, data


# --- photo (CLI-12) ------------------------------------------------------------------------------------------


def _set_photo_id(session: Session, client: Client, file_id: UUID | None) -> Client:
    client.photo_file_id = file_id
    client.version += 1
    audit.record(
        session, "clients.client.update", client, location_id=client.home_location_id, changes=audit.diff(client)
    )
    session.flush()
    events.publish(session, ClientUpdated(client_id=client.id), client.id)
    return client


def set_photo(session: Session, principal: Principal, client_id: UUID, data: bytes, content_type: str) -> Client:
    """Upload or replace the photo: JPEG or PNG, re-encoded (EXIF and GPS dropped)."""
    client = service.load(session, principal, client_id, "clients.client.update")
    service._require_live(client)
    cleaned, kind = files.clean(data, content_type, allowed=(files.JPEG, files.PNG), max_bytes=PHOTO_MAX_BYTES)
    stored = files.store(
        session, cleaned, purpose=PHOTO, content_type=kind, uploaded_by=("staff", principal.staff_user_id)
    )
    return _set_photo_id(session, client, stored.id)  # TODO(K1): files.remove the replaced photo's bytes


def remove_photo(session: Session, principal: Principal, client_id: UUID) -> None:
    client = service.load(session, principal, client_id, "clients.client.update")
    service._require_live(client)
    if client.photo_file_id is None:
        raise NotFound("The client has no photo.")
    _set_photo_id(session, client, None)  # TODO(K1): files.remove the bytes, unless a tombstone shares them


def get_photo(session: Session, principal: Principal, client_id: UUID) -> tuple[StoredFile, bytes]:
    client = service.load(session, principal, client_id, "clients.client.read")
    if client.photo_file_id is None:
        raise NotFound("The client has no photo.")
    return _read(session, client.photo_file_id, PHOTO)


# --- note attachments (CLI-09) -------------------------------------------------------------------------------


def attachment_view(session: Session, row: ClientNoteAttachment) -> dict:
    stored = session.get(StoredFile, row.stored_file_id)
    return {
        "id": row.id, "client_note_id": row.client_note_id, "file_name": stored.original_name,
        "content_type": stored.content_type, "size_bytes": stored.size_bytes, "created_at": row.created_at,
    }  # fmt: skip


def _attachments(session: Session, note_id: UUID) -> list[ClientNoteAttachment]:
    stmt = select(ClientNoteAttachment).where(ClientNoteAttachment.client_note_id == note_id)
    return list(session.scalars(stmt.order_by(ClientNoteAttachment.created_at, ClientNoteAttachment.id)))


def export_attachments(session: Session, note_id: UUID) -> list[dict]:
    """Subject-access export (merge._export_clients): what is attached, not the bytes."""
    views = (attachment_view(session, row) for row in _attachments(session, note_id))
    return [{k: v[k] for k in ("file_name", "content_type", "size_bytes")} for v in views]


# --- erasure (merge._erase_clients) ------------------------------------------------------------------------


def file_ids_of(session: Session, client: Client) -> list[UUID]:
    """The client's photo and the files attached to its notes."""
    attached = select(ClientNoteAttachment.stored_file_id).join(
        ClientNote, ClientNote.id == ClientNoteAttachment.client_note_id
    )
    ids = list(session.scalars(attached.where(ClientNote.client_id == client.id)))
    return ids + ([client.photo_file_id] if client.photo_file_id else [])


def purge_rows(session: Session, file_ids: list[UUID]) -> None:
    """Drop the name and mark the rows purged (files.read 404s them). TODO(K1): files.remove the bytes."""
    if file_ids:
        session.execute(
            update(StoredFile).where(StoredFile.id.in_(file_ids)).values(original_name=None, status="purged")
        )


def list_attachments(session: Session, principal: Principal, note_id: UUID) -> list[dict]:
    note = activity._note(session, principal, note_id, "clients.activity.read")
    return [attachment_view(session, row) for row in _attachments(session, note.id)]


def add_attachment(
    session: Session, principal: Principal, note_id: UUID, data: bytes, content_type: str, name: str | None
) -> dict:
    """PDF, JPEG or PNG up to storage.max_upload_bytes; at most MAX_ATTACHMENTS_PER_NOTE per note."""
    note = activity._note(session, principal, note_id, "clients.activity.write")
    # lock the note so two concurrent uploads cannot both pass the count below
    session.execute(select(ClientNote.id).where(ClientNote.id == note.id).with_for_update())
    count = session.scalar(select(func.count()).where(ClientNoteAttachment.client_note_id == note.id))
    if count >= MAX_ATTACHMENTS_PER_NOTE:
        raise Conflict(f"A note takes at most {MAX_ATTACHMENTS_PER_NOTE} attachments.", code="too-many-attachments")
    cleaned, kind = files.clean(
        data,
        content_type,
        allowed=(files.PDF, files.JPEG, files.PNG),
        max_bytes=get_settings().storage.max_upload_bytes,
    )
    stored = files.store(
        session, cleaned, purpose=ATTACHMENT, content_type=kind, uploaded_by=("staff", principal.staff_user_id),
        original_name=name,
    )  # fmt: skip
    row = ClientNoteAttachment(client_note_id=note.id, stored_file_id=stored.id)
    session.add(row)
    session.flush()
    audit.record(session, "clients.activity.write", note, location_id=note.location_id, changes={"attachments": True})
    events.publish(session, NoteAttachmentChanged(note_id=note.id, attachment_id=row.id, change="added"), note.id)
    return attachment_view(session, row)


def _attachment(session: Session, principal: Principal, note_id: UUID, attachment_id: UUID, key: str):
    note = activity._note(session, principal, note_id, key)
    row = session.get(ClientNoteAttachment, attachment_id)
    if row is None or row.client_note_id != note.id:
        raise NotFound()
    return note, row


def get_attachment(
    session: Session, principal: Principal, note_id: UUID, attachment_id: UUID
) -> tuple[StoredFile, bytes]:
    _, row = _attachment(session, principal, note_id, attachment_id, "clients.activity.read")
    return _read(session, row.stored_file_id, ATTACHMENT)


def remove_attachment(session: Session, principal: Principal, note_id: UUID, attachment_id: UUID) -> None:
    note, row = _attachment(session, principal, note_id, attachment_id, "clients.activity.write")
    audit.record(session, "clients.activity.write", note, location_id=note.location_id, changes={"attachments": True})
    events.publish(session, NoteAttachmentChanged(note_id=note.id, attachment_id=row.id, change="removed"), note.id)
    session.delete(row)  # TODO(K1): files.remove the bytes
    session.flush()
