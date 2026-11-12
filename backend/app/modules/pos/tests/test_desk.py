"""Phase 10 chip E at the register: quick-create a client (POS-08), the per-location receipt footer (POS-14) and the
daily low-stock digest (POS-22), each through the real routes and job on Postgres."""

from app.core.auth import system_principal
from app.core.db.session import tenant_session
from app.modules.pos import inventory
from app.modules.pos.tests.conftest import API, cash_sale, start
from conftest import add_staff, login, new_client


def _quick(client, sale, headers, **body):
    body = {"version": sale["version"], "first_name": "Robin", "last_name": "Quick"} | body
    return client.post(f"{API}/pos-sales/{sale['id']}/quick-client", headers=headers, json=body)


def _override(client, store, user_id, key: str, allowed: bool) -> None:
    body = {"grants": [{"permission_key": key, "is_allowed": allowed}]}
    assert (
        client.put(f"{API}/staff-users/{user_id}/permission-overrides", headers=store.owner, json=body).status_code
        == 200
    )


def test_quick_create_attaches_a_new_client_and_prechecks_duplicates(client, store):
    sale = start(store, store.front)
    made = _quick(client, sale, store.front, primary_email="robin@example.com")
    assert made.status_code == 200, made.text
    attached = made.json()
    assert attached["client_id"] is not None and attached["version"] == sale["version"] + 1
    person = client.get(f"{API}/clients/{attached['client_id']}", headers=store.owner).json()
    assert (person["home_location_id"], person["primary_email"]) == (store.location_id, "robin@example.com")

    store.post(f"/pos-sales/{sale['id']}/abandon", {}, headers=store.front)  # one draft per register
    second = start(store, store.front)
    clash = _quick(client, second, store.front, first_name="ROBIN")
    assert clash.status_code == 409 and clash.json()["code"] == "possible-duplicate", clash.text
    assert [c["id"] for c in clash.json()["candidates"]] == [attached["client_id"]]
    assert client.get(f"{API}/pos-sales/{second['id']}", headers=store.front).json()["client_id"] is None
    confirmed = _quick(client, second, store.front, confirm_new=True)
    assert confirmed.status_code == 200 and confirmed.json()["client_id"] not in (None, attached["client_id"])
    stale = _quick(client, second, store.front, first_name="Other", last_name="Person")
    assert stale.status_code == 409 and stale.json()["code"] == "version-conflict"


def test_quick_create_needs_the_client_key_and_the_sale_in_reach(client, store):
    email, user_id = add_staff(store.tenant, "front_desk", location_ids=[store.location_id])
    _override(client, store, user_id, "clients.client.create", False)
    cashier = login(client, store.tenant, email)
    sale = start(store, cashier)
    refused = _quick(client, sale, cashier)
    assert refused.status_code == 403, refused.text
    assert client.get(f"{API}/pos-sales/{sale['id']}", headers=cashier).json()["client_id"] is None
    elsewhere = store.post("/locations", {"name": "Other", "time_zone": "America/Chicago", "country_code": "US"})["id"]
    other_email, _ = add_staff(store.tenant, "front_desk", location_ids=[elsewhere])
    assert _quick(client, sale, login(client, store.tenant, other_email)).status_code == 404


def test_duplicate_candidates_stay_within_the_cashiers_reach(client, store):
    """A coach with own reach never learns that someone outside it exists: the precheck skips them."""
    new_client(client, store.owner, store.location_id, first_name="Robin", last_name="Quick")
    email, user_id = add_staff(store.tenant, "coach", location_ids=[store.location_id])
    _override(client, store, user_id, "pos.sale.create", True)
    coach = login(client, store.tenant, email)
    made = _quick(client, start(store, coach), coach)
    assert made.status_code == 200, made.text


def test_receipt_footer_per_location_falls_back_to_billing(client, store):
    client.put(f"{API}/billing-settings", headers=store.owner, json={"receipt_footer": "Tenant footer"})
    url = f"{API}/pos-settings?location_id={store.location_id}"
    saved = client.put(url, headers=store.owner, json={"receipt_footer": "See you at Main"})
    assert saved.status_code == 200 and saved.json()["effective_receipt_footer"] == "See you at Main"
    assert client.put(url, headers=store.front, json={"receipt_footer": "x"}).status_code == 403
    done = cash_sale(store, headers=store.front)
    receipt = f"{API}/pos-sales/{done['id']}/receipt"
    assert client.get(receipt, headers=store.front).json()["footer"] == "See you at Main"
    cleared = client.put(url, headers=store.owner, json={"receipt_footer": None}).json()
    assert (cleared["receipt_footer"], cleared["effective_receipt_footer"]) == (None, "Tenant footer")
    assert client.get(receipt, headers=store.front).json()["footer"] == "Tenant footer"


def test_low_stock_digest_once_per_location_per_day(client, store, mailbox):
    def run() -> int:
        with tenant_session(store.tenant.id, actor=system_principal("tests")) as session:
            return inventory.send_low_stock_digests(session)

    cash_sale(store, quantity=3)  # 5 on hand, reorder at 2: now 2
    assert run() == 0  # no alert address yet
    url = f"{API}/pos-settings?location_id={store.location_id}"
    assert client.put(url, headers=store.owner, json={"low_stock_alert_email": "stock@example.com"}).status_code == 200
    assert run() == 1
    assert mailbox[-1].to == "stock@example.com" and "Water (0001): 2 on hand, reorder at 2" in mailbox[-1].body
    assert run() == 0  # the same local day
    assert len([m for m in mailbox if m.to == "stock@example.com"]) == 1


def test_birth_date_matches_only_for_a_cashier_who_may_see_it(client, store):
    """Without clients.client.read_sensitive a 409 on a typed birth date would confirm a guessed date of birth."""
    body = {
        "first_name": "Jordan",
        "last_name": "Quick",
        "birth_on": "2001-02-03",
        "home_location_id": store.location_id,
    }
    assert client.post(f"{API}/clients", headers=store.owner, json=body).status_code == 201
    guess = {"first_name": "Someone", "last_name": "Quick", "birth_on": "2001-02-03"}
    email, user_id = add_staff(store.tenant, "front_desk", location_ids=[store.location_id])
    _override(client, store, user_id, "clients.client.read_sensitive", False)
    cashier = login(client, store.tenant, email)
    blind = _quick(client, start(store, cashier), cashier, **guess)
    assert blind.status_code == 200, blind.text  # no birth-date match: a new client, no candidates leaked
    store.post(f"/pos-sales/{blind.json()['id']}/abandon", {}, headers=cashier)
    clash = _quick(client, start(store, store.front), store.front, **guess)
    assert clash.status_code == 409 and clash.json()["code"] == "possible-duplicate", clash.text
