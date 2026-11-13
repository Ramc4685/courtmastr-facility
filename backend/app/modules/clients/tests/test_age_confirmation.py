"""Age confirmation (owner decision 2026-11-13, "Staff confirm once"): every online path that creates a client
needs a birth date the person declares true; a self-typed date is always flagged until staff confirm it once."""

from uuid import uuid4

import pytest
from sqlalchemy import select, update

from app.core.audit import AuditEvent
from app.core.auth import system_principal
from app.core.db.session import tenant_session
from app.core.events import OutboxEvent
from app.modules.clients.models import Client
from app.modules.engagement.tests.test_portal_entry import SIGNUPS, public, settings
from app.modules.programs.tests.test_checkout import online as online_program
from app.modules.programs.tests.test_guest_checkout import GUEST, allow_guests, guest_clients, keyed, start
from app.modules.rentals.tests.test_rentals import portal_client
from app.modules.scheduling.tests.helpers import API, facility, ok
from conftest import add_staff, link_token, login, new_client

ADULT = "1990-01-02"
CHILD = "2021-03-01"


@pytest.fixture
def f(client, owner):
    return facility(client, owner)


def staff_view(client, owner, client_id: str) -> dict:
    return ok(client.get(f"{API}/clients/{client_id}", headers=owner), 200)


def flagged(tenant, client_id) -> bool:
    with tenant_session(tenant.id) as session:
        return session.get(Client, client_id).is_birth_on_unverified


def self_declared(client, owner, tenant, f, birth_on: str | None = ADULT) -> str:
    """A record whose birth date the person typed online (as sign-up leaves it)."""
    who = new_client(client, owner, f.location, **({"birth_on": birth_on} if birth_on else {}))["id"]
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        session.execute(update(Client).where(Client.id == who).values(is_birth_on_unverified=birth_on is not None))
    return who


def confirm(client, headers, who: str, **body):
    return client.post(f"{API}/clients/{who}/age-confirmation", headers=headers, json=body)


def confirmed_events(tenant, who) -> int:
    with tenant_session(tenant.id) as session:
        return len(session.scalars(select(OutboxEvent).where(
            OutboxEvent.event_type == "clients.client.age_confirmed", OutboxEvent.aggregate_id == who)).all())  # fmt: skip


def dependant(client, portal, **extra):
    parent_of = next(t for t in ok(client.get(f"{API}/portal/relationship-types", headers=portal), 200)
                     if t["code"] == "parent_of")  # fmt: skip
    body = {"relationship_type_id": parent_of["id"], "first_name": "Kit", "last_name": "Pat", "birth_on": CHILD}
    return client.post(f"{API}/portal/dependents", headers=portal, json=body | extra)


# --- item 1: a declared birth date at every sign-up path ----------------------------------------------------------


def test_signup_needs_a_declared_birth_date_and_the_date_waits_for_staff(client, owner, tenant, f, mailbox):
    ok(settings(client, owner, f, allows_self_signup=True), 200)
    email = f"n-{uuid4().hex[:8]}@example.com"
    body = {"location_id": f.location, "email": email, "first_name": "Nia", "last_name": "Newcomer"}
    for short in (body, body | {"birth_on": ADULT}, body | {"birth_on": ADULT, "birth_on_declared": False}):
        assert client.post(SIGNUPS, headers=public(tenant), json=short).status_code == 422
    declared = body | {"birth_on": ADULT, "birth_on_declared": True}
    assert client.post(SIGNUPS, headers=public(tenant), json=declared).status_code == 202
    ok(client.post(f"{SIGNUPS}/confirm", headers=public(tenant), json={"token": link_token(mailbox[-1])}), 200)
    [found] = ok(client.get(f"{API}/clients", headers=owner, params={"q": email}), 200)["data"]
    seen = staff_view(client, owner, found["id"])
    assert (seen["birth_on"], seen["is_birth_on_unverified"]) == (ADULT, True)


def test_guest_checkout_needs_the_declaration_and_flags_every_client_it_creates(client, owner, tenant, f):
    camp, fee = online_program(client, owner, f, "immediate_card_payment")
    allow_guests(client, owner, camp["id"])
    email = f"g-{uuid4().hex[:6]}@example.com"
    assert start(client, tenant, f, camp, fee, email, declared=None).status_code == 422
    cart = ok(start(client, tenant, f, camp, fee, email))
    ok(client.post(f"{GUEST}/{cart['id']}/confirm", headers=keyed(public(tenant)),
                   json={"guest_token": cart["guest_token"], "method_token": "tok_card_ok"}), 200)  # fmt: skip
    created = guest_clients(tenant, email)
    assert len(created) == 2 and all(flagged(tenant, c) for c in created)  # the payer and the child


