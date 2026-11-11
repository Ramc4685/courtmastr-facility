"""memberships entries of the permission catalogue: rbac-matrix.md section 6.7, row for row."""

from app.core.auth.permissions import Permission, Scope, register

C, L, T = Scope.CLIENT, Scope.LOCATION, Scope.TENANT
_MG = {"admin": "all", "manager": "all"}
_FD = {**_MG, "front_desk": "all"}


def _p(key: str, scope: Scope, label: str, flags: str, roles: dict[str, str], own: bool = False) -> Permission:
    return Permission(f"memberships.{key}", scope, label, tuple(flags.split()), roles, accepts_own_reach=own)


register(
    _p("contract.read", C, "View memberships", "", {**_FD, "coach": "own"}, own=True),
    _p("contract.sell", L, "Sell memberships", "", {**_FD, "coach": "all"}),
    _p("contract.customize_terms", L, "Customise contract terms at sale", "P", _MG),
    _p("contract.update", L, "Edit sold memberships", "", _MG),
    _p("contract.edit_sold_by", L, "Change who sold a membership", "W", _MG),
    _p("contract.renew", L, "Renew memberships", "", _FD),
    _p("contract.freeze", L, "Freeze and unfreeze memberships", "", _MG),
    _p("contract.suspend", L, "Suspend and unsuspend memberships", "", _MG),
    _p("contract.cancel", L, "Cancel memberships", "D", _MG),
    _p("contract.share", L, "Share memberships with other clients", "", _MG),
    _p("contract.adjust_visits", L, "Adjust membership visit counts", "P", _MG),
    _p("billing_schedule.update", L, "Edit a membership's billing schedule", "P", _MG),
    _p("plan.manage", T, "Manage membership types, plans and settings", "", _MG),
)
