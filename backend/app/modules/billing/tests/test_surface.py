"""Build module 8 through HTTP: configuration, the items workbench, invoices and schedules, documents and the
pay link, account credit, stored methods, the provider webhook, the client portal, and the permission gates."""

from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select, update

from app.core import clock, inbound_webhooks
from app.core.audit import AuditEvent
from app.core.auth import passwords
from app.core.db.platform import platform_engine
from app.modules import clients
from app.modules.billing import documents, methods
from app.modules.billing.models import BillingSettings, InvoicePayLink, LedgerTransaction, Payment
from app.modules.billing.tests.test_autopay import drain
from app.modules.billing.tests.test_billing import API, assert_books_agree, cash, charge, svc, work
from app.modules.billing.tests.test_money import NOON, TODAY
from app.modules.platform.models import Identity
from app.ports import payment_provider
from app.ports.payment_provider import sign
from conftest import PASSWORD, link_token, login, new_client


class Api:
    """`call("POST", path, body, 201)` asserts the status and returns the JSON; every POST sends a fresh
    Idempotency-Key, as the web client does."""

    def __init__(self, client, headers):
        self.client, self.headers = client, headers

    def __call__(self, method: str, path: str, body=None, status: int = 200, code: str | None = None, headers=None):
        extra = {"Idempotency-Key": f"test-{uuid4().hex}"} if method == "POST" else {}
        response = self.client.request(method, f"{API}{path}", json=body, headers=(headers or self.headers) | extra)
        assert response.status_code == status, f"{method} {path}: {response.status_code} {response.text}"
        payload = response.json() if response.content else None
        if code:
            assert payload["code"] == code, payload
        return payload


@pytest.fixture
def api(client, shop):
    return Api(client, shop.owner)


def item(shop, price=1000, **over) -> dict:
    return {"client_id": str(shop.client_id), "location_id": str(shop.location_id), "description": "Court hire",
            "unit_price_minor": price, "revenue_category_id": str(shop.category_id)} | over  # fmt: skip


# --- configuration -----------------------------------------------------------------------------------------


def test_taxes_are_dated_and_a_used_rate_is_frozen(api, shop, desk):
    vat = api("POST", "/taxes", {"code": "VAT", "label": "VAT", "rate": "0.2", "effective_from_on": "2020-01-01"}, 201)
    api("POST", "/taxes", {"code": "vat", "label": "Again", "rate": "0.1", "effective_from_on": "2020-01-01"}, 409,
        "already-exists")  # fmt: skip
    api("POST", "/taxes", {"code": "X", "label": "X", "rate": "0.1", "effective_from_on": "2020-01-01"}, 403,
        headers=desk.front)  # fmt: skip
    rates = api("POST", f"/taxes/{vat['id']}/rates", {"rate": "0.25", "effective_from_on": "2031-01-01"}, 201)["rates"]
    api("POST", f"/taxes/{vat['id']}/rates", {"rate": "0.3", "effective_from_on": "2031-01-01"}, 409, "already-exists")
    used, future = rates[0]["id"], rates[1]["id"]
    category = api("POST", "/revenue-categories", {"code": "VATABLE", "label": "Vatable", "tax_ids": [vat["id"]]}, 201)
    assert category["tax_ids"] == [vat["id"]]
    assert api("POST", "/charges", item(shop, revenue_category_id=category["id"]), 201)["tax_minor"] == 200
    later = api("POST", "/charges/preview", {"location_id": str(shop.location_id), "unit_price_minor": 1000,
                                             "revenue_category_id": category["id"], "revenue_on": "2031-06-01"})  # fmt: skip
    assert (later["tax_minor"], later["total_minor"], later["taxes"][0]["rate"]) == (250, 1250, "0.250000")
    api("PATCH", f"/taxes/{vat['id']}/rates/{used}", {"rate": "0.21"}, 409, "tax-rate-in-use")
    api("DELETE", f"/taxes/{vat['id']}/rates/{used}", None, 409, "tax-rate-in-use")
    assert float(api("PATCH", f"/taxes/{vat['id']}/rates/{future}", {"rate": "0.3"})["rates"][1]["rate"]) == 0.3
    api("DELETE", f"/taxes/{vat['id']}/rates/{future}", None, 204)
    api("DELETE", f"/taxes/{vat['id']}/rates/{future}", None, 404)
    spare = api(
        "POST", "/taxes", {"code": "SPARE", "label": "Spare", "rate": "0", "effective_from_on": "2020-01-01"}, 201
    )
    api("DELETE", f"/taxes/{spare['id']}/rates/{spare['rates'][0]['id']}", None, 409, "last-tax-rate")
    api("PATCH", f"/taxes/{vat['id']}/rates/{spare['rates'][0]['id']}", {"rate": "0.1"}, 404)  # a rate of another tax
    off = api("PATCH", f"/taxes/{vat['id']}", {"is_active": False, "label": "VAT (old)"})
    assert (off["is_active"], off["deactivated_on"], off["label"]) == (
        False,
        clock.now().astimezone(ZoneInfo("America/Chicago")).date().isoformat(),  # the shop's day, not UTC's
        "VAT (old)",
    )
    assert api("POST", "/charges", item(shop, revenue_category_id=category["id"]), 201)["tax_minor"] == 0
    assert api("PATCH", f"/taxes/{vat['id']}", {"is_active": True})["deactivated_on"] is None
    assert {row["code"] for row in api("GET", "/taxes?is_active=true")["data"]} >= {"VAT", "SPARE", "ST"}
    assert api("GET", f"/taxes/{vat['id']}")["rates"][0]["rate"] == "0.200000"


def test_revenue_categories_form_a_tree_without_loops(api, shop):
    parent = api("POST", "/revenue-categories", {"code": "SPORT", "label": "Sport"}, 201)
    child = api("POST", "/revenue-categories", {"code": "TENNIS", "label": "Tennis", "parent_id": parent["id"]}, 201)
    api("POST", "/revenue-categories", {"code": "sport", "label": "Dup"}, 409, "already-exists")
    api("PATCH", f"/revenue-categories/{parent['id']}", {"parent_id": child["id"]}, 422)
    api("PATCH", f"/revenue-categories/{parent['id']}", {"parent_id": parent["id"]}, 422)
    api("POST", "/revenue-categories", {"code": "ORPHAN", "label": "Orphan", "parent_id": str(uuid4())}, 422)
    updated = api("PATCH", f"/revenue-categories/{child['id']}", {"label": "Racquets", "tax_ids": [str(shop.tax_id)]})
    assert (updated["label"], updated["tax_ids"], updated["parent_id"]) == (
        "Racquets",
        [str(shop.tax_id)],
        parent["id"],
    )
    assert api("PATCH", f"/revenue-categories/{child['id']}", {"tax_ids": [], "is_active": False})["tax_ids"] == []
    api("POST", "/charges", item(shop, revenue_category_id=None), 201)  # creates the built-in categories
    builtin = api("GET", "/revenue-categories?q=UNCATEGORISED")["data"][0]
    api("PATCH", f"/revenue-categories/{builtin['id']}", {"is_active": False}, 409, "system-row")
    assert api("GET", f"/revenue-categories/{child['id']}")["is_active"] is False


def test_a_stored_card_shaped_footer_is_still_readable(api, shop):
    """The card scan guards writes; a value stored before it (or by an import) must never make a read fail."""
    api("PUT", "/billing-settings", {"invoice_footer": "Thank you"})
    with work(shop.tenant) as session:
        session.execute(
            update(BillingSettings)
            .where(BillingSettings.location_id.is_(None))
            .values(invoice_footer="4111 1111 1111 1111")
        )
    assert api("GET", "/billing-settings")["invoice_footer"] == "4111 1111 1111 1111"


