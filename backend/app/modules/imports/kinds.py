"""The four import types: our columns, how a row parses, its natural key, and how it is applied through the
owning context's service (so every rule, audit row, event and plan limit applies).

`parse` returns (data, errors); an error is (field key, code, plain words). `apply` runs inside the caller's
savepoint and returns (entity_type, entity_id, created). Column names are ours (clean-room)."""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.errors import ValidationFailed
from app.modules import billing, clients, engagement, memberships, pos
from app.modules.imports import csvio
from app.modules.imports.csvio import CellError, Field
from app.modules.imports.models import EntityType, ImportKind

Errors = list[tuple[str, str, str]]
_PHONE = re.compile(r"^\+[1-9][0-9]{6,14}$")
_RELATIONS = ("child", "spouse", "parent", "guardian", "ward", "sibling", "other")


@dataclass
class Context:
    location_id: UUID
    date_format: str
    today: date  # at the job's location (overview 3.7)
    job_id: UUID


@dataclass
class Kind:
    key: str
    label: str
    entity: str
    fields: list[Field]
    guide: list[str]
    parse: Callable[[dict[str, str], Context], tuple[dict, Errors]]
    natural_key: Callable[[dict], str]
    apply: Callable[[Session, dict, Context], tuple[str, UUID, bool]]
    pointers: dict[str, str] = field(default_factory=dict)  # service error pointer -> our field
    limit_key: str | None = None  # plan limit a created row counts against
    once: bool = False  # True: a row already created by an earlier job is skipped (no updates for this type)


def _cells(cells: dict[str, str], errors: Errors, parsers: dict[str, Callable[[str], object]]) -> dict:
    out = {}
    for key, parser in parsers.items():
        try:
            out[key] = parser(cells.get(key, ""))
        except CellError as error:
            errors.append((key, error.code, error.detail))
            out[key] = None
    return out


def _required(cells: dict[str, str], errors: Errors, fields: list[Field]) -> None:
    for f in fields:
        if f.required and not cells.get(f.key):
            errors.append((f.key, "required", f"{f.label} is required."))


def _phone(value: str) -> str | None:
    if not value:
        return None
    compact = re.sub(r"[\s().-]", "", value)
    if not _PHONE.match(compact):
        raise CellError("invalid-phone", "Write phone numbers with the country code, such as +13095550101.")
    return compact


def _country(value: str) -> str | None:
    if value and not re.match(r"^[A-Za-z]{2}$", value):
        raise CellError("invalid-country", "Use the two-letter country code, such as US.")
    return value.upper() or None


def _client_ref(session: Session, data: dict) -> UUID:
    """The client a membership or balance row names: by member number, else by a single primary email."""
    if data.get("client_member_number"):
        found = clients.service.find_by_member_number(session, data["client_member_number"])
        if found is None:
            raise ValidationFailed("No client has this member number.", pointer="/client_member_number",
                                   code="unknown-client")  # fmt: skip
        return found.id
    matches = clients.service.find_by_primary_email(session, data["client_email"])
    if len(matches) != 1:
        problem = "No client has this email." if not matches else "Two clients have this email; use the member number."
        raise ValidationFailed(problem, pointer="/client_email", code="unknown-client")
    return matches[0].id


def _ref_fields() -> list[Field]:
    return [
        Field("client_member_number", "Client member number", False, "Member number of an existing client.", "M-1001"),
        Field("client_email", "Client email", False, "Used when there is no member number.", "sam@example.com"),
    ]


def _check_ref(cells: dict[str, str], errors: Errors) -> None:
    if not cells.get("client_member_number") and not cells.get("client_email"):
        errors.append(("client_member_number", "required", "Give the client's member number or email."))


# --- clients and households --------------------------------------------------------------------------------------

