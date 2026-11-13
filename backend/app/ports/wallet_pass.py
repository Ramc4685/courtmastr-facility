"""Wallet pass port (CHK-13, APP-06). A pass is a static card in Apple Wallet or Google Wallet whose barcode carries
the check-in credential; it cannot rotate, so access issues it its own long-lived, revocable credential.

Signed passes need the tenant's or platform's issuer accounts (Apple Pass Type ID certificate, Google Wallet
issuer). Until those exist only the fake adapter is wired (app.bootstrap): it builds an unsigned pass document
the app can show, and `signed` stays False so nobody mistakes it for a wallet-ready file."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PassContent:
    serial: str  # the credential id
    barcode_message: str  # what the scanner reads: the wallet-pass credential token
    holder_name: str
    organization_name: str
    description: str
    primary_color: str | None = None


@dataclass(frozen=True)
class BuiltPass:
    format: str  # "fake" now; "pkpass" or "google_jwt" for the real issuers
    media_type: str
    content: str  # the pass document (JSON here, base64 for a pkpass)
    signed: bool


class WalletPassIssuer(Protocol):
    name: str

    def build(self, content: PassContent) -> BuiltPass: ...


_issuer: WalletPassIssuer | None = None


def configure(issuer: WalletPassIssuer) -> None:
    global _issuer
    _issuer = issuer


def build(content: PassContent) -> BuiltPass:
    assert _issuer is not None, "no wallet pass adapter configured"
    return _issuer.build(content)
