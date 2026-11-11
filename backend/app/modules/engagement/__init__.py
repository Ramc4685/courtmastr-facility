"""engagement context (slice built by module 4): communication preferences and the consent log (CLI-16).

The rest of engagement (campaigns, templates, the public preference centre) belongs to its own module.
Public interface: `service` (`is_subscribed` is the send gate).
"""

from app.modules.engagement import models, service

__all__ = ["models", "service"]
