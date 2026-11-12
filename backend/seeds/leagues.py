"""Demo leagues (build module 11): a public Wednesday futsal league at Downtown with six teams (one fee billed
to a client, a captain on its roster), a referee, a committed schedule on Court 3, one played game, the demo
scorekeeper assigned to it and a scoring stat table with a formula stat (Phase 14 B1)."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules import leagues, platform
from app.modules.billing.models import RevenueCategory
from app.modules.clients.models import Client
from app.modules.leagues import depth
from app.modules.leagues import schemas as s
from app.modules.leagues.models import Competition, Game
from app.modules.platform.models import Identity, Location, StaffUser
from app.modules.resources.models import Resource


def seed(session: Session) -> None:
    actor = session.info["actor"]
    service = leagues.service
    body = lambda schema, **fields: schema(**fields).model_dump()  # noqa: E731  (the router's defaults)
    location = session.scalar(select(Location).where(Location.slug == "downtown"))
    if location is None or session.scalar(select(Competition.id).limit(1)):
        return
    court = session.scalar(select(Resource.id).where(Resource.location_id == location.id, Resource.name == "Court 3"))
    category = session.scalar(select(RevenueCategory).where(RevenueCategory.code == "PROGRAMS"))
    member = session.scalar(select(Client).where(Client.first_name == "Morgan", Client.last_name == "Member"))
    today = platform.service.location_today(session, location.id)
    monday = today + timedelta(days=7 - today.weekday())
    sport = service.create_sport(
        session, actor, body(s.SportCreate, name="Futsal", default_game_length_min=60, points_win=3)
    )
    season = service.create_season(
        session, actor, body(s.SeasonWrite, name="Demo season", starts_on=monday, ends_on=monday + timedelta(weeks=10))
    )
    league = service.create_competition(session, actor, body(
        s.CompetitionCreate, location_id=location.id, kind="league", name="Wednesday Futsal", sport_id=sport.id,
        season_id=season.id, starts_on=monday, ends_on=monday + timedelta(weeks=10), is_public=True,
        team_fee_minor=30000, revenue_category_id=category.id, team_fee_text="$300 per team",
    ))  # fmt: skip
    service.transition_competition(session, actor, league.id, "activate")
    first = service.add_competition_team(session, actor, league.id, body(
        s.CompetitionTeamCreate, team={"name": "Downtown Strikers", "captain_client_id": member.id}, bill_to_client_id=member.id
    ))  # fmt: skip
    service.generate_competition_teams(session, actor, league.id, body(s.TeamGenerate, count=5))
    service.add_roster_entry(
        session, actor, first["id"], body(s.RosterEntryCreate, client_id=member.id, role="captain")
    )
    service.create_official(session, actor, body(
        s.OfficialCreate, location_id=location.id, first_name="Rita", last_name="Referee", sport_ids=[sport.id]
    ))  # fmt: skip
    keeper = session.scalar(
        select(StaffUser.id).join(Identity, Identity.id == StaffUser.identity_id)
        .where(Identity.email == "scorekeeper@courtside-demo.example.com")
    )  # fmt: skip
    if keeper is not None:  # a scorekeeper reaches only the competitions they are assigned to (LGE-26)
        depth.replace_competition_staff(
            session, actor, league.id, body(s.CompetitionStaffPut, staff=[{"staff_user_id": keeper}])
        )
    run = service.create_schedule_run(session, actor, body(
        s.ScheduleRunCreate, location_id=location.id, competition_ids=[league.id], resource_ids=[court],
        time_slots=[{"weekday": 3, "starts_at": "18:00", "ends_at": "22:00", "resource_id": court}],
        starts_on=monday, ends_on=monday + timedelta(weeks=10),
    ))  # fmt: skip
    service.generate_schedule(session, actor, run["id"])
    while service.generate_schedule_chunk(session, run["id"]):  # the job's chunks, inline (no worker in a seed)
        pass
    service.commit_schedule(session, actor, run["id"])
    game = session.scalar(
        select(Game).where(Game.schedule_run_id == run["id"], Game.status == "scheduled").order_by(Game.starts_at)
    )
    if game is not None:
        service.put_game_result(session, actor, game.id, body(s.GameResultPut, home={"score": 4}, away={"score": 2}))
    table = depth.create_stat_table(session, actor, sport.id, body(s.StatTableWrite, name="Scoring"))
    for code, name, extra in (
        ("G", "Goals", {}),
        ("A", "Assists", {}),
        ("PTS", "Points", {"kind": "formula", "formula": "G + A"}),
    ):
        depth.create_stat_definition(
            session, actor, table["id"], body(s.StatDefinitionCreate, code=code, name=name, **extra)
        )
