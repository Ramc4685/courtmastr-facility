"""billing context (L2): receivables and money. Kernel slice (overview section 6 items 3 and 5, ADR 0003);
build module 8 completes it.

Public interface for routers, jobs and other contexts: `service`. Never import this package's models or
schemas from another context.
"""

from app.modules.billing import models, permissions, service

__all__ = ["models", "permissions", "service"]
