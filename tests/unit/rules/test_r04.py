"""R04: unknown vendor holds; wrong addressee flags."""

from invoiceflow.contracts import Severity
from invoiceflow.rules.r04 import R04


def test_r04_passes_clean(clean_ctx, rules_config):
    assert R04(rules_config).check(clean_ctx) == ()


def test_r04_holds_unknown_vendor(clean_ctx, rules_config):
    ctx = clean_ctx.model_copy(update={"vendor": None})
    findings = R04(rules_config).check(ctx)
    assert len(findings) == 1
    assert findings[0].severity is Severity.HOLD


def test_r04_flags_wrong_addressee(clean_ctx, rules_config):
    invoice = clean_ctx.invoice.model_copy(update={"buyer_name": "Some Other Company Pte Ltd"})
    ctx = clean_ctx.model_copy(update={"invoice": invoice})
    findings = R04(rules_config).check(ctx)
    assert any(f.field == "buyer_name" and f.severity is Severity.FLAG for f in findings)


def test_r04_flags_missing_addressee(clean_ctx, rules_config):
    invoice = clean_ctx.invoice.model_copy(update={"buyer_name": None})
    ctx = clean_ctx.model_copy(update={"invoice": invoice})
    findings = R04(rules_config).check(ctx)
    assert any(f.field == "buyer_name" and f.severity is Severity.FLAG for f in findings)
