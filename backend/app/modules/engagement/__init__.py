"""engagement context (module 14): communication preferences and consent (CLI-16), templates, segments,
campaigns and announcements, the delivery log and suppressions, reminders, automations, staff alert routes,
the portal inbox and devices, portal settings and videos. Public interface: `service` (`is_subscribed` is the
consent gate; `alert_staff`, `schedule_reminders` and `record_delivery_event` are internal entry points)."""

from app.modules.engagement import models, permissions  # noqa: F401  # isort: skip
from app.modules.engagement import handlers, jobs, service, subject  # noqa: F401

__all__ = ["models", "service"]
