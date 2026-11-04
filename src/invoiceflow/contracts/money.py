"""Money is Decimal everywhere, rounded half-up to cents. Never float."""

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    """Round a Decimal to two places, half-up. Floats are refused on purpose."""
    if not isinstance(value, Decimal):
        raise TypeError(f"money() needs a Decimal, got {type(value).__name__}")
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def money_sum(values: Iterable[Decimal]) -> Decimal:
    return money(sum(values, Decimal("0")))
