"""platform context (L0): tenants, locations, identity and sessions, staff users, RBAC, audit read.

Public interface for routers, jobs and other contexts: `service`, `auth`, `staff`, `entitlements`;
`onboarding.register_step` for the setup checklist. Never import this package's models or schemas from another
context.
"""

from app.modules.platform import (
    auth,
    branding,
    entitlements,
    files,
    models,
    onboarding,
    permissions,
    retention,
    service,
    staff,
    tenant_export,
)

__all__ = ["auth", "branding", "entitlements", "files", "models", "onboarding", "permissions", "retention",
           "service", "staff", "tenant_export"]  # fmt: skip
