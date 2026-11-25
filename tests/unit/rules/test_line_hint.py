"""A line that does not work out says which figures to check (user's approval, 2026-11-20).

On KSS-2026-8202 the model read the quantity as 720 for the printed 120. The flag said only
that the line works out to S$13,680.00 but the amount reads S$2,280.00, and the reviewer
raised the amount, subtotal and total to match. The printed amounts, subtotal, GST and total
all agreed with each other, which points at the quantity or unit price instead.
"""

from __future__ import annotations

from decimal import Decimal

from invoiceflow.rules.line_hint import Figures, line_message

D = Decimal
HINT = (
    " The subtotal, GST and total agree with each other, so check this line's quantity and "
    "unit price on the page first."
)
KALLANG = Figures(
    line_amounts=(D("2280.00"),),
    subtotal=D("2280.00"),
    gst_amount=D("205.20"),
    total=D("2485.20"),
    gst_rate=D("9"),
)


def _message(figures: Figures, *, days=None) -> str:
    return line_message(
        0,
        quantity=D("720"),
        unit_price=D("19.00"),
        days=days,
        expected=D("13680.00") if days is None else D("41040.00"),
        amount=D("2280.00"),
        figures=figures,
    )


def test_the_message_shows_the_arithmetic_and_where_to_look():
    assert _message(KALLANG) == (
        "Line 1 works out to S$13,680.00 (720 \u00d7 19.00), "
        "but the amount reads S$2,280.00." + HINT
    )


def test_days_are_shown_for_a_rental_line():
    assert "(720 \u00d7 19.00 \u00d7 3 days)" in _message(KALLANG, days=D("3"))


def test_the_hint_names_days_when_the_line_has_them():
    """User, 2026-11-24: a line with days says to check its days too."""
    assert _message(KALLANG, days=D("3")).endswith(
        " The subtotal, GST and total agree with each other, so check this line's quantity, "
        "unit price and days on the page first."
    )


def test_no_hint_when_the_amounts_do_not_add_up_to_the_subtotal():
    figures = Figures(**{**KALLANG.__dict__, "subtotal": D("13680.00")})
    assert HINT not in _message(figures)


def test_no_hint_when_subtotal_plus_gst_is_not_the_total():
    figures = Figures(**{**KALLANG.__dict__, "total": D("2500.00")})
    assert HINT not in _message(figures)


def test_no_hint_when_the_gst_is_not_the_rate_of_the_subtotal():
    figures = Figures(**{**KALLANG.__dict__, "gst_amount": D("100.00"), "total": D("2380.00")})
    assert HINT not in _message(figures)


def test_no_hint_without_a_gst_amount():
    figures = Figures(**{**KALLANG.__dict__, "gst_amount": None})
    assert HINT not in _message(figures)


def test_a_missing_rate_still_allows_the_hint():
    figures = Figures(**{**KALLANG.__dict__, "gst_rate": None})
    assert _message(figures).endswith(HINT)


def test_gst_inside_an_inclusive_total_agrees():
    figures = Figures(
        line_amounts=(D("1090.00"),),
        subtotal=D("1090.00"),
        gst_amount=D("90.00"),
        total=D("1090.00"),
        gst_rate=D("9"),
        gst_inclusive=True,
    )
    assert _message(figures).endswith(HINT)
