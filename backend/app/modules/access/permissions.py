"""access entries of the permission catalogue: rbac-matrix.md section 6.12, row for row."""

from app.core.auth.permissions import Permission, Scope, register

C, L = Scope.CLIENT, Scope.LOCATION
_AD = {"admin": "all"}
_MG = {**_AD, "manager": "all"}
_FD = {**_MG, "front_desk": "all"}


def _p(key, scope, label, flags="", roles=None, own=False) -> Permission:
    return Permission(f"access.{key}", scope, label, tuple(flags.split()), roles or {}, accepts_own_reach=own)


register(
    _p("checkin.create", C, "Check clients in", "", {**_FD, "coach": "own"}, own=True),
    _p("checkin.read", L, "View check-ins and client check-in history", "", _FD),
    _p("checkin.read_full_details", L, "See full client details in the check-in window", "H", _MG),
    _p("checkin.override_denial", L, "Admit a client whose check-in was denied", "P", _MG),
    _p("checkin.delete", L, "Delete a check-in and restore its visit", "", _MG),
    _p("checkin.check_out", L, "Check clients out", "", _FD),
    _p("credential.assign", C, "Assign, generate and revoke member credentials", "", _FD),
    _p("kiosk.launch", L, "Launch self check-in on a registered device", "", _FD),
    _p("kiosk.manage", L, "Register and revoke kiosk devices", "K", _MG),
    _p("rule.manage", L, "Manage access rules and schedules", "", _MG),
    _p("client.set_access_mode", C, "Set a client to always admit or always deny", "P", _MG),
    _p("settings.manage", L, "Manage check-in and kiosk settings", "", _MG),
    _p("door.unlock", L, "Unlock a door", "P", _MG),
    _p("device.manage", L, "Manage access-control devices", "K", _AD),
)
