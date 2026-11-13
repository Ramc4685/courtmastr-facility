"""Event forms (REG-15 to REG-24): the builder and its versions, the open window, stock caps, anonymous free
registration, the signed-in paid flow through secure checkout with a coupon, the wait list, staff edit, cancel,
export and summaries."""

import io
from datetime import timedelta

import pytest
from PIL import Image

from app.core import clock
from app.modules.programs import forms
from app.modules.programs.tests.test_checkout import keyed, member
from app.modules.programs.tests.test_sessions import people
from app.modules.scheduling.tests.helpers import API, facility, ok


def _png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (4, 2), (20, 90, 160)).save(out, format="PNG")
    return out.getvalue()


PNG = _png()
SHIRT = {"type": "question", "key": "shirt", "question_type": "radio", "text": "Shirt size", "required": True,
         "choices": [{"key": "s", "text": "Small"}, {"key": "m", "text": "Medium"}]}  # fmt: skip
NOTE = {"type": "question", "key": "note", "question_type": "text_box", "text": "Anything else?", "max_length": 20}


@pytest.fixture
def f(client, owner):
    return facility(client, owner)


def new_form(client, owner, f, items=(SHIRT, NOTE), publish=True, **fields) -> dict:
    form = ok(client.post(f"{API}/forms", headers=owner, json={"location_id": f.location, "name": "Open Day"} | fields))
    ok(client.put(f"{API}/forms/{form['id']}/draft", headers=owner, json={"items": list(items)}), 200)
    if publish:
        form = ok(client.post(f"{API}/forms/{form['id']}/publish", headers=owner), 200)
    return form


def submit(client, tenant, form_id: str, answers, **contact):
    body = {"contact_name": "Pat", "contact_email": "pat@example.com", "answers": answers} | contact
    return client.post(f"{API}/public/forms/{form_id}/submissions", headers={"X-Tenant-Slug": tenant.slug}, json=body)


def code(response) -> tuple[int, str]:
    return response.status_code, response.json().get("code")


def test_builder_validates_versions_and_publishes(client, owner, f):
    form = new_form(client, owner, f, publish=False)
    assert form["effective_state"] == "draft" and form["is_free"]
    url = f"{API}/forms/{form['id']}/draft"
    dup = client.put(url, headers=owner, json={"items": [SHIRT, SHIRT]})
    bad_dep = NOTE | {"depends_on": {"question_key": "shirt", "choice_key": "xl"}}
    assert code(dup)[0] == 422 and code(client.put(url, headers=owner, json={"items": [SHIRT, bad_dep]}))[0] == 422
    no_choices = SHIRT | {"choices": []}
    assert code(client.put(url, headers=owner, json={"items": [no_choices]}))[0] == 422
    text_choices = NOTE | {"choices": [{"key": "a", "text": "A"}]}
    assert code(client.put(url, headers=owner, json={"items": [text_choices]}))[0] == 422
    qty = {"type": "question", "key": "q", "question_type": "purchase_quantity", "text": "Tickets"}
    assert code(client.put(url, headers=owner, json={"items": [qty]}))[0] == 422

    published = ok(client.post(f"{API}/forms/{form['id']}/publish", headers=owner), 200)
    assert published["status"] == "open" and published["published"]["version_no"] == 1 and published["draft"] is None
    assert code(client.post(f"{API}/forms/{form['id']}/publish", headers=owner)) == (409, "draft-empty")
    edited = ok(client.put(url, headers=owner, json={"items": [SHIRT]}), 200)
    assert edited["draft"]["version_no"] == 2
    v2 = ok(client.post(f"{API}/forms/{form['id']}/publish", headers=owner), 200)
    assert v2["published"]["version_no"] == 2

    closed = ok(client.post(f"{API}/forms/{form['id']}/close", headers=owner), 200)
    assert closed["effective_state"] == "closed"
    assert code(client.post(f"{API}/forms/{form['id']}/close", headers=owner)) == (409, "form-state")
    assert ok(client.post(f"{API}/forms/{form['id']}/reopen", headers=owner), 200)["status"] == "open"
    listed = ok(client.get(f"{API}/forms?q=open&status=open", headers=owner), 200)["data"]
    assert [x["id"] for x in listed] == [form["id"]]


