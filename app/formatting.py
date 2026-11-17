"""Small pure helpers shared by the pages: parsing, formatting, labels."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from functools import cache
from zoneinfo import ZoneInfo

from dateutil import parser as date_parser

from invoiceflow.contracts import CodingSource, Confidence, DocStatus, Severity, money
from invoiceflow.settings import load_config

MONEY_FIELDS = frozenset(
    {
        "subtotal",
        "discount",
        "gst_amount",
        "total",
        "amount_due",
        "sgd_total",
        "sgd_gst_amount",
    }
)
DATE_FIELDS = frozenset({"invoice_date", "due_date"})
RATE_FIELDS = frozenset({"gst_rate"})

_AMOUNT = re.compile(r"^[+-]?(?:\d[\d,\s]*)(?:\.\d+)?$")
_CURRENCY_PREFIX = re.compile(r"^(?:S\$|SGD|USD|EUR|GBP|\$)\s*", re.IGNORECASE)


def md_escape(text: str) -> str:
    """Make plain text safe inside Streamlit markdown.

    Streamlit renders ``$...$`` pairs as LaTeX math, so a finding message like
    ``add up to S$1,080.00, but ... S$1,090.00`` would be typeset as a math span in a
    funny italic font. Escaping the dollar signs keeps them literal (Streamlit honours
    ``\\$``); the data itself stays unchanged.
    """
    return text.replace("$", "\\$")


def parse_decimal(raw: str | None) -> Decimal | None:
    """Parse a printed amount (``S$1,080.00``) into a Decimal. Never uses float."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    text = _CURRENCY_PREFIX.sub("", text).strip()
    text = text.replace(",", "").replace(" ", "")
    if text.endswith("%"):
        text = text[:-1]
    if not _AMOUNT.match(text):
        raise ValueError(f"not an amount: {raw!r}")
    try:
        value = Decimal(text)
    except InvalidOperation as exc:  # pragma: no cover - guarded by the regex
        raise ValueError(f"not an amount: {raw!r}") from exc
    return money(-value if negative else value)


def normalize_field_value(name: str, raw: str | None) -> str | None:
    """Convert what the reviewer typed into the stored ``value_norm`` representation."""
    if raw is None:
        return None
    if name in MONEY_FIELDS:
        value = parse_decimal(raw)
        return None if value is None else format(value, "f")
    if name in RATE_FIELDS:
        value = parse_decimal(raw)
        return None if value is None else format(value, "f")
    if name in DATE_FIELDS:
        text = raw.strip()
        if not text:
            return None
        try:
            return date_parser.parse(text, dayfirst=True).date().isoformat()
        except (ValueError, OverflowError) as exc:
            raise ValueError(f"not a date: {raw!r}") from exc
    text = raw.strip()
    return text or None


def format_money(value: Decimal | None, *, currency: str = "S$") -> str:
    if value is None:
        return "—"
    return f"{currency}{money(value):,.2f}"


def format_date(value: date | None) -> str:
    return value.isoformat() if value else "—"


_ZONE_LABELS = {"Asia/Singapore": "SGT"}


@cache
def _company_zone() -> ZoneInfo:
    return ZoneInfo(str(load_config("company").get("timezone", "Asia/Singapore")))


def format_time(value: datetime | None) -> str:
    """A stored time (UTC in the database) in the company's time zone, e.g. 10:37:03 SGT."""
    if value is None:
        return "—"
    zone = _company_zone()
    local = value.astimezone(zone) if value.tzinfo is not None else value
    label = _ZONE_LABELS.get(zone.key, zone.key)
    return f"{local:%Y-%m-%d %H:%M:%S} {label}"


def source_label(source: CodingSource) -> str:
    return {
        CodingSource.PO: "PO rule",
        CodingSource.VENUE: "Venue alias",
        CodingSource.VENDOR_DEFAULT: "Vendor default",
        CodingSource.REVIEWER: "Reviewer",
        CodingSource.NONE: "Uncoded",
    }[source]


def confidence_label(confidence: Confidence) -> str:
    return confidence.value.title()


def severity_color(severity: Severity | None) -> str:
    return {
        None: "#2e7d32",
        Severity.INFO: "#1565c0",
        Severity.FLAG: "#c62828",
        Severity.HOLD: "#ef6c00",
        Severity.MANUAL: "#6a1b9a",
    }[severity]


def status_tone(status: DocStatus) -> str:
    if status in {DocStatus.AUTO_PASSED, DocStatus.APPROVED, DocStatus.EXPORTED}:
        return "green"
    if status in {DocStatus.NEEDS_REVIEW, DocStatus.MANUAL_ENTRY}:
        return "orange"
    if status is DocStatus.ON_HOLD:
        return "red"
    if status is DocStatus.REJECTED:
        return "gray"
    return "blue"


def safe_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def safe_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def percent(numerator: int, denominator: int) -> float:
    return 0.0 if denominator <= 0 else 100.0 * numerator / denominator
