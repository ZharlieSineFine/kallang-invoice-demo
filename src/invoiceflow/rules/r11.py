"""R11: dates — not in the future, not too old, due date on/after invoice date, and
day/month unambiguous for the vendor locale."""

from __future__ import annotations

from invoiceflow.contracts import CheckContext, Finding, Scope
from invoiceflow.rules.base import BaseRule


class R11(BaseRule):
    rule_id = "R11"

    def check(self, ctx: CheckContext) -> tuple[Finding, ...]:
        invoice = ctx.invoice
        if invoice is None:
            return ()
        findings: list[Finding] = []
        max_age = int(self._config["max_invoice_age_days"])
        today = ctx.today
        inv_date = invoice.invoice_date

        if inv_date is not None:
            if inv_date > today:
                findings.append(
                    self.finding(
                        severity=None,
                        scope=Scope.FIELD,
                        field="invoice_date",
                        message=f"Invoice date {inv_date.isoformat()} is in the future",
                        evidence={
                            "invoice_date": inv_date.isoformat(),
                            "today": today.isoformat(),
                        },
                    )
                )
            elif (today - inv_date).days > max_age:
                findings.append(
                    self.finding(
                        severity=None,
                        scope=Scope.FIELD,
                        field="invoice_date",
                        message=(
                            f"Invoice date {inv_date.isoformat()} is older than {max_age} days"
                        ),
                        evidence={
                            "invoice_date": inv_date.isoformat(),
                            "today": today.isoformat(),
                            "age_days": str((today - inv_date).days),
                        },
                    )
                )

        if inv_date is not None and invoice.due_date is not None and invoice.due_date < inv_date:
            findings.append(
                self.finding(
                    severity=None,
                    scope=Scope.FIELD,
                    field="due_date",
                    message=(
                        f"Due date {invoice.due_date.isoformat()} is before the invoice "
                        f"date {inv_date.isoformat()}"
                    ),
                    evidence={
                        "invoice_date": inv_date.isoformat(),
                        "due_date": invoice.due_date.isoformat(),
                    },
                )
            )

        # The normalizer (WS4) records fields whose day/month could be swapped.
        for field in invoice.ambiguous_dates:
            findings.append(
                self.finding(
                    severity=None,
                    scope=Scope.FIELD,
                    field=field,
                    message=f"{field} is ambiguous: day and month could be swapped",
                    evidence={"field": field},
                )
            )

        return tuple(findings)
