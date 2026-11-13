"""Base request and response models shared by every context's schemas.py (overview 3.13, 3.14)."""

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, model_validator

from app.core.errors import ValidationFailed
from app.core.pan import contains_card_number

# Stored free text a person types (notes, messages, form answers, post bodies): scanned for card numbers on write
# (security-baseline section 3). Codes, barcodes, references and tokens are not listed: they can be long digit runs.
# shortcut: matched by field name across every In schema; a new free-text field with another name is not scanned
# until it is added here.
FREE_TEXT_FIELDS = frozenset({
    "note", "notes", "internal_note", "internal_notes", "medical_notes", "change_note", "additional_income_note",
    "body", "body_text", "message", "comment", "comments", "registrant_comment", "memo", "remarks",
    "internal_remarks", "removal_remarks", "renewal_remark", "reason", "edit_reason", "override_reason", "text",
    "text_value", "text_answers", "custom_values", "subject", "subject_text", "summary", "detail",
})  # fmt: skip


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

    @model_validator(mode="after")
    def refuse_card_data(self) -> Self:
        # Nested In models run their own check; this covers strings, lists and dicts held by a free-text field.
        for name in FREE_TEXT_FIELDS.intersection(type(self).model_fields):
            if _has_card(getattr(self, name)):
                raise ValidationFailed(
                    "Card numbers cannot be stored here. Take payments through the payment form.",
                    code="card-data-not-allowed", pointer=f"/{name}",
                )  # fmt: skip
        return self


class PageInfo(BaseModel):
    next_cursor: str | None
    has_more: bool
    total: int | None = None


class Page[T](BaseModel):
    data: list[T]
    page: PageInfo
