"""Router: turns the findings into a DocStatus and per-field confidence."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from invoiceflow.contracts import (
    CheckContext,
    DocStatus,
    Finding,
    NormalizedInvoice,
    RoutingDecision,
    Severity,
    max_severity,
)
from invoiceflow.rules.base import NOT_INVOICE_TYPES
from invoiceflow.rules.confidence import field_confidences

_STATUS_BY_SEVERITY = {
    Severity.FLAG: DocStatus.NEEDS_REVIEW,
    Severity.HOLD: DocStatus.ON_HOLD,
    Severity.MANUAL: DocStatus.MANUAL_ENTRY,
}


def limit_reason(limit: Decimal) -> str:
    return (
        f"At or above the S${limit:,.2f} auto-pass limit: every check passed, "
        "but an invoice this large needs a person."
    )


def _sgd_amount(invoice: NormalizedInvoice) -> Decimal | None:
    """The amount the limit is compared with: the SGD total, and a credit note's size."""
    foreign = invoice.currency not in (None, "SGD")
    amount = invoice.sgd_total if foreign and invoice.sgd_total is not None else invoice.total
    return abs(amount) if amount is not None else None


class Router:
    """Highest severity decides the status; confidence comes from the checks.

    A clean invoice at or above ``routing.auto_pass_limit_sgd`` still goes to a person
    (CR-012): finance approves large amounts even when every check passes."""

    def __init__(self, rules_config: Mapping[str, Any] | None = None) -> None:
        routing = (rules_config or {}).get("routing", {})
        self.auto_approve_clean = bool(routing.get("auto_approve_clean", True))
        limit = routing.get("auto_pass_limit_sgd")
        self.auto_pass_limit = Decimal(str(limit)) if limit is not None else None

    def route(self, ctx: CheckContext, findings: tuple[Finding, ...]) -> RoutingDecision:
        reasons = tuple(
            f"{f.rule_id}: {f.message}" for f in findings if f.severity.rank >= Severity.FLAG.rank
        )
        status = self._status(ctx, findings)
        if status is DocStatus.AUTO_PASSED and self._over_limit(ctx.invoice):
            status = DocStatus.NEEDS_REVIEW
            reasons = (*reasons, limit_reason(self.auto_pass_limit))
        return RoutingDecision(
            status=status,
            reasons=reasons,
            confidences=field_confidences(ctx, findings),
        )

    def _over_limit(self, invoice: NormalizedInvoice | None) -> bool:
        if self.auto_pass_limit is None or invoice is None:
            return False
        amount = _sgd_amount(invoice)
        return amount is not None and amount >= self.auto_pass_limit

    def _status(self, ctx: CheckContext, findings: tuple[Finding, ...]) -> DocStatus:
        invoice = ctx.invoice
        if invoice is None:
            return DocStatus.MANUAL_ENTRY
        if invoice.document_type in NOT_INVOICE_TYPES:
            return DocStatus.NOT_INVOICE
        worst = max_severity(tuple(f.severity for f in findings))
        if worst is None or worst is Severity.INFO:
            # In a pilot, auto_approve_clean: false sends every clean invoice to review.
            return DocStatus.AUTO_PASSED if self.auto_approve_clean else DocStatus.NEEDS_REVIEW
        return _STATUS_BY_SEVERITY[worst]
