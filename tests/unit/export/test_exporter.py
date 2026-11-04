"""Exporter tests: the golden CSV, manifest, file writing, and the blocking mismatch."""

from datetime import date

import pytest

from invoiceflow.export.checks import BatchError
from invoiceflow.export.exporter import build_batch, export_documents
from invoiceflow.export.manifest import sha256_bytes

EXPORT_DATE = date(2026, 11, 4)

EXPECTED_CSV = (
    '"DocKey","CompanyCode","VendorNo","DocumentDate","PostingDate","Reference",'
    '"Currency","GrossAmount","LineNo","GLAccount","CostCenter","NetAmount","TaxCode",'
    '"TaxAmount","PONumber","LineText"\r\n'
    '"93fe9312-fe79-50bb-b5e7-d18e83dfaff2","KG01","100014","15.10.2026","04.11.2026",'
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
