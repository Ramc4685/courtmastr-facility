"""documents context (L2): document and waiver templates, issued documents, signatures and evidence, bindings to
plans and programs, the waiver indicator (build module 7).

Public interface for routers, jobs and other contexts: `service`. Other contexts call
`service.requirements_for`, `service.ensure_pending`, `service.consume`, `service.status_for` and
`service.has_valid_waiver`. Never import this package's models or schemas from another context.
"""

from app.modules.documents import models, permissions  # isort: skip
from app.modules.documents import service

__all__ = ["models", "permissions", "service"]
