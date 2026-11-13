"""R10: document type — invoice, credit note, statement, quotation, or other."""

from __future__ import annotations

import re

from invoiceflow.contracts import CheckContext, DocType, Finding, Scope, Severity
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
        if doc_type is DocType.CREDIT_NOTE:
            return (self._credit_note(ctx),)
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

    def _credit_note(self, ctx: CheckContext) -> Finding:
        """IRAS: a credit note quotes the invoice it corrects. It must be on file for the vendor."""
        quoted = ctx.invoice.original_invoice_ref
        if not quoted:
            return self.finding(
                severity=Severity.FLAG,
                scope=Scope.FIELD,
                field="original_invoice_ref",
                message="This credit note does not quote the invoice it corrects",
            )
        vendor_id = ctx.vendor.vendor_id if ctx.vendor is not None else None
        original = next(
            (
                prior
                for prior in ctx.prior_invoices
                if prior.vendor_id == vendor_id
                and _reference_key(prior.invoice_number) == _reference_key(quoted)
            ),
            None,
        )
        if original is None:
            return self.finding(
                severity=Severity.FLAG,
                scope=Scope.FIELD,
                field="original_invoice_ref",
                message=(
                    f"This credit note quotes invoice {quoted}, which is not on file "
                    "for this vendor"
                ),
                evidence={"original_invoice_ref": quoted},
            )
        return self.finding(
            severity=None,
            scope=Scope.DOCUMENT,
            message=f"This document is a credit note for invoice {original.invoice_number}",
            evidence={
                "document_type": DocType.CREDIT_NOTE.value,
                "original_invoice_ref": original.invoice_number or quoted,
            },
        )


def _reference_key(value: str | None) -> str:
    """Invoice numbers compared on letters and digits only: SAV-2026-1001 == SAV20261001."""
    return re.sub(r"[^0-9A-Z]", "", (value or "").upper())
