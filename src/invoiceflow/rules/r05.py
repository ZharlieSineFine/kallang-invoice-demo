"""R05: duplicate detection — file hash, vendor + invoice number, or vendor + amount
within the duplicate window."""

from __future__ import annotations

from invoiceflow.contracts import CheckContext, Finding, Scope, Severity
from invoiceflow.rules.base import NOT_INVOICE_TYPES, BaseRule, fmt2, money_sgd


class R05(BaseRule):
    rule_id = "R05"

    def check(self, ctx: CheckContext) -> tuple[Finding, ...]:
        invoice = ctx.invoice
        # A statement lists invoices already on file and is never paid, so it is no duplicate.
        if invoice is None or invoice.document_type in NOT_INVOICE_TYPES:
            return ()
        window = int(self._config["duplicate_window_days"])
        findings: list[Finding] = []
        vendor_label = (
            f"{ctx.vendor.name} ({ctx.vendor.vendor_id})"
            if ctx.vendor is not None and ctx.vendor.name
            else (ctx.vendor.vendor_id if ctx.vendor is not None else "unknown vendor")
        )

        # Same file hash — the exact same bytes were already processed.
        for prior in ctx.prior_invoices:
            if prior.file_sha256 == ctx.file_sha256:
                findings.append(
                    self.finding(
                        severity=Severity.HOLD,
                        scope=Scope.DOCUMENT,
                        message="The same file was already processed",
                        evidence={"file_sha256": ctx.file_sha256},
                    )
                )
                break

        # Same vendor + same invoice number.
        if ctx.vendor is not None and invoice.invoice_number:
            for prior in ctx.prior_invoices:
                if (
                    prior.vendor_id == ctx.vendor.vendor_id
                    and prior.invoice_number == invoice.invoice_number
                ):
                    findings.append(
                        self.finding(
                            severity=Severity.HOLD,
                            scope=Scope.DOCUMENT,
                            field="invoice_number",
                            message=f"{vendor_label} already has invoice {invoice.invoice_number}",
                            evidence={
                                "vendor_name": ctx.vendor.name or ctx.vendor.vendor_id,
                                "vendor_id": ctx.vendor.vendor_id,
                                "invoice_number": invoice.invoice_number,
                            },
                        )
                    )
                    break

        # Same vendor + same amount within the duplicate window.
        if (
            ctx.vendor is not None
            and invoice.total is not None
            and invoice.invoice_date is not None
        ):
            for prior in ctx.prior_invoices:
                if prior.vendor_id != ctx.vendor.vendor_id or prior.total != invoice.total:
                    continue
                if prior.invoice_date is None:
                    continue
                if abs((invoice.invoice_date - prior.invoice_date).days) <= window:
                    evidence = {
                        "vendor_name": ctx.vendor.name or ctx.vendor.vendor_id,
                        "vendor_id": ctx.vendor.vendor_id,
                        "total": fmt2(invoice.total),
                        "window_days": str(window),
                    }
                    if prior.invoice_number:
                        evidence["prior_invoice_number"] = prior.invoice_number
                    if prior.invoice_date is not None:
                        evidence["prior_invoice_date"] = prior.invoice_date.isoformat()
                    findings.append(
                        self.finding(
                            severity=Severity.HOLD,
                            scope=Scope.DOCUMENT,
                            field="total",
                            message=(
                                f"{vendor_label} already has a {money_sgd(invoice.total)} "
                                f"invoice within {window} days"
                            ),
                            evidence=evidence,
                        )
                    )
                    break

        return tuple(findings)
