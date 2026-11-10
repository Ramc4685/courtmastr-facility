"""scheduling entries of the permission catalogue: rbac-matrix.md section 6.3, row for row.

`accepts_own_reach` mirrors the Qual column exactly as the conformance test reads it ("own" alone); rows whose
Qual is "own, subj:reservation_type" still carry the coach's `own` grant, which the service enforces.
"""

from app.core.auth.permissions import Permission, Scope, register

L = Scope.LOCATION
_MG = {"admin": "all", "manager": "all"}
_FD = {**_MG, "front_desk": "all"}
_CT = {**_FD, "coach": "own"}
_READ = {**_FD, "coach": "all", "league_admin": "all", "view_only": "all"}
_TYPE = "reservation_type"


def _p(key, label, flags="", roles=None, own=False, subject=None, scope=L) -> Permission:
    return Permission(f"scheduling.{key}", scope, label, tuple(flags.split()), roles or {}, own, subject)


register(
    _p("booking.read", "View the schedule", "", _READ, subject=_TYPE),
    _p("booking.create", "Create sessions and reservations", "", _CT, subject=_TYPE),
    _p("booking.update", "Edit and move reservations", "", _CT, subject=_TYPE),
    _p("booking.update_series", "Mass-edit linked reservations", "D", _FD, subject=_TYPE),
    _p("booking.delete", "Cancel reservations", "", _FD, subject=_TYPE),
    _p("booking.delete_series", "Cancel linked reservations in bulk", "D", _MG, subject=_TYPE),
    _p("booking.override_policy", "Book outside hours, closures and booking windows", "P", _MG),
    _p("block.manage", "Manage time blocks", "", _CT, own=True),
    _p("session.manage", "Manage bookable sessions", "", _CT, subject=_TYPE),
    _p("session.change_capacity", "Change class sizes", "", _MG, subject=_TYPE),
    _p("enrollment.create", "Register clients into sessions", "", _CT, subject=_TYPE),
    _p("enrollment.cancel", "Remove clients from sessions", "", _CT, subject=_TYPE),
    _p("enrollment.free_book", "Register without a package", "P", _MG, subject=_TYPE),
    _p("enrollment.override_capacity", "Register into a full session", "P", _MG),
    _p("attendance.mark", "Mark attendance", "", _CT, own=True),
    _p("attendance.mark_exception", "Mark early cancel, late cancel and no-show", "P", _MG, own=True),
    _p("waitlist.manage", "Manage session waitlists", "", _CT, own=True),
    _p("registration_link.create", "Create direct registration links", "", _FD),
    _p("reservation_type.manage", "Manage reservation types and categories", "", _MG, scope=Scope.TENANT),
    _p("public_schedule.manage", "Manage the public schedule", "", _MG),
)
