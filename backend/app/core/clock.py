"""Injected clock (overview 3.7). The only place allowed to read wall time; tests freeze it."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

_frozen: datetime | None = None


def now() -> datetime:
    return _frozen or datetime.now(UTC)


@contextmanager
def freeze(at: datetime) -> Iterator[None]:
    global _frozen
    previous, _frozen = _frozen, at
    try:
        yield
    finally:
        _frozen = previous
