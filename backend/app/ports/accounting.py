"""AccountingSync port (ADR 0012 sections 4 and 6). integrations posts one summarised journal per location-day.

Adapters: `fake_accounting` (simulated: records the command), `accounting_file` (writes the journal as JSON) and
`quickbooks_online` (Intuit REST, disabled by default; exercised only with a mocked HTTP layer).
`AccountingConnect` is the connection side (OAuth, refresh, revoke, chart of accounts, webhook signature):
`FakeQuickBooks` and `QuickBooksConnect`.
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


@dataclass(frozen=True)
class Credentials:
    access_token: str
    refresh_token: str
    expires_at: float  # unix seconds
    company_id: str  # the provider's company (QuickBooks realm)


@dataclass(frozen=True)
class Option:
    id: str
    name: str
    kind: str  # account | class


class AccountingConnect(Protocol):
    """The OAuth connection of an accounting provider (INT-07): authorise, exchange, refresh, revoke, the
    accounts and classes to map to, and the inbound webhook signature."""

    name: str
    simulated: bool

    def authorize_url(self, *, state: str, redirect_uri: str) -> str: ...

    def exchange_code(self, *, code: str, company_id: str, redirect_uri: str) -> Credentials: ...

    def refresh(self, credentials: Credentials) -> Credentials: ...

    def revoke(self, credentials: Credentials) -> None: ...

    def list_options(self, credentials: Credentials) -> list[Option]: ...

    def verify_webhook(self, body: bytes, signature: str) -> bool: ...

    def journal_poster(self, credentials: Credentials) -> AccountingSync: ...
