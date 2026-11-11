"""reporting entries of the permission catalogue: rbac-matrix.md section 6.17, row for row. Report families are
keys (the registry tags each report with one); a saved report or a run grants nothing beyond them."""

from app.core.auth.permissions import Permission, Scope, register

L = Scope.LOCATION
_AD_MG = {"admin": "all", "manager": "all"}


def _p(key: str, label: str, flags: str, roles: dict[str, str], own: bool = False) -> Permission:
    return Permission(f"reporting.{key}", L, label, tuple(flags.split()), roles, accepts_own_reach=own)


register(
    _p("dashboard.read", "View the management dashboard", "", _AD_MG),
    _p("financial.run", "Run financial reports", "", _AD_MG),
    _p("membership.run", "Run membership reports", "", _AD_MG),
    _p("client.run", "Run client reports", "H", _AD_MG),
    _p(
        "attendance.run",
        "Run attendance and check-in reports",
        "",
        {**_AD_MG, "front_desk": "all", "coach": "own"},
        own=True,
    ),  # fmt: skip
    _p("program.run", "Run program reports", "H", {**_AD_MG, "league_admin": "all"}),
    _p("pos.run", "Run point of sale reports", "", _AD_MG),
    _p("time_clock.run", "Run time clock reports", "W", _AD_MG),
    _p(
        "payroll.run",
        "Run payroll and commission reports",
        "W",
        {"admin": "all", "front_desk": "own", "coach": "own"},
        own=True,
    ),  # fmt: skip
    _p("league.run", "Run league reports", "", {**_AD_MG, "league_admin": "all"}),
    _p("marketing.run", "Run marketing reports", "", _AD_MG),
    _p("report.export", "Export reports to files", "X", {**_AD_MG, "league_admin": "all"}),
)
