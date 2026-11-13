from datetime import date
from decimal import Decimal

from invoiceflow.contracts import (
    DocType,
    ExtractedLineItem,
    InvoiceExtraction,
    NormalizedInvoice,
    Vendor,
)
from invoiceflow.normalize import Normalizer, to_normalized
from invoiceflow.pipeline.golden import load_golden

VENDOR = Vendor(
    vendor_id="V001",
    sap_vendor_no="100014",
    name="Stagecraft AV Rentals Pte. Ltd.",
    uen="209900123K",
    gst_reg_no="209900123K",
    currency="SGD",
    locale="SG",
)


def _extraction(**overrides) -> InvoiceExtraction:
    values = {
        "document_type": DocType.TAX_INVOICE,
        "invoice_number": "INV-0001",
        "invoice_date": "12/10/2026",
        "due_date": "14/11/2026",
        "currency": "SGD",
        "supplier_name": "Stagecraft AV Rentals Pte. Ltd.",
        "supplier_uen": "M2-1234567-8",
        "supplier_gst_reg_no": "M2-1234567-8",
        "po_number": "PO 4500 0123",
        "subtotal": "S$1,090.00",
        "gst_rate": "9%",
        "gst_amount": "98.10",
        "total": "1,188.10",
        "bank_account": "000-123456-7",
    }
    values.update(overrides)
    return InvoiceExtraction(**values)


def test_normalizer_implements_the_protocol():
    from invoiceflow.contracts import Normalizer as NormalizerProtocol

    normalizer = Normalizer()
    assert isinstance(normalizer, NormalizerProtocol)
    assert normalizer.to_normalized(_extraction(), VENDOR).invoice.invoice_number == "INV-0001"


def test_to_normalized_converts_all_supported_values():
    result = to_normalized(_extraction(), VENDOR)

    assert result.problems == ()
    invoice = result.invoice
    assert invoice.invoice_number == "INV-0001"
    assert invoice.invoice_date == date(2026, 10, 12)
    assert invoice.due_date == date(2026, 11, 14)
    assert invoice.currency == "SGD"
    assert invoice.subtotal == Decimal("1090.00")
    assert invoice.gst_rate_percent == Decimal("9")
    assert invoice.gst_amount == Decimal("98.10")
    assert invoice.total == Decimal("1188.10")
    assert invoice.supplier_uen == "M212345678"
    assert invoice.supplier_gst_reg_no == "M212345678"
    assert invoice.po_number == "PO45000123"
    assert invoice.bank_account == "0001234567"
    assert invoice.ambiguous_dates == ()


def test_subtotal_equal_to_total_stays_equal():
    result = to_normalized(
        _extraction(subtotal="S$1,090.00", gst_amount="0.00", total="1090"),
        VENDOR,
    )

    assert result.invoice.subtotal == result.invoice.total == Decimal("1090.00")


def test_us_vendor_reads_month_first():
    vendor = VENDOR.model_copy(update={"locale": "US"})
    result = to_normalized(_extraction(invoice_date="12/10/2026"), vendor)

    assert result.invoice.invoice_date == date(2026, 12, 10)
    assert result.invoice.ambiguous_dates == ("invoice_date",)


def test_ambiguous_is_not_set_for_a_clear_day():
    result = to_normalized(_extraction(invoice_date="15/10/2026"), VENDOR)

    assert result.invoice.invoice_date == date(2026, 10, 15)
    assert result.invoice.ambiguous_dates == ()


def test_conversion_problems_are_reported_not_raised():
    result = to_normalized(
        _extraction(invoice_date="31/02/2026", subtotal="not money", gst_rate="nine"),
        VENDOR,
    )

    assert result.invoice.invoice_date is None
    assert result.invoice.subtotal is None
    assert result.invoice.gst_rate_percent is None
    assert any(problem.startswith("invoice_date:") for problem in result.problems)
    assert any(problem.startswith("subtotal:") for problem in result.problems)
    assert any(problem.startswith("gst_rate:") for problem in result.problems)


