"""WS8 coding tests: precedence rules, tax codes, grouping, and GST rounding."""

from decimal import Decimal

import pytest

from invoiceflow.coding.assign import SapCoder, assign, split_gst, tax_code_for
from invoiceflow.contracts import (
    Coder,
    CodingLine,
    CodingMaster,
    CodingSource,
    CostCenter,
    DocType,
    GLAccount,
    NormalizedInvoice,
    NormalizedLineItem,
    PurchaseOrder,
    TaxCode,
    Vendor,
    VenueAlias,
)


def _master() -> CodingMaster:
    return CodingMaster(
        gl_accounts=(
            GLAccount(code="610200", name="Equipment rental"),
            GLAccount(code="610100", name="Event production"),
        ),
        cost_centers=(
            CostCenter(code="KG1100", name="National Stadium"),
            CostCenter(code="KG1200", name="Indoor Stadium"),
            CostCenter(code="KG2100", name="Events"),
        ),
        tax_codes=(
            TaxCode(code="TX", rate_percent=Decimal("9"), description="Input tax"),
            TaxCode(code="ZP", rate_percent=Decimal("0"), description="Zero-rated"),
            TaxCode(code="NR", rate_percent=Decimal("0"), description="Not registered"),
            TaxCode(code="OP", rate_percent=Decimal("0"), description="Overseas"),
        ),
        venue_aliases=(
            VenueAlias(alias="National Stadium", cost_center="KG1100"),
            VenueAlias(alias="Indoor Stadium", cost_center="KG1200"),
        ),
    )


def _vendor(**overrides) -> Vendor:
    values = dict(
        vendor_id="V001",
        sap_vendor_no="100014",
        name="Stagecraft AV Rentals Pte. Ltd.",
        gst_reg_no="209900123K",
        is_overseas=False,
        default_gl="610200",
        default_cost_center="KG2100",
        default_tax_code="TX",
    )
    values.update(overrides)
    return Vendor(**values)


def _po(**overrides) -> PurchaseOrder:
    values = dict(
        po_number="4500012345",
        vendor_id="V001",
        amount=Decimal("5000.00"),
        open_amount=Decimal("5000.00"),
        gl_account="610200",
        cost_center="KG1100",
    )
    values.update(overrides)
    return PurchaseOrder(**values)


def _line(no: int, description: str, amount: str) -> NormalizedLineItem:
    return NormalizedLineItem(line_no=no, description=description, amount=Decimal(amount))


def _invoice(**overrides) -> NormalizedInvoice:
    values = dict(
        document_type=DocType.TAX_INVOICE,
        invoice_number="SAV-2026-0412",
        currency="SGD",
        supplier_gst_reg_no="209900123K",
        gst_rate_percent=Decimal("9"),
        gst_amount=Decimal("97.20"),
        total=Decimal("1177.20"),
        line_items=(
            _line(1, "LED wall panel rental", "540.00"),
            _line(2, "Line array speaker rental", "300.00"),
            _line(3, "AV technician", "160.00"),
            _line(4, "Transport and setup", "80.00"),
        ),
    )
    values.update(overrides)
    return NormalizedInvoice(**values)


class TestPrecedence:
    def test_po_rule_wins(self):
        invoice = _invoice()
        lines = assign(invoice, _vendor(), _po(), _master())
        assert len(lines) == 1
        line = lines[0]
        assert line.coding_source is CodingSource.PO
        assert (line.gl_account, line.cost_center) == ("610200", "KG1100")
        assert line.description == "Equipment rental, PO 4500012345"
        assert line.source_line_nos == (1, 2, 3, 4)

    def test_venue_from_header(self):
        invoice = _invoice(venue="National Stadium")
        lines = assign(invoice, _vendor(), None, _master())
        assert len(lines) == 1
        line = lines[0]
        assert line.coding_source is CodingSource.VENUE
        assert line.gl_account == "610200"  # vendor default GL
        assert line.cost_center == "KG1100"  # venue cost center
        assert line.description == "Equipment rental, National Stadium"

    def test_venue_from_line_description(self):
        invoice = _invoice(
            venue=None,
            line_items=(_line(1, "Catering at Indoor Stadium", "100.00"),),
            gst_amount=Decimal("9.00"),
            total=Decimal("109.00"),
        )
        lines = assign(invoice, _vendor(), None, _master())
        assert len(lines) == 1
        assert lines[0].coding_source is CodingSource.VENUE
        assert lines[0].cost_center == "KG1200"
        assert lines[0].gl_account == "610200"

    def test_vendor_default(self):
        invoice = _invoice(venue=None)
        lines = assign(invoice, _vendor(), None, _master())
        assert len(lines) == 1
        line = lines[0]
        assert line.coding_source is CodingSource.VENDOR_DEFAULT
        assert (line.gl_account, line.cost_center) == ("610200", "KG2100")

    def test_none_when_no_rule_matches(self):
        invoice = _invoice(venue=None)
        lines = assign(invoice, None, None, _master())
        assert len(lines) == 1
        line = lines[0]
        assert line.coding_source is CodingSource.NONE
        assert line.gl_account is None
        assert line.cost_center is None

    def test_short_alias_requires_whole_word(self):
        master = CodingMaster(
            gl_accounts=_master().gl_accounts,
            cost_centers=_master().cost_centers,
            tax_codes=_master().tax_codes,
            venue_aliases=(VenueAlias(alias="SIS", cost_center="KG1200"),),
        )
        invoice = _invoice(
            venue=None,
            line_items=(_line(1, "data analysis", "100.00"),),
            gst_amount=Decimal("9.00"),
            total=Decimal("109.00"),
        )
        lines = assign(invoice, _vendor(), None, master)
        assert lines[0].coding_source is CodingSource.VENDOR_DEFAULT
        assert lines[0].cost_center == "KG2100"  # "analysis" must not match "SIS"


