"""Events the engagement context emits (overview section 2). Thin payloads: ids and the transition."""

from typing import ClassVar, Literal
from uuid import UUID

from app.core.events import Event


class CampaignSent(Event):
    aggregate_type: ClassVar[str] = "campaign"
    type: Literal["engagement.campaign.sent"] = "engagement.campaign.sent"
    campaign_id: UUID
    location_id: UUID
    channel: str


class MessageBounced(Event):
    aggregate_type: ClassVar[str] = "message"
    type: Literal["engagement.message.bounced"] = "engagement.message.bounced"
    message_id: UUID
    client_id: UUID | None


class ConsentChanged(Event):
    aggregate_type: ClassVar[str] = "client"
    type: Literal["engagement.consent.changed"] = "engagement.consent.changed"
    client_id: UUID
    source: str


class AppConfigUpdated(Event):
    aggregate_type: ClassVar[str] = "app_config"
    type: Literal["engagement.app_config.updated"] = "engagement.app_config.updated"
    app_config_id: UUID
