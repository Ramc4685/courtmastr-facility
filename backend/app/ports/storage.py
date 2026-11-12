"""File storage port (security-baseline section 8). Contexts never touch bytes on disk or in a bucket directly:
they call these functions with an object key built by `object_key`, which pins every object under its
tenant's prefix. The adapter is wired by configuration in app.bootstrap."""

from collections.abc import Iterable
from typing import Protocol
from uuid import UUID


class Storage(Protocol):
    def put(self, key: str, data: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...  # a missing key is not an error
    def keys(self, prefix: str) -> Iterable[str]: ...
    def url(self, key: str, *, expires_in: int, content_type: str, disposition: str) -> str | None:
        """A time-limited direct download URL, or None when the adapter has none (the app serves the bytes)."""
        ...


_storage: Storage | None = None


def configure(storage: Storage) -> None:
    global _storage
    _storage = storage


def _adapter() -> Storage:
    assert _storage is not None, "no storage adapter configured"
    return _storage


def object_key(tenant_id: UUID, file_id: UUID, *, public: bool = False) -> str:
    """The stored name is the file id under the tenant prefix; the user's filename is metadata only (8.3).
    Public image renditions (logos) live under their own prefix, the only one a bucket policy may expose."""
    return f"t/{tenant_id}/{'public' if public else 'files'}/{file_id}"


def check_key(key: str, tenant_id: UUID) -> None:
    """T8: a key outside the session tenant's prefix is refused before any adapter sees it."""
    if not key.startswith(f"t/{tenant_id}/") or ".." in key or "//" in key:
        raise ValueError("object key outside the tenant prefix")


def put(tenant_id: UUID, key: str, data: bytes) -> None:
    check_key(key, tenant_id)
    _adapter().put(key, data)


def get(tenant_id: UUID, key: str) -> bytes:
    check_key(key, tenant_id)
    return _adapter().get(key)


def delete(tenant_id: UUID, key: str) -> None:
    check_key(key, tenant_id)
    _adapter().delete(key)


def keys(tenant_id: UUID) -> list[str]:
    """Every object key under the tenant's prefix (the purge job's orphan check)."""
    return list(_adapter().keys(f"t/{tenant_id}/"))


def url(tenant_id: UUID, key: str, *, expires_in: int, content_type: str, disposition: str) -> str | None:
    check_key(key, tenant_id)
    return _adapter().url(key, expires_in=expires_in, content_type=content_type, disposition=disposition)
