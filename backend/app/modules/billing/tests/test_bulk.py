"""BIL-02 bulk actions: the key is required, a run is checked against its preview, dry runs check what the run
would do, jobs run as the person who started them, clients are checked against the caller's reach, and the
chunked job, the internal-error path and a successful email are covered."""

from uuid import UUID, uuid4

from app.core import idempotency
from app.modules.billing import bulk
from app.modules.billing.tests.test_billing import API, work
from app.modules.billing.tests.test_surface import _bulk, item
from conftest import new_client


def _catalog_item(api, shop, fee=1000) -> dict:
    body = {"location_id": str(shop.location_id), "kind": "one_off", "description": "Locker", "fee_minor": fee,
            "revenue_category_id": str(shop.category_id)}  # fmt: skip
    return api("POST", "/catalog-items", body, 201)


def test_the_idempotency_key_is_required(client, shop):
    body = {"action": "create_invoices", "location_id": str(shop.location_id), "is_dry_run": True}
    refused = client.post(f"{API}/billing-bulk-actions", headers=shop.owner, json=body)
    assert refused.status_code == 422


def test_a_request_that_loses_the_key_race_is_told_to_retry(client, shop, monkeypatch):
    body = {"action": "create_invoices", "location_id": str(shop.location_id), "is_dry_run": True}
    headers = shop.owner | {"Idempotency-Key": f"race-{uuid4().hex}"}
    assert client.post(f"{API}/billing-bulk-actions", headers=headers, json=body).status_code == 202
    monkeypatch.setattr(idempotency, "begin", lambda *_: None)  # the HTTP claim expired (24 h) or was bypassed
    monkeypatch.setattr(bulk, "_by_key", lambda *_: None)  # and the twin committed after our replay lookup
    lost = client.post(f"{API}/billing-bulk-actions", headers=headers, json=body)
    assert (lost.status_code, lost.json()["code"]) == (409, "request-in-progress")


def test_a_run_is_refused_when_its_preview_is_stale(api, shop):
    charge_id = api("POST", "/charges", item(shop, 1000), 201)["id"]
    body = {"action": "create_invoices", "location_id": str(shop.location_id), "charge_ids": [charge_id]}
    preview, rows = _bulk(api, body | {"is_dry_run": True})
    assert rows[0]["amount_minor"] == 1083
    api("PATCH", f"/charges/{charge_id}", {"unit_price_minor": 1200, "reason": "Price went up"})
    stale = api("POST", "/billing-bulk-actions", body | {"preview_id": preview["id"]}, 409)
    assert stale["code"] == "bulk-preview-stale"
    new_id = api("GET", f"/charges?client_id={shop.client_id}")["data"][0]["id"]
    body |= {"charge_ids": [new_id]}
    fresh, _ = _bulk(api, body | {"is_dry_run": True})
    done, _ = _bulk(api, body | {"preview_id": fresh["id"]})
    assert done["status"] == "completed"
    wrong = api("POST", "/billing-bulk-actions", body | {"preview_id": done["id"]}, 422)  # not a dry run
    assert wrong["errors"][0]["pointer"] == "/preview_id"


def test_dry_runs_of_email_and_render_check_what_the_run_would_do(api, shop):
    invoice = api("POST", "/invoices", {"charge_ids": [api("POST", "/charges", item(shop, 700), 201)["id"]]}, 201)
    body = {"location_id": str(shop.location_id), "invoice_ids": [invoice["id"]], "is_dry_run": True}
    done, rows = _bulk(api, body | {"action": "email_invoices"})
    assert (done["status"], rows[0]["error_code"]) == ("completed_with_errors", "no-email-address")
    done, rows = _bulk(api, body | {"action": "render_invoices"})
    assert done["status"] == "completed" and rows[0]["result_id"] is None


def test_a_successful_bulk_email(client, api, shop, mailbox):
    payer = new_client(client, shop.owner, shop.location_id, primary_email="payer@example.com")["id"]
    invoice = api("POST", "/invoices", {"charge_ids": [api("POST", "/charges", item(shop, 700, client_id=payer),
                                                           201)["id"]]}, 201)  # fmt: skip
    done, rows = _bulk(api, {"action": "email_invoices", "location_id": str(shop.location_id),
                             "invoice_ids": [invoice["id"]]})  # fmt: skip
    assert (done["status"], rows[0]["result_type"]) == ("completed", "billing_document_delivery")
    assert any("payer@example.com" in str(message) for message in mailbox)


