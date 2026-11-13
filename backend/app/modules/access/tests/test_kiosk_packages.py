"""Kiosk package purchase with the card on file (CHK-05; owner decisions 2026-11-13, question 15). Offered only to an
adult whose check-in was by a signed card payload (the app's QR or a wallet pass), with a default card saved, where
the location allows it; sold through packages' sale and billing's secured checkout like the portal; any refusal is
see-staff and sells nothing. A typed barcode or number and a name lookup never pay (security review 2026-11-13)."""

import secrets
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from app.core import clock
from app.core.auth import system_principal
from app.core.db.session import tenant_session
from app.modules.access.domain import cards
from app.modules.access.models import CheckIn, Credential
from app.modules.access.tests.test_checkin import _pair, ok
from app.modules.access.tests.test_kiosk_reservations import card_of, enter
from app.modules.billing import checkout
from app.modules.billing.tests.test_billing import svc, work
from app.modules.memberships.tests.support import API, package_plan, world
from app.modules.packages.models import ClientPackage
from conftest import new_client, scalar


@pytest.fixture
def k(client, tenant, owner):
    w = world(client, owner, tenant)
    person = new_client(client, owner, w.location_id, first_name="Robin", last_name=f"Kiosk{uuid4().hex[:6]}")
    _pair(client, tenant, owner, w.location_id)
    return SimpleNamespace(loc=w.location_id, person=person, tenant=tenant)


def card_on_file(tenant, person, loc, token: str = "tok_card_ok") -> None:
    with work(tenant) as session:
        svc.ensure_defaults(session)
        svc._provider_account(session)
    with work(tenant) as session:
        checkout.secure_online_checkout(
            session, client_id=UUID(person["id"]), location_id=UUID(loc), invoice=None, total_minor=1000,
            idempotency_key=uuid4().hex, must_pay_now=False, method_token=token,
        )  # fmt: skip


def app_card(tenant, person) -> SimpleNamespace:
    """An app card as the portal issues it: `seed` makes the signed rotating QR, `value` is its static number."""
    secret = secrets.token_bytes(32)
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        row = Credential(client_id=UUID(person["id"]), kind="app_card", value=f"APP{secrets.token_hex(8).upper()}",
                         source="app_issued", secret_ciphertext=secret, issued_at=clock.now())  # fmt: skip
        session.add(row)
        session.flush()
        card_id, value = row.id, row.value
    return SimpleNamespace(seed=cards.seed(card_id, secret), value=value)


def scan(client, card) -> dict:
    """Self check-in by scanning the app's current QR (a signed card payload)."""
    return ok(client.post(f"{API}/kiosk/check-ins", json={"card_payload": cards.qr_text(card.seed, clock.now())}), 201)


def owned(tenant, person) -> int:
    return scalar(
        tenant,
        select(func.count()).select_from(ClientPackage).where(ClientPackage.owner_client_id == UUID(person["id"])),
    )


@pytest.fixture
def shop(client, tenant, owner, k):
    plan = package_plan(client, owner, tenant, online_sale_mode="paid_in_full")
    ok(
        client.put(
            f"{API}/kiosk-settings?location_id={k.loc}", headers=owner, json={"is_package_purchase_enabled": True}
        )
    )
    card_on_file(tenant, k.person, k.loc)
    return SimpleNamespace(plan=plan, card=app_card(tenant, k.person))


def plans(client, visit):
    return client.get(f"{API}/kiosk/check-ins/{visit['check_in_id']}/package-plans",
                      headers={"Kiosk-Visit-Token": visit["visit_token"]})  # fmt: skip


def buy(client, visit, plan_id, key: str | None = None):
    return client.post(f"{API}/kiosk/package-purchases", headers={"Idempotency-Key": key or uuid4().hex},
                       json={"check_in_id": visit["check_in_id"], "package_plan_id": plan_id, "visit_token": visit["visit_token"]})  # fmt: skip


def test_a_card_holder_buys_a_package_with_the_card_on_file(client, tenant, owner, k, shop):
    entered = scan(client, shop.card)
    listed = ok(plans(client, entered))
    assert {
        "package_plan_id": shop.plan["id"],
        "name": shop.plan["name"],
        "price_minor": 10000,
        "is_purchasable": True,
    } in listed
    assert ok(plans(client, entered))  # reading the page does not spend the token
    bought = ok(buy(client, entered, shop.plan["id"], "kiosk-buy-1"), 201)
    assert owned(tenant, k.person) == 1 and bought["visit_token"] != entered["visit_token"]
    replay = buy(client, entered, shop.plan["id"], "kiosk-buy-1")
    assert replay.status_code == 409 and replay.json()["code"] == "response-not-stored"
    assert buy(client, entered, shop.plan["id"]).status_code == 404  # the token was spent by the purchase
    assert owned(tenant, k.person) == 1


