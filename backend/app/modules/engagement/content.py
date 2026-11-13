"""Member app content (Phase 11 C2): news, info pages, announcements, promotions and gallery images (APP-07,
APP-14), the published location contacts (APP-08, APP-09), and the staff inbox for "Try us" trial pass requests
(APP-12) and in-app feedback (APP-10).

Content is plain text with links: anything that looks like an HTML tag is refused, so the app never renders
markup. A row with no location shows at every location; writing one needs the content key at every location
(like tenant-wide automation rules). A trial request answers 202 with no body whether or not anything was stored,
creates no client, and is stored only for a location whose portal is on and public.
"""

import re
from uuid import UUID

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.orm import Session

from app.core import audit, clock, events
from app.core.auth import Principal, authorize, authorize_tenant_wide, scope_query
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.pagination import ListQuery, paginate
from app.modules import platform
from app.modules.clients import households
from app.modules.clients import service as clients
from app.modules.engagement.events import AppInquiryReceived
from app.modules.engagement.models import AppContent, AppInquiry, LocationContact, PortalSettings
from app.modules.platform import files

CONTENT = "engagement.app_content.manage"
CONTACTS = "engagement.location_contact.manage"
INBOX_READ = "engagement.app_inquiry.read"
INBOX = "engagement.app_inquiry.manage"
RECEIVED = "engagement.app_inquiry.receive"
IMAGE, IMAGE_MAX_BYTES = "app_content_image", 900_000  # inside the 1 MiB body cap, like the form header image
_TAG = re.compile(r"<[A-Za-z/!]")  # the start of an HTML tag, closing tag, comment or doctype


def _outside(principal: Principal, location_id: UUID | None) -> bool:
    """A located row outside a location-limited caller's set (tenant-wide rows are never outside)."""
    ids = None if principal.kind == "system" else principal.location_ids
    return location_id is not None and ids is not None and location_id not in ids


def _check_text(data: dict) -> None:
    for field in ("title", "body_text"):
        if _TAG.search(data.get(field) or ""):
            raise ValidationFailed("Use plain text: HTML is not allowed.", pointer=f"/{field}", code="html-not-allowed")


def _check_window(publish_at, expires_at) -> None:
    if expires_at is not None and expires_at <= publish_at:
        raise ValidationFailed("The end must come after the start.", pointer="/expires_at", code="invalid-window")


def _authorize_content(principal: Principal, location_id: UUID | None) -> None:
    if location_id is None:
        authorize_tenant_wide(principal, CONTENT)  # shown at every location, so it governs all of them
    else:
        authorize(principal, CONTENT, location_id=location_id)


def _content(session: Session, principal: Principal, content_id: UUID, *, lock: bool = False) -> AppContent:
    stmt = select(AppContent).where(AppContent.id == content_id)
    row = session.scalar(stmt.with_for_update() if lock else stmt)
    if row is None or _outside(principal, row.location_id):
        raise NotFound()
    _authorize_content(principal, row.location_id)
    return row


def list_contents(session: Session, principal: Principal, query: ListQuery) -> dict:
    """Tenant-wide rows and those at the caller's locations."""
    authorize(principal, CONTENT)
    stmt = select(AppContent)
    if principal.kind != "system" and principal.location_ids is not None:
        stmt = stmt.where(or_(AppContent.location_id.is_(None), AppContent.location_id.in_(principal.location_ids)))
    return paginate(session, stmt, query, id_column=AppContent.id, default_sort="-publish_at",
                    sort_fields={"publish_at": AppContent.publish_at, "sort_order": AppContent.sort_order},
                    filter_fields={"kind": AppContent.kind, "location_id": AppContent.location_id})  # fmt: skip


def create_content(session: Session, principal: Principal, data: dict) -> AppContent:
    _authorize_content(principal, data.get("location_id"))
    if data.get("location_id"):
        platform.service.get_location(session, principal, data["location_id"])
    _check_text(data)
    _check_window(data["publish_at"], data.get("expires_at"))
    row = AppContent(**data)
    session.add(row)
    changes = audit.diff(row)  # before the flush clears the history
    session.flush()
    audit.record(session, CONTENT, row, location_id=row.location_id, changes=changes)
    return row


def update_content(session: Session, principal: Principal, content_id: UUID, data: dict) -> AppContent:
    """Errors: version-conflict (when `version` is sent and stale), html-not-allowed, invalid-window."""
    row = _content(session, principal, content_id, lock=True)
    version = data.pop("version", None)
    if version is not None and version != row.version:
        raise Conflict("Someone else changed this item; reload and try again.", code="version-conflict")
    for field in ("kind", "title", "body_text", "publish_at", "sort_order"):
        if data.get(field) is None:
            data.pop(field, None)  # not nullable: an explicit null keeps the value
    _check_text(data)
    _check_window(data.get("publish_at", row.publish_at), data.get("expires_at", row.expires_at))
    for field, value in data.items():
        setattr(row, field, value)
    row.version += 1
    audit.record(session, CONTENT, row, location_id=row.location_id, changes=audit.diff(row))
    session.flush()
    return row