def test_gst_inclusive_note_sets_the_flag():
    inclusive = to_normalized(_extraction(gst_inclusive_note="Price payable includes GST"), VENDOR)
    exclusive = to_normalized(_extraction(gst_inclusive_note="GST not included"), VENDOR)

    assert inclusive.invoice.gst_inclusive is True
    assert exclusive.invoice.gst_inclusive is False


def test_currency_is_inferred_from_an_sdollar_amount():
    result = to_normalized(_extraction(currency=None, subtotal="S$1,090.00"), VENDOR)

    assert result.invoice.currency == "SGD"


def test_vendor_currency_is_the_fallback():
    result = to_normalized(_extraction(currency=None), VENDOR)

    assert result.invoice.currency == "SGD"


def test_blank_values_become_none_without_problems():
    result = to_normalized(
        _extraction(
            invoice_date=" ",
            due_date=None,
            subtotal="",
            gst_amount=None,
            total="",
            supplier_uen="",
            po_number=None,
            bank_account="",
        ),
        VENDOR,
    )

    assert result.problems == ()
    assert result.invoice.invoice_date is None
    assert result.invoice.subtotal is None
    assert result.invoice.supplier_uen is None
    assert result.invoice.po_number is None
    assert result.invoice.bank_account is None


def test_line_items_are_converted_and_numbered():
    extraction = _extraction(
        line_items=(
            ExtractedLineItem(
                line_no="1",
                description="LED wall panel rental",
                quantity="4",
                unit="pcs",
                days="3",
                unit_price="S$45.00",
                amount="540.00",
            ),
            ExtractedLineItem(
                line_no=None,
                description="Transport and setup",
                quantity="1",
                unit="lot",
                unit_price="80.00",
                amount="80.00",
            ),
        )
    )

    lines = to_normalized(extraction, VENDOR).invoice.line_items

    assert [line.line_no for line in lines] == [1, 2]
    assert lines[0].quantity == Decimal("4")
    assert lines[0].days == Decimal("3")
    assert lines[0].unit_price == Decimal("45.00")
    assert lines[0].amount == Decimal("540.00")
    assert lines[1].description == "Transport and setup"


def test_bad_line_item_numbers_are_reported_but_the_line_is_kept():
    extraction = _extraction(
        line_items=(
            ExtractedLineItem(line_no="one", description="Thing", quantity="many", amount="x"),
            ExtractedLineItem(line_no="0", description="Other", amount="1.00"),
        )
    )

    result = to_normalized(extraction, VENDOR)

    assert [line.line_no for line in result.invoice.line_items] == [1, 2]
    assert result.invoice.line_items[0].quantity is None
    assert any(problem.startswith("line_items[0].line_no:") for problem in result.problems)
    assert any(problem.startswith("line_items[0].quantity:") for problem in result.problems)
    assert any(problem.startswith("line_items[0].amount:") for problem in result.problems)
    assert any(problem.startswith("line_items[1].line_no:") for problem in result.problems)


def test_repeated_line_numbers_are_renumbered_by_position():
    # A noisy scan: the model split "1 lot" off the first line and printed number 1 twice.
    extraction = _extraction(
        line_items=(
            ExtractedLineItem(line_no="1", description="Cleaning services", amount="2,160.00"),
            ExtractedLineItem(line_no="1", description="lot"),
            ExtractedLineItem(line_no="2", description="Consumables", amount="135.00"),
        )
    )
    result = to_normalized(extraction, VENDOR)
    assert [line.line_no for line in result.invoice.line_items] == [1, 2, 3]
    assert [line.description for line in result.invoice.line_items] == [
        "Cleaning services",
        "lot",
        "Consumables",
    ]
    assert any("line numbers repeat" in problem for problem in result.problems)


def test_golden_truth_normalizes_exactly():
    golden = load_golden()
    vendor = golden.master.vendor("V001")

    for fixture in golden.fixtures:
        result = to_normalized(fixture.truth.printed, vendor)
        assert result.problems == ()
        assert result.invoice == fixture.truth.invoice


def test_normalized_invoice_is_the_contract_model():
    result = to_normalized(_extraction(), VENDOR)
    assert isinstance(result.invoice, NormalizedInvoice)
