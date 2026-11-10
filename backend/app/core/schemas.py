"""Base request and response models shared by every context's schemas.py (overview 3.13, 3.14)."""

from pydantic import BaseModel, ConfigDict


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PageInfo(BaseModel):
    next_cursor: str | None
    has_more: bool
    total: int | None = None


class Page[T](BaseModel):
    data: list[T]
    page: PageInfo
