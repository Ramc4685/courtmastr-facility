"""programs context (L3): one enrolment engine for sessions and program groups (camps, clinics, leagues'
registrations), fees, waitlists, online registration and its checkout, and client self-booking of sessions.

Public interface: `service` (session targets, shared enrolment endpoints), `groups` (program groups),
`checkout` (registration baskets), `selfservice` (booking policy and portal booking), `forms` (event forms),
`tools` (classifiers, saved views, defaults, copy, series, export).
"""

from app.modules.programs import (
    checkout,
    forms,
    groups,
    handlers,
    jobs,
    models,
    permissions,
    selfservice,
    service,
    tools,
)

__all__ = [
    "checkout",
    "forms",
    "groups",
    "handlers",
    "jobs",
    "models",
    "permissions",
    "selfservice",
    "service",
    "tools",
]
from app.modules.platform import onboarding  # noqa: E402
from app.modules.programs import subject  # noqa: E402, F401  (registers the merge and data-subject handlers)

onboarding.register_step("offer", label="Create your first membership or program", path="/memberships", order=60,
                         done=onboarding.has_rows(models.ProgramGroup))  # fmt: skip
