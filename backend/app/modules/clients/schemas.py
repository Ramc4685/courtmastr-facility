"""Request and response models for the clients API (docs/api/openapi-people.yaml, tag clients). Skeleton."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import EmailStr, StringConstraints

from app.core.schemas import In, Out, Page  # noqa: F401  (Page is used by the router as s.Page)

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Phone = Annotated[str, StringConstraints(pattern=r"^\+[1-9][0-9]{6,14}$")]  # E.164
MemberNumber = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]


class ClientCreate(In):
    first_name: Name
    last_name: Name
    home_location_id: UUID
    primary_email: EmailStr | None = None
    phone_mobile: Phone | None = None
    member_number: MemberNumber | None = None  # typed by staff; generated numbers arrive with build module 4


class ClientOut(Out):
    id: UUID
    first_name: str
    last_name: str
    primary_email: str | None
    phone_mobile: str | None
    home_location_id: UUID
    member_number: str | None
    status: Literal["active", "disabled"]
    created_at: datetime
