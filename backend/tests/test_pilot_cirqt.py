"""Pilot fit check for CIRQT (docs/status/pilot-fit-cirqt.md): the facility from seeds/cirqt.py, built under a
fresh slug, driven through the API as its owner, manager, front desk, league manager, a member and a parent.

Each test asserts what CIRQT needs. Where the product cannot do it today the test is `xfail(strict=True)` with
the reason, so it turns red the day the gap closes. Product code is not changed by this file.
"""

from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError

from app.core.db.session import tenant_session
from app.modules.clients.models import Client
from app.modules.memberships.models import MembershipPlan
from app.modules.platform.models import Location
from app.modules.resources.models import Resource
from app.modules.scheduling.models import ResourceHold
from conftest import _run_schedule_job, link_token, login, verify_email
from seeds import cirqt

API = "/api/v1"
ZONE = ZoneInfo(cirqt.ZONE)
TODAY = datetime.now(ZONE).date()
MON = TODAY + timedelta(days=7 - TODAY.weekday() + 21)  # a Monday three to four weeks out
LEAGUE_FROM, LEAGUE_TO = MON + timedelta(days=14), MON + timedelta(days=35)
BLOCKED_TUESDAY = MON + timedelta(days=15)
PDAY = MON + timedelta(days=9)  # a Wednesday with nothing booked: the pricing previews


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
    return SimpleNamespace(
        tenant=tenant, mail=mail, location=str(location.id), courts=courts, member=str(member.id),
        parent=str(parent.id), kids=[str(k.id) for k in kids], kid_names=[k.first_name for k in kids], plans=plans,
        types={n: t["id"] for n, t in types.items()}, rates={n: t["online_rental_rate_id"] for n, t in types.items()},
        others=walk_in_pool, owner=owner, manager=sign("manager"), desk=sign("front-desk"),
        league=sign("league-admin"), member_portal=sign("member", "client"), parent_portal=sign("parent", "client"),
        public={"X-Tenant-Slug": tenant.slug},
    )  # fmt: skip


@pytest.fixture(scope="module")
def client_module():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


def rent(c, w, headers, sport: str, court: str, day: date, start: str, end: str, client_id: str | None = None):
    return c.post(f"{API}/rentals", headers=headers | key(), json={
        "location_id": w.location, "rental_type_id": w.types[sport], "client_id": client_id or w.others[0],
        "resources": [{"resource_id": w.courts[court]}], "starts_at": at(day, start), "ends_at": at(day, end),
        "charge": {"decision": "bill", "rental_rate_id": w.rates[sport]},
    })  # fmt: skip


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
    """The manager blocks every court on one Tuesday league night; the league manager then generates and commits
    the badminton schedule (Tuesdays, one game per court) and the volleyball one (Thursdays, the two volleyball
    venues)."""
    c = client_module
    block = c.post(f"{API}/bookings", headers=w.manager, json={
        "location_id": w.location, "kind": "block", "block_kind": "unavailable", "title": "League night",
        "resources": [{"resource_id": w.courts[n]} for n in cirqt.COURTS],
        "starts_at": at(BLOCKED_TUESDAY, "18:00"), "ends_at": at(BLOCKED_TUESDAY, "22:00"),
    })  # fmt: skip
    competitions = {x["name"]: x for x in ok(c.get(f"{API}/competitions", headers=w.league), 200)["data"]}
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
    # The staff block is not the league's own: games the generator put on that night cannot be booked there.
    assert not [g for g in scheduled if _local_day(g["starts_at"]) == BLOCKED_TUESDAY]
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


@pytest.mark.xfail(
    strict=True,
    reason="A staff block on the courts is not a league reservation: the generator "
    "treats it as a clash and leaves those games unschedulable, so a league night cannot be blocked "
    "first and filled by the league scheduler later",
)
def test_c_league_fixtures_use_the_blocked_league_night(w, leagues):
    games = leagues.runs["Tuesday Badminton League"].games
    assert any(g["status"] == "scheduled" and _local_day(g["starts_at"]) == BLOCKED_TUESDAY for g in games)


# --- d. leagues: teams, fixtures, scores, standings ----------------------------------------------------------


