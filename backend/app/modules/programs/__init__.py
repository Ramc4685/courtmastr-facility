"""programs context (L3): one enrolment engine for sessions and program groups (camps, clinics, leagues'
registrations), fees, waitlists, online registration and its checkout, and client self-booking of sessions.

Public interface: `service` (session targets, shared enrolment endpoints), `groups` (program groups),
`checkout` (registration baskets), `selfservice` (booking policy and portal booking).
"""

from app.modules.programs import checkout, groups, handlers, jobs, models, permissions, selfservice, service

__all__ = ["checkout", "groups", "handlers", "jobs", "models", "permissions", "selfservice", "service"]
from app.modules.platform import onboarding  # noqa: E402
from app.modules.programs import subject  # noqa: E402, F401  (registers the merge and data-subject handlers)

onboarding.register_step("offer", label="Create your first membership or program", path="/memberships", order=60,
                         done=onboarding.has_rows(models.ProgramGroup))  # fmt: skip
