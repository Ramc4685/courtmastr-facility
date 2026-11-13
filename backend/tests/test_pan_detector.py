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
