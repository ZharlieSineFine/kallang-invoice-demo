import pytest

from invoiceflow.coding.assign import assign
from invoiceflow.export.mapping import load_sap_mapping
from invoiceflow.export.models import ExportDocument
from invoiceflow.pipeline.golden import GoldenSet, load_golden
from invoiceflow.settings import load_config


@pytest.fixture(scope="session")
def golden() -> GoldenSet:
    return load_golden()


@pytest.fixture(scope="session")
def mapping():
    return load_sap_mapping(load_config("sap_mapping"))


def _document(golden, fixture_id: str) -> ExportDocument:
    fixture = next(f for f in golden.fixtures if f.fixture_id == fixture_id)
    truth = fixture.truth
    vendor = golden.master.vendor(truth.vendor_id) if truth.vendor_id else None
    po = golden.master.purchase_order(truth.invoice.po_number) if truth.invoice.po_number else None
    return ExportDocument(
        doc_id=fixture.doc_id,
        invoice=truth.invoice,
        vendor=vendor,
        coding_lines=assign(truth.invoice, vendor, po, golden.master.coding),
    )


@pytest.fixture(scope="session")
def clean_doc(golden) -> ExportDocument:
    return _document(golden, "golden-a-clean")


@pytest.fixture(scope="session")
def mismatch_doc(golden) -> ExportDocument:
    return _document(golden, "golden-a-total-mismatch")
