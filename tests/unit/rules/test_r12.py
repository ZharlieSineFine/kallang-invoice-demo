"""R12: PO exists, belongs to the vendor, and has enough open amount."""

from decimal import Decimal

from invoiceflow.rules.r12 import R12


def test_r12_passes_clean(clean_ctx, rules_config):
    assert R12(rules_config).check(clean_ctx) == ()


def test_r12_flags_missing_po_number(clean_ctx, rules_config):
    invoice = clean_ctx.invoice.model_copy(update={"po_number": None})
    ctx = clean_ctx.model_copy(update={"invoice": invoice, "purchase_order": None})
    findings = R12(rules_config).check(ctx)
    assert any(f.field == "po_number" for f in findings)


def test_r12_flags_po_not_found(clean_ctx, rules_config):
    ctx = clean_ctx.model_copy(update={"purchase_order": None})
    findings = R12(rules_config).check(ctx)
    assert any(f.field == "po_number" and "not found" in f.message for f in findings)


def test_r12_flags_wrong_vendor(clean_ctx, rules_config):
    po = clean_ctx.purchase_order.model_copy(update={"vendor_id": "V999"})
    ctx = clean_ctx.model_copy(update={"purchase_order": po})
    findings = R12(rules_config).check(ctx)
    flagged = [f for f in findings if f.field == "po_number" and "belongs to vendor" in f.message]
    assert flagged
    # Names, not just opaque IDs: the audience can see who the vendors are.
    assert "Stagecraft AV Rentals Pte. Ltd. (V001)" in flagged[0].message
    assert flagged[0].evidence["invoice_vendor_name"] == "Stagecraft AV Rentals Pte. Ltd."


def test_r12_flags_insufficient_open_amount(clean_ctx, rules_config):
    po = clean_ctx.purchase_order.model_copy(update={"open_amount": Decimal("100.00")})
    ctx = clean_ctx.model_copy(update={"purchase_order": po})
    findings = R12(rules_config).check(ctx)
    flagged = [f for f in findings if f.field == "total"]
    assert flagged
    finding = flagged[0]
    # The card must show the whole arithmetic so the audience can see where "open" came from.
    assert "already invoiced" in finding.message
    assert "Stagecraft AV Rentals Pte. Ltd." in finding.message
    assert finding.evidence["po_amount"] == "5000.00"
    assert finding.evidence["po_invoiced"] == "4900.00"
    assert finding.evidence["po_open_amount"] == "100.00"
    assert finding.evidence["po_vendor_name"] == "Stagecraft AV Rentals Pte. Ltd."
