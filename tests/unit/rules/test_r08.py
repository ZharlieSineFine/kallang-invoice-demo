"""R08: bank account matches the vendor master (digits-only)."""

from invoiceflow.contracts import Severity, TextSource
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


def _scanned(ctx, bank_account, source=TextSource.OCR):
    invoice = ctx.invoice.model_copy(update={"bank_account": bank_account})
    pages = tuple(page.model_copy(update={"source": source}) for page in ctx.document.pages)
    document = ctx.document.model_copy(update={"pages": pages})
    return ctx.model_copy(update={"invoice": invoice, "document": document})


def test_r08_treats_one_digit_off_on_a_scan_as_a_possible_misread(clean_ctx, rules_config):
    findings = R08(rules_config).check(_scanned(clean_ctx, "9001234567"))
    assert [finding.severity for finding in findings] == [Severity.FLAG]
    assert "misread" in findings[0].message


def test_r08_holds_two_digits_off_on_a_scan(clean_ctx, rules_config):
    findings = R08(rules_config).check(_scanned(clean_ctx, "9901234567"))
    assert [finding.severity for finding in findings] == [Severity.HOLD]


def test_r08_holds_one_digit_off_on_a_digital_pdf(clean_ctx, rules_config):
    findings = R08(rules_config).check(_scanned(clean_ctx, "9001234567", TextSource.PDF_TEXT))
    assert [finding.severity for finding in findings] == [Severity.HOLD]


def test_r08_holds_a_scan_with_a_different_length_account(clean_ctx, rules_config):
    findings = R08(rules_config).check(_scanned(clean_ctx, "00012345678"))
    assert [finding.severity for finding in findings] == [Severity.HOLD]