def test_a_portal_dependant_needs_the_declaration_and_the_parent_cannot_change_the_date(client, owner, tenant, f):
    _, portal = portal_client(client, owner, tenant, f)
    assert dependant(client, portal).status_code == 422
    kid = ok(dependant(client, portal, birth_on_declared=True), 201)
    assert staff_view(client, owner, kid["id"])["is_birth_on_unverified"] is True
    moved = client.patch(f"{API}/portal/clients/{kid['id']}", headers=portal, json={"birth_on": "2011-03-01"})
    assert (moved.status_code, moved.json()["code"]) == (422, "field-locked")  # they ask staff


def test_merge_carries_the_flag_with_a_backfilled_birth_date(client, owner, tenant, f):
    survivor = new_client(client, owner, f.location)["id"]
    loser = new_client(client, owner, f.location, birth_on=ADULT)["id"]
    with tenant_session(tenant.id, actor=system_principal("tests")) as session:
        session.execute(update(Client).where(Client.id == loser).values(is_birth_on_unverified=True))
    merged = ok(client.post(f"{API}/clients/{survivor}/merge", headers=owner, json={"merged_client_ids": [loser]}), 200)
    assert (merged["birth_on"], merged["is_birth_on_unverified"]) == (ADULT, True)


# --- item 2: staff confirm age once ---------------------------------------------------------------------------------


def test_staff_confirm_an_unchanged_date_audited_flag_only_and_the_event_fires_once(client, owner, tenant, f):
    who = self_declared(client, owner, tenant, f)
    assert staff_view(client, owner, who)["age_confirmed"] is False
    done = ok(confirm(client, owner, who), 200)
    assert (done["birth_on"], done["is_birth_on_unverified"], done["age_confirmed"]) == (ADULT, False, True)
    assert done["age_confirmed_at"] and done["age_confirmed_by_staff_user_id"]
    with tenant_session(tenant.id) as session:
        record = session.scalars(select(AuditEvent).where(
            AuditEvent.entity_id == who, AuditEvent.action == "clients.client.confirm_age")).one()  # fmt: skip
    assert record.changes["is_birth_on_unverified"] == [True, False] and "birth_on" not in record.changes
    assert ADULT not in str(record.changes)  # PII flag-only; no document detail exists to store
    assert confirmed_events(tenant, who) == 1
    ok(confirm(client, owner, who), 200)  # seeing the ID again is harmless and announces nothing new
    assert confirmed_events(tenant, who) == 1


def test_staff_may_correct_the_date_while_confirming(client, owner, tenant, f):
    who = self_declared(client, owner, tenant, f)
    done = ok(confirm(client, owner, who, birth_on="1991-04-05"), 200)
    assert (done["birth_on"], done["age_confirmed"]) == ("1991-04-05", True)
    with tenant_session(tenant.id) as session:
        record = session.scalars(select(AuditEvent).where(
            AuditEvent.entity_id == who, AuditEvent.action == "clients.client.confirm_age")).one()  # fmt: skip
    assert record.changes["birth_on"] is True


def test_confirming_needs_a_date(client, owner, tenant, f):
    who = self_declared(client, owner, tenant, f, birth_on=None)
    refused = confirm(client, owner, who)
    assert (refused.status_code, refused.json()["code"]) == (422, "birth-date-required")


def test_only_the_confirm_action_confirms_a_staff_entered_date_is_not_enough(client, owner, f):
    """Coordinator security review: staff typing a date (create or edit) is not an ID check."""
    seen = new_client(client, owner, f.location, birth_on=ADULT)
    assert (seen["is_birth_on_unverified"], seen["age_confirmed"]) == (True, False)


def test_a_desk_edit_without_the_key_leaves_the_date_unconfirmed_and_fires_nothing(client, owner, tenant, f):
    who = self_declared(client, owner, tenant, f)
    email, desk_id = add_staff(tenant, "front_desk", location_ids=[f.location])
    deny = {"grants": [{"permission_key": "clients.client.confirm_age", "is_allowed": False}]}
    ok(client.put(f"{API}/staff-users/{desk_id}/permission-overrides", headers=owner, json=deny), 200)
    desk = login(client, tenant, email)
    seen = ok(client.patch(f"{API}/clients/{who}", headers=desk, json={"birth_on": "1990-01-03"}), 200)
    assert (seen["birth_on"], seen["is_birth_on_unverified"], seen["age_confirmed"]) == ("1990-01-03", True, False)
    asked = client.patch(f"{API}/clients/{who}", headers=desk, json={"birth_on": ADULT, "confirm_age": True})
    assert asked.status_code == 403 and staff_view(client, owner, who)["birth_on"] == "1990-01-03"
    assert confirm(client, desk, who).status_code == 403
    assert confirmed_events(tenant, who) == 0


