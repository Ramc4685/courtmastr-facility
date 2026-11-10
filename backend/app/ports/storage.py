"""File storage port (security-baseline section 8). Contexts never touch bytes on disk or in a bucket directly:
they call `put` and `get` with an object key built by `object_key`, which pins every object under its
tenant's prefix. The adapter is wired by configuration in app.bootstrap."""

from typing import Protocol
from uuid import UUID


class Storage(Protocol):
    def put(self, key: str, data: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...


_storage: Storage | None = None


def configure(storage: Storage) -> None:
    global _storage
    _storage = storage


def object_key(tenant_id: UUID, file_id: UUID) -> str:
    """The stored name is the file id under the tenant prefix; the user's filename is metadata only (8.3)."""
    return f"t/{tenant_id}/files/{file_id}"


def check_key(key: str, tenant_id: UUID) -> None:
    """T8: a key outside the session tenant's prefix is refused before any adapter sees it."""
    if not key.startswith(f"t/{tenant_id}/") or ".." in key or "//" in key:
        raise ValueError("object key outside the tenant prefix")


def put(tenant_id: UUID, key: str, data: bytes) -> None:
    check_key(key, tenant_id)
    assert _storage is not None, "no storage adapter configured"
    _storage.put(key, data)


def get(tenant_id: UUID, key: str) -> bytes:
    check_key(key, tenant_id)
    assert _storage is not None, "no storage adapter configured"
    return _storage.get(key)
