"""Local-disk storage adapter for development and tests. Objects are plain files under one root directory,
named by their tenant-prefixed key; the port has already checked the key."""

from collections.abc import Iterator
from pathlib import Path


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError("object key escapes the storage root")
        return path

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def keys(self, prefix: str) -> Iterator[str]:
        base = self._path(prefix)
        if base.is_dir():
            root = self.root.resolve()
            yield from (path.relative_to(root).as_posix() for path in base.rglob("*") if path.is_file())

    def url(self, key: str, *, expires_in: int, content_type: str, disposition: str) -> None:
        return None  # no origin of its own: files.download_url signs an API route instead
