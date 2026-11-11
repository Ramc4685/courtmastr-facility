"""memberships context (L3): membership types and plans, contracts and their lifecycle, the billing schedule,
freezes, suspensions, renewals, cancellations, sharing and visit counting (build module 5, ADR 0005).

Public interface for routers, jobs and other contexts: `service`. Other contexts call `service.eligibility`,
`service.is_member` and `service.record_visit`. Never import this package's models or schemas from another
context.
"""

from app.modules.memberships import models, permissions  # isort: skip
from app.modules.memberships import handlers, service

__all__ = ["handlers", "models", "permissions", "service"]
