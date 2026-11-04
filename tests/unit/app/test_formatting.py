"""Parsing and formatting helpers used by the review actions."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.formatting import (
    confidence_label,
    format_date,
    format_money,
    normalize_field_value,
    parse_decimal,
    percent,
    safe_float,
    safe_int,
    severity_color,
    source_label,
    status_tone,
)
from invoiceflow.contracts import CodingSource, Confidence, Severity


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1,080.00", Decimal("1080.00")),
        ("S$1,177.20", Decimal("1177.20")),
        ("SGD 9", Decimal("9.00")),
        ("9%", Decimal("9.00")),
        ("(1.005)", Decimal("-1.01")),
        ("", None),
        (None, None),
    ],
)
def test_parse_decimal(raw, expected):
    assert parse_decimal(raw) == expected


def test_parse_decimal_rejects_text():
    with pytest.raises(ValueError, match="not an amount"):
        parse_decimal("not money")


def test_normalize_money_date_rate_and_text():
    assert normalize_field_value("subtotal", "1,080.00") == "1080.00"
    assert normalize_field_value("gst_rate", "9%") == "9.00"
    assert normalize_field_value("invoice_date", "15/10/2026") == "2026-10-15"
    assert normalize_field_value("invoice_number", " SAV-1 ") == "SAV-1"
    assert normalize_field_value("invoice_number", "   ") is None
    with pytest.raises(ValueError, match="not a date"):
        normalize_field_value("invoice_date", "31/02/2026")


def test_labels_and_colors():
    assert format_money(Decimal("1177.2")) == "S$1,177.20"
    assert format_money(None) == "—"
    assert format_date(None) == "—"
    assert source_label(CodingSource.PO) == "PO rule"
    assert source_label(CodingSource.REVIEWER) == "Reviewer"
    assert confidence_label(Confidence.HIGH) == "High"
    assert severity_color(Severity.FLAG) == "#c62828"
    assert severity_color(None) == "#2e7d32"


def test_status_tones():
    from invoiceflow.contracts import DocStatus

    assert status_tone(DocStatus.AUTO_PASSED) == "green"
    assert status_tone(DocStatus.NEEDS_REVIEW) == "orange"
    assert status_tone(DocStatus.ON_HOLD) == "red"
    assert status_tone(DocStatus.REJECTED) == "gray"


def test_small_numbers():
    assert safe_int("3") == 3
    assert safe_int(None) is None
    assert safe_float("1.5") == 1.5
    assert safe_float("x") is None
    assert percent(1, 4) == 25.0
    assert percent(1, 0) == 0.0


def test_md_escape_keeps_dollar_signs_literal():
    from app.formatting import md_escape

    message = "The line items add up to S$1,080.00, but the subtotal reads S$1,090.00."
    escaped = md_escape(message)
    assert escaped == (
        "The line items add up to S\\$1,080.00, but the subtotal reads S\\$1,090.00."
    )
    assert md_escape("plain text") == "plain text"
