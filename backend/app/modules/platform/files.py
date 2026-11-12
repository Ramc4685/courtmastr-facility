"""Stored files: the upload rules of security-baseline 8.2 and the `stored_file` rows behind app.ports.storage.

Internal functions (ADR 0009 section 9): the context that owns the referencing row authorizes the caller.
shortcut: bytes arrive in the request and are checked and scanned in-line, with every storage adapter; the
presigned direct-to-bucket upload and scan job of 8.1 is deferred until a surface needs files over the 20 MiB
body cap (README). Moving to it changes no caller.
"""

import hashlib
import hmac
import io
import logging
import re
from collections.abc import Iterable
from uuid import UUID

from PIL import Image, UnidentifiedImageError
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.core import clock, crypto
from app.core.errors import NotFound, PermissionDenied, ValidationFailed
from app.core.ids import new_id
from app.core.jobs import tenant_actor
from app.core.settings import get_settings
from app.modules.platform.models import StoredFile
from app.ports import scanner, storage

log = logging.getLogger(__name__)

PDF, JPEG, PNG = "application/pdf", "image/jpeg", "image/png"
MAX_PIXELS = 40_000_000  # decompression-bomb guard (8.2: 40 megapixels)
_MAGIC = {PDF: (b"%PDF-",), JPEG: (b"\xff\xd8\xff",), PNG: (b"\x89PNG\r\n\x1a\n",)}
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")
URL_TTL_SECONDS = 300  # signed download URLs (8.3: 5 minutes)
DOWNLOAD_PATH = "/api/v1/files"  # the local adapter's signed route (files_router)
PUBLIC_PURPOSES = frozenset({"tenant_logo", "location_logo"})  # the only files ever stored public (PLT-08)


def sniff(data: bytes) -> str | None:
    return next((kind for kind, heads in _MAGIC.items() if data.startswith(heads)), None)


