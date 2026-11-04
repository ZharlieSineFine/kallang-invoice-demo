"""R10: document type — invoice, credit note, statement, quotation, or other."""

from __future__ import annotations

from invoiceflow.contracts import CheckContext, DocType, Finding, Scope
from invoiceflow.rules.base import BaseRule

# Types the router must send to NOT_INVOICE (mirrors the routing table in the build plan).
_NON_INVOICE = {DocType.STATEMENT, DocType.QUOTATION, DocType.DELIVERY_ORDER}


class R10(BaseRule):
    rule_id = "R10"

    def check(self, ctx: CheckContext) -> tuple[Finding, ...]:
        invoice = ctx.invoice
        if invoice is None:
            return ()
        doc_type = invoice.document_type
        if doc_type is None:
            return (
                self.finding(
                    severity=None,
                    scope=Scope.DOCUMENT,
                    message="Document type could not be determined",
                ),
            )
        if doc_type in _NON_INVOICE:
            label = doc_type.value.lower().replace("_", " ")
            return (
                self.finding(
                    severity=None,
                    scope=Scope.DOCUMENT,
                    message=f"This document is a {label}, not an invoice",
                    evidence={"document_type": doc_type.value},
                ),
            )
        if doc_type is DocType.OTHER:
            return (
                self.finding(
                    severity=None,
                    scope=Scope.DOCUMENT,
                    message="Unrecognised document type",
                    evidence={"document_type": doc_type.value},
                ),
            )
        return ()
