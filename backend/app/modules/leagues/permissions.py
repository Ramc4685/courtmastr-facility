"""leagues entries of the permission catalogue: rbac-matrix.md section 6.13, row for row. Per-competition subject
grants (`subj:competition`) are not built: the keys apply to every competition at the granted locations."""

from app.core.auth.permissions import Permission, Scope, register

_LM = {"admin": "all", "league_admin": "all"}
_MG = {**_LM, "manager": "all"}


def _p(key, label, flags="", roles=None) -> Permission:
    return Permission(f"leagues.{key}", Scope.LOCATION, label, tuple(flags.split()), roles or {}, False, None)


register(
    _p("competition.manage", "Manage leagues, tournaments, sports and standings settings", "", _MG),
    _p("competition.delete", "Delete leagues and tournaments", "D", _LM),
    _p("team.manage", "Manage teams and team entries", "", _MG),
    _p("roster.manage", "Manage team rosters", "", {**_MG, "front_desk": "all"}),
    _p("schedule.generate", "Generate and commit league schedules and brackets", "D", _MG),
    _p("game.manage", "Add, move, postpone and cancel games", "", _MG),
    _p("result.enter", "Enter game results", "", {**_MG, "scorekeeper": "all"}),
    _p("result.amend_final", "Remove recorded results", "", _LM),
    _p("standings.adjust", "Adjust standings points", "", _LM),
    _p("discipline.manage", "Manage discipline caps and suspensions", "", _LM),
    _p("official.manage", "Manage officials and game assignments", "", _MG),
    _p("game_card.print", "Print game cards", "", {**_MG, "scorekeeper": "all"}),
    _p("alert.send", "Send league alerts", "B", _MG),
    _p("public_site.manage", "Manage the public league site", "", _MG),
    _p("classified.moderate", "Moderate classifieds and pickup listings", "", _MG),
    _p("sponsor.manage", "Manage sponsor advertising", "", _LM),
)
