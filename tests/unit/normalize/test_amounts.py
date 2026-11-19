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


def test_a_percent_has_one_spelling():
    # "9%", "9.0%" and "9.00 %" are one rate, so they are stored the same way (2026-11-19).
    for printed in ("9%", "9.0%", "9.00 %"):
        assert format(normalize_percent(printed), "f") == "9"
    assert format(normalize_percent("10.0%"), "f") == "10"
    assert format(normalize_percent("8.50%"), "f") == "8.5"
