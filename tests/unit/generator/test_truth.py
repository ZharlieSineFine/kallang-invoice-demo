"""Truth files: printed values, normalized values, coding, and the anomaly signatures."""

from __future__ import annotations

from decimal import Decimal

import pytest

from generator.money import money
from generator.truth import build_truth, vendor_for
from invoiceflow.contracts import CodingSource, DocType, Vendor


def dec(text: str) -> Decimal:
    return Decimal(text.replace(",", ""))


@pytest.fixture(scope="module")
def truths(seeds, plans):
    return {plan.document_id: build_truth(plan, seeds) for plan in plans}


def test_clean_documents_add_up_from_lines_to_total(truths):
    for document_id, truth in truths.items():
        if truth.anomalies or truth.doc_type is DocType.STATEMENT or not truth.invoice.line_items:
            continue
        line_total = sum((line.amount for line in truth.invoice.line_items), Decimal("0"))
        if truth.invoice.gst_inclusive:
            assert line_total == truth.invoice.total, document_id
        else:
            assert line_total == truth.invoice.subtotal, document_id
        assert truth.invoice.subtotal + truth.invoice.gst_amount == truth.invoice.total, document_id
        assert dec(truth.printed.total) == truth.invoice.total, document_id


def test_printed_money_matches_normalized_money(truths):
    for document_id, truth in truths.items():
        if truth.doc_type is DocType.STATEMENT:
            continue
        if truth.invoice.gst_inclusive:
            assert dec(truth.printed.subtotal) == truth.invoice.total, document_id
        else:
            assert dec(truth.printed.subtotal) == truth.invoice.subtotal, document_id
        assert dec(truth.printed.gst_amount) == truth.invoice.gst_amount, document_id
        assert dec(truth.printed.total) == truth.invoice.total, document_id


def test_standard_gst_is_nine_percent_of_subtotal(truths):
    for document_id, truth in truths.items():
        if (
            truth.doc_type is DocType.STATEMENT
            or truth.invoice.gst_inclusive
            or truth.invoice.gst_rate_percent == 0
        ):
            continue
        expected = money(truth.invoice.subtotal * truth.invoice.gst_rate_percent / Decimal("100"))
        assert truth.invoice.gst_amount == expected, document_id


def test_simplified_invoices_include_gst(truths):
    simplified = [t for t in truths.values() if t.invoice.gst_inclusive]
    assert simplified
    for truth in simplified:
        assert truth.doc_type is DocType.SIMPLIFIED_TAX_INVOICE
        assert truth.printed.gst_inclusive_note
        assert truth.invoice.total <= Decimal("1000.00")
        assert truth.invoice.subtotal + truth.invoice.gst_amount == truth.invoice.total


def test_coding_uses_po_venue_and_vendor_default(truths):
    po = truths["pre-a-01"]
    assert po.expected_coding[0].coding_source is CodingSource.PO
    assert po.expected_coding[0].gl_account == "610200"

    venue = truths["pre-b-01"]
    assert venue.expected_coding[0].coding_source is CodingSource.VENUE
    assert venue.expected_coding[0].cost_center in {"KG1200"}

    default = truths["pre-a-10"]
    assert default.expected_coding[0].coding_source is CodingSource.VENDOR_DEFAULT
    assert default.expected_coding[0].cost_center == "KG2100"


def test_coding_amounts_match_the_invoice(truths):
    for document_id, truth in truths.items():
        if truth.doc_type is DocType.STATEMENT:
            assert truth.expected_coding == ()
            continue
        line = truth.expected_coding[0]
        assert line.net_amount == truth.invoice.subtotal, document_id
        assert line.tax_amount == truth.invoice.gst_amount, document_id
        if "total_edited" not in truth.anomalies:
            assert line.gross_amount == truth.invoice.total, document_id
        assert line.source_line_nos == tuple(range(1, len(truth.invoice.line_items) + 1))


def test_unknown_vendor_has_no_vendor_but_still_codes_from_the_po(truths):
    unknown = truths["pre-c-04"]
    assert unknown.vendor_id is None
    assert unknown.printed.supplier_name.startswith("Orchard")
    assert unknown.expected_coding[0].coding_source is CodingSource.PO
    assert unknown.expected_coding[0].gl_account == "610200"


