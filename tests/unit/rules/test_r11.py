"""R11: dates in range, due date ordering, unambiguous day/month."""

from datetime import date

from invoiceflow.rules.r11 import R11


def test_r11_passes_clean(clean_ctx, rules_config):
    assert R11(rules_config).check(clean_ctx) == ()


def test_r11_flags_future_date(clean_ctx, rules_config):
    invoice = clean_ctx.invoice.model_copy(update={"invoice_date": date(2027, 1, 1)})
    ctx = clean_ctx.model_copy(update={"invoice": invoice, "today": date(2026, 11, 4)})
    findings = R11(rules_config).check(ctx)
    assert any(f.field == "invoice_date" and "future" in f.message for f in findings)


def test_r11_flags_too_old(clean_ctx, rules_config):
    invoice = clean_ctx.invoice.model_copy(update={"invoice_date": date(2020, 1, 1)})
    ctx = clean_ctx.model_copy(update={"invoice": invoice, "today": date(2026, 11, 4)})
    findings = R11(rules_config).check(ctx)
    assert any(f.field == "invoice_date" and "older than" in f.message for f in findings)


def test_r11_flags_due_before_invoice(clean_ctx, rules_config):
    invoice = clean_ctx.invoice.model_copy(update={"due_date": date(2026, 10, 1)})
    ctx = clean_ctx.model_copy(update={"invoice": invoice})
    findings = R11(rules_config).check(ctx)
    assert any(f.field == "due_date" for f in findings)


def test_r11_flags_ambiguous_dates(clean_ctx, rules_config):
    invoice = clean_ctx.invoice.model_copy(update={"ambiguous_dates": ("invoice_date",)})
    ctx = clean_ctx.model_copy(update={"invoice": invoice})
    findings = R11(rules_config).check(ctx)
    assert any(f.field == "invoice_date" and "ambiguous" in f.message for f in findings)
