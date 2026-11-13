"""Guest checkout for program groups (REG-12): off by default, a new card only, always new clients, the guest token
as the only key, and blocking documents refuse guests."""

from uuid import UUID, uuid4

import pytest

from app.modules.documents.tests.support import template
from app.modules.programs.tests.test_checkout import online
from app.modules.programs.tests.test_groups import group_of
from app.modules.scheduling.tests.helpers import API, facility, ok

GUEST = f"{API}/public/guest-checkouts"


@pytest.fixture
def f(client, owner):
    return facility(client, owner)


def public(tenant) -> dict:
    return {"X-Tenant-Slug": tenant.slug}


def keyed(headers: dict) -> dict:
    return headers | {"Idempotency-Key": f"k-{uuid4().hex}"}


def allow_guests(client, owner, group_id: str):
    body = {"is_enabled": True, "payment_requirement": "immediate_card_payment", "allows_guest_checkout": True}
    ok(client.put(f"{API}/program-groups/{group_id}/registration-config", headers=owner, json=body), 200)


def start(client, tenant, f, camp, fee, email="guest@example.com"):
    body = {"location_id": f.location, "payer": {"first_name": "Gale", "last_name": "Guest", "email": email, "birth_on": "1985-02-03"},
            "participants": [{"first_name": "Kit", "last_name": "Guest", "birth_on": "2015-04-01"}],
            "items": [{"program_group_id": camp["id"], "program_fee_id": fee["id"], "participant": 0}]}  # fmt: skip
    return client.post(GUEST, headers=public(tenant), json=body)


def test_guest_checkout_is_off_by_default(client, owner, tenant, f):
    camp, fee = online(client, owner, f, "immediate_card_payment")
    assert start(client, tenant, f, camp, fee).status_code == 404


def test_guest_pays_by_new_card_and_gets_new_clients_every_time(client, owner, tenant, f):
    camp, fee = online(client, owner, f, "immediate_card_payment")
    allow_guests(client, owner, camp["id"])
    cart = ok(start(client, tenant, f, camp, fee))
    token, confirm = cart["guest_token"], f"{GUEST}/{cart['id']}/confirm"
    assert token and cart["total_minor"] == 9000

    wrong = client.post(confirm, headers=keyed(public(tenant)),
                        json={"guest_token": "fhg_" + "x" * 40, "method_token": "tok_card_ok"})  # fmt: skip
    assert wrong.status_code == 404
    declined = client.post(confirm, headers=keyed(public(tenant)),
                           json={"guest_token": token, "method_token": "tok_card_declined"})  # fmt: skip
    assert declined.status_code in (402, 409), declined.text
    paid = ok(client.post(confirm, headers=keyed(public(tenant)),
                          json={"guest_token": token, "method_token": "tok_card_ok"}), 200)  # fmt: skip
    assert paid["status"] == "completed" and group_of(client, owner, camp["id"])["enrolled_count"] == 1
    assert "guest_token" not in paid or paid["guest_token"] is None

    again = ok(start(client, tenant, f, camp, fee))  # the same email again: never matched to the first payer
    ok(client.post(f"{GUEST}/{again['id']}/confirm", headers=keyed(public(tenant)),
                   json={"guest_token": again["guest_token"], "method_token": "tok_card_ok"}), 200)  # fmt: skip
    found = ok(client.get(f"{API}/clients", headers=owner, params={"q": "guest@example.com"}), 200)["data"]
    assert [c["first_name"] for c in found].count("Gale") == 2  # two payers; each child shares its payer's email


def test_abandon_releases_the_place(client, owner, tenant, f):
    camp, fee = online(client, owner, f, "immediate_card_payment")
    allow_guests(client, owner, camp["id"])
    cart = ok(start(client, tenant, f, camp, fee))
    assert group_of(client, owner, camp["id"])["enrolled_count"] == 1
    gone = client.post(
        f"{GUEST}/{cart['id']}/abandon", headers=public(tenant), json={"guest_token": cart["guest_token"]}
    )
    assert ok(gone, 200)["status"] == "abandoned" and group_of(client, owner, camp["id"])["enrolled_count"] == 0


