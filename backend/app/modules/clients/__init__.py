"""clients context (L1): people. Kernel skeleton (overview section 6 item 2); build module 4 completes it.

Public interface for routers, jobs and other contexts: `service`. Never import this package's models or
schemas from another context.
"""

from app.modules.clients import models, permissions, service

__all__ = ["models", "permissions", "service"]
