"""Exporter tests: the golden CSV, manifest, file writing, and the blocking mismatch."""

from datetime import date

import pytest

from invoiceflow.export.checks import BatchError
from invoiceflow.export.exporter import build_batch, export_documents
from invoiceflow.export.manifest import sha256_bytes

EXPORT_DATE = date(2026, 11, 4)

EXPECTED_CSV = (
    '"InvoiceID","CompanyCode","VendorNo","DocumentDate","PostingDate","Reference",'
    '"Currency","GrossAmount","LineNo","GLAccount","CostCenter","NetAmount","TaxCode",'
    '"TaxAmount","PONumber","LineText"\r\n'
    '"1","KG01","100014","15.10.2026","04.11.2026",'
    '"SAV-2026-0412","SGD","1177.20","1","610200","KG1100","1080.00","TX","97.20",'
    '"4500012345","Equipment rental, PO 4500012345"\r\n'
)


def _versions():
    return dict(model="gemma4:12b", prompt_version="prompts/extract_v1.md", rule_version="1")


def test_golden_csv_identical_to_expected(mapping, golden, clean_doc):
    prepared = build_batch(
        mapping,
        (clean_doc,),
        golden.master.coding,
        export_date=EXPORT_DATE,
        batch_id="golden-test",
        **_versions(),
    )
    assert prepared.csv_text == EXPECTED_CSV
    assert prepared.csv_sha256 == sha256_bytes(EXPECTED_CSV.encode("utf-8"))


def test_manifest_has_required_fields(mapping, golden, clean_doc):
    prepared = build_batch(
        mapping,
        (clean_doc,),
        golden.master.coding,
        export_date=EXPORT_DATE,
        batch_id="golden-test",
        **_versions(),
    )
    data = prepared.manifest.to_dict()
    assert data["batch_id"] == "golden-test"
    assert data["row_count"] == 1
    assert data["total"] == "1177.20"
    assert data["csv_sha256"] == prepared.csv_sha256
    assert data["mapping_version"] == "1"
    assert data["model"] == "gemma4:12b"
    assert data["prompt_version"] == "prompts/extract_v1.md"
    assert data["rule_version"] == "1"


def test_mismatch_blocks_the_batch(mapping, golden, mismatch_doc):
    with pytest.raises(BatchError) as excinfo:
        build_batch(
            mapping,
            (mismatch_doc,),
            golden.master.coding,
            export_date=EXPORT_DATE,
            batch_id="bad",
            **_versions(),
        )
    assert "gross" in str(excinfo.value)


def test_export_documents_writes_csv_and_manifest(mapping, golden, clean_doc, tmp_path):
    result = export_documents(
        mapping,
        (clean_doc,),
        golden.master.coding,
        export_date=EXPORT_DATE,
        batch_id="golden-test",
        out_dir=tmp_path,
        **_versions(),
    )
    assert result.csv_path.is_file()
    assert result.manifest_path.is_file()
    assert result.csv_path.read_bytes().decode("utf-8") == EXPECTED_CSV
    assert result.manifest_path.read_text(encoding="utf-8").startswith("{")


def _second(doc, number: str):
    """Another invoice from the same vendor, so one batch can hold two."""
    from dataclasses import replace
    from uuid import NAMESPACE_URL, uuid5

    invoice = doc.invoice.model_copy(update={"invoice_number": number})
    return replace(doc, doc_id=uuid5(NAMESPACE_URL, number), invoice=invoice)


def _two_invoice_batch(mapping, golden, clean_doc):
    first = clean_doc
    second = _second(clean_doc, "SAV-2026-0499")
    two_lines = (
        second.coding_lines[0].model_copy(
            update={"net_amount": second.coding_lines[0].net_amount - 80}
        ),
        second.coding_lines[0].model_copy(update={"line_no": 2, "net_amount": 80, "tax_amount": 0}),
    )
    from dataclasses import replace

    second = replace(second, coding_lines=two_lines)
    return (
        build_batch(
            mapping,
            (first, second),
            golden.master.coding,
            export_date=EXPORT_DATE,
            batch_id="two",
            **_versions(),
        ),
        first,
        second,
    )


def test_invoices_are_numbered_1_2_3_in_each_file(mapping, golden, clean_doc):
    prepared, _, _ = _two_invoice_batch(mapping, golden, clean_doc)
    assert [row[0] for row in prepared.rows] == ["1", "2", "2"]


def test_the_manifest_records_which_number_is_which_invoice(mapping, golden, clean_doc):
    prepared, first, second = _two_invoice_batch(mapping, golden, clean_doc)
    invoices = prepared.manifest.to_dict()["invoices"]
    assert invoices == [
        {
            "invoice_id": 1,
            "doc_id": str(first.doc_id),
            "vendor_no": first.vendor.sap_vendor_no,
            "reference": "SAV-2026-0412",
            "first_row": 1,
            "row_count": 1,
        },
        {
            "invoice_id": 2,
            "doc_id": str(second.doc_id),
            "vendor_no": second.vendor.sap_vendor_no,
            "reference": "SAV-2026-0499",
            "first_row": 2,
            "row_count": 2,
        },
    ]
