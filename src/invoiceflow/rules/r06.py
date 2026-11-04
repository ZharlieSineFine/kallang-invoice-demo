"""R06: every SAP-required column can be filled after mapping, including GL account,
cost center, and tax code on every coding line."""

from __future__ import annotations

from invoiceflow.contracts import CheckContext, Finding, Scope
from invoiceflow.rules.base import BaseRule

# Header columns the SAP layout marks required (config/sap_mapping.yaml).
_HEADER_REQUIRED = ("invoice_number", "invoice_date", "currency", "total")

_CODING_ATTRS = (
    ("gl_account", "GL account"),
    ("cost_center", "cost center"),
    ("tax_code", "tax code"),
)


class R06(BaseRule):
    rule_id = "R06"

    def check(self, ctx: CheckContext) -> tuple[Finding, ...]:
        invoice = ctx.invoice
        if invoice is None:
            return ()
        findings: list[Finding] = []

        # SAP VendorNo needs the vendor's SAP number.
        if ctx.vendor is None or not ctx.vendor.sap_vendor_no:
            findings.append(
                self.finding(
                    severity=None,
                    scope=Scope.DOCUMENT,
                    field="sap_vendor_no",
                    message="SAP VendorNo cannot be filled (vendor missing or has no SAP number)",
                )
            )

        # Required header columns must be present.
        for name in _HEADER_REQUIRED:
            if getattr(invoice, name) is None:
                findings.append(
                    self.finding(
                        severity=None,
                        scope=Scope.FIELD,
                        field=name,
                        message=f"SAP column for {name} cannot be filled",
                    )
                )

        # Every coding line needs GL account, cost center, and tax code.
        if not ctx.coding_lines:
            findings.append(
                self.finding(
                    severity=None,
                    scope=Scope.DOCUMENT,
                    message=(
                        "No coding lines were produced; GL account, cost center, and "
                        "tax code cannot be filled"
                    ),
                )
            )
        for idx, line in enumerate(ctx.coding_lines):
            for attr, label in _CODING_ATTRS:
                if getattr(line, attr) is None:
                    findings.append(
                        self.finding(
                            severity=None,
                            scope=Scope.FIELD,
                            field=f"coding_lines[{idx}].{attr}",
                            message=f"{label} is missing on coding line {idx + 1}",
                        )
                    )

        return tuple(findings)