def test_d_badminton_and_volleyball_leagues_score_and_rank(client_module, w, leagues):
    c = client_module
    for name, score in (("Tuesday Badminton League", (2, 1)), ("Thursday Volleyball League", (3, 1))):
        run = leagues.runs[name]
        teams = ok(c.get(f"{API}/competitions/{run.competition}/teams", headers=w.league), 200)
        assert len(teams if isinstance(teams, list) else teams["data"]) == 6
        game = next(g for g in run.games if g["status"] == "scheduled")
        result = ok(c.put(f"{API}/games/{game['id']}/result", headers=w.league,
                          json={"home": {"score": score[0]}, "away": {"score": score[1]}}), 200)  # fmt: skip
        assert result["home"]["outcome"] == "win" and result["away"]["outcome"] == "loss"
        standings = ok(c.get(f"{API}/competitions/{run.competition}/standings", headers=w.league), 200)
        rows = standings if isinstance(standings, list) else standings["data"]
        top = rows[0]
        assert top["competition_team_id"] == result["home"]["competition_team_id"]
        assert float(top["points"]) == 2.0 and top["wins"] == 1
        public = ok(c.get(f"{API}/public/competitions/{run.competition}/standings", headers=w.public), 200)
        assert public


@pytest.mark.xfail(
    strict=True,
    reason="A result is one integer score per side: no games or sets (badminton best of "
    "three to 21, volleyball sets to 25), so per-game points cannot be entered or validated",
)
def test_d_set_by_set_scores(client_module, w, leagues):
    game = next(g for g in leagues.runs["Tuesday Badminton League"].games if g["status"] == "scheduled")
    sets = {"home": {"score": 2, "sets": [21, 18, 21]}, "away": {"score": 1, "sets": [19, 21, 15]}}
    assert client_module.put(f"{API}/games/{game['id']}/result", headers=w.league, json=sets).status_code == 200


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
    assert rental["quote"]["total_minor"] == 2400
    [invoice] = rental["invoice_ids"]
    payment = ok(c.post(f"{API}/payments", headers=w.desk | key(), json={
        "client_id": walk_in["id"], "location_id": w.location, "amount_minor": 2400, "tender_kind": "cash", "invoice_id": invoice,
    }))  # fmt: skip
    assert ok(c.get(f"{API}/invoices/{invoice}", headers=w.desk), 200)["status"] == "paid"
    cancelled = ok(
        c.post(f"{API}/rentals/{rental['rental']['id']}/cancel", headers=w.desk, json={"reason": "client"}), 200
    )
    assert cancelled["reversed_minor"] == 2400 and cancelled["late_fee_minor"] == 0
    refund = c.post(f"{API}/payments/{payment['id']}/refunds", headers=w.desk | key(), json={"amount_minor": 2400, "reason": "Walk-in cancelled"})  # fmt: skip
    if refund.status_code == 403:  # front desk may not refund: a manager does it
        refund = c.post(f"{API}/payments/{payment['id']}/refunds", headers=w.manager | key(), json={"amount_minor": 2400, "reason": "Walk-in cancelled"})  # fmt: skip
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
    c, saturday, walk_in = client_module, MON + timedelta(days=12), w.others[-1]
    # Guest (non-member) prices: badminton $30 prime (18:00-22:00 Chicago), $24 outside; pickleball $14.40 mornings.
    assert preview(c, w, walk_in, PDAY, "10:00", "11:00")["subtotal_minor"] == 2400
    assert preview(c, w, walk_in, PDAY, "18:00", "19:00")["subtotal_minor"] == 3000
    straddle = preview(c, w, walk_in, PDAY, "17:00", "19:00")  # one hour each side of 18:00 local
    assert sorted(line["unit_amount_minor"] for line in straddle["lines"]) == [2400, 3000]
    assert straddle["subtotal_minor"] == 5400
    assert preview(c, w, walk_in, saturday, "19:00", "20:00")["subtotal_minor"] == 3000  # prime every day
    assert preview(c, w, walk_in, PDAY, "08:00", "09:00", "Pickleball court")["subtotal_minor"] == 1440
    assert (
        preview(c, w, walk_in, PDAY, "11:30", "12:30", "Pickleball court")["subtotal_minor"] == 720 + 1200
    )  # noon edge
    assert preview(c, w, walk_in, PDAY, "19:00", "20:00", "Volleyball court")["subtotal_minor"] == 4800
    slots = ok(c.get(f"{API}/public/rental-availability?rental_type_id={w.types['Badminton court']}&on={PDAY.isoformat()}"
                     f"&length_min=60&resource_id={w.courts['Court 4']}", headers=w.public), 200)["data"]  # fmt: skip
    by_start = {datetime.fromisoformat(s["starts_at"].replace("Z", "+00:00")).astimezone(ZONE).strftime("%H:%M"): s["price_minor"] for s in slots}  # fmt: skip
    assert by_start["06:00"] == 2400 and by_start["18:00"] == 3000 and by_start["22:00"] == 2400
    assert "22:30" not in by_start  # closes 23:00


