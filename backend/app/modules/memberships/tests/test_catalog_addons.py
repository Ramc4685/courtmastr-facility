"""MEM-04: pre-defined billing items as plan add-ons, and per-sale add-on changes."""

from sqlalchemy import select

from app.modules.billing.models import Charge
from app.modules.memberships import service
from app.modules.memberships.models import MembershipContract, MembershipContractAddon
from app.modules.memberships.tests.support import API, category, ok, periods, sale, tx, world
from conftest import add_staff, login


def _item(client, w, **over) -> dict:
    body = {
        "location_id": w.location_id, "kind": "recurring", "description": "Towel service", "fee_minor": 500,
        "recurrence_unit": "month", "recurrence_every": 1, "recurrence_count": 1,
        "revenue_category_id": category(w.tenant, "TOWEL"),
    } | over  # fmt: skip
    return ok(client.post(f"{API}/catalog-items", headers=w.owner, json=body), 201)


def _one_off(client, w, **over) -> dict:
    fields = {"kind": "one_off", "description": "Key card", "fee_minor": 1000, "recurrence_unit": None,
              "recurrence_every": None, "recurrence_count": None}  # fmt: skip
    return _item(client, w, **(fields | over))


def _addon(item, quantity=1) -> dict:
    return {"addon_kind": "catalog_item", "catalog_item_id": item["id"], "quantity": quantity}


def test_item_add_ons_bill_with_the_dues_and_a_sale_can_change_them(client, owner, tenant):
    w = world(client, owner, tenant, billing_occurrences_count=3)
    towel, key = _item(client, w), _one_off(client, w, discount_minor=200)
    url = f"{API}/membership-plans/{w.plan['id']}/addons"
    assert client.put(url, headers=owner, json={"addons": [{"addon_kind": "catalog_item"}]}).status_code == 422
    plan = ok(client.put(url, headers=owner, json={"addons": [_addon(towel), _addon(key)]}))
    assert [a["catalog_item_id"] for a in plan["addons"]] == [towel["id"], key["id"]]

    quote = ok(client.post(f"{API}/membership-contracts/quote", headers=owner, json=sale(w)))
    addon_rows = [p for p in quote["periods"] if p["kind"] == "addon_item"]
    assert [p["amount_minor"] for p in addon_rows] == [500, 500, 500, 800]  # towel every month, key card once
    assert quote["total_minor"] == 3 * 3100 + 3 * 500 + 800

    contract = ok(client.post(f"{API}/membership-contracts", headers=owner, json=sale(w)), 201)
    rows = [p for p in periods(tenant, contract["id"]) if p.kind == "addon_item"]
    assert len(rows) == 4 and {str(p.catalog_item_id) for p in rows} == {towel["id"], key["id"]}
    billed = [p for p in rows if p.status == "billed"]
    assert {p.description for p in billed} == {f"{w.plan['name']}: Towel service", f"{w.plan['name']}: Key card"}
    with tx(tenant) as session:
        towel_charge = session.get(Charge, next(p.charge_id for p in billed if p.amount_minor == 500))
        assert str(towel_charge.revenue_category_id) == towel["revenue_category_id"]  # the item's own category


def test_changing_the_add_ons_of_one_sale_needs_customize_terms(client, owner, tenant):
    w = world(client, owner, tenant, billing_occurrences_count=2)
    towel = _item(client, w)
    ok(client.put(f"{API}/membership-plans/{w.plan['id']}/addons", headers=owner, json={"addons": [_addon(towel)]}))
    email, _ = add_staff(tenant, "front_desk", location_ids=[w.location_id])
    desk = login(client, tenant, email)
    assert client.post(f"{API}/membership-contracts", headers=desk, json=sale(w, addons=[])).status_code == 403
    same = client.post(f"{API}/membership-contracts", headers=desk, json=sale(w, addons=[_addon(towel)]))
    assert same.status_code == 201, same.text  # the plan's own list needs no extra key

    elsewhere = _item(client, world(client, owner, tenant), description="Elsewhere")
    w2 = world(client, owner, tenant, billing_occurrences_count=2)
    wrong = client.post(f"{API}/membership-contracts", headers=owner, json=sale(w2, addons=[_addon(elsewhere)]))
    assert (wrong.status_code, wrong.json()["errors"][0]["pointer"]) == (422, "/addons")
    body = sale(w2, addons=[_addon(_item(client, w2), 2)])
    doubled = ok(client.post(f"{API}/membership-contracts", headers=owner, json=body), 201)
    assert [p.amount_minor for p in periods(tenant, doubled["id"]) if p.kind == "addon_item"] == [1000, 1000]


def test_a_renewal_carries_recurring_item_add_ons_only(client, owner, tenant):
    w = world(client, owner, tenant, billing_occurrences_count=1)
    towel, key = _item(client, w), _one_off(client, w)
    body = sale(w, addons=[_addon(towel), _addon(key)])
    contract = ok(client.post(f"{API}/membership-contracts", headers=owner, json=body), 201)
    with tx(tenant) as session:
        current = session.get(MembershipContract, contract["id"])
        successor = service._renew(session, current, current.start_on)
        kept = session.scalars(
            select(MembershipContractAddon.catalog_item_id).where(
                MembershipContractAddon.membership_contract_id == successor.id
            )
        ).all()  # fmt: skip
        successor_id = successor.id
    assert [str(item_id) for item_id in kept] == [towel["id"]]
    got = sorted((p.kind, p.amount_minor) for p in periods(tenant, successor_id))
    assert got == [("addon_item", 500), ("dues", 3100)]
