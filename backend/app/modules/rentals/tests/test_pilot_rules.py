"""Pilot rules for court rentals: member prices that agree between quote and charge (one pricing path for
staff, portal and recurring rentals), and the minors rule (a minor never holds a rental; a guardian books and
names the children who play)."""

import base64
import json
from datetime import datetime, timedelta
from itertools import groupby
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, update

from app.core.audit import AuditEvent
from app.core.auth import system_principal
from app.core.db.session import tenant_session
from app.modules import billing, memberships
from app.modules.clients.models import Client
from app.modules.documents.tests.support import sign
from app.modules.memberships.models import MembershipContract
from app.modules.memberships.tests.support import membership_plan
from app.modules.programs.tests.test_selfservice import SOON, policy
from app.modules.rentals.tests.test_lockers_and_plans import bind_waiver, stopped_by_waiver
from app.modules.rentals.tests.test_rentals import portal_client
from app.modules.scheduling.tests.helpers import API, DAY, at, book, facility, ok
from conftest import add_staff, login, new_client

CHILD = "2021-03-01"  # ten in 2031
RECURRING = {"pattern": "weekly", "range_type": "count", "occurrence_limit": 3}


@pytest.fixture
def f(client, owner, tenant):
    """Badminton by the hour in Chicago: guest $24, member $20; prime 18:00-22:00 guest $30, member $25."""
    f = facility(client, owner)
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        f.category = str(billing.service.create_revenue_category(session, code="CRT", label="Courts").id)
    f.plan = membership_plan(client, owner, tenant)
    f.mtype = f.plan["membership_type_id"]
    f.rtype = ok(client.post(f"{API}/rental-types", headers=owner, json={
        "location_id": f.location, "name": "Badminton", "revenue_category_id": f.category,
        "resource_ids": [f.court, f.court2], "buffer_after_min": 0,
    }))["id"]  # fmt: skip
    f.rate = ok(client.post(f"{API}/rental-types/{f.rtype}/rates", headers=owner, json={
        "name": "Hourly", "amount_minor": 2400, "member_amount_minor": 2000, "basis": "per_hour",
        "rules": [
            {"kind": "rate", "name": "Member prime", "start_time": "18:00", "end_time": "22:00",
             "membership_type_id": f.mtype, "amount_minor": 2500},
            {"kind": "rate", "name": "Prime", "start_time": "18:00", "end_time": "22:00", "amount_minor": 3000},
        ],
    }))["id"]  # fmt: skip
    ok(client.patch(f"{API}/rental-types/{f.rtype}", headers=owner, json={
        "access": "self_service", "online_rental_rate_id": f.rate, "slot_granularity_min": 60,
    }), 200)  # fmt: skip
    f.guest = new_client(client, owner, f.location)["id"]
    f.member = new_client(client, owner, f.location)["id"]
    f.contract = join(client, owner, f, f.member, DAY - timedelta(days=10))
    return f


def join(client, owner, f, client_id: str, start, plan: dict | None = None, **extra) -> str:
    body = {"client_id": client_id, "location_id": f.location, "membership_plan_id": (plan or f.plan)["id"],
            "start_on": start.date().isoformat()} | extra  # fmt: skip
    return ok(client.post(f"{API}/membership-contracts", headers=owner, json=body))["id"]


def body(f, who: str, start: float, end: float, **extra) -> dict:
    return {
        "location_id": f.location, "rental_type_id": f.rtype, "client_id": who,
        "resources": [{"resource_id": f.court}], "starts_at": at(start), "ends_at": at(end),
        "charge": {"decision": "bill", "rental_rate_id": f.rate},
    } | extra  # fmt: skip


def rent(client, headers, payload: dict):
    return client.post(f"{API}/rentals", headers=headers | {"Idempotency-Key": f"r-{uuid4().hex}"}, json=payload)


def starting(slots: list[dict], hour: float) -> dict:
    return next(s for s in slots if datetime.fromisoformat(s["starts_at"]) == datetime.fromisoformat(at(hour)))


def units(quote: dict) -> list[int]:
    return [line["unit_amount_minor"] for line in quote["lines"]]


# 15 = 10:00, 22 = 17:00, 23 = 18:00 and 24 = 19:00 in Chicago on DAY (CDT, UTC-5).


def test_member_and_guest_rates_per_band_quote_equals_charge(client, owner, f):
    for who, expected, subtotal in ((f.member, [2000, 2500], 4500), (f.guest, [2400, 3000], 5400)):
        payload = body(f, who, 22, 24)  # straddles 18:00: one line per band, each half-up once
        preview = ok(client.post(f"{API}/rentals/preview", headers=owner, json=payload), 200)["quote"]
        created = ok(rent(client, owner, payload))
        assert sorted(units(preview)) == sorted(units(created["quote"])) == expected
        assert preview["subtotal_minor"] == created["quote"]["subtotal_minor"] == subtotal
        assert created["rental"]["amount_minor"] == subtotal
        assert all(line["is_member_price"] is (who == f.member) for line in created["quote"]["lines"])
        ok(client.post(f"{API}/rentals/{created['rental']['id']}/cancel", headers=owner, json={}), 200)


def test_recurring_rental_prices_each_occurrence_on_its_own_date(client, owner, f, tenant):
    short = membership_plan(client, owner, tenant, billing_occurrences_count=1)  # one month: Apr 15 to May 14
    lapsing = new_client(client, owner, f.location)["id"]
    join(client, owner, f, lapsing, DAY - timedelta(days=20), short)
    created = ok(rent(client, owner, body(f, lapsing, 15, 16, recurrence=RECURRING)))
    assert sorted(units(created["quote"])) == [2000, 2400]  # two member weeks on one line, the lapsed week on another
    assert created["quote"]["subtotal_minor"] == 2000 * 2 + 2400


def test_an_auto_renewing_membership_covers_past_its_end_date(client, owner, f, tenant):
    short = membership_plan(client, owner, tenant, billing_occurrences_count=1, auto_renew_lead_count=7,
                            auto_renew_lead_unit="day")  # one month, Apr 15 to May 14, renewing  # fmt: skip
    renewing = new_client(client, owner, f.location)["id"]
    join(client, owner, f, renewing, DAY - timedelta(days=20), short, is_auto_renew=True)
    created = ok(rent(client, owner, body(f, renewing, 15, 16, recurrence=RECURRING)))
    assert units(created["quote"]) == [2000]  # all three weeks at the member price, on one line
    assert created["quote"]["subtotal_minor"] == 2000 * 3