def test_billing_settings_have_location_overrides_and_tenders_can_be_relabelled(api, shop, desk):
    defaults = api("GET", "/billing-settings")
    assert (defaults["autopay_retry_offset_days"], defaults["card_expiry_notice_days"], defaults["location_id"]) == (
        [3, 5, 7], [60, 30], None
    )  # fmt: skip
    api("PUT", "/billing-settings", {"autopay_retry_offset_days": [0, 2]}, 422)
    api("PUT", "/billing-settings", {"invoice_footer": "Thank you"}, 403, headers=desk.front)
    tenant_wide = api("PUT", "/billing-settings", {"invoice_footer": "Thank you", "due_reminder_offset_days": [-7, 1]})
    assert tenant_wide["due_reminder_offset_days"] == [-7, 1]
    here = f"/billing-settings?location_id={shop.location_id}"
    assert api("GET", here)["location_id"] is None  # no override yet: the tenant's row answers
    override = api("PUT", here, {"autopay_retry_offset_days": [2, 4], "decline_alert_email": "desk@example.com"})
    assert (override["location_id"], override["autopay_retry_offset_days"]) == (str(shop.location_id), [2, 4])
    assert api("GET", here)["decline_alert_email"] == "desk@example.com"
    assert api("GET", "/billing-settings")["invoice_footer"] == "Thank you"
    api("DELETE", here, None, 204)
    api("DELETE", here, None, 404)
    assert api("GET", here)["invoice_footer"] == "Thank you"
    api("GET", f"/billing-settings?location_id={uuid4()}", None, 404)

    tenders = {row["kind"]: row for row in api("GET", "/tender-types")}
    assert len(tenders) == 8 and tenders["card"]["is_processed"] and not tenders["gift_card"]["is_processed"]
    api("PATCH", f"/tender-types/{tenders['cash']['id']}", {"is_enabled": False}, 409, "tender-required")
    assert (
        api("PATCH", f"/tender-types/{tenders['cheque']['id']}", {"label": "Check", "is_enabled": False})["label"]
        == "Check"
    )
    api("POST", "/tender-types", {"kind": "other", "label": "Check"}, 409, "already-exists")
    api("POST", "/tender-types", {"kind": "card", "label": "Second card"}, 422)  # built-in kinds exist once


def test_closing_the_books_refuses_back_dated_postings(api, shop):
    assert api("GET", "/billing-settings/period-lock") == {"locked_through_on": None}
    assert api("PUT", "/billing-settings/period-lock", {"locked_through_on": "2026-09-30"}) == {
        "locked_through_on": "2026-09-30"
    }
    assert api("GET", "/billing-settings/period-lock") == {"locked_through_on": "2026-09-30"}  # the screen shows it
    api("POST", "/charges", item(shop, revenue_on="2026-09-30"), 409, "period-locked")
    assert api("POST", "/charges", item(shop, revenue_on="2026-10-01"), 201)["revenue_on"] == "2026-10-01"
    api("PUT", "/billing-settings/period-lock", {"locked_through_on": None})
    api("POST", "/charges", item(shop, revenue_on="2026-09-30"), 201)
    history = api("GET", "/billing-history?entity_type=tenant")["data"]
    assert [row["action"] for row in history] == ["billing.settings.manage"] * 2


# --- items -------------------------------------------------------------------------------------------------


def test_items_workbench_edits_and_coupons(api, shop, desk):
    api("POST", "/coupons", {"name": "Ten", "code": "TEN", "starts_at": "2020-01-01T00:00:00Z", "discount_pct": "10",
                             "limit_per_client": 1}, 201)  # fmt: skip
    api("POST", "/coupons", {"name": "Both", "code": "BOTH", "starts_at": "2020-01-01T00:00:00Z", "discount_pct": "10",
                             "discount_minor": 5}, 422)  # fmt: skip
    quote = api("POST", "/coupons/validate", {"code": "TEN", "subtotal_minor": 1000,
                                              "redeemer_client_id": str(shop.client_id)}, headers=desk.front)  # fmt: skip
    assert (quote["is_valid"], quote["discount_minor"]) == (True, 100)
    discounted = api("POST", "/charges", item(shop, coupon_code="TEN"), 201, headers=desk.front)
    assert (discounted["discount_minor"], discounted["net_minor"], discounted["tax_minor"]) == (100, 900, 74)
    assert discounted["coupon_id"] and discounted["created_by_staff_user_id"]
    api("POST", "/charges", item(shop, coupon_code="TEN"), 422, "coupon-limit-reached")
    api("POST", "/charges", item(shop, discount_minor=50), 403, headers=desk.front)  # a hand-typed discount
    plain = api("POST", "/charges", item(shop, discount_minor=50, internal_remarks="Staff only"), 201)
    coupon_id = api("GET", "/coupons?q=TEN")["data"][0]["id"]
    assert len(api("GET", f"/coupons/{coupon_id}/redemptions")) == 1
    api("DELETE", f"/coupons/{coupon_id}", None, 409, "coupon-in-use")
    assert api("PATCH", f"/coupons/{coupon_id}", {"is_active": False})["is_active"] is False
    assert api("GET", f"/coupons/{coupon_id}")["code"] == "TEN"

    detail = api("GET", f"/charges/{plain['id']}")
    assert detail["taxes"][0]["amount_minor"] == detail["tax_minor"] == 78
    renamed = api("PATCH", f"/charges/{plain['id']}", {"description": "Court 2", "service_starts_on": "2026-11-01"},
                  headers=desk.front)  # fmt: skip
    assert (renamed["id"], renamed["description"], renamed["service_starts_on"]) == (
        plain["id"],
        "Court 2",
        "2026-11-01",
    )
    api("PATCH", f"/charges/{plain['id']}", {"unit_price_minor": 5}, 403, headers=desk.front)  # needs price override
    api("PATCH", f"/charges/{plain['id']}", {"unit_price_minor": 2000}, 422)  # and a reason
    repriced = api("PATCH", f"/charges/{plain['id']}", {"unit_price_minor": 2000, "reason": "Peak rate"})
    assert (repriced["kind"], repriced["adjusts_charge_id"], repriced["net_minor"]) == ("adjustment", plain["id"], 1950)
    api("PATCH", f"/charges/{plain['id']}", {"description": "Too late"}, 409, "charge-not-reversible")

    api("POST", f"/charges/{repriced['id']}/void", {"reason": "Mistake"}, 403, headers=desk.front)
    api("POST", f"/charges/{repriced['id']}/void", {"reason": "Mistake"}, 404, headers=desk.west_manager)
    assert api("POST", f"/charges/{repriced['id']}/void", {"reason": "Mistake"})["status"] == "voided"
    cart = api("GET", f"/charges?is_uninvoiced=true&location_id={shop.location_id}")["data"]
    assert [row["id"] for row in cart] == [discounted["id"]]  # reversed, negating and voided rows are not the cart
    mine = api("GET", f"/charges?is_uninvoiced=true&created_by_staff_user_id={discounted['created_by_staff_user_id']}")
    assert len(mine["data"]) == 1 and len(api("GET", "/charges?status=voided")["data"]) == 2
    assert len(api("GET", "/charges?is_open=true&q=court")["data"]) == 1
    assert len(api("GET", "/charges?is_uninvoiced=false")["data"]) == 0
    history = api("GET", f"/billing-history?entity_type=charge&entity_id={plain['id']}")["data"]
    assert [row["action"] for row in history] == [
        "billing.charge.update",
        "billing.charge.update",
        "billing.charge.create",
    ]
    assert history[0]["reason"] == "Peak rate" and history[0]["changes"]["total_minor"] == [1028, 2111]
    api("GET", "/billing-history", None, 403, headers=desk.front)


# --- invoices ----------------------------------------------------------------------------------------------


def _bulk(api, body, status=202, **kw):
    made = api("POST", "/billing-bulk-actions", body, status, **kw)
    if status != 202:
        return made
    return made, api("GET", f"/billing-bulk-actions/{made['id']}/items?limit=100")["data"]