def test_blocking_documents_refuse_guests(client, owner, tenant, f):
    camp, fee = online(client, owner, f, "immediate_card_payment")
    allow_guests(client, owner, camp["id"])
    body = {"scope_type": "program_group", "scope_id": camp["id"], "template_id": template(client, owner)["id"]}
    assert client.put(f"{API}/document-bindings", headers=owner, json=body).status_code in (200, 201)
    refused = start(client, tenant, f, camp, fee)
    assert (refused.status_code, refused.json()["code"]) == (409, "guest-documents-required")


def guest_clients(tenant, email: str) -> list:
    from sqlalchemy import select

    from app.core.db.session import tenant_session
    from app.modules.clients.models import Client

    with tenant_session(tenant.id) as session:
        return list(session.scalars(select(Client.id).where(Client.primary_email == email)))


def details_of(tenant, checkout_id: str):
    from app.core.db.session import tenant_session
    from app.modules.programs.models import RegistrationCheckout

    with tenant_session(tenant.id) as session:
        return session.get(RegistrationCheckout, UUID(checkout_id)).guest_details


def test_guest_details_wait_on_the_checkout_until_payment(client, owner, tenant, f):
    """No client record exists for a guest until the payment goes through; the details wait on the checkout and
    are purged when it completes, is abandoned or expires. The place is held all the same."""
    from datetime import timedelta

    from app.core import clock
    from app.core.auth import system_principal
    from app.core.db.session import tenant_session
    from app.modules.programs import checkout
    from app.modules.programs.models import RegistrationCheckout

    camp, fee = online(client, owner, f, "immediate_card_payment")
    allow_guests(client, owner, camp["id"])
    cart = ok(start(client, tenant, f, camp, fee, email="wait@example.com"))
    assert [(i["client_name"], i["status"]) for i in cart["items"]] == [("Kit Guest", "pending")]
    assert group_of(client, owner, camp["id"])["enrolled_count"] == 1  # held before payment
    assert guest_clients(tenant, "wait@example.com") == []
    assert details_of(tenant, cart["id"])["payer"]["email"] == "wait@example.com"
    confirm = f"{GUEST}/{cart['id']}/confirm"
    declined = client.post(confirm, headers=keyed(public(tenant)),
                           json={"guest_token": cart["guest_token"], "method_token": "tok_card_declined"})  # fmt: skip
    assert declined.status_code in (402, 409) and guest_clients(tenant, "wait@example.com") == []
    paid = ok(client.post(confirm, headers=keyed(public(tenant)),
                          json={"guest_token": cart["guest_token"], "method_token": "tok_card_ok"}), 200)  # fmt: skip
    assert paid["status"] == "completed" and [i["client_name"] for i in paid["items"]] == ["Kit Guest"]
    assert len(guest_clients(tenant, "wait@example.com")) == 2 and details_of(tenant, cart["id"]) is None
    assert group_of(client, owner, camp["id"])["enrolled_count"] == 1

    gone = ok(start(client, tenant, f, camp, fee, email="gone@example.com"))
    ok(
        client.post(f"{GUEST}/{gone['id']}/abandon", headers=public(tenant), json={"guest_token": gone["guest_token"]}),
        200,
    )
    late = ok(start(client, tenant, f, camp, fee, email="late@example.com"))
    assert group_of(client, owner, camp["id"])["enrolled_count"] == 2
    with tenant_session(tenant.id) as session:
        session.get(RegistrationCheckout, UUID(late["id"])).expires_at = clock.now() - timedelta(minutes=1)
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        assert checkout.expire_holds(session) == 1
    assert group_of(client, owner, camp["id"])["enrolled_count"] == 1
    for cart_id, email in ((gone["id"], "gone@example.com"), (late["id"], "late@example.com")):
        assert details_of(tenant, cart_id) is None and guest_clients(tenant, email) == []


