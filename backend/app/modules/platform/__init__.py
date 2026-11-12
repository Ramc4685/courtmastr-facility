"""platform context (L0): tenants, locations, identity and sessions, staff users, RBAC, audit read.

Public interface for routers, jobs and other contexts: `service`, `auth`, `staff`, `entitlements`. Never import
this package's models or schemas from another context.
"""

from app.modules.platform import auth, entitlements, files, models, permissions, retention, service, staff

__all__ = ["auth", "entitlements", "files", "models", "permissions", "retention", "service", "staff"]