def delete_content(session: Session, principal: Principal, content_id: UUID) -> None:
    row = _content(session, principal, content_id, lock=True)
    image = row.image_file_id
    audit.record(session, CONTENT, row, location_id=row.location_id, changes={"deleted": True})
    session.delete(row)
    session.flush()
    if image is not None:
        files.remove(session, image)


def set_image(session: Session, principal: Principal, content_id: UUID, data: bytes, content_type: str) -> AppContent:
    """JPEG or PNG, re-encoded and scanned through platform.files; replaces any earlier image."""
    row = _content(session, principal, content_id, lock=True)
    cleaned, kind = files.clean(data, content_type, allowed=(files.JPEG, files.PNG), max_bytes=IMAGE_MAX_BYTES)
    stored = files.store(session, cleaned, purpose=IMAGE, content_type=kind,
                         uploaded_by=("staff", principal.staff_user_id))  # fmt: skip
    replaced, row.image_file_id = row.image_file_id, stored.id
    session.flush()
    if replaced is not None:
        files.remove(session, replaced)
    audit.record(session, CONTENT, row, location_id=row.location_id, changes={"image_file_id": [None, "set"]})
    return row


def remove_image(session: Session, principal: Principal, content_id: UUID) -> None:
    """Idempotent: an item without an image is left as it is."""
    row = _content(session, principal, content_id, lock=True)
    if row.image_file_id is None:
        return
    removed, row.image_file_id = row.image_file_id, None
    session.flush()
    files.remove(session, removed)
    audit.record(session, CONTENT, row, location_id=row.location_id, changes={"image_file_id": ["set", None]})


def _live():
    now = clock.now()
    return AppContent.publish_at <= now, or_(AppContent.expires_at.is_(None), AppContent.expires_at > now)


def _portal_identity(principal: Principal) -> None:
    if principal.kind != "client":
        raise NotFound()


def list_portal_contents(session: Session, principal: Principal, query: ListQuery, location_id: UUID | None) -> dict:
    """Published, unexpired items: tenant-wide ones, plus the given location's. Filter: kind."""
    _portal_identity(principal)
    query.filters.pop("location_id", None)
    where: ColumnElement[bool] = AppContent.location_id.is_(None)
    if location_id is not None:
        where = or_(where, AppContent.location_id == location_id)
    return paginate(session, select(AppContent).where(where, *_live()), query, id_column=AppContent.id,
                    sort_fields={"publish_at": AppContent.publish_at, "sort_order": AppContent.sort_order},
                    default_sort="sort_order,-publish_at", filter_fields={"kind": AppContent.kind})  # fmt: skip


def portal_image(session: Session, principal: Principal, content_id: UUID):
    _portal_identity(principal)
    row = session.scalar(select(AppContent).where(AppContent.id == content_id, *_live()))
    if row is None or row.image_file_id is None:
        raise NotFound()
    return files.read(session, row.image_file_id)


# --- location contacts (APP-08, APP-09) ----------------------------------------------------------------------


def _check_reachable(phone: str | None, email: str | None) -> None:
    if not phone and not email:
        raise ValidationFailed("Give a phone number or an email address.", pointer="/phone", code="contact-unreachable")


def _contact(session: Session, principal: Principal, contact_id: UUID) -> LocationContact:
    row = session.get(LocationContact, contact_id)
    if row is None or _outside(principal, row.location_id):
        raise NotFound()
    authorize(principal, CONTACTS, location_id=row.location_id)
    return row


def list_contacts(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, CONTACTS)
    return paginate(session, scope_query(select(LocationContact), principal, LocationContact.location_id), query,
                    id_column=LocationContact.id, default_sort="sort_order",
                    sort_fields={"sort_order": LocationContact.sort_order, "name": LocationContact.name},
                    filter_fields={"location_id": LocationContact.location_id, "kind": LocationContact.kind})  # fmt: skip


def get_contact(session: Session, principal: Principal, contact_id: UUID) -> LocationContact:
    return _contact(session, principal, contact_id)


def create_contact(session: Session, principal: Principal, data: dict) -> LocationContact:
    authorize(principal, CONTACTS, location_id=data["location_id"])
    platform.service.get_location(session, principal, data["location_id"])
    _check_reachable(data.get("phone"), data.get("email"))
    row = LocationContact(**data)
    session.add(row)
    changes = audit.diff(row)  # before the flush clears the history
    session.flush()
    audit.record(session, CONTACTS, row, location_id=row.location_id, changes=changes)
    return row


