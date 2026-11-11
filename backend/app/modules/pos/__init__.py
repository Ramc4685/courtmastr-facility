"""pos context (L3): point of sale and inventory (build module 9).

Public interface for routers, jobs and other contexts: `service` (settings, registers, `check_network`),
`catalogue` (products, categories, suppliers, brands, presets, equipment), `inventory` (`move`, `on_hand`),
`drawer`, `sales` (`abandon_stale_drafts` for a daily job), `returns`, `equipment` and `reports`. Every sale
posts through billing; nothing here writes billing tables. Never import this package's models or schemas
from another context.
"""

from app.modules.pos import models, permissions, service  # noqa: I001  (service before what builds on it)
from app.modules.pos import catalogue, inventory, drawer, equipment, sales, returns, reports

__all__ = [
    "catalogue", "drawer", "equipment", "inventory", "models", "permissions", "reports", "returns", "sales", "service",
]  # fmt: skip
from app.modules.pos import subject  # noqa: E402, F401  (registers the merge and data-subject handlers)
