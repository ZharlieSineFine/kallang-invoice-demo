"""Router: turns the findings into a DocStatus and per-field confidence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from invoiceflow.contracts import (
    CheckContext,
    DocStatus,
    DocType,
    Finding,
    RoutingDecision,
    Severity,
    max_severity,
)
from invoiceflow.rules.confidence import field_confidences

# Document types that are not an invoice (R10; the router also sends OTHER here).
_NOT_INVOICE = {DocType.STATEMENT, DocType.QUOTATION, DocType.DELIVERY_ORDER, DocType.OTHER}

_STATUS_BY_SEVERITY = {
    Severity.FLAG: DocStatus.NEEDS_REVIEW,
    Severity.HOLD: DocStatus.ON_HOLD,
    Severity.MANUAL: DocStatus.MANUAL_ENTRY,
}


class Router:
    """Highest severity decides the status; confidence comes from the checks."""

    def __init__(self, rules_config: Mapping[str, Any] | None = None) -> None:
        routing = (rules_config or {}).get("routing", {})
        self.auto_approve_clean = bool(routing.get("auto_approve_clean", True))

    def route(self, ctx: CheckContext, findings: tuple[Finding, ...]) -> RoutingDecision:
        reasons = tuple(
            f"{f.rule_id}: {f.message}" for f in findings if f.severity.rank >= Severity.FLAG.rank
        )
        return RoutingDecision(
            status=self._status(ctx, findings),
            reasons=reasons,
            confidences=field_confidences(ctx, findings),
        )

    def _status(self, ctx: CheckContext, findings: tuple[Finding, ...]) -> DocStatus:
        invoice = ctx.invoice
        if invoice is None:
            return DocStatus.MANUAL_ENTRY
        if invoice.document_type in _NOT_INVOICE:
            return DocStatus.NOT_INVOICE
        worst = max_severity(tuple(f.severity for f in findings))
        if worst is None or worst is Severity.INFO:
            # In a pilot, auto_approve_clean: false sends every clean invoice to review.
            return DocStatus.AUTO_PASSED if self.auto_approve_clean else DocStatus.NEEDS_REVIEW
        return _STATUS_BY_SEVERITY[worst]
