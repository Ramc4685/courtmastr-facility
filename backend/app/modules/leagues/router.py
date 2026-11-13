"""leagues HTTP surface (docs/api/openapi-programs.yaml, tag leagues). Routed: the P0 operations for sports, age
groups, seasons, competitions, divisions, teams, team entries, rosters, standings, schedule runs, games, results,
officials, brackets and the public schedule and standings. `billCompetitionTeam` is ours (the YAML has no
command for billing a team fee). Phase 14 chip B1 (ours, `depth`): venues, team preferences, league staff,
ladders, stat tables and player stats, the team fee split, publishing a program group, game-card PDFs and the
captain's portal roster. Phase 14 chip B2 (ours, `site`): the public league site (options, links, gallery, sponsors,
news, classes, teams, brackets, player stats, the TV board) and moderated classifieds and pickup games. Every
anonymous route shares the `public-site` rate limit. Not routed (see README): league alert settings, portal games."""

from datetime import date
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.core.api import TxRoute, camel_id
from app.core.auth.deps import Ctx, current_ctx, public_session, require
from app.core.idempotency import idempotency
from app.core.pagination import ListQuery, list_query
from app.core.ratelimit import hit, rate_limit
from app.modules.leagues import depth, service, site
from app.modules.leagues import schemas as s

staff = APIRouter(
    route_class=TxRoute, tags=["leagues"], generate_unique_id_function=camel_id, dependencies=[Depends(idempotency)]
)
public = APIRouter(  # anonymous: published data only, one per-IP bucket for the whole public site
    route_class=TxRoute,
    tags=["leagues"],
    generate_unique_id_function=camel_id,
    dependencies=[Depends(rate_limit("public-site"))],
)
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
Cards = Depends(require(service.CARDS))
Portal = Annotated[Ctx, Depends(current_ctx)]
PDF: dict[int | str, dict[str, Any]] = {200: {"content": {"application/pdf": {}}, "description": "The PDF."}}


def _pdf(named: tuple[str, bytes]) -> Response:
    name, data = named
    return Response(
        data, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{name}"', "X-Content-Type-Options": "nosniff",
                 "Cache-Control": "private, no-store"},
    )  # fmt: skip


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
def list_public_competitions(
    session: Public,
    location_id: UUID | None = None,
    sport_id: UUID | None = None,
    season_id: UUID | None = None,
    kind: Literal["league", "tournament"] | None = None,
    status: Literal["active", "completed"] | None = None,
    q: Annotated[str, Query(max_length=100)] | None = None,
):
    """LGE-17: the filters also make the shareable URL and the embed (`/leagues/public?sport_id=...&embed=1`)."""
    filters = {"sport_id": sport_id, "season_id": season_id, "kind": kind, "status": status, "q": q}
    return service.list_public_competitions(session, location_id, filters)


@public.get("/public/competitions/{competition_id}", response_model=s.PublicCompetitionOut)
def get_public_competition(competition_id: UUID, session: Public):
    return service.get_public_competition(session, competition_id)


@public.get("/public/competitions/{competition_id}/games", response_model=list[s.PublicGameOut])
def list_public_games(competition_id: UUID, session: Public):
    return service.list_public_games(session, competition_id)


@public.get("/public/competitions/{competition_id}/standings", response_model=list[s.PublicStandingOut])
def list_public_standings(competition_id: UUID, session: Public):
    return service.list_public_standings(session, competition_id)


# --- Phase 14 chip B1: venues (RES-06) --------------------------------------------------------------------------


@staff.get("/league-venues", response_model=s.Page[s.VenueOut])
def list_venues(query: Lists, ctx: Ctx = Manage):
    """Filters: location_id, is_active. Sort: name. q searches the name."""
    return depth.list_venues(ctx.session, ctx.principal, query)


@staff.post("/league-venues", response_model=s.VenueOut, status_code=201)
def create_venue(body: s.VenueCreate, ctx: Ctx = Manage):
    return depth.create_venue(ctx.session, ctx.principal, body.model_dump())


@staff.get("/league-venues/{venue_id}", response_model=s.VenueOut)
def get_venue(venue_id: UUID, ctx: Ctx = Manage):
    return depth.get_venue(ctx.session, ctx.principal, venue_id)


@staff.patch("/league-venues/{venue_id}", response_model=s.VenueOut)
def update_venue(venue_id: UUID, body: s.VenueUpdate, ctx: Ctx = Manage):
    return depth.update_venue(ctx.session, ctx.principal, venue_id, _patch(body))


