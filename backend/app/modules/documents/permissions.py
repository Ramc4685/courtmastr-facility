"""documents entries of the permission catalogue: rbac-matrix.md section 6.6, row for row."""

from app.core.auth.permissions import Permission, Scope, register

C, L, T = Scope.CLIENT, Scope.LOCATION, Scope.TENANT
_AD_MG = {"admin": "all", "manager": "all"}
_DESK = {**_AD_MG, "front_desk": "all", "league_admin": "all"}


def _p(key: str, scope: Scope, label: str, flags: str, roles: dict[str, str], own: bool = False) -> Permission:
    return Permission(f"documents.{key}", scope, label, tuple(flags.split()), roles, accepts_own_reach=own)


register(
    _p("document.read", C, "View client documents and waiver status", "", {**_DESK, "coach": "own"}, own=True),
    _p("document.generate", C, "Issue documents to clients", "", _DESK),
    _p("document.collect_signature", C, "Collect signatures and send signing links", "", _DESK),
    _p("document.void", L, "Void, delete and restore documents", "D", _AD_MG),
    _p("document.bulk_request", L, "Bulk-send documents", "B", _AD_MG),
    _p("template.manage", T, "Manage document templates, bindings and settings", "", _AD_MG),
)
