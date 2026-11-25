"""R03: GST — registration number, rate for the date, amount arithmetic, simplified and
foreign-currency rules."""

from __future__ import annotations

import re
from decimal import Decimal

from invoiceflow.contracts import CheckContext, DocType, Finding, Scope, money
from invoiceflow.rules.base import (
    BaseRule,
    cfg_decimal,
    fmt2,
    fmt_percent,
    gst_rate_for_date,
    subtotal_includes_gst,
)

# Singapore GST registration numbers are the business UEN: nine digits + checksum letter.
_GST_REG = re.compile(r"^\d{9}[A-Z]$")

_TAX_DOCS = (DocType.TAX_INVOICE, DocType.SIMPLIFIED_TAX_INVOICE)
_ZERO = Decimal("0")


def _out_of_scope_at_zero(ctx: CheckContext) -> bool:
    """A foreign-currency invoice at 0% from a vendor the master marks overseas, the vendors
    coded OP (out of scope for Singapore GST). No GST is due, so 0% is right and there is no
    SGD GST amount to show (user, 2026-11-24, on HAV-2026-6001). Any GST charged is still
    checked, and so is an SGD invoice from an overseas vendor."""
    invoice = ctx.invoice
    return (
        invoice is not None
        and ctx.vendor is not None
        and ctx.vendor.is_overseas
        and bool(invoice.currency)
        and invoice.currency.upper() != "SGD"
        and invoice.gst_rate_percent == _ZERO
        and invoice.gst_amount in (None, _ZERO)
    )


class R03(BaseRule):
    rule_id = "R03"

    def check(self, ctx: CheckContext) -> tuple[Finding, ...]:
        invoice = ctx.invoice
        if invoice is None:
            return ()
        findings: list[Finding] = []
        tax_doc = invoice.document_type in _TAX_DOCS

        # 1. GST registration number present and well formed on a tax document.
        if tax_doc:
            reg = invoice.supplier_gst_reg_no
            if not reg:
                findings.append(
                    self.finding(
                        severity=None,
                        scope=Scope.FIELD,
                        field="supplier_gst_reg_no",
                        message="GST registration number is missing from the tax invoice",
                    )
                )
            elif not _GST_REG.fullmatch(reg):
                findings.append(
                    self.finding(
                        severity=None,
                        scope=Scope.FIELD,
                        field="supplier_gst_reg_no",
                        message=f"GST registration number {reg!r} is not well formed",
                        evidence={"supplier_gst_reg_no": reg},
                    )
                )

        no_gst_due = _out_of_scope_at_zero(ctx)

        # 2. Rate matches the invoice date.
        if no_gst_due:
            pass  # 0% is right for a foreign invoice from an out-of-scope vendor
        elif invoice.gst_rate_percent is not None and invoice.invoice_date is not None:
            expected = gst_rate_for_date(self._config, invoice.invoice_date)
            if expected is not None and invoice.gst_rate_percent != expected:
                findings.append(
                    self.finding(
                        severity=None,
                        scope=Scope.FIELD,
                        field="gst_rate",
                        message=(
                            f"GST rate {fmt_percent(invoice.gst_rate_percent)} does not match "
                            f"the {fmt_percent(expected)} rate for "
                            f"{invoice.invoice_date.isoformat()}"
                        ),
                        evidence={
                            "invoice_date": invoice.invoice_date.isoformat(),
                            "expected": fmt_percent(expected),
                            "found": fmt_percent(invoice.gst_rate_percent),
                        },
                    )
                )
        elif invoice.gst_rate_percent is None and invoice.gst_amount not in (None, Decimal("0")):
            findings.append(
                self.finding(
                    severity=None,
                    scope=Scope.FIELD,
                    field="gst_rate",
                    message="GST amount is present but the GST rate is missing",
                )
            )

        # 3. GST equals rate x net, allowing rounding.
        if (
            invoice.subtotal is not None
            and invoice.gst_amount is not None
            and invoice.gst_rate_percent is not None
        ):
            tol = cfg_decimal(self._config["tolerances"], "gst_amount")
            rate = invoice.gst_rate_percent
            if subtotal_includes_gst(invoice, tol):
                expected_gst = money(invoice.total * rate / (Decimal("100") + rate))
            else:
                expected_gst = money(invoice.subtotal * rate / Decimal("100"))
            if abs(invoice.gst_amount - expected_gst) > tol:
                findings.append(
                    self.finding(
                        severity=None,
                        scope=Scope.FIELD,
                        field="gst_amount",
                        message=(
                            f"GST should be {expected_gst:.2f} at "
                            f"{fmt_percent(invoice.gst_rate_percent)}, but the invoice reads "
                            f"{invoice.gst_amount:.2f}"
                        ),
                        evidence={
                            "subtotal": fmt2(invoice.subtotal),
                            "rate_percent": fmt_percent(invoice.gst_rate_percent),
                            "expected_gst": fmt2(expected_gst),
                            "gst_amount": fmt2(invoice.gst_amount),
                        },
                    )
                )

        # 4. Simplified tax invoice: capped total, GST charged, "price includes GST".
        if invoice.document_type is DocType.SIMPLIFIED_TAX_INVOICE:
            limit = cfg_decimal(self._config, "simplified_invoice_max_total")
            if invoice.total is not None and invoice.total > limit:
                findings.append(
                    self.finding(
                        severity=None,
                        scope=Scope.DOCUMENT,
                        message=(
                            f"Simplified tax invoice total {invoice.total:.2f} exceeds the "
                            f"S${limit:.2f} limit"
                        ),
                        evidence={
                            "total": fmt2(invoice.total),
                            "limit": fmt2(limit),
                        },
                    )
                )
            if invoice.gst_amount is None or invoice.gst_amount == Decimal("0"):
                findings.append(
                    self.finding(
                        severity=None,
                        scope=Scope.FIELD,
                        field="gst_amount",
                        message="Simplified tax invoice must charge GST",
                    )
                )
            if not invoice.gst_inclusive:
                findings.append(
                    self.finding(
                        severity=None,
                        scope=Scope.DOCUMENT,
                        message='Simplified tax invoice must state "price includes GST"',
                    )
                )

        # 5. Foreign-currency invoices show the SGD amounts.
        if invoice.currency and invoice.currency.upper() != "SGD":
            if invoice.sgd_total is None:
                findings.append(
                    self.finding(
                        severity=None,
                        scope=Scope.FIELD,
                        field="sgd_total",
                        message="Foreign-currency invoice must show the SGD total",
                    )
                )
            if invoice.gst_amount is not None and invoice.sgd_gst_amount is None and not no_gst_due:
                findings.append(
                    self.finding(
                        severity=None,
                        scope=Scope.FIELD,
                        field="sgd_gst_amount",
                        message="Foreign-currency invoice must show the SGD GST amount",
                    )
                )

        return tuple(findings)