@staff.delete("/league-venues/{venue_id}", status_code=204)
def delete_venue(venue_id: UUID, ctx: Ctx = Manage):
    depth.delete_venue(ctx.session, ctx.principal, venue_id)


# --- team preferences (LGE-10), league staff (LGE-26), ladder (LGE-28) ------------------------------------------


@staff.get("/competition-teams/{competition_team_id}/preferences", response_model=list[s.TeamPreferenceOut])
def list_team_preferences(competition_team_id: UUID, ctx: Ctx = Generate):
    return depth.list_team_preferences(ctx.session, ctx.principal, competition_team_id)


@staff.put("/competition-teams/{competition_team_id}/preferences", response_model=list[s.TeamPreferenceOut])
def replace_team_preferences(competition_team_id: UUID, body: s.TeamPreferencesPut, ctx: Ctx = Generate):
    """Soft inputs to the schedule generator: wanted dates, weekdays, times and courts score up, unavailable
    ones score far down. Never a hard block."""
    return depth.replace_team_preferences(ctx.session, ctx.principal, competition_team_id, body.model_dump())


@staff.get("/competitions/{competition_id}/staff", response_model=list[s.CompetitionStaffOut])
def list_competition_staff(competition_id: UUID, ctx: Ctx = Manage):
    return depth.list_competition_staff(ctx.session, ctx.principal, competition_id)


@staff.get("/competitions/{competition_id}/staff-candidates", response_model=list[s.StaffCandidateOut])
def list_staff_candidates(competition_id: UUID, ctx: Ctx = Manage):
    """Staff who may be assigned to the competition: active and working at its location."""
    return depth.list_staff_candidates(ctx.session, ctx.principal, competition_id)


@staff.put("/competitions/{competition_id}/staff", response_model=list[s.CompetitionStaffOut])
def replace_competition_staff(competition_id: UUID, body: s.CompetitionStaffPut, ctx: Ctx = Manage):
    """League admins and scorekeepers of the competition. A scorekeeper-only role then reaches only the games
    of the competitions it is assigned to."""
    return depth.replace_competition_staff(ctx.session, ctx.principal, competition_id, body.model_dump())


@staff.get("/competitions/{competition_id}/ladder", response_model=list[s.LadderRungOut])
def get_ladder(competition_id: UUID, ctx: Ctx = GameReads):
    return depth.get_ladder(ctx.session, ctx.principal, competition_id)


@staff.put("/competitions/{competition_id}/ladder", response_model=list[s.LadderRungOut])
def replace_ladder(competition_id: UUID, body: s.LadderPut, ctx: Ctx = Manage):
    return depth.replace_ladder(ctx.session, ctx.principal, competition_id, body.model_dump())


@staff.post("/competitions/{competition_id}/ladder-challenges", response_model=s.GameOut, status_code=201)
def create_ladder_challenge(competition_id: UUID, body: s.LadderChallengeCreate, ctx: Ctx = Games):
    """A challenge game, challenger at home. A challenger win swaps the two rungs when its result is recorded;
    a corrected or removed result swaps them back."""
    return depth.create_ladder_challenge(ctx.session, ctx.principal, competition_id, body.model_dump())


# --- stat tables and player stats (LGE-07) ----------------------------------------------------------------------


@staff.get("/sports/{sport_id}/stat-tables", response_model=list[s.StatTableOut])
def list_stat_tables(sport_id: UUID, ctx: Ctx = Manage):
    return depth.list_stat_tables(ctx.session, ctx.principal, sport_id)


@staff.post("/sports/{sport_id}/stat-tables", response_model=s.StatTableOut, status_code=201)
def create_stat_table(sport_id: UUID, body: s.StatTableWrite, ctx: Ctx = Manage):
    return depth.create_stat_table(ctx.session, ctx.principal, sport_id, body.model_dump())


@staff.patch("/stat-tables/{stat_table_id}", response_model=s.StatTableOut)
def update_stat_table(stat_table_id: UUID, body: s.StatTableUpdate, ctx: Ctx = Manage):
    return depth.update_stat_table(ctx.session, ctx.principal, stat_table_id, _patch(body))


@staff.delete("/stat-tables/{stat_table_id}", status_code=204)
def delete_stat_table(stat_table_id: UUID, ctx: Ctx = Manage):
    depth.delete_stat_table(ctx.session, ctx.principal, stat_table_id)


