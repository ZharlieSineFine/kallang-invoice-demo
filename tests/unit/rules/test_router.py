"""The router turns findings into a status and confidence."""

from decimal import Decimal

import pytest

from invoiceflow.contracts import DocStatus, DocType, Finding, Scope, Severity
from invoiceflow.rules import Router


def _finding(rule_id="R01", severity=Severity.FLAG, field=None, message="m"):
    return Finding(
        rule_id=rule_id,
        rule_version="t",
        severity=severity,
        scope=Scope.FIELD if field else Scope.DOCUMENT,
        field=field,
        message=message,
    )


@pytest.mark.parametrize(
    ("severity", "status"),
    [
        (Severity.INFO, DocStatus.AUTO_PASSED),
        (Severity.FLAG, DocStatus.NEEDS_REVIEW),
        (Severity.HOLD, DocStatus.ON_HOLD),
        (Severity.MANUAL, DocStatus.MANUAL_ENTRY),
    ],
)
def test_highest_severity_decides(clean_ctx, rules_config, severity, status):
    decision = Router(rules_config).route(
        clean_ctx, (_finding("R05", Severity.INFO), _finding("R05", severity))
    )
    assert decision.status is status


def test_info_findings_are_not_reasons(clean_ctx, rules_config):
    decision = Router(rules_config).route(clean_ctx, (_finding(severity=Severity.INFO),))
    assert decision.reasons == ()


def test_flagged_findings_become_reasons(clean_ctx, rules_config):
    decision = Router(rules_config).route(clean_ctx, (_finding(message="boom"),))
    assert decision.reasons == ("R01: boom",)


def test_pilot_mode_sends_clean_to_review(clean_ctx, rules_config):
    pilot = dict(rules_config)
    pilot["routing"] = {**rules_config["routing"], "auto_approve_clean": False}
    decision = Router(pilot).route(clean_ctx, ())
    assert decision.status is DocStatus.NEEDS_REVIEW


@pytest.mark.parametrize("doc_type", [DocType.STATEMENT, DocType.QUOTATION, DocType.DELIVERY_ORDER])
def test_not_an_invoice(clean_ctx, rules_config, doc_type):
    invoice = clean_ctx.invoice.model_copy(update={"document_type": doc_type})
    ctx = clean_ctx.model_copy(update={"invoice": invoice})
    assert Router(rules_config).route(ctx, ()).status is DocStatus.NOT_INVOICE


def test_invalid_extraction_is_manual_entry(clean_ctx, rules_config):
    ctx = clean_ctx.model_copy(update={"invoice": None})
    assert Router(rules_config).route(ctx, ()).status is DocStatus.MANUAL_ENTRY


# The auto-pass value limit (CR-012): at or above it, a clean invoice still goes to a person.
def _priced(ctx, total, *, currency="SGD", sgd_total=None):
    invoice = ctx.invoice.model_copy(
        update={"total": Decimal(total), "currency": currency, "sgd_total": sgd_total}
    )
    return ctx.model_copy(update={"invoice": invoice})


def test_the_configured_limit_is_5000(rules_config):
    assert Router(rules_config).auto_pass_limit == Decimal("5000.00")


def test_a_clean_invoice_below_the_limit_passes(clean_ctx, rules_config):
    decision = Router(rules_config).route(_priced(clean_ctx, "4999.99"), ())
    assert decision.status is DocStatus.AUTO_PASSED
    assert decision.reasons == ()


def test_a_clean_invoice_at_the_limit_goes_to_a_person(clean_ctx, rules_config):
    decision = Router(rules_config).route(_priced(clean_ctx, "5000.00"), ())
    assert decision.status is DocStatus.NEEDS_REVIEW
    assert decision.reasons == (
        "At or above the S$5,000.00 auto-pass limit: every check passed, "
        "but an invoice this large needs a person.",
    )


def test_a_foreign_invoice_is_compared_in_sgd(clean_ctx, rules_config):
    small = _priced(clean_ctx, "6000.00", currency="USD", sgd_total=Decimal("4800.00"))
    large = _priced(clean_ctx, "4000.00", currency="USD", sgd_total=Decimal("5200.00"))
    assert Router(rules_config).route(small, ()).status is DocStatus.AUTO_PASSED
    assert Router(rules_config).route(large, ()).status is DocStatus.NEEDS_REVIEW


def test_a_large_credit_note_goes_to_a_person(clean_ctx, rules_config):
    decision = Router(rules_config).route(_priced(clean_ctx, "-6000.00"), ())
    assert decision.status is DocStatus.NEEDS_REVIEW


def test_findings_decide_before_the_limit(clean_ctx, rules_config):
    decision = Router(rules_config).route(
        _priced(clean_ctx, "9000.00"), (_finding("R08", Severity.HOLD, message="bank"),)
    )
    assert decision.status is DocStatus.ON_HOLD
    assert decision.reasons == ("R08: bank",)


def test_no_limit_configured_means_none_applies(clean_ctx, rules_config):
    unlimited = dict(rules_config)
    unlimited["routing"] = {"auto_approve_clean": True}
    decision = Router(unlimited).route(_priced(clean_ctx, "99999.00"), ())
    assert decision.status is DocStatus.AUTO_PASSED
