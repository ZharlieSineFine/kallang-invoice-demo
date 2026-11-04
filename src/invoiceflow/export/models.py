"""Plain value objects for the export pipeline (no contracts changes needed)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from invoiceflow.contracts import CodingLine, NormalizedInvoice, Vendor


@dataclass(frozen=True)
class ExportDocument:
    """One approved invoice with its coding lines, ready to be exported."""

    doc_id: UUID
    invoice: NormalizedInvoice
    vendor: Vendor
    coding_lines: tuple[CodingLine, ...]


@dataclass(frozen=True)
class ExportRowPlan:
    """Where one document's rows sit in the CSV (``first_row_no`` is 1-based, no header)."""

    doc_id: UUID
    first_row_no: int
    row_count: int
