"""Placeholder stages that replay the golden fixtures. Each workstream replaces one:

GoldenTextExtractor -> WS2, GoldenLLMClient -> WS3 (its ReplayClient is the real version),
GoldenVendorMatcher / GoldenNormalizer / GoldenLocator -> WS4, GoldenCoder -> WS8,
GoldenFindingsRule / SeverityRouter -> WS5.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from invoiceflow.contracts import (
    CheckContext,
    CodingLine,
    CodingMaster,
    Confidence,
    DocStatus,
    DocType,
    ExtractionRequest,
    ExtractionResult,
    FieldConfidence,
    FieldLocation,
    FileKind,
    Finding,
    InvoiceExtraction,
    MatchType,
    NormalizationResult,
    NormalizedInvoice,
    ParsedDocument,
    PurchaseOrder,
    RoutingDecision,
    Scope,
    Severity,
    Vendor,
    max_severity,
)
from invoiceflow.pipeline.golden import GoldenSet
from invoiceflow.pipeline.stages import PipelineDeps, sha256_file

_LINE_BAND = 0.006  # words whose vertical centers are this close sit on one line
_NOT_INVOICES = {DocType.STATEMENT, DocType.QUOTATION, DocType.DELIVERY_ORDER, DocType.OTHER}
_STATUS_BY_SEVERITY = {
    Severity.FLAG: DocStatus.NEEDS_REVIEW,
    Severity.HOLD: DocStatus.ON_HOLD,
    Severity.MANUAL: DocStatus.MANUAL_ENTRY,
}
_CONFIDENCE_BY_MATCH = {
    MatchType.EXACT: Confidence.HIGH,
    MatchType.NUMERIC: Confidence.HIGH,
    MatchType.FUZZY: Confidence.MEDIUM,
    MatchType.NONE: Confidence.LOW,
}


def _id_key(value: str | None) -> str:
    return re.sub(r"[^0-9A-Z]", "", (value or "").upper())


@dataclass(frozen=True)
class GoldenTextExtractor:
    golden: GoldenSet

    def parse(self, path: Path, *, file_id: UUID, doc_id: UUID) -> ParsedDocument:
        fixture = self.golden.by_sha(sha256_file(path))
        return ParsedDocument(
            doc_id=doc_id, file_id=file_id, file_kind=FileKind.PDF, pages=(fixture.page,)
        )

    def page_texts(self, document: ParsedDocument) -> tuple[str, ...]:
        texts = []
        for page in document.pages:
            ordered = sorted(
                page.visible_words,
                key=lambda w: (round((w.bbox.y0 + w.bbox.y1) / 2 / _LINE_BAND), w.bbox.x0),
            )
            texts.append(" ".join(w.text for w in ordered))
        return tuple(texts)


@dataclass(frozen=True)
class GoldenLLMClient:
    golden: GoldenSet

    def extract(self, request: ExtractionRequest) -> ExtractionResult:
        fixture = self.golden.matching_text("\n".join(request.page_texts))
        return fixture.extraction.model_copy(update={"doc_id": request.doc_id})


@dataclass(frozen=True)
class GoldenVendorMatcher:
    def match(self, extraction: InvoiceExtraction, vendors: tuple[Vendor, ...]) -> Vendor | None:
        key = _id_key(extraction.supplier_gst_reg_no or extraction.supplier_uen)
        return next((v for v in vendors if key and _id_key(v.gst_reg_no) == key), None)


@dataclass(frozen=True)
class GoldenNormalizer:
    golden: GoldenSet

    def to_normalized(
        self, extraction: InvoiceExtraction, vendor: Vendor | None
    ) -> NormalizationResult:
        fixture = self.golden.by_invoice_number(extraction.invoice_number)
        return NormalizationResult(invoice=fixture.truth.invoice)


@dataclass(frozen=True)
class GoldenCoder:
    golden: GoldenSet

    def assign(
        self,
        invoice: NormalizedInvoice,
        vendor: Vendor | None,
        po: PurchaseOrder | None,
        master: CodingMaster,
    ) -> tuple[CodingLine, ...]:
        return self.golden.by_invoice_number(invoice.invoice_number).truth.expected_coding


@dataclass(frozen=True)
class GoldenLocator:
    golden: GoldenSet

    def locate(
        self, document: ParsedDocument, extraction: InvoiceExtraction
    ) -> tuple[FieldLocation, ...]:
        return self.golden.by_invoice_number(extraction.invoice_number).locations


@dataclass(frozen=True)
class GoldenFindingsRule:
    """Returns each fixture's expected findings. Stands in for R01-R12."""

    golden: GoldenSet

    @property
    def id(self) -> str:
        return "R00"

    def check(self, ctx: CheckContext) -> tuple[Finding, ...]:
        if ctx.invoice is None:
            return ()
        return self.golden.by_invoice_number(ctx.invoice.invoice_number).expected_findings


@dataclass(frozen=True)
class SeverityRouter:
    """Highest severity decides; confidence comes from the match and the flags."""

    auto_approve_clean: bool = True

    def route(self, ctx: CheckContext, findings: tuple[Finding, ...]) -> RoutingDecision:
        flagged = {f.field for f in findings if f.scope is Scope.FIELD and f.field}
        confidences = tuple(
            FieldConfidence(
                field=loc.field,
                confidence=Confidence.LOW
                if loc.field in flagged
                else _CONFIDENCE_BY_MATCH[loc.match_type],
            )
            for loc in ctx.locations
        )
        reasons = tuple(
            f"{f.rule_id}: {f.message}" for f in findings if f.severity.rank >= Severity.FLAG.rank
        )
        return RoutingDecision(
            status=self._status(ctx, findings), reasons=reasons, confidences=confidences
        )

    def _status(self, ctx: CheckContext, findings: tuple[Finding, ...]) -> DocStatus:
        if ctx.invoice is None:
            return DocStatus.MANUAL_ENTRY
        if ctx.invoice.document_type in _NOT_INVOICES:
            return DocStatus.NOT_INVOICE
        worst = max_severity(tuple(f.severity for f in findings))
        if worst is None or worst is Severity.INFO:
            return DocStatus.AUTO_PASSED if self.auto_approve_clean else DocStatus.NEEDS_REVIEW
        return _STATUS_BY_SEVERITY[worst]


def golden_deps(golden: GoldenSet, *, auto_approve_clean: bool = True) -> PipelineDeps:
    return PipelineDeps(
        text_extractor=GoldenTextExtractor(golden),
        llm_client=GoldenLLMClient(golden),
        vendor_matcher=GoldenVendorMatcher(),
        normalizer=GoldenNormalizer(golden),
        coder=GoldenCoder(golden),
        locator=GoldenLocator(golden),
        rules=(GoldenFindingsRule(golden),),
        router=SeverityRouter(auto_approve_clean=auto_approve_clean),
    )
