"""AccountingSync adapters (app.ports.accounting)."""

import json
from dataclasses import asdict
from pathlib import Path

import httpx

from app.ports.accounting import Journal


class FakeAccounting:
    """Simulated: integrations records each call in adapter_command_log; nothing leaves the process."""

    name, simulated = "fake_accounting", True

    def post_journal(self, journal: Journal, *, request_id: str) -> str:
        return f"fake-je-{request_id.rsplit(':', 1)[-1]}"


class JsonFileAccounting:
    """Writes each journal to <dir>/<request id>.json: a bookkeeper imports it, or support explains a line.
    Rewriting the same request id overwrites the same file, so a retried export is idempotent."""

    name, simulated = "accounting_file", False

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)

    def post_journal(self, journal: Journal, *, request_id: str) -> str:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{request_id.replace(':', '_')}.json"
        path.write_text(json.dumps(asdict(journal), indent=2, sort_keys=True))
        return path.name


class QuickBooksOnline:
    """Intuit Accounting API v3, JournalEntry create. Disabled by default (integrations.quickbooks_enabled):
    no Intuit app or credentials exist yet, so tests drive it through httpx.MockTransport only.

    `requestid` makes the create idempotent at Intuit; amounts are decimal strings in the company currency.
    shortcut: the OAuth authorisation-code round trip and refresh-token rotation are not built; the adapter takes
    a current access token. Build them with the connection screen when an Intuit app is registered.
    """

    name, simulated = "quickbooks_online", False
    BASE_URL = "https://quickbooks.api.intuit.com"

    def __init__(self, *, realm_id: str, access_token: str, client: httpx.Client | None = None) -> None:
        self.realm_id = realm_id
        self.client = client or httpx.Client(base_url=self.BASE_URL, timeout=30)
        self.headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}

    def post_journal(self, journal: Journal, *, request_id: str) -> str:
        lines = [
            {
                "Description": line.description,
                "Amount": f"{(line.debit_minor or line.credit_minor) / 100:.2f}",
                "DetailType": "JournalEntryLineDetail",
                "JournalEntryLineDetail": {
                    "PostingType": "Debit" if line.debit_minor else "Credit",
                    "AccountRef": {"value": line.account_ref},
                    **({"ClassRef": {"value": line.class_ref}} if line.class_ref else {}),
                },
            }
            for line in journal.lines
        ]
        body = {
            "DocNumber": journal.doc_number,
            "TxnDate": journal.business_on,
            "PrivateNote": journal.memo,
            "CurrencyRef": {"value": journal.currency},
            "Line": lines,
        }
        response = self.client.post(
            f"/v3/company/{self.realm_id}/journalentry",
            params={"requestid": request_id, "minorversion": "73"},
            json=body,
            headers=self.headers,
        )
        response.raise_for_status()
        return str(response.json()["JournalEntry"]["Id"])
