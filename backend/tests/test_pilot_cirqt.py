"""Pilot fit check for CIRQT (docs/status/pilot-fit-cirqt.md): the facility from seeds/cirqt.py, built under a
fresh slug, driven through the API as its owner, manager, front desk, league manager, a member and a parent.

Each test asserts what CIRQT needs. Where the product cannot do it today the test is `xfail(strict=True)` with
the reason, so it turns red the day the gap closes. Product code is not changed by this file.
"""

import os
from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError

from app.core import clock
from app.core.db.session import tenant_session
from app.core.events import OutboxEvent
from app.modules.clients.models import Client
from app.modules.memberships.models import MembershipPlan
from app.modules.platform.models import Location
from app.modules.resources.models import Resource
from app.modules.scheduling.models import ResourceHold
from conftest import _run_schedule_job, link_token, login, verify_email
from seeds import cirqt

API = "/api/v1"
ZONE = ZoneInfo(cirqt.ZONE)
# One clock for the whole file: core.clock (which the product reads) frozen at noon on CIRQT's real local date. Every
# scenario builds its times from NOW, TODAY and at(), never from datetime.now(), so the file gives the same result at
# any hour (a slot "three hours from now" used to run past midnight after about 20:00 in Chicago). The date is the
# real local one because Postgres stamps created_at with the real time; noon keeps both twelve hours from midnight.
# CIRQT_FROZEN_AT=HH:MM moves the frozen hour, to prove the scenarios hold at any time of day.
NOW = datetime.combine(datetime.now(ZONE).date(), time.fromisoformat(os.environ.get("CIRQT_FROZEN_AT", "12:00")), ZONE)
TODAY = NOW.date()
MON = TODAY + timedelta(days=7 - TODAY.weekday() + 21)  # a Monday three to four weeks out
LEAGUE_FROM, LEAGUE_TO = MON + timedelta(days=14), MON + timedelta(days=35)
BLOCKED_TUESDAY = MON + timedelta(days=15)
PDAY = MON + timedelta(days=9)  # a Wednesday with nothing booked: the pricing previews


@pytest.fixture(scope="module", autouse=True)
def frozen_clock():
    with clock.freeze(NOW.astimezone(UTC)):
        yield


def at(day: date, hhmm: str) -> str:
    return datetime.combine(day, time.fromisoformat(hhmm), ZONE).astimezone(UTC).isoformat().replace("+00:00", "Z")


def ok(response, status: int = 201) -> dict:
    assert response.status_code == status, response.text
    return response.json() if response.content else {}


def key() -> dict:
    return {"Idempotency-Key": f"cirqt-{uuid4().hex}"}


@pytest.fixture(scope="module")
def w(client_module):
    made = cirqt.build(slug=f"cirqt-{uuid4().hex[:8]}", name="CIRQT test")
    tenant = SimpleNamespace(id=made["tenant_id"], slug=made["slug"])
    mail = made["domain"]
    sign = lambda local, audience="staff": login(client_module, tenant, f"{local}@{mail}", cirqt.PASSWORD, audience)  # noqa: E731
    with tenant_session(tenant.id) as session:
        location = session.scalar(select(Location).where(Location.name == "CIRQT"))
        courts = {
            r.name: str(r.id) for r in session.scalars(select(Resource).where(Resource.location_id == location.id))
        }
        people = {c.primary_email: c for c in session.scalars(select(Client).where(Client.primary_email.is_not(None)))}
        parent, member = people[f"parent@{mail}"], people[f"member@{mail}"]
        kids = list(session.scalars(select(Client).where(Client.last_name == parent.last_name, Client.primary_email.is_(None)).order_by(Client.birth_on)))  # fmt: skip
        plans = {p.name: str(p.id) for p in session.scalars(select(MembershipPlan))}
        walk_in_pool = [str(c.id) for c in people.values() if c.id not in (parent.id, member.id)]
    owner = sign("owner")
    types = {t["name"]: t for t in ok(client_module.get(f"{API}/rental-types?location_id={location.id}", headers=owner), 200)["data"]}  # fmt: skip
    # Every seeded adult holds a membership; a walk-in guest pays guest prices.
    guest = ok(client_module.post(f"{API}/clients", headers=owner, json={
        "first_name": "Gale", "last_name": "Guest", "home_location_id": str(location.id), "birth_on": "1988-03-04"}))["id"]  # fmt: skip
    return SimpleNamespace(
        tenant=tenant, mail=mail, location=str(location.id), courts=courts, member=str(member.id),
        parent=str(parent.id), kids=[str(k.id) for k in kids], kid_names=[k.first_name for k in kids], plans=plans,
        types={n: t["id"] for n, t in types.items()}, rates={n: t["online_rental_rate_id"] for n, t in types.items()},
        others=walk_in_pool, guest=guest, owner=owner, manager=sign("manager"), desk=sign("front-desk"),
        league=sign("league-admin"), member_portal=sign("member", "client"), parent_portal=sign("parent", "client"),
        public={"X-Tenant-Slug": tenant.slug},
    )  # fmt: skip


@pytest.fixture(scope="module")
def client_module():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


def rent(c, w, headers, sport: str, court: str, day: date, start: str, end: str, client_id: str | None = None,
         **extra):  # fmt: skip
    return c.post(f"{API}/rentals", headers=headers | key(), json={
        "location_id": w.location, "rental_type_id": w.types[sport], "client_id": client_id or w.others[0],
        "resources": [{"resource_id": w.courts[court]}], "starts_at": at(day, start), "ends_at": at(day, end),
        "charge": {"decision": "bill", "rental_rate_id": w.rates[sport]},
    } | extra)  # fmt: skip


def conflict(response) -> bool:
    return response.status_code == 409 and response.json()["code"] == "booking-conflict"


# --- a. online booking, payment and the database constraint --------------------------------------------------


def test_a_member_books_court_1_online_and_overlaps_are_refused(client_module, w):
    c = client_module
    body = {"rental_type_id": w.types["Badminton court"], "client_id": w.member, "resource_id": w.courts["Court 1"],
            "starts_at": at(MON, "10:00"), "ends_at": at(MON, "11:00")}  # fmt: skip
    checkout = ok(c.post(f"{API}/portal/rentals", headers=w.member_portal, json=body))
    assert checkout["payment_required"] and checkout["rental"]["status"] == "tentative"
    paid = ok(c.post(f"{API}/portal/rentals/{checkout['rental']['id']}/confirm", headers=w.member_portal | key(),
                     json={"provider_payment_token": "tok_card_ok"}), 200)  # fmt: skip
    assert paid["rental"]["status"] == "confirmed" and paid["payment_status"] == "succeeded"
    # The same court at the same time, and pickleball on it half an hour later, are refused.
    assert conflict(c.post(f"{API}/portal/rentals", headers=w.member_portal, json=body))
    assert conflict(rent(c, w, w.desk, "Badminton court", "Court 1", MON, "10:00", "11:00"))
    assert conflict(rent(c, w, w.desk, "Pickleball court", "Court 1", MON, "10:30", "11:30"))
    assert (
        ok(rent(c, w, w.desk, "Pickleball court", "Court 4", MON, "10:30", "11:30"))["rental"]["status"] == "confirmed"
    )
    # The arbiter is the exclusion constraint, not the service pre-check: a hold written past the service clashes.
    block = ok(c.post(f"{API}/bookings", headers=w.manager, json={
        "location_id": w.location, "kind": "block", "block_kind": "unavailable", "resources": [{"resource_id": w.courts["Court 4"]}],
        "starts_at": at(MON, "06:00"), "ends_at": at(MON, "07:00"),
    }))  # fmt: skip
    with pytest.raises(IntegrityError, match="ex_resource_hold_overlap"):
        with tenant_session(w.tenant.id) as session:
            session.add(ResourceHold(
                resource_id=w.courts["Court 1"], booking_id=block["booking"]["id"], source_resource_id=w.courts["Court 1"],
                origin="booked", during=Range(datetime.fromisoformat(body["starts_at"].replace("Z", "+00:00")),
                                              datetime.fromisoformat(body["ends_at"].replace("Z", "+00:00")), bounds="[)"),
            ))  # fmt: skip
            session.flush()