def test_arrears_billing_prices_dates_an_ended_membership_covered(client, owner, f, tenant):
    payer = new_client(client, owner, f.location)["id"]
    contract = join(client, owner, f, payer, DAY - timedelta(days=10))
    unbilled = ok(rent(client, owner, body(f, payer, 15, 16, charge={"decision": "unbilled"})))["rental"]
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:  # it has ended since
        row = session.get(MembershipContract, contract)
        row.status, row.end_on = "expired", DAY.date() + timedelta(days=1)
    charge = {"rental_ids": [unbilled["id"]], "charge": {"decision": "bill", "rental_rate_id": f.rate}}
    billed = ok(
        client.post(f"{API}/rentals/charges", headers=owner | {"Idempotency-Key": uuid4().hex}, json=charge), 200
    )
    assert billed["quote"]["subtotal_minor"] == 2000  # the date was covered when it was played
    later = ok(rent(client, owner, body(f, payer, 15 + 24 * 7, 16 + 24 * 7)))  # a week after it ended
    assert later["quote"]["subtotal_minor"] == 2400


def test_a_membership_cancelled_before_it_starts_never_earns_the_member_price(client, owner, f):
    who = new_client(client, owner, f.location)["id"]
    contract = join(client, owner, f, who, DAY)  # starts on the rental's date, then is un-sold
    ok(client.post(f"{API}/membership-contracts/{contract}/cancel", json={"reason": "voluntary"},
                   headers=owner | {"Idempotency-Key": uuid4().hex}), 200)  # fmt: skip
    quote = ok(client.post(f"{API}/rentals/preview", headers=owner, json=body(f, who, 15, 16)), 200)["quote"]
    assert quote["subtotal_minor"] == 2400 and not quote["lines"][0]["is_member_price"]


def test_bill_selected_prices_the_payer_as_a_member(client, owner, f):
    unbilled = ok(rent(client, owner, body(f, f.member, 23, 24, charge={"decision": "unbilled"})))["rental"]
    billed = ok(client.post(f"{API}/rentals/charges", headers=owner | {"Idempotency-Key": uuid4().hex}, json={
        "rental_ids": [unbilled["id"]], "charge": {"decision": "bill", "rental_rate_id": f.rate},
    }), 200)  # fmt: skip
    assert billed["quote"]["subtotal_minor"] == 2500


def test_a_moved_rental_keeps_its_price(client, owner, f):
    rental = ok(rent(client, owner, body(f, f.member, 15, 16)))["rental"]
    booking = ok(client.get(f"{API}/bookings/{rental['booking_id']}", headers=owner), 200)
    moved = {"starts_at": at(24), "ends_at": at(25), "version": booking["version"]}
    ok(client.post(f"{API}/bookings/{rental['booking_id']}/reschedule", headers=owner, json=moved), 200)
    assert ok(client.get(f"{API}/rentals/{rental['id']}", headers=owner), 200)["amount_minor"] == 2000


def online(f, who: str, start: float, end: float) -> dict:
    return {"rental_type_id": f.rtype, "client_id": who, "resource_id": f.court, "starts_at": at(start),
            "ends_at": at(end)}  # fmt: skip


def portal_member(client, owner, tenant, f) -> tuple[str, dict]:
    me, portal = portal_client(client, owner, tenant, f)
    join(client, owner, f, me, DAY - timedelta(days=10))
    return me, portal


def test_portal_quotes_and_charges_the_member_price(client, owner, tenant, f):
    me, portal = portal_member(client, owner, tenant, f)
    query = f"rental_type_id={f.rtype}&on=2031-05-05&length_min=60&resource_id={f.court}"
    public = ok(client.get(f"{API}/public/rental-availability?{query}", headers={"X-Tenant-Slug": tenant.slug}), 200)
    mine = ok(client.get(f"{API}/portal/rental-availability?{query}&client_id={me}", headers=portal), 200)
    price = lambda slots, hour: starting(slots["data"], hour)  # noqa: E731
    assert (price(public, 15)["price_minor"], price(public, 23)["price_minor"]) == (2400, 3000)
    assert (price(mine, 15)["price_minor"], price(mine, 23)["price_minor"]) == (2000, 2500)
    assert price(mine, 23)["is_member_price"] and not price(public, 23)["is_member_price"]
    checkout = ok(client.post(f"{API}/portal/rentals", headers=portal, json=online(f, me, 23, 24)))
    assert checkout["quote"]["subtotal_minor"] == price(mine, 23)["price_minor"]
    stranger = new_client(client, owner, f.location)["id"]
    assert (
        client.get(f"{API}/portal/rental-availability?{query}&client_id={stranger}", headers=portal).status_code == 404
    )


def test_open_times_read_membership_once_per_request(client, owner, tenant, f, monkeypatch):
    me, portal = portal_member(client, owner, tenant, f)
    calls = []
    real = memberships.service.member_on
    monkeypatch.setattr(memberships.service, "member_on", lambda *a: calls.append(a) or real(*a))
    query = f"rental_type_id={f.rtype}&on=2031-05-05&length_min=60&client_id={me}"
    slots = ok(client.get(f"{API}/portal/rental-availability?{query}", headers=portal), 200)["data"]
    assert len(slots) > 10 and len(calls) == 1  # every slot of the day, one membership read


def test_member_open_times_fail_closed_when_the_limiter_is_down(client, owner, tenant, f, monkeypatch):
    """Each call reads membership: without Redis to count them the portal refuses rather than serving unmetered.
    (The past-due lockout deliberately leaves this GET open: billing's guard test records why.)"""
    import redis

    from app.core import ratelimit
    from app.core.settings import get_settings

    me, portal = portal_member(client, owner, tenant, f)
    monkeypatch.setattr(get_settings().rate_limit, "enabled", True)
    down = redis.Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.2)
    monkeypatch.setattr(ratelimit, "_redis", lambda: down)
    url = f"{API}/portal/rental-availability?rental_type_id={f.rtype}&on=2031-05-05&length_min=60&client_id={me}"
    refused(client.get(url, headers=portal), 503, "rate-limit-unavailable")


def _local_hour(slot: dict) -> int:
    return datetime.fromisoformat(slot["starts_at"]).astimezone(ZoneInfo("America/Chicago")).hour