def test_only_a_signed_card_payload_may_pay_never_a_typed_number_or_a_name(client, tenant, owner, k, shop):
    with tenant_session(tenant.id) as session:  # the check-in records how the client was identified
        row = session.get_one(CheckIn, UUID(scan(client, shop.card)["check_in_id"]))
        assert row.identified_by == "signed_card"
    for visit in (
        enter(client, k.person),  # a name lookup
        enter(client, k.person, card_of(client, owner, k.person)),  # a typed or scanned plain barcode
        enter(client, k.person, shop.card.value),  # the app card's static number typed in, no signature
    ):
        assert plans(client, visit).status_code == 404
        refused = buy(client, visit, shop.plan["id"])
        assert refused.status_code == 404 and "card" not in refused.text.lower()
    assert owned(tenant, k.person) == 0


def test_a_visit_token_is_single_use_and_buys_only_for_its_own_check_in(client, tenant, owner, k, shop):
    entered = scan(client, shop.card)
    ok(buy(client, entered, shop.plan["id"]), 201)
    assert buy(client, entered, shop.plan["id"]).status_code == 404  # replayed nonce
    ended = scan(client, shop.card)
    assert client.post(f"{API}/kiosk/visits/end").status_code == 204
    assert buy(client, ended, shop.plan["id"]).status_code == 404  # the kiosk went back to its start screen
    # Another household's member, with a signed card and a card on file of their own: neither visit's token buys
    # against the other's check-in, so nobody is charged for someone else.
    other = new_client(client, owner, k.loc)
    card_on_file(tenant, other, k.loc)
    theirs, mine = scan(client, app_card(tenant, other)), scan(client, shop.card)
    assert buy(client, {**theirs, "visit_token": mine["visit_token"]}, shop.plan["id"]).status_code == 404
    assert buy(client, {**mine, "visit_token": theirs["visit_token"]}, shop.plan["id"]).status_code == 404
    assert owned(tenant, other) == 0 and owned(tenant, k.person) == 1


def test_the_package_page_is_only_for_an_adult_card_holder_with_a_card_on_file(client, tenant, owner, k, shop):
    ok(
        client.put(
            f"{API}/kiosk-settings?location_id={k.loc}", headers=owner, json={"is_package_purchase_enabled": False}
        )
    )
    assert plans(client, scan(client, shop.card)).status_code == 404  # the location does not sell here
    ok(
        client.put(
            f"{API}/kiosk-settings?location_id={k.loc}", headers=owner, json={"is_package_purchase_enabled": True}
        )
    )

    no_card = new_client(client, owner, k.loc)
    assert plans(client, scan(client, app_card(tenant, no_card))).status_code == 404
    minor = new_client(client, owner, k.loc, birth_on=f"{clock.now().year - 10}-01-01")
    card_on_file(tenant, minor, k.loc)
    entered = scan(client, app_card(tenant, minor))
    assert plans(client, entered).status_code == 404
    assert buy(client, entered, shop.plan["id"]).status_code == 404
    assert owned(tenant, minor) == 0


def test_only_plans_sold_online_and_open_to_the_client_are_sold(client, tenant, owner, k, shop):
    hidden = package_plan(client, owner, tenant)  # online sale off
    members = package_plan(client, owner, tenant, online_sale_mode="paid_in_full", is_members_only_online=True)
    entered = scan(client, shop.card)
    listed = {p["package_plan_id"]: p for p in ok(plans(client, entered))}
    assert hidden["id"] not in listed and listed[members["id"]]["is_purchasable"] is False
    for plan_id in (hidden["id"], members["id"]):
        refused = buy(client, entered, plan_id)
        assert refused.status_code == 422 and refused.json()["code"] == "validation-failed"
    assert owned(tenant, k.person) == 0


def test_a_declined_card_sends_the_client_to_the_desk_and_sells_nothing(client, tenant, owner, k, shop):
    person = new_client(client, owner, k.loc)
    card_on_file(tenant, person, k.loc, "tok_card_flaky")  # saved fine; its first charge declines
    entered = scan(client, app_card(tenant, person))
    refused = buy(client, entered, shop.plan["id"])
    assert refused.status_code == 409 and refused.json()["code"] == "see-staff"
    assert "declin" not in refused.text.lower() and owned(tenant, person) == 0