@pytest.mark.xfail(
    strict=True,
    reason="Rental bookings never apply member prices: rentals price every payer as a "
    "non-member (member_amount_minor and membership-type rules are stored but unused on bookings)",
)
def test_g_member_prices(client_module, w):
    c = client_module
    assert preview(c, w, w.member, PDAY, "10:00", "11:00")["subtotal_minor"] == 2000  # owner: $25 prime less 20%
    assert preview(c, w, w.member, PDAY, "18:00", "19:00")["subtotal_minor"] == 2500
    assert preview(c, w, w.member, PDAY, "08:00", "09:00", "Pickleball court")["subtotal_minor"] == 1200
    assert preview(c, w, w.member, PDAY, "19:00", "20:00", "Volleyball court")["subtotal_minor"] == 4000


# --- h. cancellation and no-show -----------------------------------------------------------------------------


def test_h_cancellation_cut_off_late_fee_and_what_happens_to_the_payment(client_module, w):
    c = client_module
    payer = w.others[1]
    far = ok(rent(c, w, w.desk, "Pickleball court", "Court 2", MON + timedelta(days=4), "14:00", "15:00", payer))
    ok(c.post(f"{API}/payments", headers=w.desk | key(), json={"client_id": payer, "location_id": w.location,
         "amount_minor": 2400, "tender_kind": "card", "method_token": "tok_card_ok", "invoice_id": far["invoice_ids"][0]}))  # fmt: skip
    result = ok(c.post(f"{API}/rentals/{far['rental']['id']}/cancel", headers=w.desk, json={"reason": "client"}), 200)
    assert (result["reversed_minor"], result["late_fee_minor"]) == (2400, 0)
    balance = ok(c.get(f"{API}/clients/{payer}/account-credit", headers=w.owner), 200)
    assert balance["credit_minor"] == 2400  # paid card money became credit
    soon = datetime.now(ZONE) + timedelta(hours=3)
    start = soon.replace(minute=0, second=0, microsecond=0)
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


def _report(c, headers, location: str, key_: str, **params) -> tuple[dict, list]:
    run = ok(c.post(f"{API}/report-runs", headers=headers, json={"report_key": key_, "params": {"location_ids": [location]} | params}), 200)  # fmt: skip
    assert run["status"] == "succeeded", run
    rows = ok(c.get(f"{API}/report-runs/{run['id']}/rows", headers=headers, params={"limit": 200}), 200)["data"]
    return run, rows


