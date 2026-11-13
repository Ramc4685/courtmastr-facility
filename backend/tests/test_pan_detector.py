"""security-baseline section 3, free-text leakage: a card number typed into a stored free-text field is refused
with `card-data-not-allowed`, at the one shared point every request schema inherits (`app.core.schemas.In`)."""

import time

import pytest
from pydantic import ValidationError

from app.core.pan import contains_card_number
from app.core.schemas import In
from conftest import new_client

API = "/api/v1"

CARDS = [
    "4111111111111111", "4111 1111 1111 1111", "4111-1111-1111-1111", "5555555555554444", "2223003122003222",
    "378282246310005", "3782 822463 10005", "6011111111111117", "4000056655665556", "6200000000000005",
    "card is 4242424242424242, exp 12/29",
    # bypasses: inside a longer run, other separators, doubled separators, split across lines
    "41111111111111111111", "ref 9900004111111111111111", "ref 1234 4111 1111 1111 1111", "4111.1111.1111.1111",
    "4111/1111/1111/1111", "4111_1111_1111_1111", "4111  1111  1111  1111", "4111 1111\n1111 1111",
    "4111 - 1111 - 1111 - 1111", "4111 1111 1111 1111 003",  # 19-digit Visa, 4-4-4-4-3
    "6011 0009 9013 9424", "3530111333300000",  # Discover, JCB
    # whole groups of any size (at least 3 digits each), repeated and mixed separators
    "41111111 11111111", "4111 1111 11111111", "4111-1111--1111 1111", "4111--1111--1111--1111",
    "4111 / 1111 . 1111_1111", "3782 8224 6310 005", "411 111 111 111 1111",
    # en and em dashes, commas, and full-width digits (NFKC)
    "4111–1111–1111–1111", "4111 — 1111 — 1111 — 1111", "4111,1111,1111,1111",
    "４１１１ １１１１ １１１１ １１１１",
]  # fmt: skip
NOT_CARDS = [
    "217-555-0123", "(217) 555-0123", "+1 217 555 0123", "+44 20 7946 0958", "2175550123",
    "2026-11-13", "13/11/2026", "2026-11-13 2026-12-01", "Order 2026-000123456", "ORD-20261113-0042",
    "4111111111111112",  # Luhn fails
    "1234567890123",  # no card-network prefix
    "invoice 1000234567890 paid",
    "tracking 9400111899223817364821", "tracking 9400 1118 9922 3817 3648 21",  # USPS-style, 22 digits
    "IBAN DE89 3704 0044 0532 0130 00", "GB29 NWBK 6016 1331 9268 19",
    "scores 21 19 21 17 21 15", "ids 1000023 1000024 1000025",
    "scores 51 48 55 60 52 47 63 58", "51 48 55 60 52 47 63 58 51 48 55 60",  # groups under 3 digits never join
    "41 11 11 11 11 11 11 11", "4111 11 1111 1111 11",
    "4000000000006", "barcode 4006381333931",  # EAN-13 barcodes; 13-digit Visa is not detected
    "1234 5678 9012 3456 7890 1234",  # grouped, but no window of whole groups passes prefix, length and Luhn
    "3782822463100052",  # Luhn-valid, Amex prefix, but 16 digits: Amex is 15
]  # fmt: skip


@pytest.mark.parametrize("value", CARDS)
def test_detects_card_numbers(value):
    assert contains_card_number(value)


@pytest.mark.parametrize("value", NOT_CARDS)
def test_does_not_flag_phone_numbers_order_ids_or_dates(value):
    assert not contains_card_number(value)


class _Sample(In):
    note: str | None = None
    text_answers: list[dict[str, str]] = []
    sku: str | None = None


class _Nested(In):
    items: list[_Sample] = []


def _refused(model, **kwargs) -> list[tuple]:
    with pytest.raises(ValidationError) as refused:
        model(**kwargs)
    return [(e["type"], e["loc"]) for e in refused.value.errors()]


def test_free_text_fields_refuse_card_numbers_at_any_depth_with_the_full_path():
    assert _refused(_Sample, note="pay with 4111 1111 1111 1111") == [("card-data-not-allowed", ("note",))]
    assert _refused(_Sample, text_answers=[{"q1": "4111111111111111"}]) == [
        ("card-data-not-allowed", ("text_answers",))
    ]
    assert _refused(_Nested, items=[{"note": "ok"}, {"note": "5555555555554444"}]) == [
        ("card-data-not-allowed", ("items", 1, "note"))
    ]


@pytest.mark.parametrize("field", ["description", "additional_description", "title"])
def test_descriptions_and_titles_are_free_text(field):
    model = type("_Titled", (In,), {"__annotations__": {field: str}})
    assert _refused(model, **{field: "4111 1111 1111 1111"}) == [("card-data-not-allowed", (field,))]
    assert getattr(model(**{field: "Court 4 rental, 2 hours"}), field)


