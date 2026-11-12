"""packages entries of the permission catalogue: rbac-matrix.md section 6.8, row for row."""

from app.core.auth.permissions import Permission, Scope, register

C, L, T = Scope.CLIENT, Scope.LOCATION, Scope.TENANT
_MG = {"admin": "all", "manager": "all"}
_FD = {**_MG, "front_desk": "all"}


def _p(key: str, scope: Scope, label: str, flags: str, roles: dict[str, str], own: bool = False) -> Permission:
    return Permission(f"packages.{key}", scope, label, tuple(flags.split()), roles, accepts_own_reach=own)


register(
    _p("package.read", C, "View packages and session balances", "", {**_FD, "coach": "own"}, own=True),
    _p("package.sell", L, "Sell packages", "", {**_FD, "coach": "all"}),
    _p("package.grant_complimentary", L, "Grant complimentary packages", "P", _MG),
    _p("package.update", L, "Edit sold packages", "P", _MG),
    _p("package.share", L, "Share packages with other clients", "", _MG),
    _p("package.remove", L, "Remove sold packages", "D", _MG),
    _p("package.remove_override", L, "Reverse the billing of a package after sessions were used", "D P", _MG),
    _p("credit.adjust", L, "Adjust session credits", "$", _MG),
    _p("period.close", L, "Close post-billed package periods", "", _MG),
    _p("plan.manage", T, "Manage package plans and settings", "", _MG),
)