def test_i_court_use_for_a_24_hour_facility_respects_hours_changeover_and_prime(client_module):
    """A fresh CIRQT open 24 hours a day. The scenario's own rental types and prices (the seed's are switched off,
    so a change to the seed cannot move these numbers): badminton on all four courts, 20.00 an hour, 30.00 at
    prime (18:00-22:00, the owner's setting) and 15.00 before noon; volleyball on Courts 2 and 3, 30.00 and 40.00
    at prime, with a 10-minute changeover either side. A cleaning closure 00:00-02:00 leaves each court 22 hours,
    4 of them prime. Every figure below is worked out by hand."""
    c = client_module
    fresh = cirqt.build(slug=f"cirqt-{uuid4().hex[:8]}", name="CIRQT court use")
    tenant = SimpleNamespace(id=fresh["tenant_id"], slug=fresh["slug"])
    owner = login(c, tenant, f"owner@{fresh['domain']}", cirqt.PASSWORD)
    with tenant_session(tenant.id) as session:
        location = session.scalar(select(Location.id).where(Location.name == "CIRQT"))
        courts = {r.name: str(r.id) for r in session.scalars(select(Resource).where(Resource.location_id == location))}
    location = str(location)
    ok(c.put(f"{API}/locations/{location}/facility-hours", headers=owner, json={"days": [
        {"weekday": d, "opens_time": "00:00", "closes_time": "24:00", "is_closed": False} for d in range(1, 8)]}), 200)  # fmt: skip
    for t in ok(c.get(f"{API}/rental-types?location_id={location}", headers=owner), 200)["data"]:
        ok(c.patch(f"{API}/rental-types/{t['id']}", headers=owner, json={"is_active": False}), 200)
    categories = ok(c.get(f"{API}/revenue-categories", headers=owner), 200)["data"]
    category = next(r["id"] for r in categories if r["code"] == "RENTALS")

    def rental_type(name: str, names: list[str], buffer: int, base: int, prime: int, morning: int | None) -> tuple:
        rtype = ok(c.post(f"{API}/rental-types", headers=owner, json={
            "location_id": location, "name": name, "revenue_category_id": category, "slot_granularity_min": 30,
            "resource_ids": [courts[n] for n in names], "buffer_before_min": buffer, "buffer_after_min": buffer}))["id"]  # fmt: skip
        rules = [{"kind": "rate", "name": "Prime", "start_time": "18:00", "end_time": "22:00", "amount_minor": prime}]
        if morning:
            rules.append(
                {"kind": "rate", "name": "Morning", "start_time": "06:00", "end_time": "12:00", "amount_minor": morning}
            )
        rate = ok(c.post(f"{API}/rental-types/{rtype}/rates", headers=owner, json={
            "name": "Hourly", "amount_minor": base, "basis": "per_hour", "rules": rules}))["id"]  # fmt: skip
        return rtype, rate

    badminton = rental_type("Badminton (scenario)", cirqt.COURTS, 0, 2000, 3000, 1500)
    volleyball = rental_type("Volleyball (scenario)", cirqt.VOLLEYBALL_COURTS, 10, 3000, 4000, None)
    payer = ok(c.get(f"{API}/clients", headers=owner), 200)["data"][0]["id"]
    day = date(TODAY.year + 1, 6, 1)
    day += timedelta(days=(7 - day.weekday()) % 7)  # a Monday in June, far from the seed's league season

    def rent_(kind: tuple, court: str, start: str, end: str) -> None:
        ok(c.post(f"{API}/rentals", headers=owner | key(), json={
            "location_id": location, "rental_type_id": kind[0], "client_id": payer,
            "resources": [{"resource_id": courts[court]}], "starts_at": at(day, start), "ends_at": at(day, end),
            "charge": {"decision": "bill", "rental_rate_id": kind[1]}}))  # fmt: skip

    ok(c.post(f"{API}/blackouts", headers=owner, json={
        "location_id": location, "name": "Cleaning", "starts_at": at(day, "00:00"), "ends_at": at(day, "02:00")}))  # fmt: skip
    rent_(badminton, "Court 1", "10:00", "12:00")  # morning: 2 x 15.00
    rent_(badminton, "Court 1", "18:00", "20:00")  # prime: 2 x 30.00
    rent_(volleyball, "Court 2", "17:30", "20:00")  # 0.5 x 30.00 + 2 x 40.00 = 95.00; changeover 17:20 and 20:00
    rent_(badminton, "Court 3", "21:00", "23:00")  # 30.00 prime + 20.00 after
    ok(c.post(f"{API}/bookings", headers=owner, json={
        "location_id": location, "kind": "block", "block_kind": "unavailable", "resources": [{"resource_id": courts["Court 4"]}],
        "starts_at": at(day, "06:00"), "ends_at": at(day, "08:00")}))  # fmt: skip

    run, found = _report(c, owner, location, "court_use", from_on=day.isoformat(), to_on=day.isoformat())
    by = {r["label"]: r for r in found}
    pick = (
        "hours_source",
        "available_hours",
        "played_hours",
        "utilization_pct",
        "buffer_hours",
        "blocked_hours",
        "peak_available_hours",
        "peak_played_hours",
        "peak_utilization_pct",
        "offpeak_utilization_pct",
        "revenue_minor",
        "peak_revenue_minor",
        "revenue_per_available_hour_minor",
        "revenue_per_sold_hour_minor",
    )
    expected = {
        # 4 h of 22 = 18.18%; prime 2 of 4 h = 50%; off-prime 2 of 18 h = 11.1%; 90.00, prime 60.00;
        # 90.00 / 22 h = 4.09 an available hour, 90.00 / 4 h = 22.50 a rented hour
        "Court 1": ("Opening hours", 22.0, 4.0, 18.2, 0.0, 0.0, 4.0, 2.0, 50.0, 11.1, 9000, 6000, 409, 2250),
        # 2.5 h = 11.36%; prime 18-20 = 2 of 4 h; off 0.5 of 18 h = 2.78%; changeover 20 min (inside the hours);
        # prime share of 95.00 is 120 of 150 minutes = 76.00; 95.00 / 22 = 4.32, 95.00 / 2.5 = 38.00
        "Court 2": ("Opening hours", 22.0, 2.5, 11.4, 0.33, 0.0, 4.0, 2.0, 50.0, 2.8, 9500, 7600, 432, 3800),
        # 2 h = 9.09%; prime 21-22 = 1 of 4 h; off 1 of 18 h = 5.56%; 50.00, prime half of the minutes = 25.00
        "Court 3": ("Opening hours", 22.0, 2.0, 9.1, 0.0, 0.0, 4.0, 1.0, 25.0, 5.6, 5000, 2500, 227, 2500),
        # the staff block 06:00-08:00 is shown, not counted as use
        "Court 4": ("Opening hours", 22.0, 0.0, 0.0, 0.0, 2.0, 4.0, 0.0, 0.0, 0.0, 0, 0, 0, None),
    }  # fmt: skip
    assert {name: tuple(by[name][k] for k in pick) for name in cirqt.COURTS} == expected
    # 8.5 h of 88 = 9.66%; prime 5 of 16 h = 31.25%, half up 31.3%; 235.00 = 2.67 an available hour, 27.65 a rented one
    totals = run["totals"]
    assert (totals["available_hours"], totals["played_hours"], totals["utilization_pct"]) == (88.0, 8.5, 9.7)
    assert (totals["peak_utilization_pct"], totals["revenue_minor"]) == (31.3, 23500)
    assert (totals["revenue_per_available_hour_minor"], totals["revenue_per_sold_hour_minor"]) == (267, 2765)

    # Prime badminton versus volleyball on Courts 2 and 3: each sport against the 8 prime hours of those courts.
    _, found = _report(c, owner, location, "court_use", from_on=day.isoformat(), to_on=day.isoformat(),
                       group_by="sport", resource_ids=[courts["Court 2"], courts["Court 3"]])  # fmt: skip
    sport = {r["label"]: r for r in found}
    assert set(sport) == {"Badminton (scenario)", "Volleyball (scenario)", "League and programs"}
    assert (
        sport["Badminton (scenario)"]["peak_available_hours"],
        sport["Badminton (scenario)"]["peak_utilization_pct"],
    ) == (8.0, 12.5)
    assert (
        sport["Volleyball (scenario)"]["peak_played_hours"],
        sport["Volleyball (scenario)"]["peak_utilization_pct"],
    ) == (2.0, 25.0)
    assert sport["Volleyball (scenario)"]["utilization_pct"] == 5.7  # 2.5 of 44 h

    # The month reconciles with its days, to the minute and the cent.
    first = day.replace(day=1)
    month = {"from_on": first.isoformat(), "to_on": (first + timedelta(days=29)).isoformat()}  # June has 30 days
    _, days = _report(c, owner, location, "court_use", **month)
    _, months = _report(c, owner, location, "court_use", grain="month", **month)
    assert len(days) == 30 * 4 and len(months) == 4
    for row in months:
        daily = [r for r in days if r["label"] == row["label"]]
        assert sum(round(r["played_hours"] * 60) for r in daily) == round(row["played_hours"] * 60)
        assert sum(round(r["available_hours"] * 60) for r in daily) == round(row["available_hours"] * 60)
        assert sum(r["revenue_minor"] for r in daily) == row["revenue_minor"]
    assert {r["label"]: r["available_hours"] for r in months}["Court 1"] == 30 * 24 - 2  # less the one closure