def test_bulk_invoicing_makes_one_invoice_per_client_and_never_mixes(client, api, shop, desk):
    other = new_client(client, shop.owner, shop.location_id)["id"]
    ids = [api("POST", "/charges", item(shop, price), 201)["id"] for price in (1000, 500)]
    ids.append(api("POST", "/charges", item(shop, 300, client_id=other), 201)["id"])
    invoiced = api("POST", "/charges", item(shop, 100), 201)["id"]
    api("POST", "/invoices", {"charge_ids": [invoiced]}, 201)
    body = {"action": "create_invoices", "location_id": str(shop.location_id), "charge_ids": [*ids, invoiced]}
    _bulk(api, body, 403, headers=desk.front)
    preview, rows = _bulk(api, body | {"is_dry_run": True})
    assert (preview["is_dry_run"], preview["status"], preview["done_count"]) == (True, "completed", 3)
    assert sorted(row["status"] for row in rows) == ["done", "done", "done", "skipped"]
    assert all(row["result_id"] is None for row in rows)  # a dry run keeps nothing
    assert len(api("GET", "/invoices")["data"]) == 1
    done, rows = _bulk(api, body | {"params": {"is_autopay": True}})
    assert (done["status"], done["item_count"], done["done_count"]) == ("completed", 4, 3)
    skipped = next(row for row in rows if row["status"] == "skipped")
    assert (skipped["subject_id"], skipped["error_code"]) == (invoiced, "charge-not-invoiceable")
    invoices = {row["group_client_id"]: row["result_id"] for row in rows if row["status"] == "done"}
    assert set(invoices) == {str(shop.client_id), other}
    assert len({row["result_id"] for row in rows if row["group_client_id"] == str(shop.client_id)}) == 1
    for client_id, invoice_id in invoices.items():
        invoice = api("GET", f"/invoices/{invoice_id}")
        assert invoice["bill_to_client_id"] == client_id and invoice["is_autopay"]
        assert {line["client_id"] for line in invoice["charges"]} == {client_id}  # never a mixed invoice
    assert api("GET", f"/billing-bulk-actions/{done['id']}")["status"] == "completed"
    _, again = _bulk(api, {"action": "create_invoices", "location_id": str(shop.location_id), "only_mine": True})
    assert again == []  # nothing uninvoiced is left
    api("POST", "/billing-bulk-actions", {"action": "create_invoices"}, 422)


def test_bulk_actions_are_capped_keyed_and_run_as_a_job_when_large(api, shop, monkeypatch):
    from app.modules.billing import bulk

    monkeypatch.setattr(bulk, "MAX_ITEMS", 2)
    for price in (100, 200, 300):
        api("POST", "/charges", item(shop, price), 201)
    body = {"action": "create_invoices", "location_id": str(shop.location_id)}
    refused = _bulk(api, body | {"is_dry_run": True}, 422)
    assert refused["errors"][0]["pointer"] == "/charge_ids"
    monkeypatch.setattr(bulk, "MAX_ITEMS", 3)
    monkeypatch.setattr(bulk, "IN_REQUEST_LIMIT", 1)
    sent = []
    monkeypatch.setattr(bulk.run_bulk_action, "send", lambda *args: sent.append(args))
    key = {"Idempotency-Key": f"bulk-{uuid4().hex}"}
    queued = api.client.post(f"{API}/billing-bulk-actions", headers=shop.owner | key, json=body)
    assert queued.status_code == 202 and queued.json()["status"] == "queued" and len(sent) == 1
    replay = api.client.post(f"{API}/billing-bulk-actions", headers=shop.owner | key, json=body)
    assert replay.json()["id"] == queued.json()["id"] and len(sent) == 1  # the key replays, nothing new
    other = api.client.post(f"{API}/billing-bulk-actions", headers=shop.owner | key, json=body | {"only_mine": True})
    assert other.status_code in (409, 422)  # the key is bound to the first request body
    with work(shop.tenant) as session:
        assert bulk.run_chunk(session, UUID(queued.json()["id"])) is False  # one client: one chunk
    done = api("GET", f"/billing-bulk-actions/{queued.json()['id']}")
    assert (done["status"], done["done_count"]) == ("completed", 3)


@pytest.mark.parametrize("in_request", [True, False])
def test_bulk_invoicing_skips_a_charge_with_no_client_and_always_finishes(api, shop, monkeypatch, in_request):
    """A clientless (POS) charge left uninvoiced by a void cannot go on a client's invoice: it is skipped with a
    reason, and a chunk that selects nothing fails what is left instead of looping for ever."""
    from app.modules.billing import bulk

    api("POST", "/charges", item(shop, 100), 201)
    with work(shop.tenant) as session:
        walk_in = charge(session, shop, 250, client_id=None, source_context="pos").id
    if not in_request:
        monkeypatch.setattr(bulk, "IN_REQUEST_LIMIT", 1)
        monkeypatch.setattr(bulk.run_bulk_action, "send", lambda *args: None)
    made = api(
        "POST", "/billing-bulk-actions", {"action": "create_invoices", "location_id": str(shop.location_id)}, 202
    )
    with work(shop.tenant) as session:
        for _ in range(5):  # the job: a bounded number of chunks, never for ever
            if not bulk.run_chunk(session, UUID(made["id"])):
                break
        else:
            pytest.fail("the bulk action never finished")
    done = api("GET", f"/billing-bulk-actions/{made['id']}")
    rows = api("GET", f"/billing-bulk-actions/{made['id']}/items?limit=100")["data"]
    assert (done["status"], done["done_count"]) == ("completed", 1)
    skipped = next(row for row in rows if row["subject_id"] == str(walk_in))
    assert (skipped["status"], skipped["error_code"]) == ("skipped", "charge-has-no-client")


def test_a_chunk_that_selects_nothing_fails_the_rest(api, shop):
    from app.modules.billing import bulk
    from app.modules.billing.models import BillingBulkActionItem

    api("POST", "/charges", item(shop, 100), 201)
    made = api("POST", "/billing-bulk-actions", {"action": "create_invoices", "location_id": str(shop.location_id),
                                                 "is_dry_run": True}, 202)  # fmt: skip
    with work(shop.tenant) as session:  # an item that no chunk can pick up (a payer the grouping cannot match)
        session.add(BillingBulkActionItem(
            billing_bulk_action_id=UUID(made["id"]), subject_type="charge", subject_id=uuid4(), group_client_id=None,
            status="pending",
        ))  # fmt: skip
        action = session.get(bulk.BillingBulkAction, UUID(made["id"]))
        action.status = "running"
        assert bulk.run_chunk(session, action.id) is False
        assert (
            session.scalar(
                select(BillingBulkActionItem.error_code).where(BillingBulkActionItem.group_client_id.is_(None))
            )
            == "not-processed"
        )


def test_bulk_reverse_email_render_and_add_item(api, shop, desk):
    from app.modules.billing.models import BillingDocumentDelivery

    loc = str(shop.location_id)
    ids = [api("POST", "/charges", item(shop, price), 201)["id"] for price in (1000, 500)]
    _bulk(api, {"action": "reverse_charges", "location_id": loc, "charge_ids": ids}, 422)  # a reason is required
    done, rows = _bulk(api, {"action": "reverse_charges", "location_id": loc, "charge_ids": ids,
                             "params": {"reason": "Entered twice"}})  # fmt: skip
    assert done["done_count"] == 2 and {row["result_type"] for row in rows} == {"charge"}
    assert {api("GET", f"/charges/{charge_id}")["status"] for charge_id in ids} == {"reversed"}
    invoice = api("POST", "/invoices", {"charge_ids": [api("POST", "/charges", item(shop, 700), 201)["id"]]}, 201)
    done, rows = _bulk(api, {"action": "email_invoices", "location_id": loc, "invoice_ids": [invoice["id"]]})
    assert (done["status"], rows[0]["error_code"]) == ("completed_with_errors", "no-email-address")  # reported
    done, rows = _bulk(api, {"action": "render_invoices", "location_id": loc, "invoice_ids": [invoice["id"]]})
    assert done["status"] == "completed" and rows[0]["result_type"] == "billing_document_delivery"
    with work(shop.tenant) as session:
        assert session.get(BillingDocumentDelivery, UUID(rows[0]["result_id"])).channel == "download"
    catalog_item = api(
        "POST",
        "/catalog-items",
        {
            "location_id": loc,
            "kind": "one_off",
            "description": "Locker",
            "fee_minor": 1000,
            "revenue_category_id": str(shop.category_id),
        },
        201,
    )
    body = {"action": "add_catalog_item", "location_id": loc, "client_ids": [str(shop.client_id)],
            "params": {"catalog_item_id": catalog_item["id"]}}  # fmt: skip
    done, rows = _bulk(api, body)
    assert (done["status"], rows[0]["result_type"]) == ("completed", "catalog_item_sale")


def test_a_bulk_action_is_location_scoped(client, api, shop):
    other = client.post(f"{API}/locations", headers=shop.owner,
                        json={"name": "North", "time_zone": "America/Chicago", "country_code": "US"}).json()["id"]  # fmt: skip
    mine = api("POST", "/charges", item(shop, 400), 201)["id"]
    done, rows = _bulk(api, {"action": "reverse_charges", "location_id": other, "charge_ids": [mine],
                             "params": {"reason": "x"}})  # fmt: skip
    assert rows[0]["status"] == "skipped" and api("GET", f"/charges/{mine}")["status"] == "active"


