"""A small PDF engine for printable business documents (invoices, receipts, statements, Phase 12 reports).

    doc = Document("Invoice 12", organization="Courtside", subtitle="Bill to: Ana Ruiz")
    doc.fields([("Due", "2026-12-01")]); doc.table([Column("Item"), Column("Total", 30, "R")], rows)
    data = doc.output()  # bytes, identical for identical input

Output is deterministic and uncompressed (fixed creation date, no random ids), so tests can assert the text in
the bytes. Every value is placed as plain text: the engine reads no file, URL or markup.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from fpdf import FPDF

_EPOCH = datetime(2000, 1, 1, tzinfo=UTC)
_log = logging.getLogger(__name__)
# shortcut: the built-in PDF fonts cover Latin-1 only; other characters print as "?". Embed a Unicode TTF font
# when a tenant needs non-Latin scripts.
_ASCII = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "…": "...",
                        "•": "*", " ": " "})  # fmt: skip


def latin(text: object) -> str:
    plain = str(text).translate(_ASCII)
    out = plain.encode("latin-1", "replace").decode("latin-1")
    if out != plain:
        _log.warning(
            "pdf: %d character(s) outside Latin-1 printed as '?'", sum(a != b for a, b in zip(plain, out, strict=True))
        )
    return out


def money(amount_minor: int, currency: str) -> str:
    """12345, "USD" -> "123.45 USD". Exact (no float); minus sign for negatives."""
    # shortcut: assumes a two-decimal currency, so zero-decimal ones (JPY, KRW, VND, CLP) and three-decimal ones
    # (BHD, KWD) print wrongly; use the tenant locale formatter when such a tenant exists.
    return f"{Decimal(amount_minor).scaleb(-2):,.2f} {currency}"


def local_date(value: date | datetime | None, zone: str | None = None) -> str:
    """A calendar date as ISO text; an instant is first moved to the IANA zone (UTC when none is given)."""
    if value is None:
        return "-"
    if isinstance(value, datetime):
        value = value.astimezone(ZoneInfo(zone or "UTC")).date()
    return value.isoformat()


@dataclass(frozen=True)
class Column:
    title: str
    width: float = 0  # millimetres; 0 shares what the fixed columns leave
    align: str = "L"  # L, R or C


class Document:
    """One Letter-size document: a header with the organisation and title on page one, a footer with the
    organisation and page number on every page, then whatever blocks the caller adds in order."""

    def __init__(self, title: str, *, organization: str, subtitle: str | None = None, footer: str | None = None):
        self._footer = latin(footer) if footer else None
        org = latin(organization)

        class _Page(FPDF):
            def footer(page) -> None:  # noqa: N805 (fpdf2 hook on the page object)
                page.set_y(-14)
                page.set_font("Helvetica", "", 8)
                page.cell(0, 5, f"{org} - page {page.page_no()}", align="C")

        pdf = _Page(format="Letter")
        pdf.set_compression(False)
        pdf.set_creation_date(_EPOCH)
        pdf.set_title(latin(title))
        pdf.set_creator(org)
        pdf.set_auto_page_break(auto=True, margin=20)
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 5, org, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "B", 16)
        pdf.multi_cell(0, 8, latin(title), new_x="LMARGIN", new_y="NEXT")
        if subtitle:
            pdf.set_font("Helvetica", "", 10)
            pdf.multi_cell(0, 5, latin(subtitle), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)
        self._pdf = pdf
        self._done = False

    def heading(self, text: str) -> "Document":
        self._pdf.ln(2)
        self._pdf.set_font("Helvetica", "B", 11)
        self._pdf.multi_cell(0, 6, latin(text), new_x="LMARGIN", new_y="NEXT")
        return self

    def text(self, text: str, *, size: int = 10) -> "Document":
        self._pdf.set_font("Helvetica", "", size)
        self._pdf.multi_cell(0, 5, latin(text), new_x="LMARGIN", new_y="NEXT")
        return self

    def fields(self, pairs: Sequence[tuple[str, object]]) -> "Document":
        """Label and value lines, such as number, dates and totals."""
        for label, value in pairs:
            self._pdf.set_font("Helvetica", "B", 10)
            self._pdf.cell(45, 5, latin(label))
            self._pdf.set_font("Helvetica", "", 10)
            self._pdf.multi_cell(0, 5, latin(value), new_x="LMARGIN", new_y="NEXT")
        return self

    def table(self, columns: Sequence[Column], rows: Sequence[Sequence[object]], *, empty: str = "None.") -> "Document":
        """A header row and one row per item; the header repeats on a new page. Long cells are clipped to the
        column, so every row keeps one line."""
        pdf = self._pdf
        fixed = sum(c.width for c in columns)
        flexible = [c for c in columns if not c.width]
        share = (pdf.epw - fixed) / len(flexible) if flexible else 0
        widths = [c.width or share for c in columns]

        def header() -> None:
            pdf.set_font("Helvetica", "B", 9)
            for column, width in zip(columns, widths, strict=True):
                pdf.cell(width, 6, latin(column.title), border="B", align=column.align)
            pdf.ln()
            pdf.set_font("Helvetica", "", 9)

        pdf.ln(1)
        header()
        if not rows:
            pdf.cell(0, 6, latin(empty), new_x="LMARGIN", new_y="NEXT")
        for row in rows:
            if pdf.will_page_break(6):
                pdf.add_page()
                header()
            for column, width, value in zip(columns, widths, row, strict=True):
                text = latin(value if value is not None else "")
                if pdf.get_string_width(text) > width - 2:
                    while text and pdf.get_string_width(text + "...") > width - 2:
                        text = text[:-1]
                    text += "..."
                pdf.cell(width, 6, text, align=column.align)
            pdf.ln()
        pdf.ln(2)
        return self

    def output(self) -> bytes:
        """The finished bytes; a document is output once (a second call would repeat the footer text)."""
        if self._done:
            raise RuntimeError("Document.output() was already called")
        self._done = True
        if self._footer:
            self.text(self._footer, size=8)
        return bytes(self._pdf.output())
