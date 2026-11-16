"""Turn the model's printed strings into a ``NormalizedInvoice``.

The normalizer is pure and deterministic. A value it cannot convert becomes ``None`` and a
human-readable problem is added; it never raises and never guesses silently.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

from invoiceflow.contracts import (
    InvoiceExtraction,
    NormalizationResult,
    NormalizedInvoice,
    NormalizedLineItem,
    Vendor,
)
from invoiceflow.normalize.amounts import normalize_amount, normalize_percent, parse_amount
from invoiceflow.normalize.currency import infer_currency, normalize_currency
from invoiceflow.normalize.dates import normalize_date
from invoiceflow.normalize.ids import normalized_labeled_id
from invoiceflow.normalize.text import clean_reference, clean_text, normalize_text

_INTEGER = re.compile(r"^(\d+)(?:\.0*)?$")


def _is_blank(value: str | None) -> bool:
    return clean_text(value) is None


def _money(value: str | None, field: str, problems: list[str]) -> Decimal | None:
    if _is_blank(value):
        return None
    amount = normalize_amount(value)
    if amount is None:
        problems.append(f"{field}: could not parse {value!r} as an amount")
    return amount


def _plain_decimal(value: str | None, field: str, problems: list[str]) -> Decimal | None:
    if _is_blank(value):
        return None
    amount = parse_amount(value)
    if amount is None:
        problems.append(f"{field}: could not parse {value!r} as a number")
    return amount


def _date(
    value: str | None, field: str, locale: str, ambiguous: list[str], problems: list[str]
) -> date | None:
    if _is_blank(value):
        return None
    parsed, is_ambiguous = normalize_date(value, locale=locale)
    if parsed is None:
        problems.append(f"{field}: could not parse {value!r} as a date")
    elif is_ambiguous:
        ambiguous.append(field)
    return parsed


def _text(value: str | None) -> str | None:
    return clean_text(value)


def _identifier(value: str | None) -> str | None:
    return normalized_labeled_id(value)


def _bank_account(value: str | None, problems: list[str]) -> str | None:
    if _is_blank(value):
        return None
    digits = re.sub(r"\D", "", value or "")
    if not digits:
        problems.append(f"bank_account: could not find digits in {value!r}")
        return None
    return digits


def gst_inclusive_from_note(note: str | None) -> bool:
    """Whether a printed GST note says the amounts already include GST."""
    text = normalize_text(note)
    if not text:
        return False
    if any(marker in text for marker in ("exclusive", "not included", "excl. gst", "no gst")):
        return False
    return any(
        marker in text
        for marker in ("inclusive", "included", "includes gst", "incl. gst", "incl gst")
    )


def _currency(extraction: InvoiceExtraction, vendor: Vendor | None) -> str | None:
    direct = normalize_currency(extraction.currency)
    if direct is not None:
        return direct
    inferred = infer_currency(
        extraction.subtotal,
        extraction.gst_amount,
        extraction.total,
        extraction.amount_due,
    )
    if inferred is not None:
        return inferred
    return normalize_currency(vendor.currency) if vendor is not None else None


def _line_no(raw: str | None, fallback: int, index: int, problems: list[str]) -> int:
    if _is_blank(raw):
        return fallback
    match = _INTEGER.fullmatch((clean_text(raw) or "").strip())
    if match is None:
        problems.append(f"line_items[{index}].line_no: could not parse {raw!r} as a line number")
        return fallback
    number = int(match.group(1))
    if number < 1:
        problems.append(f"line_items[{index}].line_no: {number} is not a positive line number")
        return fallback
    return number


def _line_items(
    extraction: InvoiceExtraction, problems: list[str]
) -> tuple[NormalizedLineItem, ...]:
    items: list[NormalizedLineItem] = []
    for index, item in enumerate(extraction.line_items):
        prefix = f"line_items[{index}]"
        items.append(
            NormalizedLineItem(
                line_no=_line_no(item.line_no, index + 1, index, problems),
                description=_text(item.description),
                quantity=_plain_decimal(item.quantity, f"{prefix}.quantity", problems),
                unit=_text(item.unit),
                days=_plain_decimal(item.days, f"{prefix}.days", problems),
                unit_price=_money(item.unit_price, f"{prefix}.unit_price", problems),
                amount=_money(item.amount, f"{prefix}.amount", problems),
            )
        )
    return _unique_line_numbers(tuple(items), problems)


def _unique_line_numbers(
    items: tuple[NormalizedLineItem, ...], problems: list[str]
) -> tuple[NormalizedLineItem, ...]:
    """Line numbers identify lines in review and export, so a repeat is renumbered by position.

    A noisy scan can make the model split one printed line in two, both carrying its number.
    """
    numbers = [item.line_no for item in items]
    if len(set(numbers)) == len(numbers):
        return items
    problems.append(f"line_items: line numbers repeat ({numbers}); numbered by position instead")
    return tuple(
        item.model_copy(update={"line_no": position})
        for position, item in enumerate(items, start=1)
    )


def to_normalized(extraction: InvoiceExtraction, vendor: Vendor | None) -> NormalizationResult:
    """Convert every printable value, collecting conversion problems instead of raising."""
    problems: list[str] = []
    ambiguous: list[str] = []
    locale = vendor.locale if vendor is not None else "SG"

    gst_rate = None
    if not _is_blank(extraction.gst_rate):
        gst_rate = normalize_percent(extraction.gst_rate)
        if gst_rate is None:
            problems.append(f"gst_rate: could not parse {extraction.gst_rate!r} as a percentage")

    invoice = NormalizedInvoice(
        document_type=extraction.document_type,
        invoice_number=clean_reference(extraction.invoice_number),
        invoice_date=_date(extraction.invoice_date, "invoice_date", locale, ambiguous, problems),
        due_date=_date(extraction.due_date, "due_date", locale, ambiguous, problems),
        currency=_currency(extraction, vendor),
        supplier_name=_text(extraction.supplier_name),
        supplier_uen=_identifier(extraction.supplier_uen),
        supplier_gst_reg_no=_identifier(extraction.supplier_gst_reg_no),
        buyer_name=_text(extraction.buyer_name),
        po_number=_identifier(extraction.po_number),
        contract_number=_identifier(extraction.contract_number),
        venue=_text(extraction.venue),
        subtotal=_money(extraction.subtotal, "subtotal", problems),
        discount=_money(extraction.discount, "discount", problems),
        gst_rate_percent=gst_rate,
        gst_amount=_money(extraction.gst_amount, "gst_amount", problems),
        total=_money(extraction.total, "total", problems),
        amount_due=_money(extraction.amount_due, "amount_due", problems),
        gst_inclusive=gst_inclusive_from_note(extraction.gst_inclusive_note),
        sgd_total=_money(extraction.sgd_total, "sgd_total", problems),
        sgd_gst_amount=_money(extraction.sgd_gst_amount, "sgd_gst_amount", problems),
        bank_account=_bank_account(extraction.bank_account, problems),
        original_invoice_ref=_identifier(extraction.original_invoice_ref),
        line_items=_line_items(extraction, problems),
        ambiguous_dates=tuple(ambiguous),
    )
    return NormalizationResult(invoice=invoice, problems=tuple(problems))


class Normalizer:
    """The ``Normalizer`` protocol implementation."""

    def to_normalized(
        self, extraction: InvoiceExtraction, vendor: Vendor | None
    ) -> NormalizationResult:
        return to_normalized(extraction, vendor)