def test_invoice_edits_schedule_void_and_mark_paid(client, api, shop, desk):
    other = new_client(client, shop.owner, shop.location_id)["id"]
    first, second = (api("POST", "/charges", item(shop, price), 201)["id"] for price in (3000, 1000))
    invoice = api("POST", "/invoices", {"charge_ids": [first], "comments": "Autumn term"}, 201)
    path = f"/invoices/{invoice['id']}"
    assert (invoice["version"], invoice["comments"], invoice["dunning_state"]) == (1, "Autumn term", "none")
    edited = api("PATCH", path, {"is_autopay": True, "comments": None, "organization_name": "Acme", "version": 1},
                 headers=desk.front)  # fmt: skip
    assert (edited["is_autopay"], edited["comments"], edited["organization_name"], edited["version"]) == (
        True,
        None,
        "Acme",
        2,
    )
    api("PATCH", path, {"comments": "Stale", "version": 1}, 409, "stale-version")
    tomorrow = (clock.now().date() + timedelta(days=40)).isoformat()
    assert api("PATCH", path, {"due_on": tomorrow})["due_on"] == tomorrow
    api("PATCH", path, {"invoice_on": (clock.now().date() + timedelta(days=41)).isoformat()}, 422)
    assert len(api("POST", f"{path}/charges", {"charge_ids": [second]})["charges"]) == 2

    schedule = api("GET", f"{path}/payment-schedule")
    assert (schedule["total_minor"], len(schedule["instalments"])) == (4331, 1)
    api("PUT", f"{path}/payment-schedule", {"instalments": [{"due_on": tomorrow, "amount_minor": 1}]}, 422,
        "schedule-not-balanced")  # fmt: skip
    api("PUT", f"{path}/payment-schedule", {"instalments": [{"due_on": tomorrow, "amount_minor": 4331}]}, 403,
        headers=desk.front)  # fmt: skip
    generated = api("POST", f"{path}/payment-schedule/generate",
                    {"start_on": clock.now().date().isoformat(), "every": 2, "unit": "week", "count": 4})  # fmt: skip
    assert [row["amount_minor"] for row in generated["instalments"]] == [1083, 1083, 1083, 1082]
    api("PATCH", path, {"due_on": tomorrow}, 409, "invoice-has-schedule")
    typed = api("PUT", f"{path}/payment-schedule", {"instalments": [
        {"due_on": tomorrow, "amount_minor": 4000}, {"due_on": clock.now().date().isoformat(), "amount_minor": 331}]})  # fmt: skip
    assert [row["seq"] for row in typed["instalments"]] == [1, 2] and typed["instalments"][0]["amount_minor"] == 331

    target = api("POST", "/invoices", {"charge_ids": [api("POST", "/charges", item(shop, 10), 201)["id"]]}, 201)
    moved = api("POST", f"{path}/charges/{second}/move", {"target_invoice_id": target["id"]})
    assert moved["total_minor"] == 3248 and api("GET", f"/invoices/{target['id']}")["total_minor"] == 1094
    assert api("DELETE", f"/invoices/{target['id']}/charges/{second}")["total_minor"] == 11
    api("DELETE", f"/invoices/{target['id']}/charges/{second}", None, 404)

    api("POST", f"{path}/reassign-payer", {"bill_to_client_id": other}, 403, headers=desk.front)
    api("POST", f"{path}/reassign-payer", {"bill_to_client_id": other}, 422, "payer-not-related")  # a stranger
    parent_of = next(t["id"] for t in api("GET", "/relationship-types") if t["code"] == "parent_of")
    api("POST", f"/clients/{other}/relationships",
        {"other_client_id": str(shop.client_id), "relationship_type_id": parent_of}, 201)  # fmt: skip
    assert api("POST", f"{path}/reassign-payer", {"bill_to_client_id": other})["bill_to_client_id"] == other
    api("POST", f"{path}/reassign-payer", {"bill_to_client_id": str(uuid4())}, 422)
    paid = api("POST", f"{path}/mark-paid", {"external_reference": "BACS 4471"}, 201)
    assert (paid["tender_kind"], paid["amount_minor"], paid["client_id"]) == ("external", 3248, other)
    api("POST", f"{path}/mark-paid", {}, 409, "invoice-not-payable")
    api("POST", f"{path}/void", {"reason": "Wrong"}, 403, headers=desk.front)
    api("POST", f"{path}/void", {"reason": "Wrong"}, 409, "invoice-has-payments")
    voided = api("POST", f"{path}/void", {"reason": "Wrong", "release_allocations": True})
    assert (voided["status"], voided["void_reason"], voided["charges"], voided["total_minor"]) == (
        "voided",
        "Wrong",
        [],
        0,
    )
    api("PATCH", path, {"comments": "Late"}, 409, "invoice-voided")
    assert api("GET", f"/clients/{other}/account-credit")["credit_minor"] == 3248
    actions = [
        row["action"] for row in api("GET", f"/billing-history?entity_type=invoice&entity_id={invoice['id']}")["data"]
    ]
    assert actions[0] == "billing.invoice.void" and "billing.payment_schedule.manage" in actions


# --- documents, pay link, statements, ageing ---------------------------------------------------------------


@pytest.fixture
def emailed(client, shop):
    person = new_client(client, shop.owner, shop.location_id, primary_email=f"pat@{shop.tenant.slug}.example.com")
    return person["id"]


def test_invoice_email_carries_a_single_use_pay_link(client, api, shop, emailed, mailbox):
    slug = {"X-Tenant-Slug": shop.tenant.slug}
    charge_id = api("POST", "/charges", item(shop, client_id=emailed), 201)["id"]
    invoice = api("POST", "/invoices", {"charge_ids": [charge_id]}, 201)
    sent = api("POST", f"/invoices/{invoice['id']}/deliveries", {"channel": "email"}, 201)
    assert (sent["document_kind"], sent["status"], sent["to_email"]) == (
        "invoice",
        "sent",
        f"pat@{shop.tenant.slug}.example.com",
    )
    message = mailbox[-1]
    assert message.subject == f"Invoice {invoice['number']}" and "Court hire: 10.83 USD" in message.body
    assert "/pay#token=" in message.body and "?token=" not in message.body  # the token rides in the fragment
    token = link_token(message)
    with work(shop.tenant) as session:
        stored = session.scalars(select(InvoicePayLink)).one()
        assert stored.token_hash != token and len(stored.token_hash) == 64  # only a hash is at rest

    def public(path, body, status=200, code=None):
        return api("POST", f"/public/invoice-links/{path}", body, status, code, headers=slug)

    shown = public("lookup", {"token": token})
    assert (shown["number"], shown["balance_minor"], shown["bill_to_name"]) == (
        invoice["number"],
        1083,
        shown["bill_to_name"],
    )
    assert "client_id" not in str(shown) and len(shown["lines"]) == 1
    assert shown["provider"] == "fake"  # the pay page renders that processor's card entry
    public("lookup", {"token": "x" * 43}, 404, "link-invalid")
    declined = public("payments", {"token": token, "method_token": "tok_card_declined"}, 201)
    assert declined["status"] == "failed"
    public("lookup", {"token": token})  # a decline leaves the link usable
    paid = public("payments", {"token": token, "method_token": "tok_card_ok"}, 201)
    assert (paid["status"], paid["amount_minor"]) == ("succeeded", 1083)
    assert api("GET", f"/invoices/{invoice['id']}")["status"] == "paid"
    public("lookup", {"token": token}, 404, "link-invalid")  # used up by the payment
    public("payments", {"token": token, "method_token": "tok_card_ok"}, 404, "link-invalid")
    with work(shop.tenant) as session:
        assert session.scalars(select(InvoicePayLink)).one().payment_id is not None
        assert session.scalars(select(Payment.origin).where(Payment.status == "succeeded")).one() == "portal"
        assert_books_agree(session)

    api("POST", f"/invoices/{invoice['id']}/deliveries", {"channel": "email", "to_email": "boss@example.com"}, 201)
    assert mailbox[-1].to == "boss@example.com" and "/pay#token=" not in mailbox[-1].body  # nothing owed: no link
    assert api("POST", f"/invoices/{invoice['id']}/deliveries", {"channel": "print"}, 201)["to_email"] is None
    assert len(api("GET", f"/invoices/{invoice['id']}/deliveries")) == 3
    document = api("GET", f"/invoices/{invoice['id']}/document")
    assert (document["paid_minor"], document["lines"][0]["total_minor"], len(document["instalments"])) == (
        1083,
        1083,
        1,
    )


