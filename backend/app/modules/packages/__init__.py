"""packages context (L3): package plans, sold packages, the session-credit ledger, expiry, renewal and sharing
(build module 5).

Public interface for routers, jobs and other contexts: `service`. Booking contexts call `service.reserve_credit`,
`service.release_credit`, `service.consume_credit`, `service.restore_credit` and `service.spendable_packages`;
`pos` calls `service.sell`. Never import this package's models or schemas from another context.
"""

from app.modules.packages import models, permissions  # isort: skip
from app.modules.packages import (
    handlers,
    postbilled,  # after service, which it builds on
    service,
)

__all__ = ["handlers", "models", "permissions", "postbilled", "service"]
