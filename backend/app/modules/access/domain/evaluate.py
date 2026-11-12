"""The access decision, as a pure function shared by the staff window, the client profile and the kiosk (CHK-01,
CHK-03, CHK-05). Inputs are plain values read from other contexts by the service; nothing here touches the
database.

Order (CHK-08, CHK-09, CHK-10, MEM-20): a disabled client is denied; then the client's access mode (always deny,
always admit); then the location's outcome for the membership's condition (frozen, suspended, used-up visits,
second visit of the day), then the membership type's admitting locations, then its time-of-day schedule.
Everything that does not deny is still raised as an alert."""

from dataclasses import dataclass, field
from datetime import timedelta

# Attendance is auto-marked for sessions starting this long before or after a staff check-in (CHK-01); a
# location's access settings may change it (CHK-02).
STAFF_EARLY, STAFF_LATE = timedelta(hours=3), timedelta(hours=5)
# Booking a session from the window (CHK-04): one that started up to an hour ago or starts in the next four.
BOOK_EARLY, BOOK_LATE = timedelta(hours=1), timedelta(hours=4)
# What the window offers to clear an alert (CHK-21); anything else has no remedy at the desk.
ALERT_ACTION = {
    "balance_due": "take_payment", "waiver_unsigned": "sign_waiver", "membership_expired": "renew_membership",
    "visits_depleted": "renew_membership", "payment_method_expired": "update_payment_method",
}  # fmt: skip
# Alert catalogue, highest priority first (data-model-money, kiosk_settings).
ALERTS = (
    "client_disabled", "access_denied", "membership_suspended", "membership_frozen", "membership_expired",
    "visits_depleted", "balance_due", "waiver_unsigned", "payment_method_expired", "staff_note", "birthday",
    "photo_missing", "over_daily_limit",
)  # fmt: skip
# memberships.eligibility() reason -> the rule condition it falls under.
_CONDITION = {
    "frozen": "frozen",
    "suspended": "suspended",
    "depleted": "depleted",
    "daily_limit_reached": "over_daily_limit",
}
# Outcome per condition when the location has no rule (owner question 12: used-up visits are refused).
DEFAULT_RULES = {"frozen": "deny", "suspended": "deny", "depleted": "deny", "over_daily_limit": "allow"}
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
    access_mode: str = "normal"  # normal | always_admit | always_deny (client_access)
    rules: dict = field(default_factory=dict)  # condition -> allow | deny, this location's rows
    location_admits: bool = True  # the membership type admits at this location (CHK-10)
    schedule_open: bool = True  # inside the membership type's schedule now, in the location's zone (CHK-09)
    repeat_entry: bool = False  # admitted here within the repeat window: the same entry, no second visit


@dataclass(frozen=True)
class Decision:
    would_grant: bool
    denial_reason: str | None
    alerts: list[str] = field(default_factory=list)
    counts_visit: bool = False  # a granted entry is counted against the covering contract


def _denial(facts: Facts) -> str | None:
    if not facts.client_active:
        return "client_disabled"
    if facts.access_mode == "always_deny":
        return "access_mode_deny"
    if facts.access_mode == "always_admit":
        return None
    if facts.membership_reason == "cancelled":
        return "cancelled"
    condition = _CONDITION.get(facts.membership_reason or "")
    # A repeat entry is the visit already counted: a pass it just used up does not turn the client away.
    if facts.repeat_entry and condition in ("depleted", "over_daily_limit"):
        condition = None
    if condition and {**DEFAULT_RULES, **facts.rules}[condition] == "deny":
        return condition
    if facts.membership_contract_id is not None and not facts.location_admits:
        return "wrong_location"
    if facts.membership_contract_id is not None and not facts.schedule_open:
        return "outside_schedule"
    return None


def evaluate(facts: Facts) -> Decision:
    alerts: set[str] = set()
    denial = _denial(facts)
    reason = facts.membership_reason
    if not facts.client_active:
        alerts.add("client_disabled")
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
    counts = denial is None and facts.membership_contract_id is not None and reason is None and not facts.repeat_entry
    return Decision(denial is None, denial, [code for code in ALERTS if code in alerts], counts)


def in_schedule(ranges: list[tuple[int, str, str]], weekday: int, wall: str) -> bool:
    """`wall` ('HH:MM', the location's local time) on ISO `weekday` falls inside one of the ranges."""
    return any(day == weekday and starts <= wall < ends for day, starts, ends in ranges)