def test_an_expired_pay_link_and_a_payer_without_an_address(api, shop, emailed, mailbox):
    slug = {"X-Tenant-Slug": shop.tenant.slug}
    no_email = api("POST", "/invoices", {"charge_ids": [api("POST", "/charges", item(shop), 201)["id"]]}, 201)
    api("POST", f"/invoices/{no_email['id']}/deliveries", {}, 422, "no-email-address")
    invoice = api(
        "POST", "/invoices", {"charge_ids": [api("POST", "/charges", item(shop, client_id=emailed), 201)["id"]]}, 201
    )
    api("POST", f"/invoices/{invoice['id']}/deliveries", {}, 201)
    token = link_token(mailbox[-1])
    with clock.freeze(clock.now() + timedelta(days=documents.PAY_LINK_DAYS, minutes=1)):
        api("POST", "/public/invoice-links/lookup", {"token": token}, 404, "link-invalid", headers=slug)
        api("POST", "/public/invoice-links/payments", {"token": token, "method_token": "tok_card_ok"}, 404,
            "link-invalid", headers=slug)  # fmt: skip
    api("POST", f"/invoices/{invoice['id']}/void", {"reason": "Cancelled"})
    api("POST", f"/invoices/{invoice['id']}/deliveries", {}, 409, "invoice-voided")
    api("POST", "/public/invoice-links/lookup", {"token": token}, 404, headers={"X-Tenant-Slug": "no-such-tenant"})


def test_receipts_statements_credit_and_ageing(api, shop, emailed, mailbox):
    who = {"client_id": emailed, "location_id": str(shop.location_id)}
    with clock.freeze(NOON - timedelta(days=100)):
        old = api(
            "POST",
            "/invoices",
            {"charge_ids": [api("POST", "/charges", item(shop, 1000, client_id=emailed), 201)["id"]]},
            201,
        )
    with clock.freeze(NOON - timedelta(days=40)):
        api(
            "POST",
            "/invoices",
            {"charge_ids": [api("POST", "/charges", item(shop, 2000, client_id=emailed), 201)["id"]]},
            201,
        )
    with clock.freeze(NOON - timedelta(days=10)):
        payment = api(
            "POST", "/payments", who | {"amount_minor": 1500, "tender_kind": "cash", "invoice_id": old["id"]}, 201
        )
    with clock.freeze(NOON):
        api("POST", "/charges", item(shop, 300, client_id=emailed), 201)  # billed today, not invoiced
        receipt = api("GET", f"/payments/{payment['id']}/receipt")
        assert (receipt["received_minor"], receipt["applied_minor"], receipt["unapplied_minor"]) == (1500, 1083, 417)
        assert receipt["lines"] == [{"description": "Court hire", "invoice_id": old["id"], "amount_minor": 1083}]
        assert api("POST", f"/payments/{payment['id']}/receipt-deliveries", {}, 201)["document_kind"] == "receipt"
        assert "Received: 15.00 USD (cash)" in mailbox[-1].body and "On account: 4.17 USD" in mailbox[-1].body

        summary = api("GET", f"/clients/{emailed}/billing-summary")
        assert (summary["credit_minor"], summary["open_balance_minor"], summary["uninvoiced_minor"]) == (417, 2165, 325)
        credit = api("GET", f"/clients/{emailed}/account-credit")
        assert (credit["credit_minor"], [row["id"] for row in credit["payments"]]) == (417, [payment["id"]])
        ageing = api("GET", "/receivables-ageing")
        mine = next(row for row in ageing["rows"] if row["client_id"] == emailed)
        assert (mine["current"], mine["days_31_60"], mine["days_over_90"], mine["total_minor"]) == (325, 2165, 0, 2490)
        assert ageing["totals"]["total_minor"] == 2490 and ageing["as_of"] == TODAY.isoformat()
        before = api("GET", f"/receivables-ageing?as_of={(TODAY - timedelta(days=20)).isoformat()}")
        was = next(row for row in before["rows"] if row["client_id"] == emailed)  # before the payment was applied
        assert (was["days_61_90"], was["days_1_30"], was["current"], was["total_minor"]) == (1083, 2165, 0, 3248)
        assert api("GET", f"/receivables-ageing?location_id={uuid4()}")["rows"] == []

        applied = api("POST", f"/clients/{emailed}/account-credit/apply", {})
        assert (applied["applied_minor"], applied["credit_minor"]) == (417, 0)
        api("POST", f"/clients/{emailed}/account-credit/refund", {"amount_minor": 1, "reason": "None left"}, 422,
            "refund-exceeds-unapplied")  # fmt: skip
        extra = api(
            "POST", "/payments", who | {"amount_minor": 250, "tender_kind": "card", "method_token": "tok_card_ok"}, 201
        )
        batch = api(
            "POST", f"/clients/{emailed}/account-credit/refund", {"amount_minor": 250, "reason": "Leaving"}, 201
        )
        refunds = batch["refunds"]
        assert (batch["amount_minor"], batch["refunded_minor"]) == (250, 250)
        assert batch["refund_batch_id"] == refunds[0]["refund_batch_id"]
        assert [(row["payment_id"], row["method"], row["status"]) for row in refunds] == [
            (extra["id"], "original", "succeeded")
        ]
        assert len(api("GET", f"/refunds?refund_batch_id={refunds[0]['refund_batch_id']}")["data"]) == 1

        period = f"from_on={(TODAY - timedelta(days=60)).isoformat()}&to_on={TODAY.isoformat()}"
        statement = api("GET", f"/clients/{emailed}/statement?{period}")
        assert (len(statement["invoices"]), statement["invoiced_minor"], statement["paid_minor"]) == (1, 2165, 1750)
        assert (statement["refunded_minor"], statement["balance_due_minor"]) == (250, 2165 - 417)
        assert len(api("GET", f"/clients/{emailed}/statement?{period}&date_basis=due_date")["invoices"]) == 1
        assert len(api("GET", f"/clients/{emailed}/statement")["invoices"]) == 0  # the default 30 days
        api("GET", f"/clients/{emailed}/statement?from_on=2020-01-01&to_on=2026-01-01", None, 422)
        body = {"from_on": (TODAY - timedelta(days=60)).isoformat(), "to_on": TODAY.isoformat()}
        assert api("POST", f"/clients/{emailed}/statement/deliveries", body, 201)["document_kind"] == "statement"
        assert "Balance due: 17.48 USD" in mailbox[-1].body and "Statement for" in mailbox[-1].body
        api("POST", f"/clients/{shop.client_id}/statement/deliveries", body, 422, "no-email-address")
    kinds = [row["kind"] for row in api("GET", "/billing-notices")["data"]]
    assert kinds == []  # nothing was declined or reminded here


# --- payments through the API ------------------------------------------------------------------------------


