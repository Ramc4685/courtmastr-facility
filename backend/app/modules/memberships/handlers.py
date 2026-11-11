"""Events memberships consumes (overview section 2). Handlers re-read current state and are idempotent."""

from uuid import UUID

from app.core.events import handles
from app.modules.memberships import service


@handles("documents.document.accepted")
def on_document_accepted(session, payload: dict) -> None:
    service.document_accepted(session, UUID(payload["client_document_id"]))
