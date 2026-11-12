"""CSV rendering of a report snapshot (ADR 0010 section 5): UTF-8 with BOM, RFC 4180 quoting, the column labels
as the header row, ISO dates, money as a plain decimal in major units (currency in the money headers, never in
cells), and a leading apostrophe on any text cell a spreadsheet would read as a formula."""

import csv
import io
from decimal import Decimal

_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def cell(value, kind: str, exponent: int = 2) -> str:
    if value is None:
        return ""
    if kind == "money":
        return str((Decimal(int(value)) / (10**exponent)).quantize(Decimal(1).scaleb(-exponent)))
    if isinstance(value, bool):
        return "yes" if value else "no"
    text = str(value)
    if kind not in ("count", "pct", "minutes", "number") and text.startswith(_FORMULA):
        return "'" + text
    return text


BOM = "﻿".encode()


def header(columns: list[dict], *, currency: str) -> bytes:
    return _lines([[f"{c['label']} ({currency})" if c["type"] == "money" else c["label"] for c in columns]])


def body(columns: list[dict], rows: list[dict]) -> bytes:
    """Data lines only, so a chunked export can append rows to what earlier chunks rendered."""
    return _lines([cell(row.get(c["key"]), c["type"]) for c in columns] for row in rows)


def render(columns: list[dict], rows: list[dict], *, currency: str) -> bytes:
    return BOM + header(columns, currency=currency) + body(columns, rows)


def _lines(rows) -> bytes:
    out = io.StringIO()
    csv.writer(out, lineterminator="\r\n").writerows(rows)
    return out.getvalue().encode()
