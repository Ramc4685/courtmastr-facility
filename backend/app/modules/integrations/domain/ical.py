"""iCalendar (RFC 5545) text for the one-way calendar feeds: VEVENTs in UTC, escaped and folded."""

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class Event:
    uid: str
    starts_at: datetime
    ends_at: datetime
    summary: str
    description: str = ""
    cancelled: bool = False
    updated_at: datetime | None = None  # the record's last change: LAST-MODIFIED, and a stable DTSTAMP


def escape(value: str) -> str:
    """TEXT escaping (RFC 5545 section 3.3.11): backslash, semicolon, comma and line breaks."""
    out = value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return out.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")


def fold(line: str) -> str:
    """Lines longer than 75 octets continue on the next line after CRLF and one space, never mid-character."""
    out: list[str] = []
    current = b""
    for char in line:
        encoded = char.encode()
        if len(current) + len(encoded) > (75 if not out else 74):
            out.append(current.decode())
            current = b""
        current += encoded
    out.append(current.decode())
    return "\r\n ".join(out)


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def calendar(name: str, events: list[Event], now: datetime) -> str:
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Courtmastr Facility//Calendar feed//EN", "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH", f"X-WR-CALNAME:{escape(name)}", "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
    ]  # fmt: skip
    for event in sorted(events, key=lambda e: (e.starts_at, e.uid)):
        lines += [
            "BEGIN:VEVENT", f"UID:{event.uid}", f"DTSTAMP:{_stamp(event.updated_at or event.starts_at)}",
            f"DTSTART:{_stamp(event.starts_at)}", f"DTEND:{_stamp(event.ends_at)}", f"SUMMARY:{escape(event.summary)}",
        ]  # fmt: skip
        if event.updated_at is not None:
            lines.append(f"LAST-MODIFIED:{_stamp(event.updated_at)}")
        if event.description:
            lines.append(f"DESCRIPTION:{escape(event.description)}")
        lines += ["STATUS:CANCELLED" if event.cancelled else "STATUS:CONFIRMED", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "".join(fold(line) + "\r\n" for line in lines)