def test_open_times_cover_the_whole_day_grouped_by_court_in_pages_never_truncated(client, owner, tenant, f):
    me, portal = portal_member(client, owner, tenant, f)
    url = f"{API}/portal/rental-availability?rental_type_id={f.rtype}&on=2031-05-05&length_min=60&client_id={me}"
    whole = ok(client.get(url, headers=portal), 200)
    assert not whole["page"]["has_more"] and whole["page"]["next_cursor"] is None
    courts = [s["resource_id"] for s in whole["data"]]
    assert [k for k, _ in groupby(courts)] == sorted(set(courts), key=courts.index)  # one run per court
    assert len(set(courts)) == 2 and max(_local_hour(s) for s in whole["data"]) >= 21  # the evening is there
    paged, cursor = [], ""
    while True:
        page = ok(client.get(f"{url}&limit=7{cursor}", headers=portal), 200)
        paged += page["data"]
        if not page["page"]["has_more"]:
            break
        cursor = f"&cursor={page['page']['next_cursor']}"
    assert paged == whole["data"]  # keyset pages add up to the whole day, nothing dropped or repeated
    assert client.get(f"{url}&cursor=not-a-cursor", headers=portal).status_code == 400


def _cursor(value) -> str:
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode()


BAD_CURSORS = [
    "WzEsMiwiMjAzMS0wNS0wNVQxMDowMDowMCJd",  # [1, 2, "2031-05-05T10:00:00"]: the verifier's 500
    "!!!",
    _cursor("abc"),
    _cursor({"a": 1}),
    _cursor([None, None, "2031-05-05T15:00:00+00:00"]),
    _cursor(["Court 1", "not-a-uuid", "2031-05-05T15:00:00+00:00"]),
    _cursor(["Court 1", str(uuid4()), "2031-05-05T15:00:00"]),  # naive: cannot be compared with a slot's start
    _cursor(["Court 1", str(uuid4()), 5]),
    _cursor(["Court 1", str(uuid4())]),
]


@pytest.mark.parametrize("cursor", BAD_CURSORS)
def test_a_malformed_cursor_is_400_on_both_availability_routes(client, owner, tenant, f, cursor):
    me, portal = portal_member(client, owner, tenant, f)
    query = f"rental_type_id={f.rtype}&on=2031-05-05&length_min=60&cursor={cursor}"
    public = client.get(f"{API}/public/rental-availability?{query}", headers={"X-Tenant-Slug": tenant.slug})
    mine = client.get(f"{API}/portal/rental-availability?{query}&client_id={me}", headers=portal)
    assert (public.status_code, mine.status_code) == (400, 400), (public.text, mine.text)


def test_open_times_narrow_to_a_court_and_a_time_band(client, owner, tenant, f):
    me, portal = portal_member(client, owner, tenant, f)
    query = f"rental_type_id={f.rtype}&on=2031-05-05&length_min=60&from_time=18:00&to_time=22:00"
    public = ok(client.get(f"{API}/public/rental-availability?{query}", headers={"X-Tenant-Slug": tenant.slug}), 200)
    assert {_local_hour(s) for s in public["data"]} == {18, 19, 20, 21}  # starts in the band, both courts
    assert {s["resource_id"] for s in public["data"]} == {f.court, f.court2}
    mine = ok(client.get(f"{API}/portal/rental-availability?{query}&client_id={me}&resource_id={f.court2}",
                         headers=portal), 200)["data"]  # fmt: skip
    assert [_local_hour(s) for s in mine] == [18, 19, 20, 21] and {s["resource_id"] for s in mine} == {f.court2}
    backwards = client.get(f"{API}/public/rental-availability?rental_type_id={f.rtype}&on=2031-05-05"
                           "&from_time=20:00&to_time=18:00", headers={"X-Tenant-Slug": tenant.slug})  # fmt: skip
    assert backwards.status_code == 422 and backwards.json()["errors"][0]["pointer"] == "/to_time"


def test_a_membership_that_lapses_after_the_quote_the_charge_wins(client, owner, tenant, f):
    me, portal = portal_client(client, owner, tenant, f)
    contract = join(client, owner, f, me, datetime.now(ZoneInfo("America/Chicago")))  # active today there
    ten = SOON + timedelta(hours=16)  # 10:00 in Chicago (CST) three days ahead
    query = f"rental_type_id={f.rtype}&on={SOON.date()}&length_min=60&resource_id={f.court}&client_id={me}"
    slots = ok(client.get(f"{API}/portal/rental-availability?{query}", headers=portal), 200)["data"]
    quoted = next(s for s in slots if datetime.fromisoformat(s["starts_at"]) == ten)
    assert quoted["price_minor"] == 2000 and quoted["is_member_price"]
    ok(client.post(f"{API}/membership-contracts/{contract}/suspensions", headers=owner, json={"remarks": "Paused"}))
    request = online(f, me, 0, 1) | {"starts_at": ten.isoformat(), "ends_at": (ten + timedelta(hours=1)).isoformat()}
    checkout = ok(client.post(f"{API}/portal/rentals", headers=portal, json=request))
    assert checkout["quote"]["subtotal_minor"] == 2400  # the guest price, shown on the checkout before paying
    assert not checkout["quote"]["lines"][0]["is_member_price"]


# --- the minors rule ---------------------------------------------------------------------------------------------


def family(client, owner, f) -> tuple[str, str]:
    parent = new_client(client, owner, f.location, first_name="Pat")["id"]
    kid = new_client(client, owner, f.location, first_name="Kit", birth_on=CHILD)["id"]
    parent_of = next(
        t for t in ok(client.get(f"{API}/relationship-types", headers=owner), 200) if t["code"] == "parent_of"
    )
    ok(client.post(f"{API}/clients/{parent}/relationships", headers=owner,
                   json={"other_client_id": kid, "relationship_type_id": parent_of["id"]}))  # fmt: skip
    return parent, kid


def refused(response, status: int, code: str) -> None:
    assert (response.status_code, response.json().get("code")) == (status, code), response.text


def test_a_minor_cannot_hold_a_rental_and_override_needs_the_key_and_a_reason(client, owner, tenant, f):
    _, kid = family(client, owner, f)
    refused(rent(client, owner, body(f, kid, 15, 16)), 422, "minor-cannot-hold-rental")
    refused(client.post(f"{API}/rentals/preview", headers=owner, json=body(f, kid, 15, 16)), 422,
            "minor-cannot-hold-rental")  # fmt: skip
    desk = login(client, tenant, add_staff(tenant, "front_desk", all_locations=True)[0])
    assert rent(client, desk, body(f, kid, 15, 16, minor_override_reason="Coach's own child")).status_code == 403
    allowed = ok(rent(client, owner, body(f, kid, 15, 16, minor_override_reason="Coach's own child")))
    with tenant_session(tenant.id) as session:
        record = session.scalars(
            select(AuditEvent).where(AuditEvent.entity_id == allowed["rental"]["id"]).order_by(AuditEvent.id.desc())
        ).first()
    assert record.changes["minor_override_reason"] is True  # free text is flag-only
    staff_view = ok(client.get(f"{API}/rentals/{allowed['rental']['id']}", headers=owner), 200)
    assert staff_view["minor_override_reason"] == "Coach's own child"  # the stored reason, shown to staff


