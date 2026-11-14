"""A league night held ahead of the schedule: a block carrying the competition. The competition's games take their
slots out of it when committed (the block is split around each game) and what they did not take stays held; other
bookings and other competitions' games still clash with it. Gated on the game key at the competition's location."""

import threading
import time
from datetime import datetime
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.auth import system_principal
from app.core.db import tenant_session
from app.main import app as fastapi_app
from app.modules import scheduling
from app.modules.leagues.tests.test_leagues import WINDOW, generate, get, league, post, run_body, staff
from app.modules.scheduling.tests.helpers import API, book, local
from conftest import scalar


def night(client, headers, f, competition_id, resources, start=18, end=22):
    return client.post(f"{API}/competitions/{competition_id}/league-nights", headers=headers, json={
        "resource_ids": resources, "starts_at": local(f.zone, 2031, 5, 7, start), "ends_at": local(f.zone, 2031, 5, 7, end),
    })  # fmt: skip


def test_the_league_uses_its_blocked_night_and_what_is_left_stays_held(client, owner, tenant, f):
    comp = league(client, owner, f, teams=4)
    other = league(client, owner, f, teams=2, name="Thursday Futsal")
    held = night(client, owner, f, comp["id"], [f.court, f.court2])
    assert held.status_code == 201, held.text
    assert held.json()["title"] == "Wednesday Futsal league night"
    assert (
        book(client, owner, f, [f.court], local(f.zone, 2031, 5, 7, 19), local(f.zone, 2031, 5, 7, 20)).status_code
        == 409
    )
    run = post(client, owner, "/schedule-runs", run_body(f, [comp["id"]]))
    generate(client, owner, run["id"])
    post(client, owner, f"/schedule-runs/{run['id']}/commit", {}, 200)
    games = get(client, owner, f"/schedule-runs/{run['id']}/games")["data"]
    first_night = [g for g in games if g["starts_at"] and g["starts_at"].startswith("2031-05-07")]
    assert first_night and all(g["status"] == "scheduled" for g in first_night), first_night
    # what the games did not take stays held: the end of the night on Court 1 and all of Court 2
    last = max(g["ends_at"] for g in first_night)
    assert book(client, owner, f, [f.court], last, local(f.zone, 2031, 5, 7, 22)).status_code == 409
    assert book(client, owner, f, [f.half_a], last, local(f.zone, 2031, 5, 7, 22)).status_code == 409  # a half too
    assert (
        book(client, owner, f, [f.court2], local(f.zone, 2031, 5, 7, 18), local(f.zone, 2031, 5, 7, 19)).status_code
        == 409
    )
    # another competition's game is refused there; outside the night Court 2 is free
    body = {
        "competition_id": other["id"],
        "home_team_id": other["teams"][0]["id"],
        "away_team_id": other["teams"][1]["id"],
    }
    clash = client.post(
        f"{API}/games", headers=owner, json=body | {"resource_id": f.court2, "starts_at": local(f.zone, 2031, 5, 7, 19)}
    )
    assert clash.status_code == 409 and clash.json()["code"] == "booking-conflict"
    assert (
        book(client, owner, f, [f.court2], local(f.zone, 2031, 5, 7, 22), local(f.zone, 2031, 5, 7, 23)).status_code
        == 201
    )
    # moving one of the league's games into the held end of the night is allowed too
    moved = client.post(f"{API}/games/{first_night[0]['id']}/reschedule", headers=owner,
                        json={"resource_id": f.court2, "starts_at": local(f.zone, 2031, 5, 7, 20)})  # fmt: skip
    assert moved.status_code == 200, moved.text


def test_a_league_night_needs_the_game_key_and_courts_at_the_location(client, owner, tenant, f):
    comp = league(client, owner, f)
    desk = staff(client, tenant, "front_desk", f)
    assert night(client, desk, f, comp["id"], [f.court]).status_code == 403
    elsewhere = post(
        client, owner, "/locations", {"name": "Elsewhere", "time_zone": "America/Chicago", "country_code": "US"}
    )
    group = post(client, owner, "/resource-groups", {"location_id": elsewhere["id"], "name": "Far"})
    far = post(
        client,
        owner,
        "/resources",
        {"location_id": elsewhere["id"], "resource_group_id": group["id"], "name": "Far court"},
    )
    bad = night(client, owner, f, comp["id"], [far["id"]])
    assert bad.status_code == 422 and bad.json()["errors"][0]["pointer"] == "/resource_ids"
    assert night(client, owner, f, comp["id"], [f.court], start=22, end=18).status_code == 422
    long = client.post(f"{API}/competitions/{comp['id']}/league-nights", headers=owner, json={
        "resource_ids": [f.court], "starts_at": local(f.zone, 2031, 5, 7, 18), "ends_at": local(f.zone, 2031, 5, 8, 19),
    })  # fmt: skip
    assert long.status_code == 422 and long.json()["errors"][0]["pointer"] == "/ends_at"  # more than 24 hours
    draft = league(client, owner, f, activate=False, name="Draft League")
    assert night(client, owner, f, draft["id"], [f.court]).status_code == 409
    post(client, owner, f"/competitions/{draft['id']}/archive", {}, 200)
    assert night(client, owner, f, draft["id"], [f.court]).status_code == 409  # archived
    assert WINDOW["weekday"] == 3  # 2031-05-07 is a Wednesday, the window's day


def test_a_carve_that_meets_a_concurrent_carve_rereads_the_night_and_retries(client, owner, tenant, f):
    """Known limit 3, made fail safe: while one carve holds the night's row lock, a game moved into the night waits
    on it. When the first commits, the block the mover read is cancelled; it re-reads the night's current pieces and
    carves again instead of reporting a clash that is not real. (A new booking waits earlier, on the booking number
    counter, and so already reads the night afresh; a move takes no number.)"""
    comp = league(client, owner, f, teams=4)
    assert night(client, owner, f, comp["id"], [f.court]).status_code == 201
    teams, codes = comp["teams"], []
    game = post(client, owner, "/games", {
        "competition_id": comp["id"], "home_team_id": teams[2]["id"], "away_team_id": teams[3]["id"],
        "resource_id": f.court2, "starts_at": local(f.zone, 2031, 5, 7, 23),
    })  # fmt: skip
    move = {"resource_id": f.court, "starts_at": local(f.zone, 2031, 5, 7, 20)}

    def second_game():
        with TestClient(fastapi_app) as own:
            codes.append(own.post(f"{API}/games/{game['id']}/reschedule", headers=owner, json=move).status_code)

    waiting = text(
        "SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock' AND datname = current_database()"
    )
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        scheduling.service.create_booking(
            session, location_id=UUID(f.location), kind="block", block_kind="unavailable",
            starts_at=datetime.fromisoformat(local(f.zone, 2031, 5, 7, 18)),
            ends_at=datetime.fromisoformat(local(f.zone, 2031, 5, 7, 19)), resource_ids=[UUID(f.court)],
            include_linked=False, title="First carve", buffer_before_min=0, buffer_after_min=0,
            gives_way=("leagues", "competition", UUID(comp["id"])),
        )  # fmt: skip
        thread = threading.Thread(target=second_game)
        thread.start()
        deadline = time.monotonic() + 10
        while thread.is_alive() and not scalar(tenant, waiting) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert thread.is_alive(), codes  # the second carve is waiting on the night, not finished before it
    thread.join(timeout=30)
    assert codes == [200]
    # both carves stand: the night is held between them and after the second game
    assert (
        book(client, owner, f, [f.court], local(f.zone, 2031, 5, 7, 19), local(f.zone, 2031, 5, 7, 20)).status_code
        == 409
    )
