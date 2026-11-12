"""The shared PDF engine (app/core/pdf.py): deterministic text, Latin-1 fallback, clipping, page breaks."""

import logging

import pytest

from app.core import pdf


def _doc(**over) -> pdf.Document:
    return pdf.Document("Invoice 12", organization="Courtside", **over)


def test_output_is_deterministic_and_carries_the_text():
    def build() -> bytes:
        doc = _doc(subtitle="Bill to: Ana Ruiz", footer="Thank you")
        doc.fields([("Due", "2026-12-01")]).table(
            [pdf.Column("Item"), pdf.Column("Total", 30, "R")], [("Court", "25.00")]
        )
        return doc.output()

    first = build()
    assert first.startswith(b"%PDF-") and first == build()
    for text in (b"Invoice 12", b"Bill to: Ana Ruiz", b"Court", b"Thank you", b"Courtside - page 1"):
        assert text in first


def test_a_document_is_output_once():
    doc = _doc(footer="Footer")
    doc.output()
    with pytest.raises(RuntimeError):
        doc.output()


def test_characters_outside_latin1_print_as_question_marks_and_warn(caplog):
    assert pdf.latin("Café – “ok”") == 'Café - "ok"'  # Latin-1 and the mapped punctuation pass quietly
    with caplog.at_level(logging.WARNING, logger="app.core.pdf"):
        assert pdf.latin("Zoë 東京") == "Zoë ??"
    assert "2 character(s)" in caplog.text and "東京" not in caplog.text  # the count, never the text


def test_long_cells_are_clipped_with_an_ellipsis():
    doc = _doc()
    doc.table([pdf.Column("Item", 30), pdf.Column("Total", 30, "R")], [("A very long description of the item", "1.00")])
    data = doc.output()
    assert b"..." in data and b"description of the item" not in data


def test_a_long_table_breaks_pages_and_repeats_its_header():
    doc = _doc()
    doc.table([pdf.Column("Item"), pdf.Column("Total", 30, "R")], [(f"Line {n}", "1.00") for n in range(120)])
    data = doc.output()
    assert b"Courtside - page 3" in data
    assert data.count(b"(Item)") >= 3  # the header on every page
    assert b"Line 119" in data


def test_money_is_exact_with_a_minus_sign_and_dates_are_local():
    from datetime import UTC, datetime

    assert pdf.money(1234567, "USD") == "12,345.67 USD"
    assert pdf.money(-505, "USD") == "-5.05 USD"
    assert pdf.money(0, "EUR") == "0.00 EUR"
    late = datetime(2026, 11, 11, 5, 30, tzinfo=UTC)
    assert (pdf.local_date(late, "America/Chicago"), pdf.local_date(late)) == ("2026-11-10", "2026-11-11")
    assert pdf.local_date(None) == "-"
