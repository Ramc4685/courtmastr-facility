"""rentals entries of the permission catalogue: rbac-matrix.md section 6.4, row for row."""

from app.core.auth.permissions import Permission, Scope, register

L, T = Scope.LOCATION, Scope.TENANT
_MG = {"admin": "all", "manager": "all"}
_FD = {**_MG, "front_desk": "all"}


def _p(key, label, flags="", roles=None, scope=L) -> Permission:
    return Permission(f"rentals.{key}", scope, label, tuple(flags.split()), roles or {}, False, None)


register(
    _p("booking.create", "Book rentals", "", _FD),
    _p("booking.update", "Edit, extend and bill rentals", "", _FD),
    _p("booking.cancel", "Remove rentals from the schedule", "", _FD),
    _p("booking.override_rate", "Key a custom rental price or waive a late-cancel fee", "P", _MG),
    _p("booking.override_minor", "Book a court in a minor's name, with a reason", "P", _MG),
    _p("rental_type.manage", "Manage rental types and rates", "", _MG, scope=T),
    _p("rental_plan.manage", "Manage rental plans", "", _MG, scope=T),
    _p("rental_plan.sell", "Sell rental plans", "", _FD),
    _p("rental_plan.share", "Share rental plans", "", _MG),
    _p("rental_plan.remove", "Remove and refund rental plans", "D", _MG),
    _p("locker_rental.manage", "Rent and clear lockers", "", _FD),
    _p("portal_setting.manage", "Set online rental defaults for a location", "", _MG),
    _p("public_listing.publish", "Publish rentals on the public schedule", "", {**_MG, "league_admin": "all"}),
)
