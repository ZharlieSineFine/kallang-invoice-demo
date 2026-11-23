"""R02: arithmetic — line amounts, lines vs subtotal, subtotal + GST vs total."""

from __future__ import annotations

from decimal import Decimal

from invoiceflow.contracts import CheckContext, Finding, Scope, money, money_sum
from invoiceflow.rules.base import (
    BaseRule,
    cfg_decimal,
    fmt2,
    money_sgd,
    subtotal_includes_gst,
)
from invoiceflow.rules.line_hint import Figures, line_message


class R02(BaseRule):
    rule_id = "R02"

    def check(self, ctx: CheckContext) -> tuple[Finding, ...]:
        invoice = ctx.invoice
        if invoice is None:
            return ()
        tolerances = self._config["tolerances"]
        line_tol = cfg_decimal(tolerances, "line_amount")
        lines_tol = cfg_decimal(tolerances, "lines_vs_subtotal")
        total_tol = cfg_decimal(tolerances, "subtotal_plus_gst")
        findings: list[Finding] = []
        figures = Figures(
            line_amounts=tuple(i.amount for i in invoice.line_items if i.amount is not None),
            subtotal=invoice.subtotal,
            gst_amount=invoice.gst_amount,
            total=invoice.total,
            gst_rate=invoice.gst_rate_percent,
            gst_inclusive=invoice.gst_inclusive,
            lines_tolerance=lines_tol,
            total_tolerance=total_tol,
            gst_tolerance=cfg_decimal(tolerances, "gst_amount"),
        )

        # quantity x unit_price (x days for rental lines) equals the line amount.
        for idx, item in enumerate(invoice.line_items):
            if item.quantity is None or item.unit_price is None or item.amount is None:
                continue
            factor = item.days if item.days is not None else Decimal("1")
            expected = money(item.quantity * item.unit_price * factor)
            if abs(expected - item.amount) > line_tol:
                findings.append(
                    self.finding(
                        severity=None,
                        scope=Scope.FIELD,
                        field=f"line_items[{idx}].amount",
                        message=line_message(
                            idx,
                            quantity=item.quantity,
                            unit_price=item.unit_price,
                            days=item.days,
                            expected=expected,
                            amount=item.amount,
                            figures=figures,
                        ),
                        evidence={
                            "line_no": str(idx + 1),
                            "expected": fmt2(expected),
                            "amount": fmt2(item.amount),
                        },
                    )
                )

        # The lines add up to the subtotal.
        if invoice.subtotal is not None:
            lines_sum = money_sum(
                item.amount for item in invoice.line_items if item.amount is not None
            )
            if abs(lines_sum - invoice.subtotal) > lines_tol:
                findings.append(
                    self.finding(
                        severity=None,
                        scope=Scope.FIELD,
                        field="subtotal",
                        message=(
                            f"The line items add up to {money_sgd(lines_sum)}, "
                            f"but the subtotal reads {money_sgd(invoice.subtotal)}."
                        ),
                        evidence={
                            "lines_sum": fmt2(lines_sum),
                            "subtotal": fmt2(invoice.subtotal),
                        },
                    )
                )

        # Subtotal + GST equals the total.
        if (
            invoice.subtotal is not None
            and invoice.gst_amount is not None
            and invoice.total is not None
            and not subtotal_includes_gst(invoice, total_tol)
        ):
            expected_total = money(invoice.subtotal + invoice.gst_amount)
            if abs(expected_total - invoice.total) > total_tol:
                findings.append(
                    self.finding(
                        severity=None,
                        scope=Scope.FIELD,
                        field="total",
                        message=(
                            f"Subtotal {money_sgd(invoice.subtotal)} + GST "
                            f"{money_sgd(invoice.gst_amount)} gives "
                            f"{money_sgd(expected_total)}, but the total reads "
                            f"{money_sgd(invoice.total)}."
                        ),
                        evidence={
                            "subtotal": fmt2(invoice.subtotal),
                            "gst_amount": fmt2(invoice.gst_amount),
                            "expected_total": fmt2(expected_total),
                            "total": fmt2(invoice.total),
                        },
                    )
                )

        return tuple(findings)
