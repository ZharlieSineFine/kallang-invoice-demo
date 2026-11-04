"""R06: every SAP-required column can be filled after mapping."""

from invoiceflow.rules.r06 import R06


def test_r06_passes_clean(clean_ctx, rules_config):
    assert R06(rules_config).check(clean_ctx) == ()


def test_r06_flags_missing_coding_lines(clean_ctx, rules_config):
    ctx = clean_ctx.model_copy(update={"coding_lines": ()})
    findings = R06(rules_config).check(ctx)
    assert any("No coding lines" in f.message for f in findings)


def test_r06_flags_missing_gl_cost_center_tax(clean_ctx, rules_config):
    line = clean_ctx.coding_lines[0].model_copy(
        update={"gl_account": None, "cost_center": None, "tax_code": None}
    )
    ctx = clean_ctx.model_copy(update={"coding_lines": (line,)})
    findings = R06(rules_config).check(ctx)
    fields = {f.field for f in findings}
    assert "coding_lines[0].gl_account" in fields
    assert "coding_lines[0].cost_center" in fields
    assert "coding_lines[0].tax_code" in fields


def test_r06_flags_missing_sap_vendor_no(clean_ctx, rules_config):
    vendor = clean_ctx.vendor.model_copy(update={"sap_vendor_no": ""})
    ctx = clean_ctx.model_copy(update={"vendor": vendor})
    findings = R06(rules_config).check(ctx)
    assert any(f.field == "sap_vendor_no" for f in findings)


def test_r06_flags_missing_header_columns(clean_ctx, rules_config):
    invoice = clean_ctx.invoice.model_copy(update={"invoice_date": None, "currency": None})
    ctx = clean_ctx.model_copy(update={"invoice": invoice})
    findings = R06(rules_config).check(ctx)
    fields = {f.field for f in findings}
    assert "invoice_date" in fields and "currency" in fields
