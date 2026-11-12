"""The pure CSV helpers: strict encoding, strict cells, auto-mapping, and formula neutralising on the way out."""

from datetime import date

import pytest

from app.core.errors import ValidationFailed
from app.modules.imports import csvio
from app.modules.imports.csvio import CellError
from app.modules.imports.kinds import CLIENT_FIELDS


def test_decode_takes_utf8_with_or_without_a_bom_and_nothing_else():
    assert csvio.decode(b"a,b\r\n") == "a,b\r\n"
    assert csvio.decode(("﻿" + "café").encode()) == "café"
    with pytest.raises(ValidationFailed) as latin:
        csvio.decode("café".encode("latin-1"))
    assert latin.value.code == "file-not-utf8"
    with pytest.raises(ValidationFailed) as binary:
        csvio.decode(b"PK\x03\x04\x00\x00")
    assert binary.value.code == "file-type-mismatch"


def test_read_keeps_row_positions_and_refuses_bad_headers():
    headers, records = csvio.read("first_name,last_name\r\nA,B\r\n,\r\nC,D\r\n\r\n")
    assert headers == ["first_name", "last_name"] and records == [["A", "B"], [], ["C", "D"]]
    for text, code in [("", "file-no-header"), (",\r\nA,B", "file-no-header"), ("a,A\r\n1,2", "file-duplicate-header")]:
        with pytest.raises(ValidationFailed) as refused:
            csvio.read(text)
        assert refused.value.code == code
    with pytest.raises(ValidationFailed) as many:
        csvio.read("a\n" + "x\n" * (csvio.MAX_ROWS + 1))
    assert many.value.code == "file-too-many-rows"


def test_auto_map_and_mapping_checks():
    headers = ["First Name", "LAST_NAME", "E-mail", "Notes"]
    mapping = csvio.auto_map(headers, CLIENT_FIELDS)
    assert mapping == {"first_name": "First Name", "last_name": "LAST_NAME"}
    csvio.check_mapping(mapping | {"email": "E-mail"}, headers, CLIENT_FIELDS)
    for bad, pointer in [({"first_name": "First Name"}, "/column_mapping/last_name"),
                         (mapping | {"email": "Missing"}, "/column_mapping/email"),
                         (mapping | {"nope": "Notes"}, "/column_mapping/nope"),
                         (mapping | {"email": "First Name"}, "/column_mapping")]:  # fmt: skip
        with pytest.raises(ValidationFailed) as refused:
            csvio.check_mapping(bad, headers, CLIENT_FIELDS)
        assert refused.value.extra["errors"][0]["pointer"] == pointer


def test_cells_parse_strictly():
    assert csvio.day("2026-02-28", "iso") == date(2026, 2, 28)
    assert csvio.day("02/03/2026", "mdy") == date(2026, 2, 3) and csvio.day("02/03/2026", "dmy") == date(2026, 3, 2)
    assert csvio.money("12") == 1200 and csvio.money("12.5") == 1250 and csvio.money("0.07") == 7
    assert csvio.flag("Yes") is True and csvio.flag("0") is False and csvio.flag("") is None
    assert csvio.whole("48") == 48 and csvio.choice("Male", ("male",)) == "male"
    assert csvio.email("Sam@Example.com") == "sam@example.com"
    bad = [(csvio.day, ("2026-02-30", "iso")), (csvio.day, ("2026/02/03", "iso")), (csvio.day, ("3/2/2026", "mdy")),
           (csvio.money, ("$5",)), (csvio.money, ("1,000.00",)), (csvio.money, ("12.345",)), (csvio.money, ("-5",)),
           (csvio.flag, ("maybe",)), (csvio.whole, ("4.5",)), (csvio.email, ("nope",)), (csvio.text, ("x" * 201,)),
           (csvio.choice, ("x", ("a",)))]  # fmt: skip
    for parser, args in bad:
        with pytest.raises(CellError):
            parser(*args)


def test_written_cells_never_run_as_formulas():
    assert [csvio.safe(v) for v in ["=1+1", "+1", "-1", "@SUM(A1)", "\tx", "plain", None, 3]] == [
        "'=1+1", "'+1", "'-1", "'@SUM(A1)", "'\tx", "plain", "", "3"]  # fmt: skip
    out = csvio.write([["Row", "Problem"], [2, '=HYPERLINK("x")']])
    assert out.startswith("﻿".encode()) and b"'=HYPERLINK" in out and out.endswith(b"\r\n")


def test_read_cells_undo_our_neutralising_apostrophe_and_compose_accents():
    assert csvio.cell(csvio.safe("+13095550101")) == "+13095550101"  # the template round trip
    assert csvio.cell(" 'plain ") == "'plain" and csvio.cell("'") == "'"  # only our own apostrophe goes
    assert csvio.cell("José") == "José"
