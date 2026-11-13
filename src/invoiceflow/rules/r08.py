"""R08: the bank account matches the vendor master (digits-only comparison).

A difference is a hold, because changed bank details are a known fraud pattern. The one
exception is a single wrong digit on a scanned page: text recognition misreads digits, so that
case is flagged for a person to compare against the page. It still cannot pass unreviewed.
"""

from __future__ import annotations

from invoiceflow.contracts import CheckContext, Finding, Scope, Severity, TextSource
from invoiceflow.rules.base import BaseRule, digits_only


def _one_digit_apart(left: str, right: str) -> bool:
    return len(left) == len(right) and sum(a != b for a, b in zip(left, right, strict=True)) == 1


def _possible_misread(ctx: CheckContext, invoice_digits: str, vendor_digits: str) -> bool:
    scanned = any(page.source is TextSource.OCR for page in ctx.document.pages)
    return scanned and _one_digit_apart(invoice_digits, vendor_digits)


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
        if not vendor_digits or invoice_digits == vendor_digits:
            return ()
        misread = _possible_misread(ctx, invoice_digits, vendor_digits)
        return (
            self.finding(
                severity=Severity.FLAG if misread else None,
                scope=Scope.FIELD,
                field="bank_account",
                message=(
                    "One digit of the bank account differs from the vendor master on a scanned "
                    "page. This may be a misread: compare it with the page."
                    if misread
                    else "The bank account differs from the vendor master"
                ),
                evidence={
                    "invoice_bank_account": invoice_digits,
                    "vendor_bank_account": vendor_digits,
                },
            ),
        )
