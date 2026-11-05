"""R12: the PO exists, belongs to the same vendor, and has enough open amount left."""

from __future__ import annotations

from invoiceflow.contracts import CheckContext, Finding, Scope
from invoiceflow.rules.base import BaseRule, fmt2, money_sgd


class R12(BaseRule):
    rule_id = "R12"

    def check(self, ctx: CheckContext) -> tuple[Finding, ...]:
        invoice = ctx.invoice
        if invoice is None:
            return ()
        findings: list[Finding] = []
        po = ctx.purchase_order

        if not invoice.po_number:
            findings.append(
                self.finding(
                    severity=None,
                    scope=Scope.FIELD,
                    field="po_number",
                    message="No purchase order number on the invoice",
                )
            )
        elif po is None:
            findings.append(
                self.finding(
                    severity=None,
                    scope=Scope.FIELD,
                    field="po_number",
                    message=f"Purchase order {invoice.po_number} was not found",
                    evidence={"po_number": invoice.po_number},
                )
            )
        else:
            po_vendor = ctx.master.vendor(po.vendor_id)
            po_vendor_label = (
                f"{po_vendor.name} ({po.vendor_id})" if po_vendor is not None else po.vendor_id
            )
            if ctx.vendor is not None and po.vendor_id != ctx.vendor.vendor_id:
                invoice_vendor_label = (
                    f"{ctx.vendor.name} ({ctx.vendor.vendor_id})"
                    if ctx.vendor.name
                    else ctx.vendor.vendor_id
                )
                findings.append(
                    self.finding(
                        severity=None,
                        scope=Scope.FIELD,
                        field="po_number",
                        message=(
                            f"Purchase order {po.po_number} belongs to vendor "
                            f"{po_vendor_label}, not {invoice_vendor_label}"
                        ),
                        evidence={
                            "po_number": po.po_number,
                            "po_vendor_name": po_vendor.name if po_vendor else po.vendor_id,
                            "po_vendor_id": po.vendor_id,
                            "invoice_vendor_name": ctx.vendor.name or ctx.vendor.vendor_id,
                            "invoice_vendor_id": ctx.vendor.vendor_id,
                        },
                    )
                )
            if invoice.total is not None and po.open_amount < invoice.total:
                already_invoiced = po.amount - po.open_amount
                findings.append(
                    self.finding(
                        severity=None,
                        scope=Scope.FIELD,
                        field="total",
                        message=(
                            f"Purchase order {po.po_number} (vendor {po_vendor_label}) has "
                            f"{money_sgd(po.open_amount)} open (PO total "
                            f"{money_sgd(po.amount)} minus {money_sgd(already_invoiced)} "
                            f"already invoiced), less than the invoice total "
                            f"{money_sgd(invoice.total)}"
                        ),
                        evidence={
                            "po_number": po.po_number,
                            "po_vendor_name": po_vendor.name if po_vendor else po.vendor_id,
                            "po_amount": fmt2(po.amount),
                            "po_invoiced": fmt2(already_invoiced),
                            "po_open_amount": fmt2(po.open_amount),
                            "invoice_total": fmt2(invoice.total),
                        },
                    )
                )

        return tuple(findings)