def test_a_a_member_picks_an_8_pm_court_from_the_open_times_and_pays(client_module, w):
    """Prime time is 18:00-22:00: the open times cover the whole day (here narrowed to the evening), every court."""
    c, day = client_module, MON + timedelta(days=4)
    query = (f"rental_type_id={w.types['Badminton court']}&on={day.isoformat()}&length_min=60&client_id={w.member}"
             "&from_time=18:00&to_time=22:00")  # fmt: skip
    page = ok(c.get(f"{API}/portal/rental-availability?{query}", headers=w.member_portal), 200)
    assert not page["page"]["has_more"]
    eight = [
        s for s in page["data"] if datetime.fromisoformat(s["starts_at"]) == datetime.fromisoformat(at(day, "20:00"))
    ]
    assert len(eight) == len({s["resource_id"] for s in page["data"]}) >= 2  # 8 pm is offered on every court
    slot = eight[-1]
    assert slot["price_minor"] == 2500 and slot["is_member_price"]  # member prime
    checkout = ok(c.post(f"{API}/portal/rentals", headers=w.member_portal, json={
        "rental_type_id": w.types["Badminton court"], "client_id": w.member, "resource_id": slot["resource_id"],
        "starts_at": slot["starts_at"], "ends_at": slot["ends_at"]}))  # fmt: skip
    assert checkout["quote"]["subtotal_minor"] == 2500
    paid = ok(c.post(f"{API}/portal/rentals/{checkout['rental']['id']}/confirm", headers=w.member_portal | key(),
                     json={"provider_payment_token": "tok_card_ok"}), 200)  # fmt: skip
    assert paid["rental"]["status"] == "confirmed"
    again = ok(c.get(f"{API}/portal/rental-availability?{query}", headers=w.member_portal), 200)["data"]
    assert (slot["resource_id"], slot["starts_at"]) not in {(s["resource_id"], s["starts_at"]) for s in again}


# --- b. convertible courts: Court 2 and Court 3 each become one volleyball court ------------------------------


def test_b_volleyball_on_court_2_or_3_excludes_badminton_and_pickleball_there(client_module, w):
    c, day = client_module, MON + timedelta(days=2)
    assert (
        ok(rent(c, w, w.desk, "Volleyball court", "Court 2", day, "18:00", "20:00"))["rental"]["status"] == "confirmed"
    )
    assert conflict(rent(c, w, w.desk, "Badminton court", "Court 2", day, "19:00", "20:00"))
    assert conflict(rent(c, w, w.desk, "Pickleball court", "Court 2", day, "17:30", "18:30"))
    assert ok(rent(c, w, w.desk, "Badminton court", "Court 3", day, "18:00", "19:00"))  # the neighbour stays free
    # The 10-minute changeover either side of volleyball keeps Court 2 shut from 17:50 to 20:10.
    assert conflict(rent(c, w, w.desk, "Badminton court", "Court 2", day, "17:00", "18:00"))
    assert conflict(rent(c, w, w.desk, "Badminton court", "Court 2", day, "20:00", "21:00"))
    assert ok(rent(c, w, w.desk, "Badminton court", "Court 2", day, "20:30", "21:30"))
    # The other way round: a pickleball game on Court 3 stops a volleyball booking of Court 3, and its changeover
    # stops a volleyball booking that starts the minute the pickleball ends.
    assert ok(rent(c, w, w.desk, "Pickleball court", "Court 3", day, "10:00", "11:00"))
    assert conflict(rent(c, w, w.desk, "Volleyball court", "Court 3", day, "10:30", "11:30"))
    assert conflict(rent(c, w, w.desk, "Volleyball court", "Court 3", day, "11:00", "12:00"))
    assert ok(rent(c, w, w.desk, "Volleyball court", "Court 3", day, "11:30", "12:30"))
    # Volleyball is offered only on the convertible courts.
    wrong = rent(c, w, w.desk, "Volleyball court", "Court 1", day, "12:00", "13:00")
    assert wrong.status_code == 422, wrong.text
    public = ok(c.get(f"{API}/public/rental-types", headers=w.public), 200)
    volley = next(t for t in public if t["name"] == "Volleyball court")
    assert {r["id"] for r in volley["resources"]} == {w.courts["Court 2"], w.courts["Court 3"]}


# --- c. league nights hold the courts ------------------------------------------------------------------------


@pytest.fixture(scope="module")
def leagues(client_module, w):
    """The manager holds every court on one Tuesday as the badminton league's night; the league manager then
    generates and commits the badminton schedule (Tuesdays, one game per court) and the volleyball one (Thursdays,
    the two volleyball venues)."""
    c = client_module
    competitions = {x["name"]: x for x in ok(c.get(f"{API}/competitions", headers=w.league), 200)["data"]}
    night = f"{API}/competitions/{competitions['Tuesday Badminton League']['id']}/league-nights"
    block = c.post(night, headers=w.manager, json={
        "resource_ids": [w.courts[n] for n in cirqt.COURTS],
        "starts_at": at(BLOCKED_TUESDAY, "18:00"), "ends_at": at(BLOCKED_TUESDAY, "22:00"),
    })  # fmt: skip
    venues = {v["name"]: v["id"] for v in ok(c.get(f"{API}/league-venues", headers=w.league), 200)["data"]}
    runs = {}
    for name, slots in (
        ("Tuesday Badminton League", [{"weekday": 2, "starts_at": "18:00", "ends_at": "22:00", "resource_id": w.courts[n]} for n in cirqt.COURTS]),
        ("Thursday Volleyball League", [{"weekday": 4, "starts_at": "18:00", "ends_at": "22:00", "venue_id": venues[f"Volleyball, {n}"]} for n in cirqt.VOLLEYBALL_COURTS]),
    ):  # fmt: skip
        run = ok(c.post(f"{API}/schedule-runs", headers=w.league, json={
            "location_id": w.location, "competition_ids": [competitions[name]["id"]], "time_slots": slots,
            "resource_ids": [s["resource_id"] for s in slots if s.get("resource_id")],
            "starts_on": LEAGUE_FROM.isoformat(), "ends_on": LEAGUE_TO.isoformat(),
        }))  # fmt: skip
        generated = c.post(f"{API}/schedule-runs/{run['id']}/generate", headers=w.league, json={})
        assert generated.status_code < 300, generated.text
        _run_schedule_job(w.tenant, run["id"])
        ok(c.post(f"{API}/schedule-runs/{run['id']}/commit", headers=w.league, json={}), 200)
        games = ok(c.get(f"{API}/schedule-runs/{run['id']}/games", headers=w.league), 200)["data"]
        runs[name] = SimpleNamespace(competition=competitions[name]["id"], run=run["id"], games=games)
    return SimpleNamespace(block=block, runs=runs)


def _local_day(iso: str) -> date:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(ZONE).date()


def test_c_blocked_league_night_and_committed_fixtures_refuse_public_rentals(client_module, w, leagues):
    c = client_module
    assert leagues.block.status_code == 201, leagues.block.text
    assert conflict(rent(c, w, w.desk, "Badminton court", "Court 1", BLOCKED_TUESDAY, "19:00", "20:00"))
    badminton = leagues.runs["Tuesday Badminton League"].games
    scheduled = [g for g in badminton if g["status"] == "scheduled"]
    assert scheduled, badminton
    # The night is held for this league: its games take their slots out of the hold.
    assert [g for g in scheduled if _local_day(g["starts_at"]) == BLOCKED_TUESDAY]
    game = scheduled[0]
    court = next(n for n, i in w.courts.items() if i == game["resource_id"])
    starts = datetime.fromisoformat(game["starts_at"].replace("Z", "+00:00")).astimezone(ZONE)
    assert conflict(rent(c, w, w.desk, "Badminton court", court, starts.date(), starts.strftime("%H:%M"),
                         (starts + timedelta(hours=1)).strftime("%H:%M")))  # fmt: skip
    portal = c.post(f"{API}/portal/rentals", headers=w.member_portal, json={
        "rental_type_id": w.types["Pickleball court"], "client_id": w.member, "resource_id": game["resource_id"],
        "starts_at": game["starts_at"], "ends_at": game["ends_at"],
    })  # fmt: skip
    assert conflict(portal)
    volley = [g for g in leagues.runs["Thursday Volleyball League"].games if g["status"] == "scheduled"]
    assert volley and {g["resource_id"] for g in volley} <= {w.courts["Court 2"], w.courts["Court 3"]}
    v = datetime.fromisoformat(volley[0]["starts_at"].replace("Z", "+00:00")).astimezone(ZONE)
    vcourt = next(n for n, i in w.courts.items() if i == volley[0]["resource_id"])
    hhmm = v.strftime("%H:%M"), (v + timedelta(hours=1)).strftime("%H:%M")
    assert conflict(rent(c, w, w.desk, "Badminton court", vcourt, v.date(), *hhmm))
    assert ok(rent(c, w, w.desk, "Badminton court", "Court 1", v.date(), *hhmm))  # Court 1 is not a volleyball court


