"""Phase 12 chip C reports over two locations in different zones: Main (Chicago) and North (New York)."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.core import clock
from app.modules.reporting.reports import clients, pos, programs
from app.modules.reporting.tests.test_reporting import (  # noqa: F401 (fixtures)
    API,
    _location,
    ok,
    ran,
    rows,
    same_day_everywhere,
    world,
)
from conftest import new_client

CHIP_C = [s.key for family in (clients.SPECS, programs.SPECS, pos.SPECS) for s in family]


def _params(definition: dict) -> dict:
    if definition["key"] == "client_retention":
        return {"first_from_on": "2030-01-01", "first_to_on": "2030-12-31", "second_from_on": "2030-01-01",
                "second_to_on": "2030-12-31"}  # fmt: skip (populate's sessions are in 2030)
    if "period" in definition["params_schema"]["properties"]:
        today = clock.now().date()
        return {"from_on": str(today - timedelta(days=180)), "to_on": str(today + timedelta(days=180))}
    return {}


def test_every_chip_c_report_keeps_to_the_locations_asked_for(client, tenant):
    """populate() fills Main; a New York location with nothing in it must see none of Main's rows."""
    from conftest import populate

    world_ = populate(client, tenant)
    north = _location(client, world_.headers, "North", "America/New_York")
    definitions = {d["key"]: d for d in ok(client.get(f"{API}/report-definitions", headers=world_.headers))["data"]}
    leaked, empty = {}, []
    for key in CHIP_C:
        params = _params(definitions[key])
        if not ran(client, world_.headers, key, **params)["row_count"]:
            empty.append(key)
        got = ran(client, world_.headers, key, location_ids=[north], **params)
        if got["row_count"]:
            leaked[key] = got["row_count"]
    assert not empty and not leaked, (empty, leaked)


def test_check_ins_count_on_each_location_s_own_day(client, owner, world):
    # 05:30 UTC on 8 March: still the 7th in Chicago, already the 8th in New York.
    with clock.freeze(datetime(2026, 3, 8, 5, 30, tzinfo=UTC)):
        for location in (world.main, world.north):
            person = new_client(client, owner, location)["id"]
            body = {"client_id": person, "location_id": location, "channel": "staff_window"}
            ok(client.post(f"{API}/check-ins", headers=owner, json=body), 201)
    eighth = ran(client, owner, "check_in_summary", from_on="2026-03-08", to_on="2026-03-08")
    seventh = ran(client, owner, "check_in_summary", from_on="2026-03-07", to_on="2026-03-07")
    assert eighth["totals"]["check_ins"] == 1 and seventh["totals"]["check_ins"] == 1
    hours = {r["label"] for r in rows(client, owner, eighth["id"])["data"] if r["section"] == "By hour of day"}
    assert hours == {"00:00"}  # New York's local hour, not UTC's 05:00
    north = ran(client, owner, "check_in_summary", from_on="2026-03-07", to_on="2026-03-07", location_ids=[world.north])
    assert north["totals"]["check_ins"] == 0


def test_pos_sales_group_by_coupon_with_buying_price_and_margin(client, owner, world):
    def post(path, body, key=None):
        headers = owner | ({"Idempotency-Key": key} if key else {})
        response = client.post(f"{API}{path}", headers=headers, json=body)
        assert response.status_code in (200, 201), response.text
        return response.json()

    assert client.put(f"{API}/pos-settings", headers=owner, json={}).status_code == 200
    category = post("/product-categories", {"name": "Drinks", "revenue_category_id": world.category})
    product = post("/products", {"product_category_id": category["id"], "name": "Water", "product_code": "W-1", "sku": "0001",
                       "unit_price_minor": 250, "cost_minor": 100})  # fmt: skip
    post("/coupons", {"name": "Spring", "code": "SPRING", "starts_at": "2020-01-01T00:00:00Z", "discount_minor": 50})
    cash = next(t for t in client.get(f"{API}/tender-types", headers=owner).json() if t["kind"] == "cash")
    for location, coupon in ((world.main, True), (world.north, False)):
        post("/stock-movements", {"product_id": product["id"], "location_id": location, "kind": "adjustment",
                                  "quantity_delta": 5, "reason": "new_stock"})  # fmt: skip
        register = post("/registers", {"location_id": location, "name": "Desk"})
        post(f"/registers/{register['id']}/drawer-sessions", {"opening_float_minor": 0})
        sale = post("/pos-sales", {"register_id": register["id"], "client_id": world.person})
        sale = post(f"/pos-sales/{sale['id']}/lines", {"sku": "0001", "quantity": 2})
        if coupon:
            sale = post(f"/pos-sales/{sale['id']}/discounts", {"source": "coupon", "coupon_code": "SPRING"})
        body = {"tender": "payment", "tender_type_id": cash["id"], "amount_minor": sale["total_minor"]}
        sale = post(f"/pos-sales/{sale['id']}/tenders", body, key=uuid4().hex)
        assert post(f"/pos-sales/{sale['id']}/complete", {}, key=uuid4().hex)["status"] == "completed"

    period = {"period": "last_30_days"}
    by_coupon = ran(client, owner, "pos_sales", group_by="coupon", **period)
    assert [r["label"] for r in rows(client, owner, by_coupon["id"])["data"]] == ["Spring"]
    assert by_coupon["totals"]["cost_minor"] == 200  # only Main's coupon line: 2 x 100
    north = ran(client, owner, "pos_sales", group_by="product", location_ids=[world.north], **period)
    assert (north["totals"]["net_minor"], north["totals"]["cost_minor"], north["totals"]["margin_minor"]) == (
        500, 200, 300)  # fmt: skip
