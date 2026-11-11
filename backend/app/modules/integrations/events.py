"""Events the integrations context emits. Thin payloads: ids and the transition, no PII (overview 3.11)."""

from typing import ClassVar, Literal
from uuid import UUID

from app.core.events import Event


class WebhookEndpointDisabled(Event):
    """Operational, never delivered to webhooks (ADR 0007 section 6: `webhook = false`)."""

    aggregate_type: ClassVar[str] = "webhook_endpoint"
    type: Literal["integrations.webhook_endpoint.disabled"] = "integrations.webhook_endpoint.disabled"
    webhook_endpoint_id: UUID
    reason: str
