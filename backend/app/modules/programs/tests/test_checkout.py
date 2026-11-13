"""Registration baskets (REG-09, 10, 12): held places, one invoice, documents before confirm, the portal paying
through secure_online_checkout as the strictest program asks, ownership by identity, and hold expiry."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.core import clock
from app.core.auth import system_principal
from app.core.db.session import tenant_session
from app.modules import billing
from app.modules.documents.tests.support import template
from app.modules.programs import checkout
from app.modules.programs.models import RegistrationCheckout
from app.modules.programs.tests.test_groups import fee_of, group_of, program
from app.modules.programs.tests.test_sessions import people
from app.modules.scheduling.tests.helpers import API, facility, ok
from conftest import PASSWORD, link_token, login, new_client

PORTAL = "portal/registration-checkouts"
STAFF = "registration-checkouts"


@pytest.fixture
def f(client, owner):
    return facility(client, owner)


def basket(client, headers, f, path: str = STAFF, **body) -> dict:
    return ok(client.post(f"{API}/{path}", headers=headers, json={"location_id": f.location} | body))


def add(client, headers, basket_id: str, group: str, person: str, path: str = STAFF, **extra):
    body = {"program_group_id": group, "client_id": person} | extra
    return client.post(f"{API}/{path}/{basket_id}/items", headers=headers, json=body)


def online(client, owner, f, requirement: str = "pay_later_allowed", **fields) -> tuple[dict, dict]:
    """A published program open online with one online fee."""
    camp = program(client, owner, f, **fields)
    fee = fee_of(client, owner, camp["id"], 9000)
    body = {"is_enabled": True, "payment_requirement": requirement}
    ok(client.put(f"{API}/program-groups/{camp['id']}/registration-config", headers=owner, json=body), 200)
    ok(client.post(f"{API}/program-groups/{camp['id']}/publish", headers=owner), 200)
    return camp, fee


def member(client, tenant, owner, f, mailbox) -> tuple[dict, dict]:
    person = new_client(client, owner, f.location, primary_email=f"m-{uuid4().hex[:8]}@example.com")
    assert client.post(f"{API}/clients/{person['id']}/portal-access/invite", headers=owner, json={}).status_code == 200
    client.post(f"{API}/auth/invitations/accept", json={"token": link_token(mailbox[-1]), "new_password": PASSWORD})
    return person, login(client, tenant, person["primary_email"], audience="client")


def keyed(headers: dict) -> dict:
    return headers | {"Idempotency-Key": f"k-{uuid4().hex}"}


def test_staff_basket_holds_places_and_bills_one_invoice(client, owner, f):
    camp, clinic = program(client, owner, f, capacity=1), program(client, owner, f, name="Clinic")
    fee = fee_of(client, owner, camp["id"], 10000)
    a, b, payer = people(client, owner, f, 3)
    cart = basket(client, owner, f)
    cart = ok(add(client, owner, cart["id"], camp["id"], a, program_fee_id=fee["id"]), 200)
    assert cart["items"][0]["status"] == "pending" and group_of(client, owner, camp["id"])["enrolled_count"] == 1
    full = add(client, owner, cart["id"], camp["id"], b, program_fee_id=fee["id"])  # the hold takes the only place
    assert (full.status_code, full.json()["code"]) == (409, "capacity-full")
    cart = ok(add(client, owner, cart["id"], clinic["id"], b), 200)
    assert cart["total_minor"] == 10000 and len(cart["items"]) == 2

    item = cart["items"][1]["id"]
    assert len(ok(client.delete(f"{API}/{STAFF}/{cart['id']}/items/{item}", headers=owner), 200)["items"]) == 1
    done = ok(client.post(f"{API}/{STAFF}/{cart['id']}/confirm", headers=owner), 200)
    assert done["status"] == "completed" and done["invoice_id"] and done["items"][0]["status"] == "enrolled"
    again = client.post(f"{API}/{STAFF}/{cart['id']}/confirm", headers=owner)
    assert (again.status_code, again.json()["code"]) == (409, "checkout-closed")

    stranger = basket(client, owner, f, payer_client_id=payer)  # money goes where its owner points it
    refused = add(client, owner, stranger["id"], clinic["id"], a)
    assert (refused.status_code, refused.json()["code"]) == (422, "payer-not-related")


def test_documents_block_confirm_until_accepted(client, owner, f):
    camp = program(client, owner, f)
    tpl = template(client, owner)
    body = {"scope_type": "program_group", "scope_id": camp["id"], "template_id": tpl["id"]}
    assert client.put(f"{API}/document-bindings", headers=owner, json=body).status_code in (200, 201)
    (kid,) = people(client, owner, f, 1)
    cart = basket(client, owner, f)
    cart = ok(add(client, owner, cart["id"], camp["id"], kid), 200)
    assert [d["client_id"] for d in cart["missing_documents"]] == [kid]
    blocked = client.post(f"{API}/{STAFF}/{cart['id']}/confirm", headers=owner)
    assert (blocked.status_code, blocked.json()["code"]) == (409, "document-required")
    assert ok(client.get(f"{API}/{STAFF}/{cart['id']}", headers=owner), 200)["status"] == "open"


def test_abandon_and_expiry_release_the_held_places(client, owner, tenant, f):
    camp = program(client, owner, f, capacity=2)
    a, b = people(client, owner, f, 2)
    first, second = basket(client, owner, f), basket(client, owner, f)
    ok(add(client, owner, first["id"], camp["id"], a), 200)
    ok(add(client, owner, second["id"], camp["id"], b), 200)
    assert group_of(client, owner, camp["id"])["enrolled_count"] == 2
    gone = ok(client.post(f"{API}/{STAFF}/{first['id']}/abandon", headers=owner), 200)
    assert gone["status"] == "abandoned" and group_of(client, owner, camp["id"])["enrolled_count"] == 1

    with tenant_session(tenant.id) as session:
        session.get(RegistrationCheckout, UUID(second["id"])).expires_at = clock.now() - timedelta(minutes=1)
    late = add(client, owner, second["id"], camp["id"], a)
    assert (late.status_code, late.json()["code"]) == (409, "checkout-expired")
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        assert checkout.expire_holds(session) == 1
    assert group_of(client, owner, camp["id"])["enrolled_count"] == 0
    assert ok(client.get(f"{API}/{STAFF}/{second['id']}", headers=owner), 200)["status"] == "expired"


def test_portal_pays_as_the_strictest_program_asks(client, owner, tenant, f, mailbox):
    later, later_fee = online(client, owner, f)
    now, now_fee = online(client, owner, f, "immediate_card_payment", name="Paid now")
    person, portal = member(client, tenant, owner, f, mailbox)
    cart = basket(client, portal, f, PORTAL)
    ok(add(client, portal, cart["id"], later["id"], person["id"], PORTAL, program_fee_id=later_fee["id"]), 200)
    cart = ok(add(client, portal, cart["id"], now["id"], person["id"], PORTAL, program_fee_id=now_fee["id"]), 200)
    assert cart["total_minor"] == 18000

    confirm = f"{API}/{PORTAL}/{cart['id']}/confirm"
    refused = client.post(confirm, headers=keyed(portal), json={"pay_later": True})
    assert (refused.status_code, refused.json()["code"]) == (422, "pay-now-required")
    declined = client.post(confirm, headers=keyed(portal), json={"method_token": "tok_card_declined"})
    assert declined.status_code in (402, 409), declined.text
    assert ok(client.get(f"{API}/{PORTAL}/{cart['id']}", headers=portal), 200)["status"] == "open"  # rolled back
    paid = ok(client.post(confirm, headers=keyed(portal), json={"method_token": "tok_card_ok"}), 200)
    assert paid["status"] == "completed" and paid["invoice_id"]
    assert group_of(client, owner, now["id"])["enrolled_count"] == 1


def test_portal_pay_later_and_ownership(client, owner, tenant, f, mailbox):
    camp, fee = online(client, owner, f)
    person, portal = member(client, tenant, owner, f, mailbox)
    other, _ = member(client, tenant, owner, f, mailbox)
    cart = basket(client, portal, f, PORTAL)
    foreign = add(client, portal, cart["id"], camp["id"], other["id"], PORTAL)  # not someone this login buys for
    assert foreign.status_code == 404
    cart = ok(add(client, portal, cart["id"], camp["id"], person["id"], PORTAL, program_fee_id=fee["id"]), 200)

    _, intruder = member(client, tenant, owner, f, mailbox)
    assert client.get(f"{API}/{PORTAL}/{cart['id']}", headers=intruder).status_code == 404
    assert client.get(f"{API}/{STAFF}/{cart['id']}", headers=owner).status_code == 404  # not a staff basket
    staff_cart = basket(client, owner, f)
    assert client.get(f"{API}/{PORTAL}/{staff_cart['id']}", headers=portal).status_code == 404

    unlisted = program(client, owner, f, name="Unpublished")
    assert add(client, portal, cart["id"], unlisted["id"], person["id"], PORTAL).status_code == 404
    confirm = client.post(f"{API}/{PORTAL}/{cart['id']}/confirm", headers=keyed(portal), json={"pay_later": True})
    assert ok(confirm, 200)["status"] == "completed"
    invoices = ok(client.get(f"{API}/invoices?bill_to_client_id={person['id']}", headers=owner), 200)["data"]
    assert [i["total_minor"] for i in invoices] == [9000]


def test_public_listing_shows_published_programs_only(client, owner, tenant, f):
    camp, _ = online(client, owner, f)
    program(client, owner, f, name="Private")
    public = {"X-Tenant-Slug": tenant.slug}
    listed = ok(client.get(f"{API}/public/program-groups?location_id={f.location}", headers=public), 200)
    assert [g["id"] for g in listed] == [camp["id"]]
    ok(client.post(f"{API}/program-groups/{camp['id']}/unpublish", headers=owner), 200)
    assert client.get(f"{API}/public/program-groups/{camp['id']}", headers=public).status_code == 404


def test_portal_group_waitlist_needs_a_full_program_and_a_fee_and_is_not_auto_promoted(
    client, owner, tenant, f, mailbox
):
    camp, fee = online(client, owner, f, capacity=1, waitlist_mode="auto_promote")
    (holder,) = people(client, owner, f, 1)
    person, portal = member(client, tenant, owner, f, mailbox)
    join = f"{API}/portal/waitlist-entries"
    body = {"client_id": person["id"], "program_group_id": camp["id"]}
    early = client.post(join, headers=portal, json=body | {"program_fee_id": fee["id"]})
    assert (early.status_code, early.json()["code"]) == (409, "session-has-space")
    place = ok(
        client.post(
            f"{API}/enrollments",
            headers=owner,
            json={"program_group_id": camp["id"], "client_id": holder, "program_fee_ids": [fee["id"]]},
        )
    )
    feeless = client.post(join, headers=portal, json=body)
    assert (feeless.status_code, feeless.json()["code"]) == (422, "fee-required")
    entry = ok(client.post(join, headers=portal, json=body | {"program_fee_id": fee["id"]}))
    ok(client.post(f"{API}/enrollments/{place['id']}/cancel", headers=owner, json={}), 200)
    waiting = ok(client.get(join, headers=portal), 200)
    assert [(e["id"], e["status"]) for e in waiting] == [(entry["id"], "waiting")]  # staff promote it by hand
    assert group_of(client, owner, camp["id"])["enrolled_count"] == 0


def test_reg_10_deposit_and_instalment_plans(client, owner, tenant, f, mailbox):
    """REG-10 (phase 11 B, decision Q5): a group's plan takes the deposit now and schedules the rest on the
    invoice, so autopay collects it; coupons and pay-later are refused, and a stored payer needs autopay."""
    camp = program(client, owner, f)
    fee = ok(client.post(f"{API}/program-groups/{camp['id']}/fees", headers=owner,
                         json={"description": "Camp", "amount_minor": 9000, "deposit_minor": 3000}))  # fmt: skip
    config = f"{API}/program-groups/{camp['id']}/registration-config"
    base = {"is_enabled": True, "payment_requirement": "immediate_card_payment"}
    bad = client.put(config, headers=owner, json=base | {"payment_plan": "instalments", "balance_due_on": "2031-06-01"})
    assert (bad.status_code, bad.json()["code"]) == (422, "payment-plan-invalid")  # no count or unit
    lax = client.put(config, headers=owner, json=base | {"payment_requirement": "pay_later_allowed",
                                                         "payment_plan": "deposit", "balance_due_on": "2031-06-01"})  # fmt: skip
    assert lax.status_code == 422
    plan = {
        "payment_plan": "instalments",
        "balance_due_on": "2031-06-01",
        "instalment_count": 3,
        "instalment_unit": "month",
    }
    saved = ok(client.put(config, headers=owner, json=base | plan), 200)
    assert saved["instalment_count"] == 3
    ok(client.post(f"{API}/program-groups/{camp['id']}/publish", headers=owner), 200)
    public = ok(client.get(f"{API}/public/program-groups", headers={"X-Tenant-Slug": tenant.slug}), 200)
    [listed] = [g for g in public if g["id"] == camp["id"]]
    assert listed["payment_plan"] == "instalments" and listed["fees"][0]["deposit_minor"] == 3000

    person, portal = member(client, tenant, owner, f, mailbox)
    cart = basket(client, portal, f, PORTAL)
    cart = ok(add(client, portal, cart["id"], camp["id"], person["id"], PORTAL, program_fee_id=fee["id"]), 200)
    assert cart["due_now_minor"] == 3000
    assert [(i["due_on"], i["amount_minor"]) for i in cart["instalments"]] == [
        ("2031-06-01", 2000), ("2031-07-01", 2000), ("2031-08-01", 2000)]  # fmt: skip
    confirm = f"{API}/{PORTAL}/{cart['id']}/confirm"
    later = client.post(confirm, headers=keyed(portal), json={"pay_later": True})
    assert (later.status_code, later.json()["code"]) == (422, "pay-now-required")
    stored = client.post(confirm, headers=keyed(portal), json={})  # no card given and no autopay method
    assert stored.status_code == 422
    paid = ok(client.post(confirm, headers=keyed(portal), json={"method_token": "tok_card_ok"}), 200)
    assert paid["status"] == "completed"
    # the confirmed view keeps the plan, read back from the invoice schedule
    assert (paid["total_minor"], paid["due_now_minor"]) == (9000, 3000)
    assert [(i["due_on"], i["amount_minor"]) for i in paid["instalments"]] == [
        ("2031-06-01", 2000), ("2031-07-01", 2000), ("2031-08-01", 2000)]  # fmt: skip
    bill = ok(client.get(f"{API}/invoices/{paid['invoice_id']}", headers=owner), 200)
    assert (bill["total_minor"], bill["balance_minor"], bill["status"]) == (9000, 6000, "partially_paid")
    schedule = ok(client.get(f"{API}/invoices/{paid['invoice_id']}/payment-schedule", headers=owner), 200)
    assert [(i["amount_minor"], i["covered_minor"]) for i in schedule["instalments"]] == [
        (3000, 3000), (2000, 0), (2000, 0), (2000, 0)]  # fmt: skip
    methods = ok(client.get(f"{API}/portal/payment-methods", headers=portal), 200)
    assert any(m["is_autopay"] for m in methods)  # the card stays on file for the instalments
    assert bill["is_autopay"] is True
    # on the first instalment date the autopay run collects it from that card (no dunning, no lockout)
    with clock.freeze(datetime(2031, 6, 1, 18, tzinfo=UTC)), tenant_session(tenant.id, actor=system_principal("tests")) as session:  # fmt: skip
        run = billing.autopay.run_location(session, UUID(f.location))
        assert (run.succeeded_count, run.collected_minor) == (1, 2000)
    bill = ok(client.get(f"{API}/invoices/{paid['invoice_id']}", headers=owner), 200)
    assert (bill["balance_minor"], bill["status"], bill["dunning_state"]) == (4000, "partially_paid", "none")


def plan_program(client, owner, f, balance_due_on: str = "2031-06-01", **fields) -> tuple[dict, dict]:
    """A published deposit-plan program: 9000 with a 3000 deposit."""
    camp = program(client, owner, f, **fields)
    fee = ok(client.post(f"{API}/program-groups/{camp['id']}/fees", headers=owner,
                         json={"description": "Camp", "amount_minor": 9000, "deposit_minor": 3000}))  # fmt: skip
    body = {"is_enabled": True, "payment_requirement": "immediate_card_payment", "payment_plan": "deposit",
            "balance_due_on": balance_due_on}  # fmt: skip
    ok(client.put(f"{API}/program-groups/{camp['id']}/registration-config", headers=owner, json=body), 200)
    ok(client.post(f"{API}/program-groups/{camp['id']}/publish", headers=owner), 200)
    return camp, fee


def test_a_discounted_plan_defers_what_was_billed_less_the_deposit(client, owner, tenant, f, mailbox, monkeypatch):
    """The balance left for later is the billed charge (after discounts) less the deposit, not the list fee."""
    from app.modules.programs import groups

    real_bill = groups.bill

    def discounted(session, row, fees):
        ids = [billing.service.adjust_charge(session, charge_id, reason="Sibling", discount_minor=3000).id
               for charge_id in real_bill(session, row, fees)]  # fmt: skip
        row.charge_id = ids[0]
        return ids

    monkeypatch.setattr(groups, "bill", discounted)
    camp, fee = plan_program(client, owner, f)
    person, portal = member(client, tenant, owner, f, mailbox)
    cart = basket(client, portal, f, PORTAL)
    ok(add(client, portal, cart["id"], camp["id"], person["id"], PORTAL, program_fee_id=fee["id"]), 200)
    paid = ok(client.post(f"{API}/{PORTAL}/{cart['id']}/confirm", headers=keyed(portal),
                          json={"method_token": "tok_card_ok"}), 200)  # fmt: skip
    bill = ok(client.get(f"{API}/invoices/{paid['invoice_id']}", headers=owner), 200)
    assert (bill["total_minor"], bill["balance_minor"]) == (6000, 3000)  # the 3000 deposit was paid now
    schedule = ok(client.get(f"{API}/invoices/{paid['invoice_id']}/payment-schedule", headers=owner), 200)
    assert [(i["due_on"], i["amount_minor"]) for i in schedule["instalments"]][1:] == [("2031-06-01", 3000)]


def test_a_balance_date_already_passed_is_due_now(client, owner, tenant, f, mailbox):
    """A balance date in the past would land on the deposit's date and wait for autopay: it is paid now."""
    camp, fee = plan_program(client, owner, f, balance_due_on="2020-01-01")
    person, portal = member(client, tenant, owner, f, mailbox)
    cart = basket(client, portal, f, PORTAL)
    cart = ok(add(client, portal, cart["id"], camp["id"], person["id"], PORTAL, program_fee_id=fee["id"]), 200)
    assert (cart["due_now_minor"], cart["instalments"]) == (9000, [])
    paid = ok(client.post(f"{API}/{PORTAL}/{cart['id']}/confirm", headers=keyed(portal),
                          json={"method_token": "tok_card_ok"}), 200)  # fmt: skip
    bill = ok(client.get(f"{API}/invoices/{paid['invoice_id']}", headers=owner), 200)
    assert (bill["total_minor"], bill["balance_minor"], bill["status"]) == (9000, 0, "paid")
    assert bill["is_autopay"] is False  # no later rows, so not an autopay invoice


