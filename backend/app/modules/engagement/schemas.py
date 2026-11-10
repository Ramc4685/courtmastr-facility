"""engagement request and response models: communication preferences (CLI-16)."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints

from app.core.schemas import In, Out

ChannelValue = Literal["email", "sms", "push"]
TopicValue = Literal[
    "session_reminders", "card_expiration", "email_campaigns", "sms_marketing", "push_announcements", "league_alerts"
]


class PreferenceOut(Out):
    channel: str
    address: str | None
    topic: str
    is_subscribed: bool
    is_default: bool
    source: str | None
    changed_at: datetime | None


class Preferences(Out):
    data: list[PreferenceOut]


class PreferenceChange(In):
    channel: ChannelValue
    address: Annotated[str, StringConstraints(max_length=254)] | None = None  # email address or E.164 number
    topic: TopicValue
    is_subscribed: bool


class PreferencesReplace(In):
    """Staff changes record how the client gave consent (basis) and a note; the portal records `express`."""

    changes: Annotated[list[PreferenceChange], Field(min_length=1, max_length=60)]
    basis: Literal["express", "express_written", "express_verbal", "implied_purchase", "implied_inquiry"] = "express"
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)] | None = None


class PortalPreferencesReplace(In):
    changes: Annotated[list[PreferenceChange], Field(min_length=1, max_length=60)]


class ClientRef(Out):
    client_id: UUID
