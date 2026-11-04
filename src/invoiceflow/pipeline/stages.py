"""The intake pipeline as plain functions. No Airflow imports, so Azure Functions can call
the same code later. Every dependency arrives through PipelineDeps (contract interfaces)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

from invoiceflow.contracts import (
    CheckContext,
    Coder,
    ExtractionRequest,
    ExtractionResult,
    Finding,
    LLMClient,
    Locator,
    MasterData,
    NormalizedInvoice,
    Normalizer,
    ParsedDocument,
    PriorInvoice,
    PurchaseOrder,
    Router,
    RoutingDecision,
    Rule,
    TextExtractor,
    VendorMatcher,
)


@dataclass(frozen=True)
class PipelineDeps:
    text_extractor: TextExtractor
    llm_client: LLMClient
    vendor_matcher: VendorMatcher
    normalizer: Normalizer
    coder: Coder
    locator: Locator
    rules: tuple[Rule, ...]
    router: Router


@dataclass(frozen=True)
class CheckOutcome:
    context: CheckContext
    findings: tuple[Finding, ...]
    decision: RoutingDecision


@dataclass(frozen=True)
class ProcessResult:
    file_sha256: str
    document: ParsedDocument
    extraction: ExtractionResult
    context: CheckContext
    findings: tuple[Finding, ...]
    decision: RoutingDecision


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_stage(path: Path, *, file_id: UUID, doc_id: UUID, deps: PipelineDeps) -> ParsedDocument:
    return deps.text_extractor.parse(path, file_id=file_id, doc_id=doc_id)


def extract_stage(
    document: ParsedDocument, deps: PipelineDeps, image_paths: tuple[str, ...] = ()
) -> ExtractionResult:
    request = ExtractionRequest(
        doc_id=document.doc_id,
        page_texts=deps.text_extractor.page_texts(document),
        image_paths=image_paths,
    )
    return deps.llm_client.extract(request)


def find_purchase_order(invoice: NormalizedInvoice, master: MasterData) -> PurchaseOrder | None:
    return master.purchase_order(invoice.po_number) if invoice.po_number else None


def run_rules(rules: tuple[Rule, ...], ctx: CheckContext) -> tuple[Finding, ...]:
    return tuple(finding for rule in rules for finding in rule.check(ctx))


def check_stage(
    *,
    document: ParsedDocument,
    extraction: ExtractionResult,
    master: MasterData,
    file_sha256: str,
    deps: PipelineDeps,
    today: date,
    run_id: str,
    rules_config: dict[str, Any],
    prior_invoices: tuple[PriorInvoice, ...] = (),
) -> CheckOutcome:
    """Order: match vendor, standardize, find the PO, assign coding, locate, check, route."""
    base = {
        "doc_id": document.doc_id,
        "run_id": run_id,
        "today": today,
        "file_sha256": file_sha256,
        "document": document,
        "extraction": extraction,
        "master": master,
        "prior_invoices": prior_invoices,
        "rules_config": rules_config,
    }
    printed = extraction.extraction
    if not extraction.valid or printed is None:
        ctx = CheckContext(**base)
    else:
        vendor = deps.vendor_matcher.match(printed, master.vendors)
        normalized = deps.normalizer.to_normalized(printed, vendor)
        po = find_purchase_order(normalized.invoice, master)
        ctx = CheckContext(
            **base,
            invoice=normalized.invoice,
            normalization_problems=normalized.problems,
            vendor=vendor,
            purchase_order=po,
            coding_lines=deps.coder.assign(normalized.invoice, vendor, po, master.coding),
            locations=deps.locator.locate(document, printed),
        )
    findings = run_rules(deps.rules, ctx)
    return CheckOutcome(context=ctx, findings=findings, decision=deps.router.route(ctx, findings))


def recheck(
    *,
    doc_id: UUID,
    invoice: NormalizedInvoice | None,
    extraction: ExtractionResult,
    document: ParsedDocument,
    master: MasterData,
    coding_lines: tuple = (),
    locations: tuple = (),
    prior_invoices: tuple[PriorInvoice, ...] = (),
    rules_config: dict[str, Any],
    today: date,
    run_id: str,
    file_sha256: str = "0" * 64,
    vendor=None,
    purchase_order: PurchaseOrder | None = None,
    normalization_problems: tuple[str, ...] = (),
) -> CheckOutcome:
    """Re-run the checks on corrected, stored values (CR-002, used by the review screen).

    Unlike ``check_stage`` this re-reads nothing and re-extracts nothing: every value is
    what the caller passes, so a reviewer's correction is what the rules see. The same
    real WS5 rules and router run, so the decision matches intake semantics.
    """
    ctx = CheckContext(
        doc_id=doc_id,
        run_id=run_id,
        today=today,
        file_sha256=file_sha256,
        document=document,
        extraction=extraction,
        invoice=invoice,
        normalization_problems=normalization_problems,
        vendor=vendor,
        purchase_order=purchase_order,
        coding_lines=coding_lines,
        locations=locations,
        master=master,
        prior_invoices=prior_invoices,
        rules_config=rules_config,
    )
    from invoiceflow.pipeline.deps import build_deps

    deps = build_deps(rules_config)
    findings = run_rules(deps.rules, ctx)
    return CheckOutcome(context=ctx, findings=findings, decision=deps.router.route(ctx, findings))


def process_document(
    path: Path,
    *,
    file_id: UUID,
    doc_id: UUID,
    deps: PipelineDeps,
    master: MasterData,
    today: date,
    run_id: str,
    rules_config: dict[str, Any],
    prior_invoices: tuple[PriorInvoice, ...] = (),
) -> ProcessResult:
    """Run one file through every stage without persisting anything."""
    file_sha256 = sha256_file(path)
    document = parse_stage(path, file_id=file_id, doc_id=doc_id, deps=deps)
    extraction = extract_stage(document, deps)
    outcome = check_stage(
        document=document,
        extraction=extraction,
        master=master,
        file_sha256=file_sha256,
        deps=deps,
        today=today,
        run_id=run_id,
        rules_config=rules_config,
        prior_invoices=prior_invoices,
    )
    return ProcessResult(
        file_sha256=file_sha256,
        document=document,
        extraction=extraction,
        context=outcome.context,
        findings=outcome.findings,
        decision=outcome.decision,
    )
