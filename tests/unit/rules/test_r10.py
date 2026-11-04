"""R10: document type classification."""

from invoiceflow.contracts import DocType
from invoiceflow.rules.r10 import R10


def test_r10_passes_invoice(clean_ctx, rules_config):
    assert R10(rules_config).check(clean_ctx) == ()


def test_r10_passes_credit_note(clean_ctx, rules_config):
    invoice = clean_ctx.invoice.model_copy(update={"document_type": DocType.CREDIT_NOTE})
    ctx = clean_ctx.model_copy(update={"invoice": invoice})
    assert R10(rules_config).check(ctx) == ()


def test_r10_flags_statement(clean_ctx, rules_config):
    invoice = clean_ctx.invoice.model_copy(update={"document_type": DocType.STATEMENT})
    ctx = clean_ctx.model_copy(update={"invoice": invoice})
    findings = R10(rules_config).check(ctx)
    assert len(findings) == 1 and "statement" in findings[0].message


def test_r10_flags_unknown_type(clean_ctx, rules_config):
    invoice = clean_ctx.invoice.model_copy(update={"document_type": None})
    ctx = clean_ctx.model_copy(update={"invoice": invoice})
    findings = R10(rules_config).check(ctx)
    assert any("could not be determined" in f.message for f in findings)


def test_r10_flags_other(clean_ctx, rules_config):
    invoice = clean_ctx.invoice.model_copy(update={"document_type": DocType.OTHER})
    ctx = clean_ctx.model_copy(update={"invoice": invoice})
    findings = R10(rules_config).check(ctx)
    assert any("Unrecognised" in f.message for f in findings)
