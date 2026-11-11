"""assessments entries of the permission catalogue: rbac-matrix.md section 6.16, row for row."""

from app.core.auth.permissions import Permission, Scope, register

C, L, T = Scope.CLIENT, Scope.LOCATION, Scope.TENANT
_AD_MG = {"admin": "all", "manager": "all"}
_COACH = {**_AD_MG, "coach": "own"}


def _p(key: str, scope: Scope, label: str, flags: str, roles: dict[str, str], own: bool = False) -> Permission:
    return Permission(f"assessments.{key}", scope, label, tuple(flags.split()), roles, accepts_own_reach=own)


register(
    _p("assessment.read", C, "View client assessments", "H", _COACH, own=True),
    _p("assessment.record", C, "Record client assessments", "H", _COACH, own=True),
    _p("assessment.share", C, "Share assessment results with clients", "", _COACH, own=True),
    _p("assessment.delete", L, "Delete assessment entries", "D", _AD_MG),
    _p("definition.manage", T, "Manage assessment categories, fields and settings", "", _AD_MG),
)
