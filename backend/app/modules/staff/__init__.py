"""staff context (L3): trainer and salesperson pay records, session pay and commission rules, job
classifications and hourly rates, the time clock, shifts, instructor assignment and payroll runs (build module
12). Staff users, roles and RBAC stay in `platform`; trainer calendars are `resources` rows.

Public interface for routers, jobs and other contexts: `service`. Never import this package's models or
schemas from another context.
"""

from app.modules.staff import models, permissions  # isort: skip
from app.modules.staff import service

__all__ = ["models", "permissions", "service"]