def test_guest_clients_are_unverified_and_skip_client_created_automations(client, owner, tenant, f):
    from sqlalchemy import func, select

    from app.core.auth import system_principal
    from app.core.db.session import tenant_session
    from app.core.events import OutboxEvent
    from app.modules.clients.models import ClientEmail
    from app.modules.engagement import handlers
    from app.modules.engagement.models import ScheduledNotification

    body = {"name": "Welcome", "subject": "Welcome", "body_text": "Hi $first_name"}
    message = ok(client.post(f"{API}/message-templates", headers=owner, json=body), 201)
    ok(client.post(f"{API}/automation-rules", headers=owner, json={
        "name": "Welcome", "trigger_event_type": "clients.client.created", "message_template_id": message["id"],
    }), 201)  # fmt: skip
    camp, fee = online(client, owner, f, "immediate_card_payment")
    allow_guests(client, owner, camp["id"])
    cart = ok(start(client, tenant, f, camp, fee, email="quiet@example.com"))
    ok(client.post(f"{GUEST}/{cart['id']}/confirm", headers=keyed(public(tenant)),
                   json={"guest_token": cart["guest_token"], "method_token": "tok_card_ok"}), 200)  # fmt: skip
    made = guest_clients(tenant, "quiet@example.com")
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        assert session.scalar(select(func.count()).where(ClientEmail.client_id.in_(made),
                                                         ClientEmail.verified_at.is_not(None))) == 0  # fmt: skip
        events = session.scalars(select(OutboxEvent).where(
            OutboxEvent.event_type == "clients.client.created", OutboxEvent.aggregate_id.in_(made))).all()  # fmt: skip
        assert len(events) == 2 and {e.payload["source"] for e in events} == {"guest"}
        deliveries = [(str(e.id), e.payload) for e in events]
    for event_id, payload in deliveries:
        handlers.on_client_created.fn(str(tenant.id), event_id, payload)
    with tenant_session(tenant.id) as session:
        assert session.scalar(select(func.count()).where(ScheduledNotification.client_id.in_(made))) == 0


def test_guest_create_is_limited_per_address_and_per_ip(client, owner, tenant, f, monkeypatch):
    from app.core.settings import get_settings

    camp, fee = online(client, owner, f, "immediate_card_payment")
    allow_guests(client, owner, camp["id"])
    body = {"location_id": f.location, "payer": {"first_name": "Gale", "last_name": "Guest", "email": "g@example.com",
            "birth_on": "1985-02-03"}, "items": [{"program_group_id": camp["id"], "program_fee_id": fee["id"]}],
            "participants": [{"first_name": f"K{n}", "last_name": "Guest", "birth_on": "2015-04-01"} for n in range(5)]}  # fmt: skip
    assert client.post(GUEST, headers=public(tenant), json=body).status_code == 422  # at most 4 participants

    cfg = get_settings().rate_limit
    monkeypatch.setattr(cfg, "enabled", True)
    assert cfg.buckets["guest-checkout-create"].limit == 5
    monkeypatch.setitem(cfg.buckets, "guest-checkout-create",
                        cfg.buckets["guest-checkout-create"].model_copy(update={"limit": 1000}))  # fmt: skip
    monkeypatch.setitem(cfg.buckets, "guest-checkout-email",
                        cfg.buckets["guest-checkout-email"].model_copy(update={"limit": 1}))  # fmt: skip
    ok(start(client, tenant, f, camp, fee, email="once@example.com"))
    again = start(client, tenant, f, camp, fee, email="ONCE@example.com")
    assert (again.status_code, again.json()["code"]) == (429, "rate-limited")
    assert (
        guest_clients(tenant, "ONCE@example.com") == [] and group_of(client, owner, camp["id"])["enrolled_count"] == 1
    )

    monkeypatch.setitem(cfg.buckets, "guest-checkout-create",
                        cfg.buckets["guest-checkout-create"].model_copy(update={"limit": 1}))  # fmt: skip
    monkeypatch.setitem(cfg.buckets, "guest-checkout-email",
                        cfg.buckets["guest-checkout-email"].model_copy(update={"limit": 1000}))  # fmt: skip
    limited = [start(client, tenant, f, camp, fee, email=f"ip{n}@example.com").status_code for n in range(2)]
    assert 429 in limited