@staff.post("/stat-tables/{stat_table_id}/stats", response_model=s.StatDefinitionOut, status_code=201)
def create_stat_definition(stat_table_id: UUID, body: s.StatDefinitionCreate, ctx: Ctx = Manage):
    """An entry stat, or a formula over the sport's entry stat codes (+ - * / and brackets), checked on save."""
    return depth.create_stat_definition(ctx.session, ctx.principal, stat_table_id, body.model_dump())


@staff.patch("/stat-definitions/{stat_definition_id}", response_model=s.StatDefinitionOut)
def update_stat_definition(stat_definition_id: UUID, body: s.StatDefinitionUpdate, ctx: Ctx = Manage):
    return depth.update_stat_definition(ctx.session, ctx.principal, stat_definition_id, _patch(body))


@staff.delete("/stat-definitions/{stat_definition_id}", status_code=204)
def delete_stat_definition(stat_definition_id: UUID, ctx: Ctx = Manage):
    depth.delete_stat_definition(ctx.session, ctx.principal, stat_definition_id)


@staff.get("/games/{game_id}/player-stats", response_model=list[s.PlayerStatOut])
def list_game_player_stats(game_id: UUID, ctx: Ctx = Results):
    return depth.list_game_player_stats(ctx.session, ctx.principal, game_id)


@staff.put("/games/{game_id}/player-stats", response_model=list[s.PlayerStatOut])
def replace_game_player_stats(game_id: UUID, body: s.PlayerStatsPut, ctx: Ctx = Results):
    return depth.replace_game_player_stats(ctx.session, ctx.principal, game_id, body.model_dump())


@staff.get("/competitions/{competition_id}/player-stats", response_model=list[s.PlayerTotalsOut])
def list_competition_player_stats(competition_id: UUID, ctx: Ctx = GameReads):
    """Season totals per player, formula stats computed on the totals (null on a division by zero)."""
    return depth.list_competition_player_stats(ctx.session, ctx.principal, competition_id)


# --- team fee split (REG-26), publish a program group (REG-14) --------------------------------------------------


@staff.get("/competition-teams/{competition_team_id}/fee-shares", response_model=list[s.TeamFeeShareOut])
def list_team_fee_shares(competition_team_id: UUID, ctx: Ctx = Teams):
    return depth.list_team_fee_shares(ctx.session, ctx.principal, competition_team_id)


@staff.post(
    "/competition-teams/{competition_team_id}/fee-shares", response_model=list[s.TeamFeeShareOut], status_code=201
)
def split_team_fee(competition_team_id: UUID, body: s.TeamFeeSplit, ctx: Ctx = Teams):
    """Bill the unbilled team fee as shares across rostered players, one charge and invoice each; whatever the
    shares leave is billed to `bill_to_client_id`."""
    return depth.split_team_fee(ctx.session, ctx.principal, competition_team_id, body.model_dump())


@staff.post("/competitions/from-program-group", response_model=s.CompetitionOut, status_code=201)
def create_competition_from_program_group(body: s.ProgramGroupPublish, ctx: Ctx = Manage):
    """A league or tournament from a program group: each subgroup becomes a team, its enrolled clients the
    roster. Needs the programs read key too."""
    return depth.publish_program_group(ctx.session, ctx.principal, body.model_dump())


# --- game cards (LGE-16) ----------------------------------------------------------------------------------------


@staff.get("/games/{game_id}/card", response_class=Response, responses=PDF)
def get_game_card(game_id: UUID, ctx: Ctx = Cards):
    return _pdf(depth.game_card_pdf(ctx.session, ctx.principal, game_id))


@staff.get("/competitions/{competition_id}/blank-game-card", response_class=Response, responses=PDF)
def get_blank_game_card(competition_id: UUID, ctx: Ctx = Cards):
    return _pdf(depth.manual_game_card_pdf(ctx.session, ctx.principal, competition_id))


@staff.get("/game-cards", response_class=Response, responses=PDF)
def get_game_cards(sport_id: UUID, from_on: date, to_on: date, ctx: Ctx = Cards):
    """Cards for every scheduled game of a sport in the date range (at most 31 days, 200 games)."""
    return _pdf(depth.game_cards_pdf(ctx.session, ctx.principal, sport_id, from_on, to_on))


# --- captain portal roster (REG-26) -----------------------------------------------------------------------------

portal = APIRouter(
    route_class=TxRoute, tags=["leagues"], generate_unique_id_function=camel_id, dependencies=[Depends(idempotency)]
)