def test_add_item_skips_unknown_clients_and_clients_outside_the_callers_locations(client, api, shop, desk):
    catalog_item = _catalog_item(api, shop)
    west_client = new_client(client, shop.owner, desk.west)["id"]
    body = {"action": "add_catalog_item", "location_id": str(shop.location_id),
            "client_ids": [str(shop.client_id), west_client, str(uuid4())],
            "params": {"catalog_item_id": catalog_item["id"]}}  # fmt: skip
    done, rows = _bulk(api, body, headers=desk.front)
    by_subject = {row["subject_id"]: (row["status"], row["error_code"]) for row in rows}
    assert by_subject[str(shop.client_id)] == ("done", None)
    assert by_subject[west_client] == ("skipped", "client-not-found")
    assert sorted(by_subject.values()).count(("skipped", "client-not-found")) == 2
    assert done["done_count"] == 1


def test_a_job_spans_several_chunks_and_runs_as_its_requester(client, api, shop, monkeypatch):
    monkeypatch.setattr(bulk, "IN_REQUEST_LIMIT", 1)
    monkeypatch.setattr(bulk, "CHUNK_ITEMS", 1)
    monkeypatch.setattr(bulk.run_bulk_action, "send", lambda *args: None)
    ids = [api("POST", "/charges", item(shop, price), 201)["id"] for price in (100, 200, 300)]
    made = api("POST", "/billing-bulk-actions", {"action": "reverse_charges", "location_id": str(shop.location_id),
                                                 "charge_ids": ids, "params": {"reason": "Batch"}}, 202)  # fmt: skip
    chunks = 0
    while True:
        with work(shop.tenant) as session:
            chunks += 1
            more = bulk.run_job_chunk(session, made["id"])
            if chunks == 1:
                assert session.info["actor"].kind == "staff"  # attributed to the person, not the system
        if not more:
            break
        assert chunks < 10
    assert chunks == 3
    done = api("GET", f"/billing-bulk-actions/{made['id']}")
    assert (done["status"], done["done_count"]) == ("completed", 3)


def test_an_unexpected_error_fails_only_its_item(api, shop, monkeypatch):
    ids = [api("POST", "/charges", item(shop, price), 201)["id"] for price in (100, 200)]
    real = bulk.service.reverse

    def flaky(session, charge_id, **kw):
        if str(charge_id) == ids[0]:
            raise RuntimeError("disk on fire")
        return real(session, charge_id, **kw)

    monkeypatch.setattr(bulk.service, "reverse", flaky)
    done, rows = _bulk(api, {"action": "reverse_charges", "location_id": str(shop.location_id), "charge_ids": ids,
                             "params": {"reason": "x"}})  # fmt: skip
    by_subject = {row["subject_id"]: (row["status"], row["error_code"]) for row in rows}
    assert by_subject == {ids[0]: ("failed", "internal-error"), ids[1]: ("done", None)}
    assert done["status"] == "completed_with_errors"


def test_a_job_stops_when_its_requester_may_no_longer_act(api, shop, monkeypatch):
    monkeypatch.setattr(bulk, "IN_REQUEST_LIMIT", 1)
    monkeypatch.setattr(bulk.run_bulk_action, "send", lambda *args: None)
    ids = [api("POST", "/charges", item(shop, price), 201)["id"] for price in (100, 200)]
    made = api("POST", "/billing-bulk-actions", {"action": "reverse_charges", "location_id": str(shop.location_id),
                                                 "charge_ids": ids, "params": {"reason": "x"}}, 202)  # fmt: skip
    monkeypatch.setattr(bulk.platform.staff, "principal_for", lambda *_: None)
    with work(shop.tenant) as session:
        assert bulk.run_job_chunk(session, made["id"]) is False
        row = session.get(bulk.BillingBulkAction, UUID(made["id"]))
        assert (row.status, row.failed_count) == ("completed_with_errors", 2)