def test_guests_see_and_pay_the_full_price_of_a_plan_program(client, owner, tenant, f):
    camp, _ = online(client, owner, f, "immediate_card_payment")
    fee = ok(client.post(f"{API}/program-groups/{camp['id']}/fees", headers=owner,
                         json={"description": "Plan", "amount_minor": 6000, "deposit_minor": 1000}))  # fmt: skip
    body = {"is_enabled": True, "payment_requirement": "immediate_card_payment", "allows_guest_checkout": True,
            "payment_plan": "deposit", "balance_due_on": "2031-06-01"}  # fmt: skip
    ok(client.put(f"{API}/program-groups/{camp['id']}/registration-config", headers=owner, json=body), 200)
    url = f"{API}/public/program-groups/{camp['id']}"
    member_view = ok(client.get(url, headers=public(tenant)), 200)
    assert member_view["payment_plan"] == "deposit"
    guest_view = ok(client.get(url, headers=public(tenant), params={"guest": "true"}), 200)
    assert (guest_view["payment_plan"], guest_view["balance_due_on"]) == ("pay_in_full", None)
    assert {f_["id"]: (f_["amount_minor"], f_["deposit_minor"]) for f_ in guest_view["fees"]}[fee["id"]] == (6000, None)
    cart = ok(start(client, tenant, f, camp, fee))
    assert cart["total_minor"] == 6000
    ok(client.post(f"{GUEST}/{cart['id']}/confirm", headers=keyed(public(tenant)),
                   json={"guest_token": cart["guest_token"], "method_token": "tok_card_ok"}), 200)  # fmt: skip
    from app.core.db.session import tenant_session
    from app.modules.programs.models import RegistrationCheckout

    with tenant_session(tenant.id) as session:
        invoice_id = session.get(RegistrationCheckout, UUID(cart["id"])).invoice_id
    bill = ok(client.get(f"{API}/invoices/{invoice_id}", headers=owner), 200)
    assert (bill["balance_minor"], bill["status"]) == (0, "paid")
    assert bill["is_autopay"] is False  # paid in full once: nothing left for an autopay run


def _rows_of(tenant, checkout_id: str) -> tuple[int, object]:
    from sqlalchemy import func, select

    from app.core.db.session import tenant_session
    from app.modules.programs.models import Enrollment, RegistrationCheckout

    with tenant_session(tenant.id) as session:
        count = session.scalar(select(func.count()).where(Enrollment.checkout_id == UUID(checkout_id)))
        return count, session.get(RegistrationCheckout, UUID(checkout_id)).invoice_id


def test_a_held_place_is_not_paid_for_once_the_program_stops_taking_registrations(client, owner, tenant, f):
    """A guest's place is held with no roster row, so confirm checks again that the program is still open:
    deleted, completed or past its closing date refuses before any client, charge or registration exists."""
    from datetime import timedelta

    from app.core import clock
    from app.core.db.session import tenant_session
    from app.modules.programs.models import ProgramGroup

    def held(email: str) -> tuple[dict, dict]:
        camp, fee = online(client, owner, f, "immediate_card_payment", name=f"Camp {uuid4().hex[:6]}")
        allow_guests(client, owner, camp["id"])
        return camp, ok(start(client, tenant, f, camp, fee, email=email))

    def pay(cart: dict):
        return client.post(f"{GUEST}/{cart['id']}/confirm", headers=keyed(public(tenant)),
                           json={"guest_token": cart["guest_token"], "method_token": "tok_card_ok"})  # fmt: skip

    camp, cart = held("deleted@example.com")
    with tenant_session(tenant.id) as session:  # deleted under the hold (the staff route now refuses, below)
        session.get(ProgramGroup, UUID(camp["id"])).deleted_at = clock.now()
    refused = pay(cart)
    assert (refused.status_code, refused.json()["code"]) == (409, "program-not-active")
    assert guest_clients(tenant, "deleted@example.com") == [] and _rows_of(tenant, cart["id"]) == (0, None)

    camp, cart = held("completed@example.com")
    ok(client.post(f"{API}/program-groups/{camp['id']}/complete", headers=owner), 200)
    refused = pay(cart)
    assert (refused.status_code, refused.json()["code"]) == (409, "program-not-active")
    assert guest_clients(tenant, "completed@example.com") == [] and _rows_of(tenant, cart["id"]) == (0, None)

    camp, cart = held("closed@example.com")
    yesterday = (clock.now() - timedelta(days=2)).date().isoformat()
    body = {"is_enabled": True, "payment_requirement": "immediate_card_payment", "allows_guest_checkout": True,
            "closes_on": yesterday}  # fmt: skip
    ok(client.put(f"{API}/program-groups/{camp['id']}/registration-config", headers=owner, json=body), 200)
    refused = pay(cart)
    assert (refused.status_code, refused.json()["code"]) == (409, "registration-closed")
    assert guest_clients(tenant, "closed@example.com") == [] and _rows_of(tenant, cart["id"]) == (0, None)


