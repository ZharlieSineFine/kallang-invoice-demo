"""Review-time arithmetic checks (the temporary stand-in for pipeline.recheck)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.recheck import RecheckInput, recheck, recompute_findings, route
from invoiceflow.contracts import DocStatus, DocType, Severity


def test_mismatch_subtotal_fires_r02(mismatch_bundle, rules_config):
    state = RecheckInput.from_bundle(mismatch_bundle, rules_config)
    result = recheck(state)
    assert result.status is DocStatus.NEEDS_REVIEW
    assert [finding.rule_id for finding in result.findings] == ["R02"]
    assert result.findings[0].field == "subtotal"
    assert result.findings[0].severity is Severity.FLAG
    assert result.findings[0].evidence == {"lines_sum": "1080.00", "subtotal": "1090.00"}


def test_corrected_subtotal_clears_r02(mismatch_bundle, rules_config):
    corrected = RecheckInput(
        invoice_number="SAV-2026-0413",
        document_type=DocType.TAX_INVOICE,
        subtotal=Decimal("1080.00"),
        gst_amount=Decimal("97.20"),
        total=Decimal("1177.20"),
        line_amounts=(Decimal("540.00"), Decimal("300.00"), Decimal("160.00"), Decimal("80.00")),
        rules_config=rules_config,
    )
    result = recheck(corrected)
    assert result.findings == ()
    assert result.status is DocStatus.AUTO_PASSED


def test_correcting_subtotal_alone_reveals_r03(mismatch_bundle, rules_config):
    state = RecheckInput(
        document_type=DocType.TAX_INVOICE,
        subtotal=Decimal("1080.00"),
        gst_amount=Decimal("98.10"),
        total=Decimal("1188.10"),
        line_amounts=(Decimal("1080.00"),),
        rules_config=rules_config,
    )
    result = recheck(state)
    assert [finding.rule_id for finding in result.findings] == ["R03"]
    assert result.findings[0].field == "total"


def test_clean_invoice_has_no_findings(clean_bundle, rules_config):
    result = recheck(RecheckInput.from_bundle(clean_bundle, rules_config))
    assert result.findings == ()
    assert result.status is DocStatus.AUTO_PASSED


def test_pilot_mode_sends_clean_invoices_to_review(clean_bundle, rules_config):
    config = dict(rules_config)
    config["routing"] = {"auto_approve_clean": False}
    result = recheck(RecheckInput.from_bundle(clean_bundle, config))
    assert result.status is DocStatus.NEEDS_REVIEW


def test_configured_severity_changes_the_status(rules_config):
    config = dict(rules_config)
    config["severities"] = {**rules_config["severities"], "R02": "HOLD"}
    state = RecheckInput(
        subtotal=Decimal("1090.00"),
        line_amounts=(Decimal("1080.00"),),
        rules_config=config,
    )
    result = recheck(state)
    assert result.findings[0].severity is Severity.HOLD
    assert result.status is DocStatus.ON_HOLD


def test_statement_is_not_an_invoice(rules_config):
    state = RecheckInput(document_type=DocType.STATEMENT, rules_config=rules_config)
    result = recheck(state)
    assert result.status is DocStatus.NOT_INVOICE


def test_route_takes_the_worst_severity():
    from invoiceflow.contracts import Finding, Scope

    def finding(severity):
        return Finding(
            rule_id="R05",
            rule_version="v",
            severity=severity,
            scope=Scope.DOCUMENT,
            message="m",
        )

    config = {"routing": {"auto_approve_clean": True}}
    assert route((), rules_config=config) is DocStatus.AUTO_PASSED
    assert route((finding(Severity.FLAG),), rules_config=config) is DocStatus.NEEDS_REVIEW
    assert (
        route((finding(Severity.FLAG), finding(Severity.HOLD)), rules_config=config)
        is DocStatus.ON_HOLD
    )


@pytest.mark.parametrize(
    ("subtotal", "amounts", "expected"),
    [
        (None, (Decimal("1"),), ()),
        (Decimal("10.00"), (), ()),
        (Decimal("10.04"), (Decimal("10.00"),), ()),
        (Decimal("10.06"), (Decimal("10.00"),), ("R02",)),
    ],
)
def test_tolerance_and_missing_values(rules_config, subtotal, amounts, expected):
    findings = recompute_findings(
        RecheckInput(subtotal=subtotal, line_amounts=amounts, rules_config=rules_config)
    )
    assert tuple(finding.rule_id for finding in findings) == expected