def test_an_edit_with_the_key_and_the_explicit_flag_confirms_once(client, owner, tenant, f):
    who = self_declared(client, owner, tenant, f)
    body = {"birth_on": "1990-01-03", "confirm_age": True}
    seen = ok(client.patch(f"{API}/clients/{who}", headers=owner, json=body), 200)
    assert (seen["birth_on"], seen["age_confirmed"]) == ("1990-01-03", True)
    assert confirmed_events(tenant, who) == 1
    ok(client.patch(f"{API}/clients/{who}", headers=owner, json={"comments": "seen", "confirm_age": True}), 200)
    assert confirmed_events(tenant, who) == 1


def test_changing_a_confirmed_date_without_confirming_resets_it_and_says_so(client, owner, tenant, f):
    who = self_declared(client, owner, tenant, f)
    ok(confirm(client, owner, who), 200)
    seen = ok(client.patch(f"{API}/clients/{who}", headers=owner, json={"birth_on": "1990-01-04"}), 200)
    assert (seen["age_confirmed"], seen["age_confirmation_reset"], seen["age_confirmed_at"]) == (False, True, None)
    other = ok(client.patch(f"{API}/clients/{who}", headers=owner, json={"comments": "x"}), 200)
    assert other["age_confirmation_reset"] is False


def test_an_import_never_confirms(client, owner, tenant, f):
    from app.modules.clients import service

    who = self_declared(client, owner, tenant, f)
    ok(confirm(client, owner, who), 200)
    member = staff_view(client, owner, who)
    with tenant_session(tenant.id, actor=system_principal("import")) as session:
        created, fresh = service.import_client(session, {
            "first_name": "Imo", "last_name": f"Port-{uuid4().hex[:6]}", "home_location_id": f.location,
            "birth_on": ADULT})  # fmt: skip
        assert fresh and created.is_birth_on_unverified
        session.execute(update(Client).where(Client.id == who).values(member_number="M-AGE-1"))
        service.import_client(session, {"member_number": "M-AGE-1", "first_name": member["first_name"],
                                        "last_name": member["last_name"], "birth_on": "1990-02-02"})  # fmt: skip
    assert staff_view(client, owner, who)["age_confirmed"] is False
    assert confirmed_events(tenant, who) == 1  # only the action's


def test_a_merge_backfill_never_confirms(client, owner, tenant, f):
    survivor = new_client(client, owner, f.location)["id"]
    loser = self_declared(client, owner, tenant, f)
    ok(confirm(client, owner, loser), 200)
    merged = ok(client.post(f"{API}/clients/{survivor}/merge", headers=owner, json={"merged_client_ids": [loser]}), 200)
    assert (merged["birth_on"], merged["age_confirmed"]) == (ADULT, False)
    assert confirmed_events(tenant, survivor) == 0


def test_an_api_key_can_never_hold_or_use_confirm_age(client, owner, tenant, f):
    who = self_declared(client, owner, tenant, f)
    given = client.post(
        f"{API}/api-keys", headers=owner, json={"name": "Partner", "scopes": ["clients.client.confirm_age"]}
    )
    assert (given.status_code, given.json()["code"]) == (422, "scope-not-grantable")
    key = ok(
        client.post(f"{API}/api-keys", headers=owner, json={"name": "Partner", "scopes": ["clients.client.update"]})
    )
    bearer = {"Authorization": f"Bearer {key['secret']}"}
    asked = client.patch(f"{API}/clients/{who}", headers=bearer, json={"birth_on": ADULT, "confirm_age": True})
    assert asked.status_code == 403
    assert confirm(client, bearer, who).status_code == 403
    edited = ok(client.patch(f"{API}/clients/{who}", headers=bearer, json={"birth_on": "1990-03-03"}), 200)
    assert edited["age_confirmed"] is False and confirmed_events(tenant, who) == 0


def test_confirm_age_has_its_own_key_and_stays_in_location_scope(client, owner, tenant, f):
    who = self_declared(client, owner, tenant, f)
    coach = login(client, tenant, add_staff(tenant, "coach", all_locations=True)[0])
    assert confirm(client, coach, who).status_code == 403
    elsewhere = ok(client.post(f"{API}/locations", headers=owner, json={
        "name": f"Elsewhere {uuid4().hex[:4]}", "time_zone": "America/Chicago", "country_code": "US"}))["id"]  # fmt: skip
    away = login(client, tenant, add_staff(tenant, "front_desk", location_ids=[elsewhere])[0])
    assert confirm(client, away, who).status_code == 404
    desk = login(client, tenant, add_staff(tenant, "front_desk", location_ids=[f.location])[0])
    assert ok(confirm(client, desk, who), 200)["age_confirmed"] is True