def test_staff_cannot_delete_or_archive_a_program_while_a_guest_holds_a_place(client, owner, tenant, f):
    camp, fee = online(client, owner, f, "immediate_card_payment")
    allow_guests(client, owner, camp["id"])
    week = ok(client.post(f"{API}/program-groups", headers=owner, json={"parent_id": camp["id"], "name": "Wk 1"}))
    body = {"is_enabled": True, "payment_requirement": "immediate_card_payment", "allows_guest_checkout": True}
    ok(client.put(f"{API}/program-groups/{week['id']}/registration-config", headers=owner, json=body), 200)
    week_fee = ok(client.post(f"{API}/program-groups/{week['id']}/fees", headers=owner,
                              json={"description": "Week", "amount_minor": 2000}))  # fmt: skip
    cart = ok(start(client, tenant, f, week, week_fee))
    for parent_or_node in (camp["id"], week["id"]):
        gone = client.delete(f"{API}/program-groups/{parent_or_node}", headers=owner)
        assert (gone.status_code, gone.json()["code"]) == (409, "has-guest-holds")
        archived = client.post(f"{API}/program-groups/{parent_or_node}/archive", headers=owner)
        assert (archived.status_code, archived.json()["code"]) == (409, "has-guest-holds")
    abandon = client.post(
        f"{GUEST}/{cart['id']}/abandon", headers=public(tenant), json={"guest_token": cart["guest_token"]}
    )
    ok(abandon, 200)
    assert client.delete(f"{API}/program-groups/{week['id']}", headers=owner).status_code == 204


def test_one_address_holds_at_most_four_unpaid_places_in_a_program(client, owner, tenant, f):
    """Without paying, one IP holds at most four places of a program at a time (as many as one basket), and a
    basket carries at most four places."""
    camp, fee = online(client, owner, f, "immediate_card_payment")
    allow_guests(client, owner, camp["id"])
    other, other_fee = online(client, owner, f, "immediate_card_payment", name="Other")
    allow_guests(client, owner, other["id"])
    payer = {"first_name": "Gale", "last_name": "Guest", "email": "cap@example.com", "birth_on": "1985-02-03"}
    kids = [{"first_name": f"K{n}", "last_name": "Guest", "birth_on": "2015-04-01"} for n in range(4)]

    def basket(group, fee_id, people: list[int | None]):
        items = [{"program_group_id": group["id"], "program_fee_id": fee_id, "participant": p} for p in people]
        body = {"location_id": f.location, "payer": payer, "participants": kids, "items": items}
        return client.post(GUEST, headers=public(tenant), json=body)

    assert basket(camp, fee["id"], [None, 0, 1, 2, 3]).status_code == 422  # five items in one basket
    first = ok(basket(camp, fee["id"], [0, 1, 2]))
    ok(basket(camp, fee["id"], [3]))  # four held now
    over = basket(camp, fee["id"], [None])
    assert (over.status_code, over.json()["code"]) == (409, "too-many-held-places")
    assert group_of(client, owner, camp["id"])["enrolled_count"] == 4
    ok(basket(other, other_fee["id"], [None]))  # per program
    ok(client.post(f"{GUEST}/{first['id']}/abandon", headers=public(tenant),
                   json={"guest_token": first["guest_token"]}), 200)  # fmt: skip
    again = ok(basket(camp, fee["id"], [None]))  # released places no longer count
    assert details_of(tenant, again["id"])["ip_digest"]  # hashed, and cleared with the other details


