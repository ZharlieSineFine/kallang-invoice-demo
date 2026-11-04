"""Frozen data models shared by every workstream (Phase 0 contracts, tag contracts-v1).

Rules that hold everywhere:
- Boxes are fractions of the page (0-1), measured from the top-left corner.
- The model returns strings exactly as printed (InvoiceExtraction); Python converts them
  (NormalizedInvoice).
- Money and quantities are Decimal; floats are refused.
- Sequences are tuples, so a model can't be changed after it is built.
- ``dict`` fields (evidence, params, rules_config) are read-only by convention.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from invoiceflow.contracts.enums import (
    CodingSource,
    Confidence,
    DocStatus,
    DocType,
    FileKind,
    LLMMode,
    MatchType,
    ReviewAction,
    Scope,
    Severity,
    Stage,
    TextSource,
    ValueSource,
)
from invoiceflow.contracts.money import money


def _reject_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("use Decimal or a string for amounts, never float")
    return value


Dec = Annotated[Decimal, BeforeValidator(_reject_float)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --------------------------------------------------------------------------- pages


class BBox(Contract):
    x0: float = Field(ge=0, le=1)
    y0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _ordered(self) -> BBox:
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError("bbox needs x0 <= x1 and y0 <= y1")
        return self

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    def union(self, other: BBox) -> BBox:
        return BBox(
            x0=min(self.x0, other.x0),
            y0=min(self.y0, other.y0),
            x1=max(self.x1, other.x1),
            y1=max(self.y1, other.y1),
        )


class Word(Contract):
    text: str
    bbox: BBox
    conf: float | None = None  # OCR confidence 0-100; None for PDF text
    hidden: bool = False  # white, tiny, or off-page text: kept as evidence, never prompted


class PageText(Contract):
    page_no: int = Field(ge=1)
    width_pt: float = Field(gt=0)
    height_pt: float = Field(gt=0)
    source: TextSource
    words: tuple[Word, ...] = ()
    image_path: str | None = None  # page PNG for the review screen
    ocr_mean_conf: float | None = None

    @property
    def visible_words(self) -> tuple[Word, ...]:
        return tuple(w for w in self.words if not w.hidden)


class ParsedDocument(Contract):
    doc_id: UUID
    file_id: UUID
    file_kind: FileKind
    pages: tuple[PageText, ...]

    @property
    def hidden_words(self) -> tuple[tuple[int, Word], ...]:
        return tuple((p.page_no, w) for p in self.pages for w in p.words if w.hidden)


# --------------------------------------------------------------------- extraction


class ExtractedLineItem(Contract):
    """One printed invoice line, values exactly as printed."""

    line_no: str | None = None
    description: str | None = None
    quantity: str | None = None
    unit: str | None = None
    days: str | None = None  # rental days (type A)
    unit_price: str | None = None
    amount: str | None = None


class InvoiceExtraction(Contract):
    """What the model returns. Every value is a string exactly as printed, or null.

    This class's JSON schema is the structured-output schema sent to the model.
    """

    document_type: DocType | None = None
    title: str | None = None
    invoice_number: str | None = None
    invoice_date: str | None = None
    due_date: str | None = None
    payment_terms: str | None = None
    currency: str | None = None
    supplier_name: str | None = None
    supplier_address: str | None = None
    supplier_uen: str | None = None
    supplier_gst_reg_no: str | None = None
    buyer_name: str | None = None
    buyer_address: str | None = None
    po_number: str | None = None
    contract_number: str | None = None
    venue: str | None = None
    service_period: str | None = None
    subtotal: str | None = None
    discount: str | None = None
    gst_rate: str | None = None
    gst_amount: str | None = None
    total: str | None = None
    amount_due: str | None = None
    gst_inclusive_note: str | None = None  # e.g. "Price payable includes GST"
    sgd_total: str | None = None  # foreign-currency invoices: total shown in SGD
    sgd_gst_amount: str | None = None
    bank_name: str | None = None
    bank_account: str | None = None
    original_invoice_ref: str | None = None  # credit notes
    line_items: tuple[ExtractedLineItem, ...] = ()


HEADER_FIELDS: tuple[str, ...] = tuple(
    name for name in InvoiceExtraction.model_fields if name not in {"document_type", "line_items"}
)

# PINT SG business terms (InvoiceNow), so records can later be filled from e-invoices.
PINT_SG_TERMS: dict[str, str] = {
    "invoice_number": "IBT-001",
    "invoice_date": "IBT-002",
    "currency": "IBT-005",
    "due_date": "IBT-009",
    "contract_number": "IBT-012",
    "po_number": "IBT-013",
    "payment_terms": "IBT-020",
    "supplier_name": "IBT-027",
    "supplier_uen": "IBT-030",
    "supplier_gst_reg_no": "IBT-031",
    "buyer_name": "IBT-044",
    "bank_account": "IBT-084",
    "subtotal": "IBT-109",
    "gst_amount": "IBT-110",
    "total": "IBT-112",
    "amount_due": "IBT-115",
    "line_items": "IBG-25",
}


class ExtractionRequest(Contract):
    doc_id: UUID
    page_texts: tuple[str, ...]  # reading-order text per page, hidden words removed
    image_paths: tuple[str, ...] = ()  # page images, sent for scans


class ExtractionResult(Contract):
    extraction_id: UUID
    doc_id: UUID
    model: str
    model_digest: str | None = None
    prompt_version: str
    schema_version: str
    params: dict[str, Any] = Field(default_factory=dict)
    mode: LLMMode
    raw_output: str
    extraction: InvoiceExtraction | None = None  # None when the output was invalid
    valid: bool
    error: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: int | None = None
    created_at: datetime

    @model_validator(mode="after")
    def _valid_has_extraction(self) -> ExtractionResult:
        if self.valid and self.extraction is None:
            raise ValueError("a valid result needs an extraction")
        return self


# ------------------------------------------------------------------ normalized


class NormalizedLineItem(Contract):
    line_no: int = Field(ge=1)
    description: str | None = None
    quantity: Dec | None = None
    unit: str | None = None
    days: Dec | None = None
    unit_price: Dec | None = None
    amount: Dec | None = None


class NormalizedInvoice(Contract):
    """Values converted by Python from an InvoiceExtraction."""

    document_type: DocType | None = None
    invoice_number: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    currency: str | None = None  # ISO 4217, e.g. SGD
    supplier_name: str | None = None
    supplier_uen: str | None = None
    supplier_gst_reg_no: str | None = None  # uppercase, no spaces or hyphens
    buyer_name: str | None = None
    po_number: str | None = None
    contract_number: str | None = None
    venue: str | None = None
    subtotal: Dec | None = None
    discount: Dec | None = None
    gst_rate_percent: Dec | None = None  # 9 means 9%
    gst_amount: Dec | None = None
    total: Dec | None = None
    amount_due: Dec | None = None
    gst_inclusive: bool = False
    sgd_total: Dec | None = None
    sgd_gst_amount: Dec | None = None
    bank_account: str | None = None  # digits only
    original_invoice_ref: str | None = None
    line_items: tuple[NormalizedLineItem, ...] = ()
    ambiguous_dates: tuple[str, ...] = ()  # field names whose day/month could be swapped


class NormalizationResult(Contract):
    invoice: NormalizedInvoice
    problems: tuple[str, ...] = ()  # e.g. "invoice_date: could not parse '31/02/2026'"


class FieldLocation(Contract):
    field: str  # "invoice_number" or "line_items[0].amount"
    page_no: int | None = None
    bbox: BBox | None = None
    match_type: MatchType
    score: float = Field(ge=0, le=100)
    matched_text: str | None = None


class FieldValue(Contract):
    """One stored field: what was printed, what it became, and how sure we are."""

    name: str
    value_raw: str | None
    value_norm: str | None
    page_no: int | None = None
    bbox: BBox | None = None
    match_type: MatchType = MatchType.NONE
    match_score: float = 0.0
    confidence: Confidence
    source: ValueSource


# ----------------------------------------------------------------- master data


class Vendor(Contract):
    vendor_id: str
    sap_vendor_no: str
    name: str
    uen: str | None = None
    gst_reg_no: str | None = None
    address: str | None = None
    bank_name: str | None = None
    bank_account: str | None = None  # digits only
    currency: str = "SGD"
    locale: str = "SG"  # SG reads dates day first; US month first
    is_overseas: bool = False
    default_gl: str | None = None
    default_cost_center: str | None = None
    default_tax_code: str | None = None
    active: bool = True


class PurchaseOrder(Contract):
    po_number: str
    vendor_id: str
    currency: str = "SGD"
    amount: Dec
    open_amount: Dec
    gl_account: str | None = None
    cost_center: str | None = None


class GLAccount(Contract):
    code: str
    name: str
    active: bool = True


class CostCenter(Contract):
    code: str
    name: str
    active: bool = True


class TaxCode(Contract):
    code: str
    rate_percent: Dec
    description: str


def _venue_key(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


class VenueAlias(Contract):
    alias: str
    cost_center: str


class CodingMaster(Contract):
    """Hypothetical SAP coding data (build plan section 5.5)."""

    gl_accounts: tuple[GLAccount, ...] = ()
    cost_centers: tuple[CostCenter, ...] = ()
    tax_codes: tuple[TaxCode, ...] = ()
    venue_aliases: tuple[VenueAlias, ...] = ()

    def has_gl(self, code: str) -> bool:
        return any(g.code == code and g.active for g in self.gl_accounts)

    def has_cost_center(self, code: str) -> bool:
        return any(c.code == code and c.active for c in self.cost_centers)

    def tax_rate(self, code: str) -> Decimal | None:
        return next((t.rate_percent for t in self.tax_codes if t.code == code), None)

    def cost_center_for_venue(self, venue: str) -> str | None:
        key = _venue_key(venue)
        return next((v.cost_center for v in self.venue_aliases if _venue_key(v.alias) == key), None)


class CompanyProfile(Contract):
    company_code: str
    currency: str = "SGD"
    timezone: str = "Asia/Singapore"
    entity_names: tuple[str, ...]  # names an invoice may be addressed to (R04)


class MasterData(Contract):
    company: CompanyProfile
    vendors: tuple[Vendor, ...] = ()
    purchase_orders: tuple[PurchaseOrder, ...] = ()
    coding: CodingMaster = CodingMaster()

    def vendor(self, vendor_id: str) -> Vendor | None:
        return next((v for v in self.vendors if v.vendor_id == vendor_id), None)

    def purchase_order(self, po_number: str) -> PurchaseOrder | None:
        return next((p for p in self.purchase_orders if p.po_number == po_number), None)


class PriorInvoice(Contract):
    """An invoice already in the system, for the duplicate check (R05)."""

    doc_id: UUID
    vendor_id: str | None
    invoice_number: str | None
    total: Dec | None
    invoice_date: date | None
    file_sha256: Sha256


# ---------------------------------------------------------------------- coding


class CodingLine(Contract):
    line_no: int = Field(ge=1)
    gl_account: str | None = None
    cost_center: str | None = None
    tax_code: str | None = None
    net_amount: Dec
    tax_amount: Dec
    description: str | None = None
    source_line_nos: tuple[int, ...] = ()  # the invoice lines grouped into this one
    coding_source: CodingSource

    @property
    def gross_amount(self) -> Decimal:
        return money(self.net_amount + self.tax_amount)


# -------------------------------------------------------------------- checks


class Finding(Contract):
    rule_id: str = Field(pattern=r"^R\d{2}$")
    rule_version: str  # hash of the rule's code version and its YAML config
    severity: Severity
    scope: Scope
    field: str | None = None
    message: str  # shown to finance
    evidence: dict[str, str] = Field(default_factory=dict)
    stage: Stage = Stage.INTAKE


class FieldConfidence(Contract):
    field: str
    confidence: Confidence


class RoutingDecision(Contract):
    status: DocStatus
    reasons: tuple[str, ...] = ()
    confidences: tuple[FieldConfidence, ...] = ()


class CheckContext(Contract):
    """Everything a check may read. Checks never touch the database or files."""

    doc_id: UUID
    run_id: str
    today: date
    file_sha256: Sha256
    document: ParsedDocument
    extraction: ExtractionResult
    invoice: NormalizedInvoice | None = None
    normalization_problems: tuple[str, ...] = ()
    vendor: Vendor | None = None
    purchase_order: PurchaseOrder | None = None
    coding_lines: tuple[CodingLine, ...] = ()
    locations: tuple[FieldLocation, ...] = ()
    master: MasterData
    prior_invoices: tuple[PriorInvoice, ...] = ()
    rules_config: dict[str, Any] = Field(default_factory=dict)

    def location(self, field: str) -> FieldLocation | None:
        return next((loc for loc in self.locations if loc.field == field), None)


# ------------------------------------------------------------------- records


class BronzeFile(Contract):
    file_id: UUID
    sha256: Sha256
    original_name: str
    source: str  # upload | email | folder
    sender: str | None = None
    received_at: datetime
    size_bytes: int = Field(ge=0)
    mime_type: str | None = None
    path: str


class DocumentRecord(Contract):
    doc_id: UUID
    file_id: UUID
    doc_type: DocType | None = None
    status: DocStatus
    status_reason: str | None = None
    vendor_id: str | None = None


class Review(Contract):
    doc_id: UUID
    reviewer: str = Field(min_length=1)
    action: ReviewAction
    field: str | None = None
    old_value: str | None = None
    new_value: str | None = None
    comment: str | None = None
    created_at: datetime

    @model_validator(mode="after")
    def _hold_release_needs_comment(self) -> Review:
        if self.action is ReviewAction.RELEASE_HOLD and not (self.comment or "").strip():
            raise ValueError("releasing a hold needs a comment")
        return self


class ExportBatch(Contract):
    batch_id: str
    created_at: datetime
    csv_path: str
    csv_sha256: Sha256
    row_count: int = Field(ge=0)
    total: Dec
    layout: str  # "hypothetical" until Kallang's template arrives
    mapping_version: str


# ------------------------------------------------------------------- testing


class InvoiceTruth(Contract):
    """Ground truth for one generated document (WS1 writes it, WS8 scores against it)."""

    document_id: str  # e.g. "golden-a-clean", "A1-0007"
    doc_type: DocType
    template_id: str
    set_name: str  # golden | pre | live | benchmark
    printed: InvoiceExtraction  # what a perfect extraction returns
    invoice: NormalizedInvoice  # what perfect normalization returns
    vendor_id: str | None
    expected_coding: tuple[CodingLine, ...] = ()
    anomalies: tuple[str, ...] = ()
    expected_rules: tuple[str, ...] = ()
