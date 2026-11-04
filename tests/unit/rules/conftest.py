"""Shared fixtures for the WS5 unit tests: a full CheckContext from the golden fixtures."""

from __future__ import annotations

from datetime import date

import pytest

from invoiceflow.contracts import CheckContext
from invoiceflow.pipeline.golden import GoldenFixture, GoldenSet, load_golden
from invoiceflow.pipeline.stubs import (
    GoldenCoder,
    GoldenLocator,
    GoldenNormalizer,
    GoldenTextExtractor,
    GoldenVendorMatcher,
)
from invoiceflow.settings import load_config

GOLDEN_TODAY = date(2026, 11, 4)


@pytest.fixture(scope="session")
def rules_config() -> dict:
    return load_config("rules")


@pytest.fixture(scope="session")
def golden() -> GoldenSet:
    return load_golden()


def make_context(
    golden: GoldenSet, fixture: GoldenFixture, rules_config: dict, today: date = GOLDEN_TODAY
) -> CheckContext:
    """Replay the golden stubs to build the context the real rules would receive."""
    text = GoldenTextExtractor(golden)
    document = text.parse(fixture.pdf_path, file_id=fixture.file_id, doc_id=fixture.doc_id)
    printed = fixture.extraction.extraction
    vendor = GoldenVendorMatcher().match(printed, golden.master.vendors)
    normalized = GoldenNormalizer(golden).to_normalized(printed, vendor)
    po = (
        golden.master.purchase_order(normalized.invoice.po_number)
        if normalized.invoice.po_number
        else None
    )
    coding = GoldenCoder(golden).assign(normalized.invoice, vendor, po, golden.master.coding)
    locations = GoldenLocator(golden).locate(document, printed)
    return CheckContext(
        doc_id=fixture.doc_id,
        run_id="test",
        today=today,
        file_sha256=fixture.sha256,
        document=document,
        extraction=fixture.extraction,
        invoice=normalized.invoice,
        normalization_problems=normalized.problems,
        vendor=vendor,
        purchase_order=po,
        coding_lines=coding,
        locations=locations,
        master=golden.master,
        prior_invoices=(),
        rules_config=rules_config,
    )


@pytest.fixture(scope="session")
def clean_ctx(golden, rules_config) -> CheckContext:
    return make_context(golden, golden.fixtures[0], rules_config)


@pytest.fixture(scope="session")
def mismatch_ctx(golden, rules_config) -> CheckContext:
    return make_context(golden, golden.by_invoice_number("SAV-2026-0413"), rules_config)