def test_extending_a_minors_series_needs_a_fresh_reason(client, owner, f):
    _, kid = family(client, owner, f)
    weekly = {"pattern": "weekly", "range_type": "count", "occurrence_limit": 2}
    created = ok(
        rent(client, owner, body(f, kid, 15, 16, recurrence=weekly, minor_override_reason="Coach's own child"))
    )
    more = {"start_on": "2031-06-02", "start_time": "10:00", "end_time": "11:00", "rule": weekly}
    url = f"{API}/rentals/{created['rental']['id']}/extensions"
    refused(client.post(url, headers=owner, json=more), 422, "minor-cannot-hold-rental")  # never inherited
    ok(client.post(url, headers=owner, json=more | {"minor_override_reason": "Still the coach's child"}))
    series = ok(client.get(f"{API}/rentals?booking_series_id={created['booking_series_id']}", headers=owner), 200)
    assert sorted(r["minor_override_reason"] for r in series["data"]) == [
        "Coach's own child", "Coach's own child", "Still the coach's child", "Still the coach's child",
    ]  # fmt: skip


def test_extending_a_rental_checks_its_players_again(client, owner, f):
    _, kid = family(client, owner, f)
    weekly = {"pattern": "weekly", "range_type": "count", "occurrence_limit": 2}
    created = ok(rent(client, owner, body(f, f.guest, 15, 16, recurrence=weekly, parties=[{"client_id": kid}],
                                          minor_override_reason="Club helper")))  # fmt: skip
    more = {"start_on": "2031-06-02", "start_time": "10:00", "end_time": "11:00", "rule": weekly}
    url = f"{API}/rentals/{created['rental']['id']}/extensions"
    refused(client.post(url, headers=owner, json=more), 422, "minor-needs-guardian")  # not the child's guardian
    ok(client.post(url, headers=owner, json=more | {"minor_override_reason": "Club helper again"}))


@pytest.mark.parametrize("who", ["front_desk", "owner"])
def test_scheduling_routes_never_extend_a_rental_series(client, owner, tenant, f, who):
    """Scheduling's generic add-rule and replace-rule routes are not a side door past the minors rule: a series
    that belongs to a rental is extended only through the rental, whoever asks."""
    _, kid = family(client, owner, f)
    weekly = {"pattern": "weekly", "range_type": "count", "occurrence_limit": 2}
    created = ok(
        rent(client, owner, body(f, kid, 15, 16, recurrence=weekly, minor_override_reason="Coach's own child"))
    )
    series_id = created["booking_series_id"]
    headers = owner if who == "owner" else login(client, tenant, add_staff(tenant, who, all_locations=True)[0])
    more = {"start_on": "2031-06-02", "start_time": "10:00", "end_time": "11:00", "rule": weekly}
    url = f"{API}/booking-series/{series_id}/rules"
    for preview in (False, True):
        refused(client.post(url, headers=headers | {"Idempotency-Key": uuid4().hex}, json=more | {"preview": preview}),
                409, "series-owned-by-rental")  # fmt: skip
    rule_id = ok(client.get(f"{API}/booking-series/{series_id}", headers=owner), 200)["rules"][0]["id"]
    replace = {"start_on": DAY.date().isoformat(), "start_time": "12:00", "end_time": "13:00", "rule": weekly}
    refused(client.patch(f"{url}/{rule_id}", headers=headers | {"Idempotency-Key": uuid4().hex}, json=replace),
            409, "series-owned-by-rental")  # fmt: skip
    series = ok(client.get(f"{API}/rentals?booking_series_id={series_id}", headers=owner), 200)
    assert len(series["data"]) == 2 and all(r["cancelled_at"] is None for r in series["data"])


def test_a_guardian_books_and_names_the_children_who_play(client, owner, f):
    parent, kid = family(client, owner, f)
    party = [{"client_id": kid}]
    created = ok(rent(client, owner, body(f, parent, 15, 16, parties=party)))
    assert created["rental"]["parties"] == [{"client_id": kid, "is_charged": False}]
    refused(rent(client, owner, body(f, f.guest, 16, 17, parties=party)), 422, "minor-needs-guardian")
    refused(rent(client, owner, body(f, parent, 17, 18, parties=[{"client_id": kid, "is_charged": True}])), 422,
            "minor-needs-guardian")  # fmt: skip
    unknown = new_client(client, owner, f.location)["id"]  # no birth date: treated as an adult (ADR 0002 section 5)
    preview = ok(client.post(f"{API}/rentals/preview", headers=owner, json=body(f, unknown, 18, 19)), 200)
    assert preview["birth_on_unknown"] == [unknown]  # ... and the desk is warned
    assert ok(rent(client, owner, body(f, unknown, 18, 19)))["birth_on_unknown"] == [unknown]
    assert ok(client.post(f"{API}/rentals/preview", headers=owner, json=body(f, parent, 19, 20, parties=party)),
              200)["birth_on_unknown"] == [parent]  # fmt: skip


def test_a_guardian_spends_a_plan_bought_in_the_childs_name_when_the_child_plays(client, owner, f):
    parent, kid = family(client, owner, f)
    plan = ok(client.post(f"{API}/rental-plans", headers=owner, json={
        "location_id": f.location, "name": "Junior hours", "rental_type_id": f.rtype, "model": "per_hour",
        "quantity": "3", "price_minor": 6000, "revenue_category_id": f.category,
    }))  # fmt: skip
    purchase = ok(client.post(f"{API}/rental-plan-purchases", headers=owner | {"Idempotency-Key": uuid4().hex},
                              json={"rental_plan_id": plan["id"], "client_id": kid}))  # fmt: skip
    cover = {"decision": "plan", "rental_plan_purchase_id": purchase["id"]}
    refused(
        rent(client, owner, body(f, parent, 15, 16, charge=cover)), 422, "validation-failed"
    )  # the child is not playing
    covered = ok(rent(client, owner, body(f, parent, 15, 16, charge=cover, parties=[{"client_id": kid}])))["rental"]
    assert covered["charge_state"] == "plan_covered"
    refused(rent(client, owner, body(f, f.guest, 16, 17, charge=cover, parties=[{"client_id": kid}])), 422,
            "minor-needs-guardian")  # fmt: skip