def test_window_on_the_location_clock_and_template_copy(client, owner, tenant, f):
    later = (clock.now() + timedelta(days=2)).replace(tzinfo=None, microsecond=0).isoformat()
    form = new_form(client, owner, f, opens_local=later, capacity=5, is_template=False)
    assert form["effective_state"] == "not_yet_open" and form["opens_local"].startswith(later[:16])
    refused = submit(client, tenant, form["id"], [{"item_key": "shirt", "choice_keys": ["s"]}])
    assert code(refused) == (409, "form-closed")
    bad = client.patch(f"{API}/forms/{form['id']}", headers=owner, json={"closes_local": "2020-01-01T10:00:00"})
    assert code(bad)[0] == 422
    span = client.patch(f"{API}/forms/{form['id']}", headers=owner,
                        json={"event_starts_on": "2031-05-02", "event_ends_on": "2031-05-01"})  # fmt: skip
    assert code(span)[0] == 422

    template = new_form(client, owner, f, publish=False, is_template=True, name="Template")
    ok(client.put(f"{API}/forms/{template['id']}/inventory", headers=owner,
                  json={"items": [{"item_key": "shirt.s", "limit_count": 3}]}), 200)  # fmt: skip
    assert code(client.post(f"{API}/forms/{template['id']}/publish", headers=owner)) == (409, "form-is-template")
    copy = ok(client.post(f"{API}/forms", headers=owner, json={"name": "Copy", "copy_from_form_id": template["id"]}))
    assert copy["copied_from_form_id"] == template["id"] and not copy["is_template"]
    assert [i["key"] for i in copy["draft"]["schema_doc"]["items"]] == ["shirt", "note"]
    caps = ok(client.get(f"{API}/forms/{copy['id']}/inventory", headers=owner), 200)
    assert caps[0]["item_key"] == "shirt.s" and caps[0]["limit_count"] == 3 and caps[0]["label"] == "Shirt size: Small"


