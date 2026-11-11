"""staff entries of the permission catalogue: rbac-matrix.md section 6.14, row for row."""

from app.core.auth.permissions import Permission, Scope, register

T, L = Scope.TENANT, Scope.LOCATION
_AD = {"admin": "all"}
_MG = {"admin": "all", "manager": "all"}


def _p(key: str, scope: Scope, label: str, flags: str = "", roles: dict[str, str] | None = None, own=False) -> Permission:
    return Permission(f"staff.{key}", scope, label, tuple(flags.split()), roles or {}, own)


register(
    _p("time_entry.punch", L, "Clock in and out", "",
       {**_MG, "front_desk": "all", "coach": "all", "league_admin": "all"}),
    _p("time_entry.read", L, "View time entries", "W",
       {**_MG, "front_desk": "own", "coach": "own", "league_admin": "own"}, own=True),
    _p("time_entry.manage", L, "Add, edit and void time entries", "W", _MG),
    _p("shift.manage", L, "Plan and publish shifts", "", _MG),
    _p("pay_rate.read", T, "View pay rates and commission rules", "W", _AD),
    _p("pay_rate.manage", T, "Edit pay rates and commission rules", "W", _AD),
    _p("pay_statement.read", L, "View pay statements", "W", {**_AD, "front_desk": "own", "coach": "own"}, own=True),
    _p("payroll_run.create", L, "Run payroll and commission reports", "W", _AD),
    _p("payroll_run.approve", L, "Finalize and void payroll runs", "W +", _AD),
    _p("payroll_run.export", L, "Export payroll runs", "W X", _AD),
)  # fmt: skip