def _junior_plan(client, owner, f, holder: str) -> dict:
    plan = ok(client.post(f"{API}/rental-plans", headers=owner, json={
        "location_id": f.location, "name": f"Junior hours {uuid4().hex[:6]}", "rental_type_id": f.rtype,
        "model": "per_hour", "quantity": "5", "price_minor": 6000, "revenue_category_id": f.category,
    }))  # fmt: skip
    purchase = ok(client.post(f"{API}/rental-plan-purchases", headers=owner | {"Idempotency-Key": uuid4().hex},
                              json={"rental_plan_id": plan["id"], "client_id": holder}))  # fmt: skip
    return {"decision": "plan", "rental_plan_purchase_id": purchase["id"]}


def test_a_guardian_spends_a_childs_plan_only_on_dates_the_child_plays(client, owner, f):
    parent, kid = family(client, owner, f)
    cover = _junior_plan(client, owner, f, kid)
    played = ok(rent(client, owner, body(f, parent, 15, 16, parties=[{"client_id": kid}],
                                         charge={"decision": "unbilled"})))["rental"]  # fmt: skip
    alone = ok(rent(client, owner, body(f, parent, 17, 18, charge={"decision": "unbilled"})))["rental"]
    both = {"rental_ids": [played["id"], alone["id"]], "charge": cover}
    refused(client.post(f"{API}/rentals/charges", headers=owner | {"Idempotency-Key": uuid4().hex}, json=both),
            422, "validation-failed")  # the child does not play the second date  # fmt: skip
    one = {"rental_ids": [played["id"]], "charge": cover}
    billed = ok(client.post(f"{API}/rentals/charges", headers=owner | {"Idempotency-Key": uuid4().hex}, json=one), 200)
    assert billed["rentals"][0]["charge_state"] == "plan_covered"


def test_a_guardian_never_spends_a_grown_childs_plan(client, owner, f):
    parent, kid = family(client, owner, f)
    ok(client.patch(f"{API}/clients/{kid}", headers=owner, json={"birth_on": "1990-01-01"}), 200)  # an adult now
    cover = _junior_plan(client, owner, f, kid)
    refused(rent(client, owner, body(f, parent, 15, 16, charge=cover, parties=[{"client_id": kid}])), 422,
            "validation-failed")  # an adult's plan is shared only through plan sharing  # fmt: skip


def test_a_guardian_spending_a_childs_plan_passes_the_share_waiver_gate(client, owner, f):
    """A guardian spending a child's plan is a holder spending someone else's plan, like a share-holder: the child's
    signature does not cover them. Refused with document-required until they accept it, once per purchase."""
    parent, kid = family(client, owner, f)
    cover = _junior_plan(client, owner, f, kid)
    plan_id = ok(client.get(f"{API}/rental-plan-purchases/{cover['rental_plan_purchase_id']}", headers=owner), 200)
    bind_waiver(client, owner, {"id": plan_id["rental_plan_id"]})  # bound after the child's purchase was sold
    document = stopped_by_waiver(client, owner, rent(client, owner, body(f, parent, 15, 16, charge=cover,
                                                                         parties=[{"client_id": kid}])))  # fmt: skip
    assert document["client_id"] == parent
    assert sign(client, owner, document).status_code == 200
    ok(rent(client, owner, body(f, parent, 15, 16, charge=cover, parties=[{"client_id": kid}])))
    signed = ok(client.get(f"{API}/client-documents/{document['id']}", headers=owner), 200)
    assert (signed["source_type"], signed["source_id"]) == ("rental_plan_purchase", cover["rental_plan_purchase_id"])
    ok(rent(client, owner, body(f, parent, 17, 18, charge=cover, parties=[{"client_id": kid}])))  # one per purchase


def test_the_minor_age_is_the_tenant_setting(client, owner, f):
    _, kid = family(client, owner, f)
    ok(client.patch(f"{API}/tenant", headers=owner, json={"settings": {"minor_age": 8}}), 200)
    ok(rent(client, owner, body(f, kid, 15, 16)))


def test_portal_parent_books_in_own_name_with_the_child_playing(client, owner, tenant, f):
    me, portal = portal_client(client, owner, tenant, f)
    kid = new_client(client, owner, f.location, first_name="Kit", birth_on=CHILD)["id"]
    parent_of = next(
        t for t in ok(client.get(f"{API}/relationship-types", headers=owner), 200) if t["code"] == "parent_of"
    )
    ok(client.post(f"{API}/clients/{me}/relationships", headers=owner,
                   json={"other_client_id": kid, "relationship_type_id": parent_of["id"]}))  # fmt: skip
    checkout = ok(client.post(f"{API}/portal/rentals", headers=portal,
                              json=online(f, me, 15, 16) | {"player_client_ids": [kid]}))  # fmt: skip
    staff_view = ok(client.get(f"{API}/rentals/{checkout['rental']['id']}", headers=owner), 200)
    assert staff_view["parties"] == [{"client_id": kid, "is_charged": False}]
    assert "parties" not in checkout["rental"]  # the portal view carries no co-party ids (S-06)
    assert "minor_override_reason" not in checkout["rental"]  # staff notes stay on the staff view
    stranger = new_client(client, owner, f.location)["id"]
    assert client.post(f"{API}/portal/rentals", headers=portal,
                       json=online(f, me, 16, 17) | {"player_client_ids": [stranger]}).status_code == 404  # fmt: skip


def test_only_a_guardian_brings_a_child_a_delegate_does_not(client, owner, tenant, f):
    """A grandparent with acting rights (a delegate) may book for the family, but a child plays only on a booking
    held by one of their guardians: the person answerable for them at the court."""
    grandparent, theirs = portal_client(client, owner, tenant, f)
    kid = new_client(client, owner, f.location, first_name="Kit", birth_on=CHILD)["id"]
    minds = ok(client.post(f"{API}/relationship-types", headers=owner, json={
        "code": "grandparent", "label": "Grandparent", "grants_acting_rights": True}))  # fmt: skip
    ok(client.post(f"{API}/clients/{grandparent}/relationships", headers=owner,
                   json={"other_client_id": kid, "relationship_type_id": minds["id"]}))  # fmt: skip
    seen = ok(client.get(f"{API}/portal/clients/{kid}", headers=theirs), 200)
    assert (seen["authority"], seen["is_adult"], seen["is_my_ward"], seen["age_confirmed"]) == (
        "delegate", None, False, None)  # no age signal  # fmt: skip
    refused(client.post(f"{API}/portal/rentals", headers=theirs,
                        json=online(f, grandparent, 15, 16) | {"player_client_ids": [kid]}), 422,
            "minor-needs-guardian")  # fmt: skip
    ok(client.post(f"{API}/portal/rentals", headers=theirs, json=online(f, grandparent, 15, 16)))  # alone is fine