def test_c_league_fixtures_use_the_blocked_league_night(w, leagues):
    games = leagues.runs["Tuesday Badminton League"].games
    assert any(g["status"] == "scheduled" and _local_day(g["starts_at"]) == BLOCKED_TUESDAY for g in games)


# --- d. leagues: teams, fixtures, scores, standings ----------------------------------------------------------


def test_d_badminton_and_volleyball_leagues_score_and_rank(client_module, w, leagues):
    c = client_module
    for name, sets in (
        ("Tuesday Badminton League", ([21, 19, 21], [18, 21, 15])),
        ("Thursday Volleyball League", ([25, 23, 25, 25], [20, 25, 18, 22])),
    ):
        run = leagues.runs[name]
        teams = ok(c.get(f"{API}/competitions/{run.competition}/teams", headers=w.league), 200)
        assert len(teams if isinstance(teams, list) else teams["data"]) == 6
        game = next(g for g in run.games if g["status"] == "scheduled")
        result = ok(c.put(f"{API}/games/{game['id']}/result", headers=w.league,
                          json={"home": {"sets": sets[0]}, "away": {"sets": sets[1]}}), 200)  # fmt: skip
        assert result["home"]["outcome"] == "win" and result["away"]["outcome"] == "loss"
        standings = ok(c.get(f"{API}/competitions/{run.competition}/standings", headers=w.league), 200)
        rows = standings if isinstance(standings, list) else standings["data"]
        top = rows[0]
        assert top["competition_team_id"] == result["home"]["competition_team_id"]
        assert float(top["points"]) == 2.0 and top["wins"] == 1
        public = ok(c.get(f"{API}/public/competitions/{run.competition}/standings", headers=w.public), 200)
        assert public


def test_d_set_by_set_scores(client_module, w, leagues):
    c = client_module
    run = leagues.runs["Tuesday Badminton League"]
    game = [g for g in run.games if g["status"] == "scheduled"][1]  # the first one is scored above
    url = f"{API}/games/{game['id']}/result"
    # 21-20 is not a finished set (win by two); 30-29 is, at the cap.
    bad = c.put(url, headers=w.league, json={"home": {"sets": [21, 21]}, "away": {"sets": [20, 15]}})
    assert bad.status_code == 422, bad.text
    result = ok(c.put(url, headers=w.league, json={"home": {"sets": [21, 19, 30]}, "away": {"sets": [18, 21, 29]}}), 200)  # fmt: skip
    assert (result["home"]["score"], result["away"]["score"]) == (2, 1) and result["home"]["sets"] == [21, 19, 30]
    public = ok(c.get(f"{API}/public/competitions/{run.competition}/games", headers=w.public), 200)
    assert next(g for g in public if g["id"] == game["id"])["set_scores"] == "21-18, 19-21, 30-29"


# --- e. children ---------------------------------------------------------------------------------------------


def test_e_parent_registers_and_pays_for_a_child_and_the_child_stays_private(client_module, w, leagues):
    c = client_module
    actable = ok(c.get(f"{API}/portal/clients", headers=w.parent_portal), 200)
    actable = actable if isinstance(actable, list) else actable["data"]
    assert set(w.kids) <= {x["id"] for x in actable}
    bought = ok(c.post(f"{API}/portal/membership-contracts", headers=w.parent_portal | key(), json={
        "client_id": w.kids[0], "location_id": w.location, "membership_plan_id": w.plans["Junior monthly"],
        "method_token": "tok_card_ok",
    }))  # fmt: skip
    assert bought["owner_client_id"] == w.kids[0] and bought["status"] == "active"
    assert bought["payment_status"] == "succeeded"
    # No address and no opt-in: nothing can be sent to the child directly.
    prefs = ok(c.get(f"{API}/clients/{w.kids[0]}/communication-preferences", headers=w.owner), 200)["data"]
    assert not [p for p in prefs if p["is_subscribed"] and p["topic"] in ("email_campaigns", "sms_marketing")]
    # The child plays on a public league team; with show_players off (the default) no public page names them.
    team = ok(c.get(f"{API}/competitions/{leagues.runs['Tuesday Badminton League'].competition}/teams", headers=w.league), 200)  # fmt: skip
    team = (team if isinstance(team, list) else team["data"])[0]
    ok(c.post(f"{API}/competition-teams/{team['id']}/roster", headers=w.league, json={"client_id": w.kids[0], "role": "player"}))  # fmt: skip
    pages = [f"{API}/public/competitions", f"{API}/public/locations/{w.location}/league-board"]
    for run in leagues.runs.values():
        pages += [
            f"{API}/public/competitions/{run.competition}{p}"
            for p in ("", "/teams", "/games", "/standings", "/player-stats")
        ]
    for page in pages:
        response = c.get(page, headers=w.public)
        assert response.status_code in (200, 404), (page, response.text)
        assert w.kid_names[0] not in response.text, page
    # A child has no login of their own, so cannot buy: the sale above went through the parent.
    assert c.post(f"{API}/auth/sign-in", headers=w.public, json={"email": w.kid_names[0], "password": "x", "audience": "client", "client_kind": "mobile"}).status_code in (401, 422)  # fmt: skip


@pytest.mark.xfail(
    strict=True,
    reason="Nothing stops staff giving a minor their own email and opting it into "
    "marketing (engagement has no minor rule); only the default of no opt-in protects children",
)
def test_e_a_minor_cannot_be_opted_into_marketing(client_module, w):
    c, teen = client_module, w.kids[1]
    address = f"teen-{uuid4().hex[:6]}@{w.mail}"
    ok(
        c.patch(f"{API}/clients/{teen}", headers=w.owner, json={"emails": [{"email": address, "is_primary": True}]}),
        200,
    )
    verify_email(w.tenant, teen, address)  # the address is confirmed, so only a minor rule could refuse
    put = c.put(f"{API}/clients/{teen}/communication-preferences", headers=w.owner, json={
        "note": "Asked at the desk", "changes": [{"channel": "email", "address": address, "topic": "email_campaigns", "is_subscribed": True}],
    })  # fmt: skip
    assert put.status_code == 422 and put.json()["code"] != "email-unverified", put.text


@pytest.mark.xfail(
    strict=True,
    reason="A minor with an email can be invited to the member portal like an adult, "
    "and a portal sign-in can buy; there is no 'children cannot buy' rule",
)
def test_e_a_minor_cannot_get_a_buying_login(client_module, w):
    c, teen = client_module, w.kids[1]
    client = ok(c.get(f"{API}/clients/{teen}", headers=w.owner), 200)
    address = client.get("primary_email") or f"teen2-{uuid4().hex[:6]}@{w.mail}"
    if not client.get("primary_email"):
        ok(
            c.patch(
                f"{API}/clients/{teen}", headers=w.owner, json={"emails": [{"email": address, "is_primary": True}]}
            ),
            200,
        )
    invited = c.post(f"{API}/clients/{teen}/portal-access/invite", headers=w.owner, json={"email": address})
    assert invited.status_code in (403, 409, 422), invited.text


# --- f. the front desk ---------------------------------------------------------------------------------------


