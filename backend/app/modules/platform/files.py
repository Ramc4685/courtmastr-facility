"""Stored files: the upload rules of security-baseline 8.2 and the `stored_file` rows behind app.ports.storage.

Internal functions (ADR 0009 section 9): the context that owns the referencing row authorizes the caller.
With the local storage adapter the bytes arrive in the request and are checked in-line; an object-storage
adapter moves this to the presigned upload and scan job of 8.1 without changing the callers.
"""

import hashlib
import io
import re
from collections.abc import Iterable
from uuid import UUID

from PIL import Image, UnidentifiedImageError
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.core.errors import NotFound, ValidationFailed
from app.core.ids import new_id
from app.modules.platform.models import StoredFile
from app.ports import storage

PDF, JPEG, PNG = "application/pdf", "image/jpeg", "image/png"
MAX_PIXELS = 40_000_000  # decompression-bomb guard (8.2: 40 megapixels)
_MAGIC = {PDF: (b"%PDF-",), JPEG: (b"\xff\xd8\xff",), PNG: (b"\x89PNG\r\n\x1a\n",)}
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")


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
) -> StoredFile:
    """Write already-checked bytes and their row. Bytes written for a transaction that later rolls back are
    orphans with no row; they are unreachable (every read goes through a row) and left for a purge job."""
    tenant_id = session.info["tenant_id"]
    file_id = new_id()
    key = storage.object_key(tenant_id, file_id)
    storage.put(tenant_id, key, data)
    row = StoredFile(
        id=file_id, object_key=key, purpose=purpose, content_type=content_type, size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(), original_name=safe_name(original_name), status="ready",
        uploaded_by_type=uploaded_by[0], uploaded_by_id=uploaded_by[1],
    )  # fmt: skip
    session.add(row)
    session.flush()
    return row


def read(session: Session, file_id: UUID) -> tuple[StoredFile, bytes]:
    row = session.get(StoredFile, file_id)
    if row is None or row.status != "ready":
        raise NotFound()
    return row, storage.get(session.info["tenant_id"], row.object_key)


def purge(session: Session, file_ids: Iterable[UUID] | Select) -> int:
    """Blank the bytes and mark the rows purged, so they can never be read again (erasure). Returns the count."""
    # shortcut: overwrites with empty bytes because the storage port has no delete; use files.remove once it lands.
    count = 0
    for row in session.scalars(select(StoredFile).where(StoredFile.id.in_(file_ids), StoredFile.status != "purged")):
        storage.put(session.info["tenant_id"], row.object_key, b"")
        row.status, row.original_name, row.sha256, row.size_bytes = "purged", None, None, 0
        count += 1
    return count