def test_anonymous_free_registration_with_stock_and_dependencies(client, owner, tenant, f, mailbox):
    detail = {"type": "question", "key": "size_note", "question_type": "text_box", "text": "Why small?",
              "required": True, "depends_on": {"question_key": "shirt", "choice_key": "s"}}  # fmt: skip
    secret = {
        "type": "question",
        "key": "staff",
        "question_type": "text_box",
        "text": "Staff",
        "visibility": "staff_only",
    }
    topic = {"type": "topic", "key": "intro", "title": "Welcome", "body": "Bring water."}
    form = new_form(client, owner, f, items=[topic, SHIRT, detail, NOTE, secret])
    ok(client.put(f"{API}/forms/{form['id']}/inventory", headers=owner, json={"items": [
        {"item_key": "shirt.s", "limit_count": 1, "shows_count_publicly": True, "sold_out_memo": "No small left"},
    ]}), 200)  # fmt: skip
    public = ok(client.get(f"{API}/public/forms/{form['id']}", headers={"X-Tenant-Slug": tenant.slug}), 200)
    assert [i["key"] for i in public["items"]] == ["intro", "shirt", "size_note", "note"]
    assert public["items"][1]["choices"][0]["remaining"] == 1 and public["is_free"]

    missing = submit(client, tenant, form["id"], [])
    assert code(missing) == (422, "answer-required")
    needs = submit(client, tenant, form["id"], [{"item_key": "shirt", "choice_keys": ["s"]}])
    assert code(needs) == (422, "answer-required")
    hidden = submit(client, tenant, form["id"], [{"item_key": "staff", "text_value": "x"}])
    assert code(hidden)[0] == 422
    too_long = submit(client, tenant, form["id"], [{"item_key": "shirt", "choice_keys": ["m"]},
                                                   {"item_key": "note", "text_value": "x" * 21}])  # fmt: skip
    assert code(too_long)[0] == 422
    two = submit(client, tenant, form["id"], [{"item_key": "shirt", "choice_keys": ["s", "m"]}])
    assert code(two)[0] == 422

    first = ok(submit(client, tenant, form["id"], [{"item_key": "shirt", "choice_keys": ["s"]},
                                                  {"item_key": "size_note", "text_value": "Kid"}]))  # fmt: skip
    assert first["status"] == "confirmed" and first["total_minor"] == 0 and first["confirmation_no"] >= 1
    assert mailbox[-1].to == "pat@example.com" and "Open Day" in mailbox[-1].subject
    assert "Hello there" in mailbox[-1].body and "Pat" not in mailbox[-1].body  # no visitor text in mail
    sold = submit(client, tenant, form["id"], [{"item_key": "shirt", "choice_keys": ["s"]},
                                               {"item_key": "size_note", "text_value": "Kid"}])  # fmt: skip
    assert code(sold) == (409, "sold-out") and sold.json()["detail"] == "No small left"
    # the dependent question is skipped when its choice is not picked
    ok(submit(client, tenant, form["id"], [{"item_key": "shirt", "choice_keys": ["m"]}]))
    public = ok(client.get(f"{API}/public/forms/{form['id']}", headers={"X-Tenant-Slug": tenant.slug}), 200)
    assert public["items"][1]["choices"][0]["sold_out"]
    limit = client.put(f"{API}/forms/{form['id']}/inventory", headers=owner,
                       json={"items": [{"item_key": "shirt.s", "limit_count": 0}]})  # fmt: skip
    assert code(limit) == (409, "limit-below-sold")
    unknown = client.put(f"{API}/forms/{form['id']}/inventory", headers=owner,
                         json={"items": [{"item_key": "note", "limit_count": 3}]})  # fmt: skip
    assert code(unknown)[0] == 422
    kept = ok(client.put(f"{API}/forms/{form['id']}/inventory", headers=owner, json={"items": []}), 200)
    assert kept[0]["is_enabled"] is False  # a cap that sold stays, switched off


def test_capacity_wait_list_promote_and_cancel(client, owner, tenant, f):
    form = new_form(client, owner, f, capacity=1, has_waitlist=True, items=[NOTE])
    one = ok(submit(client, tenant, form["id"], []))
    two = ok(submit(client, tenant, form["id"], [], contact_name="Sam"))
    assert (one["status"], two["status"]) == ("confirmed", "waitlisted")
    assert ok(client.get(f"{API}/forms/{form['id']}", headers=owner), 200)["effective_state"] == "full_waitlist"
    subs = ok(client.get(f"{API}/form-submissions?form_id={form['id']}&sort=confirmation_no", headers=owner), 200)
    first, waiting = subs["data"]
    full = client.post(f"{API}/form-submissions/{waiting['id']}/promote", headers=owner)
    assert code(full) == (409, "form-full")

    cancelled = ok(client.post(f"{API}/form-submissions/{first['id']}/cancel", headers=owner, json={}), 200)
    assert cancelled["status"] == "cancelled" and cancelled["cancelled_at"]
    again = client.post(f"{API}/form-submissions/{first['id']}/cancel", headers=owner, json={})
    assert code(again) == (409, "already-cancelled")
    promoted = ok(client.post(f"{API}/form-submissions/{waiting['id']}/promote", headers=owner), 200)
    assert promoted["status"] == "confirmed"
    assert code(client.post(f"{API}/form-submissions/{waiting['id']}/promote", headers=owner)) == (
        409,
        "not-waitlisted",
    )

    ok(client.patch(f"{API}/forms/{form['id']}", headers=owner, json={"has_waitlist": False}), 200)
    assert code(submit(client, tenant, form["id"], [])) == (409, "form-closed")