def test_coaching_keeps_its_rules_a_parent_registers_a_child(client, owner, tenant, f):
    """Sessions are not rentals: a parent may still register a child alone (dropped off at coaching)."""
    policy(client, owner, f)
    seat = ok(book(client, owner, f, [f.coach], at(13, SOON), at(14, SOON), kind="session"))["booking"]["session"]
    me, portal = portal_client(client, owner, tenant, f)
    kid = new_client(client, owner, f.location, first_name="Kit", birth_on=CHILD)["id"]
    parent_of = next(
        t for t in ok(client.get(f"{API}/relationship-types", headers=owner), 200) if t["code"] == "parent_of"
    )
    ok(client.post(f"{API}/clients/{me}/relationships", headers=owner,
                   json={"other_client_id": kid, "relationship_type_id": parent_of["id"]}))  # fmt: skip
    enrolled = ok(client.post(f"{API}/portal/enrollments", headers=portal,
                              json={"client_id": kid, "session_id": seat["id"]}))  # fmt: skip
    assert enrolled["client_id"] == kid and enrolled["status"] == "enrolled"


# --- the portal fails closed on birth dates (nobody is at the desk to look) --------------------------------------


def test_portal_holder_needs_a_birth_date_and_a_first_one_is_flagged_for_staff(client, owner, tenant, f):
    me, portal = portal_client(client, owner, tenant, f, birth_on=None)
    refused(client.post(f"{API}/portal/rentals", headers=portal, json=online(f, me, 15, 16)), 422,
            "birth-date-required")  # fmt: skip
    assert ok(client.get(f"{API}/portal/clients/{me}", headers=portal), 200)["is_adult"] is False
    ok(client.patch(f"{API}/portal/clients/{me}", headers=portal, json={"birth_on": "1990-01-02"}), 200)
    assert ok(client.get(f"{API}/clients/{me}", headers=owner), 200)["is_birth_on_unverified"] is True
    with tenant_session(tenant.id) as session:
        record = session.scalars(
            select(AuditEvent).where(AuditEvent.entity_id == me, AuditEvent.action == "clients.client.update")
        ).one()
    assert (
        record.changes["birth_on"] is True
        and ok(client.get(f"{API}/clients/{me}", headers=owner), 200)["age_confirmed"] is False
    )
    # Owner decision 2026-11-13: a self-declared adult books and pays, but is told the first entry code waits for
    # staff to confirm the age once; the date is not trusted for entry until then.
    ok(client.patch(f"{API}/locations/{f.location}", headers=owner, json={"phone": "217-555-0100"}), 200)
    me_seen = ok(client.get(f"{API}/portal/clients/{me}", headers=portal), 200)
    assert (me_seen["is_adult"], me_seen["age_confirmed"]) == (True, False)
    checkout = ok(client.post(f"{API}/portal/rentals", headers=portal, json=online(f, me, 15, 16)))
    assert checkout["entry_code_notice"].startswith("Your entry code will be sent once our staff have confirmed")
    assert "217-555-0100" in checkout["entry_code_notice"] == me_seen["entry_code_notice"]
    ok(client.post(f"{API}/clients/{me}/age-confirmation", headers=owner, json={}), 200)  # the same date, confirmed
    me_seen = ok(client.get(f"{API}/portal/clients/{me}", headers=portal), 200)
    assert (me_seen["age_confirmed"], me_seen["entry_code_notice"]) == (True, None)
    assert (
        ok(client.post(f"{API}/portal/rentals", headers=portal, json=online(f, me, 16, 17)))["entry_code_notice"]
        is None
    )


def test_a_self_declared_adult_pays_online_and_a_self_declared_minor_still_cannot_hold(client, owner, tenant, f):
    me, portal = portal_client(client, owner, tenant, f, birth_on=None)
    ok(client.patch(f"{API}/portal/clients/{me}", headers=portal, json={"birth_on": "1990-01-02"}), 200)
    checkout = ok(client.post(f"{API}/portal/rentals", headers=portal, json=online(f, me, 15, 16)))
    assert checkout["payment_required"] and checkout["entry_code_notice"]  # told before paying
    paid = ok(client.post(f"{API}/portal/rentals/{checkout['rental']['id']}/confirm",
                          headers=portal | {"Idempotency-Key": uuid4().hex},
                          json={"provider_payment_token": "tok_card_ok"}), 200)  # fmt: skip
    assert paid["rental"]["status"] == "confirmed" and paid["entry_code_notice"] == checkout["entry_code_notice"]
    kid, kid_portal = portal_client(client, owner, tenant, f, birth_on=None)
    ok(client.patch(f"{API}/portal/clients/{kid}", headers=kid_portal, json={"birth_on": CHILD}), 200)
    refused(client.post(f"{API}/portal/rentals", headers=kid_portal, json=online(f, kid, 15, 16)), 422,
            "minor-cannot-hold-rental")  # fmt: skip


def test_a_portal_dependant_needs_a_birth_date_and_never_holds_the_rental(client, owner, tenant, f):
    """A parent acting for a child they added resolves to `manager` authority: the server, not the authority,
    decides who may hold (`is_adult`) and who may play (`is_my_ward`)."""
    me, portal = portal_client(client, owner, tenant, f)
    parent_of = next(t for t in ok(client.get(f"{API}/portal/relationship-types", headers=portal), 200)
                     if t["code"] == "parent_of")  # fmt: skip
    child = {"relationship_type_id": parent_of["id"], "first_name": "Kit", "last_name": "Pat"}
    assert client.post(f"{API}/portal/dependents", headers=portal, json=child).status_code == 422
    kid = ok(
        client.post(
            f"{API}/portal/dependents", headers=portal, json=child | {"birth_on": CHILD, "birth_on_declared": True}
        ),
        201,
    )
    assert (kid["authority"], kid["is_adult"], kid["is_my_ward"]) == ("manager", False, True)
    assert ok(client.get(f"{API}/clients/{kid['id']}", headers=owner), 200)["is_birth_on_unverified"] is True
    refused(client.post(f"{API}/portal/rentals", headers=portal, json=online(f, kid["id"], 15, 16)), 422,
            "minor-cannot-hold-rental")  # fmt: skip
    ok(client.post(f"{API}/portal/rentals", headers=portal,
                   json=online(f, me, 15, 16) | {"player_client_ids": [kid["id"]]}))  # fmt: skip


