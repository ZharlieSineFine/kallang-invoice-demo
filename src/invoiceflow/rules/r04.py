"""R04: vendor is in the master, and the invoice is addressed to a Kallang entity."""

from __future__ import annotations

from invoiceflow.contracts import CheckContext, Finding, Scope, Severity
from invoiceflow.rules.base import BaseRule, fuzzy_score


class R04(BaseRule):
    rule_id = "R04"

    def check(self, ctx: CheckContext) -> tuple[Finding, ...]:
        invoice = ctx.invoice
        if invoice is None:
            return ()
        findings: list[Finding] = []

        # Unknown vendor holds the document.
        if ctx.vendor is None:
            findings.append(
                self.finding(
                    severity=Severity.HOLD,
                    scope=Scope.DOCUMENT,
                    message=(
                        f"Vendor {invoice.supplier_name or '(unnamed)'} is not in the vendor master"
                    ),
                    evidence={
                        "supplier_name": invoice.supplier_name or "",
                        "supplier_uen": invoice.supplier_uen or "",
                        "supplier_gst_reg_no": invoice.supplier_gst_reg_no or "",
                    },
                )
            )

        # The addressee must be a Kallang entity (company.yaml entity_names).
        threshold = float(self._config["fuzzy_match_min_score"])
        names = ctx.master.company.entity_names
        if not invoice.buyer_name:
            findings.append(
                self.finding(
                    severity=Severity.FLAG,
                    scope=Scope.FIELD,
                    field="buyer_name",
                    message="The invoice has no addressee",
                )
            )
        else:
            best = max((fuzzy_score(invoice.buyer_name, name) for name in names), default=0.0)
            if best < threshold:
                findings.append(
                    self.finding(
                        severity=Severity.FLAG,
                        scope=Scope.FIELD,
                        field="buyer_name",
                        message=(
                            f"Invoice is addressed to {invoice.buyer_name!r}, not a Kallang entity"
                        ),
                        evidence={
                            "buyer_name": invoice.buyer_name,
                            "best_match_score": f"{best:.0f}",
                        },
                    )
                )

        return tuple(findings)
