"""clients context (L1): people, households, activity, merge (module 4).

Public interface for routers, jobs and other contexts: `service` (the record, lists, internal helpers),
`households` (relationships, portal access, `can_act_for`), `activity` (notes, tasks, alerts, timeline),
`merge` (duplicates, merge, the merge-handler registry) and `terms` (the portal terms acknowledgment hook).
Never import this package's models or schemas from another context.
"""

from app.modules.clients import models, permissions, service  # isort: skip
from app.modules.clients import activity, households, merge, terms

__all__ = ["activity", "households", "merge", "models", "permissions", "service", "terms"]

# Platform hooks: invited access rows go live when the identity accepts; /me lists the clients it acts for.
from app.modules import platform as _platform  # noqa: E402

_platform.auth.ACTIVATION_HOOKS.append(service.activate_access_for_identity)
_platform.service.register_client_ids_resolver(households.actable_client_ids)
_platform.entitlements.register_usage_counter("clients", service.count_active_clients)  # PLT-14 client limit
