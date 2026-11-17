"""Frozen view models the pages render. They are built from SQL rows, never mutated."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from invoiceflow.contracts import (
    BBox,
    CodingSource,
    Confidence,
    DocStatus,
    DocType,
    LLMMode,
    MatchType,
    ReviewAction,
    Scope,
    Severity,
    Stage,
    ValueSource,
)


@dataclass(frozen=True)
class FindingRow:
    rule_id: str
    field: str | None
    severity: Severity
    scope: Scope
    message: str
    evidence: dict[str, str] = field(default_factory=dict)
    stage: Stage = Stage.INTAKE
    run_id: str | None = None
    rule_version: str | None = None


@dataclass(frozen=True)
class ReviewRow:
    action: ReviewAction
    reviewer: str
    field: str | None
    old_value: str | None
    new_value: str | None
    comment: str | None
    created_at: datetime


@dataclass(frozen=True)
class FieldRow:
    name: str
    value_raw: str | None
    value_norm: str | None
    page_no: int | None = None
    bbox: BBox | None = None
    match_type: MatchType = MatchType.NONE
    match_score: float = 0.0
    confidence: Confidence = Confidence.LOW
    source: ValueSource = ValueSource.MODEL


@dataclass(frozen=True)
class LineItemRow:
    line_no: int
    description: str | None = None
    quantity: Decimal | None = None
    unit: str | None = None
    days: Decimal | None = None
    unit_price: Decimal | None = None
    amount: Decimal | None = None
    source: ValueSource = ValueSource.MODEL


@dataclass(frozen=True)
class CodingRow:
    line_no: int
    gl_account: str | None
    cost_center: str | None
    tax_code: str | None
    net_amount: Decimal
    tax_amount: Decimal
    description: str | None
    coding_source: CodingSource
    source_line_nos: tuple[int, ...] = ()


@dataclass(frozen=True)
class PageRow:
    page_no: int
    image_path: str | None
    words_path: str | None
    width_pt: float
    height_pt: float
    ocr_mean_conf: float | None = None


@dataclass(frozen=True)
class ExtractionInfo:
    extraction_id: UUID
    model: str
    model_digest: str | None
    prompt_version: str
    schema_version: str
    mode: LLMMode
    valid: bool
    error: str | None
    latency_ms: int | None
    created_at: datetime
    raw_output: str | None = None
    parsed: dict[str, Any] | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    images_sent: int | None = None  # page images sent with the text (params.n_images)

    @property
    def replay(self) -> bool:
        return self.mode is LLMMode.REPLAY


@dataclass(frozen=True)
class EventRow:
    event_id: int
    ts: datetime
    actor: str
    type: str
    payload: dict[str, Any] = field(default_factory=dict)


# Statuses a document has while intake is still working on it (saved before the model runs).
PROCESSING_STATUSES = frozenset({DocStatus.RECEIVED, DocStatus.PARSED, DocStatus.EXTRACTED})


@dataclass(frozen=True)
class DocumentSummary:
    doc_id: UUID
    status: DocStatus
    status_reason: str | None = None
    doc_type: DocType | None = None
    vendor_id: str | None = None
    vendor_name: str | None = None
    invoice_number: str | None = None
    supplier_name: str | None = None
    total: Decimal | None = None
    received_at: datetime | None = None
    is_replay: bool = False
    finding_count: int = 0
    highest_severity: Severity | None = None
    open_rules: tuple[str, ...] = ()
    first_page_image: str | None = None
    extraction_valid: bool | None = None
    printed_title: str | None = None
    file_name: str | None = None
    file_path: str | None = None  # the stored upload (bronze), shown until page images exist
    is_audit_sample: bool = False  # picked for the random audit of auto-passed invoices
    audit_result: str | None = None  # "passed" or "error" once a person has checked it

    @property
    def is_processing(self) -> bool:
        return self.status in PROCESSING_STATUSES

    @property
    def label(self) -> str:
        number = self.invoice_number or "no invoice number"
        vendor = self.vendor_name or self.supplier_name or "unknown vendor"
        return f"{number} — {vendor} ({self.status.value})"


@dataclass(frozen=True)
class AuditSummary:
    """The random audit of auto-passed invoices (CR-012), counted from the audit events."""

    percent: Decimal | None  # the configured share; None when no audit is configured
    picked: int = 0
    checked: int = 0
    with_error: int = 0
    error_fields: tuple[tuple[str, int], ...] = ()  # (field, audits that found it wrong)


@dataclass(frozen=True)
class DiscardedCopy:
    """A file intake discarded because its bytes match a file already stored.

    The copy's name, arrival time and fingerprint come from the discard event; the kept
    original and its fingerprint come from the stored file it matched."""

    name: str | None
    arrived_at: datetime | None
    sha256: str
    kept_sha256: str
    original: DocumentSummary

    @property
    def is_identical(self) -> bool:
        return self.sha256 == self.kept_sha256


@dataclass(frozen=True)
class DocumentBundle:
    document: DocumentSummary
    fields: tuple[FieldRow, ...] = ()
    line_items: tuple[LineItemRow, ...] = ()
    coding_lines: tuple[CodingRow, ...] = ()
    findings: tuple[FindingRow, ...] = ()
    reviews: tuple[ReviewRow, ...] = ()
    pages: tuple[PageRow, ...] = ()
    extraction: ExtractionInfo | None = None
    events: tuple[EventRow, ...] = ()

    def field(self, name: str) -> FieldRow | None:
        return next((f for f in self.fields if f.name == name), None)

    @property
    def flagged_fields(self) -> frozenset[str]:
        return frozenset(
            f.field for f in self.findings if f.scope is Scope.FIELD and f.field is not None
        )


@dataclass(frozen=True)
class ReviewOutcome:
    doc_id: UUID
    status: DocStatus
    message: str
    findings: tuple[FindingRow, ...] = ()
    run_id: str | None = None

    @property
    def blocked(self) -> bool:
        return bool(self.findings)


@dataclass(frozen=True)
class CheckCount:
    rule_id: str
    severity: Severity
    count: int


@dataclass(frozen=True)
class CountRow:
    key: str
    count: int


@dataclass(frozen=True)
class EvaluationSummary:
    path: str
    generated_at: str | None
    set_name: str
    document_count: int | None
    metrics: dict[str, float]
    raw: dict[str, Any]
    synthetic: bool = True


@dataclass(frozen=True)
class DashboardData:
    total_documents: int = 0
    auto_passed: int = 0
    needs_review: int = 0
    approved: int = 0
    rejected: int = 0
    on_hold: int = 0
    auto_pass_rate: float = 0.0
    findings_by_check: tuple[CheckCount, ...] = ()
    avg_seconds_per_invoice: float | None = None
    corrections_by_field: tuple[CountRow, ...] = ()
    corrections_by_vendor: tuple[CountRow, ...] = ()
    hold_count: int = 0
    total_value: Decimal = Decimal("0.00")
    latest_evaluation: EvaluationSummary | None = None


@dataclass(frozen=True)
class BatchSummary:
    batch_id: str
    created_at: datetime
    csv_path: str
    row_count: int
    total: Decimal
    layout: str
    mapping_version: str
    doc_ids: tuple[UUID, ...] = ()
    csv_sha256: str | None = None
    manifest: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TraceData:
    bundle: DocumentBundle
    finding_history: tuple[FindingRow, ...] = ()
    runs: tuple[str, ...] = ()