def test_f_desk_checks_in_takes_a_walk_in_rental_with_payment_and_refunds_it(client_module, w):
    c, day = client_module, MON + timedelta(days=3)
    checked = ok(c.post(f"{API}/check-ins", headers=w.desk, json={"client_id": w.member, "location_id": w.location, "channel": "staff_window"}))  # fmt: skip
    assert checked["check_in"]["result"] == "granted"
    walk_in = ok(c.post(f"{API}/clients", headers=w.desk, json={"first_name": "Drop", "last_name": f"In-{uuid4().hex[:4]}", "home_location_id": w.location}))  # fmt: skip
    rental = ok(rent(c, w, w.desk, "Badminton court", "Court 4", day, "10:00", "11:00", walk_in["id"]))
    assert rental["quote"]["total_minor"] == 1800  # a guest off-peak hour: $15 member price plus 20%
    [invoice] = rental["invoice_ids"]
    payment = ok(c.post(f"{API}/payments", headers=w.desk | key(), json={
        "client_id": walk_in["id"], "location_id": w.location, "amount_minor": 1800, "tender_kind": "cash", "invoice_id": invoice,
    }))  # fmt: skip
    assert ok(c.get(f"{API}/invoices/{invoice}", headers=w.desk), 200)["status"] == "paid"
    cancelled = ok(
        c.post(f"{API}/rentals/{rental['rental']['id']}/cancel", headers=w.desk, json={"reason": "client"}), 200
    )
    assert cancelled["reversed_minor"] == 1800 and cancelled["late_fee_minor"] == 0
    refund = c.post(f"{API}/payments/{payment['id']}/refunds", headers=w.desk | key(), json={"amount_minor": 1800, "reason": "Walk-in cancelled"})  # fmt: skip
    if refund.status_code == 403:  # front desk may not refund: a manager does it
        refund = c.post(f"{API}/payments/{payment['id']}/refunds", headers=w.manager | key(), json={"amount_minor": 1800, "reason": "Walk-in cancelled"})  # fmt: skip
        w.desk_cannot_refund = True
    assert refund.status_code == 201, refund.text


# --- g. pricing ----------------------------------------------------------------------------------------------


def preview(c, w, client_id: str, day: date, start: str, end: str, sport: str = "Badminton court") -> dict:
    return ok(c.post(f"{API}/rentals/preview", headers=w.desk, json={
        "location_id": w.location, "rental_type_id": w.types[sport], "client_id": client_id,
        "resources": [{"resource_id": w.courts["Court 2" if sport == "Volleyball court" else "Court 1"]}], "starts_at": at(day, start), "ends_at": at(day, end),
        "charge": {"decision": "bill", "rental_rate_id": w.rates[sport]},
    }), 200)["quote"]  # fmt: skip


def test_g_peak_and_off_peak_in_the_location_zone_with_a_straddling_booking(client_module, w):
    c, saturday, walk_in = client_module, MON + timedelta(days=12), w.guest
    # Guest (non-member) prices, the owner's member prices plus the assumed 20%: badminton and pickleball $30 peak
    # (18:00-22:00 Chicago), $18 off-peak; volleyball $48 at any hour (the owner's $40 is flat).
    assert preview(c, w, walk_in, PDAY, "10:00", "11:00")["subtotal_minor"] == 1800
    assert preview(c, w, walk_in, PDAY, "18:00", "19:00")["subtotal_minor"] == 3000
    straddle = preview(c, w, walk_in, PDAY, "17:00", "19:00")  # one hour each side of 18:00 local
    assert sorted(line["unit_amount_minor"] for line in straddle["lines"]) == [1800, 3000]
    assert straddle["subtotal_minor"] == 4800
    assert preview(c, w, walk_in, saturday, "19:00", "20:00")["subtotal_minor"] == 3000  # peak every day
    assert (
        preview(c, w, walk_in, PDAY, "08:00", "09:00", "Pickleball court")["subtotal_minor"] == 1800
    )  # no morning price
    assert preview(c, w, walk_in, PDAY, "19:00", "20:00", "Pickleball court")["subtotal_minor"] == 3000
    assert preview(c, w, walk_in, PDAY, "19:00", "20:00", "Volleyball court")["subtotal_minor"] == 4800
    assert preview(c, w, walk_in, PDAY, "10:00", "11:00", "Volleyball court")["subtotal_minor"] == 4800
    slots = ok(c.get(f"{API}/public/rental-availability?rental_type_id={w.types['Badminton court']}&on={PDAY.isoformat()}"
                     f"&length_min=60&resource_id={w.courts['Court 4']}", headers=w.public), 200)["data"]  # fmt: skip
    by_start = {datetime.fromisoformat(s["starts_at"].replace("Z", "+00:00")).astimezone(ZONE).strftime("%H:%M"): s["price_minor"] for s in slots}  # fmt: skip
    assert by_start["06:00"] == 1800 and by_start["18:00"] == 3000 and by_start["22:00"] == 1800
    assert by_start["02:00"] == 1800 and by_start["22:30"] == 1800  # open 24 hours


def test_g_member_prices(client_module, w):
    c = client_module
    assert preview(c, w, w.member, PDAY, "10:00", "11:00")["subtotal_minor"] == 1500  # owner: $15 off-peak
    assert preview(c, w, w.member, PDAY, "18:00", "19:00")["subtotal_minor"] == 2500  # owner: $25 peak
    assert preview(c, w, w.member, PDAY, "08:00", "09:00", "Pickleball court")["subtotal_minor"] == 1500
    assert preview(c, w, w.member, PDAY, "19:00", "20:00", "Pickleball court")["subtotal_minor"] == 2500
    assert preview(c, w, w.member, PDAY, "19:00", "20:00", "Volleyball court")["subtotal_minor"] == 4000  # flat
    assert preview(c, w, w.member, PDAY, "10:00", "11:00", "Volleyball court")["subtotal_minor"] == 4000


# --- h. cancellation and no-show -----------------------------------------------------------------------------


def test_h_cancellation_cut_off_late_fee_and_what_happens_to_the_payment(client_module, w):
    c = client_module
    payer = w.guest
    far = ok(rent(c, w, w.desk, "Pickleball court", "Court 2", MON + timedelta(days=4), "14:00", "15:00", payer))
    paid = far["quote"]["subtotal_minor"]
    assert paid == 1800  # a walk-in guest: the guest off-peak price (members pay 1500, test_g_member_prices)
    ok(c.post(f"{API}/payments", headers=w.desk | key(), json={"client_id": payer, "location_id": w.location,
         "amount_minor": paid, "tender_kind": "card", "method_token": "tok_card_ok", "invoice_id": far["invoice_ids"][0]}))  # fmt: skip
    result = ok(c.post(f"{API}/rentals/{far['rental']['id']}/cancel", headers=w.desk, json={"reason": "client"}), 200)
    assert (result["reversed_minor"], result["late_fee_minor"]) == (paid, 0)
    balance = ok(c.get(f"{API}/clients/{payer}/account-credit", headers=w.owner), 200)
    assert balance["credit_minor"] == paid  # paid card money became credit
    soon = NOW + timedelta(hours=3)
    start = soon.replace(minute=0, second=0, microsecond=0)
    if start.hour >= 22:  # both hour-long bookings below stay on one local date, still inside the 24-hour cut-off
        start = (start + timedelta(days=1)).replace(hour=1)
    late = ok(rent(c, w, w.desk, "Pickleball court", "Court 1", start.date(), start.strftime("%H:%M"),
                   (start + timedelta(hours=1)).strftime("%H:%M"), payer))  # fmt: skip
    charged = late["quote"]["subtotal_minor"]
    result = ok(c.post(f"{API}/rentals/{late['rental']['id']}/cancel", headers=w.desk, json={"reason": "client"}), 200)
    assert result["late_fee_minor"] == charged // 2  # 50% inside the 24-hour cut-off
    waive = ok(rent(c, w, w.desk, "Pickleball court", "Court 1", start.date(), (start + timedelta(hours=1)).strftime("%H:%M"),
                    (start + timedelta(hours=2)).strftime("%H:%M"), payer))  # fmt: skip
    assert (
        c.post(
            f"{API}/rentals/{waive['rental']['id']}/cancel", headers=w.desk, json={"waive_late_fee": True}
        ).status_code
        == 403
    )
    assert ok(c.post(f"{API}/rentals/{waive['rental']['id']}/cancel", headers=w.manager, json={"waive_late_fee": True}), 200)["late_fee_minor"] == 0  # fmt: skip


