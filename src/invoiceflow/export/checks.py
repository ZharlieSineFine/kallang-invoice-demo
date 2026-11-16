"""Batch checks that must all pass before a CSV is written.

Every check is pure. The database "already exported" check takes the set of previously
exported ``doc_id``s as a parameter; the caller obtains it from ``export_rows``.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from invoiceflow.contracts import CodingMaster, money, money_sum
from invoiceflow.export.mapping import SapMapping, empty_required
from invoiceflow.export.models import ExportDocument
from invoiceflow.normalize.text import invoice_number_key

_ZERO = Decimal("0")


class BatchError(Exception):
    """A batch is blocked; ``problems`` holds one clear message per failure."""

    def __init__(self, problems: tuple[str, ...]):
        self.problems = problems
        super().__init__("; ".join(problems))


def check_batch(
    mapping: SapMapping,
    rows: tuple[tuple[str, ...], ...],
    documents: tuple[ExportDocument, ...],
    master: CodingMaster,
    *,
    previously_exported: frozenset[UUID] = frozenset(),
) -> tuple[str, ...]:
    """Run every batch check and return the problems (empty means the batch is clean)."""
    problems: list[str] = []
    problems.extend(_required_columns(mapping, rows))
    problems.extend(_unique_vendor_reference(documents))
    problems.extend(_reconcile_invoices(documents))
    problems.extend(_batch_totals(documents))
    problems.extend(_master_exists(documents, master))
    problems.extend(_not_exported_before(documents, previously_exported))
    return tuple(problems)


def _required_columns(mapping: SapMapping, rows: tuple[tuple[str, ...], ...]) -> list[str]:
    problems: list[str] = []
    for row_no, row in enumerate(rows, start=1):
        missing = empty_required(mapping, row)
        if missing:
            problems.append(f"row {row_no}: required column(s) empty: {', '.join(missing)}")
    return problems


def _unique_vendor_reference(documents: tuple[ExportDocument, ...]) -> list[str]:
    seen: dict[tuple[str, str], str] = {}
    problems: list[str] = []
    for doc in documents:
        vendor_no = doc.vendor.sap_vendor_no
        reference = doc.invoice.invoice_number or ""
        # Letters and digits only, so "GSH-2026-9004" and "GSH- 2026-9004" are one reference.
        key = (vendor_no, invoice_number_key(reference))
        if key in seen:
            problems.append(
                f"vendor {vendor_no} and reference {reference!r} appears twice "
                f"({seen[key]} and {doc.doc_id})"
            )
        else:
            seen[key] = str(doc.doc_id)
    return problems


def _invoice_gross(doc: ExportDocument) -> Decimal:
    return money(
        money_sum(line.net_amount for line in doc.coding_lines)
        + money_sum(line.tax_amount for line in doc.coding_lines)
    )


def _reconcile_invoices(documents: tuple[ExportDocument, ...]) -> list[str]:
    problems: list[str] = []
    for doc in documents:
        total = doc.invoice.total
        if total is None:
            continue
        net = money_sum(line.net_amount for line in doc.coding_lines)
        tax = money_sum(line.tax_amount for line in doc.coding_lines)
        if net + tax != total:
            problems.append(
                f"invoice {doc.invoice.invoice_number or doc.doc_id}: "
                f"net {net} + tax {tax} = {net + tax}, expected gross {total}"
            )
    return problems


def _batch_totals(documents: tuple[ExportDocument, ...]) -> list[str]:
    problems: list[str] = []
    gross = money_sum(_invoice_gross(doc) for doc in documents)
    totals = money_sum(doc.invoice.total for doc in documents if doc.invoice.total is not None)
    if gross != totals:
        problems.append(f"batch total {gross} does not agree with document totals {totals}")
    return problems


def _master_exists(documents: tuple[ExportDocument, ...], master: CodingMaster) -> list[str]:
    problems: list[str] = []
    for doc in documents:
        for line in doc.coding_lines:
            if line.gl_account is None or not master.has_gl(line.gl_account):
                problems.append(
                    f"invoice {doc.invoice.invoice_number or doc.doc_id} line {line.line_no}: "
                    f"unknown GL account {line.gl_account!r}"
                )
            if line.cost_center is None or not master.has_cost_center(line.cost_center):
                problems.append(
                    f"invoice {doc.invoice.invoice_number or doc.doc_id} line {line.line_no}: "
                    f"unknown cost center {line.cost_center!r}"
                )
            if line.tax_code is None or master.tax_rate(line.tax_code) is None:
                problems.append(
                    f"invoice {doc.invoice.invoice_number or doc.doc_id} line {line.line_no}: "
                    f"unknown tax code {line.tax_code!r}"
                )
    return problems


def _not_exported_before(
    documents: tuple[ExportDocument, ...], previously_exported: frozenset[UUID]
) -> list[str]:
    return [
        f"document {doc.doc_id} was exported before"
        for doc in documents
        if doc.doc_id in previously_exported
    ]
