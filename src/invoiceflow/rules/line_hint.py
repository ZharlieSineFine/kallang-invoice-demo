"""The message for a line whose quantity x unit price (x days) is not its amount.

Shared by R02 at intake and the review-time recheck (``app.recheck``), so both say the same.
The message shows the arithmetic, and when the printed amounts, subtotal, GST and total all
agree with each other it says to check the line's quantity and unit price first (user's
approval, 2026-11-20). On KSS-2026-8202 the model read the quantity as 720 for the printed
120; without the hint the flags led the reviewer to raise the amount, subtotal and total.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from invoiceflow.contracts import money, money_sum
from invoiceflow.contracts.money import plain_decimal
from invoiceflow.rules.base import money_sgd

HINT = (
    "The subtotal, GST and total agree with each other, so check this line's quantity and "
    "unit price on the page first."
)
DAYS_HINT = (  # a line with days, e.g. a rental (user, 2026-11-24)
    "The subtotal, GST and total agree with each other, so check this line's quantity, "
    "unit price and days on the page first."
)


@dataclass(frozen=True)
class Figures:
    """The invoice's other figures, to see whether they back up the printed amount."""

    line_amounts: Sequence[Decimal]
    subtotal: Decimal | None
    gst_amount: Decimal | None
    total: Decimal | None
    gst_rate: Decimal | None = None  # percent, e.g. 9
    gst_inclusive: bool = False
    lines_tolerance: Decimal = Decimal("0.05")  # rules.yaml tolerances.lines_vs_subtotal
    total_tolerance: Decimal = Decimal("0.01")  # tolerances.subtotal_plus_gst
    gst_tolerance: Decimal = Decimal("0.05")  # tolerances.gst_amount


def _number(value: Decimal) -> str:
    return format(plain_decimal(value), "f")


def _arithmetic(quantity: Decimal, unit_price: Decimal, days: Decimal | None) -> str:
    parts = [_number(quantity), f"{unit_price:.2f}"]
    if days is not None:
        parts.append(f"{_number(days)} days")
    return " \u00d7 ".join(parts)


def figures_agree(figures: Figures) -> bool:
    """The amounts add up to the subtotal, subtotal + GST is the total, and the GST is the
    rate of the subtotal (when a rate was read)."""
    subtotal, gst, total = figures.subtotal, figures.gst_amount, figures.total
    if subtotal is None or gst is None or total is None or not figures.line_amounts:
        return False
    if abs(money_sum(figures.line_amounts) - subtotal) > figures.lines_tolerance:
        return False
    inclusive = figures.gst_inclusive and abs(subtotal - total) <= figures.total_tolerance
    if not inclusive and abs(money(subtotal + gst) - total) > figures.total_tolerance:
        return False
    if figures.gst_rate is None:
        return True
    rate = figures.gst_rate
    if inclusive:
        expected = money(total * rate / (Decimal("100") + rate))
    else:
        expected = money(subtotal * rate / Decimal("100"))
    return abs(expected - gst) <= figures.gst_tolerance


def line_message(
    index: int,
    *,
    quantity: Decimal,
    unit_price: Decimal,
    days: Decimal | None,
    expected: Decimal,
    amount: Decimal,
    figures: Figures,
) -> str:
    message = (
        f"Line {index + 1} works out to {money_sgd(expected)} "
        f"({_arithmetic(quantity, unit_price, days)}), "
        f"but the amount reads {money_sgd(amount)}."
    )
    if not figures_agree(figures):
        return message
    return f"{message} {HINT if days is None else DAYS_HINT}"
