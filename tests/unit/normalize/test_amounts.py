from decimal import Decimal

import pytest

from invoiceflow.normalize import normalize_amount, normalize_percent, parse_amount


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("S$1,090.00", Decimal("1090.00")),
        ("S$ 1,090.00", Decimal("1090.00")),
        ("SGD 1,090.00", Decimal("1090.00")),
        ("1 090.00", Decimal("1090.00")),
        ("1,090", Decimal("1090.00")),
        ("1090", Decimal("1090.00")),
        ("$1,090.00", Decimal("1090.00")),
        ("(1,090.00)", Decimal("-1090.00")),
        ("-1,090.00", Decimal("-1090.00")),
        ("1,090.00-", Decimal("-1090.00")),
        ("S$ 0.05", Decimal("0.05")),
    ],
)
def test_normalize_amount_accepts_singapore_money_forms(raw, expected):
    assert normalize_amount(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "not an amount", "1,2,3.00", "9%", "31/10/2026", "M2-1234567-8"],
)
def test_invalid_amounts_are_none(raw):
    assert normalize_amount(raw) is None


def test_parse_amount_keeps_precision():
    assert parse_amount("1,090.005") == Decimal("1090.005")
    assert normalize_amount("1,090.005") == Decimal("1090.01")
    assert parse_amount("+1,090.00") == Decimal("1090.00")
    assert parse_amount(None) is None


def test_percent_parsing():
    assert normalize_percent("9%") == Decimal("9")
    assert normalize_percent("9.00 %") == Decimal("9.00")
    assert normalize_percent("0%") == Decimal("0")
    assert normalize_percent("GST") is None
    assert normalize_percent("9,00%") is None
    assert normalize_percent(None) is None
