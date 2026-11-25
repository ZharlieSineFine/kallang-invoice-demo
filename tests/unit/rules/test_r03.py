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


def _foreign(ctx, *, overseas=True, currency="USD", rate="0", gst="0.00"):
    """HAV-2026-6001's shape: a USD invoice at 0% from a vendor the master marks overseas
    (out of scope for Singapore GST, tax code OP), SGD total shown, no SGD GST read."""
    invoice = ctx.invoice.model_copy(
        update={
            "currency": currency,
            "gst_rate_percent": Decimal(rate),
            "gst_amount": Decimal(gst),
            "total": ctx.invoice.subtotal + Decimal(gst),
            "sgd_total": Decimal("1620.00"),
            "sgd_gst_amount": None,
        }
    )
    vendor = ctx.vendor.model_copy(update={"is_overseas": overseas})
    return ctx.model_copy(update={"invoice": invoice, "vendor": vendor})


def _gst_fields(ctx, rules_config):
    return {f.field for f in R03(rules_config).check(ctx)} & {"gst_rate", "sgd_gst_amount"}


def test_r03_accepts_zero_gst_on_a_foreign_out_of_scope_invoice(clean_ctx, rules_config):
    """User, 2026-11-24: accept 0% when the invoice is in a foreign currency and the vendor
    is marked out of scope. With no GST charged there is no SGD GST amount to show."""
    assert _gst_fields(_foreign(clean_ctx), rules_config) == set()


def test_r03_still_flags_zero_gst_from_a_vendor_not_marked_out_of_scope(clean_ctx, rules_config):
    assert _gst_fields(_foreign(clean_ctx, overseas=False), rules_config) == {
        "gst_rate",
        "sgd_gst_amount",
    }


def test_r03_still_flags_zero_gst_on_an_sgd_invoice_from_an_overseas_vendor(
    clean_ctx, rules_config
):
    assert _gst_fields(_foreign(clean_ctx, currency="SGD"), rules_config) == {"gst_rate"}


def test_r03_still_flags_gst_charged_by_an_out_of_scope_vendor(clean_ctx, rules_config):
    gst = str(clean_ctx.invoice.subtotal * Decimal("0.05"))
    ctx = _foreign(clean_ctx, rate="5", gst=gst)
    assert _gst_fields(ctx, rules_config) == {"gst_rate", "sgd_gst_amount"}


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


def test_r03_shows_rates_with_a_percent_sign(clean_ctx, rules_config):
    # The finding card prints evidence as stored; a rate reads "8%", never "8.00" (2026-11-19).
    invoice = clean_ctx.invoice.model_copy(update={"gst_rate_percent": Decimal("8.00")})
    ctx = clean_ctx.model_copy(update={"invoice": invoice})
    rate = next(f for f in R03(rules_config).check(ctx) if f.field == "gst_rate")
    assert rate.evidence["expected"] == "9%"
    assert rate.evidence["found"] == "8%"
    assert "8%" in rate.message
    assert "8.00" not in rate.message


def test_r03_amount_evidence_keeps_money_but_shows_the_rate_as_a_percent(clean_ctx, rules_config):
    invoice = clean_ctx.invoice.model_copy(update={"gst_amount": Decimal("90.00")})
    ctx = clean_ctx.model_copy(update={"invoice": invoice})
    amount = next(f for f in R03(rules_config).check(ctx) if f.field == "gst_amount")
    assert amount.evidence["rate_percent"] == "9%"
    assert amount.evidence["gst_amount"] == "90.00"