def _reencode(data: bytes, kind: str) -> bytes:
    """Decode and re-encode: drops EXIF (GPS included) and neutralises polyglots (8.2)."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.width * image.height > MAX_PIXELS:
                raise ValidationFailed("The image is too large.", code="file-too-large")
            image.load()
            out = io.BytesIO()
            if kind == JPEG:
                image.convert("RGB").save(out, "JPEG", quality=88)
            else:
                image.save(out, "PNG")
            return out.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValidationFailed("The image could not be read.", code="file-type-mismatch") from None


def clean(data: bytes, declared: str, *, allowed: tuple[str, ...], max_bytes: int) -> tuple[bytes, str]:
    """Bytes ready to store and their content type, or a 422. The magic bytes must match the declared type."""
    if not data:
        raise ValidationFailed("The file is empty.", code="file-empty")
    if len(data) > max_bytes:
        raise ValidationFailed(f"Files may not exceed {max_bytes} bytes.", code="file-too-large")
    kind = sniff(data)
    if kind is None or kind not in allowed or kind != declared.split(";")[0].strip().lower():
        raise ValidationFailed(f"Allowed file types: {', '.join(allowed)}.", code="file-type-mismatch")
    return (data if kind == PDF else _reencode(data, kind)), kind


def safe_name(name: str | None) -> str | None:
    """Filename kept as metadata only (Content-Disposition), reduced to a safe character set (8.3)."""
    if not name:
        return None
    cleaned = _SAFE_NAME.sub("_", name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]).strip(" .")[:120]
    return cleaned or None


def store(
    session: Session,
    data: bytes,
    *,
    purpose: str,
    content_type: str,
    uploaded_by: tuple[str, UUID | None],
    original_name: str | None = None,
    public: bool = False,
    generated: bool = False,
) -> StoredFile:
    """Scan and write already-checked bytes and their row; a malware hit is a 422. `public` puts a processed
    image rendition (a logo) under the public prefix; nothing else is ever public (8.3). Bytes written for a
    transaction that later rolls back are orphans with no row: unreachable, and reported by `purge_files`.
    `generated`: bytes this system produced from its own data (an export zip, a report, a rendered PDF). They are
    not scanned, so a large export or a clamd outage cannot dead-letter them; any bytes that came from a person
    are always scanned, fail-closed. Internal only: no router passes it, and no request field maps to it."""
    if public and (purpose not in PUBLIC_PURPOSES or content_type not in (JPEG, PNG)):
        raise ValueError("only logo image renditions may be stored public")  # a programming error, not user input
    if not generated and (signature := scanner.scan(data)):
        log.warning("upload refused by the malware scanner", extra={"signature": signature, "purpose": purpose})
        raise ValidationFailed("The file failed the malware scan.", code="file-infected")
    tenant_id = session.info["tenant_id"]
    file_id = new_id()
    key = storage.object_key(tenant_id, file_id, public=public)
    storage.put(tenant_id, key, data)
    row = StoredFile(
        id=file_id, object_key=key, purpose=purpose, content_type=content_type, size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(), original_name=safe_name(original_name), status="ready",
        uploaded_by_type=uploaded_by[0], uploaded_by_id=uploaded_by[1],
    )  # fmt: skip
    session.add(row)
    session.flush()
    return row


def _ready(session: Session, file_id: UUID) -> StoredFile:
    row = session.get(StoredFile, file_id)
    if row is None or row.status != "ready":
        raise NotFound()
    return row


def read(session: Session, file_id: UUID) -> tuple[StoredFile, bytes]:
    row = _ready(session, file_id)
    return row, storage.get(session.info["tenant_id"], row.object_key)


def purge(session: Session, file_ids: Iterable[UUID] | Select) -> int:
    """Remove the rows (bytes deleted after commit) and blank their metadata (erasure). Returns the count."""
    count = 0
    for row in session.scalars(select(StoredFile).where(StoredFile.id.in_(file_ids), StoredFile.status != "purged")):
        remove(session, row.id)
        row.original_name, row.sha256, row.size_bytes = None, None, 0
        count += 1
    return count


def load(session: Session, file_id: UUID, *, purpose: str) -> StoredFile:
    """The row, if it is ready, in this tenant and of the expected purpose: check before a row references it."""
    row = _ready(session, file_id)
    if row.purpose != purpose:
        raise NotFound()
    return row


def remove(session: Session, file_id: UUID) -> None:
    """Row to `purged` now; bytes deleted once the transaction commits (`purge_files` retries a failed delete).
    Removing a purged file again does nothing."""
    row = session.get(StoredFile, file_id)
    if row is None:
        raise NotFound()
    if row.status == "purged":
        return
    row.status = "purged"
    session.flush()
    tenant_id, key = session.info["tenant_id"], row.object_key

    def delete() -> None:
        try:
            storage.delete(tenant_id, key)
        except Exception:  # the row is already purged; the hourly purge deletes the bytes
            log.warning("deleting a purged file's bytes failed", exc_info=True)

    session.info.setdefault("after_commit", []).append(delete)


def disposition(row: StoredFile) -> str:
    """Images we re-encoded are safe to show inline; everything else downloads (8.3)."""
    name = row.original_name or "file"
    return f'{"inline" if row.content_type in (JPEG, PNG) else "attachment"}; filename="{name}"'


def _signature(tenant_id: UUID, file_id: UUID, expires: int) -> str:
    return crypto.mac(f"file:{tenant_id}:{file_id}:{expires}")


def download_url(session: Session, file_id: UUID) -> str:
    """A signed URL for a ready file, valid 5 minutes: the bucket's own presigned URL, or with the local adapter
    the app's signed route."""
    row = _ready(session, file_id)
    tenant_id = session.info["tenant_id"]
    direct = storage.url(
        tenant_id, row.object_key, expires_in=URL_TTL_SECONDS, content_type=row.content_type,
        disposition=disposition(row),
    )  # fmt: skip
    if direct:
        return direct
    expires = int(clock.now().timestamp()) + URL_TTL_SECONDS
    query = f"exp={expires}&sig={_signature(tenant_id, row.id, expires)}"
    return f"{get_settings().app.web_base_url}{DOWNLOAD_PATH}/{tenant_id}/{row.id}?{query}"


def check_signature(tenant_id: UUID, file_id: UUID, expires: int, signature: str) -> None:
    """The local signed route's gate: a wrong signature is 404, a right but expired one 403."""
    if not hmac.compare_digest(
        signature.encode(), _signature(tenant_id, file_id, expires).encode()
    ):  # bytes: a non-ASCII str raises
        raise NotFound()
    if expires < clock.now().timestamp():
        raise PermissionDenied("This download link has expired.", code="link-expired")


@tenant_actor
def purge_files(session: Session) -> dict:
    """Hourly: delete the bytes of purged rows and report objects with no row (a store whose transaction rolled
    back, or one still in flight, so they are only reported). Idempotent: deleting twice is a no-op.
    shortcut: lists the whole tenant prefix and every row each run; page through both past ~100k files."""
    tenant_id = session.info["tenant_id"]
    status = dict(session.execute(select(StoredFile.object_key, StoredFile.status)).all())
    deleted, orphans = 0, []
    for key in storage.keys(tenant_id):
        if status.get(key) == "purged":
            storage.delete(tenant_id, key)
            deleted += 1
        elif key not in status:
            orphans.append(key)
    if orphans:
        log.warning("stored objects with no stored_file row", extra={"count": len(orphans), "keys": orphans[:20]})
    return {"deleted": deleted, "orphans": orphans}
