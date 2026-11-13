"""scheduling context (L2): the calendar engine. Bookings, resource holds, sessions, series, blackouts.

Public interface for routers, jobs and other contexts: `service`. Only this context writes `resource_hold`.
"""

from app.modules.scheduling import jobs, models, permissions, service

__all__ = ["jobs", "models", "permissions", "service"]
from app.modules import platform as _platform  # noqa: E402
from app.modules.scheduling import subject  # noqa: E402, F401  (registers the merge and data-subject handlers)

_platform.service.register_location_archive_check(service.check_location_archive)
