"""XLSX and PDF renderings of a report snapshot (ADR 0010 section 5), through the shared engines `core.xlsx` and
`core.pdf`. Both take the same inputs: the snapshot (columns, rows, details), the cover lines (report,
parameters, date basis), and the totals as (label, type, value). XLSX has one sheet per section with typed cells;
PDF lists at most PDF_DETAIL_ROWS detail rows and says so when it leaves the rest out (CSV and XLSX carry them)."""

from collections.abc import Sequence

from app.core import pdf, xlsx

PDF_DETAIL_ROWS = 5_000
NUMERIC = ("money", "count", "number", "pct", "minutes")
Total = tuple[str, str, object]


def _label(column: dict, currency: str) -> str:
    return f"{column['label']} ({currency})" if column["type"] == "money" else column["label"]


def _values(columns: list[dict], rows: list[dict]):
    return ([row.get(c["key"]) for c in columns] for row in rows)


def to_xlsx(snapshot: dict, cover: Sequence[tuple[str, object]], totals: Sequence[Total], *, details: bool,
            currency: str) -> bytes:  # fmt: skip
    sheets = [xlsx.Sheet("Summary", [xlsx.Column(_label(c, currency), c["type"]) for c in snapshot["columns"]],
                         _values(snapshot["columns"], snapshot["rows"]))]  # fmt: skip
    if totals:
        sheets.append(xlsx.Sheet(
            "Totals", [xlsx.Column(f"{label} ({currency})" if kind == "money" else label, kind)
                       for label, kind, _ in totals], [[value for _, _, value in totals]],
        ))  # fmt: skip
    if details and snapshot["details"]:
        columns = snapshot["detail_columns"]
        sheets.append(xlsx.Sheet("Details", [xlsx.Column(_label(c, currency), c["type"]) for c in columns],
                                 _values(columns, snapshot["details"])))  # fmt: skip
    return xlsx.workbook(cover, sheets)


def _text(value: object, kind: str, currency: str) -> str:
    if value is None or value == "":
        return ""
    if kind == "money":
        return pdf.money(int(str(value)), currency)
    if kind == "pct":
        return f"{value}%"
    if kind == "bool" or isinstance(value, bool):
        return "yes" if value else "no"
    return str(value).replace("_", " ") if kind == "text" else str(value)


def _table(doc: pdf.Document, columns: list[dict], rows: list[dict], currency: str) -> None:
    doc.table(
        [pdf.Column(c["label"], align="R" if c["type"] in NUMERIC else "L") for c in columns],
        [[_text(row.get(c["key"]), c["type"], currency) for c in columns] for row in rows],
        empty="Nothing matched these parameters.",
    )


def to_pdf(snapshot: dict, cover: Sequence[tuple[str, object]], totals: Sequence[Total], *, title: str,
           organization: str, details: bool, currency: str, page_size: str | None, orientation: str | None) -> bytes:  # fmt: skip
    """One document: the cover lines, the totals, the summary table, then the detail rows when asked for. Wide
    reports (more than six columns) default to landscape."""
    widest = max(len(snapshot["columns"]), len(snapshot["detail_columns"] or []) if details else 0)
    doc = pdf.Document(
        title, organization=organization, page_size="A4" if page_size == "a4" else "Letter",
        orientation=orientation or ("landscape" if widest > 6 else "portrait"),
    )  # fmt: skip
    doc.fields(cover)
    if totals:
        doc.heading("Totals").fields([(label, _text(value, kind, currency) or "-") for label, kind, value in totals])
    doc.heading("Summary")
    _table(doc, snapshot["columns"], snapshot["rows"], currency)
    if details and snapshot["details"]:
        rows = snapshot["details"]
        doc.heading("Details")
        if len(rows) > PDF_DETAIL_ROWS:
            doc.text(f"{len(rows):,} detail rows is more than a PDF lists ({PDF_DETAIL_ROWS:,}): export CSV or XLSX "
                     "for the detail rows.")  # fmt: skip
        else:
            _table(doc, snapshot["detail_columns"], rows, currency)
    return doc.output()
