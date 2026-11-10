"""billing entries of the permission catalogue: rbac-matrix.md section 6.10, row for row.

The whole section is registered now, although the kernel enforces only the keys its endpoints use, so that
seeded and custom roles already carry the right grants when build module 8 adds the operations.
"""

from app.core.auth.permissions import Permission, Scope, register

T, L, C = Scope.TENANT, Scope.LOCATION, Scope.CLIENT
_AD = {"admin": "all"}
_MG = {"admin": "all", "manager": "all"}
_FD = {**_MG, "front_desk": "all"}
_FD_LM = {**_FD, "league_admin": "all"}


def _p(key: str, scope: Scope, label: str, flags: str = "", roles: dict[str, str] | None = None) -> Permission:
    return Permission(f"billing.{key}", scope, label, tuple(flags.split()), roles or {})


register(
    _p("charge.read", C, "View billing items", "", _FD_LM),
    _p("charge.create", L, "Add billing items", "", _FD),
    _p("charge.update", L, "Edit billing item descriptions and dates", "", _FD),
    _p("charge.override_price", L, "Override prices", "P", _MG),
    _p("charge.reverse", L, "Reverse billing items", "$", _MG),
    _p("charge.void", L, "Void billing items", "$", _MG),
    _p("invoice.read", C, "View invoices", "", _FD_LM),
    _p("invoice.create", L, "Create invoices", "", _FD),
    _p("invoice.bulk_create", L, "Create invoices in bulk", "D", _MG),
    _p("invoice.update", L, "Edit invoices", "", _FD),
    _p("invoice.reassign_payer", L, "Change who an invoice is billed to", "", _MG),
    _p("invoice.void", L, "Void invoices", "$", _MG),
    _p("invoice.send", C, "Send invoices", "", _FD),
    _p("payment_schedule.manage", L, "Manage payment schedules", "", _MG),
    _p("statement.send", L, "Send statements", "B", _MG),
    _p("payment.read", C, "View payments", "", _FD),
    _p("payment.take", C, "Take payments", "", _FD),
    _p("payment.reallocate", L, "Apply and move payments between items", "", _MG),
    _p("payment.void", L, "Void payments", "$", _MG),
    _p("refund.create", L, "Refund payments", "$", _MG),
    _p("credit.issue", L, "Issue account credit", "$", _MG),
    _p("credit.apply", C, "Apply account credit", "", _FD),
    _p("payment_method.read", C, "View stored payment methods", "", _FD),
    _p("payment_method.manage", C, "Add and remove stored payment methods", "", _FD),
    _p("autopay.configure", L, "Configure autopay", "", _MG),
    _p("autopay.run", L, "Run autopay", "D", _MG),
    _p("discount.apply_preset", L, "Apply preset discounts and coupons", "", _FD),
    _p("discount.apply_custom", L, "Apply custom discounts", "P", _MG),
    _p("coupon.manage", T, "Manage coupons", "P", _MG),
    _p("item.manage", T, "Manage pre-defined billing items", "", _MG),
    _p("collections.manage", L, "Manage collections", "", _MG),
    _p("dispute.manage", L, "Manage payment disputes", "", _AD),
    _p("history.read", L, "View billing history", "", _MG),
    _p("ledger.read", L, "View ledger entries", "", _AD),
    _p("ledger.export", L, "Export the ledger", "X", _AD),
    _p("tax.manage", T, "Manage taxes", "A", _AD),
    _p("revenue_category.manage", T, "Manage revenue categories", "", _AD),
    _p("settings.manage", T, "Manage billing settings", "A", _AD),
    _p("provider.manage", T, "Connect the payment processor", "K OD +"),
)
