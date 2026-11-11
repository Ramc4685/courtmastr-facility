"""Autopay retry policy (ADR 0005 section 8, ADR 0003 section 7): a pure decision from what just failed."""

from dataclasses import dataclass
from datetime import date, timedelta

# The method itself is unusable: retrying the same method cannot succeed, so we wait for a new one.
HARD = frozenset({"expired_card", "account_closed", "authorization_revoked"})
# The method should be suspended, not just skipped (closed account, revoked mandate).
SUSPENDS = frozenset({"account_closed", "authorization_revoked"})
MAX_BANK_RETRIES = 2


@dataclass(frozen=True)
class Decision:
    state: str  # retrying | awaiting_method | exhausted
    next_attempt_on: date | None = None


def decide(
    category: str | None, tender_kind: str, failures: int, first_failed_on: date, offsets: list[int]
) -> Decision:
    """What happens to an autopay invoice after its `failures`-th consecutive decline (1 = the first).

    Hard declines never retry. A bank debit is re-presented at most twice and only for insufficient funds.
    Otherwise the next attempt is `offsets[failures - 1]` days after the first decline; when the offsets are
    used up the invoice is `exhausted` and nothing is charged automatically again.
    """
    if category in HARD:
        return Decision("awaiting_method")
    if tender_kind == "bank_debit" and category != "insufficient_funds":
        return Decision("awaiting_method")
    limit = min(len(offsets), MAX_BANK_RETRIES) if tender_kind == "bank_debit" else len(offsets)
    if failures > limit:
        return Decision("exhausted")
    return Decision("retrying", first_failed_on + timedelta(days=sorted(offsets)[failures - 1]))


AGEING_BUCKETS = ("current", "days_1_30", "days_31_60", "days_61_90", "days_over_90")


def ageing_bucket(due_on: date, as_of: date) -> str:
    """Accounts-receivable bucket of a balance by how long it has been due (BIL-19)."""
    days = (as_of - due_on).days
    if days <= 0:
        return "current"
    return "days_1_30" if days <= 30 else "days_31_60" if days <= 60 else "days_61_90" if days <= 90 else "days_over_90"
