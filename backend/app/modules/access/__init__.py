"""access context (L4): check-in from the front desk, the client profile and the kiosk, credentials and app
cards, kiosk devices and settings (build module 10).

Public interface: `service`. Never import this package's models or schemas from another context."""

from app.modules.access import models, permissions, service  # isort: skip

__all__ = ["models", "permissions", "service"]
from app.modules.access import subject  # noqa: E402, F401  (registers the merge and data-subject handlers)