@portal.get("/portal/league-teams", response_model=list[s.PortalLeagueTeamOut])
def list_portal_league_teams(ctx: Portal):
    """Teams the signed-in client (or someone they act for) captains."""
    return depth.portal_list_league_teams(ctx.session, ctx.principal)


@portal.get("/portal/league-teams/{competition_team_id}/roster", response_model=list[s.PortalRosterEntryOut])
def list_portal_team_roster(competition_team_id: UUID, ctx: Portal):
    return depth.portal_list_team_roster(ctx.session, ctx.principal, competition_team_id)


@portal.post(
    "/portal/league-teams/{competition_team_id}/roster", response_model=s.PortalRosterEntryOut, status_code=201
)
def create_portal_roster_entry(competition_team_id: UUID, body: s.PortalRosterEntryCreate, ctx: Portal):
    return depth.portal_add_roster_entry(ctx.session, ctx.principal, competition_team_id, body.model_dump())


@portal.delete("/portal/league-roster-entries/{roster_entry_id}", status_code=204)
def delete_portal_roster_entry(roster_entry_id: UUID, ctx: Portal):
    depth.portal_remove_roster_entry(ctx.session, ctx.principal, roster_entry_id)


# --- public league site (Phase 14 B2) ---------------------------------------------------------------------------

SiteManage = Depends(require(site.SITE))
Moderate = Depends(require(site.MODERATE))
SponsorManage = Depends(require(site.SPONSORS))
_IMAGE: dict[int | str, dict[str, Any]] = {
    200: {"content": {"image/jpeg": {}, "image/png": {}}, "description": "The image."}
}


def _image(named) -> Response:
    row, data = named
    return Response(data, media_type=row.content_type,
                    headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "public, max-age=300"})  # fmt: skip


async def _upload(request: Request) -> tuple[bytes, str]:
    return await request.body(), request.headers.get("content-type", "application/octet-stream").split(";")[0].strip()


@public.get("/public/league-site", response_model=s.PublicLeagueSiteOut)
def get_public_league_site(session: Public):
    """The enabled site's options and facility info; 404 while the site is off."""
    return site.public_site(session)


@public.get("/public/league-site/links", response_model=list[s.LeagueLinkOut])
def list_public_league_links(session: Public):
    return site.public_links(session)


@public.get("/public/league-site/photos", response_model=list[s.PublicLeaguePhotoOut])
def list_public_league_photos(session: Public):
    return site.public_photos(session)


@public.get("/public/league-site/photos/{photo_id}/image", response_class=Response, responses=_IMAGE)
def get_public_league_photo_image(photo_id: UUID, session: Public):
    return _image(site.public_photo_image(session, photo_id))


@public.get("/public/league-site/sponsors", response_model=list[s.PublicLeagueSponsorOut])
def list_public_league_sponsors(session: Public):
    return site.public_sponsors(session)


@public.get("/public/league-site/sponsors/{sponsor_id}/logo", response_class=Response, responses=_IMAGE)
def get_public_league_sponsor_logo(sponsor_id: UUID, session: Public):
    return _image(site.public_sponsor_logo(session, sponsor_id))


@public.get("/public/league-site/news", response_model=list[s.PublicLeagueNewsOut])
def list_public_league_news(session: Public):
    return site.public_news(session)


@public.get("/public/league-site/news/{story_id}", response_model=s.PublicLeagueNewsOut)
def get_public_league_news_story(story_id: UUID, session: Public):
    return site.public_news_story(session, story_id)


@public.get("/public/league-site/classes", response_model=list[s.PublicClassOut])
def list_public_league_classes(session: Public, location_id: UUID | None = None):
    """CLS-07: programs, camps, clinics and class series published to the portal."""
    return site.public_classes(session, location_id)


@public.get("/public/league-site/posts", response_model=list[s.PublicLeaguePostOut])
def list_public_league_posts(session: Public, kind: Literal["classified", "pickup"], location_id: UUID | None = None):
    """Approved classifieds or pickup games still within their 30 days; no poster details."""
    return site.public_posts(session, kind, location_id)


@public.get("/public/competitions/{competition_id}/teams", response_model=list[s.PublicTeamOut])
def list_public_teams(competition_id: UUID, session: Public):
    """Team names; player names only when the competition has `show_players` on."""
    return site.public_teams(session, competition_id)


