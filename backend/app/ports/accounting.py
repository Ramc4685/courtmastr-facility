"""AccountingSync port (ADR 0012 sections 4 and 6). integrations posts one summarised journal per location-day.

Adapters: `fake_accounting` (simulated: records the command), `accounting_file` (writes the journal as JSON) and
`quickbooks_online` (Intuit REST, disabled by default; exercised only with a mocked HTTP layer).
"""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class JournalLine:
    account_ref: str  # the provider's account id (or our posting key for file adapters)
    debit_minor: int
    credit_minor: int
    class_ref: str | None = None
    description: str = ""


@dataclass(frozen=True)
class Journal:
    doc_number: str  # FH-<location code>-<YYYYMMDD>
    business_on: str  # ISO date
    currency: str
    memo: str
    lines: list[JournalLine] = field(default_factory=list)


class AccountingSync(Protocol):
    name: str
    simulated: bool

    def post_journal(self, journal: Journal, *, request_id: str) -> str:
        """Post once per request_id (the provider deduplicates on it); returns the provider's journal id."""
        ...
