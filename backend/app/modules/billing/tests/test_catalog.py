"""Pre-defined items (BIL-14): the catalogue, selling to a client, cancelling and the renewal job."""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select

from app.core.audit import AuditEvent
from app.core.dates import add_interval
from app.core.events import OutboxEvent
from app.modules import platform
from app.modules.billing import catalog
from app.modules.billing.models import CatalogItemSale, Charge, Invoice
from app.modules.billing.tests.test_billing import API, work

DAY = timedelta(days=1)


def _key() -> dict:
    return {"Idempotency-Key": f"cat-{uuid4().hex}"}


def _item(client, shop, **over) -> dict:
    body = {
        "location_id": str(shop.location_id), "kind": "recurring", "description": "Locker", "fee_minor": 3000,
        "discount_pct": "10", "recurrence_unit": "month", "recurrence_every": 1, "recurrence_count": 3,
        "revenue_category_id": str(shop.category_id),
    } | over  # fmt: skip
    response = client.post(f"{API}/catalog-items", headers=shop.owner, json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _one_off(**over) -> dict:
    return {"kind": "one_off", "recurrence_unit": None, "recurrence_every": None, "recurrence_count": None} | over


def _sell(client, shop, item, headers=None, **over):
    body = {"client_id": str(shop.client_id)} | over
    return client.post(f"{API}/catalog-items/{item['id']}/sales", headers=(headers or shop.owner) | _key(), json=body)


def _today(shop):
    with work(shop.tenant) as session:
        return platform.service.location_today(session, shop.location_id)


def test_item_validation_and_scoped_reads(client, shop, desk):
    bad = {"location_id": str(shop.location_id), "kind": "recurring", "description": "x", "fee_minor": 100,
           "revenue_category_id": str(shop.category_id)}  # fmt: skip
    response = client.post(f"{API}/catalog-items", headers=shop.owner, json=bad)
    assert (response.status_code, response.json()["errors"][0]["pointer"]) == (422, "/recurrence_count")
    both = bad | {"kind": "one_off", "discount_pct": "5", "discount_minor": 10}
    assert client.post(f"{API}/catalog-items", headers=shop.owner, json=both).status_code == 422
    assert client.post(f"{API}/catalog-items", headers=desk.front, json=bad | {"kind": "one_off"}).status_code == 403

    item = _item(client, shop)
    assert client.get(f"{API}/catalog-items/{item['id']}", headers=desk.front).status_code == 200
    assert client.get(f"{API}/catalog-items/{item['id']}", headers=desk.west_manager).status_code == 404
    assert client.patch(f"{API}/catalog-items/{item['id']}", headers=desk.west_manager, json={}).status_code == 404
    assert client.get(f"{API}/catalog-items?kind=recurring", headers=desk.west_manager).json()["data"] == []
    renamed = client.patch(f"{API}/catalog-items/{item['id']}", headers=shop.owner, json={"description": "Big locker"})
    assert renamed.json()["description"] == "Big locker"


def test_selling_a_recurring_item_expands_into_one_invoiced_charge_per_occurrence(client, shop, desk):
    item = _item(client, shop)
    today = _today(shop)
    response = _sell(client, shop, item, headers=desk.front)
    assert response.status_code == 201, response.text
    sale = response.json()
    assert (sale["status"], sale["starts_on"], sale["is_auto_renew"]) == ("active", today.isoformat(), False)
    assert sale["ends_on"] == (add_interval(today, "month", 3) - DAY).isoformat()
    assert len(sale["charge_ids"]) == 3 and len(sale["invoice_ids"]) == 1
    with work(shop.tenant) as session:
        charges = session.scalars(select(Charge).where(Charge.source_id == sale["id"]).order_by(Charge.source_line_no))
        rows = [(c.unit_price_minor, c.discount_minor, c.net_minor, c.tax_minor, c.service_starts_on) for c in charges]
        # 10% off once per line, then 8.25% tax on the net
        assert rows == [(3000, 300, 2700, 223, add_interval(today, "month", i)) for i in range(3)]
        assert session.get(Invoice, sale["invoice_ids"][0]).total_minor == 3 * 2923
        sold = session.scalar(select(OutboxEvent).where(OutboxEvent.aggregate_id == sale["id"]))
        assert sold.event_type == "billing.catalog_item_sale.sold"
        audits = session.scalars(select(AuditEvent.action).where(AuditEvent.entity_id == sale["id"])).all()
        assert audits == ["billing.charge.create"]

    listed = client.get(f"{API}/catalog-item-sales?client_id={shop.client_id}", headers=desk.front).json()["data"]
    assert [row["id"] for row in listed] == [sale["id"]]
    assert _sell(client, shop, item, headers=desk.west_manager).status_code == 404


def test_a_price_override_needs_its_own_key(client, shop, desk):
    item = _item(client, shop, **_one_off())
    assert _sell(client, shop, item, headers=desk.front, fee_minor=1000).status_code == 403
    assert _sell(client, shop, item, headers=desk.front, fee_minor=3000).status_code == 201  # same as the item
    sale = _sell(client, shop, item, fee_minor=1000, discount_minor=0, invoice_option="leave_uninvoiced").json()
    assert sale["terms"]["fee_minor"] == 1000 and sale["terms"]["discount_pct"] is None
    assert sale["invoice_ids"] == [] and sale["ends_on"] is None


def test_invoice_per_occurrence_dates_each_invoice_at_its_occurrence(client, shop):
    item = _item(client, shop, recurrence_count=2, invoice_option="invoice_per_occurrence", discount_pct=None)
    sale = _sell(client, shop, item).json()
    assert len(sale["invoice_ids"]) == 2
    today = _today(shop)
    with work(shop.tenant) as session:
        due = sorted(session.get(Invoice, invoice_id).due_on for invoice_id in sale["invoice_ids"])
    assert due == [today, add_interval(today, "month", 1)]


def test_cancel_reverses_the_occurrences_that_have_not_started(client, shop, desk):
    sale = _sell(client, shop, _item(client, shop)).json()
    url = f"{API}/catalog-item-sales/{sale['id']}/cancel"
    assert client.post(url, headers=desk.front, json={"reason": "moved away"}).status_code == 403
    assert client.post(url, headers=desk.west_manager, json={"reason": "moved away"}).status_code == 404
    cancelled = client.post(url, headers=shop.owner, json={"reason": "moved away"})
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    with work(shop.tenant) as session:
        statuses = session.scalars(
            select(Charge.status).where(Charge.source_id == sale["id"], Charge.kind == "standard")
            .order_by(Charge.source_line_no)
        ).all()  # fmt: skip
    assert statuses == ["active", "reversed", "reversed"]
    assert client.post(url, headers=shop.owner, json={"reason": "again"}).status_code == 409


def test_the_renewal_job_renews_once_and_ends_what_does_not_renew(client, shop):
    today = _today(shop)
    started = add_interval(today, "month", -1)
    full = _item(client, shop, **_one_off(length_count=1, length_unit="month", fee_minor=5000, discount_pct=None))
    intro = _item(client, shop, recurrence_count=1, is_auto_renew=True, renews_as_catalog_item_id=full["id"])
    copy = _item(client, shop, recurrence_count=1, is_auto_renew=True)
    plain = _item(client, shop, recurrence_count=1)
    sold = {
        item["id"]: _sell(client, shop, item, starts_on=started.isoformat()).json() for item in (intro, copy, plain)
    }
    assert sold[intro["id"]]["renew_on"] == today.isoformat()

    with work(shop.tenant) as session:
        assert catalog.renew_due(session) == {"renewed": 2, "ended": 1, "failed": 0}
    with work(shop.tenant) as session:
        assert catalog.renew_due(session) == {"renewed": 0, "ended": 0, "failed": 0}  # idempotent
        sales = list(session.scalars(select(CatalogItemSale)))
        status = {str(s.id): s.status for s in sales}
        successors = {str(s.previous_sale_id): s for s in sales if s.previous_sale_id}
    assert status[sold[plain["id"]]["id"]] == "ended"
    assert status[sold[intro["id"]]["id"]] == status[sold[copy["id"]]["id"]] == "renewed"
    as_full = successors[sold[intro["id"]]["id"]]
    assert (str(as_full.catalog_item_id), as_full.terms["fee_minor"], as_full.starts_on) == (full["id"], 5000, today)
    assert as_full.is_auto_renew is False  # the full-price item does not auto-renew itself
    repeat = successors[sold[copy["id"]]["id"]]
    assert (repeat.terms["fee_minor"], repeat.is_auto_renew) == (3000, True)
    assert repeat.renew_on == add_interval(today, "month", 1)
