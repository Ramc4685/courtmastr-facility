"""resources context (L1): bookable things and their tree, standing links, availability windows.

Public interface for routers, jobs and other contexts: `service`. Never import this package's models or
schemas from another context.
"""

from app.modules.resources import models, permissions, service

__all__ = ["models", "permissions", "service"]
