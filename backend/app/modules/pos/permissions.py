"""pos entries of the permission catalogue: rbac-matrix.md section 6.11, row for row. Money out of a return
or void is also checked against billing.refund.create (the matrix funnels every refund through billing)."""

from app.core.auth.permissions import Permission, Scope, register

T, L = Scope.TENANT, Scope.LOCATION
_MG = {"admin": "all", "manager": "all"}
_FD = {**_MG, "front_desk": "all"}


def _p(key: str, scope: Scope, label: str, flags: str = "", roles: dict[str, str] | None = None) -> Permission:
    return Permission(f"pos.{key}", scope, label, tuple(flags.split()), roles or {})


register(
    _p("sale.create", L, "Use the register and ring up sales", "", _FD),
    _p("sale.read", L, "View POS transactions", "", _FD),
    _p("sale.override_price", L, "Override prices at the register", "P", _MG),
    _p("sale.void", L, "Void POS sales", "$", _MG),
    _p("sale.return", L, "Return POS items", "$", _MG),
    _p("receipt.resend", L, "Re-send POS receipts", "", _FD),
    _p("drawer.operate", L, "Open, count and close the cash drawer", "", _FD),
    _p("drawer.open_no_sale", L, "Open the drawer without a sale", "$", _MG),
    _p("drawer.reconcile", L, "Accept drawer variances", "", _MG),
    _p("equipment.rent", L, "Rent out and return equipment", "", _FD),
    _p("terminal.use", L, "Use card terminals", "", _FD),
    _p("terminal.manage", L, "Manage card terminals", "K", _MG),
    _p("inventory.adjust", L, "Adjust stock", "D", _MG),
    _p("product.manage", T, "Manage products and equipment", "", _MG),
    _p("register.manage", L, "Manage registers and POS settings", "", _MG),
)
