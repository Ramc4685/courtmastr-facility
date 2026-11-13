"""Recorded portal terms acknowledgment (SSP-14): the one hook every portal sale path (memberships, packages,
programs, rentals) calls once, before `secure_online_checkout`.

documents owns the record and registers it here at import: packages and rentals may not import documents
(pyproject import contracts), and clients sits below all four sale contexts.
"""

from collections.abc import Callable
from uuid import UUID

from sqlalchemy.orm import Session

_recorder: Callable[..., None] | None = None


def register(fn: Callable[..., None]) -> None:
    global _recorder
    _recorder = fn


def acknowledge(
    session: Session, *, client_id: UUID, terms_version_id: str | None, sale_kind: str, subject_id: UUID
) -> None:  # fmt: skip
    """Record that the buyer accepted the bound portal terms at this version, or 409 `terms-changed` when the
    version shown is stale or missing. No terms bound: nothing to record."""
    assert _recorder is not None, "documents registers the terms recorder at import"
    _recorder(session, client_id=client_id, terms_version_id=terms_version_id, sale_kind=sale_kind,
              subject_id=subject_id)  # fmt: skip
