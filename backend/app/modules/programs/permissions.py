"""programs entries of the permission catalogue: rbac-matrix.md section 6.9, row for row. The session-target
enrolment keys stay in scheduling (rbac-matrix 6.3)."""

from app.core.auth.permissions import Permission, Scope, register

L = Scope.LOCATION
_MG_LM = {"admin": "all", "manager": "all", "league_admin": "all"}
_FD_LM = {**_MG_LM, "front_desk": "all"}


def _p(key: str, label: str, flags: str, roles: dict[str, str], own: bool = False) -> Permission:
    return Permission(f"programs.{key}", L, label, tuple(flags.split()), roles, accepts_own_reach=own)


register(
    _p("program.manage", "Create and edit programs, subgroups, sessions and fees", "", _MG_LM),
    _p("program.delete", "Delete and restore programs", "D", {"admin": "all", "manager": "all"}),
    _p("registration_config.manage", "Configure and publish online registration", "", _MG_LM),
    _p("registration.read", "View program registrations and rosters", "", {**_FD_LM, "coach": "own"}, own=True),
    _p("registration.create", "Register clients into programs", "", _FD_LM),
    _p("registration.update", "Edit and move program registrations", "", _FD_LM),
    _p("registration.cancel", "Cancel program registrations", "", _FD_LM),
    _p("registration.export", "Export registrations", "X", _MG_LM),
    _p("waitlist.manage", "Manage program waitlists", "", _FD_LM),
    _p("form.manage", "Build registration forms", "", _MG_LM),
    _p("form_response.read", "View form answers", "H", {**_FD_LM, "coach": "own"}, own=True),
    _p("roster_link.send", "Send team roster links", "", _FD_LM),
)