def test_portal_paid_registration_pays_now_with_a_coupon(client, owner, tenant, f, mailbox):
    priced = {"type": "question", "key": "tickets", "question_type": "purchase_quantity", "text": "Tickets",
              "unit_price_minor": 1000, "max_quantity": 4}  # fmt: skip
    meal = {"type": "question", "key": "meal", "question_type": "drop_down", "text": "Meal",
            "choices": [{"key": "veg", "text": "Veg", "price_minor": 500}, {"key": "none", "text": "None"}]}  # fmt: skip
    form = new_form(client, owner, f, items=[priced, meal], allows_coupons=True)
    assert not form["is_free"]
    ok(client.put(f"{API}/forms/{form['id']}/inventory", headers=owner,
                  json={"items": [{"item_key": "tickets", "limit_count": 3}]}), 200)  # fmt: skip
    signed_out = submit(client, tenant, form["id"], [{"item_key": "tickets", "quantity": 1}])
    assert code(signed_out) == (409, "sign-in-required")
    ok(client.post(f"{API}/coupons", headers=owner, json={
        "name": "Ten", "code": "TEN", "starts_at": "2020-01-01T00:00:00Z", "discount_pct": "10", "is_portal_enabled": True,
    }))  # fmt: skip
    person, portal = member(client, tenant, owner, f, mailbox)
    body = {"form_id": form["id"], "registrant_client_id": person["id"], "contact_name": "Pat",
            "contact_email": "pat@example.com", "answers": [{"item_key": "tickets", "quantity": 2},
                                                            {"item_key": "meal", "choice_keys": ["veg"]}]}  # fmt: skip
    url = f"{API}/portal/form-submissions"
    declined = client.post(url, headers=keyed(portal), json=body | {"method_token": "tok_card_declined"})
    assert declined.status_code in (402, 409, 422)
    caps = ok(client.get(f"{API}/forms/{form['id']}/inventory", headers=owner), 200)
    assert caps[0]["sold_count"] == 0  # the failed payment rolled the stock back
    too_many = client.post(url, headers=keyed(portal), json=body | {"answers": [{"item_key": "tickets", "quantity": 4}],
                                                                    "method_token": "tok_card_ok"})  # fmt: skip
    assert code(too_many) == (409, "sold-out")
    paid = ok(
        client.post(url, headers=keyed(portal), json=body | {"method_token": "tok_card_ok", "coupon_code": "TEN"})
    )
    assert paid["status"] == "confirmed" and paid["total_minor"] == 2500
    invoices = ok(client.get(f"{API}/invoices?bill_to_client_id={person['id']}", headers=owner), 200)["data"]
    assert len(invoices) == 1 and invoices[0]["balance_minor"] == 0
    stranger = people(client, owner, f, 1)[0]
    assert client.post(url, headers=keyed(portal), json=body | {"registrant_client_id": stranger}).status_code == 404
    assert client.post(url, headers=keyed(owner), json=body).status_code == 404  # staff are not registrants

    ok(client.patch(f"{API}/forms/{form['id']}", headers=owner, json={"allows_coupons": False}), 200)
    no_coupon = client.post(
        url, headers=keyed(portal), json=body | {"coupon_code": "TEN", "method_token": "tok_card_ok"}
    )
    assert code(no_coupon) == (422, "coupon-not-allowed")

    sub = ok(client.get(f"{API}/form-submissions?form_id={form['id']}", headers=owner), 200)["data"][0]
    reversed_ = ok(client.post(f"{API}/form-submissions/{sub['id']}/cancel", headers=owner,
                               json={"reverse_charges": True, "reason": "Refund"}), 200)  # fmt: skip
    assert reversed_["status"] == "cancelled"
    assert ok(client.get(f"{API}/forms/{form['id']}/inventory", headers=owner), 200)[0]["sold_count"] == 0


