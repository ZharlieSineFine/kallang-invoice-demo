import hashlib

import pytest

from invoiceflow.contracts import DocStatus
from invoiceflow.pipeline.golden import GoldenFixtureNotFound


def test_two_fixtures(golden):
    assert [f.fixture_id for f in golden.fixtures] == [
        "golden-a-clean",
        "golden-a-total-mismatch",
    ]


def test_pdf_matches_manifest_hash(golden):
    for f in golden.fixtures:
        assert hashlib.sha256(f.pdf_path.read_bytes()).hexdigest() == f.sha256


def test_page_has_words_and_image(golden):
    for f in golden.fixtures:
        assert len(f.page.words) > 50
        assert f.page_image_path.is_file()


def test_expected_outcomes(clean, mismatch):
    assert clean.expected_status is DocStatus.AUTO_PASSED and clean.expected_findings == ()
    assert mismatch.expected_status is DocStatus.NEEDS_REVIEW
    assert [f.rule_id for f in mismatch.expected_findings] == ["R02"]
    assert mismatch.truth.expected_rules == ("R02",)


def test_twin_breaks_only_lines_vs_subtotal(mismatch):
    inv = mismatch.truth.invoice
    lines = sum(item.amount for item in inv.line_items)
    assert lines != inv.subtotal
    assert inv.subtotal + inv.gst_amount == inv.total


def test_lookups(golden, mismatch):
    assert golden.by_invoice_number("SAV-2026-0413") == mismatch
    assert golden.matching_text("blah SAV-2026-0413 blah") == mismatch
    with pytest.raises(GoldenFixtureNotFound):
        golden.by_sha("0" * 64)
    with pytest.raises(GoldenFixtureNotFound):
        golden.by_invoice_number("NOPE")
    with pytest.raises(GoldenFixtureNotFound):
        golden.matching_text("no invoice number here")


def test_master_data(golden):
    assert golden.master.vendor("V001").gst_reg_no == "209900123K"
    assert golden.master.purchase_order("4500012345").cost_center == "KG1100"
    assert golden.master.coding.cost_center_for_venue("SIS") == "KG1200"
    assert golden.master.vendor("V999") is None