CLIENT_FIELDS = [
    Field("member_number", "Member number", False, "Matches an existing client to update.", "M-1001"),
    Field("first_name", "First name", True, "", "Sam"),
    Field("last_name", "Last name", True, "", "Rivera"),
    Field("preferred_name", "Preferred name", False, "", "Sammy"),
    Field("email", "Email", False, "Primary email.", "sam@example.com"),
    Field("mobile_phone", "Mobile phone", False, "With the country code.", "+13095550101"),
    Field("home_phone", "Home phone", False, "With the country code.", ""),
    Field("birth_date", "Birth date", False, "In the date format you choose.", "2012-04-30"),
    Field("gender", "Gender", False, "female, male, non_binary or undisclosed.", ""),
    Field("address_line1", "Address line 1", False, "", "12 Main St"),
    Field("address_line2", "Address line 2", False, "", ""),
    Field("city", "City", False, "", "Normal"),
    Field("region", "State or region", False, "", "IL"),
    Field("postal_code", "Postal code", False, "", "61761"),
    Field("country_code", "Country code", False, "Two letters, such as US.", "US"),
    Field("household_ref", "Household", False, "Any label shared by the people of one household.", "RIVERA"),
    Field("household_head", "Household head", False, "yes for the one head of each household.", "yes"),
    Field("relationship_to_head", "Relationship to head", False,
          "For other members: child, spouse, parent, guardian, ward, sibling or other.", ""),
    Field("email_marketing", "Email marketing", False, "yes if the person agreed to marketing email.", "no"),
    Field("sms_marketing", "Text marketing", False, "yes if the person agreed to marketing texts.", "no"),
]  # fmt: skip
_CLIENT_POINTERS = {
    "/primary_email": "email", "/emails": "email", "/member_number": "member_number", "/first_name": "first_name",
    "/last_name": "last_name", "/phone_mobile": "mobile_phone", "/phone_home": "home_phone",
    "/birth_on": "birth_date", "/country_code": "country_code", "/relationship_type": "relationship_to_head",
}  # fmt: skip


def _parse_client(cells: dict[str, str], ctx: Context) -> tuple[dict, Errors]:
    errors: Errors = []
    _required(cells, errors, CLIENT_FIELDS)
    text = csvio.text
    data = _cells(cells, errors, {
        "member_number": lambda v: text(v, 40), "first_name": text, "last_name": text, "preferred_name": text,
        "email": csvio.email, "mobile_phone": _phone, "home_phone": _phone,
        "birth_date": lambda v: csvio.day(v, ctx.date_format),
        "gender": lambda v: csvio.choice(v, ("female", "male", "non_binary", "undisclosed")),
        "address_line1": text, "address_line2": text, "city": text, "region": text, "postal_code": text,
        "country_code": _country, "household_ref": lambda v: text(v, 100), "household_head": csvio.flag,
        "relationship_to_head": lambda v: csvio.choice(v, _RELATIONS),
        "email_marketing": csvio.flag, "sms_marketing": csvio.flag,
    })  # fmt: skip
    if data["birth_date"] and data["birth_date"] > ctx.today:
        errors.append(("birth_date", "date-in-future", "A birth date cannot be in the future."))
    if data["household_head"] and not data["household_ref"]:
        errors.append(("household_ref", "required", "A household head needs a household."))
    if data["household_head"] and data["relationship_to_head"]:
        errors.append(("relationship_to_head", "not-allowed", "Leave this empty for the household head."))
    if data["household_ref"] and not data["household_head"] and not data["relationship_to_head"]:
        errors.append(("relationship_to_head", "required", "Say how this person relates to the household head."))
    if data["email_marketing"] and not data["email"]:
        errors.append(("email_marketing", "no-address", "Email marketing needs an email address."))
    if data["sms_marketing"] and not data["mobile_phone"]:
        errors.append(("sms_marketing", "no-address", "Text marketing needs a mobile phone."))
    return data, errors


def _client_key(data: dict) -> str:
    if data.get("member_number"):
        return "m:" + data["member_number"].upper()
    if data.get("email"):
        return "e:" + "|".join([data["email"], data["first_name"].lower(), data["last_name"].lower()])
    return "n:" + "|".join([data["first_name"].lower(), data["last_name"].lower(), str(data.get("birth_date") or ""),
                            data.get("mobile_phone") or ""])  # fmt: skip


def _apply_client(session: Session, data: dict, ctx: Context) -> tuple[str, UUID, bool]:
    row = {
        "first_name": data["first_name"], "last_name": data["last_name"], "home_location_id": ctx.location_id,
        "member_number": data["member_number"], "primary_email": data["email"],
        "preferred_name": data["preferred_name"], "phone_mobile": data["mobile_phone"], "phone_home": data["home_phone"],
        "birth_on": data["birth_date"], "gender": data["gender"], "address_line1": data["address_line1"],
        "address_line2": data["address_line2"], "city": data["city"], "region": data["region"],
        "postal_code": data["postal_code"], "country_code": data["country_code"],
    }  # fmt: skip
    client, created = clients.service.import_client(session, {k: v for k, v in row.items() if v is not None})
    if data["email_marketing"] is not None or data["sms_marketing"] is not None:
        engagement.service.import_consent(
            session, client.id, email_marketing=data["email_marketing"], sms_marketing=data["sms_marketing"],
            note=f"Import job {ctx.job_id}",
        )  # fmt: skip
    if data.get("head_client_id"):  # set by the engine from the head's row
        code = "other" if data["relationship_to_head"] == "other" else f"{data['relationship_to_head']}_of"
        clients.households.import_link(session, client.id, data["head_client_id"], code)
    return EntityType.CLIENT, client.id, created