def update_contact(session: Session, principal: Principal, contact_id: UUID, data: dict) -> LocationContact:
    row = _contact(session, principal, contact_id)
    for field in ("kind", "name", "sort_order"):
        if data.get(field) is None:
            data.pop(field, None)  # not nullable: an explicit null keeps the value
    _check_reachable(data.get("phone", row.phone), data.get("email", row.email))
    for field, value in data.items():
        setattr(row, field, value)
    audit.record(session, CONTACTS, row, location_id=row.location_id, changes=audit.diff(row))
    session.flush()
    return row


def delete_contact(session: Session, principal: Principal, contact_id: UUID) -> None:
    row = _contact(session, principal, contact_id)
    audit.record(session, CONTACTS, row, location_id=row.location_id, changes={"deleted": True})
    session.delete(row)
    session.flush()


def _open_portal(session: Session, location_id: UUID) -> bool:
    row = session.scalar(select(PortalSettings).where(PortalSettings.location_id == location_id))
    return row is not None and row.is_enabled and row.is_public


def public_contacts(session: Session, location_id: UUID) -> list[LocationContact]:
    """Anonymous: the location's contacts, only while its portal is on and public (else an empty list)."""
    if not _open_portal(session, location_id):
        return []
    stmt = select(LocationContact).where(LocationContact.location_id == location_id)
    return list(session.scalars(stmt.order_by(LocationContact.kind, LocationContact.sort_order, LocationContact.name)))


# --- the inbox: trial requests (APP-12) and feedback (APP-10) ------------------------------------------------


def _received(session: Session, row: AppInquiry) -> None:
    session.add(row)
    changes = audit.diff(row)  # before the flush clears the history
    session.flush()
    audit.record(session, RECEIVED, row, location_id=row.location_id, changes=changes)
    events.publish(session, AppInquiryReceived(app_inquiry_id=row.id, location_id=row.location_id, kind=row.kind),
                   row.id)  # fmt: skip


def request_trial(session: Session, data: dict) -> None:
    """Anonymous. Stored only when the location's portal is on and public; the caller answers the same either way.
    No client is created: staff follow up from the inbox."""
    if not _open_portal(session, data["location_id"]):
        return
    _received(session, AppInquiry(
        kind="trial", location_id=data["location_id"], contact_name=data["name"], contact_email=data["email"].lower(),
        contact_phone=data.get("phone"), interest=data.get("interest"), message=data.get("message") or "",
    ))  # fmt: skip


def send_feedback(session: Session, principal: Principal, data: dict) -> AppInquiry:
    """Feedback for the signed-in client or one it may act for (else 404). Goes to the staff inbox."""
    identity_id = principal.identity_id
    if (
        principal.kind != "client"
        or identity_id is None
        or households.can_act_for(session, identity_id, data["client_id"]) is None
    ):
        raise NotFound()
    client = clients.get(session, data["client_id"])
    location_id = data.get("location_id") or client.home_location_id
    if not platform.service.location_exists(session, location_id):
        raise ValidationFailed("Unknown location.", pointer="/location_id")
    row = AppInquiry(kind="feedback", location_id=location_id, client_id=client.id,
                     contact_name=clients.display_name(client), message=data["message"],
                     rating=data.get("rating"))  # fmt: skip
    _received(session, row)
    return row


def list_inquiries(session: Session, principal: Principal, query: ListQuery) -> dict:
    authorize(principal, INBOX_READ)
    return paginate(session, scope_query(select(AppInquiry), principal, AppInquiry.location_id), query,
                    id_column=AppInquiry.id, default_sort="-created_at",
                    sort_fields={"created_at": AppInquiry.created_at, "status": AppInquiry.status},
                    filter_fields={"kind": AppInquiry.kind, "status": AppInquiry.status,
                                   "location_id": AppInquiry.location_id})  # fmt: skip


def update_inquiry(session: Session, principal: Principal, inquiry_id: UUID, data: dict) -> AppInquiry:
    row = session.get(AppInquiry, inquiry_id)
    if row is None or _outside(principal, row.location_id):
        raise NotFound()
    authorize(principal, INBOX, location_id=row.location_id)
    if data["status"] != row.status:
        row.status = data["status"]
        handled = row.status != "new"
        row.handled_at = clock.now() if handled else None
        row.handled_by_staff_user_id = principal.staff_user_id if handled else None
        audit.record(session, INBOX, row, location_id=row.location_id, changes=audit.diff(row))
        session.flush()
    return row