@pytest.mark.xfail(
    strict=True,
    reason="No no-show for a court rental: no mark, no fee and no rule; only shared "
    "booking participants carry a no_show attendance, with no money attached",
)
def test_h_no_show_rule(client_module):
    paths = client_module.get("/api/v1/openapi.json").json()["paths"]
    assert any("rentals" in p and "no-show" in p for p in paths)


# --- i. utilisation and revenue ------------------------------------------------------------------------------


def _report(c, w, key_: str, **params) -> dict:
    run = ok(c.post(f"{API}/report-runs", headers=w.owner, json={"report_key": key_, "params": {"location_ids": [w.location]} | params}), 200)  # fmt: skip
    assert run["status"] == "succeeded", run
    rows = ok(c.get(f"{API}/report-runs/{run['id']}/rows", headers=w.owner), 200)
    return run | {"rows": rows["data"]}


def test_i_daily_and_monthly_court_utilisation_and_revenue(client_module, w):
    c, day = client_module, MON + timedelta(days=7)
    ok(rent(c, w, w.desk, "Badminton court", "Court 1", day, "10:00", "12:00"))
    ok(rent(c, w, w.desk, "Volleyball court", "Court 2", day, "18:00", "19:00"))
    daily = _report(c, w, "resource_utilization", from_on=day.isoformat(), to_on=day.isoformat())
    by = {r["resource_name"]: r for r in daily["rows"]}
    # Changeover buffers count as held time: one volleyball hour holds Court 2 for 1h20 (1.33 h).
    assert by["Court 1"]["held_hours"] == 2 and by["Court 2"]["held_hours"] == 1.33
    assert by["Court 1"]["open_hours"] is None  # opening hours alone give no utilisation (see the xfail below)
    # Workaround: an availability window per court matching the opening hours.
    for court in cirqt.COURTS:
        ok(c.post(f"{API}/resources/{w.courts[court]}/availability-windows", headers=w.manager, json={
            "starts_on": TODAY.isoformat(), "weekdays": [1, 2, 3, 4, 5, 6, 7], "start_time": "00:00", "end_time": "24:00",
        }))  # fmt: skip
    daily = _report(c, w, "resource_utilization", from_on=day.isoformat(), to_on=day.isoformat())
    by = {r["resource_name"]: r for r in daily["rows"]}
    assert by["Court 1"]["open_hours"] == 24 and by["Court 1"]["utilization_pct"] == 8.3  # 2 of 24 hours
    assert by["Court 4"]["utilization_pct"] in (0, 0.0, None) or by["Court 4"]["held_hours"] == 0
    first = day.replace(day=1)
    last = (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    monthly = _report(c, w, "resource_utilization", from_on=first.isoformat(), to_on=last.isoformat())
    assert {r["resource_name"] for r in monthly["rows"]} >= set(cirqt.COURTS)
    assert all(0 <= (r["utilization_pct"] or 0) <= 100 for r in monthly["rows"])
    revenue = _report(c, w, "revenue_summary", from_on=first.isoformat(), to_on=last.isoformat())
    rentals = next(r for r in revenue["rows"] if "rental" in (r["revenue_category"] or "").lower())
    assert rentals["net_minor"] >= 2 * 1500 + 4000  # at least today's two bookings, at member prices


@pytest.mark.xfail(
    strict=True,
    reason="The utilisation report measures open time only from per-resource availability "
    "windows; the location's opening hours (which booking and online availability use) are ignored",
)
def test_i_utilisation_from_opening_hours(client_module, w):
    fresh = cirqt.build(slug=f"cirqt-{uuid4().hex[:8]}", name="CIRQT hours")
    tenant = SimpleNamespace(id=fresh["tenant_id"], slug=fresh["slug"])
    owner = login(client_module, tenant, f"owner@{fresh['domain']}", cirqt.PASSWORD)
    [badminton] = [
        t
        for t in ok(client_module.get(f"{API}/rental-types", headers=owner), 200)["data"]
        if t["name"] == "Badminton court"
    ]
    ok(client_module.post(f"{API}/rentals", headers=owner | key(), json={
        "location_id": badminton["location_id"], "rental_type_id": badminton["id"],
        "client_id": ok(client_module.get(f"{API}/clients", headers=owner), 200)["data"][0]["id"],
        "resources": [{"resource_id": badminton["resource_ids"][0]}], "starts_at": at(MON, "10:00"),
        "ends_at": at(MON, "11:00"), "charge": {"decision": "no_charge"},
    }))  # fmt: skip
    run = ok(client_module.post(f"{API}/report-runs", headers=owner, json={"report_key": "resource_utilization",
             "params": {"from_on": MON.isoformat(), "to_on": MON.isoformat()}}), 200)  # fmt: skip
    rows = ok(client_module.get(f"{API}/report-runs/{run['id']}/rows", headers=owner), 200)["data"]
    assert rows and all(r["open_hours"] == 17 for r in rows)


def data(response) -> list:
    body = ok(response, 200)
    return body if isinstance(body, list) else body["data"]


# --- j. unmanned: a newcomer signs up, pays the membership fee and books a court with no staff ---------------


NOTICE = "Your entry code will be sent once our staff have confirmed your age. This is a one-time check."


def newcomer(c, w, mailbox) -> tuple[dict, dict]:
    """Self sign-up with a declared birth date (no staff step: the seed switches self sign-up on)."""
    body = {
        "location_id": w.location,
        "email": f"new-{uuid4().hex[:6]}@{w.mail}",
        "first_name": "Nova",
        "last_name": "Newcomer",
        "birth_on": "1994-06-07",
        "birth_on_declared": True,
    }
    mailbox.clear()
    assert c.post(f"{API}/public/portal-signups", headers=w.public, json=body).status_code == 202
    signed = ok(c.post(f"{API}/public/portal-signups/confirm", headers=w.public,
                       json={"token": link_token(mailbox[-1]), "client_kind": "mobile"}), 200)  # fmt: skip
    me = {"Authorization": f"Bearer {signed['access_token']}"}
    [mine] = data(c.get(f"{API}/portal/clients", headers=me))
    return me, mine


def test_j_a_newcomer_goes_from_finding_cirqt_to_a_paid_court_with_no_staff(client_module, w, mailbox):
    c, day = client_module, MON + timedelta(days=8)
    assert w.location in {x["id"] for x in data(c.get(f"{API}/public/locations", headers=w.public))}
    assert "Adult monthly" in {p["name"] for p in data(c.get(f"{API}/public/membership-plans", headers=w.public))}
    offered = {t["name"] for t in data(c.get(f"{API}/public/rental-types", headers=w.public))}
    assert {"Badminton court", "Pickleball court", "Volleyball court"} <= offered
    me, mine = newcomer(c, w, mailbox)
    # The declared date lets an adult book and pay at once; the entry code waits for staff's one-time check.
    assert mine["age_confirmed"] is False
    assert mine["entry_code_notice"] == f"{NOTICE} Questions? Call us on {cirqt.PHONE}."
    member = ok(c.post(f"{API}/portal/membership-contracts", headers=me | key(), json={
        "client_id": mine["id"], "location_id": w.location, "membership_plan_id": w.plans["Adult monthly"],
        "method_token": "tok_card_ok",
    }))  # fmt: skip
    assert member["status"] == "active" and member["payment_status"] == "succeeded"
    court = {
        "rental_type_id": w.types["Pickleball court"],
        "client_id": mine["id"],
        "resource_id": w.courts["Court 4"],
        "starts_at": at(day, "08:00"),
        "ends_at": at(day, "09:00"),
    }
    checkout = ok(c.post(f"{API}/portal/rentals", headers=me, json=court))
    assert checkout["entry_code_notice"].startswith(NOTICE)  # shown before payment
    paid = ok(c.post(f"{API}/portal/rentals/{checkout['rental']['id']}/confirm", headers=me | key(),
                     json={"provider_payment_token": "tok_card_ok"}), 200)  # fmt: skip
    assert paid["rental"]["status"] == "confirmed" and paid["payment_status"] == "succeeded"
    # The person cannot confirm or change their own date.
    locked = c.patch(f"{API}/portal/clients/{mine['id']}", headers=me, json={"birth_on": "1992-08-09"})
    assert (locked.status_code, locked.json()["code"]) == (422, "field-locked"), locked.text


def test_j_staff_confirm_a_newcomers_age_once_and_the_confirmed_event_fires(client_module, w, mailbox):
    c = client_module
    me, mine = newcomer(c, w, mailbox)
    queue = data(c.get(f"{API}/client-age-reviews", headers=w.desk))
    assert mine["id"] in {r["id"] for r in queue}
    confirmed = ok(c.post(f"{API}/clients/{mine['id']}/age-confirmation", headers=w.desk, json={}), 200)
    assert confirmed["age_confirmed"] is True and confirmed["age_confirmed_at"]
    with tenant_session(w.tenant.id) as session:
        fired = session.scalars(select(OutboxEvent).where(OutboxEvent.event_type == "clients.client.age_confirmed",
                                                          OutboxEvent.aggregate_id == UUID(mine["id"]))).all()  # fmt: skip
    assert len(fired) == 1
    [after] = data(c.get(f"{API}/portal/clients", headers=me))
    assert after["age_confirmed"] is True and after["entry_code_notice"] is None
    assert mine["id"] not in {r["id"] for r in data(c.get(f"{API}/client-age-reviews", headers=w.desk))}
    # Seeded adults were confirmed by the owner through the same action.
    assert ok(c.get(f"{API}/clients/{w.member}", headers=w.desk), 200)["age_confirmed"] is True


# --- k. bulk booking -----------------------------------------------------------------------------------------


def test_k_staff_bulk_book_several_courts_for_several_weeks_in_one_go(client_module, w):
    c, day = client_module, MON + timedelta(days=10)
    made = ok(c.post(f"{API}/rentals", headers=w.manager | key(), json={
        "location_id": w.location, "rental_type_id": w.types["Pickleball court"], "client_id": w.others[2],
        "resources": [{"resource_id": w.courts["Court 1"]}, {"resource_id": w.courts["Court 4"]}],
        "starts_at": at(day, "07:00"), "ends_at": at(day, "08:00"),
        "charge": {"decision": "bill", "rental_rate_id": w.rates["Pickleball court"], "invoice_routing": "new_single"},
        "recurrence": {"pattern": "weekly", "range_type": "count", "occurrence_limit": 4},
    }))  # fmt: skip
    assert made["created_count"] == 4 and len(made["invoice_ids"]) == 1
    assert conflict(rent(c, w, w.desk, "Badminton court", "Court 4", day + timedelta(days=21), "07:00", "08:00"))


def test_k_a_club_holds_the_same_weekly_prime_slot_at_15_percent_off(client_module, w):
    """Bulk for CIRQT: a club or coach keeps one weekly slot. Staff book it as a recurring rental on the second
    rate the seed made, "Weekly club" (the same prices with a 15% discount rule). There is no contract object."""
    c, day = client_module, MON + timedelta(days=11)  # a Friday
    rates = {
        r["name"]: r["id"]
        for r in data(c.get(f"{API}/rental-types/{w.types['Badminton court']}/rates", headers=w.owner))
    }
    made = ok(c.post(f"{API}/rentals", headers=w.manager | key(), json={
        "location_id": w.location, "rental_type_id": w.types["Badminton court"], "client_id": w.others[3],
        "resources": [{"resource_id": w.courts["Court 1"]}], "starts_at": at(day, "19:00"), "ends_at": at(day, "20:00"),
        "charge": {"decision": "bill", "rental_rate_id": rates["Weekly club"], "invoice_routing": "new_single"},
        "recurrence": {"pattern": "weekly", "range_type": "count", "occurrence_limit": 8},
    }))  # fmt: skip
    assert made["created_count"] == 8 and len(made["invoice_ids"]) == 1
    invoice = ok(c.get(f"{API}/invoices/{made['invoice_ids'][0]}", headers=w.manager), 200)
    assert invoice["total_minor"] == 8 * 2125, invoice  # the club's holder is a member: $25 member prime less 15%
    assert conflict(rent(c, w, w.desk, "Badminton court", "Court 1", day + timedelta(days=49), "19:30", "20:30"))


@pytest.mark.xfail(
    strict=True,
    reason="Online (portal) rental is one court and one occurrence per checkout: no "
    "recurrence and no second court, so a member books several courts or weeks one checkout at a time",
)
def test_k_a_member_bulk_books_online(client_module, w):
    day = MON + timedelta(days=11)
    response = client_module.post(f"{API}/portal/rentals", headers=w.member_portal, json={
        "rental_type_id": w.types["Badminton court"], "client_id": w.member, "resource_id": w.courts["Court 1"],
        "resource_ids": [w.courts["Court 1"], w.courts["Court 4"]], "starts_at": at(day, "19:00"),
        "ends_at": at(day, "20:00"), "recurrence": {"pattern": "weekly", "range_type": "count", "occurrence_limit": 4},
    })  # fmt: skip
    assert response.status_code == 201 and response.json().get("created_count") == 8, response.text


# --- l. coaching: a paid lesson with a coach on a court ------------------------------------------------------


def payees(c, w) -> dict:
    return {p["display_name"]: p for p in data(c.get(f"{API}/staff-payees", headers=w.owner))}


def lesson_setup(c, w):
    lesson = next(t["id"] for t in data(c.get(f"{API}/reservation-types?location_id={w.location}", headers=w.owner))
                  if t["name"] == "Private lesson")  # fmt: skip
    plan = next(p["id"] for p in data(c.get(f"{API}/package-plans", headers=w.owner)) if p["name"] == "One lesson")
    return lesson, plan


def coached_session(c, w, day: date, start: str, end: str, court: str, coach: str = "Rowan (staff coach)") -> str:
    lesson, _ = lesson_setup(c, w)
    booked = ok(c.post(f"{API}/bookings", headers=w.owner, json={
        "location_id": w.location, "kind": "session", "reservation_type_id": lesson,
        "resources": [{"resource_id": payees(c, w)[coach]["resource_id"]}, {"resource_id": w.courts[court]}],
        "starts_at": at(day, start), "ends_at": at(day, end)}))  # fmt: skip
    return booked["booking"]["session"]["id"]


def buy_and_enrol(c, w, headers, client_id: str, session_id: str) -> dict:
    _, plan = lesson_setup(c, w)
    bought = ok(c.post(f"{API}/portal/client-packages", headers=headers | key(), json={
        "package_plan_id": plan, "location_id": w.location, "client_id": client_id, "method_token": "tok_card_ok"}))  # fmt: skip
    return ok(c.post(f"{API}/portal/enrollments", headers=headers, json={
        "client_id": client_id, "session_id": session_id, "client_package_id": bought["id"]}))  # fmt: skip


def test_l_a_member_buys_and_books_a_coached_lesson_that_holds_the_court(client_module, w):
    c, day = client_module, TODAY + timedelta(days=6)  # portal lists sessions 30 days ahead by default
    session_id = coached_session(c, w, day, "08:00", "09:00", "Court 4")
    assert conflict(
        rent(c, w, w.desk, "Pickleball court", "Court 4", day, "08:30", "09:30")
    )  # the lesson holds the court
    assert buy_and_enrol(c, w, w.member_portal, w.member, session_id)["client_id"] == w.member


# --- m. kids: dropped off at coaching is fine; playing needs a parent on the booking ------------------------------


def test_m_a_parent_buys_a_lesson_for_a_child_and_drops_them_off(client_module, w):
    c, day = client_module, TODAY + timedelta(days=7)
    session_id = coached_session(c, w, day, "16:00", "17:00", "Court 1")
    assert buy_and_enrol(c, w, w.parent_portal, w.kids[0], session_id)["client_id"] == w.kids[0]


def test_m_online_a_parent_can_only_rent_a_court_in_their_own_name(client_module, w):
    """Online, a rental is for the signed-in person's own record only (portal rentals ignore guardianship), so a
    child cannot be put on a court alone from the portal; the parent books in their own name and brings the child."""
    day = MON + timedelta(days=12)
    body = {"rental_type_id": w.types["Badminton court"], "resource_id": w.courts["Court 4"],
            "starts_at": at(day, "15:00"), "ends_at": at(day, "16:00")}  # fmt: skip
    assert (
        client_module.post(
            f"{API}/portal/rentals", headers=w.parent_portal, json=body | {"client_id": w.kids[1]}
        ).status_code
        == 404
    )
    assert ok(client_module.post(f"{API}/portal/rentals", headers=w.parent_portal, json=body | {"client_id": w.parent}))


def test_m_a_child_cannot_be_booked_on_a_court_without_a_parent(client_module, w):
    day = MON + timedelta(days=12)
    response = rent(client_module, w, w.desk, "Badminton court", "Court 4", day, "17:00", "18:00", w.kids[1])
    assert (response.status_code, response.json()["code"]) == (422, "minor-cannot-hold-rental"), response.text
    with_parent = rent(client_module, w, w.desk, "Badminton court", "Court 4", day, "17:00", "18:00", w.parent,
                       parties=[{"client_id": w.kids[1]}])  # fmt: skip
    assert with_parent.status_code == 201, with_parent.text  # the parent holds and pays; the child plays


def _portal_child(c, w, born: str) -> str:
    parent_of = next(t for t in ok(c.get(f"{API}/portal/relationship-types", headers=w.parent_portal), 200)
                     if t["code"] == "parent_of")  # fmt: skip
    return ok(c.post(f"{API}/portal/dependents", headers=w.parent_portal, json={
        "relationship_type_id": parent_of["id"], "first_name": "Remy", "last_name": "Added", "birth_on": born, "birth_on_declared": True}))["id"]  # fmt: skip


def test_m_a_child_the_parent_added_online_never_holds_a_court(client_module, w):
    """The parent manages a child they add in the portal (`manager`, not `guardian`): the server's age check,
    not the acting authority, keeps the court in the parent's name."""
    c, day = client_module, MON + timedelta(days=13)
    kid = _portal_child(c, w, (TODAY - timedelta(days=9 * 365)).isoformat())
    acting = next(x for x in data(c.get(f"{API}/portal/clients", headers=w.parent_portal)) if x["id"] == kid)
    assert (acting["authority"], acting["is_adult"], acting["is_my_ward"]) == ("manager", False, True)
    body = {"rental_type_id": w.types["Badminton court"], "resource_id": w.courts["Court 4"],
            "starts_at": at(day, "15:00"), "ends_at": at(day, "16:00")}  # fmt: skip
    alone = c.post(f"{API}/portal/rentals", headers=w.parent_portal, json=body | {"client_id": kid})
    assert (alone.status_code, alone.json()["code"]) == (422, "minor-cannot-hold-rental"), alone.text
    ok(c.post(f"{API}/portal/rentals", headers=w.parent_portal,
              json=body | {"client_id": w.parent, "player_client_ids": [kid]}))  # fmt: skip


def test_m_a_dependant_with_no_birth_date_cannot_hold_a_court_online(client_module, w):
    """Dependants added before birth dates were required: online an unknown date is not an adult."""
    c, day = client_module, MON + timedelta(days=13)
    kid = _portal_child(c, w, "2016-01-01")
    with tenant_session(w.tenant.id) as session:
        session.get(Client, kid).birth_on = None
    body = {"rental_type_id": w.types["Badminton court"], "resource_id": w.courts["Court 4"], "client_id": kid,
            "starts_at": at(day, "17:00"), "ends_at": at(day, "18:00")}  # fmt: skip
    refused = c.post(f"{API}/portal/rentals", headers=w.parent_portal, json=body)
    assert (refused.status_code, refused.json()["code"]) == (422, "birth-date-required"), refused.text


# --- n. coaches: one on staff, one independent ----------------------------------------------------------------


def test_n_staff_coach_and_independent_coach(client_module, w):
    c = client_module
    found = payees(c, w)
    rowan, ines = found["Rowan (staff coach)"], found["Ines (independent coach)"]
    assert rowan["staff_user_id"] and ines["staff_user_id"] is None  # Ines has no sign-in
    rates = lambda p: data(c.get(f"{API}/staff-payees/{p['id']}/pay-rates", headers=w.owner))  # noqa: E731
    assert any(r.get("rate_60_minor") == 3000 for r in rates(rowan)), rates(rowan)
    # Ines is engaged as an independent coach on a 70% revenue share; Rowan has no engagement row, so he is staff.
    terms = lambda p: ok(c.get(f"{API}/staff-payees/{p['id']}/engagements", headers=w.owner), 200)  # noqa: E731
    assert [t["engagement"] for t in terms(ines)] == ["independent"] and terms(rowan) == []
    shares = data(c.get(f"{API}/coach-share-rules?staff_payee_id={ines['id']}", headers=w.owner))
    assert [float(r["coach_share_pct"]) for r in shares] == [70]
    coach = login(c, w.tenant, f"coach@{w.mail}", cirqt.PASSWORD, "staff")
    assert ok(c.get(f"{API}/me", headers=coach), 200)["linked_resource_id"] == rowan["resource_id"]  # his own column
    # Signed in, the coach sees his sessions, his shifts, the payee names and the client list, but no pay rates
    # (his own included) and no payroll runs.
    seen = {
        p: c.get(f"{API}{p}", headers=coach).status_code
        for p in (
            f"/staff-payees/{rowan['id']}/sessions",
            "/my-shifts",
            "/staff-payees",
            "/clients?limit=5",
            f"/staff-payees/{rowan['id']}/pay-rates",
            f"/staff-payees/{ines['id']}/pay-rates",
            "/payroll-runs",
            "/coach-share-rules",
            f"/staff-payees/{ines['id']}/engagements",
        )
    }
    assert list(seen.values()) == [200, 200, 200, 200, 403, 403, 403, 403, 403], seen


def test_n_the_coaches_pay_shows_on_the_time_clock_and_the_payroll_preview(client_module, w):
    """The owner pays coaches per session: Rowan $30 a one-hour lesson (assumed rate), and his only clock job is
    for non-coaching work ("Upkeep and front desk (not lessons)", $15 an hour, assumed); Ines keeps 70% of the lesson
    money. Rowan clocks the opening hour and, by mistake, through his lesson as well; Ines teaches a paid lesson. The
    next day's payroll preview pays his lesson once: clocked minutes inside a paid session are not counted."""
    c, day = client_module, TODAY + timedelta(days=3)
    found = payees(c, w)
    rowan, ines = found["Rowan (staff coach)"], found["Ines (independent coach)"]
    coach = login(c, w.tenant, f"coach@{w.mail}", cirqt.PASSWORD, "staff")
    clock_state = ok(c.get(f"{API}/time-entries/current?location_id={w.location}", headers=coach), 200)
    [job] = [j for j in clock_state["job_classifications"] if j["name"] == cirqt.UPKEEP_JOB]
    rates = data(c.get(f"{API}/staff-users/{rowan['staff_user_id']}/hourly-rates", headers=w.owner))
    assert [(r["job_classification_id"], r["rate_minor"]) for r in rates] == [(job["id"], 1500)]
    _, plan = lesson_setup(c, w)
    lessons = []
    for name, start, end in (("Rowan (staff coach)", "09:00", "10:00"), ("Ines (independent coach)", "11:00", "12:00")):
        session_id = coached_session(c, w, day, start, end, "Court 1", coach=name)
        bought = ok(c.post(f"{API}/portal/client-packages", headers=w.member_portal | key(), json={
            "package_plan_id": plan, "location_id": w.location, "client_id": w.member, "method_token": "tok_card_ok"}))  # fmt: skip
        enrolled = ok(c.post(f"{API}/enrollments", headers=w.owner, json={
            "session_id": session_id, "client_id": w.member, "client_package_id": bought["id"]}))  # fmt: skip
        lessons.append((session_id, enrolled["id"]))
    with clock.freeze(datetime.combine(day + timedelta(days=1), time(12), ZONE)):
        owner = login(c, w.tenant, f"owner@{w.mail}", cirqt.PASSWORD, "staff")  # a token minted on the frozen clock
        ok(c.post(f"{API}/time-entries", headers=owner, json={
            "staff_user_id": rowan["staff_user_id"], "location_id": w.location, "job_classification_id": job["id"],
            "clock_in_at": at(day, "07:00"), "clock_out_at": at(day, "08:00"), "edit_reason": "Opening the doors"}))  # fmt: skip
        ok(c.post(f"{API}/time-entries", headers=owner, json={
            "staff_user_id": rowan["staff_user_id"], "location_id": w.location, "job_classification_id": job["id"],
            "clock_in_at": at(day, "08:30"), "clock_out_at": at(day, "10:00"), "edit_reason": "Clocked through the lesson"}))  # fmt: skip
        for session_id, enrollment_id in lessons:
            ok(c.put(f"{API}/sessions/{session_id}/attendance", headers=owner,
                     json={"marks": [{"enrollment_id": enrollment_id, "status": "attended"}]}), 200)  # fmt: skip
        run = ok(c.post(f"{API}/payroll-runs", headers=owner, json={
            "location_id": w.location, "period_starts_on": day.isoformat(), "period_ends_on": day.isoformat()}))  # fmt: skip
        statements = data(c.get(f"{API}/payroll-runs/{run['id']}/statements", headers=owner))
    pay = lambda field, *who: sum(s[field] for s in statements if {s["staff_payee_id"], s["staff_user_id"]} & set(who))  # noqa: E731
    assert pay("session_pay_minor", rowan["id"], rowan["staff_user_id"]) == 3000  # his lesson
    assert pay("hourly_pay_minor", rowan["id"], rowan["staff_user_id"]) == 2250  # 07:00-08:00 and 08:30-09:00 only
    # Ines is independent: her lesson is shared on her earnings ledger (next test), never paid through payroll.
    assert [s for s in statements if s["staff_payee_id"] == ines["id"]] == []


def test_n_the_independent_coach_earns_a_share_and_is_settled_by_payout_statement(client_module, w):
    """Ines keeps 70% of her lesson money. A paid one-lesson package ($50) and one lesson of a five-lesson package
    ($225, so $45 a lesson) each make an earning line when attended; refunding the single lesson reverses its line.
    The payout statement totals what is left, is approved and recorded as paid (no money moves in the product).
    Rowan, a staff coach, never earns a share and never appears on a payout."""
    from app.modules.memberships.tests.support import deliver_events

    c, day = client_module, TODAY + timedelta(days=4)
    found = payees(c, w)
    rowan, ines = found["Rowan (staff coach)"], found["Ines (independent coach)"]
    plans = {p["name"]: p["id"] for p in data(c.get(f"{API}/package-plans", headers=w.owner))}
    lessons = []
    for plan, start, end in (("One lesson", "13:00", "14:00"), ("Five lessons", "14:00", "15:00")):
        session_id = coached_session(c, w, day, start, end, "Court 2", coach="Ines (independent coach)")
        bought = ok(c.post(f"{API}/portal/client-packages", headers=w.member_portal | key(), json={
            "package_plan_id": plans[plan], "location_id": w.location, "client_id": w.member,
            "method_token": "tok_card_ok"}))  # fmt: skip
        enrolled = ok(c.post(f"{API}/enrollments", headers=w.owner, json={
            "session_id": session_id, "client_id": w.member, "client_package_id": bought["id"]}))  # fmt: skip
        lessons.append((session_id, enrolled["id"], bought["id"]))
    rowan_session = coached_session(c, w, day, "16:00", "17:00", "Court 3")
    rowan_pack = ok(c.post(f"{API}/portal/client-packages", headers=w.member_portal | key(), json={
        "package_plan_id": plans["One lesson"], "location_id": w.location, "client_id": w.member,
        "method_token": "tok_card_ok"}))  # fmt: skip
    rowan_place = ok(c.post(f"{API}/enrollments", headers=w.owner, json={
        "session_id": rowan_session, "client_id": w.member, "client_package_id": rowan_pack["id"]}))  # fmt: skip
    with clock.freeze(datetime.combine(day + timedelta(days=1), time(12), ZONE)):
        owner = login(c, w.tenant, f"owner@{w.mail}", cirqt.PASSWORD, "staff")
        every = lambda: data(c.get(f"{API}/coach-earnings?staff_payee_id={ines['id']}&limit=50", headers=owner))  # noqa: E731
        deliver_events()  # the earlier scenario's lesson lands on her ledger first
        before = {r["id"] for r in every()}
        earned = lambda: [r for r in every() if r["id"] not in before]  # noqa: E731
        for session_id, enrollment_id, _ in lessons:
            ok(c.put(f"{API}/sessions/{session_id}/attendance", headers=owner,
                     json={"marks": [{"enrollment_id": enrollment_id, "status": "attended"}]}), 200)  # fmt: skip
        deliver_events()

        def split(rows):
            return sorted(
                (r["kind"], r["gross_minor"], r["facility_share_minor"], r["coach_share_minor"]) for r in rows
            )

        assert split(earned()) == [("lesson", 4500, 1350, 3150), ("lesson", 5000, 1500, 3500)]
        member = ok(c.get(f"{API}/clients/{w.member}", headers=owner), 200)
        label = f"Lesson with {member['first_name']} {member['last_name'][0]}."  # first name and last initial only
        assert {r["description"] for r in earned()} == {label}
        # A refund of the single lesson starts with reversing its package charge: the line is reversed.
        single = ok(c.get(f"{API}/client-packages/{lessons[0][2]}", headers=owner), 200)
        ok(c.post(f"{API}/charges/{single['charge_id']}/reverse", headers=owner | key(), json={"reason": "Refund"}))
        deliver_events()
        assert split(earned()) == [("lesson", 4500, 1350, 3150), ("lesson", 5000, 1500, 3500),
                                   ("reversal", -5000, -1500, -3500)]  # fmt: skip
        assert data(c.get(f"{API}/coach-earnings?staff_payee_id={rowan['id']}", headers=owner)) == []
        period = {"location_id": w.location, "period_starts_on": day.isoformat(), "period_ends_on": day.isoformat()}
        made = ok(c.post(f"{API}/coach-payouts", headers=owner, json=period))["data"]
        assert [p["staff_payee_id"] for p in made] == [ines["id"]]  # Rowan is never on a payout
        [payout] = made
        # Every unpaid line up to the end date, earlier ones too; the refund's reversal is dated the refund day (the
        # next day), so it waits for the next statement.
        unpaid = [r for r in every() if r["earned_on"] <= day.isoformat()]
        assert (payout["line_count"], payout["gross_minor"], payout["coach_share_minor"]) == (
            len(unpaid), sum(r["gross_minor"] for r in unpaid), sum(r["coach_share_minor"] for r in unpaid))  # fmt: skip
        assert payout["gross_minor"] == payout["facility_share_minor"] + payout["coach_share_minor"]
        url = f"{API}/coach-payouts/{payout['id']}"
        assert ok(c.post(f"{url}/approve", headers=owner), 200)["status"] == "approved"
        paid = ok(c.post(f"{url}/paid", headers=owner, json={
            "paid_on": (day + timedelta(days=1)).isoformat(), "payment_method": "bank_transfer",
            "payment_reference": "CIRQT-INES-1"}), 200)  # fmt: skip
        assert (paid["status"], paid["coach_share_minor"]) == ("paid", payout["coach_share_minor"])
        # Paid is final; the refund lands on the next statement as a correction.
        later = period | {
            "period_starts_on": (day + timedelta(days=1)).isoformat(),
            "period_ends_on": (day + timedelta(days=1)).isoformat(),
        }
        [correction] = ok(c.post(f"{API}/coach-payouts", headers=owner, json=later))["data"]
        assert (correction["line_count"], correction["coach_share_minor"]) == (1, -3500)
        # Rowan's lesson the same day goes through payroll, as a staff coach's always has.
        ok(c.put(f"{API}/sessions/{rowan_session}/attendance", headers=owner,
                 json={"marks": [{"enrollment_id": rowan_place["id"], "status": "attended"}]}), 200)  # fmt: skip
        deliver_events()
        assert data(c.get(f"{API}/coach-earnings?staff_payee_id={rowan['id']}", headers=owner)) == []
        run = ok(c.post(f"{API}/payroll-runs", headers=owner, json=period))
        statements = data(c.get(f"{API}/payroll-runs/{run['id']}/statements", headers=owner))
    assert {s["staff_payee_id"] for s in statements} & {rowan["id"], ines["id"]} == {rowan["id"]}