def test_venue_without_cost_center_leaves_coding_missing(truths, seeds):
    missing = truths["pre-b-03"]
    line = missing.expected_coding[0]
    assert line.coding_source is CodingSource.VENDOR_DEFAULT
    assert line.cost_center is None
    assert seeds.vendor("V011").default_cost_center is None


def test_credit_notes_are_negative_and_quote_an_invoice(truths):
    for document_id in ("pre-cn-01", "pre-cn-02"):
        truth = truths[document_id]
        assert truth.doc_type is DocType.CREDIT_NOTE
        assert truth.invoice.total < 0
        assert truth.printed.original_invoice_ref
        assert truth.expected_coding[0].net_amount < 0


def test_statement_is_not_an_invoice(truths):
    statement = truths["pre-soa-01"]
    assert statement.doc_type is DocType.STATEMENT
    assert statement.printed.subtotal is None
    assert statement.printed.gst_amount is None
    assert statement.invoice.line_items == ()
    assert statement.expected_coding == ()
    assert statement.invoice.total == Decimal("3542.50")


def test_us_date_is_normalized_month_first(truths):
    us = truths["pre-a-06"]
    assert us.printed.invoice_date == "03/04/2026"
    assert us.invoice.invoice_date.isoformat() == "2026-03-04"
    assert "invoice_date" in us.invoice.ambiguous_dates


def test_bank_change_differs_from_the_master(truths, seeds):
    truth = truths["live-03"]
    vendor = seeds.vendor(truth.vendor_id)
    assert truth.printed.bank_account.replace("-", "") != vendor.bank_account


def test_missing_gst_registration_is_omitted(truths, seeds):
    truth = truths["pre-a-05"]
    assert truth.printed.supplier_gst_reg_no is None
    assert truth.invoice.supplier_gst_reg_no is None
    assert seeds.vendor(truth.vendor_id).gst_reg_no is not None


def test_wrong_gst_rate_is_printed_as_eight_percent(truths):
    truth = truths["pre-a-04"]
    assert truth.printed.gst_rate == "8%"
    assert truth.invoice.gst_rate_percent == Decimal("8")
    assert truth.invoice.gst_amount == Decimal("83.20")


def test_total_edited_prints_a_total_that_does_not_add_up(truths):
    truth = truths["live-02"]
    assert truth.printed.subtotal == "1,080.00"
    assert truth.printed.gst_amount == "97.20"
    assert truth.printed.total == "1,090.00"
    assert truth.invoice.subtotal + truth.invoice.gst_amount != truth.invoice.total


def test_po_exceeded_is_above_the_open_amount(truths, seeds):
    truth = truths["pre-a-07"]
    po = seeds.purchase_order(truth.printed.po_number)
    assert truth.invoice.total > po.open_amount


def test_instruction_anomalies_are_not_extracted(truths):
    for document_id in ("pre-a-09", "pre-b-07", "pre-b-10", "live-04"):
        truth = truths[document_id]
        assert "instructions" not in truth.printed.model_dump_json()


def test_hidden_and_visible_instruction_documents_exist(truths):
    hidden = [t for t in truths.values() if "hidden_instructions" in t.anomalies]
    visible = [t for t in truths.values() if "visible_instructions" in t.anomalies]
    assert hidden and visible


def test_usd_invoice_has_an_sgd_equivalent(truths):
    truth = truths["pre-usd-01"]
    assert truth.invoice.currency == "USD"
    assert truth.invoice.gst_rate_percent == Decimal("0")
    assert truth.invoice.sgd_total == Decimal("1620.00")
    assert truth.printed.sgd_total == "1,620.00"
    assert truth.expected_coding[0].tax_code == "OP"


def test_vendor_from_plan(seeds, plans):
    plan = next(p for p in plans if p.document_id == "pre-c-04")
    vendor = vendor_for(plan, seeds)
    assert isinstance(vendor.to_contract(), Vendor)
    assert vendor.vendor_id == "V999"
