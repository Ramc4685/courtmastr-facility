"""engagement entries of the permission catalogue: rbac-matrix.md section 6.15, row for row."""

from app.core.auth.permissions import Permission, Scope, register

C, L, T = Scope.CLIENT, Scope.LOCATION, Scope.TENANT
_AD_MG = {"admin": "all", "manager": "all"}


def _p(key: str, scope: Scope, label: str, flags: str, roles: dict[str, str], own: bool = False) -> Permission:
    return Permission(f"engagement.{key}", scope, label, tuple(flags.split()), roles, accepts_own_reach=own)


register(
    _p("campaign.read", L, "View campaigns, templates, segments and message history", "", _AD_MG),
    _p("campaign.edit", L, "Edit message templates and segments", "", _AD_MG),
    _p("campaign.create", L, "Create and edit campaigns", "", _AD_MG),
    _p("campaign.send", L, "Send email campaigns", "B", _AD_MG),
    _p("campaign.send_all", L, "Send campaigns to every client", "B", _AD_MG),
    _p("sms_campaign.send", L, "Send SMS campaigns", "B", _AD_MG),
    _p("push.send", L, "Send announcements and push notifications", "B", _AD_MG),
    _p("message.send_direct", C, "Email one client directly", "",
       {**_AD_MG, "front_desk": "all", "coach": "own", "league_admin": "all"}, own=True),
    _p("inbox.reply", L, "Reply to client messages", "", {**_AD_MG, "front_desk": "all"}),
    _p("app_content.manage", L, "Manage app and portal content", "", _AD_MG),
    _p("portal_settings.manage", L, "Manage member portal settings", "", _AD_MG),
    _p("notification_rule.manage", L, "Manage reminders and staff alerts", "", _AD_MG),
    _p("automation.manage", L, "Manage automated messages", "B", _AD_MG),
    _p("suppression.manage", T, "Release suppressed addresses", "", {"admin": "all"}),
)  # fmt: skip
