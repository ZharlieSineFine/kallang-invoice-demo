"""CSV row -> document -> page box, for the SAP layout and the current DAG layout."""

from __future__ import annotations

from app import ui
from app.boxes import load_page_text
from app.csv_trace import (
    column_sources,
    origin_boxes,
    read_csv,
    trace_cell,
)

SAP_CSV = (
    '"DocKey","CompanyCode","VendorNo","DocumentDate","PostingDate","Reference","Currency",'
    '"GrossAmount","LineNo","GLAccount","CostCenter","NetAmount","TaxCode","TaxAmount",'
    '"PONumber","LineText"\n'
    '"{doc}","KG01","100014","15.10.2026","04.11.2026","SAV-2026-0412","SGD","1177.20","1",'
    '"610200","KG1100","1080.00","TX","97.20","4500012345","Equipment rental"\n'
)


def _sap_row(tmp_path, bundle):
    path = tmp_path / "sap.csv"
    path.write_text(SAP_CSV.format(doc=bundle.document.doc_id), encoding="utf-8")
    return read_csv(path)[0]


def _words(bundle):
    return load_page_text(bundle.pages[0].words_path)


def test_read_csv_numbers_rows_and_finds_the_document(tmp_path, clean_bundle):
    row = _sap_row(tmp_path, clean_bundle)
    assert row.row_no == 1
    assert row.doc_id == clean_bundle.document.doc_id
    assert row.line_no == 1
    assert row.cells["GrossAmount"] == "1177.20"


def test_read_csv_tolerates_an_unknown_document_key(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text(SAP_CSV.format(doc="not-a-uuid"), encoding="utf-8")
    assert read_csv(path)[0].doc_id is None


def test_sap_columns_come_from_the_mapping_config(tmp_path, clean_bundle):
    sources = column_sources(tuple(_sap_row(tmp_path, clean_bundle).cells))
    assert sources["GrossAmount"] == "invoice.total"
    assert sources["CompanyCode"] == "const:KG01"


def test_header_value_traces_to_its_field_and_box(tmp_path, clean_bundle):
    row = _sap_row(tmp_path, clean_bundle)
    origin = trace_cell(row, "GrossAmount", column_sources(tuple(row.cells)), clean_bundle)
    assert origin.kind == "page"
    assert origin.field == "total"
    boxes = origin_boxes(origin, clean_bundle, _words(clean_bundle))
    assert [box.field for box in boxes] == ["total"]
    assert boxes[0].selected


def test_net_amount_traces_to_the_source_line_items(tmp_path, clean_bundle):
    row = _sap_row(tmp_path, clean_bundle)
    origin = trace_cell(row, "NetAmount", column_sources(tuple(row.cells)), clean_bundle)
    assert origin.kind == "page"
    boxes = origin_boxes(origin, clean_bundle, _words(clean_bundle))
    assert boxes
    assert all(box.field.endswith(".amount") for box in boxes)


def test_gl_account_is_assigned_not_read_so_it_has_no_box(tmp_path, clean_bundle):
    row = _sap_row(tmp_path, clean_bundle)
    origin = trace_cell(row, "GLAccount", column_sources(tuple(row.cells)), clean_bundle)
    assert origin.kind == "coding"
    assert "not printed" in origin.detail.lower()
    assert origin_boxes(origin, clean_bundle, _words(clean_bundle)) == ()


def test_vendor_number_comes_from_the_master_matched_on_the_printed_name(tmp_path, clean_bundle):
    row = _sap_row(tmp_path, clean_bundle)
    origin = trace_cell(row, "VendorNo", column_sources(tuple(row.cells)), clean_bundle)
    assert origin.kind == "master"
    assert origin.field == "supplier_name"


def test_constants_and_batch_values_are_labeled_as_such(tmp_path, clean_bundle):
    row = _sap_row(tmp_path, clean_bundle)
    sources = column_sources(tuple(row.cells))
    assert trace_cell(row, "CompanyCode", sources, clean_bundle).kind == "constant"
    assert trace_cell(row, "PostingDate", sources, clean_bundle).kind == "batch"
    assert trace_cell(row, "DocKey", sources, clean_bundle).kind == "document"


def test_an_unmapped_column_is_reported_not_guessed(tmp_path, clean_bundle):
    row = _sap_row(tmp_path, clean_bundle)
    origin = trace_cell(row, "GrossAmount", {}, clean_bundle)
    assert origin.kind == "unknown"


def test_relative_words_paths_resolve_under_the_data_directory(tmp_path, monkeypatch):
    # The pipeline stores words_path relative to data/, so the Review page lost its boxes.
    monkeypatch.setenv("INVOICEFLOW_DATA", str(tmp_path))
    target = tmp_path / "silver" / "doc" / "page-1.words.json"
    target.parent.mkdir(parents=True)
    target.write_text("{}", encoding="utf-8")
    assert ui.resolve_path("silver/doc/page-1.words.json") == target
