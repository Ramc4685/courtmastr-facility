"""AccountingSync and AccountingConnect adapters (app.ports.accounting)."""

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlencode

import httpx

from app.ports.accounting import Credentials, Journal, Option


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
    It takes a current access token; `QuickBooksConnect` does the OAuth round trip and refresh.
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


def _webhook_signature(secret: str, body: bytes) -> str:
    return base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()


class FakeQuickBooks:
    """Simulated QuickBooks connection: the authorise URL points straight back at our callback with a code,
    tokens are opaque strings, and the chart of accounts is a fixed sample. Nothing leaves the process."""

    name, simulated = "fake_quickbooks", True
    WEBHOOK_SECRET = "fake-quickbooks-verifier"  # noqa: S105  (a public test value, never a real verifier)

    def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        realm = str(secrets.randbelow(10**15) + 10**15)  # a fresh simulated company per authorisation
        return f"{redirect_uri}?{urlencode({'state': state, 'code': f'fake-code.{realm}', 'realm_id': realm})}"

    def exchange_code(self, *, code: str, company_id: str, redirect_uri: str) -> Credentials:
        prefix, _, realm = code.partition(".")
        if prefix != "fake-code" or not realm.isdigit():
            raise ValueError("invalid_grant")
        # the token belongs to the company the code was issued for, whatever the browser claims
        return Credentials(f"fake-at.{realm}", f"fake-rt.{realm}", time.time() + 3600, company_id)

    def token_company_id(self, credentials: Credentials) -> str | None:
        realm = credentials.access_token.split(".")[1].rstrip("+")
        return realm if realm == credentials.company_id else None

    def refresh(self, credentials: Credentials) -> Credentials:
        return Credentials(credentials.access_token + "+", credentials.refresh_token, time.time() + 3600,
                           credentials.company_id)  # fmt: skip

    def revoke(self, credentials: Credentials) -> None:
        return None

    def list_options(self, credentials: Credentials) -> list[Option]:
        return [
            Option("1", "Undeposited Funds", "account"), Option("4", "Sales of Product Income", "account"),
            Option("12", "Accounts Receivable", "account"), Option("33", "Sales Tax Payable", "account"),
            Option("100", "Courts", "class"),
        ]  # fmt: skip

    def verify_webhook(self, body: bytes, signature: str) -> bool:
        return hmac.compare_digest(_webhook_signature(self.WEBHOOK_SECRET, body), signature or "")

    def journal_poster(self, credentials: Credentials) -> FakeAccounting:
        return FakeAccounting()


class QuickBooksConnect:
    """Intuit OAuth 2.0 and the Accounting API's account and class queries. Never called live in this build:
    no Intuit app exists, so tests drive it through httpx.MockTransport (docs/status/phase15-api.md)."""

    name, simulated = "quickbooks_online", False
    AUTHORIZE_URL = "https://appcenter.intuit.com/connect/oauth2"
    TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
    REVOKE_URL = "https://developer.api.intuit.com/v2/oauth2/tokens/revoke"
    SCOPE = "com.intuit.quickbooks.accounting"

    def __init__(
        self, *, client_id: str, client_secret: str, webhook_verifier: str, client: httpx.Client | None = None
    ) -> None:
        self.client_id, self.webhook_verifier = client_id, webhook_verifier
        self.client = client or httpx.Client(base_url=QuickBooksOnline.BASE_URL, timeout=30)
        basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        self.auth = {"Authorization": f"Basic {basic}", "Accept": "application/json"}

    def authorize_url(self, *, state: str, redirect_uri: str) -> str:
        query = {"client_id": self.client_id, "response_type": "code", "scope": self.SCOPE,
                 "redirect_uri": redirect_uri, "state": state}  # fmt: skip
        return f"{self.AUTHORIZE_URL}?{urlencode(query)}"

    def _token(self, form: dict, company_id: str) -> Credentials:
        response = self.client.post(self.TOKEN_URL, data=form, headers=self.auth)
        response.raise_for_status()
        body = response.json()
        return Credentials(
            body["access_token"], body["refresh_token"], time.time() + int(body["expires_in"]), company_id
        )

    def exchange_code(self, *, code: str, company_id: str, redirect_uri: str) -> Credentials:
        return self._token({"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}, company_id)

    def token_company_id(self, credentials: Credentials) -> str | None:
        """Reads the company's own record with the token: Intuit answers 401 or 403 for a realm the token was
        not issued for, so a realm id the browser invented never verifies."""
        response = self.client.get(
            f"/v3/company/{credentials.company_id}/companyinfo/{credentials.company_id}",
            params={"minorversion": "73"},
            headers={"Authorization": f"Bearer {credentials.access_token}", "Accept": "application/json"},
        )
        if response.status_code in (401, 403, 404):
            return None
        response.raise_for_status()
        return str(response.json()["CompanyInfo"]["Id"])

    def refresh(self, credentials: Credentials) -> Credentials:
        form = {"grant_type": "refresh_token", "refresh_token": credentials.refresh_token}
        return self._token(form, credentials.company_id)

    def revoke(self, credentials: Credentials) -> None:
        self.client.post(
            self.REVOKE_URL, json={"token": credentials.refresh_token}, headers=self.auth
        ).raise_for_status()

    def list_options(self, credentials: Credentials) -> list[Option]:
        headers = {"Authorization": f"Bearer {credentials.access_token}", "Accept": "application/json"}
        out = []
        for entity, kind in (("Account", "account"), ("Class", "class")):
            response = self.client.get(
                f"/v3/company/{credentials.company_id}/query",
                params={"query": f"select Id, Name from {entity} where Active = true", "minorversion": "73"},
                headers=headers,
            )
            response.raise_for_status()
            rows = response.json().get("QueryResponse", {}).get(entity, [])
            out += [Option(str(row["Id"]), row["Name"], kind) for row in rows]
        return out

    def verify_webhook(self, body: bytes, signature: str) -> bool:
        """`intuit-signature`: base64 HMAC-SHA256 of the raw body under the app's verifier token."""
        return hmac.compare_digest(_webhook_signature(self.webhook_verifier, body), signature or "")

    def journal_poster(self, credentials: Credentials) -> QuickBooksOnline:
        return QuickBooksOnline(
            realm_id=credentials.company_id, access_token=credentials.access_token, client=self.client
        )
