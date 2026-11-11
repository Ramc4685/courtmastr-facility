"""leagues HTTP surface (docs/api/openapi-programs.yaml, tag leagues). Routed: the P0 operations for sports, age
groups, seasons, competitions, divisions, teams, team entries, rosters, standings, schedule runs, games, results,
officials, brackets and the public schedule and standings. `billCompetitionTeam` is ours (the YAML has no
command for billing a team fee). Not routed (P1/P2, see README): scheduling preferences, stat tables and player
stats, game cards, league site and alert settings, public brackets and team pages, portal games."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.api import TxRoute, camel_id
from app.core.auth.deps import Ctx, public_session, require
from app.core.idempotency import idempotency
from app.core.pagination import ListQuery, list_query
from app.modules.leagues import schemas as s
from app.modules.leagues import service

staff = APIRouter(
    route_class=TxRoute, tags=["leagues"], generate_unique_id_function=camel_id, dependencies=[Depends(idempotency)]
)
public = APIRouter(route_class=TxRoute, tags=["leagues"], generate_unique_id_function=camel_id)  # anonymous
Lists = Annotated[ListQuery, Depends(list_query)]
Public = Annotated[Session, Depends(public_session)]
Manage = Depends(require(service.MANAGE))
Delete = Depends(require(service.DELETE))
Teams = Depends(require(service.TEAMS))
Roster = Depends(require(service.ROSTER))
Generate = Depends(require(service.GENERATE))
Games = Depends(require(service.GAMES))
GameReads = Depends(require(service.GAMES, service.RESULTS))  # a scorekeeper finds the games to score
Results = Depends(require(service.RESULTS))
Amend = Depends(require(service.AMEND))
Adjust = Depends(require(service.ADJUST))
Officials = Depends(require(service.OFFICIALS))


def _patch(body) -> dict:
    return body.model_dump(exclude_unset=True)


# --- sports, age groups, seasons --------------------------------------------------------------------------------


@staff.get("/sports", response_model=s.Page[s.SportOut])
def list_sports(query: Lists, ctx: Ctx = Manage):
    """Filters: is_active. Sort: name. q searches the name."""
    return service.list_sports(ctx.session, ctx.principal, query)


@staff.post("/sports", response_model=s.SportOut, status_code=201)
def create_sport(body: s.SportCreate, ctx: Ctx = Manage):
    return service.create_sport(ctx.session, ctx.principal, body.model_dump())


@staff.get("/sports/{sport_id}", response_model=s.SportOut)
def get_sport(sport_id: UUID, ctx: Ctx = Manage):
    return service.get_sport(ctx.session, ctx.principal, sport_id)


@staff.patch("/sports/{sport_id}", response_model=s.SportOut)
def update_sport(sport_id: UUID, body: s.SportUpdate, ctx: Ctx = Manage):
    return service.update_sport(ctx.session, ctx.principal, sport_id, _patch(body))


@staff.delete("/sports/{sport_id}", status_code=204)
def delete_sport(sport_id: UUID, ctx: Ctx = Manage):
    service.delete_sport(ctx.session, ctx.principal, sport_id)


@staff.get("/age-groups", response_model=s.Page[s.AgeGroupOut])
def list_age_groups(query: Lists, ctx: Ctx = Manage):
    """Filters: is_active. Sort: name, sort_order."""
    return service.list_age_groups(ctx.session, ctx.principal, query)


@staff.post("/age-groups", response_model=s.AgeGroupOut, status_code=201)
def create_age_group(body: s.AgeGroupWrite, ctx: Ctx = Manage):
    return service.create_age_group(ctx.session, ctx.principal, body.model_dump())


@staff.get("/age-groups/{age_group_id}", response_model=s.AgeGroupOut)
def get_age_group(age_group_id: UUID, ctx: Ctx = Manage):
    return service.get_age_group(ctx.session, ctx.principal, age_group_id)


@staff.patch("/age-groups/{age_group_id}", response_model=s.AgeGroupOut)
def update_age_group(age_group_id: UUID, body: s.AgeGroupWrite, ctx: Ctx = Manage):
    return service.update_age_group(ctx.session, ctx.principal, age_group_id, _patch(body))


@staff.delete("/age-groups/{age_group_id}", status_code=204)
def delete_age_group(age_group_id: UUID, ctx: Ctx = Manage):
    service.delete_age_group(ctx.session, ctx.principal, age_group_id)


@staff.get("/seasons", response_model=s.Page[s.SeasonOut])
def list_seasons(query: Lists, ctx: Ctx = Manage):
    """Filters: is_active. Sort: name."""
    return service.list_seasons(ctx.session, ctx.principal, query)


@staff.post("/seasons", response_model=s.SeasonOut, status_code=201)
def create_season(body: s.SeasonWrite, ctx: Ctx = Manage):
    return service.create_season(ctx.session, ctx.principal, body.model_dump())


@staff.get("/seasons/{season_id}", response_model=s.SeasonOut)
def get_season(season_id: UUID, ctx: Ctx = Manage):
    return service.get_season(ctx.session, ctx.principal, season_id)


@staff.patch("/seasons/{season_id}", response_model=s.SeasonOut)
def update_season(season_id: UUID, body: s.SeasonWrite, ctx: Ctx = Manage):
    return service.update_season(ctx.session, ctx.principal, season_id, _patch(body))


@staff.delete("/seasons/{season_id}", status_code=204)
def delete_season(season_id: UUID, ctx: Ctx = Manage):
    service.delete_season(ctx.session, ctx.principal, season_id)


# --- competitions and divisions ---------------------------------------------------------------------------------


@staff.get("/competitions", response_model=s.Page[s.CompetitionOut])
def list_competitions(query: Lists, ctx: Ctx = Manage):
    """Filters: location_id, kind, status, sport_id, season_id, age_group_id. Sort: name, starts_on, created_at."""
    return service.list_competitions(ctx.session, ctx.principal, query)


@staff.post("/competitions", response_model=s.CompetitionOut, status_code=201)
def create_competition(body: s.CompetitionCreate, ctx: Ctx = Manage):
    """Scoring, game length and team fee default from the sport. A 'Main' division is created."""
    return service.create_competition(ctx.session, ctx.principal, body.model_dump())


@staff.get("/competitions/{competition_id}", response_model=s.CompetitionOut)
def get_competition(competition_id: UUID, ctx: Ctx = Manage):
    return service.get_competition(ctx.session, ctx.principal, competition_id)


@staff.patch("/competitions/{competition_id}", response_model=s.CompetitionOut)
def update_competition(competition_id: UUID, body: s.CompetitionUpdate, ctx: Ctx = Manage):
    return service.update_competition(ctx.session, ctx.principal, competition_id, _patch(body))


@staff.delete("/competitions/{competition_id}", status_code=204)
def delete_competition(competition_id: UUID, ctx: Ctx = Delete):
    service.delete_competition(ctx.session, ctx.principal, competition_id)


@staff.post("/competitions/{competition_id}/activate", response_model=s.CompetitionOut)
def activate_competition(competition_id: UUID, ctx: Ctx = Manage):
    return service.transition_competition(ctx.session, ctx.principal, competition_id, "activate")


@staff.post("/competitions/{competition_id}/complete", response_model=s.CompetitionOut)
def complete_competition(competition_id: UUID, ctx: Ctx = Manage):
    return service.transition_competition(ctx.session, ctx.principal, competition_id, "complete")


@staff.post("/competitions/{competition_id}/archive", response_model=s.CompetitionOut)
def archive_competition(competition_id: UUID, ctx: Ctx = Manage):
    return service.transition_competition(ctx.session, ctx.principal, competition_id, "archive")


@staff.post("/competitions/{competition_id}/reopen", response_model=s.CompetitionOut)
def reopen_competition(competition_id: UUID, ctx: Ctx = Manage):
    return service.transition_competition(ctx.session, ctx.principal, competition_id, "reopen")


@staff.get("/competitions/{competition_id}/divisions", response_model=list[s.DivisionOut])
def list_divisions(competition_id: UUID, ctx: Ctx = Manage):
    return service.list_divisions(ctx.session, ctx.principal, competition_id)


@staff.post("/competitions/{competition_id}/divisions", response_model=s.DivisionOut, status_code=201)
def create_division(competition_id: UUID, body: s.DivisionWrite, ctx: Ctx = Manage):
    return service.create_division(ctx.session, ctx.principal, competition_id, body.model_dump())


@staff.patch("/divisions/{division_id}", response_model=s.DivisionOut)
def update_division(division_id: UUID, body: s.DivisionWrite, ctx: Ctx = Manage):
    return service.update_division(ctx.session, ctx.principal, division_id, _patch(body))


@staff.delete("/divisions/{division_id}", status_code=204)
def delete_division(division_id: UUID, ctx: Ctx = Manage):
    service.delete_division(ctx.session, ctx.principal, division_id)


# --- teams, entries, rosters ------------------------------------------------------------------------------------


@staff.get("/teams", response_model=s.Page[s.LeagueTeamOut])
def list_teams(query: Lists, ctx: Ctx = Teams):
    """Filters: location_id, is_active. Sort: name. q searches the name."""
    return service.list_teams(ctx.session, ctx.principal, query)


@staff.post("/teams", response_model=s.LeagueTeamOut, status_code=201)
def create_team(body: s.LeagueTeamCreate, ctx: Ctx = Teams):
    return service.create_team(ctx.session, ctx.principal, body.model_dump())


@staff.get("/teams/{team_id}", response_model=s.LeagueTeamOut)
def get_team(team_id: UUID, ctx: Ctx = Teams):
    return service.get_team(ctx.session, ctx.principal, team_id)


@staff.patch("/teams/{team_id}", response_model=s.LeagueTeamOut)
def update_team(team_id: UUID, body: s.LeagueTeamUpdate, ctx: Ctx = Teams):
    return service.update_team(ctx.session, ctx.principal, team_id, _patch(body))


@staff.delete("/teams/{team_id}", status_code=204)
def delete_team(team_id: UUID, ctx: Ctx = Teams):
    service.delete_team(ctx.session, ctx.principal, team_id)


@staff.get("/competitions/{competition_id}/teams", response_model=list[s.CompetitionTeamOut])
def list_competition_teams(competition_id: UUID, ctx: Ctx = Teams):
    return service.list_competition_teams(ctx.session, ctx.principal, competition_id)


@staff.post("/competitions/{competition_id}/teams", response_model=s.CompetitionTeamOut, status_code=201)
def add_competition_team(competition_id: UUID, body: s.CompetitionTeamCreate, ctx: Ctx = Teams):
    """An existing team (`team_id`) or a new one (`team`). With `bill_to_client_id` the team fee is charged
    and invoiced at once; otherwise the entry stays 'unbilled' until billCompetitionTeam."""
    return service.add_competition_team(ctx.session, ctx.principal, competition_id, body.model_dump())


@staff.post("/competitions/{competition_id}/teams/generate", response_model=list[s.CompetitionTeamOut], status_code=201)
def generate_competition_teams(competition_id: UUID, body: s.TeamGenerate, ctx: Ctx = Teams):
    return service.generate_competition_teams(ctx.session, ctx.principal, competition_id, body.model_dump())


@staff.post("/competitions/{competition_id}/teams/copy", response_model=list[s.CompetitionTeamOut], status_code=201)
def copy_competition_teams(competition_id: UUID, body: s.TeamCopy, ctx: Ctx = Teams):
    return service.copy_competition_teams(ctx.session, ctx.principal, competition_id, body.model_dump())


@staff.put("/competitions/{competition_id}/seeding", response_model=list[s.CompetitionTeamOut])
def put_competition_seeding(competition_id: UUID, body: s.Seeding, ctx: Ctx = Teams):
    return service.put_seeding(ctx.session, ctx.principal, competition_id, body.model_dump())


@staff.patch("/competition-teams/{competition_team_id}", response_model=s.CompetitionTeamOut)
def update_competition_team(competition_team_id: UUID, body: s.CompetitionTeamUpdate, ctx: Ctx = Teams):
    return service.update_competition_team(ctx.session, ctx.principal, competition_team_id, _patch(body))


@staff.delete("/competition-teams/{competition_team_id}", status_code=204)
def remove_competition_team(competition_team_id: UUID, ctx: Ctx = Teams):
    service.remove_competition_team(ctx.session, ctx.principal, competition_team_id)


@staff.post("/competition-teams/{competition_team_id}/bill", response_model=s.CompetitionTeamOut)
def bill_competition_team(competition_team_id: UUID, body: s.TeamFeeBill, ctx: Ctx = Teams):
    """Charge and invoice the team fee to a client (once per entry)."""
    return service.bill_competition_team(ctx.session, ctx.principal, competition_team_id, body.model_dump())


@staff.get("/competition-teams/{competition_team_id}/roster", response_model=list[s.LeagueRosterEntryOut])
def list_team_roster(competition_team_id: UUID, ctx: Ctx = Roster):
    return service.list_team_roster(ctx.session, ctx.principal, competition_team_id)


@staff.post("/competition-teams/{competition_team_id}/roster", response_model=s.LeagueRosterEntryOut, status_code=201)
def add_roster_entry(competition_team_id: UUID, body: s.RosterEntryCreate, ctx: Ctx = Roster):
    return service.add_roster_entry(ctx.session, ctx.principal, competition_team_id, body.model_dump())


@staff.get("/roster-entries", response_model=s.Page[s.LeagueRosterEntryOut])
def search_roster_entries(query: Lists, ctx: Ctx = Roster):
    """Filters: client_id, competition_team_id, competition_id, status. q searches names and jersey numbers."""
    return service.search_roster_entries(ctx.session, ctx.principal, query)


@staff.patch("/roster-entries/{roster_entry_id}", response_model=s.LeagueRosterEntryOut)
def update_roster_entry(roster_entry_id: UUID, body: s.RosterEntryUpdate, ctx: Ctx = Roster):
    return service.update_roster_entry(ctx.session, ctx.principal, roster_entry_id, _patch(body))


@staff.delete("/roster-entries/{roster_entry_id}", status_code=204)
def remove_roster_entry(roster_entry_id: UUID, ctx: Ctx = Roster):
    service.remove_roster_entry(ctx.session, ctx.principal, roster_entry_id)


# --- standings --------------------------------------------------------------------------------------------------


@staff.get("/competitions/{competition_id}/standings", response_model=list[s.LeagueStandingOut])
def list_standings(competition_id: UUID, ctx: Ctx = Manage, division_id: UUID | None = None):
    return service.list_standings(ctx.session, ctx.principal, competition_id, division_id)


@staff.post("/competitions/{competition_id}/standings/recompute", response_model=list[s.LeagueStandingOut])
def recompute_standings(competition_id: UUID, ctx: Ctx = Manage):
    return service.recompute_standings(ctx.session, ctx.principal, competition_id)


@staff.patch("/standings/{standing_id}", response_model=s.LeagueStandingOut)
def adjust_standing(standing_id: UUID, body: s.StandingAdjust, ctx: Ctx = Adjust):
    return service.adjust_standing(ctx.session, ctx.principal, standing_id, body.model_dump())


# --- schedule runs ----------------------------------------------------------------------------------------------


@staff.get("/schedule-runs", response_model=s.Page[s.ScheduleRunOut])
def list_schedule_runs(query: Lists, ctx: Ctx = Generate):
    """Filters: location_id, state. Sort: created_at."""
    return service.list_schedule_runs(ctx.session, ctx.principal, query)


@staff.post("/schedule-runs", response_model=s.ScheduleRunOut, status_code=201)
def create_schedule_run(body: s.ScheduleRunCreate, ctx: Ctx = Generate):
    return service.create_schedule_run(ctx.session, ctx.principal, body.model_dump())


@staff.get("/schedule-runs/{schedule_run_id}", response_model=s.ScheduleRunOut)
def get_schedule_run(schedule_run_id: UUID, ctx: Ctx = Generate):
    return service.get_schedule_run(ctx.session, ctx.principal, schedule_run_id)


@staff.patch("/schedule-runs/{schedule_run_id}", response_model=s.ScheduleRunOut)
def update_schedule_run(schedule_run_id: UUID, body: s.ScheduleRunUpdate, ctx: Ctx = Generate):
    return service.update_schedule_run(ctx.session, ctx.principal, schedule_run_id, _patch(body))


@staff.post("/schedule-runs/{schedule_run_id}/generate", response_model=s.ScheduleRunOut)
def generate_schedule(schedule_run_id: UUID, ctx: Ctx = Generate):
    """Writes a preview of proposed games (no bookings). Re-running replaces the preview."""
    return service.generate_schedule(ctx.session, ctx.principal, schedule_run_id)


@staff.get("/schedule-runs/{schedule_run_id}/games", response_model=s.Page[s.GameOut])
def list_schedule_run_games(schedule_run_id: UUID, query: Lists, ctx: Ctx = Generate):
    return service.list_schedule_run_games(ctx.session, ctx.principal, schedule_run_id, query)


@staff.post("/schedule-runs/{schedule_run_id}/commit", response_model=s.ScheduleRunOut)
def commit_schedule(schedule_run_id: UUID, ctx: Ctx = Generate):
    """Books every proposed game through scheduling; clashes leave games 'unschedulable' with the reason."""
    return service.commit_schedule(ctx.session, ctx.principal, schedule_run_id)


@staff.post("/schedule-runs/{schedule_run_id}/discard", response_model=s.ScheduleRunOut)
def discard_schedule_run(schedule_run_id: UUID, ctx: Ctx = Generate):
    return service.discard_schedule_run(ctx.session, ctx.principal, schedule_run_id)


# --- games, results, officials ----------------------------------------------------------------------------------


@staff.get("/games", response_model=s.Page[s.GameOut])
def list_games(query: Lists, ctx: Ctx = GameReads):
    """Filters: location_id, competition_id, division_id, status, resource_id, schedule_run_id, game_type."""
    return service.list_games(ctx.session, ctx.principal, query)


@staff.post("/games", response_model=s.GameOut, status_code=201)
def create_game(body: s.GameCreate, ctx: Ctx = Games):
    return service.create_game(ctx.session, ctx.principal, body.model_dump())


@staff.get("/games/{game_id}", response_model=s.GameOut)
def get_game(game_id: UUID, ctx: Ctx = GameReads):
    return service.get_game(ctx.session, ctx.principal, game_id)


@staff.patch("/games/{game_id}", response_model=s.GameOut)
def update_game(game_id: UUID, body: s.GameUpdate, ctx: Ctx = Games):
    return service.update_game(ctx.session, ctx.principal, game_id, _patch(body))


@staff.post("/games/{game_id}/reschedule", response_model=s.GameOut)
def reschedule_game(game_id: UUID, body: s.GameReschedule, ctx: Ctx = Games):
    return service.reschedule_game(ctx.session, ctx.principal, game_id, body.model_dump())


@staff.post("/games/{game_id}/postpone", response_model=s.GameOut)
def postpone_game(game_id: UUID, body: s.GamePostpone, ctx: Ctx = Games):
    return service.postpone_game(ctx.session, ctx.principal, game_id, body.model_dump())


@staff.post("/games/{game_id}/cancel", response_model=s.GameOut)
def cancel_game(game_id: UUID, ctx: Ctx = Games):
    return service.cancel_game(ctx.session, ctx.principal, game_id)


@staff.get("/games/{game_id}/result", response_model=s.GameResultOut)
def get_game_result(game_id: UUID, ctx: Ctx = Results):
    return service.get_game_result(ctx.session, ctx.principal, game_id)


@staff.put("/games/{game_id}/result", response_model=s.GameResultOut)
def put_game_result(game_id: UUID, body: s.GameResultPut, ctx: Ctx = Results):
    return service.put_game_result(ctx.session, ctx.principal, game_id, body.model_dump())


@staff.delete("/games/{game_id}/result", status_code=204)
def delete_game_result(game_id: UUID, ctx: Ctx = Amend):
    service.delete_game_result(ctx.session, ctx.principal, game_id)


@staff.get("/officials", response_model=s.Page[s.OfficialOut])
def list_officials(query: Lists, ctx: Ctx = Officials):
    """Filters: location_id, is_active. Sort: last_name."""
    return service.list_officials(ctx.session, ctx.principal, query)


@staff.post("/officials", response_model=s.OfficialOut, status_code=201)
def create_official(body: s.OfficialCreate, ctx: Ctx = Officials):
    return service.create_official(ctx.session, ctx.principal, body.model_dump())


@staff.get("/officials/{official_id}", response_model=s.OfficialOut)
def get_official(official_id: UUID, ctx: Ctx = Officials):
    return service.get_official(ctx.session, ctx.principal, official_id)


@staff.patch("/officials/{official_id}", response_model=s.OfficialOut)
def update_official(official_id: UUID, body: s.OfficialUpdate, ctx: Ctx = Officials):
    return service.update_official(ctx.session, ctx.principal, official_id, _patch(body))


@staff.delete("/officials/{official_id}", status_code=204)
def delete_official(official_id: UUID, ctx: Ctx = Officials):
    service.delete_official(ctx.session, ctx.principal, official_id)


@staff.get("/games/{game_id}/officials", response_model=list[s.GameOfficialOut])
def list_game_officials(game_id: UUID, ctx: Ctx = Officials):
    return service.list_game_officials(ctx.session, ctx.principal, game_id)


@staff.put("/games/{game_id}/officials", response_model=list[s.GameOfficialOut])
def put_game_officials(game_id: UUID, body: s.GameOfficialsPut, ctx: Ctx = Officials):
    """Replaces the game's officials. 409 official-conflict when one is already on an overlapping game."""
    return service.put_game_officials(ctx.session, ctx.principal, game_id, body.model_dump())


