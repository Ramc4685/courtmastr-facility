"""Base request and response models shared by every context's schemas.py (overview 3.13, 3.14)."""

from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationInfo, field_validator
from pydantic_core import PydanticCustomError

from app.core.pan import contains_card_number

# Stored free text a person types (notes, messages, form answers, post bodies, descriptions, titles): scanned for
# card numbers on write (security-baseline section 3). Codes, barcodes, references and tokens are not listed: they
# can be long digit runs. Client custom values are checked in clients.service, where a field's type is known (text
# fields only). CSV imports skip these schemas and check FREE_TEXT_FIELDS in imports.service.
# shortcut: matched by field name across every In schema; a new free-text field with another name is not scanned
# until it is added here.
FREE_TEXT_FIELDS = frozenset({
    "note", "notes", "internal_note", "internal_notes", "medical_notes", "change_note", "additional_income_note",
    "body", "body_text", "message", "comment", "comments", "registrant_comment", "memo", "remarks",
    "internal_remarks", "removal_remarks", "renewal_remark", "reason", "edit_reason", "override_reason", "text",
    "text_value", "text_answers", "subject", "subject_text", "summary", "detail", "description",
    "additional_description", "title",
})  # fmt: skip
CARD_DATA = "card-data-not-allowed"
CARD_DATA_DETAIL = "Card numbers cannot be stored here. Take payments through the payment form."


def _has_card(value: Any) -> bool:
    if isinstance(value, str):
        return contains_card_number(value)
    if isinstance(value, dict):
        return any(_has_card(v) for v in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_has_card(v) for v in value)
    return False


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class In(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def refuse_card_data(cls, value: Any, info: ValidationInfo) -> Any:
        # A field-level error, so the location is the full path inside nested models (core.api turns a body with
        # one into a `card-data-not-allowed` problem); the value is never echoed.
        if info.field_name in FREE_TEXT_FIELDS and _has_card(value):
            raise PydanticCustomError(CARD_DATA, CARD_DATA_DETAIL)
        return value


class PageInfo(BaseModel):
    next_cursor: str | None
    has_more: bool
    total: int | None = None


class Page[T](BaseModel):
    data: list[T]
    page: PageInfo