# --- memberships and contracts -----------------------------------------------------------------------------------

MEMBERSHIP_FIELDS = [
    *_ref_fields(),
    Field("membership", "Membership", True, "The name of an active membership plan, as it is spelled here.", "Adult monthly"),
    Field("start_date", "Start date", True, "", "2026-01-01"),
    Field("end_date", "End date", False, "Empty for an open-ended membership.", ""),
    Field("next_bill_date", "Next bill date", False,
          "The first date this system bills; empty when the old system already billed the whole term.", "2026-12-01"),
    Field("status", "Status", False, "active, upcoming or expired; checked against the dates.", "active"),
    Field("price", "Price", False, "The price per billing period when it differs from the plan.", "45.00"),
]  # fmt: skip


def _parse_membership(cells: dict[str, str], ctx: Context) -> tuple[dict, Errors]:
    errors: Errors = []
    _required(cells, errors, MEMBERSHIP_FIELDS)
    _check_ref(cells, errors)
    day = lambda v: csvio.day(v, ctx.date_format)  # noqa: E731
    data = _cells(cells, errors, {
        "client_member_number": lambda v: csvio.text(v, 40), "client_email": csvio.email,
        "membership": csvio.text, "start_date": day, "end_date": day, "next_bill_date": day,
        "status": lambda v: csvio.choice(v, ("active", "upcoming", "expired")), "price": csvio.money,
    })  # fmt: skip
    if data["start_date"] and data["end_date"] and data["end_date"] < data["start_date"]:
        errors.append(("end_date", "end-before-start", "The end date is before the start date."))
    return data, errors


def _membership_key(data: dict) -> str:
    ref = (data.get("client_member_number") or "").upper() or data.get("client_email") or ""
    return "|".join([ref, data["membership"].lower(), str(data["start_date"])])


def _apply_membership(session: Session, data: dict, ctx: Context) -> tuple[str, UUID, bool]:
    contract, created = memberships.service.import_contract(session, {
        "client_id": _client_ref(session, data), "location_id": ctx.location_id, "plan_name": data["membership"],
        "start_on": data["start_date"], "end_on": data["end_date"], "next_bill_on": data["next_bill_date"],
        "status": data["status"], "term_fee_minor": data["price"],
    })  # fmt: skip
    return EntityType.MEMBERSHIP_CONTRACT, contract.id, created


# --- opening balances --------------------------------------------------------------------------------------------

BALANCE_FIELDS = [
    *_ref_fields(),
    Field("amount", "Amount", True, "A plain positive number in the account currency.", "120.00"),
    Field("as_of_date", "As of date", True, "The date of the balance in the old system; not in the future.", "2026-11-01"),
    Field("direction", "Direction", True, "owed when the client owes it, credit when it is the client's credit.", "owed"),
    Field("description", "Description", False, "Shown on the client's account.", "Opening balance"),
]  # fmt: skip


def _parse_balance(cells: dict[str, str], ctx: Context) -> tuple[dict, Errors]:
    errors: Errors = []
    _required(cells, errors, BALANCE_FIELDS)
    _check_ref(cells, errors)
    data = _cells(cells, errors, {
        "client_member_number": lambda v: csvio.text(v, 40), "client_email": csvio.email, "amount": csvio.money,
        "as_of_date": lambda v: csvio.day(v, ctx.date_format),
        "direction": lambda v: csvio.choice(v, ("owed", "credit")), "description": csvio.text,
    })  # fmt: skip
    if data["amount"] == 0:
        errors.append(("amount", "invalid-amount", "The amount must be more than zero."))
    if data["as_of_date"] and data["as_of_date"] > ctx.today:
        errors.append(("as_of_date", "date-in-future", "The date cannot be in the future."))
    return data, errors


def _balance_key(data: dict) -> str:
    ref = (data.get("client_member_number") or "").upper() or data.get("client_email") or ""
    return "|".join([ref, str(data["as_of_date"]), data["direction"], str(data["amount"])])


def _apply_balance(session: Session, data: dict, ctx: Context) -> tuple[str, UUID, bool]:
    entity, entity_id = billing.service.post_opening_balance(
        session, client_id=_client_ref(session, data), location_id=ctx.location_id, amount_minor=data["amount"],
        kind="credit" if data["direction"] == "credit" else "owed", as_of=data["as_of_date"],
        description=data["description"] or f"Opening balance as of {data['as_of_date'].isoformat()}",
        key=f"{ctx.job_id}:{data['_row_key']}",
    )  # fmt: skip
    return entity, entity_id, True


