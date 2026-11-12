"""billing context (L2): receivables and money (ADR 0003, ADR 0005 section 8; build module 8).

Public interface for routers, jobs and other contexts: `service` (charges, invoices, payments, the undo
operations, account credit), `catalogue` (settings, coupons: `settings_for`, `quote_coupon`, `redeem_coupon`,
`release_coupon`), `methods` (stored payment methods) and `documents` (`billing_summary`). Never import this
package's models or schemas from another context.
"""

from app.modules.billing import models, permissions, service  # noqa: I001  (service before what builds on it)
from app.modules.billing import catalogue, methods, autopay, checkout, documents, webhooks
from app.modules.billing import statements  # noqa: E402, F401  (after documents, which it builds on)

__all__ = ["autopay", "catalogue", "checkout", "documents", "methods", "models", "permissions", "service", "webhooks"]
from app.modules.billing import (
    catalog,  # noqa: E402, F401  (pre-defined items; registers its renewal actor)
    collections,  # noqa: E402, F401  (registers the portal past-due guard)
    subject,  # noqa: E402, F401  (registers the merge and data-subject handlers)
)
from app.modules.platform import onboarding  # noqa: E402

onboarding.register_step("payments", label="Connect a payment provider", path="/billing/setup", order=50,
                         done=onboarding.has_rows(models.ProviderAccount, models.ProviderAccount.status == "active"))  # fmt: skip
