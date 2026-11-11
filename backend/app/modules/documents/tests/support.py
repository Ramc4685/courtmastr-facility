"""Shared helpers for the documents tests: a location, published templates, issued documents, signatures."""

import base64
import io
from datetime import date, timedelta
from uuid import uuid4

from PIL import Image

from app.core import clock

API = "/api/v1"
BODY = "<p>I, {{client.full_name}}, accept the risks at {{location.name}}.</p>"


def ok(response, status: int = 200):
    assert response.status_code == status, response.text
    return response.json() if response.content else None


def location(client, headers) -> str:
    body = {"name": "Main", "time_zone": "America/Chicago", "country_code": "US"}
    return ok(client.post(f"{API}/locations", headers=headers, json=body), 201)["id"]


def template(client, headers, *, body: str = BODY, blocks=None, **fields) -> dict:
    """A template with one published version."""
    created = ok(client.post(f"{API}/document-templates", headers=headers,
                             json={"name": f"Waiver {uuid4().hex[:6]}", "is_waiver": True} | fields), 201)  # fmt: skip
    draft = {"body_html": body, "acceptance_text": "I have read and agree."}
    if blocks is not None:
        draft["signature_blocks"] = blocks
    ok(client.put(f"{API}/document-templates/{created['id']}/draft", headers=headers, json=draft))
    return ok(client.post(f"{API}/document-templates/{created['id']}/publish", headers=headers))


def issue(client, headers, person: dict, location_id: str, template_id: str | None, method="checkbox", **extra):
    body = {"client_id": person["id"], "location_id": location_id, "template_id": template_id,
            "acceptance_method": method} | extra  # fmt: skip
    return ok(client.post(f"{API}/client-documents", headers=headers, json=body), 201)


def signer(role="client", decision="accepted", **extra) -> dict:
    return {"decision": decision, "signer_role": role, "signer_name": "Sam Signer", "method": "typed_name",
            "typed_signature": "Sam Signer"} | extra  # fmt: skip


def sign(client, headers, doc: dict, *signers, user_agent: str | None = None):
    body = {"content_sha256": doc["content_sha256"], "signers": list(signers) or [signer()]}
    headers = headers | ({"User-Agent": user_agent} if user_agent else {})
    return client.post(f"{API}/client-documents/{doc['id']}/acceptances", headers=headers, json=body)


def png(size=(120, 40)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, "white").save(out, "PNG")
    return out.getvalue()


def png_b64() -> str:
    return "data:image/png;base64," + base64.b64encode(png()).decode()


def today() -> date:
    return clock.now().date()


def born(years: int) -> str:
    """A birth date `years` (and a few days) ago."""
    return str(today() - timedelta(days=365 * years + years // 4 + 5))
