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


def render(columns: list[dict], rows: list[dict], *, currency: str) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(f"{c['label']} ({currency})" if c["type"] == "money" else c["label"] for c in columns)
    for row in rows:
        writer.writerow(cell(row.get(c["key"]), c["type"]) for c in columns)
    return ("﻿" + out.getvalue()).encode()
