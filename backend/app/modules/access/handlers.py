"""Events access consumes: a disabled client's wallet passes are revoked (CHK-13). Idempotent: revoking twice
finds nothing active the second time."""

from uuid import UUID

from app.core.events import handles
from app.modules.access import service


@handles("clients.client.disabled")
def on_client_disabled(session, payload: dict) -> None:
    service.revoke_wallet_passes_of(session, UUID(payload["client_id"]))
