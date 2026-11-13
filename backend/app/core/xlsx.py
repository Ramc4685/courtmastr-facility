"""The one spreadsheet writer (ADR 0010 section 5): openpyxl in write-only (streaming) mode.

    data = workbook([("Report", "Revenue"), ("From", "2026-01-01")],
                    [Sheet("Summary", [Column("Category"), Column("Net", "money")], [["Courts", 12345]])])

A cover sheet holds the label and value pairs, then one sheet per section with a frozen header row. Cells are
typed: money (minor units in, a decimal in major units out), counts and numbers, percentages, dates (a `date` or
an ISO string) and yes/no. Text is always stored as text, never as a formula, so a cell starting with "=" cannot
run in the reader's spreadsheet. A sheet over MAX_ROWS rows raises TooLarge before anything is returned.
"""

import io
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.cell.cell import Cell
from openpyxl.styles import Font
from openpyxl.worksheet._write_only import WriteOnlyWorksheet

MAX_ROWS = 1_000_000  # data rows per sheet; Excel's own limit is 1,048,576 rows
_FORMATS = {"money": "#,##0.00", "count": "#,##0", "minutes": "#,##0", "number": "#,##0.##", "pct": "0.0",
            "date": "yyyy-mm-dd"}  # fmt: skip
_BAD_TITLE = str.maketrans({c: " " for c in "[]:*?/\\"})


class TooLarge(ValueError):
    """A sheet has more rows than the format allows; export as CSV instead."""


@dataclass(frozen=True)
class Column:
    title: str
    kind: str = "text"  # text, money, count, number, pct, minutes, date, bool


@dataclass(frozen=True)
class Sheet:
    title: str
    columns: Sequence[Column]
    rows: Iterable[Sequence[object]]


def _value(value: object, kind: str, exponent: int) -> object:
    if value is None or value == "":
        return None
    if kind == "money":
        return Decimal(int(str(value))).scaleb(-exponent)
    if kind in ("count", "minutes"):
        return int(str(value))
    if kind in ("number", "pct"):
        return Decimal(str(value))
    if kind == "date":
        return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
    if kind == "bool" or isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _cell(sheet: WriteOnlyWorksheet, value: object, kind: str, exponent: int) -> Cell:
    typed = _value(value, kind, exponent)
    cell = WriteOnlyCell(sheet, value=typed)
    if isinstance(typed, str):
        cell.data_type = "s"  # openpyxl would read a leading "=" as a formula
    elif kind in _FORMATS:
        cell.number_format = _FORMATS[kind]
    return cell


def _header(sheet: WriteOnlyWorksheet, titles: Sequence[str]) -> list[Cell]:
    cells = []
    for title in titles:
        cell = WriteOnlyCell(sheet, value=title)
        cell.data_type, cell.font = "s", Font(bold=True)
        cells.append(cell)
    return cells


def workbook(cover: Sequence[tuple[str, object]], sheets: Sequence[Sheet], *, exponent: int = 2) -> bytes:
    """The finished .xlsx bytes: a cover sheet, then each section in order."""
    book = Workbook(write_only=True)
    first = book.create_sheet("Cover")
    for label, value in cover:
        first.append([_cell(first, label, "text", exponent), _cell(first, value, "text", exponent)])
    used = {"cover"}
    for section in sheets:
        title = section.title.translate(_BAD_TITLE)[:31] or "Sheet"
        while title.lower() in used:
            title = f"{title[:28]} {len(used)}"
        used.add(title.lower())
        sheet = book.create_sheet(title)
        sheet.freeze_panes = "A2"
        sheet.append(_header(sheet, [c.title for c in section.columns]))
        for count, row in enumerate(section.rows, start=1):
            if count > MAX_ROWS:
                raise TooLarge(f"More than {MAX_ROWS:,} rows in one sheet: export as CSV instead")
            sheet.append([_cell(sheet, v, c.kind, exponent) for c, v in zip(section.columns, row, strict=True)])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()