def test_the_hold_cap_counts_every_week_of_a_program(client, owner, tenant, f):
    """Places held in sibling weeks count against their shared program, so splitting across weeks gains nothing."""
    camp, _ = online(client, owner, f, "immediate_card_payment")
    allow_guests(client, owner, camp["id"])
    weeks = []
    for n in range(3):
        week = ok(
            client.post(f"{API}/program-groups", headers=owner, json={"parent_id": camp["id"], "name": f"Wk {n}"})
        )
        body = {"is_enabled": True, "payment_requirement": "immediate_card_payment", "allows_guest_checkout": True}
        ok(client.put(f"{API}/program-groups/{week['id']}/registration-config", headers=owner, json=body), 200)
        fee = ok(client.post(f"{API}/program-groups/{week['id']}/fees", headers=owner,
                             json={"description": "Week", "amount_minor": 2000}))  # fmt: skip
        weeks.append((week, fee))
    payer = {"first_name": "Gale", "last_name": "Guest", "email": "split@example.com", "birth_on": "1985-02-03"}
    kids = [{"first_name": f"K{n}", "last_name": "Guest", "birth_on": "2015-04-01"} for n in range(4)]

    def basket(week, fee, people):
        items = [{"program_group_id": week["id"], "program_fee_id": fee["id"], "participant": p} for p in people]
        body = {"location_id": f.location, "payer": payer, "participants": kids, "items": items}
        return client.post(GUEST, headers=public(tenant), json=body)

    ok(basket(*weeks[0], [0, 1]))
    ok(basket(*weeks[1], [2, 3]))  # four held across the camp
    over = basket(*weeks[2], [None])
    assert (over.status_code, over.json()["code"]) == (409, "too-many-held-places")


def _from(address: str):
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app, client=(address, 50000))


def test_one_ipv6_slash_64_shares_the_hold_cap_and_the_create_bucket(client, owner, tenant, f, monkeypatch):
    """Rotating addresses inside one /64 gains nothing: the cap and the per-IP bucket key on the network; IPv4
    addresses stay one each."""
    from app.core.settings import get_settings

    camp, fee = online(client, owner, f, "immediate_card_payment")
    allow_guests(client, owner, camp["id"])
    net = f"2001:db8:{uuid4().int % 0xFFFF:x}:1"
    payer = {"first_name": "Gale", "last_name": "Guest", "email": "v6@example.com", "birth_on": "1985-02-03"}
    kids = [{"first_name": f"K{n}", "last_name": "Guest", "birth_on": "2015-04-01"} for n in range(4)]

    def basket(address, people):
        items = [{"program_group_id": camp["id"], "program_fee_id": fee["id"], "participant": p} for p in people]
        body = {"location_id": f.location, "payer": payer, "participants": kids, "items": items}
        return _from(address).post(GUEST, headers=public(tenant), json=body)

    ok(basket(f"{net}::a", [0, 1, 2, 3]))
    over = basket(f"{net}::b", [None])
    assert (over.status_code, over.json()["code"]) == (409, "too-many-held-places")
    v4 = f"198.51.100.{uuid4().int % 200 + 1}"
    ok(basket(v4, [None]))  # another address, another cap
    ok(basket(f"203.0.113.{uuid4().int % 200 + 1}", [None]))

    cfg = get_settings().rate_limit
    monkeypatch.setattr(cfg, "enabled", True)
    monkeypatch.setitem(cfg.buckets, "guest-checkout-create",
                        cfg.buckets["guest-checkout-create"].model_copy(update={"limit": 1}))  # fmt: skip
    other = online(client, owner, f, "immediate_card_payment", name="Other")
    allow_guests(client, owner, other[0]["id"])
    camp, fee = other
    net = f"2001:db8:{uuid4().int % 0xFFFF:x}:2"
    ok(basket(f"{net}::1", [None]))
    limited = basket(f"{net}::2", [0])
    assert (limited.status_code, limited.json()["code"]) == (429, "rate-limited")
    ok(basket(f"192.0.2.{uuid4().int % 100 + 1}", [None]))
    ok(basket(f"192.0.2.{uuid4().int % 100 + 101}", [None]))


def test_guest_baskets_naming_two_programs_in_opposite_order_both_hold_and_pay(client, owner, tenant, f):
    camp, fee = online(client, owner, f, "immediate_card_payment")
    allow_guests(client, owner, camp["id"])
    other, other_fee = online(client, owner, f, "immediate_card_payment", name="Other")
    allow_guests(client, owner, other["id"])
    payer = {"first_name": "Gale", "last_name": "Guest", "email": "order@example.com", "birth_on": "1985-02-03"}
    kids = [{"first_name": "Kit", "last_name": "Guest", "birth_on": "2015-04-01"}]
    carts = []
    for pair in ((camp, fee, other, other_fee), (other, other_fee, camp, fee)):
        items = [{"program_group_id": pair[0]["id"], "program_fee_id": pair[1]["id"], "participant": 0},
                 {"program_group_id": pair[2]["id"], "program_fee_id": pair[3]["id"], "participant": 0}]  # fmt: skip
        body = {"location_id": f.location, "payer": payer, "participants": kids, "items": items}
        carts.append(ok(client.post(GUEST, headers=public(tenant), json=body)))
    for cart in carts:
        ok(client.post(f"{GUEST}/{cart['id']}/confirm", headers=keyed(public(tenant)),
                       json={"guest_token": cart["guest_token"], "method_token": "tok_card_ok"}), 200)  # fmt: skip
    assert group_of(client, owner, camp["id"])["enrolled_count"] == 2
    assert group_of(client, owner, other["id"])["enrolled_count"] == 2


