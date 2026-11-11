"""integrations entries of the permission catalogue: rbac-matrix.md section 6.18, row for row."""

from app.core.auth.permissions import Permission, Scope, register

T, L = Scope.TENANT, Scope.LOCATION
_AD = {"admin": "all"}


def _p(key: str, scope: Scope, label: str, flags: str = "", roles: dict[str, str] | None = None) -> Permission:
    return Permission(f"integrations.{key}", scope, label, tuple(flags.split()), roles or {})


register(
    _p("api_key.manage", T, "Manage API keys", "K A +", _AD),
    _p("webhook.manage", T, "Manage outbound webhooks", "K", _AD),
    _p("connection.manage", T, "Connect and configure external providers", "K", _AD),
    _p("sync.run", T, "Run accounting exports", "", _AD),
    _p("delivery.read", T, "View the webhook delivery log", "", _AD),
    _p("calendar_feed.revoke_any", L, "Revoke anyone's calendar feed", "K", {"admin": "all", "manager": "all"}),
)
