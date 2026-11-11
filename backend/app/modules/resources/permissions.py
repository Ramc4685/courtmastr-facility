"""resources entries of the permission catalogue: rbac-matrix.md section 6.2, row for row."""

from app.core.auth.permissions import Permission, Scope, register

_MG = {"admin": "all", "manager": "all"}


def _p(key: str, label: str, flags: str = "", roles: dict[str, str] | None = None, own: bool = False) -> Permission:
    return Permission(f"resources.{key}", Scope.LOCATION, label, tuple(flags.split()), roles or {}, own)


register(
    _p("resource.manage", "Manage venues, trainers-as-resources and schedule groups", "", _MG),
    _p("availability.manage", "Manage availability windows", "", {**_MG, "coach": "own"}, own=True),
    _p("locker.manage", "Manage locker rooms, lockers and terms", "", _MG),
    _p("padlock.manage", "Manage padlock inventory", "", _MG),
    _p("padlock.reveal_combination", "Reveal padlock combinations", "K", {**_MG, "front_desk": "all"}),
)