# --- brackets ---------------------------------------------------------------------------------------------------


@staff.get("/competitions/{competition_id}/brackets", response_model=list[s.BracketOut])
def list_brackets(competition_id: UUID, ctx: Ctx = Manage):
    return service.list_brackets(ctx.session, ctx.principal, competition_id)


@staff.post("/competitions/{competition_id}/brackets", response_model=s.BracketOut, status_code=201)
def generate_bracket(competition_id: UUID, body: s.BracketGenerate, ctx: Ctx = Generate):
    """Single elimination only; other types answer 422 not-supported."""
    return service.generate_bracket(ctx.session, ctx.principal, competition_id, body.model_dump())


@staff.get("/brackets/{bracket_id}", response_model=s.BracketOut)
def get_bracket(bracket_id: UUID, ctx: Ctx = Manage):
    return service.get_bracket(ctx.session, ctx.principal, bracket_id)


@staff.delete("/brackets/{bracket_id}", status_code=204)
def delete_bracket(bracket_id: UUID, ctx: Ctx = Generate):
    service.delete_bracket(ctx.session, ctx.principal, bracket_id)


@staff.patch("/bracket-slots/{bracket_slot_id}", response_model=s.BracketSlotOut)
def update_bracket_slot(bracket_slot_id: UUID, body: s.BracketSlotUpdate, ctx: Ctx = Generate):
    return service.update_bracket_slot(ctx.session, ctx.principal, bracket_slot_id, _patch(body))


@staff.post("/brackets/{bracket_id}/publish", response_model=s.BracketOut)
def publish_bracket(bracket_id: UUID, ctx: Ctx = Generate):
    return service.publish_bracket(ctx.session, ctx.principal, bracket_id)


# --- public schedule and standings ------------------------------------------------------------------------------


@public.get("/public/competitions", response_model=list[s.PublicCompetitionOut])
def list_public_competitions(session: Public, location_id: UUID | None = None):
    return service.list_public_competitions(session, location_id)


@public.get("/public/competitions/{competition_id}", response_model=s.PublicCompetitionOut)
def get_public_competition(competition_id: UUID, session: Public):
    return service.get_public_competition(session, competition_id)


@public.get("/public/competitions/{competition_id}/games", response_model=list[s.PublicGameOut])
def list_public_games(competition_id: UUID, session: Public):
    return service.list_public_games(session, competition_id)


@public.get("/public/competitions/{competition_id}/standings", response_model=list[s.PublicStandingOut])
def list_public_standings(competition_id: UUID, session: Public):
    return service.list_public_standings(session, competition_id)


router = APIRouter()
router.include_router(staff)
router.include_router(public)
