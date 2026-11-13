"""R10: document type classification."""

from datetime import date
from decimal import Decimal
from uuid import uuid4

from invoiceflow.contracts import DocType, PriorInvoice, Severity
from invoiceflow.rules.r10 import R10


def test_r10_passes_invoice(clean_ctx, rules_config):
    assert R10(rules_config).check(clean_ctx) == ()


def _credit_note(ctx, original, prior_number="SAV-2026-0412", prior_vendor="V001"):
    """A credit note quoting ``original``, with one earlier invoice on file."""
    invoice = ctx.invoice.model_copy(
        update={"document_type": DocType.CREDIT_NOTE, "original_invoice_ref": original}
    )
    prior = PriorInvoice(
        doc_id=uuid4(),
        vendor_id=prior_vendor,
        invoice_number=prior_number,
        total=Decimal("1000.00"),
        invoice_date=date(2026, 10, 1),
        file_sha256="0" * 64,
    )
    return ctx.model_copy(update={"invoice": invoice, "prior_invoices": (prior,)})


def test_r10_notes_a_credit_note_for_an_invoice_on_file(clean_ctx, rules_config):
    findings = R10(rules_config).check(_credit_note(clean_ctx, "SAV20260412"))
    assert [f.severity for f in findings] == [Severity.INFO]
    assert "SAV-2026-0412" in findings[0].message


def test_r10_flags_a_credit_note_that_quotes_no_invoice(clean_ctx, rules_config):
    findings = R10(rules_config).check(_credit_note(clean_ctx, None))
    assert [f.severity for f in findings] == [Severity.FLAG]
    assert findings[0].field == "original_invoice_ref"


def test_r10_flags_a_credit_note_for_an_invoice_not_on_file(clean_ctx, rules_config):
    other_vendor = _credit_note(clean_ctx, "SAV-2026-0412", prior_vendor="V002")
    findings = R10(rules_config).check(other_vendor)
    assert [f.severity for f in findings] == [Severity.FLAG]
    assert "not on file" in findings[0].message


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
