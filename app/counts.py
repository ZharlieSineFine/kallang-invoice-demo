"""One count of what came in, shared by every page (user's report, 2026-11-20).

The Queue listed a non-invoice under Discarded while the flow strip still counted only the
copies, so two pages gave two numbers. Every page now counts from here:

- received: every stored document plus every byte-identical copy intake discarded
- discarded: those copies plus the documents the model read as not an invoice
- invoices: the rest, including any still being read

so received = discarded + invoices on every page.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.models import DocumentSummary
from invoiceflow.contracts import DocStatus


@dataclass(frozen=True)
class IntakeCounts:
    documents: int  # stored documents, including any still being read
    copies: int  # byte-identical copies intake discarded; they were never stored
    not_invoices: int

    @property
    def received(self) -> int:
        return self.documents + self.copies

    @property
    def discarded(self) -> int:
        return self.copies + self.not_invoices

    @property
    def invoices(self) -> int:
        return self.documents - self.not_invoices

    @property
    def breakdown(self) -> str:
        """What the discarded ones are, e.g. "1 copy of a file already in, 2 not invoices"."""
        parts = []
        if self.copies:
            parts.append(
                "1 copy of a file already in"
                if self.copies == 1
                else f"{self.copies} copies of files already in"
            )
        if self.not_invoices:
            many = f"{self.not_invoices} not invoices"
            parts.append("1 not an invoice" if self.not_invoices == 1 else many)
        return ", ".join(parts)


def is_invoice(doc: DocumentSummary) -> bool:
    return doc.status is not DocStatus.NOT_INVOICE


def intake_counts(docs: Sequence[DocumentSummary], copies: int) -> IntakeCounts:
    return IntakeCounts(
        documents=len(docs),
        copies=copies,
        not_invoices=sum(not is_invoice(doc) for doc in docs),
    )