def test_payment_commands_and_their_gates(api, shop, desk, monkeypatch):
    who = {"client_id": str(shop.client_id), "location_id": str(shop.location_id)}
    charge_id = api("POST", "/charges", item(shop), 201)["id"]
    invoice = api("POST", "/invoices", {"charge_ids": [charge_id]}, 201)
    payment = api("POST", "/payments", who | {"amount_minor": 1083, "tender_kind": "gift_card", "invoice_id": invoice["id"],
                                              "external_reference": "GC-77"}, 201, headers=desk.front)  # fmt: skip
    allocation = payment["allocations"][0]["id"]
    path = f"/payments/{payment['id']}"
    api("DELETE", f"{path}/allocations/{allocation}", None, 403, headers=desk.front)
    released = api("DELETE", f"{path}/allocations/{allocation}")
    assert (released["unapplied_minor"], released["allocations"][0]["release_reason"]) == (1083, "unapplied")
    api("DELETE", f"{path}/allocations/{allocation}", None, 409, "allocation-released")
    api("DELETE", f"{path}/allocations/{uuid4()}", None, 404)
    api("POST", f"{path}/void", {"reason": "Wrong card"}, 403, headers=desk.front)
    api("POST", f"{path}/void", {"reason": "Wrong card"}, 404, headers=desk.west_manager)
    assert api("POST", f"{path}/void", {"reason": "Wrong card"})["status"] == "voided"
    api("POST", f"{path}/cancel", None, 409, "payment-not-cancellable")
    api("POST", f"{path}/receipt-deliveries", {"channel": "download"}, 201)
    waiting = api(
        "POST", "/payments", who | {"amount_minor": 500, "tender_kind": "card", "method_token": "tok_card_auth"}, 201
    )
    assert waiting["status"] == "requires_action" and waiting["client_secret"]
    assert api("GET", f"/payments/{waiting['id']}")["client_secret"] is None  # never stored
    api("POST", f"/payments/{waiting['id']}/receipt-deliveries", {"channel": "download"}, 409, "payment-not-settled")
    assert api("POST", f"/payments/{waiting['id']}/cancel")["status"] == "cancelled"

    stored = api(
        "POST", f"/clients/{shop.client_id}/payment-methods", {"method_token": "tok_card_ok"}, 201, headers=desk.front
    )
    assert stored["is_autopay"] and "provider_method_ref" not in stored and "tok_" not in str(stored)
    api("POST", f"/clients/{shop.client_id}/payment-methods", {"method_token": "nope"}, 422, "payment-method-rejected")
    api("POST", f"/clients/{shop.client_id}/payment-methods", {"method_token": "tok_card_ok"}, 403, headers=desk.viewer)
    secret = api(
        "POST", f"/clients/{shop.client_id}/payment-methods/setup-intents", {"kinds": ["card", "bank_account"]}, 201
    )
    assert secret["provider"] == "fake" and secret["client_secret"]
    by_method = api("POST", "/payments", who | {"amount_minor": 1083, "tender_kind": "card", "invoice_id": invoice["id"],
                                                "payment_method_id": stored["id"]}, 201)  # fmt: skip
    assert by_method["status"] == "succeeded" and api("GET", f"/invoices/{invoice['id']}")["status"] == "paid"
    bank = api("POST", f"/clients/{shop.client_id}/payment-methods", {"method_token": "tok_ach_unverified"}, 201)
    api("POST", f"/payment-methods/{bank['id']}/verify", {"amounts": [1, 2]}, 422, "verification-failed")
    assert api("POST", f"/payment-methods/{bank['id']}/verify", {"amounts": [32, 45]})["status"] == "active"
    assert api("PATCH", f"/payment-methods/{bank['id']}", {"is_autopay": True})["is_autopay"] is True
    listed = api("GET", f"/clients/{shop.client_id}/payment-methods")
    assert [(row["kind"], row["is_autopay"]) for row in listed] == [("card", False), ("bank_account", True)]
    assert len(api("GET", "/payment-methods?kind=card&exp_year=2099")["data"]) == 1
    api("DELETE", f"/payment-methods/{stored['id']}", None, 204)
    api("DELETE", f"/payment-methods/{stored['id']}", None, 409, "payment-method-removed")
    assert len(api("GET", f"/clients/{shop.client_id}/payment-methods")) == 1

    accounts = api("GET", "/provider-accounts")
    assert [(row["provider"], row["status"], row["has_card"]) for row in accounts] == [("fake", "active", True)]
    api("POST", "/provider-accounts", {"provider": "fake"}, 409, "processor-already-connected")
    api("POST", "/provider-accounts", {"provider": "stripe"}, 409, "provider-unavailable")  # disabled by default
    api("POST", "/provider-accounts", {"provider": "fake"}, 403, headers=desk.front)
    assert "/billing/setup" in api("POST", f"/provider-accounts/{accounts[0]['id']}/onboarding-links")["url"]
    assert api("POST", f"/provider-accounts/{accounts[0]['id']}/disconnect")["status"] == "disabled"
    api("POST", f"/provider-accounts/{accounts[0]['id']}/disconnect", None, 409, "processor-not-connected")
    api("POST", "/payments", who | {"amount_minor": 5, "tender_kind": "card", "method_token": "tok_card_ok"}, 409,
        "processor-not-connected")  # fmt: skip
    assert api("GET", f"/clients/{shop.client_id}/payment-methods") == []  # its stored methods went with it
    fake = payment_provider.get("fake")

    def refuse(**_):
        raise ValueError("Review your platform profile.")

    monkeypatch.setattr(fake, "create_account", refuse)
    api("POST", "/provider-accounts", {"provider": "fake"}, 409, "provider-refused")  # the processor's no, not a 500
    monkeypatch.undo()
    again = api("POST", "/provider-accounts", {"provider": "fake"}, 201)
    assert again["status"] == "active" and again["id"] != accounts[0]["id"]
    assert (
        api("POST", "/payments", who | {"amount_minor": 5, "tender_kind": "card", "method_token": "tok_card_ok"}, 201)[
            "status"
        ]
        == "succeeded"
    )


def test_two_people_sending_the_same_key_get_their_own_payments(api, shop, desk):
    """An Idempotency-Key is the caller's own: the same string from someone else is another payment."""
    body = {"client_id": str(shop.client_id), "location_id": str(shop.location_id), "amount_minor": 500,
            "tender_kind": "card", "method_token": "tok_card_ok"}  # fmt: skip
    send = lambda headers, amount: api.client.post(  # noqa: E731
        f"{API}/payments", json=body | {"amount_minor": amount}, headers=headers | {"Idempotency-Key": "same-key-0001"}
    ).json()
    mine, theirs = send(shop.owner, 500), send(desk.front, 700)
    assert mine["id"] != theirs["id"] and (mine["amount_minor"], theirs["amount_minor"]) == (500, 700)
    assert send(shop.owner, 500)["id"] == mine["id"]  # the same person repeating it is a replay
    assert len(api("GET", "/payments")["data"]) == 2


def test_autopay_through_the_api(api, shop, desk):
    api("POST", f"/clients/{shop.client_id}/payment-methods", {"method_token": "tok_card_insufficient"}, 201)
    invoice = api(
        "POST", "/invoices", {"charge_ids": [api("POST", "/charges", item(shop), 201)["id"]], "is_autopay": True}, 201
    )
    start = {"location_id": str(shop.location_id)}
    api("POST", "/autopay-runs", start, 403, headers=desk.front)
    api("POST", "/autopay-runs", {"location_id": str(desk.west)} | {}, 201, headers=desk.west_manager)
    api("POST", "/autopay-runs", start, 404, headers=desk.west_manager)
    preview = api("POST", "/autopay-runs", start | {"is_dry_run": True}, 201)
    assert preview["run"] is None and preview["preview"][0]["invoice_id"] == invoice["id"]
    run = api("POST", "/autopay-runs", start, 201)["run"]
    assert (run["status"], run["failed_count"]) == ("completed_with_errors", 1)
    assert api("GET", f"/autopay-runs/{run['id']}")["selected_count"] == 1
    api("GET", f"/autopay-runs/{run['id']}", None, 404, headers=desk.west_manager)
    assert (
        len(api("GET", "/autopay-runs")["data"]) == 2
        and len(api("GET", "/autopay-runs", headers=desk.front)["data"]) == 1
    )
    errors = api("GET", "/autopay-attempts?status=failed&is_error_open=true")["data"]
    assert [(row["invoice_id"], row["failure_category"]) for row in errors] == [(invoice["id"], "insufficient_funds")]
    assert api("GET", "/autopay-attempts", headers=desk.west_manager)["data"] == []
    assert api("GET", f"/invoices/{invoice['id']}")["dunning_state"] == "retrying"
    api("POST", f"/autopay-attempts/{errors[0]['id']}/clear-error", None, 403, headers=desk.front)
    assert api("POST", f"/autopay-attempts/{errors[0]['id']}/clear-error")["error_cleared_at"]
    assert api("GET", "/autopay-attempts?status=failed&is_error_open=true")["data"] == []
    retried = api("POST", f"/autopay-attempts/{errors[0]['id']}/retry", None, 201)
    assert (retried["attempt_no"], retried["status"]) == (2, "failed")
    assert [row["kind"] for row in api("GET", "/billing-notices?kind=payment_declined")["data"]] == [
        "payment_declined"
    ] * 2


