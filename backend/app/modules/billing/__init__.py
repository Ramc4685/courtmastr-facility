"""billing context (L2): receivables and money (ADR 0003, ADR 0005 section 8; build module 8).

Public interface for routers, jobs and other contexts: `service` (charges, invoices, payments, the undo
operations, account credit), `catalogue` (settings, coupons: `settings_for`, `quote_coupon`, `redeem_coupon`,
`release_coupon`), `methods` (stored payment methods) and `documents` (`billing_summary`). Never import this
package's models or schemas from another context.
"""

from app.modules.billing import models, permissions, service  # noqa: I001  (service before what builds on it)
from app.modules.billing import catalogue, methods, autopay, documents, webhooks

__all__ = ["autopay", "catalogue", "documents", "methods", "models", "permissions", "service", "webhooks"]
