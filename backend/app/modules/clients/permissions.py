"""clients entries of the permission catalogue: rbac-matrix.md section 6.5, row for row.

The whole section is registered now, although the skeleton enforces only read and create, so that seeded and
custom roles already carry the right grants when build module 4 adds the operations.
"""

from app.core.auth.permissions import Permission, Scope, register

T = Scope.TENANT
_AD = {"admin": "all"}
_AD_MG = {"admin": "all", "manager": "all"}
_DESK = {**_AD_MG, "front_desk": "all"}
_DESK_LM = {**_DESK, "league_admin": "all"}
_OWN = {**_DESK_LM, "coach": "own"}  # coaches reach their own clients only
_ACTIVITY = {**_DESK, "coach": "own"}


def _p(key: str, label: str, flags: str = "", roles: dict[str, str] | None = None, own: bool = False) -> Permission:
    return Permission(f"clients.{key}", T, label, tuple(flags.split()), roles or {}, accepts_own_reach=own)


register(
    _p("client.read", "View clients", "", _OWN, own=True),
    _p("client.read_sensitive", "View birth date, address, medical notes and emergency contacts", "H", _OWN, own=True),
    _p("client.create", "Add clients", "", {**_DESK_LM, "coach": "all"}),
    _p("client.update", "Edit clients", "", _OWN, own=True),
    _p("client.disable", "Disable and enable clients", "", _AD_MG),
    _p("client.merge", "Merge duplicate clients", "D", _AD_MG),
    _p("client.export", "Export clients", "X", _AD),
    _p("client.assign_owner", "Assign default trainer and salesperson", "W", _AD_MG),
    # Owner decision 2026-11-13 ("Staff confirm once"): ID seen at the client's home location, nothing kept.
    Permission("clients.client.confirm_age", Scope.LOCATION, "Confirm a client's age", (), _DESK),
    _p("relationship.manage", "Manage relationships", "", _DESK_LM),
    _p("activity.read", "View notes and activity", "", _ACTIVITY, own=True),
    _p("activity.write", "Add notes and activity", "", _ACTIVITY, own=True),
    _p("activity.delete", "Delete notes", "", _AD_MG),
    _p("task.manage", "Manage client tasks", "", _ACTIVITY, own=True),
    _p("portal_access.manage", "Manage portal access", "", _DESK),
    _p("consent.update", "Update communication consent", "", _DESK),
    _p("config.manage", "Configure client fields, categories and tags", "", _AD),
)