def test_non_free_text_fields_are_not_scanned():
    assert _Sample(sku="4111111111111111", note="call 217-555-0123").sku  # codes and barcodes are not free text


@pytest.mark.parametrize(
    "field",
    ["statement_email_body", "invoice_description", "online_description", "internal_description", "public_title",
     "confirmation_message", "interest", "a_field_nobody_classified_yet"],
)  # fmt: skip
def test_every_string_field_is_scanned_unless_allow_listed(field):
    model = type("_Any", (In,), {"__annotations__": {field: str}})
    assert _refused(model, **{field: "4111 1111 1111 1111"}) == [("card-data-not-allowed", (field,))]


def test_staff_typed_text_under_reference_like_names_is_scanned():
    from app.modules.billing.schemas import MarkPaidRequest
    from app.modules.clients.schemas import ClientCreate
    from app.modules.engagement.schemas import LocationContactUpdate
    from app.modules.integrations.schemas import ExternalConnectionUpdate
    from app.modules.platform.schemas import TenantUpdate

    card = "4111 1111 1111 1111"
    cases = [
        (MarkPaidRequest, {"external_reference": f"cheque, card {card}"}, ("external_reference",)),
        (LocationContactUpdate, {"role": card}, ("role",)),
        (ClientCreate, {"first_name": "Pat", "last_name": "Lee", "postal_code": card}, ("postal_code",)),
        (TenantUpdate, {"settings": {"receipt_note": card}}, ("settings",)),
        (ExternalConnectionUpdate, {"settings": {"default_income_account": card}}, ("settings",)),
    ]
    for model, body, loc in cases:
        assert ("card-data-not-allowed", loc) in _refused(model, **body), model.__name__
    assert MarkPaidRequest(external_reference="Cheque 004512, bank ref 20261113-88").external_reference


@pytest.mark.parametrize("field", ["value", "card_payload", "member_number", "phone", "external_ref", "token"])
def test_allow_listed_fields_keep_long_digit_runs(field):
    model = type("_Code", (In,), {"__annotations__": {field: str}})
    assert getattr(model(**{field: "4111111111111111"}), field)  # a fob or member card is a digit run by design


def test_html_fields_are_scanned_with_their_tags_removed():
    model = type("_Html", (In,), {"__annotations__": {"body_html": str}})
    assert _refused(model, body_html="<p>4111<b>1111</b>1111 <i>1111</i></p>") == [
        ("card-data-not-allowed", ("body_html",))
    ]
    assert model(body_html="<p>Court <b>4</b> at 6pm, call 217-555-0123</p>").body_html


def test_html_tag_stripping_is_linear_and_still_refuses_unclosed_and_nested_tags():
    model = type("_Html", (In,), {"__annotations__": {"body_html": str}})
    started = time.perf_counter()
    model(body_html="<" * 200_000)
    assert time.perf_counter() - started < 0.5
    for hidden in (
        "<<b>4111</b>> <i><u>1111</u></i> 1111 1111",
        "<p 4111 1111 1111 1111",
        "4111<br/>1111<br>1111<hr>1111",
        "4111&nbsp;1111&#32;1111&nbsp;1111",
    ):
        assert _refused(model, body_html=hidden) == [("card-data-not-allowed", ("body_html",))], hidden


def test_a_card_at_the_end_of_the_longest_html_body_is_refused():
    from app.modules.documents.schemas import DocumentTemplateDraft

    limit = DocumentTemplateDraft.model_fields["body_html"].metadata[0].max_length
    card = "4111 1111 1111 1111"
    body = "<p>" + "x" * (limit - len(card) - 7) + "</p>" + card
    assert len(body) == limit
    started = time.perf_counter()
    with pytest.raises(ValidationError, match="card-data-not-allowed|Card numbers"):
        DocumentTemplateDraft(body_html=body, acceptance_text="I agree")
    assert time.perf_counter() - started < 1.0


def test_every_html_request_field_has_a_maximum_the_scan_covers():
    """The scan must see the whole accepted value, so every *_html request field is capped and the cap is within
    what contains_card_number reads."""
    from app.core.pan import MAX_SCAN
    from app.main import app  # noqa: F401  (imports every module's schemas)

    def subclasses(cls):
        for sub in cls.__subclasses__():
            yield sub
            yield from subclasses(sub)

    html = [(c, n, f) for c in subclasses(In) if c.__module__.startswith("app.") for n, f in c.model_fields.items()
            if n.endswith("_html")]  # fmt: skip
    assert html
    for cls, name, field in html:
        caps = [m.max_length for m in field.metadata if getattr(m, "max_length", None)]
        assert caps and caps[0] <= MAX_SCAN, f"{cls.__name__}.{name}"


