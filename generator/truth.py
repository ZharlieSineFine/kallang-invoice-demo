"""Turn a document plan into the printed extraction, normalized invoice, coding, and truth."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from generator.money import (
    Totals,
    compute_totals,
    fmt_money,
    fmt_plain,
    fmt_rate,
    format_bank_account,
)
from generator.plans import DocumentPlan
from generator.seeds import Seeds, VendorSeed
from invoiceflow.contracts import (
    CodingLine,
    CodingMaster,
    CodingSource,
    CompanyProfile,
    DocType,
    ExtractedLineItem,
    InvoiceExtraction,
    InvoiceTruth,
    MasterData,
    NormalizedInvoice,
    NormalizedLineItem,
)
from invoiceflow.settings import load_config

_TITLES: dict[DocType, str] = {
    DocType.TAX_INVOICE: "TAX INVOICE",
    DocType.SIMPLIFIED_TAX_INVOICE: "SIMPLIFIED TAX INVOICE",
    DocType.INVOICE: "INVOICE",
    DocType.CREDIT_NOTE: "CREDIT NOTE",
    DocType.STATEMENT: "STATEMENT OF ACCOUNT",
    DocType.DEBIT_NOTE: "DEBIT NOTE",
}


def document_title(plan: DocumentPlan) -> str:
    return _TITLES[plan.doc_type]


def company_profile() -> CompanyProfile:
    company = load_config("company")
    return CompanyProfile(
        company_code=company["company_code"],
        currency=company["currency"],
        timezone=company["timezone"],
        entity_names=tuple(company["entity_names"]),
    )


def build_master(seeds: Seeds) -> MasterData:
    return seeds.master(company=company_profile())


def vendor_for(plan: DocumentPlan, seeds: Seeds) -> VendorSeed:
    if plan.supplier_override is not None:
        return plan.supplier_override
    if plan.vendor_id is None:
        raise ValueError(f"{plan.document_id} has no supplier")
    return seeds.vendor(plan.vendor_id)


def totals_for(plan: DocumentPlan) -> Totals:
    if plan.doc_type is DocType.STATEMENT:
        total = sum((row.amount for row in plan.statement_rows), Decimal("0"))
        return Totals(
            net=Decimal("0"), printed_subtotal=Decimal("0"), gst=Decimal("0"), total=total
        )
    return compute_totals(
        tuple(line.amount for line in plan.lines),
        gst_rate_percent=plan.gst_rate_percent,
        simplified=plan.simplified,
        total_override=plan.total_override,
    )


def printed_date(plan: DocumentPlan, value: date) -> str:
    pattern = "%m/%d/%Y" if plan.locale.upper() == "US" else "%d/%m/%Y"
    return value.strftime(pattern)


def bank_account(plan: DocumentPlan, vendor: VendorSeed) -> tuple[str, str]:
    """Return (printed, digits-only) for the account in the footer."""
    digits = plan.bank_account_override or vendor.bank_account
    return format_bank_account(digits), digits


def _line_items(plan: DocumentPlan) -> tuple[ExtractedLineItem, ...]:
    items = []
    for index, line in enumerate(plan.lines, start=1):
        items.append(
            ExtractedLineItem(
                line_no=str(index),
                description=line.description,
                quantity=fmt_plain(line.quantity),
                unit=line.unit,
                days=fmt_plain(line.days) if line.days is not None else None,
                unit_price=fmt_money(line.unit_price),
                amount=fmt_money(line.amount),
            )
        )
    return tuple(items)


def _normalized_lines(plan: DocumentPlan) -> tuple[NormalizedLineItem, ...]:
    return tuple(
        NormalizedLineItem(
            line_no=index,
            description=line.description,
            quantity=line.quantity,
            unit=line.unit,
            days=line.days,
            unit_price=line.unit_price,
            amount=line.amount,
        )
        for index, line in enumerate(plan.lines, start=1)
    )


def printed_extraction(plan: DocumentPlan, seeds: Seeds) -> InvoiceExtraction:
    vendor = vendor_for(plan, seeds)
    totals = totals_for(plan)
    account_printed, _ = bank_account(plan, vendor)
    is_statement = plan.doc_type is DocType.STATEMENT
    is_credit = plan.doc_type is DocType.CREDIT_NOTE
    gst_reg = None if plan.omit_gst_reg else vendor.gst_reg_no
    return InvoiceExtraction(
        document_type=plan.doc_type,
        title=_TITLES[plan.doc_type],
        invoice_number=plan.invoice_number,
        invoice_date=printed_date(plan, plan.invoice_date),
        due_date=printed_date(plan, plan.due_date) if plan.due_date else None,
        payment_terms=None if (is_statement or is_credit or not plan.due_date) else "30 days",
        currency=plan.currency,
        supplier_name=vendor.name,
        supplier_address=vendor.address,
        supplier_uen=vendor.uen or None,
        supplier_gst_reg_no=gst_reg or None,
        buyer_name="The Kallang Group",
        buyer_address="Kallang, Singapore",
        po_number=plan.po_number,
        venue=plan.venue,
        service_period=plan.service_period,
        subtotal=None if is_statement else fmt_money(totals.printed_subtotal),
        gst_rate=None if is_statement else fmt_rate(plan.gst_rate_percent),
        gst_amount=None if is_statement else fmt_money(totals.gst),
        total=fmt_money(totals.total),
        gst_inclusive_note="Price payable includes GST" if plan.simplified else None,
        sgd_total=fmt_money(plan.sgd_total) if plan.sgd_total is not None else None,
        sgd_gst_amount=(
            fmt_money(plan.sgd_gst_amount) if plan.sgd_gst_amount is not None else None
        ),
        bank_name=vendor.bank_name or None,
        bank_account=account_printed,
        original_invoice_ref=plan.original_invoice_ref,
        line_items=() if is_statement else _line_items(plan),
    )


def normalized_invoice(plan: DocumentPlan, seeds: Seeds) -> NormalizedInvoice:
    vendor = vendor_for(plan, seeds)
    totals = totals_for(plan)
    _, account_digits = bank_account(plan, vendor)
    is_statement = plan.doc_type is DocType.STATEMENT
    ambiguous = ("invoice_date", "due_date") if plan.locale.upper() == "US" else ()
    return NormalizedInvoice(
        document_type=plan.doc_type,
        invoice_number=plan.invoice_number,
        invoice_date=plan.invoice_date,
        due_date=plan.due_date,
        currency=plan.currency,
        supplier_name=vendor.name,
        supplier_uen=vendor.uen or None,
        supplier_gst_reg_no=None if plan.omit_gst_reg else (vendor.gst_reg_no or None),
        buyer_name="The Kallang Group",
        po_number=plan.po_number,
        venue=plan.venue,
        subtotal=None if is_statement else totals.net,
        gst_rate_percent=None if is_statement else plan.gst_rate_percent,
        gst_amount=None if is_statement else totals.gst,
        total=totals.total,
        gst_inclusive=plan.simplified,
        sgd_total=plan.sgd_total,
        sgd_gst_amount=plan.sgd_gst_amount,
        bank_account=account_digits,
        original_invoice_ref=plan.original_invoice_ref,
        line_items=() if is_statement else _normalized_lines(plan),
        ambiguous_dates=ambiguous,
    )


def expected_coding(plan: DocumentPlan, seeds: Seeds) -> tuple[CodingLine, ...]:
    if plan.doc_type is DocType.STATEMENT:
        return ()
    vendor = vendor_for(plan, seeds)
    totals = totals_for(plan)
    tax_code = plan.tax_code_override or vendor.default_tax_code

    if plan.po_number:
        po = seeds.purchase_order(plan.po_number)
        gl_account, cost_center = po.gl_account, po.cost_center
        source = CodingSource.PO
        suffix = f", PO {po.po_number}"
    else:
        venue_center = seeds.cost_center_for_venue(plan.venue)
        gl_account = vendor.default_gl
        tax_code = tax_code or "TX"
        if venue_center:
            cost_center = venue_center
            source = CodingSource.VENUE
            suffix = f", {plan.venue}"
        else:
            cost_center = vendor.default_cost_center
            source = CodingSource.VENDOR_DEFAULT
            suffix = ""

    description = f"{seeds.gl_name(gl_account)}{suffix}"
    return (
        CodingLine(
            line_no=1,
            gl_account=gl_account or None,
            cost_center=cost_center or None,
            tax_code=tax_code or None,
            net_amount=totals.net,
            tax_amount=totals.gst,
            description=description,
            source_line_nos=tuple(range(1, len(plan.lines) + 1)),
            coding_source=source,
        ),
    )


def build_truth(plan: DocumentPlan, seeds: Seeds) -> InvoiceTruth:
    return InvoiceTruth(
        document_id=plan.document_id,
        doc_type=plan.doc_type,
        template_id=plan.template,
        set_name=plan.set_name,
        printed=printed_extraction(plan, seeds),
        invoice=normalized_invoice(plan, seeds),
        vendor_id=plan.vendor_id,
        expected_coding=expected_coding(plan, seeds),
        anomalies=plan.anomalies,
        expected_rules=plan.expected_rules,
    )


def coding_master(seeds: Seeds) -> CodingMaster:
    return CodingMaster(
        gl_accounts=seeds.gl_accounts,
        cost_centers=seeds.cost_centers,
        tax_codes=seeds.tax_codes,
        venue_aliases=seeds.venue_aliases,
    )


def write_master(path: Path, seeds: Seeds) -> MasterData:
    """Write the master data the pipeline should see (active vendors only)."""
    master = build_master(seeds)
    path.write_text(
        json.dumps(master.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return master
