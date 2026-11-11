"""The access decision, as a pure function shared by the staff window, the client profile and the kiosk (CHK-01,
CHK-03, CHK-05). Inputs are plain values read from other contexts by the service; nothing here touches the
database. Access rules per location (CHK-08) are not built, so the data model's seeded defaults apply: deny
frozen, suspended and cancelled memberships, allow everything else and raise an alert instead."""

from dataclasses import dataclass, field
from datetime import timedelta

# Attendance is auto-marked for sessions starting this long before or after a staff check-in (CHK-01).
STAFF_EARLY, STAFF_LATE = timedelta(hours=3), timedelta(hours=5)
# Alert catalogue, highest priority first (data-model-money, kiosk_settings).
ALERTS = (
    "client_disabled", "access_denied", "membership_suspended", "membership_frozen", "membership_expired",
    "visits_depleted", "balance_due", "waiver_unsigned", "payment_method_expired", "staff_note", "birthday",
    "photo_missing", "over_daily_limit",
)  # fmt: skip
_DENY = {"frozen": "frozen", "suspended": "suspended", "cancelled": "cancelled"}
_ALERT_FOR = {
    "frozen": "membership_frozen", "suspended": "membership_suspended", "cancelled": "membership_expired",
    "expired": "membership_expired", "depleted": "visits_depleted", "daily_limit_reached": "over_daily_limit",
}  # fmt: skip


@dataclass(frozen=True)
class Facts:
    client_active: bool
    membership_reason: str | None  # memberships.eligibility()["reason"]: None, none, frozen, suspended, ...
    membership_contract_id: object = None
    has_waiver: bool = True
    balance_due_minor: int = 0
    has_staff_alert: bool = False


@dataclass(frozen=True)
class Decision:
    would_grant: bool
    denial_reason: str | None
    alerts: list[str] = field(default_factory=list)
    counts_visit: bool = False  # a granted entry is counted against the covering contract


def evaluate(facts: Facts) -> Decision:
    alerts: set[str] = set()
    denial = None
    reason = facts.membership_reason
    if not facts.client_active:
        denial = "client_disabled"
        alerts.add("client_disabled")
    elif reason in _DENY:
        denial = _DENY[reason]
    if reason in _ALERT_FOR:
        alerts.add(_ALERT_FOR[reason])
    if denial:
        alerts.add("access_denied")
    if facts.balance_due_minor > 0:
        alerts.add("balance_due")
    if not facts.has_waiver:
        alerts.add("waiver_unsigned")
    if facts.has_staff_alert:
        alerts.add("staff_note")
    counts = denial is None and facts.membership_contract_id is not None and reason is None
    return Decision(denial is None, denial, [code for code in ALERTS if code in alerts], counts)
