"""resources context (L1): bookable things and their tree, standing links, availability windows.

Public interface for routers, jobs and other contexts: `service`. Never import this package's models or
schemas from another context.
"""

from app.modules.platform import onboarding
from app.modules.resources import models, permissions, service

__all__ = ["models", "permissions", "service"]
onboarding.register_step("resources", label="Add your courts, rooms or trainers", path="/resources", order=30,
                         done=onboarding.has_rows(models.Resource))  # fmt: skip
