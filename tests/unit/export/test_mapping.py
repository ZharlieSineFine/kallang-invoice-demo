"""Mapping engine tests: sources, formatting, truncation, and required columns."""

from datetime import date
from decimal import Decimal

import pytest

from invoiceflow.export.mapping import (
    RowContext,
    empty_required,
    format_cell_value,
    map_row,
    resolve_value,
)

EXPORT_DATE = date(2026, 11, 4)


def _ctx(mapping, clean_doc, **updates):
    values = dict(
        doc_id=clean_doc.doc_id,
        vendor=clean_doc.vendor,
        invoice=clean_doc.invoice,
        coding_line=clean_doc.coding_lines[0],
        export_date=EXPORT_DATE,
    )
    values.update(updates)
    return RowContext(**values)


def test_load_sap_mapping_shape(mapping):
    assert mapping.layout == "hypothetical"
    assert len(mapping.columns) == 16
    assert mapping.header[0] == "DocKey"
    assert mapping.header[-1] == "LineText"
    assert "LineText" in mapping.free_text_names


def test_const_source(mapping, clean_doc):
    company = next(c for c in mapping.columns if c.name == "CompanyCode")
    assert resolve_value(company.source, _ctx(mapping, clean_doc)) == "KG01"


def test_doc_id_source(mapping, clean_doc):
    doc_key = next(c for c in mapping.columns if c.name == "DocKey")
    assert resolve_value(doc_key.source, _ctx(mapping, clean_doc)) == clean_doc.doc_id


def test_date_formatting(mapping):
    assert format_cell_value(date(2026, 10, 15), mapping.date_format) == "15.10.2026"


def test_decimal_and_int_formatting(mapping):
    assert format_cell_value(Decimal("1177.20"), mapping.date_format) == "1177.20"
    assert format_cell_value(1, mapping.date_format) == "1"
    assert format_cell_value(None, mapping.date_format) == ""


def test_map_row_matches_golden(mapping, clean_doc):
    assert map_row(mapping, _ctx(mapping, clean_doc)) == (
        "93fe9312-fe79-50bb-b5e7-d18e83dfaff2",
        "KG01",
        "100014",
        "15.10.2026",
        "04.11.2026",
        "SAV-2026-0412",
        "SGD",
        "1177.20",
        "1",
        "610200",
        "KG1100",
        "1080.00",
        "TX",
        "97.20",
        "4500012345",
        "Equipment rental, PO 4500012345",
    )


def test_max_len_truncation(mapping, clean_doc):
    long_desc = "A" * 80
    coding_line = clean_doc.coding_lines[0].model_copy(update={"description": long_desc})
    row = map_row(mapping, _ctx(mapping, clean_doc, coding_line=coding_line))
    line_text_col = next(c for c in mapping.columns if c.name == "LineText")
    assert len(row[mapping.columns.index(line_text_col)]) == line_text_col.max_len


def test_empty_required_reports_names(mapping, clean_doc):
    invoice = clean_doc.invoice.model_copy(update={"invoice_number": None})
    row = map_row(mapping, _ctx(mapping, clean_doc, invoice=invoice))
    assert "Reference" in empty_required(mapping, row)


def test_template_source_resolves_fields(mapping, clean_doc):
    value = resolve_value(
        "template:{invoice.invoice_number}-L{coding.line_no}", _ctx(mapping, clean_doc)
    )
    assert value == "SAV-2026-0412-L1"


def test_unknown_source_section_raises(mapping, clean_doc):
    with pytest.raises(ValueError, match="unknown source section"):
        resolve_value("nope.field", _ctx(mapping, clean_doc))


def test_source_without_section_raises(mapping, clean_doc):
    with pytest.raises(ValueError, match="needs a section"):
        resolve_value("no-section", _ctx(mapping, clean_doc))
