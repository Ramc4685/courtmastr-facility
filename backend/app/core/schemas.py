"""Base request and response models shared by every context's schemas.py (overview 3.13, 3.14)."""

from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from app.core.errors import ValidationFailed


def _nul_pointer(value: Any, path: str = "") -> str | None:
    """The JSON pointer of the first string holding a NUL character, if any."""
    if isinstance(value, str):
        return path if "\x00" in value else None
    items = value.items() if isinstance(value, dict) else enumerate(value) if isinstance(value, list) else ()
    for key, item in items:
        if (found := _nul_pointer(item, f"{path}/{key}")) is not None:
            return found
    return None


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class In(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _no_nul(cls, data: Any) -> Any:
        # Postgres text cannot hold NUL (it would be a 500): refuse it once here, for every request body.
        if (pointer := _nul_pointer(data)) is not None:
            raise ValidationFailed("Text cannot contain a NUL character.", pointer=pointer or "/")
        return data


class PageInfo(BaseModel):
    next_cursor: str | None
    has_more: bool
    total: int | None = None


class Page[T](BaseModel):
    data: list[T]
    page: PageInfo
