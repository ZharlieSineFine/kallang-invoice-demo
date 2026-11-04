"""The router turns findings into a status and confidence."""

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
