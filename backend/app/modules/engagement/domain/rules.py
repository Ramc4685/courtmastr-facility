"""Pure engagement rules: merge fields, the delivery state machine, audience definitions, video links and
reminder times. No database, no clock: callers pass `now`."""

import re
from datetime import datetime, timedelta
from string import Template
from urllib.parse import urlparse

# The one merge-field catalogue (data model 3.3 keeps one per system key; one shared list is enough for v1).
MERGE_FIELDS = frozenset({
    "first_name", "last_name", "full_name", "facility_name", "location_name", "title", "starts_at",
})  # fmt: skip
_FIELD = re.compile(r"\$(?:(\w+)|\{(\w+)\})")


def unknown_fields(*texts: str | None) -> list[str]:
    """Merge fields used in the texts that are not in the catalogue, sorted."""
    used = {a or b for text in texts if text for a, b in _FIELD.findall(text)}
    return sorted(used - MERGE_FIELDS)


def render(text: str | None, data: dict) -> str:
    """Substitute merge fields; a field with no value renders empty (validated on save, so never unknown)."""
    if not text:
        return ""
    return Template(text).safe_substitute({field: data.get(field) or "" for field in MERGE_FIELDS})


# Delivery state machine (data model 3.7): forward only along the happy path; terminal side exits.
_RANK = {"queued": 0, "sent": 1, "delivered": 2, "opened": 3, "clicked": 4}
_EVENT_STATUS = {
    "delivered": "delivered", "open": "opened", "click": "clicked", "bounce": "bounced",
    "complaint": "complained", "failed": "failed",
}  # fmt: skip
TERMINAL = frozenset({"bounced", "complained", "failed", "skipped"})


def advance(status: str, event_type: str) -> str:
    """The message status after a provider event. Out-of-order or repeated events never move it back."""
    target = _EVENT_STATUS.get(event_type)
    if target is None or status in TERMINAL:
        return status
    if target in TERMINAL:
        return target
    return target if _RANK[target] > _RANK[status] else status


# Audience definitions (data model 3.5), v1 subset.
SOURCES = frozenset({"all_clients", "client_ids", "tag"})
FILTERS = frozenset({"member", "birth_month", "gender", "age_range", "home_location"})
GENDERS = frozenset({"female", "male", "non_binary", "undisclosed"})


def check_definition(definition: dict) -> list[tuple[str, str]]:
    """Problems with an audience definition as (pointer, message); empty when valid."""
    problems: list[tuple[str, str]] = []
    sources = definition.get("sources")
    if not isinstance(sources, list) or not sources:
        return [("/sources", "Choose at least one source.")]
    for i, source in enumerate(sources):
        kind = source.get("kind") if isinstance(source, dict) else None
        if kind not in SOURCES:
            problems.append((f"/sources/{i}/kind", "Unknown source."))
        elif kind in ("client_ids", "tag") and not (isinstance(source.get("ids"), list) and source["ids"]):
            problems.append((f"/sources/{i}/ids", "List at least one id."))
    for i, flt in enumerate(definition.get("filters") or []):
        kind = flt.get("kind") if isinstance(flt, dict) else None
        if kind not in FILTERS:
            problems.append((f"/filters/{i}/kind", "Unknown filter."))
        elif kind == "birth_month" and not all(isinstance(m, int) and 1 <= m <= 12 for m in flt.get("months") or [0]):
            problems.append((f"/filters/{i}/months", "Months are 1 to 12."))
        elif kind == "gender" and not set(flt.get("values") or ["?"]) <= GENDERS:
            problems.append((f"/filters/{i}/values", "Unknown gender value."))
        elif kind == "age_range":
            low, high = flt.get("min"), flt.get("max")
            if not all(v is None or (isinstance(v, int) and 0 <= v <= 120) for v in (low, high)) or (
                low is not None and high is not None and low > high
            ):
                problems.append((f"/filters/{i}", "Ages are 0 to 120 and min is at most max."))
        elif kind == "home_location" and not (isinstance(flt.get("ids"), list) and flt["ids"]):
            problems.append((f"/filters/{i}/ids", "List at least one location."))
    return problems


def age_on(birth_on, on) -> int:
    return on.year - birth_on.year - ((on.month, on.day) < (birth_on.month, birth_on.day))


# Videos (SSP-16): links to hosts we know how to embed, https only.
VIDEO_HOSTS = frozenset({"www.youtube.com", "youtube.com", "youtu.be", "vimeo.com", "player.vimeo.com"})


def is_allowed_video_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and parsed.hostname in VIDEO_HOSTS and not parsed.username and not parsed.port


def is_https_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username


def reminder_times(starts_at: datetime, offsets: list[int | None], now: datetime) -> list[tuple[int, datetime]]:
    """(reminder number, send time) for each configured offset still in the future."""
    out = []
    for number, minutes in enumerate(offsets, start=1):
        if minutes:
            send_at = starts_at - timedelta(minutes=minutes)
            if send_at > now:
                out.append((number, send_at))
    return out
