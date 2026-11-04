"""R08: bank account matches the vendor master (digits-only)."""

from invoiceflow.rules.r08 import R08


def test_r08_passes_clean(clean_ctx, rules_config):
    assert R08(rules_config).check(clean_ctx) == ()


def test_r08_flags_bank_account_mismatch(clean_ctx, rules_config):
    invoice = clean_ctx.invoice.model_copy(update={"bank_account": "1112223334"})
    ctx = clean_ctx.model_copy(update={"invoice": invoice})
    findings = R08(rules_config).check(ctx)
    assert [f.field for f in findings] == ["bank_account"]


def test_r08_compares_digits_only(clean_ctx, rules_config):
    invoice = clean_ctx.invoice.model_copy(update={"bank_account": "000-123456-7"})
    ctx = clean_ctx.model_copy(update={"invoice": invoice})
    assert R08(rules_config).check(ctx) == ()


def test_r08_skips_missing_bank_account(clean_ctx, rules_config):
    invoice = clean_ctx.invoice.model_copy(update={"bank_account": None})
    ctx = clean_ctx.model_copy(update={"invoice": invoice})
    assert R08(rules_config).check(ctx) == ()


def test_r08_skips_unknown_vendor(clean_ctx, rules_config):
    ctx = clean_ctx.model_copy(update={"vendor": None})
    assert R08(rules_config).check(ctx) == ()