class TestTaxCode:
    def test_tx_when_gst_registered_and_9_percent(self):
        assert tax_code_for(_invoice(), _vendor()) == "TX"

    def test_nr_when_no_gst_number(self):
        invoice = _invoice(supplier_gst_reg_no=None)
        assert tax_code_for(invoice, _vendor(gst_reg_no=None)) == "NR"

    def test_op_when_overseas(self):
        assert tax_code_for(_invoice(), _vendor(is_overseas=True)) == "OP"

    def test_zp_when_zero_rated(self):
        invoice = _invoice(gst_rate_percent=Decimal("0"), gst_amount=Decimal("0"))
        assert tax_code_for(invoice, _vendor()) == "ZP"


class TestGrouping:
    def test_same_coding_merges_into_one_line(self):
        lines = assign(_invoice(), _vendor(), None, _master())
        assert len(lines) == 1
        assert lines[0].net_amount == Decimal("1080.00")
        assert lines[0].source_line_nos == (1, 2, 3, 4)

    def test_different_venues_split_lines(self):
        invoice = _invoice(
            venue=None,
            line_items=(
                _line(1, "Catering at National Stadium", "100.00"),
                _line(2, "Catering at Indoor Stadium", "200.00"),
            ),
            gst_amount=Decimal("27.00"),
            total=Decimal("327.00"),
        )
        lines = assign(invoice, _vendor(), None, _master())
        assert [line.cost_center for line in lines] == ["KG1100", "KG1200"]
        assert [line.net_amount for line in lines] == [Decimal("100.00"), Decimal("200.00")]

    def test_empty_invoice_has_no_coding(self):
        assert assign(_invoice(line_items=()), _vendor(), _po(), _master()) == ()


class TestGstSpread:
    def test_single_line_gets_whole_gst(self):
        invoice = _invoice(
            line_items=(_line(1, "One line", "1080.00"),),
            gst_amount=Decimal("97.20"),
            total=Decimal("1177.20"),
        )
        lines = assign(invoice, _vendor(), None, _master())
        assert lines[0].tax_amount == Decimal("97.20")

    def test_rounding_difference_lands_on_largest_line(self):
        master = CodingMaster(
            gl_accounts=_master().gl_accounts,
            cost_centers=(
                CostCenter(code="KG1100", name="National Stadium"),
                CostCenter(code="KG1200", name="Indoor Stadium"),
                CostCenter(code="KG1300", name="Aquatic Centre"),
            ),
            tax_codes=_master().tax_codes,
            venue_aliases=(
                VenueAlias(alias="National Stadium", cost_center="KG1100"),
                VenueAlias(alias="Indoor Stadium", cost_center="KG1200"),
                VenueAlias(alias="Aquatic Centre", cost_center="KG1300"),
            ),
        )
        invoice = _invoice(
            venue=None,
            line_items=(
                _line(1, "National Stadium", "1.00"),
                _line(2, "Indoor Stadium", "1.00"),
                _line(3, "Aquatic Centre", "1.00"),
            ),
            gst_amount=Decimal("0.10"),
            total=Decimal("3.10"),
        )
        lines = assign(invoice, _vendor(), None, master)
        taxes = [line.tax_amount for line in lines]
        assert sum(taxes, Decimal("0")) == Decimal("0.10")
        assert taxes[0] == Decimal("0.04")  # largest (first) carries the cent
        assert taxes[1:] == [Decimal("0.03"), Decimal("0.03")]

    @pytest.mark.parametrize(
        ("total", "nets", "expected"),
        [
            (Decimal("97.20"), (Decimal("1080.00"),), (Decimal("97.20"),)),
            (
                Decimal("28.00"),
                (Decimal("100.00"), Decimal("100.00"), Decimal("100.00")),
                (Decimal("9.34"), Decimal("9.33"), Decimal("9.33")),
            ),
            (
                Decimal("0.10"),
                (Decimal("1.00"), Decimal("1.00"), Decimal("1.00")),
                (Decimal("0.04"), Decimal("0.03"), Decimal("0.03")),
            ),
            (Decimal("0"), (Decimal("5.00"), Decimal("5.00")), (Decimal("0.00"), Decimal("0.00"))),
            (Decimal("5.00"), (), ()),
            (Decimal("5.00"), (Decimal("0"), Decimal("0")), (Decimal("5.00"), Decimal("0.00"))),
        ],
    )
    def test_split_gst(self, total, nets, expected):
        assert split_gst(total, nets) == expected

    def test_tax_code_falls_back_to_vendor_default(self):
        invoice = _invoice(gst_rate_percent=None)
        assert tax_code_for(invoice, _vendor(default_tax_code="BL")) == "BL"
        assert tax_code_for(invoice, _vendor(default_tax_code=None)) == "TX"

    def test_gst_number_from_vendor_when_invoice_has_none(self):
        invoice = _invoice(supplier_gst_reg_no=None)
        assert tax_code_for(invoice, _vendor(gst_reg_no="209900123K")) == "TX"


def test_sap_coder_satisfies_the_coder_protocol():
    assert isinstance(SapCoder(), Coder)
    result = SapCoder().assign(_invoice(), _vendor(), _po(), _master())
    assert isinstance(result, tuple)
    assert all(isinstance(line, CodingLine) for line in result)
