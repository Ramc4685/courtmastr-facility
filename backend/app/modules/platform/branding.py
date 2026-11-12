"""Logos (PLT-08): one for the tenant and one per location, shown in the staff shell and the member portal header.

The one public-read case of file storage (security-baseline 8.3). The upload is re-encoded by `files.clean` (EXIF
and polyglots gone) and stored under `t/<tenant>/public/`, the only prefix a bucket policy may expose;
`files.store` refuses `public=True` for any other purpose. The public URL is `storage.public_base_url` plus the
object key when a bucket or CDN serves that prefix, else the app's `GET /public/objects/{object_key}` route. A
replaced or removed logo's file is purged, so its URL stops working within the cache lifetime.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.auth import Principal, authorize
from app.core.errors import NotFound
from app.core.settings import get_settings
from app.modules.platform import files, service
from app.modules.platform.models import Logo, StoredFile

LOGO_TYPES = (files.JPEG, files.PNG)
MAX_LOGO_BYTES = 512 * 1024
PUBLIC_PATH = "/api/v1/public/objects"


def public_url(row: StoredFile) -> str:
    settings = get_settings()
    base = settings.storage.public_base_url or f"{settings.app.web_base_url}{PUBLIC_PATH}"
    return f"{base.rstrip('/')}/{row.object_key}"


def branding(session: Session) -> dict:
    """Internal (no principal: logos are public): the tenant's logo URL and each location's."""
    rows = session.execute(select(Logo.location_id, StoredFile).join(StoredFile, StoredFile.id == Logo.file_id)).all()
    return {
        "tenant_logo_url": next((public_url(f) for loc, f in rows if loc is None), None),
        "locations": [{"location_id": loc, "logo_url": public_url(f)} for loc, f in rows if loc is not None],
    }


def _gate(session: Session, principal: Principal, location_id: UUID | None) -> tuple[str, str]:
    """(audit action, file purpose); the tenant logo needs tenant.update, a location's needs location.update there."""
    if location_id is None:
        authorize(principal, "platform.tenant.update")
        return "platform.tenant.update", "tenant_logo"
    location = service.get_location(session, principal, location_id)
    authorize(principal, "platform.location.update", location_id=location.id)
    return "platform.location.update", "location_logo"


def _logo(session: Session, location_id: UUID | None) -> Logo | None:
    where = Logo.location_id.is_(None) if location_id is None else Logo.location_id == location_id
    return session.scalar(select(Logo).where(where).with_for_update())


def set_logo(
    session: Session, principal: Principal, location_id: UUID | None, data: bytes, content_type: str, name: str | None
) -> dict:
    """Upload or replace a logo (JPEG or PNG up to 512 KiB); the previous image is purged."""
    action, purpose = _gate(session, principal, location_id)
    cleaned, kind = files.clean(data, content_type, allowed=LOGO_TYPES, max_bytes=MAX_LOGO_BYTES)
    stored = files.store(
        session, cleaned, purpose=purpose, content_type=kind, uploaded_by=("staff", principal.staff_user_id),
        original_name=name, public=True,
    )  # fmt: skip
    row = _logo(session, location_id)
    old = row.file_id if row else None
    if row is None:
        row = Logo(location_id=location_id, file_id=stored.id)
        session.add(row)
    else:
        row.file_id = stored.id
    session.flush()
    if old:
        files.remove(session, old)
    audit.record(session, action, row, location_id=location_id,
                 changes={"logo_file_id": [old and str(old), str(stored.id)]})  # fmt: skip
    return branding(session)


def remove_logo(session: Session, principal: Principal, location_id: UUID | None) -> dict:
    action, _ = _gate(session, principal, location_id)
    row = _logo(session, location_id)
    if row is None:
        raise NotFound()
    old = row.file_id
    audit.record(session, action, row, location_id=location_id, changes={"logo_file_id": [str(old), None]})
    session.delete(row)
    session.flush()
    files.remove(session, old)
    return branding(session)


def public_object(session: Session, object_key: str) -> StoredFile:
    """The app's stand-in for a public bucket origin: a ready logo file whose key is exactly `object_key`, in the
    session's tenant. Anything else (another prefix, a purged or private file) is 404."""
    row = session.scalar(select(StoredFile).where(StoredFile.object_key == object_key))
    if row is None or row.status != "ready" or row.purpose not in files.PUBLIC_PURPOSES or "/public/" not in object_key:
        raise NotFound()
    return row
