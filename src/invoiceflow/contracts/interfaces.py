"""Boundaries between workstreams. Each Protocol names the workstream that implements it.

The pipeline (WS6, then the integrator) only ever calls these, so a stub can be swapped
for the real implementation without touching the pipeline.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

from invoiceflow.contracts.enums import DocStatus, DocType
from invoiceflow.contracts.models import (
    BronzeFile,
    CheckContext,
    CodingLine,
    CodingMaster,
    DocumentRecord,
    ExportBatch,
    ExtractionRequest,
    ExtractionResult,
    FieldLocation,
    FieldValue,
    Finding,
    InvoiceExtraction,
    MasterData,
    NormalizationResult,
    NormalizedInvoice,
    NormalizedLineItem,
    ParsedDocument,
    PriorInvoice,
    PurchaseOrder,
    Review,
    RoutingDecision,
    Vendor,
)


@runtime_checkable
class TextExtractor(Protocol):
    """WS2. Reads a file into words with boxes; marks hidden words."""

    def parse(self, path: Path, *, file_id: UUID, doc_id: UUID) -> ParsedDocument: ...

    def page_texts(self, document: ParsedDocument) -> tuple[str, ...]:
        """Reading-order text per page, hidden words left out. This is what the model reads."""
        ...


@runtime_checkable
class LLMClient(Protocol):
    """WS3. Live (Ollama), replay (cache), or Azure OpenAI later."""

    def extract(self, request: ExtractionRequest) -> ExtractionResult: ...


@runtime_checkable
class VendorMatcher(Protocol):
    """WS4. GST number or UEN first, then fuzzy name match."""

    def match(
        self, extraction: InvoiceExtraction, vendors: tuple[Vendor, ...]
    ) -> Vendor | None: ...


@runtime_checkable
class Normalizer(Protocol):
    """WS4. Converts printed strings to Decimal, dates, and clean IDs."""

    def to_normalized(
        self, extraction: InvoiceExtraction, vendor: Vendor | None
    ) -> NormalizationResult: ...


@runtime_checkable
class Coder(Protocol):
    """WS8. Assigns GL account, cost center, and tax code (build plan section 5.5)."""

    def assign(
        self,
        invoice: NormalizedInvoice,
        vendor: Vendor | None,
        po: PurchaseOrder | None,
        master: CodingMaster,
    ) -> tuple[CodingLine, ...]: ...


@runtime_checkable
class Locator(Protocol):
    """WS4. Finds each extracted value on the page; ignores hidden words."""

    def locate(
        self, document: ParsedDocument, extraction: InvoiceExtraction
    ) -> tuple[FieldLocation, ...]: ...


@runtime_checkable
class Rule(Protocol):
    """WS5. One check, R01-R12. Pure: reads the context, returns findings."""

    @property
    def id(self) -> str: ...

    def check(self, ctx: CheckContext) -> tuple[Finding, ...]: ...


@runtime_checkable
class Router(Protocol):
    """WS5. Turns findings into a status and per-field confidence."""

    def route(self, ctx: CheckContext, findings: tuple[Finding, ...]) -> RoutingDecision: ...


@runtime_checkable
class BlobStore(Protocol):
    """WS6. Bronze is write-once and content-addressed."""

    def put_bronze(self, data: bytes, original_name: str) -> tuple[str, str]:
        """Store original bytes; returns (sha256, path). Same bytes, same path."""
        ...

    def read(self, path: str) -> bytes: ...

    def put_silver(self, doc_id: UUID, name: str, data: bytes) -> str: ...

    def put_gold(self, batch_id: str, name: str, data: bytes) -> str: ...


@runtime_checkable
class Repository(Protocol):
    """WS6. Postgres access. Saving fields, lines, or coding marks the previous rows
    not current and adds new ones; nothing is updated in place."""

    def register_file(self, file: BronzeFile) -> bool:
        """True if new; False if a file with the same sha256 already exists."""
        ...

    def unfinished_document(self, sha256: str) -> tuple[UUID, UUID] | None:
        """``(doc_id, file_id)`` of this file's RECEIVED document, if intake stopped midway."""
        ...

    def discard_document(self, doc_id: UUID, file_id: UUID) -> None:
        """Remove a RECEIVED document and its file row; never one with an outcome."""
        ...

    def create_document(self, record: DocumentRecord) -> None: ...

    def set_document_meta(
        self, doc_id: UUID, doc_type: DocType | None, vendor_id: str | None
    ) -> None: ...

    def stored_invoice(self, doc_id: UUID) -> NormalizedInvoice | None: ...

    def get_document(self, doc_id: UUID) -> DocumentRecord | None: ...

    def set_status(self, doc_id: UUID, status: DocStatus, reason: str | None) -> None: ...

    def list_documents(self, statuses: tuple[DocStatus, ...]) -> tuple[DocumentRecord, ...]: ...

    def save_parsed(self, document: ParsedDocument) -> None: ...

    def save_extraction(self, result: ExtractionResult) -> None: ...

    def save_fields(
        self,
        doc_id: UUID,
        fields: tuple[FieldValue, ...],
        line_items: tuple[NormalizedLineItem, ...],
    ) -> None: ...

    def save_coding(self, doc_id: UUID, lines: tuple[CodingLine, ...]) -> None: ...

    def save_findings(self, doc_id: UUID, run_id: str, findings: tuple[Finding, ...]) -> None: ...

    def add_review(self, review: Review) -> None: ...

    def load_master(self) -> MasterData: ...

    def prior_invoices(self, vendor_id: str | None) -> tuple[PriorInvoice, ...]: ...

    def approved_not_exported(self) -> tuple[UUID, ...]: ...

    def record_export(
        self,
        batch: ExportBatch,
        doc_ids: tuple[UUID, ...],
        manifest: Mapping[str, Any] | None = None,
    ) -> None:
        """One transaction. Raises if any doc_id was exported before."""
        ...

    def log_event(
        self, actor: str, event_type: str, doc_id: UUID | None, payload: Mapping[str, Any]
    ) -> None: ...