def data(response) -> list:
    body = ok(response, 200)
    return body if isinstance(body, list) else body["data"]


# --- j. unmanned: a newcomer signs up, pays the membership fee and books a court with no staff ---------------


def test_j_a_newcomer_goes_from_finding_cirqt_to_a_paid_court_with_no_staff(client_module, w, mailbox):
    c, day = client_module, MON + timedelta(days=8)
    assert w.location in {x["id"] for x in data(c.get(f"{API}/public/locations", headers=w.public))}
    assert "Adult monthly" in {p["name"] for p in data(c.get(f"{API}/public/membership-plans", headers=w.public))}
    offered = {t["name"] for t in data(c.get(f"{API}/public/rental-types", headers=w.public))}
    assert {"Badminton court", "Pickleball court", "Volleyball court"} <= offered
    # The one staff step: online sign-up is off by default, so the owner turns it on once at set-up.
    body = {
        "location_id": w.location,
        "email": f"new-{uuid4().hex[:6]}@{w.mail}",
        "first_name": "Nova",
        "last_name": "Newcomer",
    }
    refused = c.post(f"{API}/public/portal-signups", headers=w.public, json=body)
    assert refused.status_code == 409 and refused.json()["code"] == "signup-disabled"
    ok(c.put(f"{API}/locations/{w.location}/portal-settings", headers=w.owner,
             json={"is_enabled": True, "is_public": True, "allows_self_signup": True}), 200)  # fmt: skip
    mailbox.clear()
    assert c.post(f"{API}/public/portal-signups", headers=w.public, json=body).status_code == 202
    signed = ok(c.post(f"{API}/public/portal-signups/confirm", headers=w.public,
                       json={"token": link_token(mailbox[-1]), "client_kind": "mobile"}), 200)  # fmt: skip
    me = {"Authorization": f"Bearer {signed['access_token']}"}
    [mine] = data(c.get(f"{API}/portal/clients", headers=me))
    member = ok(c.post(f"{API}/portal/membership-contracts", headers=me | key(), json={
        "client_id": mine["id"], "location_id": w.location, "membership_plan_id": w.plans["Adult monthly"],
        "method_token": "tok_card_ok",
    }))  # fmt: skip
    assert member["status"] == "active" and member["payment_status"] == "succeeded"
    checkout = ok(c.post(f"{API}/portal/rentals", headers=me, json={
        "rental_type_id": w.types["Pickleball court"], "client_id": mine["id"], "resource_id": w.courts["Court 4"],
        "starts_at": at(day, "08:00"), "ends_at": at(day, "09:00"),
    }))  # fmt: skip
    paid = ok(c.post(f"{API}/portal/rentals/{checkout['rental']['id']}/confirm", headers=me | key(),
                     json={"provider_payment_token": "tok_card_ok"}), 200)  # fmt: skip
    assert paid["rental"]["status"] == "confirmed" and paid["payment_status"] == "succeeded"


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
    rate the seed made, "Weekly club" (the guest price with a 15% discount rule). There is no contract object."""
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
    assert invoice["total_minor"] == 8 * 2550, invoice  # $30 prime guest price less 15%
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


def coached_session(c, w, day: date, start: str, end: str, court: str) -> str:
    lesson, _ = lesson_setup(c, w)
    booked = ok(c.post(f"{API}/bookings", headers=w.owner, json={
        "location_id": w.location, "kind": "session", "reservation_type_id": lesson,
        "resources": [{"resource_id": payees(c, w)["Rowan (staff coach)"]["resource_id"]}, {"resource_id": w.courts[court]}],
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


@pytest.mark.xfail(
    strict=True,
    reason="No age rule on rentals: staff (or an import) can book a court in a child's "
    "name alone; a rental carries one client and no participant list, so 'a parent on the booking' "
    "cannot be expressed or enforced, and rental types have no age or guardian setting",
)
def test_m_a_child_cannot_be_booked_on_a_court_without_a_parent(client_module, w):
    response = rent(
        client_module, w, w.desk, "Badminton court", "Court 4", MON + timedelta(days=12), "17:00", "18:00", w.kids[1]
    )
    assert response.status_code in (403, 409, 422), response.text


# --- n. coaches: one on staff, one independent ----------------------------------------------------------------


def test_n_staff_coach_and_independent_coach(client_module, w):
    c = client_module
    found = payees(c, w)
    rowan, ines = found["Rowan (staff coach)"], found["Ines (independent coach)"]
    assert rowan["staff_user_id"] and ines["staff_user_id"] is None  # Ines has no sign-in
    rates = lambda p: data(c.get(f"{API}/staff-payees/{p['id']}/pay-rates", headers=w.owner))  # noqa: E731
    assert any(r.get("rate_60_minor") == 3000 for r in rates(rowan)), rates(rowan)
    assert any(
        r.get("session_commission_pct") not in (None, 0, "0") and float(r["session_commission_pct"]) == 70
        for r in rates(ines)
    )
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
        )
    }
    assert list(seen.values()) == [200, 200, 200, 200, 403, 403, 403], seen