# --- provider webhooks -------------------------------------------------------------------------------------


def test_webhooks_are_verified_stored_once_and_idempotent(client, shop):
    fake = payment_provider.get("fake")
    with work(shop.tenant) as session:
        invoice = svc.create_invoice_for_charges(session, [charge(session, shop).id])
        payment = svc.take_payment(
            session, client_id=shop.client_id, location_id=shop.location_id, amount_minor=invoice.total_minor,
            tender_kind="bank_debit", method_token="tok_ach_ok", idempotency_key=uuid4().hex, invoice_id=invoice.id,
        )  # fmt: skip
        fake.settle(payment.provider_payment_ref)
        payment_id, invoice_id, provider_ref = payment.id, invoice.id, payment.provider_payment_ref
    headers, body = fake.outbox.pop()

    def deliver(send_headers=headers, content=body, path="fake"):
        return client.post(f"{API}/webhooks/{path}", content=content, headers=send_headers)

    assert deliver(path="stripe").status_code == 404  # the Stripe adapter is not enabled here
    for forged in ({}, {"fake-signature": "t=1,v1=00"}, {"fake-signature": sign("wrong-secret", body)}):
        rejected = deliver(forged)
        assert (rejected.status_code, rejected.json()["code"]) == (400, "invalid-signature")
    tampered = deliver(content=body.replace(b"succeeded", b"failed!!!"))
    assert tampered.status_code == 400
    stale = {"fake-signature": sign("whsec_fake_dev_only", body, timestamp=1)}
    assert deliver(stale).status_code == 400  # a captured delivery cannot be replayed later
    with work(shop.tenant) as session:
        assert session.get(Payment, payment_id).status == "processing"  # nothing forged got through

    assert deliver().json() == {"result": "accepted"}
    assert deliver().json() == {"result": "duplicate"}  # redelivered before it was processed
    drain()
    with work(shop.tenant) as session:
        assert session.get(Payment, payment_id).status == "succeeded"
        assert session.get(svc.Invoice, invoice_id).status == "paid"
        posted = session.scalar(select(func.count()).select_from(LedgerTransaction))
    assert deliver().json() == {"result": "duplicate"}
    drain()
    with platform_engine().connect() as conn:
        stored = conn.exec_driver_sql(
            "SELECT id, status, tenant_id FROM inbound_webhook_event WHERE tenant_id = %s", (shop.tenant.id,)
        ).all()
    assert [(row.status, row.tenant_id) for row in stored] == [("processed", shop.tenant.id)]
    # The same event processed again, and a second, different event about the same payment: no new postings.
    from app.modules.billing import webhooks

    webhooks.process_provider_event.fn(str(shop.tenant.id), str(stored[0].id))
    fake._emit(fake._payments[provider_ref][3], "payment", provider_ref, "payment.succeeded")
    again_headers, again_body = fake.outbox.pop()
    assert deliver(again_headers, again_body).json() == {"result": "accepted"}
    drain()
    with work(shop.tenant) as session:
        assert session.scalar(select(func.count()).select_from(LedgerTransaction)) == posted
        assert_books_agree(session)

    fake._emit("fake_acct_nobody", "payment", "fake_pay_x", "payment.succeeded")
    orphan_headers, orphan_body = fake.outbox.pop()
    assert deliver(orphan_headers, orphan_body).json() == {"result": "ignored"}  # kept, not dropped
    assert inbound_webhooks.record("fake", "evt-malformed-test-" + uuid4().hex, None, "x", {}) is not None
    bad = b'{"id": "only"}'
    assert deliver({"fake-signature": sign("whsec_fake_dev_only", bad)}, bad).status_code == 400


def test_disputes_arrive_by_webhook_and_move_the_money(client, shop):
    """PAY-17: opened releases the allocations and parks the funds; won returns them as credit; lost charges
    back. Replays change nothing, a bank-debit dispute is lost on arrival, inquiries are ignored."""
    from app.modules.billing.models import Dispute

    fake = payment_provider.get("fake")
    fake.outbox.clear()  # deliveries other tests left behind

    def paid(token="tok_card_ok", kind="card"):
        with work(shop.tenant) as session:
            invoice = svc.create_invoice_for_charges(session, [charge(session, shop).id])
            payment = svc.take_payment(
                session, client_id=shop.client_id, location_id=shop.location_id, amount_minor=invoice.total_minor,
                tender_kind=kind, method_token=token, idempotency_key=uuid4().hex, invoice_id=invoice.id,
            )  # fmt: skip
            if kind == "bank_debit":
                fake.settle(payment.provider_payment_ref)
                fake.outbox.clear()
                svc.confirm_payment(session, payment.id)
            return payment.id, invoice.id, payment.provider_payment_ref, invoice.total_minor

    def deliver_all():
        while fake.outbox:
            headers, body = fake.outbox.pop(0)
            assert client.post(f"{API}/webhooks/fake", content=body, headers=headers).status_code == 200
        drain()

    def state(payment_id, invoice_id):
        with work(shop.tenant) as session:
            payment, invoice = session.get(Payment, payment_id), session.get(svc.Invoice, invoice_id)
            dispute = session.scalars(select(Dispute).where(Dispute.payment_id == payment_id)).one_or_none()
            assert_books_agree(session)
            return payment.status, payment.unapplied_minor, invoice.status, dispute and dispute.status

    won_id, won_invoice, won_ref, total = paid()
    dispute_ref = fake.open_dispute(won_ref)
    replay = list(fake.outbox)
    deliver_all()
    assert state(won_id, won_invoice) == ("disputed", 0, "open", "open")
    # A redelivery (re-signed, as a processor does on every attempt), then the same event under a new id.
    fake.outbox.extend(({"fake-signature": sign("whsec_fake_dev_only", body)}, body) for _, body in replay)
    fake._emit(fake._payments[won_ref][3], "dispute", dispute_ref, "dispute.updated")
    deliver_all()
    assert state(won_id, won_invoice) == ("disputed", 0, "open", "open")
    fake.close_dispute(dispute_ref, won=True)
    deliver_all()
    assert state(won_id, won_invoice) == ("succeeded", total, "open", "won")  # credit, not re-applied

    lost_id, lost_invoice, lost_ref, _ = paid()
    fake.close_dispute(fake.open_dispute(lost_ref), won=False)
    deliver_all()
    assert state(lost_id, lost_invoice) == ("charged_back", 0, "open", "lost")

    ach_id, ach_invoice, ach_ref, _ = paid("tok_ach_ok", "bank_debit")
    fake.open_dispute(ach_ref)
    deliver_all()
    assert state(ach_id, ach_invoice) == ("charged_back", 0, "open", "lost")

    quiet_id, quiet_invoice, quiet_ref, _ = paid()
    inquiry = fake.open_dispute(quiet_ref)
    fake._disputes[inquiry] = (replace(fake._disputes[inquiry][0], status=None), fake._disputes[inquiry][1])
    deliver_all()
    assert state(quiet_id, quiet_invoice) == ("succeeded", 0, "paid", None)
    with work(shop.tenant) as session:
        kinds = session.scalars(select(LedgerTransaction.kind).where(LedgerTransaction.source_type == "dispute")).all()
    assert sorted(kinds) == ["dispute_lost", "dispute_lost", "dispute_opened", "dispute_opened", "dispute_opened",
                             "dispute_won"]  # fmt: skip


def test_webhook_events_for_methods_and_accounts(shop):
    from app.modules.billing import webhooks

    fake = payment_provider.get("fake")
    with work(shop.tenant) as session:
        method = methods.attach_method(session, shop.client_id, "tok_card_ok")
        state, token = fake._methods[method.provider_method_ref]
        fake._methods[method.provider_method_ref] = (
            state.__class__(**{**state.__dict__, "exp_year": 2101, "last4": "1111"}),
            token,
        )
        webhooks.apply_event(session, "method", method.provider_method_ref)  # the card updater replaced the card
        assert (method.exp_year, method.last4) == (2101, "1111")
        account = svc._provider_account(session)
        account.has_card = False
        webhooks.apply_event(session, "account", account.provider_account_ref)
        assert account.has_card is True
        for nothing in (("payment", "fake_pay_unknown"), ("refund", "fake_ref_unknown"), ("method", "pm_unknown"),
                        ("account", "acct_unknown"), ("other", "x"), ("payment", None)):  # fmt: skip
            webhooks.apply_event(session, *nothing)  # events about objects we do not hold are ignored


