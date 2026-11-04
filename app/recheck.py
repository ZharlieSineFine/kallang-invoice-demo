"""Temporary stand-in for ``pipeline.recheck`` (see docs/contract-requests.md CR-001).

``contracts-v1`` exposes ``pipeline.stages.check_stage`` but its Phase 0 rules replay the
golden fixture's recorded findings, so they cannot see a reviewer's correction. Until the
integrator adds ``pipeline.recheck``, this module recomputes the arithmetic checks (R02
lines-vs-subtotal and R03 subtotal-plus-GST-vs-total) from the *current* stored values and
routes them with the configured severities.

It is deliberately small: WS5 owns the full R01-R12 rule set. Every caller goes through
``recheck()`` so swapping in the real pipeline function is one change.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.formatting import parse_decimal
from app.models import DocumentBundle
from invoiceflow.contracts import (
    DocStatus,
    DocType,
    Finding,
    Scope,
    Severity,
    money,
)

_SEVERITY_ORDER = {
    Severity.INFO: 0,
    Severity.FLAG: 1,
    Severity.HOLD: 2,
    Severity.MANUAL: 3,
}
_STATUS_BY_SEVERITY = {
    Severity.FLAG: DocStatus.NEEDS_REVIEW,
    Severity.HOLD: DocStatus.ON_HOLD,
    Severity.MANUAL: DocStatus.MANUAL_ENTRY,
}
_NOT_INVOICES = frozenset(
    {DocType.STATEMENT, DocType.QUOTATION, DocType.DELIVERY_ORDER, DocType.OTHER}
)
RULE_VERSION = "app-recheck-v1"


@dataclass(frozen=True)
class RecheckInput:
    """The current values a review-time check may read."""

    invoice_number: str | None = None
    document_type: DocType | None = None
    subtotal: Decimal | None = None
    gst_amount: Decimal | None = None
    total: Decimal | None = None
    line_amounts: tuple[Decimal, ...] = ()
    rules_config: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_bundle(cls, bundle: DocumentBundle, rules_config: Mapping[str, Any]) -> RecheckInput:
        def value(name: str) -> Decimal | None:
            field = bundle.field(name)
            return None if field is None else parse_decimal(field.value_norm)

        amounts = tuple(item.amount for item in bundle.line_items if item.amount is not None)
        return cls(
            invoice_number=bundle.document.invoice_number,
            document_type=bundle.document.doc_type,
            subtotal=value("subtotal"),
            gst_amount=value("gst_amount"),
            total=value("total"),
            line_amounts=amounts,
            rules_config=rules_config,
        )


@dataclass(frozen=True)
class RecheckResult:
    findings: tuple[Finding, ...]
    status: DocStatus
    reasons: tuple[str, ...] = ()


def _tolerance(config: Mapping[str, Any], name: str, default: str) -> Decimal:
    raw = (config.get("tolerances") or {}).get(name, default)
    return Decimal(str(raw))


def _severity(config: Mapping[str, Any], rule_id: str, default: Severity) -> Severity:
    raw = (config.get("severities") or {}).get(rule_id)
    try:
        return Severity(raw) if raw is not None else default
    except ValueError:
        return default


def _finding(rule_id: str, severity: Severity, field_name: str, message: str, **evidence: str):
    return Finding(
        rule_id=rule_id,
        rule_version=RULE_VERSION,
        severity=severity,
        scope=Scope.FIELD,
        field=field_name,
        message=message,
        evidence=evidence,
        stage="REVIEW",
    )


def recompute_findings(state: RecheckInput) -> tuple[Finding, ...]:
    """Arithmetic checks that can change when a reviewer edits a value."""
    config = state.rules_config
    findings: list[Finding] = []
    if state.subtotal is not None and state.line_amounts:
        lines_sum = money(sum(state.line_amounts, Decimal("0")))
        tolerance = _tolerance(config, "lines_vs_subtotal", "0.05")
        if abs(lines_sum - state.subtotal) > tolerance:
            findings.append(
                _finding(
                    "R02",
                    _severity(config, "R02", Severity.FLAG),
                    "subtotal",
                    (
                        f"The line items add up to S${lines_sum:,.2f}, "
                        f"but the subtotal reads S${state.subtotal:,.2f}."
                    ),
                    lines_sum=f"{lines_sum:.2f}",
                    subtotal=f"{state.subtotal:.2f}",
                )
            )
    if state.subtotal is not None and state.gst_amount is not None and state.total is not None:
        expected = money(state.subtotal + state.gst_amount)
        tolerance = _tolerance(config, "subtotal_plus_gst", "0.01")
        if abs(expected - state.total) > tolerance:
            findings.append(
                _finding(
                    "R03",
                    _severity(config, "R03", Severity.FLAG),
                    "total",
                    (
                        f"The subtotal plus GST is S${expected:,.2f}, "
                        f"but the total reads S${state.total:,.2f}."
                    ),
                    expected=f"{expected:.2f}",
                    total=f"{state.total:.2f}",
                )
            )
    return tuple(findings)


def route(findings: tuple[Finding, ...], *, rules_config: Mapping[str, Any]) -> DocStatus:
    auto_approve = bool((rules_config.get("routing") or {}).get("auto_approve_clean", True))
    worst = max((f.severity for f in findings), key=lambda s: _SEVERITY_ORDER[s], default=None)
    if worst is None or worst is Severity.INFO:
        return DocStatus.AUTO_PASSED if auto_approve else DocStatus.NEEDS_REVIEW
    return _STATUS_BY_SEVERITY[worst]


def recheck(state: RecheckInput, *, today: date | None = None) -> RecheckResult:
    """Return findings for the current values and the status the router would choose.

    ``today`` is accepted so the future ``pipeline.recheck`` signature (which needs it for
    date checks) does not force callers to change.
    """
    del today  # only R02/R03 here; the real recheck uses it
    if state.document_type in _NOT_INVOICES:
        return RecheckResult((), DocStatus.NOT_INVOICE, ())
    findings = recompute_findings(state)
    reasons = tuple(
        f"{f.rule_id}: {f.message}"
        for f in findings
        if _SEVERITY_ORDER[f.severity] >= _SEVERITY_ORDER[Severity.FLAG]
    )
    return RecheckResult(findings, route(findings, rules_config=state.rules_config), reasons)
