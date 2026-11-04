"""Contract tests: the shapes every workstream builds against."""

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from invoiceflow.contracts import (
    HEADER_FIELDS,
    PINT_SG_TERMS,
    BBox,
    CodingLine,
    CodingMaster,
    CodingSource,
    Confidence,
    CostCenter,
    DocStatus,
    DocType,
    ExtractedLineItem,
    Finding,
    GLAccount,
    InvoiceExtraction,
    NormalizedInvoice,
    NormalizedLineItem,
    Review,
    ReviewAction,
    Scope,
    Severity,
    TaxCode,
    VenueAlias,
    Word,
    max_severity,
    money,
)


class TestBBox:
    def test_accepts_page_fractions(self):
        box = BBox(x0=0.1, y0=0.2, x1=0.3, y1=0.4)
        assert box.width == pytest.approx(0.2)

    @pytest.mark.parametrize(
        "coords",
        [
            {"x0": -0.1, "y0": 0, "x1": 0.5, "y1": 0.5},
            {"x0": 0, "y0": 0, "x1": 1.2, "y1": 0.5},
            {"x0": 0.6, "y0": 0, "x1": 0.5, "y1": 0.5},
            {"x0": 0, "y0": 0.6, "x1": 0.5, "y1": 0.5},
        ],
    )
    def test_rejects_out_of_range_or_inverted(self, coords):
        with pytest.raises(ValidationError):
            BBox(**coords)

    def test_union_covers_both(self):
        a = BBox(x0=0.1, y0=0.1, x1=0.2, y1=0.2)
        b = BBox(x0=0.15, y0=0.05, x1=0.4, y1=0.15)
        assert a.union(b) == BBox(x0=0.1, y0=0.05, x1=0.4, y1=0.2)


class TestImmutability:
    def test_models_are_frozen(self):
        word = Word(text="Total", bbox=BBox(x0=0, y0=0, x1=0.1, y1=0.1))
        with pytest.raises(ValidationError):
            word.text = "changed"

    def test_unknown_fields_rejected(self):
        with pytest.raises(ValidationError):
            Word(text="x", bbox=BBox(x0=0, y0=0, x1=0.1, y1=0.1), colour="red")

    def test_hidden_defaults_false(self):
        assert Word(text="x", bbox=BBox(x0=0, y0=0, x1=0.1, y1=0.1)).hidden is False


class TestMoney:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("2.345", "2.35"), ("2.344", "2.34"), ("97.2", "97.20"), ("-1.005", "-1.01")],
    )
    def test_rounds_half_up_to_cents(self, raw, expected):
        assert money(Decimal(raw)) == Decimal(expected)

    def test_rejects_float(self):
        with pytest.raises(TypeError):
            money(1.1)  # type: ignore[arg-type]


class TestSeverity:
    def test_order(self):
        assert Severity.INFO.rank < Severity.FLAG.rank < Severity.HOLD.rank < Severity.MANUAL.rank

    def test_max_severity(self):
        assert max_severity(()) is None
        assert max_severity((Severity.FLAG, Severity.HOLD, Severity.INFO)) is Severity.HOLD


class TestExtraction:
    def test_all_header_fields_are_optional_strings(self):
        empty = InvoiceExtraction()
        for name in HEADER_FIELDS:
            assert getattr(empty, name) is None

    def test_values_stay_as_printed(self):
        ext = InvoiceExtraction(total="S$1,177.20", invoice_date="15/10/2026")
        assert ext.total == "S$1,177.20"

    def test_json_schema_is_usable_for_structured_output(self):
        schema = InvoiceExtraction.model_json_schema()
        assert schema["type"] == "object"
        assert "line_items" in schema["properties"]
        assert schema.get("additionalProperties") is False

    def test_pint_sg_terms_name_real_fields(self):
        assert set(PINT_SG_TERMS) <= set(HEADER_FIELDS) | {"line_items"}
        assert PINT_SG_TERMS["invoice_number"] == "IBT-001"

    def test_line_items_are_tuples(self):
        ext = InvoiceExtraction(line_items=[ExtractedLineItem(description="LED wall")])
        assert isinstance(ext.line_items, tuple)


class TestNormalizedInvoice:
    def test_round_trips_through_json_without_losing_decimals(self):
        inv = NormalizedInvoice(
            document_type=DocType.TAX_INVOICE,
            invoice_number="SAV-2026-0412",
            invoice_date=date(2026, 10, 15),
            subtotal=Decimal("1080.00"),
            gst_rate_percent=Decimal("9"),
            gst_amount=Decimal("97.20"),
            total=Decimal("1177.20"),
            line_items=(NormalizedLineItem(line_no=1, amount=Decimal("540.00")),),
        )
        again = NormalizedInvoice.model_validate_json(inv.model_dump_json())
        assert again == inv
        assert again.total == Decimal("1177.20")

    def test_rejects_float_money(self):
        with pytest.raises(ValidationError):
            NormalizedInvoice(total=1177.2)


class TestFinding:
    def test_rule_id_format(self):
        with pytest.raises(ValidationError):
            Finding(
                rule_id="2",
                rule_version="v",
                severity=Severity.FLAG,
                scope=Scope.FIELD,
                message="m",
            )

    def test_evidence_is_string_map(self):
        f = Finding(
            rule_id="R02",
            rule_version="abc",
            severity=Severity.FLAG,
            scope=Scope.FIELD,
            field="subtotal",
            message="Lines do not add up",
            evidence={"lines_sum": "1080.00"},
        )
        assert f.evidence["lines_sum"] == "1080.00"


class TestCoding:
    def _master(self):
        return CodingMaster(
            gl_accounts=(GLAccount(code="610200", name="Equipment rental"),),
            cost_centers=(CostCenter(code="KG1100", name="National Stadium"),),
            tax_codes=(TaxCode(code="TX", rate_percent=Decimal("9"), description="Input tax"),),
            venue_aliases=(VenueAlias(alias="National Stadium", cost_center="KG1100"),),
        )

    def test_lookups(self):
        m = self._master()
        assert m.has_gl("610200") and not m.has_gl("999999")
        assert m.has_cost_center("KG1100")
        assert m.tax_rate("TX") == Decimal("9")
        assert m.tax_rate("ZZ") is None

    def test_venue_lookup_ignores_case_and_spacing(self):
        assert self._master().cost_center_for_venue("  national   STADIUM ") == "KG1100"
        assert self._master().cost_center_for_venue("Somewhere else") is None

    def test_coding_line_money_is_decimal(self):
        line = CodingLine(
            line_no=1,
            gl_account="610200",
            cost_center="KG1100",
            tax_code="TX",
            net_amount=Decimal("1080.00"),
            tax_amount=Decimal("97.20"),
            coding_source=CodingSource.PO,
        )
        assert line.gross_amount == Decimal("1177.20")


class TestReview:
    def test_release_hold_needs_comment(self):
        with pytest.raises(ValidationError):
            Review(
                doc_id=uuid4(),
                reviewer="finance.a",
                action=ReviewAction.RELEASE_HOLD,
                created_at=datetime.now(UTC),
            )

    def test_approve_without_comment_is_fine(self):
        r = Review(
            doc_id=uuid4(),
            reviewer="finance.a",
            action=ReviewAction.APPROVE,
            created_at=datetime.now(UTC),
        )
        assert r.comment is None


def test_enum_values_are_stable_strings():
    assert DocStatus.NEEDS_REVIEW == "NEEDS_REVIEW"
    assert Confidence.HIGH == "HIGH"