# --- client portal -----------------------------------------------------------------------------------------


@pytest.fixture
def member(client, shop):
    """A client who can sign in to the portal, and a second client they have nothing to do with."""
    email = f"member@{shop.tenant.slug}.example.com"
    me = new_client(client, shop.owner, shop.location_id, primary_email=email)["id"]
    stranger = new_client(client, shop.owner, shop.location_id)["id"]
    with work(shop.tenant) as session:
        identity = Identity(kind="client", email=email, status="active", email_verified_at=clock.now(),
                            password_hash=passwords.hash_password(PASSWORD))  # fmt: skip
        session.add(identity)
        session.flush()
        clients.service.link_identity(session, UUID(me), identity.id)
    headers = login(client, shop.tenant, email, audience="client")
    return type("Member", (), {"id": me, "stranger": stranger, "headers": headers, "api": Api(client, headers)})


def test_a_client_sees_and_pays_only_their_own_invoices(api, shop, member):
    def invoice_for(client_id, price=1000, **over):
        return api(
            "POST",
            "/invoices",
            {"charge_ids": [api("POST", "/charges", item(shop, price, client_id=client_id), 201)["id"]]} | over,
            201,
        )

    mine, second, theirs = invoice_for(member.id), invoice_for(member.id, 500), invoice_for(member.stranger)
    portal = member.api
    listed = portal("GET", "/portal/invoices?is_payable=true")["data"]
    assert {row["id"] for row in listed} == {mine["id"], second["id"]}
    document = portal("GET", f"/portal/invoices/{mine['id']}")
    assert document["balance_minor"] == 1083
    assert {row["currency"] for row in listed} == {document["currency"]}  # the app formats amounts with it
    portal("GET", f"/portal/invoices/{theirs['id']}", None, 404)
    portal("GET", "/invoices", None, 403)  # the staff surface is closed to clients
    api("GET", "/portal/invoices", None, 403)  # and the portal is for clients
    api("GET", "/portal/payment-methods", None, 403)
    summary = portal("GET", "/portal/billing-summary")
    assert (summary["client_id"], summary["open_balance_minor"]) == (member.id, 1624)
    portal("GET", f"/portal/billing-summary?client_id={member.stranger}", None, 404)

    card = portal("POST", "/portal/payment-methods", {"method_token": "tok_card_ok"}, 201)
    assert (
        card["client_id"] == member.id
        and portal("POST", "/portal/payment-methods/setup-intents", {}, 201)["client_secret"]
    )
    their_card = api("POST", f"/clients/{member.stranger}/payment-methods", {"method_token": "tok_card_ok"}, 201)
    pay = lambda body, status=201, code=None: portal("POST", "/portal/payments", body, status, code)  # noqa: E731
    pay({"invoice_ids": [mine["id"]], "payment_method_id": their_card["id"]}, 422, "payment-method-not-usable")
    pay({"invoice_ids": [theirs["id"]], "payment_method_id": card["id"]}, 404)
    pay({"invoice_ids": [mine["id"]]}, 422)  # no way to pay named
    pay({"invoice_ids": [mine["id"]], "payment_method_id": card["id"], "amount_minor": 0}, 422)  # above zero
    api("POST", "/payments", {"client_id": member.id, "location_id": str(shop.location_id), "amount_minor": 100,
                              "tender_kind": "cash"}, 201)  # fmt: skip
    paid = pay({"invoice_ids": [mine["id"], second["id"]], "payment_method_id": card["id"], "use_account_credit": True,
                "set_autopay": True})  # fmt: skip
    assert (paid["credit_applied_minor"], paid["payment"]["amount_minor"], paid["payment"]["status"]) == (
        100,
        1524,
        "succeeded",
    )
    assert paid["payment"]["origin"] == "portal" and paid["payment"]["client_id"] == member.id
    assert {api("GET", f"/invoices/{row['id']}")["status"] for row in (mine, second)} == {"paid"}
    assert api("GET", f"/invoices/{mine['id']}")["is_autopay"] is True
    pay({"invoice_ids": [mine["id"]], "payment_method_id": card["id"]}, 409, "invoice-not-payable")
    assert (
        len(portal("GET", "/portal/payments")["data"]) == 2
        and portal("GET", "/portal/invoices?is_payable=true")["data"] == []
    )
    with work(shop.tenant) as session:
        actors = set(session.scalars(select(AuditEvent.actor_type).where(AuditEvent.action == "billing.payment.take")))
        assert actors == {"staff", "client"}
        assert_books_agree(session)

    # a client replaces, but cannot remove, their last method while an autopay invoice is open
    open_autopay = invoice_for(member.id, 200, is_autopay=True)
    portal("PATCH", f"/portal/payment-methods/{their_card['id']}", {"is_autopay": True}, 404)
    portal("DELETE", f"/portal/payment-methods/{their_card['id']}", None, 404)
    portal("DELETE", f"/portal/payment-methods/{card['id']}", None, 409, "payment-method-required")
    spare = portal("POST", "/portal/payment-methods", {"method_token": "tok_card_ok", "is_autopay": False}, 201)
    portal("DELETE", f"/portal/payment-methods/{card['id']}", None, 204)
    assert portal("PATCH", f"/portal/payment-methods/{spare['id']}", {"is_autopay": True})["is_autopay"] is True
    assert api("GET", f"/invoices/{open_autopay['id']}")["status"] == "open"  # dunning state none: nothing waited
    assert [row["id"] for row in portal("GET", "/portal/payment-methods")] == [spare["id"]]
    declined = portal(
        "POST", "/portal/payments", {"invoice_ids": [open_autopay["id"]], "method_token": "tok_card_declined"}, 201
    )
    assert (
        declined["payment"]["status"] == "failed" and api("GET", f"/invoices/{open_autopay['id']}")["status"] == "open"
    )


def test_service_gates_hold_without_the_router(shop, desk):
    """ADR 0009: the service authorizes whoever calls it. A Front Desk principal built by hand is refused the
    Manager-only commands, and a Manager of another location gets 404, never 403."""
    from app.core.auth import Principal
    from app.core.errors import NotFound, PermissionDenied
    from app.modules.billing import bulk, catalogue
    from app.modules.billing import desk as commands

    nobody = Principal(kind="staff", tenant_id=shop.tenant.id, permissions={"billing.charge.read": "all"})
    elsewhere = Principal(
        kind="staff", tenant_id=shop.tenant.id, location_ids=frozenset({UUID(desk.west)}),
        permissions=dict.fromkeys(("billing.charge.void", "billing.invoice.void", "billing.payment.void",
                                   "billing.charge.update", "billing.invoice.update", "billing.autopay.run"), "all"),
    )  # fmt: skip
    with work(shop.tenant) as session:
        row = charge(session, shop)
        invoice = svc.create_invoice_for_charges(session, [charge(session, shop).id])
        payment = cash(session, shop, 100)
        guarded = [
            lambda p: commands.void_charge(session, p, row.id, {"reason": "x"}),
            lambda p: commands.update_charge(session, p, row.id, {"description": "x"}),
            lambda p: commands.void_invoice(session, p, invoice.id, {"reason": "x"}),
            lambda p: commands.update_invoice(session, p, invoice.id, {"comments": "x"}),
            lambda p: commands.void_payment(session, p, payment.id, {"reason": "x"}),
        ]
        for command in guarded:
            with pytest.raises(PermissionDenied):
                command(nobody)
            with pytest.raises(NotFound):
                command(elsewhere)
        for tenant_wide in (
            lambda: catalogue.create_coupon(session, nobody, {}),
            lambda: catalogue.put_settings(session, nobody, None, {}),
            lambda: catalogue.set_period_lock(session, nobody, None),
            lambda: methods.connect_provider_account(session, nobody, "fake"),
            lambda: bulk.create_bulk_action(
                session, nobody, {"action": "create_invoices", "location_id": shop.location_id}, None
            ),
            lambda: documents.receivables_ageing(session, nobody),
        ):
            with pytest.raises(PermissionDenied):
                tenant_wide()
        # another location's bulk scoping: test_a_bulk_action_is_location_scoped
