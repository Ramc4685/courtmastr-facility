"""Template content: the rich-text allow-list (security-baseline 9.2), merge fields and the evidence hash.

Merge fields are fixed tokens such as `{{client.first_name}}` replaced by escaped values; there is no template
language and no server-side evaluation of tenant text (security-baseline 9.4). Unknown tokens are refused when the
draft is saved, so a published version can always be rendered.
"""

import hashlib
import html
import re
from collections.abc import Mapping

import nh3

SANITIZER_VERSION = 1
TAGS = {
    "h1", "h2", "h3", "h4", "p", "br", "hr", "strong", "b", "em", "i", "u", "blockquote", "ul", "ol", "li", "a",
    "table", "thead", "tbody", "tr", "th", "td",
}  # fmt: skip
ATTRIBUTES = {"a": {"href", "title"}, "th": {"colspan", "rowspan"}, "td": {"colspan", "rowspan"}}
# Images are left out until there is a file origin to allow (9.2): nothing here can fetch a URL.
URL_SCHEMES = {"https", "mailto", "tel"}

MERGE_FIELDS = {
    "client.first_name": "Client first name",
    "client.last_name": "Client last name",
    "client.full_name": "Client full name",
    "client.member_number": "Member number",
    "client.birth_date": "Client birth date",
    "location.name": "Location name",
    "organization.name": "Organization name",
    "document.date": "Date issued",
}
_TOKEN = re.compile(r"\{\{\s*([a-z_]+\.[a-z_]+)\s*\}\}")


def sanitize(body: str) -> str:
    return nh3.clean(
        body, tags=TAGS, attributes=ATTRIBUTES, url_schemes=URL_SCHEMES, link_rel="noopener noreferrer nofollow"
    ).strip()


def unknown_fields(*texts: str) -> list[str]:
    return sorted({m for text in texts for m in _TOKEN.findall(text) if m not in MERGE_FIELDS})


def merge(text: str, values: Mapping[str, str | None], *, escape: bool) -> str:
    """Replace every known token; a missing value renders as an empty string."""

    def value(match: re.Match) -> str:
        found = values.get(match[1]) or ""
        return html.escape(found) if escape else found

    return _TOKEN.sub(value, text)


def content_hash(body_html: str, acceptance_text: str) -> str:
    """Hex SHA-256 over body_html || '\\n' || acceptance_text (data-model 2.2)."""
    return hashlib.sha256(f"{body_html}\n{acceptance_text}".encode()).hexdigest()