def test_terms_are_recorded_against_the_whole_basket(client, owner, tenant, f, mailbox):
    from sqlalchemy import select

    from app.modules.documents.models import TermsAcceptance
    from app.modules.documents.tests.test_portal_terms import bind_terms, shown

    first, first_fee = online(client, owner, f, "immediate_card_payment")
    second, second_fee = online(client, owner, f, "immediate_card_payment", name="Second")
    person, portal = member(client, tenant, owner, f, mailbox)
    bind_terms(client, owner, f"Terms {uuid4().hex}")
    cart = basket(client, portal, f, PORTAL)
    ok(add(client, portal, cart["id"], first["id"], person["id"], PORTAL, program_fee_id=first_fee["id"]), 200)
    ok(add(client, portal, cart["id"], second["id"], person["id"], PORTAL, program_fee_id=second_fee["id"]), 200)
    ok(client.post(f"{API}/{PORTAL}/{cart['id']}/confirm", headers=keyed(portal),
                   json={"method_token": "tok_card_ok", "terms_version_id": shown(client, tenant)}), 200)  # fmt: skip
    with tenant_session(tenant.id) as session:
        subjects = list(
            session.scalars(select(TermsAcceptance.subject_id).where(TermsAcceptance.sale_kind == "program"))
        )
    assert subjects == [UUID(cart["id"])]