# --- POS products ------------------------------------------------------------------------------------------------

PRODUCT_FIELDS = [
    Field("sku", "SKU", True, "Your stock code; matches an existing product to update.", "WATER-500"),
    Field("name", "Name", True, "", "Water 500 ml"),
    Field("category", "Category", True, "A top-level category; created when missing.", "Drinks"),
    Field("price", "Price", True, "Before tax.", "2.50"),
    Field("tax_codes", "Tax codes", False, "Codes of existing taxes, separated by ;. Empty keeps the category's.", ""),
    Field("stock_on_hand", "Stock on hand", False, "The count at the import's location.", "48"),
]  # fmt: skip


def _codes(value: str) -> list[str] | None:
    codes = [c.strip() for c in value.split(";") if c.strip()]
    if any(len(c) > 40 for c in codes):
        raise CellError("too-long", "A tax code is at most 40 characters.")
    return codes or None


def _parse_product(cells: dict[str, str], ctx: Context) -> tuple[dict, Errors]:
    errors: Errors = []
    _required(cells, errors, PRODUCT_FIELDS)
    data = _cells(cells, errors, {
        "sku": lambda v: csvio.text(v, 64), "name": csvio.text, "category": lambda v: csvio.text(v, 120),
        "price": csvio.money, "tax_codes": _codes, "stock_on_hand": lambda v: csvio.whole(v, high=1_000_000),
    })  # fmt: skip
    return data, errors


def _apply_product(session: Session, data: dict, ctx: Context) -> tuple[str, UUID, bool]:
    product, created = pos.catalogue.import_product(session, {
        "sku": data["sku"], "name": data["name"], "category": data["category"], "unit_price_minor": data["price"],
        "tax_codes": data["tax_codes"], "stock_on_hand": data["stock_on_hand"],
    }, ctx.location_id)  # fmt: skip
    return EntityType.PRODUCT, product.id, created


KINDS: dict[str, Kind] = {
    ImportKind.CLIENTS: Kind(
        ImportKind.CLIENTS,
        "Clients and households",
        EntityType.CLIENT,
        CLIENT_FIELDS,
        [
            "One row per person. A row matching an existing client by member number, or by email and name, updates "
            "that client; a row that looks like an existing client is skipped, never merged.",
            "Households: give everyone in a household the same household label, mark one person as head, and say how "
            "each other person relates to the head.",
        ],
        _parse_client,
        _client_key,
        _apply_client,
        _CLIENT_POINTERS,
        limit_key="clients",
    ),
    ImportKind.MEMBERSHIPS: Kind(
        ImportKind.MEMBERSHIPS,
        "Memberships",
        EntityType.MEMBERSHIP_CONTRACT,
        MEMBERSHIP_FIELDS,
        [
            "Import clients first. One row per membership; the plan must already exist here.",
            "Billing starts on the next bill date. A membership already imported is skipped.",
        ],
        _parse_membership,
        _membership_key,
        _apply_membership,
        {
            "/plan_name": "membership",
            "/status": "status",
            "/end_on": "end_date",
            "/next_bill_on": "next_bill_date",
            "/start_on": "start_date",
            "/client_member_number": "client_member_number",
            "/client_email": "client_email",
        },
        once=True,
    ),  # fmt: skip
    ImportKind.BALANCES: Kind(
        ImportKind.BALANCES,
        "Opening balances",
        "charge",
        BALANCE_FIELDS,
        [
            "Import clients first. One row per client balance. An amount owed becomes an invoice; a credit becomes "
            "account credit. A balance already imported is skipped."
        ],
        _parse_balance,
        _balance_key,
        _apply_balance,
        {"/client_member_number": "client_member_number", "/client_email": "client_email"},
        once=True,
    ),  # fmt: skip
    ImportKind.PRODUCTS: Kind(
        ImportKind.PRODUCTS,
        "Products",
        EntityType.PRODUCT,
        PRODUCT_FIELDS,
        [
            "One row per product. A row whose SKU matches an existing product updates it.",
            "Stock on hand is counted at the location you import into.",
        ],
        _parse_product,
        lambda data: data["sku"].lower(),
        _apply_product,
        {"/tax_codes": "tax_codes", "/sku": "sku", "/name": "name", "/unit_price_minor": "price"},
    ),  # fmt: skip
}