def test_staff_may_cancel_open_guest_holds_to_delete_or_archive(client, owner, tenant, f):
    """`cancel_guest_holds=true` abandons the open guest baskets holding a place in the subtree (the whole basket,
    its places released and details cleared), then deletes or archives; the guest can no longer pay."""
    for action in ("delete", "archive"):
        camp, fee = online(client, owner, f, "immediate_card_payment", name=f"Camp {action}")
        allow_guests(client, owner, camp["id"])
        other, other_fee = online(client, owner, f, "immediate_card_payment", name=f"Other {action}")
        allow_guests(client, owner, other["id"])
        body = {"location_id": f.location, "payer": {"first_name": "Gale", "last_name": "Guest",
                "email": f"{action}@example.com", "birth_on": "1985-02-03"}, "participants": [],
                "items": [{"program_group_id": camp["id"], "program_fee_id": fee["id"]},
                          {"program_group_id": other["id"], "program_fee_id": other_fee["id"]}]}  # fmt: skip
        cart = ok(client.post(GUEST, headers=public(tenant), json=body))
        url = f"{API}/program-groups/{camp['id']}" + ("/archive" if action == "archive" else "")
        call = client.post if action == "archive" else client.delete
        refused = call(url, headers=owner)
        assert (refused.status_code, refused.json()["code"]) == (409, "has-guest-holds")
        done = call(url, headers=owner, params={"cancel_guest_holds": "true"})
        assert done.status_code == (200 if action == "archive" else 204), done.text
        assert details_of(tenant, cart["id"]) is None
        assert group_of(client, owner, other["id"])["enrolled_count"] == 0  # the whole basket went
        late = client.post(f"{GUEST}/{cart['id']}/confirm", headers=keyed(public(tenant)),
                           json={"guest_token": cart["guest_token"], "method_token": "tok_card_ok"})  # fmt: skip
        assert (late.status_code, late.json()["code"]) == (409, "checkout-closed")
        assert guest_clients(tenant, f"{action}@example.com") == []


def test_cancelling_guest_holds_needs_the_online_registration_key_too(client, owner, tenant, f):
    """`cancel_guest_holds=true` throws away a guest's basket: on top of the delete or archive key it needs
    programs.registration_config.manage (managers, not the front desk). Without the flag the holds refuse."""
    from conftest import add_staff, login

    camp, fee = online(client, owner, f, "immediate_card_payment", name="Gated")
    allow_guests(client, owner, camp["id"])
    body = {"location_id": f.location, "payer": {"first_name": "Gale", "last_name": "Guest",
            "email": "gated@example.com", "birth_on": "1985-02-03"}, "participants": [],
            "items": [{"program_group_id": camp["id"], "program_fee_id": fee["id"]}]}  # fmt: skip
    cart = ok(client.post(GUEST, headers=public(tenant), json=body))
    email, staff_id = add_staff(tenant, "manager", location_ids=[f.location])
    deny = {"grants": [{"permission_key": "programs.registration_config.manage", "is_allowed": False}]}
    ok(client.put(f"{API}/staff-users/{staff_id}/permission-overrides", headers=owner, json=deny), 200)
    manager = login(client, tenant, email)
    url = f"{API}/program-groups/{camp['id']}"
    for call, path in ((client.delete, url), (client.post, f"{url}/archive")):
        gated = call(path, headers=manager, params={"cancel_guest_holds": "true"})
        assert gated.status_code == 403, gated.text
        refused = call(path, headers=manager)
        assert (refused.status_code, refused.json()["code"]) == (409, "has-guest-holds")
    assert details_of(tenant, cart["id"]) is not None  # the basket is untouched
    assert client.delete(url, headers=owner, params={"cancel_guest_holds": "true"}).status_code == 204