def test_staff_edit_export_and_summaries(client, owner, tenant, f):
    form = new_form(client, owner, f)
    ok(submit(client, tenant, form["id"], [{"item_key": "shirt", "choice_keys": ["s"]},
                                           {"item_key": "note", "text_value": "Hi"}], contact_name="=cmd()"))  # fmt: skip
    ok(submit(client, tenant, form["id"], [{"item_key": "shirt", "choice_keys": ["m"]}], contact_name="Sam"))
    found = ok(client.get(f"{API}/form-submissions?q=sam", headers=owner), 200)["data"]
    assert [s["contact_name"] for s in found] == ["Sam"]
    sub = found[0]
    (person,) = people(client, owner, f, 1)
    edited = ok(client.patch(f"{API}/form-submissions/{sub['id']}", headers=owner, json={
        "contact_phone": "555-0100", "registrant_client_id": person, "text_answers": {"note": "Late"},
    }), 200)  # fmt: skip
    assert edited["registrant_client_id"] == person and edited["last_edited_at"]
    assert {a["item_key"]: a["text_value"] for a in edited["answers"]}["note"] == "Late"
    priced = client.patch(f"{API}/form-submissions/{sub['id']}", headers=owner, json={"text_answers": {"shirt": "x"}})
    assert code(priced)[0] == 422
    assert ok(client.get(f"{API}/form-submissions/{sub['id']}", headers=owner), 200)["answers"][0]["label"]

    csv = client.post(f"{API}/forms/{form['id']}/exports", headers=keyed(owner))
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv")
    text = csv.text.splitlines()
    assert text[0].endswith("Shirt size,Anything else?") and "'=cmd()" in text[1]

    def summary(key):
        return ok(client.get(f"{API}/forms/{form['id']}/summaries/{key}", headers=owner), 200)["rows"]

    assert {(r["group"], r["label"]): r["count"] for r in summary("registrant")}[("status", "confirmed")] == 2
    assert {r["label"]: r["count"] for r in summary("answer")}["Shirt size: Small"] == 1
    demo = {(r["group"], r["label"]) for r in summary("demographic")}
    assert ("gender", "unknown") in demo
    assert summary("revenue")[-1]["label"] == "Total"
    assert code(client.get(f"{API}/forms/{form['id']}/summaries/nope", headers=owner))[0] == 422


def test_header_image_is_public_only_once_published(client, owner, tenant, f):
    form = new_form(client, owner, f, publish=False)
    put = client.put(f"{API}/forms/{form['id']}/header-image", headers=owner | {"Content-Type": "image/png"},
                     content=PNG)  # fmt: skip
    assert ok(put, 200)["has_header_image"]
    public = {"X-Tenant-Slug": tenant.slug}
    assert client.get(f"{API}/public/forms/{form['id']}/header-image", headers=public).status_code == 404
    ok(client.post(f"{API}/forms/{form['id']}/publish", headers=owner), 200)
    image = client.get(f"{API}/public/forms/{form['id']}/header-image", headers=public)
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    wrong = client.put(f"{API}/forms/{form['id']}/header-image", headers=owner | {"Content-Type": "image/png"},
                       content=b"not an image")  # fmt: skip
    assert wrong.status_code == 422
    assert client.delete(f"{API}/forms/{form['id']}/header-image", headers=owner).status_code == 204
    assert client.delete(f"{API}/forms/{form['id']}/header-image", headers=owner).status_code == 204
    assert client.get(f"{API}/public/forms/{form['id']}/header-image", headers=public).status_code == 404


def test_effective_state_rules():
    class Row:
        status, opens_at, auto_close_at, capacity, submitted_count, has_waitlist = "open", None, None, None, 0, False

    now, row = clock.now(), Row()
    assert forms.effective_state(row, now) == "open"
    row.auto_close_at = now - timedelta(minutes=1)
    assert forms.effective_state(row, now) == "closed"
    row.auto_close_at, row.capacity, row.submitted_count = None, 1, 1
    assert forms.effective_state(row, now) == "full"
    assert forms.is_free({"items": [SHIRT]}) and not forms.is_free(
        {"items": [SHIRT | {"choices": [{"key": "a", "text": "A", "price_minor": 1}]}]}
    )
