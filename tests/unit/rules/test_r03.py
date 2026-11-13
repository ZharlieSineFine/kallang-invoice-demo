"""R03: GST number, rate, amount, simplified and foreign-currency rules."""

from decimal import Decimal

from invoiceflow.contracts import DocType
from invoiceflow.rules.r03 import R03


def test_r03_passes_clean(clean_ctx, rules_config):
    assert R03(rules_config).check(clean_ctx) == ()


def test_r03_flags_missing_gst_number(clean_ctx, rules_config):
    invoice = clean_ctx.invoice.model_copy(update={"supplier_gst_reg_no": None})
    ctx = clean_ctx.model_copy(update={"invoice": invoice})
    findings = R03(rules_config).check(ctx)
    assert any(f.field == "supplier_gst_reg_no" for f in findings)


def test_r03_flags_illformed_gst_number(clean_ctx, rules_config):
    invoice = clean_ctx.invoice.model_copy(update={"supplier_gst_reg_no": "12345"})
    ctx = clean_ctx.model_copy(update={"invoice": invoice})
    findings = R03(rules_config).check(ctx)
    assert any(f.field == "supplier_gst_reg_no" for f in findings)


def test_r03_flags_wrong_rate_for_date(clean_ctx, rules_config):
    invoice = clean_ctx.invoice.model_copy(update={"gst_rate_percent": Decimal("8")})
    ctx = clean_ctx.model_copy(update={"invoice": invoice})
    findings = R03(rules_config).check(ctx)
    assert any(f.field == "gst_rate" for f in findings)


def test_r03_flags_gst_amount_mismatch(clean_ctx, rules_config):
    invoice = clean_ctx.invoice.model_copy(update={"gst_amount": Decimal("90.00")})
    ctx = clean_ctx.model_copy(update={"invoice": invoice})
    findings = R03(rules_config).check(ctx)
    assert any(f.field == "gst_amount" for f in findings)


def test_r03_flags_rate_missing_but_gst_present(clean_ctx, rules_config):
    invoice = clean_ctx.invoice.model_copy(update={"gst_rate_percent": None})
    ctx = clean_ctx.model_copy(update={"invoice": invoice})
    findings = R03(rules_config).check(ctx)
    assert any(f.field == "gst_rate" and "rate is missing" in f.message for f in findings)


def test_r03_does_not_require_gst_number_on_plain_invoice(clean_ctx, rules_config):
    invoice = clean_ctx.invoice.model_copy(
        update={"document_type": DocType.INVOICE, "supplier_gst_reg_no": None}
    )
    ctx = clean_ctx.model_copy(update={"invoice": invoice})
    assert not any(f.field == "supplier_gst_reg_no" for f in R03(rules_config).check(ctx))


def test_r03_flags_simplified_over_limit(clean_ctx, rules_config):
    invoice = clean_ctx.invoice.model_copy(
        update={
            "document_type": DocType.SIMPLIFIED_TAX_INVOICE,
            "total": Decimal("1500.00"),
            "gst_inclusive": True,
        }
    )
    ctx = clean_ctx.model_copy(update={"invoice": invoice})
    findings = R03(rules_config).check(ctx)
    assert any("exceeds" in f.message for f in findings)


def test_r03_flags_simplified_without_gst_note(clean_ctx, rules_config):
    invoice = clean_ctx.invoice.model_copy(
        update={
            "document_type": DocType.SIMPLIFIED_TAX_INVOICE,
            "total": Decimal("500.00"),
            "gst_inclusive": False,
        }
    )
    ctx = clean_ctx.model_copy(update={"invoice": invoice})
    findings = R03(rules_config).check(ctx)
    assert any("price includes GST" in f.message for f in findings)


def test_r03_flags_simplified_without_gst(clean_ctx, rules_config):
    invoice = clean_ctx.invoice.model_copy(
        update={
            "document_type": DocType.SIMPLIFIED_TAX_INVOICE,
            "gst_amount": Decimal("0"),
            "gst_inclusive": True,
        }
    )
    ctx = clean_ctx.model_copy(update={"invoice": invoice})
    findings = R03(rules_config).check(ctx)
    assert any("must charge GST" in f.message for f in findings)


def test_r03_flags_foreign_currency_without_sgd(clean_ctx, rules_config):
    invoice = clean_ctx.invoice.model_copy(update={"currency": "USD", "sgd_total": None})
    ctx = clean_ctx.model_copy(update={"invoice": invoice})
    findings = R03(rules_config).check(ctx)
    assert any(f.field == "sgd_total" for f in findings)


def _inclusive(ctx, **values):
    defaults = {
        "gst_inclusive": True,
        "subtotal": Decimal("950.00"),
        "gst_amount": Decimal("78.44"),
        "gst_rate_percent": Decimal("9"),
        "total": Decimal("950.00"),
    }
    invoice = ctx.invoice.model_copy(update={**defaults, **values})
    return ctx.model_copy(update={"invoice": invoice})


def test_r03_extracts_gst_from_an_inclusive_total(clean_ctx, rules_config):
    findings = R03(rules_config).check(_inclusive(clean_ctx))
    assert "gst_amount" not in [finding.field for finding in findings]


def test_r03_flags_wrong_gst_inside_an_inclusive_total(clean_ctx, rules_config):
    findings = R03(rules_config).check(_inclusive(clean_ctx, gst_amount=Decimal("50.00")))
    flagged = [finding for finding in findings if finding.field == "gst_amount"]
    assert flagged
    assert flagged[0].evidence["expected_gst"] == "78.44"
