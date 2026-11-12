"""CSV in and out, and the strict cell parsers. Pure functions: no database, no clock.

Reading accepts UTF-8 with or without a byte-order mark and nothing else (no guessing of legacy encodings).
Writing always neutralises cells a spreadsheet would run as a formula, whatever their origin.
"""

import csv
import io
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.core.errors import ValidationFailed

BOM = "﻿"
MAX_ROWS = 20_000
_FORMULA = ("=", "+", "-", "@", "\t", "\r")
_MONEY = re.compile(r"^\d{1,9}(\.\d{1,2})?$")  # shortcut: two-decimal currencies only; add an exponent per currency
_EMAIL = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")
_DATES = {"iso": (r"^(\d{4})-(\d{2})-(\d{2})$", (0, 1, 2)), "mdy": (r"^(\d{2})/(\d{2})/(\d{4})$", (2, 0, 1)),
          "dmy": (r"^(\d{2})/(\d{2})/(\d{4})$", (2, 1, 0))}  # fmt: skip
DATE_HINT = {"iso": "YYYY-MM-DD", "mdy": "MM/DD/YYYY", "dmy": "DD/MM/YYYY"}
_TRUE, _FALSE = {"yes", "y", "true", "1"}, {"no", "n", "false", "0"}


class CellError(ValueError):
    """A cell that does not parse: `code` for machines, the message in plain words (never quoting the cell)."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code, self.detail = code, detail


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    required: bool
    help: str
    example: str


# --- reading -----------------------------------------------------------------------------------------------------


def decode(raw: bytes) -> str:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ValidationFailed(
            "The file is not UTF-8 text. In your spreadsheet choose Save As, CSV UTF-8, and upload that file.",
            code="file-not-utf8",
        ) from None
    if "\x00" in text:
        raise ValidationFailed("The file is not a text CSV file.", code="file-type-mismatch")
    return text.removeprefix(BOM)


def read(text: str) -> tuple[list[str], list[list[str]]]:
    """(headers, records). Records keep their position, so record i is spreadsheet row i + 2; blank records stay
    in the list as [] and are ignored by the caller."""
    try:
        rows = list(csv.reader(io.StringIO(text, newline="")))
    except csv.Error:
        raise ValidationFailed("The file could not be read as CSV.", code="file-not-csv") from None
    if not rows or not any(cell.strip() for cell in rows[0]):
        raise ValidationFailed("The first row must hold the column names.", code="file-no-header")
    headers = [cell.strip() for cell in rows[0]]
    named = [h for h in headers if h]
    if len(set(h.lower() for h in named)) != len(named):
        raise ValidationFailed(
            "Two columns have the same name. Rename one and upload again.", code="file-duplicate-header"
        )
    records = [row if any(cell.strip() for cell in row) else [] for row in rows[1:]]
    while records and not records[-1]:
        records.pop()
    if len(records) > MAX_ROWS:
        raise ValidationFailed(f"A file may hold at most {MAX_ROWS} rows. Split it and import each part.",
                               code="file-too-many-rows")  # fmt: skip
    return headers, records


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def auto_map(headers: list[str], fields: list[Field]) -> dict[str, str]:
    """Our field key -> source header, matching the key or the label without case or punctuation."""
    by_name = {_norm(h): h for h in headers if h}
    found = {}
    for field in fields:
        header = by_name.get(field.key) or by_name.get(_norm(field.label))
        if header is not None:
            found[field.key] = header
    return found


def check_mapping(mapping: dict[str, str], headers: list[str], fields: list[Field]) -> None:
    keys = {f.key for f in fields}
    for key, header in mapping.items():
        if key not in keys:
            raise ValidationFailed("Unknown field.", pointer=f"/column_mapping/{key}")
        if header not in headers:
            raise ValidationFailed("The file has no column with this name.", pointer=f"/column_mapping/{key}")
    if len(set(mapping.values())) != len(mapping):
        raise ValidationFailed("A column is mapped to two fields.", pointer="/column_mapping")
    for field in fields:
        if field.required and field.key not in mapping:
            raise ValidationFailed(f"Choose the column that holds {field.label}.", pointer=f"/column_mapping/{field.key}",
                                   code="mapping-incomplete")  # fmt: skip


def values(record: list[str], headers: list[str], mapping: dict[str, str]) -> dict[str, str]:
    """Our field key -> the stripped cell ('' when missing)."""
    index = {h: i for i, h in enumerate(headers)}
    return {key: (record[index[h]].strip() if index[h] < len(record) else "") for key, h in mapping.items()}


# --- cells -------------------------------------------------------------------------------------------------------


def text(value: str, max_length: int = 200) -> str | None:
    if not value:
        return None
    if len(value) > max_length:
        raise CellError("too-long", f"Use at most {max_length} characters.")
    return value


def email(value: str) -> str | None:
    if not value:
        return None
    if len(value) > 254 or not _EMAIL.match(value):
        raise CellError("invalid-email", "This is not an email address.")
    return value.lower()


def day(value: str, fmt: str) -> date | None:
    if not value:
        return None
    pattern, order = _DATES[fmt]
    match = re.match(pattern, value)
    if match is None:
        raise CellError("invalid-date", f"Write dates as {DATE_HINT[fmt]}.")
    parts = [int(p) for p in match.groups()]
    try:
        return date(parts[order[0]], parts[order[1]], parts[order[2]])
    except ValueError:
        raise CellError("invalid-date", "This date does not exist.") from None


def money(value: str) -> int | None:
    """Minor units from a plain decimal (12, 12.5, 12.50): no currency sign, thousands separator or minus."""
    if not value:
        return None
    if not _MONEY.match(value):
        raise CellError("invalid-amount", "Write amounts as a plain number such as 1234.50, without a currency sign.")
    return int(Decimal(value) * 100)


def flag(value: str) -> bool | None:
    if not value:
        return None
    lowered = value.lower()
    if lowered in _TRUE or lowered in _FALSE:
        return lowered in _TRUE
    raise CellError("invalid-yes-no", "Write yes or no.")


def whole(value: str, *, low: int = 0, high: int = 10_000_000) -> int | None:
    if not value:
        return None
    if not re.match(r"^\d+$", value) or not low <= int(value) <= high:
        raise CellError("invalid-number", f"Write a whole number from {low} to {high}.")
    return int(value)


def choice(value: str, allowed: tuple[str, ...]) -> str | None:
    if not value:
        return None
    if value.lower() not in allowed:
        raise CellError("invalid-choice", f"Use one of: {', '.join(allowed)}.")
    return value.lower()


# --- writing -----------------------------------------------------------------------------------------------------


def safe(cell) -> str:
    """A cell a spreadsheet will show as text: a leading apostrophe on anything that would start a formula."""
    value = "" if cell is None else str(cell)
    return "'" + value if value.startswith(_FORMULA) else value


def write(rows: list[list]) -> bytes:
    out = io.StringIO()
    csv.writer(out, lineterminator="\r\n").writerows([[safe(cell) for cell in row] for row in rows])
    return (BOM + out.getvalue()).encode()