def _request_string_fields() -> set[str]:
    """Names of string properties reachable from every JSON request body in the OpenAPI document."""
    from app.main import app

    doc = app.openapi()
    schemas = doc["components"]["schemas"]
    plain = {"uuid", "date", "date-time", "email", "uri", "time", "duration", "binary"}

    def resolve(node):
        while "$ref" in node:
            node = schemas[node["$ref"].rsplit("/", 1)[-1]]
        return node

    def stringy(node) -> bool:
        node = resolve(node)
        if any(k in node for k in ("anyOf", "oneOf", "allOf")):
            return any(stringy(n) for k in ("anyOf", "oneOf", "allOf") for n in node.get(k, []))
        if node.get("type") == "array":
            return stringy(node.get("items", {}))
        if node.get("type") == "object" and isinstance(node.get("additionalProperties"), dict):
            return stringy(node["additionalProperties"])
        return node.get("type") == "string" and not {"enum", "const"} & node.keys() and node.get("format") not in plain

    found: set[str] = set()
    seen: set[str] = set()

    def walk(node) -> None:
        if "$ref" in node:
            name = node["$ref"].rsplit("/", 1)[-1]
            if name in seen:
                return
            seen.add(name)
            node = schemas[name]
        for key in ("anyOf", "oneOf", "allOf"):
            for sub in node.get(key, []):
                walk(sub)
        if node.get("type") == "array":
            walk(node.get("items", {}))
        for prop, sub in node.get("properties", {}).items():
            if stringy(sub):
                found.add(prop)
            walk(sub)

    for operations in doc["paths"].values():
        for operation in operations.values():
            body = operation.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
            if body:
                walk(body)
    return found


def test_no_response_model_runs_the_request_card_scan():
    """A stored value must always be readable: no Out model (or any model a route answers with, at any depth)
    may inherit the In validator, so an `Out(In)` class cannot turn a stored footer into a 500."""
    from fastapi.routing import APIRoute
    from pydantic import BaseModel

    from app.core.schemas import Out
    from app.main import app

    def subclasses(cls):
        for sub in cls.__subclasses__():
            yield sub
            yield from subclasses(sub)

    def models(tp, seen):
        if isinstance(tp, type) and issubclass(tp, BaseModel):
            if tp not in seen:
                seen.add(tp)
                for field in tp.model_fields.values():
                    models(field.annotation, seen)
        for arg in getattr(tp, "__args__", ()) or ():
            models(arg, seen)
        return seen

    answered: set = set(c for c in subclasses(Out) if c.__module__.startswith("app."))
    for route in app.routes:
        if isinstance(route, APIRoute) and route.response_model is not None:
            models(route.response_model, answered)
    scanning = sorted(m.__qualname__ for m in answered if issubclass(m, In))
    assert scanning == []


def test_every_request_string_field_is_classified():
    """A new string field on a request body must be put in FREE_TEXT_FIELDS (scanned) or NOT_FREE_TEXT (with the
    reason, grouped as there). Until then the runtime scans it anyway."""
    from app.core.schemas import FREE_TEXT_FIELDS, NOT_FREE_TEXT

    assert not FREE_TEXT_FIELDS & NOT_FREE_TEXT
    assert sorted(_request_string_fields() - FREE_TEXT_FIELDS - NOT_FREE_TEXT) == []


def test_api_refuses_a_note_with_a_card_number(client, owner):
    location = client.post(f"{API}/locations", headers=owner, json={"name": "Main", "time_zone": "America/Chicago",
                                                                    "country_code": "US"}).json()  # fmt: skip
    person = new_client(client, owner, location["id"])
    url = f"{API}/clients/{person['id']}/notes"
    refused = client.post(
        url, headers=owner, json={"kind": "call", "subject_text": "Call", "body": "Card 4111 1111 1111 1111 exp 12/29"}
    )
    assert refused.status_code == 422 and refused.json()["code"] == "card-data-not-allowed"
    assert refused.json()["errors"][0]["pointer"] == "/body"
    assert "4111" not in refused.text  # the problem body never echoes the number
    kept = client.post(
        url, headers=owner, json={"kind": "call", "subject_text": "Call", "body": "Call back on 217-555-0123"}
    )
    assert kept.status_code == 201, kept.text


@pytest.mark.parametrize(
    "hostile", ["1 " * 500_000, "1-" * 500_000, "4" * 1_000_000, "4111 " * 200_000, "411 -- " * 100_000]
)
def test_detector_is_linear_on_hostile_input(hostile):
    started = time.perf_counter()
    contains_card_number(hostile)
    assert time.perf_counter() - started < 1.0
