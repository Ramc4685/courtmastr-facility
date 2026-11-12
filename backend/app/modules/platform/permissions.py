"""platform entries of the permission catalogue: rbac-matrix.md section 6.1, row for row.

A generated test parses that table and fails if this file drifts from it.
"""

from app.core.auth.permissions import Permission, Scope, register

T, L = Scope.TENANT, Scope.LOCATION
_AD = {"admin": "all"}
_AD_MG = {"admin": "all", "manager": "all"}


def _p(key: str, scope: Scope, label: str, flags: str = "", roles: dict[str, str] | None = None) -> Permission:
    return Permission(f"platform.{key}", scope, label, tuple(flags.split()), roles or {})


register(
    _p("tenant.update", T, "Edit the account profile and settings", "A", _AD),
    _p("tenant.manage_subscription", T, "Manage the subscription", "OO"),
    _p("tenant.transfer_ownership", T, "Transfer ownership", "OO +"),
    _p("tenant.close", T, "Close the account", "OO D +"),
    _p("tenant.export", T, "Export all of the account's data", "OO X +"),
    _p("location.create", T, "Add locations", "A", _AD),
    _p("location.update", L, "Edit location details and hours", "", _AD_MG),
    _p("location.archive", T, "Archive locations", "A D", _AD),
    _p("staff_user.read", T, "View staff users", "", _AD_MG),
    _p("staff_user.invite", T, "Invite staff users", "A", _AD),
    _p("staff_user.update", T, "Edit staff users", "A", _AD),
    _p("staff_user.deactivate", T, "Deactivate and reactivate staff users", "A", _AD),
    _p("staff_user.reset_credentials", T, "Send credential reset links", "A", _AD),
    _p("staff_user.assign_role", T, "Assign roles", "A +", _AD),
    _p("staff_user.assign_locations", T, "Assign locations to staff", "A", _AD),
    _p("staff_user.override_permissions", T, "Override permissions per user", "A +", _AD),
    _p("role.read", T, "View roles and permissions", "", _AD_MG),
    _p("role.manage", T, "Create and edit custom roles", "A +", _AD),
    _p("security.manage", T, "Manage security policy", "A +", _AD),
    _p("security.bypass_ip_allowlist", T, "Sign in from outside facility networks", "A", _AD),
    _p("audit.read", L, "View the activity trail", "", _AD_MG),
    _p("audit.export", T, "Export the activity trail", "X", _AD),
    _p("client_session.impersonate", T, "View the portal as a client", "I +", _AD),
    _p("support_access.grant", T, "Grant support access", "I OD +"),
    _p("data_subject_request.read", T, "View data-subject requests", "G", _AD),
    _p("data_subject_request.export", T, "Export a person's data", "G X", _AD),
    _p("data_subject_request.erase", T, "Erase a person's data", "G D OD +"),
    _p("import_job.read", T, "View imports", "", _AD_MG),
    _p("import_job.run", T, "Run imports", "D", _AD),
    _p("support_request.create", T, "Contact support", "", _AD_MG),
)  # fmt: skip
