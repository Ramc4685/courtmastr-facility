"""Malware scanner port (security-baseline 8.1). `scan` returns the signature name of a hit, or None for clean
bytes; an adapter that cannot reach its engine raises, so an unscanned file is never stored (fail closed).
The adapter is wired by configuration in app.bootstrap; production refuses the no-op one (core.settings)."""

from typing import Protocol


class Scanner(Protocol):
    def scan(self, data: bytes) -> str | None: ...


_scanner: Scanner | None = None


def configure(scanner: Scanner) -> None:
    global _scanner
    _scanner = scanner


def scan(data: bytes) -> str | None:
    assert _scanner is not None, "no scanner adapter configured"
    return _scanner.scan(data)