def test_a_dateless_dependant_online_counts_as_a_minor(client, owner, tenant, f):
    """Dependants added before birth dates were required: the parent manages them, the date is unknown."""
    me, portal = portal_client(client, owner, tenant, f)
    parent_of = next(t for t in ok(client.get(f"{API}/portal/relationship-types", headers=portal), 200)
                     if t["code"] == "parent_of")  # fmt: skip
    kid = ok(client.post(f"{API}/portal/dependents", headers=portal, json={
        "relationship_type_id": parent_of["id"], "first_name": "Kit", "last_name": "Pat", "birth_on": CHILD, "birth_on_declared": True}), 201)["id"]  # fmt: skip
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        session.execute(update(Client).where(Client.id == kid).values(birth_on=None))
    refused(client.post(f"{API}/portal/rentals", headers=portal, json=online(f, kid, 15, 16)), 422,
            "birth-date-required")  # fmt: skip
    ok(
        client.post(f"{API}/portal/rentals", headers=portal, json=online(f, me, 15, 16) | {"player_client_ids": [kid]})
    )  # the guardian may bring them


# --- the staff queue of age checks (owner decision 2026-11-13) --------------------------------------------------


def test_staff_get_one_notice_on_a_newcomers_first_booking_and_a_queue_with_bookers_first(
    client, owner, tenant, f, mailbox
):
    ok(client.patch(f"{API}/locations/{f.location}", headers=owner, json={"alert_email": "desk@example.com"}), 200)
    waiting = new_client(client, owner, f.location, birth_on="1980-01-01")["id"]  # unconfirmed, no booking
    me, portal = portal_client(client, owner, tenant, f, birth_on=None)
    ok(client.patch(f"{API}/portal/clients/{me}", headers=portal, json={"birth_on": "1990-01-02"}), 200)
    mailbox.clear()
    ok(client.post(f"{API}/portal/rentals", headers=portal, json=online(f, me, 17, 18)))
    ok(client.post(f"{API}/portal/rentals", headers=portal, json=online(f, me, 15, 16)))
    notices = [m for m in mailbox if m.to == "desk@example.com"]
    assert len(notices) == 1 and "age" in notices[0].subject.lower()  # one, not one per booking
    assert "1990" not in notices[0].body  # no birth date in the email
    page = ok(client.get(f"{API}/client-age-reviews?include=total", headers=owner), 200)
    ids = [row["id"] for row in page["data"]]
    assert ids.index(me) < ids.index(waiting) and page["page"]["total"] >= 2  # a booker first
    first = page["data"][ids.index(me)]
    assert datetime.fromisoformat(first["earliest_booking_at"]) == datetime.fromisoformat(at(15))  # the earliest
    one = ok(client.get(f"{API}/client-age-reviews?limit=1", headers=owner), 200)
    assert one["page"]["has_more"] and ok(client.get(
        f"{API}/client-age-reviews?limit=1&cursor={one['page']['next_cursor']}", headers=owner), 200)["data"]  # fmt: skip
    ok(client.post(f"{API}/clients/{me}/age-confirmation", headers=owner, json={}), 200)
    assert me not in [r["id"] for r in ok(client.get(f"{API}/client-age-reviews", headers=owner), 200)["data"]]
    elsewhere = ok(client.post(f"{API}/locations", headers=owner, json={
        "name": f"Elsewhere {uuid4().hex[:4]}", "time_zone": "America/Chicago", "country_code": "US"}))["id"]  # fmt: skip
    away = login(client, tenant, add_staff(tenant, "front_desk", location_ids=[elsewhere])[0])
    assert waiting not in [r["id"] for r in ok(client.get(f"{API}/client-age-reviews", headers=away), 200)["data"]]
    coach = login(client, tenant, add_staff(tenant, "coach", all_locations=True)[0])
    assert client.get(f"{API}/client-age-reviews", headers=coach).status_code == 403


def test_a_refused_booking_neither_tells_staff_nor_burns_the_one_notice(client, owner, tenant, f, mailbox):
    """The notice is noted only once the rental is written, in the same transaction: a 409 that commits (the
    document prompt) leaves nothing behind."""
    from app.modules.rentals.models import RentalBooking

    ok(client.patch(f"{API}/locations/{f.location}", headers=owner, json={"alert_email": "desk@example.com"}), 200)
    me, portal = portal_client(client, owner, tenant, f)  # a self-typed adult date: unconfirmed
    kid = new_client(client, owner, f.location, first_name="Kit", birth_on=CHILD)["id"]
    parent_of = next(t for t in ok(client.get(f"{API}/relationship-types", headers=owner), 200)
                     if t["code"] == "parent_of")  # fmt: skip
    ok(client.post(f"{API}/clients/{me}/relationships", headers=owner,
                   json={"other_client_id": kid, "relationship_type_id": parent_of["id"]}))  # fmt: skip
    cover = _junior_plan(client, owner, f, kid)
    bought = ok(client.get(f"{API}/rental-plan-purchases/{cover['rental_plan_purchase_id']}", headers=owner), 200)
    bind_waiver(client, owner, {"id": bought["rental_plan_id"]})
    mailbox.clear()
    payload = online(f, me, 15, 16) | {
        "player_client_ids": [kid],
        "rental_plan_purchase_id": cover["rental_plan_purchase_id"],
    }
    refused(client.post(f"{API}/portal/rentals", headers=portal | {"Idempotency-Key": uuid4().hex}, json=payload),
            409, "document-required")  # fmt: skip
    with tenant_session(tenant.id) as session:
        row = session.get(Client, me)
        assert (row.age_review_notified_at, row.earliest_booking_at) == (None, None)
        assert not session.scalars(select(RentalBooking)).all()
    assert not [m for m in mailbox if m.to == "desk@example.com"]
    ok(client.post(f"{API}/portal/rentals", headers=portal, json=online(f, me, 17, 18)))  # a booking that lands
    assert len([m for m in mailbox if m.to == "desk@example.com"]) == 1


