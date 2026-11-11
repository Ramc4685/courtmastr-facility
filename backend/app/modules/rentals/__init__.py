"""rentals context (L3): rental types and rates, rental bookings and their charges, online checkout and
prepaid rental plans (build module 3). Lockers (RNT-17, RNT-18) are not built.

Public interface: `service`.
"""

from app.modules.rentals import handlers, models, permissions, service

__all__ = ["handlers", "models", "permissions", "service"]
from app.modules.rentals import subject  # noqa: E402, F401  (registers the merge and data-subject handlers)
