"""R05: duplicate detection on file hash, vendor + number, or vendor + amount."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

from invoiceflow.contracts import PriorInvoice, Severity
from invoiceflow.rules.r05 import R05

_SHA = "a" * 64


def _prior(**kwargs):
    defaults = dict(
        doc_id=uuid4(),
        vendor_id="V001",
        invoice_number="SAV-2026-0001",
        total=Decimal("1177.20"),
        invoice_date=date(2026, 10, 15),
        file_sha256=_SHA,
    )
    defaults.update(kwargs)
    return PriorInvoice(**defaults)


def test_r05_passes_clean(clean_ctx, rules_config):
    assert R05(rules_config).check(clean_ctx) == ()


def test_r05_flags_same_file_hash(clean_ctx, rules_config):
    prior = _prior(file_sha256=clean_ctx.file_sha256, total=Decimal("1.00"))
    ctx = clean_ctx.model_copy(update={"prior_invoices": (prior,)})
    findings = R05(rules_config).check(ctx)
    assert len(findings) == 1 and findings[0].severity is Severity.HOLD


def test_r05_flags_same_vendor_and_number(clean_ctx, rules_config):
    prior = _prior(invoice_number="SAV-2026-0412", total=Decimal("1.00"))
    ctx = clean_ctx.model_copy(update={"prior_invoices": (prior,)})
    findings = R05(rules_config).check(ctx)
    flagged = [f for f in findings if f.field == "invoice_number"]
    assert flagged
    # Names, not opaque IDs.
    assert "Stagecraft AV Rentals Pte. Ltd. (V001)" in flagged[0].message
    assert flagged[0].evidence["vendor_name"] == "Stagecraft AV Rentals Pte. Ltd."


def test_r05_flags_same_vendor_and_amount_in_window(clean_ctx, rules_config):
    prior = _prior(invoice_number="SAV-2026-9999", invoice_date=date(2026, 10, 12))
    ctx = clean_ctx.model_copy(update={"prior_invoices": (prior,)})
    findings = R05(rules_config).check(ctx)
    flagged = [f for f in findings if f.field == "total"]
    assert flagged
    assert "Stagecraft AV Rentals Pte. Ltd. (V001)" in flagged[0].message
    assert flagged[0].evidence["prior_invoice_number"] == "SAV-2026-9999"
    assert flagged[0].evidence["prior_invoice_date"] == "2026-10-12"


def test_r05_ignores_amount_outside_window(clean_ctx, rules_config):
    prior = _prior(invoice_number="SAV-2026-9999", invoice_date=date(2026, 9, 1))
    ctx = clean_ctx.model_copy(update={"prior_invoices": (prior,)})
    assert R05(rules_config).check(ctx) == ()


def test_r05_ignores_prior_without_date(clean_ctx, rules_config):
    prior = _prior(invoice_number="SAV-2026-9999", invoice_date=None)
    ctx = clean_ctx.model_copy(update={"prior_invoices": (prior,)})
    assert R05(rules_config).check(ctx) == ()
