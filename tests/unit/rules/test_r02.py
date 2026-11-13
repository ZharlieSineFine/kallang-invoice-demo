"""R02: line arithmetic, lines vs subtotal, subtotal + GST vs total."""

from decimal import Decimal

from invoiceflow.rules.r02 import R02


def test_r02_passes_clean(clean_ctx, rules_config):
    assert R02(rules_config).check(clean_ctx) == ()


def test_r02_flags_lines_vs_subtotal(mismatch_ctx, rules_config):
    findings = R02(rules_config).check(mismatch_ctx)
    assert [(f.field, f.severity.value) for f in findings] == [("subtotal", "FLAG")]
    finding = findings[0]
    assert finding.message == (
        "The line items add up to S$1,080.00, but the subtotal reads S$1,090.00."
    )
    assert finding.evidence == {"lines_sum": "1080.00", "subtotal": "1090.00"}


def test_r02_flags_broken_line_amount(clean_ctx, rules_config):
    line = clean_ctx.invoice.line_items[0].model_copy(update={"amount": Decimal("999.00")})
    invoice = clean_ctx.invoice.model_copy(
        update={"line_items": (line, *clean_ctx.invoice.line_items[1:])}
    )
    ctx = clean_ctx.model_copy(update={"invoice": invoice})
    findings = R02(rules_config).check(ctx)
    assert any(f.field == "line_items[0].amount" for f in findings)


def test_r02_flags_subtotal_plus_gst(clean_ctx, rules_config):
    invoice = clean_ctx.invoice.model_copy(update={"total": Decimal("1000.00")})
    ctx = clean_ctx.model_copy(update={"invoice": invoice})
    findings = R02(rules_config).check(ctx)
    assert [f.field for f in findings] == ["total"]


def test_r02_ignores_lines_with_missing_amount(clean_ctx, rules_config):
    line = clean_ctx.invoice.line_items[0].model_copy(update={"amount": None})
    invoice = clean_ctx.invoice.model_copy(
        update={"line_items": (line, *clean_ctx.invoice.line_items[1:])}
    )
    ctx = clean_ctx.model_copy(update={"invoice": invoice})
    findings = R02(rules_config).check(ctx)
    assert not any(f.field == "line_items[0].amount" for f in findings)


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


def test_r02_accepts_a_printed_subtotal_that_already_includes_gst(clean_ctx, rules_config):
    findings = R02(rules_config).check(_inclusive(clean_ctx))
    assert "total" not in [finding.field for finding in findings]


def test_r02_still_flags_a_gst_exclusive_invoice_with_the_same_numbers(clean_ctx, rules_config):
    findings = R02(rules_config).check(_inclusive(clean_ctx, gst_inclusive=False))
    assert "total" in [finding.field for finding in findings]


def test_r02_still_flags_an_inclusive_invoice_whose_total_differs(clean_ctx, rules_config):
    findings = R02(rules_config).check(_inclusive(clean_ctx, total=Decimal("1200.00")))
    assert "total" in [finding.field for finding in findings]