def test_someone_booking_for_another_adult_gets_no_age_signal(client, owner, tenant, f):
    """The entry-code notice says the holder's age waits for staff: only the person themselves is told, never a
    manager (or anyone else) booking in their name."""
    from app.modules import clients
    from app.modules.clients.models import ClientPortalAccess

    helper, theirs = portal_client(client, owner, tenant, f)
    adult = new_client(client, owner, f.location, first_name="Ada", birth_on="1990-01-02")["id"]  # unconfirmed
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        identity = session.scalars(select(ClientPortalAccess.identity_id).where(
            ClientPortalAccess.client_id == helper)).one()  # fmt: skip
        clients.service.link_identity(session, adult, identity, is_primary=False)
    checkout = ok(client.post(f"{API}/portal/rentals", headers=theirs, json=online(f, adult, 15, 16)))
    assert checkout["entry_code_notice"] is None
    paid = ok(client.post(f"{API}/portal/rentals/{checkout['rental']['id']}/confirm",
                          headers=theirs | {"Idempotency-Key": uuid4().hex},
                          json={"provider_payment_token": "tok_card_ok"}), 200)  # fmt: skip
    assert paid["entry_code_notice"] is None
    mine = ok(client.post(f"{API}/portal/rentals", headers=theirs, json=online(f, helper, 17, 18)))
    assert mine["entry_code_notice"]  # their own booking: they are told


def test_a_newcomers_first_session_enrolment_feeds_the_queue_and_the_one_notice(client, owner, tenant, f, mailbox):
    """Entry codes are held for coaching sessions too: a session enrolment counts as a booking for the age check.
    A child enrolled by a parent never gets a code, so it tells staff nothing."""
    ok(client.patch(f"{API}/locations/{f.location}", headers=owner, json={"alert_email": "desk@example.com"}), 200)
    policy(client, owner, f)
    seat = ok(book(client, owner, f, [f.coach], at(13, SOON), at(14, SOON), kind="session"))["booking"]["session"]
    me, portal = portal_client(client, owner, tenant, f)
    kid = new_client(client, owner, f.location, first_name="Kit", birth_on=CHILD)["id"]
    parent_of = next(t for t in ok(client.get(f"{API}/relationship-types", headers=owner), 200)
                     if t["code"] == "parent_of")  # fmt: skip
    ok(client.post(f"{API}/clients/{me}/relationships", headers=owner,
                   json={"other_client_id": kid, "relationship_type_id": parent_of["id"]}))  # fmt: skip
    mailbox.clear()
    ok(client.post(f"{API}/portal/enrollments", headers=portal, json={"client_id": kid, "session_id": seat["id"]}))
    assert not [m for m in mailbox if m.to == "desk@example.com"]
    ok(client.post(f"{API}/portal/enrollments", headers=portal, json={"client_id": me, "session_id": seat["id"]}))
    assert len([m for m in mailbox if m.to == "desk@example.com"]) == 1
    rows = ok(client.get(f"{API}/client-age-reviews", headers=owner), 200)["data"]
    [mine] = [r for r in rows if r["id"] == me]
    assert datetime.fromisoformat(mine["earliest_booking_at"]) == datetime.fromisoformat(at(13, SOON))
    with tenant_session(tenant.id) as session:
        assert session.get(Client, kid).earliest_booking_at is None


# --- member pricing for families: the holder is a member, or every listed player is covered ----------------------


def priced(client, owner, f, holder: str, *players: str) -> tuple[int, int]:
    """(preview subtotal, charged subtotal) for a 10:00 hour: member $20, guest $24."""
    payload = body(f, holder, 15, 16, parties=[{"client_id": p} for p in players])
    preview = ok(client.post(f"{API}/rentals/preview", headers=owner, json=payload), 200)["quote"]["subtotal_minor"]
    created = ok(rent(client, owner, payload))
    ok(client.post(f"{API}/rentals/{created['rental']['id']}/cancel", headers=owner, json={}), 200)
    return preview, created["quote"]["subtotal_minor"]


def test_a_member_parent_with_a_child_pays_the_member_price(client, owner, f):
    parent, kid = family(client, owner, f)
    join(client, owner, f, parent, DAY - timedelta(days=10))
    assert priced(client, owner, f, parent, kid) == (2000, 2000)


def test_a_non_member_parent_with_a_child_who_holds_a_junior_membership_pays_the_member_price(client, owner, f):
    parent, kid = family(client, owner, f)
    join(client, owner, f, kid, DAY - timedelta(days=10))
    assert priced(client, owner, f, parent, kid) == (2000, 2000)
    assert priced(client, owner, f, parent) == (2400, 2400)  # the child is not playing: the holder pays as a guest


def test_a_child_named_on_a_shared_membership_is_covered(client, owner, f):
    parent, kid = family(client, owner, f)
    sharer = new_client(client, owner, f.location)["id"]  # another family member holds the membership
    contract = join(client, owner, f, sharer, DAY - timedelta(days=10))
    ok(client.post(f"{API}/membership-contracts/{contract}/shares", headers=owner, json={"client_id": kid}), 201)
    assert priced(client, owner, f, parent, kid) == (2000, 2000)


def test_one_covered_child_and_one_uncovered_friend_pay_the_guest_price(client, owner, f):
    parent, kid = family(client, owner, f)
    join(client, owner, f, kid, DAY - timedelta(days=10))
    friend = new_client(client, owner, f.location)["id"]  # not a member, holds no share
    assert priced(client, owner, f, parent, kid, friend) == (2400, 2400)


def test_an_unrelated_member_listed_by_a_guest_holder_never_lowers_the_price(client, owner, f):
    """The family rule needs the holder to be each player's guardian: listing any member at the desk is not enough."""
    guest = new_client(client, owner, f.location, first_name="Gus")["id"]
    stranger = new_client(client, owner, f.location, first_name="Stan")["id"]
    join(client, owner, f, stranger, DAY - timedelta(days=10))
    assert priced(client, owner, f, guest, stranger) == (2400, 2400)


def test_a_covered_child_and_a_covered_friend_who_is_not_the_holders_ward_pay_the_guest_price(client, owner, f):
    parent, kid = family(client, owner, f)
    friend = new_client(client, owner, f.location, first_name="Fay")["id"]
    for who in (kid, friend):
        join(client, owner, f, who, DAY - timedelta(days=10))
    assert priced(client, owner, f, parent, kid, friend) == (2400, 2400)