@public.get("/public/competitions/{competition_id}/player-stats", response_model=list[s.PublicPlayerStatOut])
def list_public_player_stats(competition_id: UUID, session: Public):
    """404 unless the competition shows players."""
    return site.public_player_stats(session, competition_id)


@public.get("/public/competitions/{competition_id}/brackets", response_model=list[s.PublicBracketOut])
def list_public_brackets(competition_id: UUID, session: Public):
    return site.public_brackets(session, competition_id)


@public.get("/public/locations/{location_id}/league-board", response_model=s.PublicBoardOut)
def get_public_league_board(location_id: UUID, session: Public):
    """LGE-24: today's games and scores at one location, for a lobby screen; it refreshes every `refresh_sec`."""
    return site.public_board(session, location_id)


@staff.get("/league-site", response_model=s.LeagueSiteOut)
def get_league_site(ctx: Ctx = SiteManage):
    return site.get_site(ctx.session, ctx.principal)


@staff.put("/league-site", response_model=s.LeagueSiteOut)
def put_league_site(body: s.LeagueSiteIn, ctx: Ctx = SiteManage):
    """Tenant-wide: needs the key at every location."""
    return site.put_site(ctx.session, ctx.principal, body.model_dump())


@staff.get("/league-links", response_model=list[s.LeagueLinkOut])
def list_league_links(ctx: Ctx = SiteManage):
    return site.list_links(ctx.session, ctx.principal)


@staff.post("/league-links", response_model=s.LeagueLinkOut, status_code=201)
def create_league_link(body: s.LeagueLinkCreate, ctx: Ctx = SiteManage):
    return site.create_link(ctx.session, ctx.principal, body.model_dump())


@staff.patch("/league-links/{link_id}", response_model=s.LeagueLinkOut)
def update_league_link(link_id: UUID, body: s.LeagueLinkUpdate, ctx: Ctx = SiteManage):
    return site.update_link(ctx.session, ctx.principal, link_id, _patch(body))


@staff.delete("/league-links/{link_id}", status_code=204)
def delete_league_link(link_id: UUID, ctx: Ctx = SiteManage):
    site.delete_link(ctx.session, ctx.principal, link_id)


@staff.get("/league-photos", response_model=list[s.LeaguePhotoOut])
def list_league_photos(ctx: Ctx = SiteManage):
    return site.list_photos(ctx.session, ctx.principal)


@staff.post("/league-photos", response_model=s.LeaguePhotoOut, status_code=201)
async def upload_league_photo(
    request: Request, caption: Annotated[str, Query(max_length=300)] | None = None,
    album: Annotated[str, Query(max_length=100)] | None = None, ctx: Ctx = SiteManage,
):  # fmt: skip
    """JPEG or PNG bytes as the body, up to 900 KB, re-encoded and scanned. Errors: file-type-mismatch,
    file-too-large, file-infected."""
    data, content_type = await _upload(request)
    return site.upload_photo(ctx.session, ctx.principal, data, content_type, {"caption": caption, "album": album})


@staff.patch("/league-photos/{photo_id}", response_model=s.LeaguePhotoOut)
def update_league_photo(photo_id: UUID, body: s.LeaguePhotoUpdate, ctx: Ctx = SiteManage):
    return site.update_photo(ctx.session, ctx.principal, photo_id, _patch(body))


@staff.delete("/league-photos/{photo_id}", status_code=204)
def delete_league_photo(photo_id: UUID, ctx: Ctx = SiteManage):
    site.delete_photo(ctx.session, ctx.principal, photo_id)


@staff.get("/league-sponsors", response_model=list[s.LeagueSponsorOut])
def list_league_sponsors(ctx: Ctx = SponsorManage):
    return site.list_sponsors(ctx.session, ctx.principal)


@staff.post("/league-sponsors", response_model=s.LeagueSponsorOut, status_code=201)
def create_league_sponsor(body: s.LeagueSponsorCreate, ctx: Ctx = SponsorManage):
    return site.create_sponsor(ctx.session, ctx.principal, body.model_dump())


@staff.patch("/league-sponsors/{sponsor_id}", response_model=s.LeagueSponsorOut)
def update_league_sponsor(sponsor_id: UUID, body: s.LeagueSponsorUpdate, ctx: Ctx = SponsorManage):
    return site.update_sponsor(ctx.session, ctx.principal, sponsor_id, _patch(body))


