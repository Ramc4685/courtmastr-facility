"""Wallet pass adapters (app.ports.wallet_pass). Only the fake one until issuer certificates exist (CHK-13 partial)."""

import json

from app.ports.wallet_pass import BuiltPass, PassContent


class FakeWalletPass:
    """Builds an unsigned pass document shaped like a generic Wallet pass: enough for the app to show the barcode."""

    name = "fake"

    def build(self, content: PassContent) -> BuiltPass:
        document = {
            "format_version": 1,
            "serial_number": content.serial,
            "organization_name": content.organization_name,
            "description": content.description,
            "holder_name": content.holder_name,
            "background_color": content.primary_color,
            "barcode": {"format": "qr", "message": content.barcode_message, "encoding": "utf-8"},
            "signed": False,
        }
        return BuiltPass(format="fake", media_type="application/json", content=json.dumps(document), signed=False)
