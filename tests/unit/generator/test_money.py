"""Money rules: Decimal only, half-up cents, GST on the subtotal."""

from decimal import Decimal

import pytest

from generator.money import (
    compute_totals,
    digits_only,
    fmt_money,
    fmt_plain,
    fmt_rate,
    format_bank_account,
    money,
)


def test_money_rounds_half_up():
    assert money(Decimal("1.005")) == Decimal("1.01")
    assert money(Decimal("1.004")) == Decimal("1.00")
    assert money(Decimal("-1.005")) == Decimal("-1.01")


def test_money_refuses_float():
    with pytest.raises(TypeError, match="Decimal"):
        money(1.23)  # type: ignore[arg-type]


def test_standard_totals_add_gst_to_subtotal():
    totals = compute_totals(
        (Decimal("540.00"), Decimal("300.00"), Decimal("160.00"), Decimal("80.00")),
        gst_rate_percent=Decimal("9"),
    )
    assert totals.net == Decimal("1080.00")
    assert totals.printed_subtotal == Decimal("1080.00")
    assert totals.gst == Decimal("97.20")
    assert totals.total == Decimal("1177.20")
    assert totals.gross == totals.total


def test_simplified_totals_back_out_the_included_gst():
    totals = compute_totals((Decimal("850.00"),), gst_rate_percent=Decimal("9"), simplified=True)
    assert totals.printed_subtotal == Decimal("850.00")
    assert totals.total == Decimal("850.00")
    assert totals.net == Decimal("779.82")
    assert totals.gst == Decimal("70.18")
    assert totals.net + totals.gst == totals.total


def test_credit_note_is_negative_and_consistent():
    totals = compute_totals((Decimal("-540.00"), Decimal("-300.00")), gst_rate_percent=Decimal("9"))
    assert totals.net == Decimal("-840.00")
    assert totals.gst == Decimal("-75.60")
    assert totals.total == Decimal("-915.60")


def test_total_override_only_changes_the_total():
    totals = compute_totals(
        (Decimal("1080.00"),),
        gst_rate_percent=Decimal("9"),
        total_override=Decimal("1090.00"),
    )
    assert totals.printed_subtotal == Decimal("1080.00")
    assert totals.gst == Decimal("97.20")
    assert totals.total == Decimal("1090.00")


def test_empty_document_is_refused():
    with pytest.raises(ValueError, match="at least one line"):
        compute_totals((), gst_rate_percent=Decimal("9"))


def test_float_rate_is_refused():
    with pytest.raises(TypeError, match="Decimal"):
        compute_totals((Decimal("1.00"),), gst_rate_percent=9)  # type: ignore[arg-type]


def test_formatting_helpers():
    assert fmt_money(Decimal("1080")) == "1,080.00"
    assert fmt_money(Decimal("-75.6")) == "-75.60"
    assert fmt_plain(Decimal("4.0")) == "4"
    assert fmt_plain(Decimal("1.50")) == "1.5"
    assert fmt_rate(Decimal("9")) == "9%"
    assert fmt_rate(Decimal("0")) == "0%"


def test_bank_account_helpers():
    assert format_bank_account("0001234567") == "000-123456-7"
    assert format_bank_account("12345") == "12345"
    assert digits_only("000-123456-7") == "0001234567"
