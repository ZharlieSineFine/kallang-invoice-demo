"""R08: the bank account matches the vendor master (digits-only comparison)."""

from __future__ import annotations

from invoiceflow.contracts import CheckContext, Finding, Scope
from invoiceflow.rules.base import BaseRule, digits_only


class R08(BaseRule):
    rule_id = "R08"

    def check(self, ctx: CheckContext) -> tuple[Finding, ...]:
        invoice = ctx.invoice
        if invoice is None or ctx.vendor is None:
            return ()
        if not invoice.bank_account:
            return ()  # a missing account is caught by the other checks, not a mismatch
        invoice_digits = digits_only(invoice.bank_account)
        vendor_digits = digits_only(ctx.vendor.bank_account)
        if vendor_digits and invoice_digits != vendor_digits:
            return (
                self.finding(
                    severity=None,
                    scope=Scope.FIELD,
                    field="bank_account",
                    message="The bank account differs from the vendor master",
                    evidence={
                        "invoice_bank_account": invoice_digits,
                        "vendor_bank_account": vendor_digits,
                    },
                ),
            )
        return ()