@staff.put("/league-sponsors/{sponsor_id}/logo", response_model=s.LeagueSponsorOut)
async def set_league_sponsor_logo(sponsor_id: UUID, request: Request, ctx: Ctx = SponsorManage):
    """JPEG or PNG bytes as the body, up to 900 KB; replaces any earlier logo."""
    data, content_type = await _upload(request)
    return site.set_sponsor_logo(ctx.session, ctx.principal, sponsor_id, data, content_type)


@staff.delete("/league-sponsors/{sponsor_id}", status_code=204)
def delete_league_sponsor(sponsor_id: UUID, ctx: Ctx = SponsorManage):
    site.delete_sponsor(ctx.session, ctx.principal, sponsor_id)


@staff.get("/league-news", response_model=s.Page[s.LeagueNewsOut])
def list_league_news(query: Lists, ctx: Ctx = SiteManage):
    """Sort: created_at, published_at, title. Filter: is_pinned. q: title."""
    return site.list_news(ctx.session, ctx.principal, query)


@staff.get("/league-news/{story_id}", response_model=s.LeagueNewsOut)
def get_league_news_story(story_id: UUID, ctx: Ctx = SiteManage):
    return site.get_news(ctx.session, ctx.principal, story_id)


@staff.post("/league-news", response_model=s.LeagueNewsOut, status_code=201)
def create_league_news_story(body: s.LeagueNewsCreate, ctx: Ctx = SiteManage):
    """Public once `published_at` is set and reached; leave it empty for a draft."""
    return site.create_news(ctx.session, ctx.principal, body.model_dump())


@staff.patch("/league-news/{story_id}", response_model=s.LeagueNewsOut)
def update_league_news_story(story_id: UUID, body: s.LeagueNewsUpdate, ctx: Ctx = SiteManage):
    return site.update_news(ctx.session, ctx.principal, story_id, _patch(body))


@staff.delete("/league-news/{story_id}", status_code=204)
def delete_league_news_story(story_id: UUID, ctx: Ctx = SiteManage):
    site.delete_news(ctx.session, ctx.principal, story_id)


@staff.get("/league-posts", response_model=s.Page[s.LeaguePostOut])
def list_league_posts(query: Lists, ctx: Ctx = Moderate):
    """The moderation queue at the caller's locations. Filters: status, kind, location_id. q: title."""
    return site.list_posts(ctx.session, ctx.principal, query)


@staff.post("/league-posts/{post_id}/approve", response_model=s.LeaguePostOut)
def approve_league_post(post_id: UUID, ctx: Ctx = Moderate):
    """Errors: post-not-pending."""
    return site.approve_post(ctx.session, ctx.principal, post_id)


@staff.post("/league-posts/{post_id}/reject", response_model=s.LeaguePostOut)
def reject_league_post(post_id: UUID, body: s.LeaguePostReject, ctx: Ctx = Moderate):
    """Refuse a pending post or take down an approved one. Errors: post-not-pending."""
    return site.reject_post(ctx.session, ctx.principal, post_id, body.reason)


@portal.get("/portal/league-posts", response_model=list[s.PortalLeaguePostOut])
def list_portal_league_posts(ctx: Portal):
    return site.portal_list_posts(ctx.session, ctx.principal)


@portal.post("/portal/league-posts", response_model=s.PortalLeaguePostOut, status_code=201,
             dependencies=[Depends(rate_limit("league-post"))])  # fmt: skip
def create_portal_league_post(body: s.LeaguePostCreate, ctx: Portal):
    """A classified or a pickup game; shown once staff approve, for 30 days. Errors: post-limit."""
    return site.portal_create_post(ctx.session, ctx.principal, body.model_dump())


@portal.post("/portal/league-posts/{post_id}/withdraw", status_code=204)
def withdraw_portal_league_post(post_id: UUID, ctx: Portal):
    site.portal_withdraw_post(ctx.session, ctx.principal, post_id)


@portal.post("/portal/league-posts/{post_id}/contact", status_code=204,
             dependencies=[Depends(rate_limit("league-post-contact"))])  # fmt: skip
def contact_portal_league_post(post_id: UUID, body: s.LeaguePostContact, ctx: Portal, response: Response):
    """The relay: the poster is emailed the message and your name and address; theirs is never shown.
    Errors: contact-unavailable, rate-limited."""
    site.portal_contact_post(ctx.session, ctx.principal, post_id, body.message)
    hit("league-post-contact-sender", str(ctx.principal.identity_id), response, tenant=ctx.session.info["tenant_id"])


router = APIRouter()
router.include_router(staff)
router.include_router(portal)
router.include_router(public)
